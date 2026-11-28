"""Read-only, event-triggered Sidecar Auditor for autonomous drug-design campaigns.

Implements a two-layer旁路审核 (sidecar review & advisory) architecture across four
stage-gate checkpoints without polluting leaf evidence records (Hard Constraint 2) or
slowing down every tool turn:

  - **Layer A (Deterministic Zero-Token Audit):** Immediately checks hard invariants at
    ``CP1_TARGET_DATA``, ``CP2_PRE_PHYSICS``, ``CP3_RUNTIME_TELEMETRY``, and
    ``CP4_PRE_DELIVERY`` (observable mixing, HTML/reCAPTCHA disguised files, 0/2 catalog
    shortlist partners, RBFE bond-mapping mismatches, GPU/CPU lease violations, GPU
    under-utilization, and overclaimed delivery statements).
  - **Layer B (Optional Clean-Context LLM Critic):** Feeds *only* the structured
    on-disk artifacts and Layer A findings — never the primary agent's conversational
    self-justification — to an independent read-only ``Transport`` (``CodexCli``,
    ``ClaudeCli``, or ``Scripted``), parses strict JSON via ``advisor._parse``, and
    merges findings monotonically (the LLM may add ``warn``/``block`` findings or
    scientific suggestions, never downgrade a deterministic ``block``).
  - **Append-Only Resolution Ledger:** Records whether the primary agent accepted or
    rejected (with rationale) each advisory in a dedicated ``sidecar_audit.jsonl`` log.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from moldarwin.judgment.advisor import AdvisorError, Transport, _parse
from moldarwin.runtime.lease import DEFAULT_UNDERUTIL_SM_PCT, DEFAULT_UNDERUTIL_VRAM_FRAC

SIDECAR_REVIEW_SCHEMA = "moldarwin-sidecar-review/1"
SIDECAR_RESOLUTION_SCHEMA = "moldarwin-sidecar-resolution/1"

SIDECAR_CHECKPOINTS: tuple[str, ...] = (
    "CP1_TARGET_DATA",
    "CP2_PRE_PHYSICS",
    "CP3_RUNTIME_TELEMETRY",
    "CP4_PRE_DELIVERY",
)

_SEVERITY_RANK: dict[str, int] = {"info": 0, "warn": 1, "block": 2}
_VERDICT_FROM_RANK: dict[int, str] = {0: "pass", 1: "warn", 2: "block"}

_HTML_CAPTCHA_RE = re.compile(
    r"(<!doctype\s+html|<html\b|g-recaptcha|captcha|verify you are human|cloudflare)",
    re.IGNORECASE,
)
_OVERCLAIM_POTENCY_RE = re.compile(
    r"(confirmed\s+higher\s+potency|verified\s+stronger\s+binder|proven\s+superior\s+affinity|"
    r"experimentally\s+improved\s+lle|outperforms\s+crystal\s+control\s+in\s+affinity)",
    re.IGNORECASE,
)


def _finding(
    *,
    rule_id: str,
    severity: str,
    summary: str,
    recommendation: str,
    source: str = "deterministic",
    evidence_paths: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if severity not in _SEVERITY_RANK:
        raise ValueError(f"invalid severity {severity!r}; expected one of {sorted(_SEVERITY_RANK)}")
    out: dict[str, Any] = {
        "rule_id": rule_id,
        "severity": severity,
        "source": source,
        "summary": summary,
        "recommendation": recommendation,
        "evidence_paths": [str(p) for p in evidence_paths],
    }
    if details:
        out["details"] = dict(details)
    return out


def _audit_cp1_target_data(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    suggestions: list[str] = []

    # 1. Check for disguised HTML/reCAPTCHA files in downloaded inputs
    for raw in payload.get("input_file_snippets", ()):
        if not isinstance(raw, Mapping):
            continue
        fpath = str(raw.get("path") or "<unknown>")
        snippet = str(raw.get("head_text") or "")
        if _HTML_CAPTCHA_RE.search(snippet):
            findings.append(_finding(
                rule_id="CP1_HTML_OR_CAPTCHA_DISGUISED_INPUT",
                severity="block",
                summary=f"Input file {fpath} contains HTML/CAPTCHA markup instead of scientific data.",
                recommendation="Fetch verified primary data from an alternate open mirror (e.g., EBI BioStudies / RCSB / ChEMBL) and verify SHA-256.",
                evidence_paths=[fpath],
            ))

    # 2. Observable endpoint mixing (e.g., pooling Kd and IC50 into one regression)
    endpoints = [str(e).strip() for e in payload.get("assay_endpoints", ()) if str(e).strip()]
    distinct_endpoints = sorted({e.lower() for e in endpoints})
    if len(distinct_endpoints) > 1 and bool(payload.get("pooled_into_single_fit", False)):
        findings.append(_finding(
            rule_id="CP1_MIXED_OBSERVABLE_POOLING",
            severity="block",
            summary=f"Distinct experimental observables {distinct_endpoints} are pooled into a single SAR/Free-Wilson fit.",
            recommendation="Separate binding Kd/Ki from biochemical/cellular IC50 endpoints before fitting or calibration.",
            details={"endpoints": distinct_endpoints},
        ))
    elif len(distinct_endpoints) > 1:
        findings.append(_finding(
            rule_id="CP1_MULTIPLE_OBSERVABLES_TRACKED",
            severity="info",
            summary=f"Multiple assay observables present ({distinct_endpoints}); keep endpoint labels strictly separated.",
            recommendation="Report each observable in its own units and column throughout downstream reports.",
            details={"endpoints": distinct_endpoints},
        ))

    # 3. Positive structural controls
    control_count = payload.get("structural_control_count")
    if control_count is not None and int(control_count) < 1:
        findings.append(_finding(
            rule_id="CP1_MISSING_STRUCTURAL_CONTROL",
            severity="warn",
            summary="No co-crystal positive control registered before starting structure-based design.",
            recommendation="Add at least one cognate co-crystal control to calibrate sampling, ranking, and MD/RBFE gates.",
        ))

    # 4. Unverified crystal-water conservation assumption
    if bool(payload.get("crystal_water_assumed_conserved", False)):
        conserved_n = int(payload.get("conserved_bridge_water_count") or 0)
        if conserved_n == 0:
            findings.append(_finding(
                rule_id="CP1_UNVERIFIED_CRYSTAL_WATER_ASSUMPTION",
                severity="warn",
                summary="Crystal water conservation is assumed despite 0 conserved bridging waters across deposited structures.",
                recommendation="Treat bridging hydration as a falsifiable wet-vs-dry arm with matching seeds and water-identity residence tracking.",
            ))
            suggestions.append("Run matched-seed dry and wet control replicas before assuming water-mediated rescue.")

    return findings, suggestions


def _audit_cp2_pre_physics(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    suggestions: list[str] = []

    shortlist = list(payload.get("shortlist", ()))
    zero_catalog_ids: list[str] = []
    verified_catalog_ids: list[str] = []
    hard_flag_ids: list[str] = []

    for row in shortlist:
        if not isinstance(row, Mapping):
            continue
        cid = str(row.get("id") or row.get("candidate_id") or "?")
        if row.get("catalog_verified_partners") is not None:
            n_ver = int(row["catalog_verified_partners"])
            if n_ver == 0:
                zero_catalog_ids.append(cid)
            elif n_ver >= 2:
                verified_catalog_ids.append(cid)
        flags = list(row.get("hard_red_flags") or ())
        if flags:
            hard_flag_ids.append(cid)

    if zero_catalog_ids:
        findings.append(_finding(
            rule_id="CP2_UNVERIFIED_CATALOG_PARTNERS",
            severity="warn",
            summary=(
                f"{len(zero_catalog_ids)}/{len(shortlist)} shortlisted design(s) have 0 catalog-verified "
                f"coupling partners: {zero_catalog_ids[:6]}."
            ),
            recommendation=(
                "Include at least one 2/2 catalog-verified purchasable comparator (via catalog-constrained "
                "enumerate_reaction_analogs) before committing GPU-hours to MD/RBFE."
            ),
            details={
                "zero_catalog_ids": zero_catalog_ids,
                "fully_verified_ids": verified_catalog_ids,
            },
        ))
        if not verified_catalog_ids:
            suggestions.append(
                "Add a 2/2 catalog-verified reaction analog to the physics shortlist so synthetic feasibility is anchored."
            )

    if hard_flag_ids:
        findings.append(_finding(
            rule_id="CP2_HARD_CHEMICAL_INSTABILITY_IN_SHORTLIST",
            severity="block",
            summary=f"Shortlisted candidate(s) carry hard chemical instability flags: {hard_flag_ids}.",
            recommendation="Remove chemically unstable warheads/acyl/sulfonyl halides from the physics shortlist unless covalent design is explicitly intended.",
            details={"hard_flag_ids": hard_flag_ids},
        ))

    # RBFE atom-mapping graph integrity check
    for edge in payload.get("rbfe_mapping_audits", ()):
        if not isinstance(edge, Mapping):
            continue
        eid = str(edge.get("edge_id") or "?")
        heavy_mm = int(edge.get("heavy_connectivity_or_order_mismatches") or 0)
        passed = edge.get("passed_gate")
        if heavy_mm > 0 or passed is False:
            findings.append(_finding(
                rule_id="CP2_RBFE_MAPPING_BOND_MISMATCH",
                severity="block",
                summary=(
                    f"RBFE edge {eid} failed bond-consistent atom mapping "
                    f"(heavy_connectivity_or_order_mismatches={heavy_mm})."
                ),
                recommendation=(
                    "Regenerate mapping with verify_bond_consistent_atom_mapping "
                    "(ringMatchesRingOnly=True, completeRingsOnly=True) until 0 mismatches."
                ),
                details={"edge_id": eid, "heavy_mismatches": heavy_mm},
            ))

    # Control-gate enforcement before dispatching candidate RBFE
    if bool(payload.get("dispatch_design_rbfe", False)) and payload.get("rbfe_control_gate_passed") is False:
        findings.append(_finding(
            rule_id="CP2_CANDIDATE_RBFE_BLOCKED_BY_CONTROL_GATE",
            severity="block",
            summary="Attempted to dispatch candidate RBFE edges while the crystal-control RBFE gate failed.",
            recommendation="Hold candidate RBFE (design_rbfe_held_control_gate); escalate control edge via plan_shallow_ppi_physics_protocol first.",
        ))

    if bool(payload.get("dispatch_design_md", False)) and payload.get("md_control_gate_passed") is False:
        findings.append(_finding(
            rule_id="CP2_MD_CONTROL_DRIFT_DIAGNOSTIC_ONLY",
            severity="warn",
            summary="Crystal MD control failed pose-stability gate; candidate MD runs are diagnostic only.",
            recommendation="Do not claim candidate superiority from unconstrained MD alone; evaluate restrained/enhanced-sampling protocol.",
        ))

    return findings, suggestions


def _audit_cp3_runtime_telemetry(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    suggestions: list[str] = []

    active_dispatchers = int(payload.get("active_dispatchers") or 1)
    if active_dispatchers > 1:
        findings.append(_finding(
            rule_id="CP3_DUPLICATE_DISPATCHER_DETECTED",
            severity="block",
            summary=f"Detected {active_dispatchers} concurrent campaign dispatchers (max 1 allowed).",
            recommendation="Terminate duplicate supervisors immediately and enforce single-instance ComputeLease flock.",
            details={"active_dispatchers": active_dispatchers},
        ))

    max_cpu = payload.get("max_cpu_threads")
    cfg_cpu = payload.get("configured_cpu_threads")
    if max_cpu is not None and cfg_cpu is not None and int(cfg_cpu) > int(max_cpu):
        findings.append(_finding(
            rule_id="CP3_CPU_THREAD_CAP_BREACH",
            severity="block",
            summary=f"Configured CPU threads ({cfg_cpu}) exceed lease ceiling ({max_cpu}).",
            recommendation="Reduce concurrent workers or ntomp immediately via ComputeLease.validate_worker_launch.",
            details={"configured_cpu_threads": int(cfg_cpu), "max_cpu_threads": int(max_cpu)},
        ))

    allowed_gpus = {int(g) for g in payload.get("allowed_gpus", ())}
    forbidden_gpus = {int(g) for g in payload.get("forbidden_gpus", ())}
    raw_gpu_pids = payload.get("campaign_gpu_pids") or {}
    for raw_gid, pids in raw_gpu_pids.items():
        gid = int(raw_gid)
        pid_list = [int(p) for p in pids] if isinstance(pids, Sequence) else []
        if not pid_list:
            continue
        if gid in forbidden_gpus:
            findings.append(_finding(
                rule_id="CP3_FORBIDDEN_GPU_VIOLATION",
                severity="block",
                summary=f"Campaign process(es) {pid_list} detected on FORBIDDEN GPU {gid}.",
                recommendation=f"Evacuate GPU {gid} immediately and enforce CUDA_VISIBLE_DEVICES from ComputeLease.",
                details={"gpu_id": gid, "pids": pid_list},
            ))
        elif allowed_gpus and gid not in allowed_gpus:
            findings.append(_finding(
                rule_id="CP3_UNLEASED_GPU_VIOLATION",
                severity="block",
                summary=f"Campaign process(es) {pid_list} detected on unleased GPU {gid}.",
                recommendation=f"Restrict workers strictly to allowed_gpus={sorted(allowed_gpus)}.",
                details={"gpu_id": gid, "pids": pid_list},
            ))

    # GPU packing / utilization audit
    gpu_util = payload.get("gpu_util_by_id") or {}
    gpu_vram = payload.get("gpu_vram_frac_by_id") or {}
    underutil_gpus: list[dict[str, Any]] = []
    for raw_gid, util_val in gpu_util.items():
        gid = int(raw_gid)
        if allowed_gpus and gid not in allowed_gpus:
            continue
        pids_on_gpu = raw_gpu_pids.get(str(gid), raw_gpu_pids.get(gid, ()))
        if raw_gpu_pids and not pids_on_gpu:
            continue
        util = float(util_val)
        vram_frac = float(gpu_vram.get(str(gid), gpu_vram.get(gid, 0.0)))
        if util < DEFAULT_UNDERUTIL_SM_PCT and vram_frac < DEFAULT_UNDERUTIL_VRAM_FRAC:
            underutil_gpus.append({"gpu_id": gid, "sm_util_pct": round(util, 1), "vram_frac": round(vram_frac, 4)})

    if underutil_gpus:
        findings.append(_finding(
            rule_id="CP3_GPU_UNDER_UTILIZED_PACKING_OPPORTUNITY",
            severity="warn",
            summary=(
                f"{len(underutil_gpus)} active leased GPU(s) below {DEFAULT_UNDERUTIL_SM_PCT:.0f}% SM "
                f"with <{DEFAULT_UNDERUTIL_VRAM_FRAC * 100:.0f}% VRAM used."
            ),
            recommendation="Increase jobs_per_gpu via ComputeLease.plan_packed_slots (within CPU cap) to improve throughput.",
            details={"underutilized_gpus": underutil_gpus},
        ))
        suggestions.append("Repack idle VRAM slots on leased GPUs using single_job_sm_util_pct auto-packing.")

    return findings, suggestions


def _audit_cp4_pre_delivery(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    findings: list[dict[str, Any]] = []
    suggestions: list[str] = []

    report_text = str(payload.get("report_text") or "")
    exp_count = int(payload.get("experimental_validation_count") or 0)
    if exp_count == 0 and report_text and _OVERCLAIM_POTENCY_RE.search(report_text):
        findings.append(_finding(
            rule_id="CP4_PROXY_OVERCLAIMED_AS_POTENCY",
            severity="block",
            summary="Draft report claims confirmed/verified higher experimental potency despite 0 new wet-lab measurements.",
            recommendation="Qualify all docking/MPO/Free-Wilson rankings explicitly as computational hypotheses, not measured affinity.",
        ))

    if bool(payload.get("claims_admitted_candidate_rbfe", False)) and payload.get("rbfe_control_converged") is False:
        findings.append(_finding(
            rule_id="CP4_UNCONVERGED_RBFE_PRESENTED_AS_ADMITTED",
            severity="block",
            summary="Draft delivery presents candidate RBFE ΔΔG as admitted despite unconverged control edges.",
            recommendation="Mark candidate RBFE as held/not_admitted and report exact control overlap and grid shift.",
        ))

    if bool(payload.get("claims_wet_bridge_rescue", False)):
        occ = payload.get("full_wet_water_site_occupancy")
        if occ is None or float(occ) <= 0.05:
            findings.append(_finding(
                rule_id="CP4_UNSUBSTANTIATED_WET_RESCUE_CLAIM",
                severity="block",
                summary="Draft delivery claims crystal-water rescue without reproducible full-trajectory site occupancy.",
                recommendation="Report exact seeded-water site residence across full replicas and retract causal rescue claims.",
            ))

    if not payload.get("admission_explicitly_stated", True):
        findings.append(_finding(
            rule_id="CP4_ADMISSION_NOT_SEPARATED_FROM_COMPLETION",
            severity="warn",
            summary="Delivery report does not explicitly separate completion, verification, and scientific admission.",
            recommendation="State admission status explicitly at the top of REPORT.md per CLAUDE.md fixed terminology.",
        ))

    return findings, suggestions


def run_deterministic_sidecar_audit(
    checkpoint: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Run Layer-A deterministic zero-token sidecar audit for one stage checkpoint."""
    if checkpoint not in SIDECAR_CHECKPOINTS:
        raise ValueError(
            f"unknown checkpoint {checkpoint!r}; expected one of {SIDECAR_CHECKPOINTS}"
        )

    if checkpoint == "CP1_TARGET_DATA":
        findings, suggestions = _audit_cp1_target_data(payload)
    elif checkpoint == "CP2_PRE_PHYSICS":
        findings, suggestions = _audit_cp2_pre_physics(payload)
    elif checkpoint == "CP3_RUNTIME_TELEMETRY":
        findings, suggestions = _audit_cp3_runtime_telemetry(payload)
    else:
        findings, suggestions = _audit_cp4_pre_delivery(payload)

    max_rank = max((_SEVERITY_RANK[f["severity"]] for f in findings), default=0)
    verdict = _VERDICT_FROM_RANK[max_rank]
    payload_digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    return {
        "schema": SIDECAR_REVIEW_SCHEMA,
        "checkpoint": checkpoint,
        "audited_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "payload_sha256": payload_digest,
        "verdict": verdict,
        "blocking_count": sum(1 for f in findings if f["severity"] == "block"),
        "warning_count": sum(1 for f in findings if f["severity"] == "warn"),
        "findings": findings,
        "suggestions": suggestions,
        "llm_critic": {"status": "not_run", "transport": None, "retries": 0},
    }


def build_sidecar_critic_prompt(
    checkpoint: str,
    payload: Mapping[str, Any],
    deterministic_review: Mapping[str, Any],
) -> str:
    """Build a compact, artifact-only prompt for a fresh read-only LLM critic agent.

    Deliberately excludes the primary agent's conversational narrative to eliminate
    sycophancy and groupthink.
    """
    compact_payload = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)[:6000]
    compact_det = json.dumps(
        {
            "verdict": deterministic_review.get("verdict"),
            "findings": deterministic_review.get("findings", []),
        },
        sort_keys=True,
        ensure_ascii=False,
    )[:3000]
    return (
        "You are an independent, read-only scientific and engineering sidecar auditor for MolDarwin.\n"
        f"Checkpoint: {checkpoint}\n"
        "You have NO write authority and MUST NOT downgrade any existing deterministic 'block' finding.\n"
        "Inspect ONLY the structured checkpoint artifacts below and flag missed scientific, chemical, "
        "statistical, or compute-efficiency risks plus concrete actionable suggestions.\n\n"
        f"Deterministic Pre-Audit:\n{compact_det}\n\n"
        f"Checkpoint Artifacts (JSON):\n{compact_payload}\n\n"
        "Return ONLY a single JSON object with keys:\n"
        '{"verdict": "pass"|"warn"|"block", '
        '"findings": [{"rule_id": str, "severity": "info"|"warn"|"block", "summary": str, "recommendation": str}], '
        '"suggestions": [str]}\n'
    )


def run_sidecar_review(
    checkpoint: str,
    payload: Mapping[str, Any],
    *,
    transport: Transport | None = None,
    max_llm_attempts: int = 2,
) -> dict[str, Any]:
    """Run deterministic sidecar audit plus optional clean-context LLM critic review.

    Monotonic safety guarantee: an LLM critic can add ``info``/``warn``/``block`` findings
    and suggestions, and can raise ``verdict``, but can NEVER erase or downgrade a
    deterministic ``block`` or ``warn``.
    """
    review = run_deterministic_sidecar_audit(checkpoint, payload)
    if transport is None:
        return review

    prompt = build_sidecar_critic_prompt(checkpoint, payload, review)
    attempts = max(1, int(max_llm_attempts))
    errors: list[str] = []
    parsed: dict[str, Any] | None = None

    for attempt in range(1, attempts + 1):
        try:
            raw_reply = transport.ask(prompt)
            cand = _parse(raw_reply, required=("verdict", "findings", "suggestions"))
            if cand["verdict"] not in {"pass", "warn", "block"}:
                raise AdvisorError(f"invalid sidecar verdict: {cand['verdict']!r}")
            if not isinstance(cand["findings"], list) or not isinstance(cand["suggestions"], list):
                raise AdvisorError("findings and suggestions must be JSON arrays")
            parsed = cand
            review["llm_critic"] = {
                "status": "completed",
                "transport": getattr(transport, "name", type(transport).__name__),
                "attempts": attempt,
                "retries": attempt - 1,
                "errors": errors,
            }
            break
        except (AdvisorError, ValueError, TypeError) as exc:
            errors.append(f"attempt {attempt}: {exc}")

    if parsed is None:
        # Honest failure: keep deterministic audit intact, report LLM critic failure clearly.
        review["llm_critic"] = {
            "status": "failed_refused",
            "transport": getattr(transport, "name", type(transport).__name__),
            "attempts": attempts,
            "retries": attempts - 1,
            "errors": errors,
        }
        return review

    det_rank = _SEVERITY_RANK.get(
        "block" if review["verdict"] == "block" else ("warn" if review["verdict"] == "warn" else "info"),
        0,
    )
    llm_verdict_rank = _SEVERITY_RANK.get(
        "block" if parsed["verdict"] == "block" else ("warn" if parsed["verdict"] == "warn" else "info"),
        0,
    )

    merged_findings = list(review["findings"])
    for item in parsed["findings"]:
        if not isinstance(item, Mapping):
            continue
        sev = str(item.get("severity") or "info")
        if sev not in _SEVERITY_RANK:
            continue
        merged_findings.append(_finding(
            rule_id=str(item.get("rule_id") or "LLM_SIDECAR_NOTE"),
            severity=sev,
            summary=str(item.get("summary") or "").strip() or "LLM sidecar observation",
            recommendation=str(item.get("recommendation") or "").strip() or "Review observation.",
            source=f"llm_critic:{review['llm_critic']['transport']}",
        ))

    merged_suggestions = list(review["suggestions"])
    for s in parsed["suggestions"]:
        text = str(s).strip()
        if text and text not in merged_suggestions:
            merged_suggestions.append(text)

    findings_rank = max((_SEVERITY_RANK[f["severity"]] for f in merged_findings), default=0)
    final_rank = max(det_rank, llm_verdict_rank, findings_rank)

    review["findings"] = merged_findings
    review["suggestions"] = merged_suggestions
    review["verdict"] = _VERDICT_FROM_RANK[final_rank]
    review["blocking_count"] = sum(1 for f in merged_findings if f["severity"] == "block")
    review["warning_count"] = sum(1 for f in merged_findings if f["severity"] == "warn")
    return review


def record_advisory_resolution(
    ledger_path: str | Path,
    *,
    checkpoint: str,
    rule_id: str,
    severity: str,
    decision: str,
    rationale: str,
    actor: str = "primary_agent",
    waiver_ref: str | None = None,
) -> dict[str, Any]:
    """Append an auditable acceptance or rejection record for one sidecar finding.

    Enforces two governance guards:
      1. Rejecting a ``warn`` requires an explicit rationale (>= 16 chars) for auditability.
      2. Rejecting a ``block`` is refused unless an explicit human ``waiver_ref`` is supplied.
    Never mutates leaf measurement records (Hard Constraint 2).
    """
    if decision not in {"accepted", "rejected_with_rationale"}:
        raise ValueError(f"invalid decision {decision!r}; expected 'accepted' or 'rejected_with_rationale'")
    if severity not in _SEVERITY_RANK:
        raise ValueError(f"invalid severity {severity!r}")
    clean_rationale = rationale.strip()
    if decision == "rejected_with_rationale":
        if len(clean_rationale) < 16:
            raise ValueError("rejecting a sidecar advisory requires rationale >= 16 characters")
        if severity == "block" and not (waiver_ref and waiver_ref.strip()):
            raise ValueError(
                "cannot reject a 'block' sidecar finding without an explicit human waiver_ref"
            )

    record = {
        "schema": SIDECAR_RESOLUTION_SCHEMA,
        "recorded_at": datetime.now(UTC).isoformat(),
        "checkpoint": checkpoint,
        "rule_id": rule_id,
        "severity": severity,
        "decision": decision,
        "rationale": clean_rationale,
        "actor": actor,
        "waiver_ref": waiver_ref.strip() if waiver_ref else None,
    }
    record["record_sha256"] = hashlib.sha256(
        json.dumps(record, sort_keys=True).encode("utf-8")
    ).hexdigest()

    dest = Path(ledger_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


__all__ = [
    "SIDECAR_CHECKPOINTS",
    "SIDECAR_RESOLUTION_SCHEMA",
    "SIDECAR_REVIEW_SCHEMA",
    "build_sidecar_critic_prompt",
    "record_advisory_resolution",
    "run_deterministic_sidecar_audit",
    "run_sidecar_review",
]
