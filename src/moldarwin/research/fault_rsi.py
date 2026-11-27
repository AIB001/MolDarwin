"""Fault-signature indexed executable code-level RSI registry with physical admission gating.

Elevates RSI from passive prose notes to active executable immunity without conflating
process completion with scientific admission:
  - Maps concrete stderr/traceback regexes and physical diagnostic codes to verified
    Python remediation entrypoints (``module:function``) tagged with an explicit
    ``impact_class``:
      * ``io_repair``: parser/formatting/runtime flag fix that does not alter the chemical
        input set or physical Hamiltonian.
      * ``input_filter``: excludes/filters molecules or atoms; requires explicit
        ``coverage_loss_logged=True`` so dropped hits cannot be silently swallowed.
      * ``physics_perturbation``: alters force-field/mass/alchemical/sampling parameters;
        process completion alone can NEVER promote to ``cross_target_default`` without a
        passing Tier-1 physical equivalence check (``equivalence_verified=True``).
  - Stamps every registered remediation and outcome with ``generation_stamp`` and a content
    ``remediation_digest`` (SHA-256).
  - Bridges applied remediations into :class:`moldarwin.research.ResearchJournal` as
    content-hashed :class:`moldarwin.research.schema.Artifact` receipts so downstream
    experiments and conclusions bind them into ``relied_on`` provenance chains.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAULT_RSI_SCHEMA = "moldarwin-fault-rsi-match/1"
FAULT_RSI_RECORD_SCHEMA = "moldarwin-fault-rsi-event/1"
FAULT_RSI_RECEIPT_SCHEMA = "moldarwin-fault-rsi-journal-receipt/1"

VALID_IMPACT_CLASSES: frozenset[str] = frozenset({
    "io_repair",
    "input_filter",
    "physics_perturbation",
})

DEFAULT_GENERATION_STAMP = "host, in session"

#: Empirically verified built-in fault signatures -> executable MolDarwin remediations.
BUILTIN_FAULT_REMEDIATIONS: tuple[dict[str, Any], ...] = (
    {
        "remediation_id": "unidock_unsupported_elements",
        "pattern": r"(unsupported atom type|unknown atom type|element\s+(B|Si|Se)\b|AutoDock.*type)",
        "fault_class": "docking_preflight",
        "impact_class": "input_filter",
        "entrypoint": "moldarwin.physics.preflight:preflight_scorer_elements",
        "summary": "Filter B/Si/Se/metals before Meeko/Uni-Dock PDBQT generation and log excluded coverage loss (caught 9/123 boron crashes).",
        "tier": "scoped_candidate",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "prism_blank_sdf_title",
        "pattern": r"(IG\s+L|blank.*title|corrupted.*GRO|invalid literal for float.*IG)",
        "fault_class": "prism_topology",
        "impact_class": "io_repair",
        "entrypoint": "moldarwin.physics.preflight:sanitize_ligand_sdf",
        "summary": "Repair blank SDF line-0 titles before PRISMBuilder to prevent GRO/ITP column corruption.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gnina_meeko_pdbqt_tag",
        "pattern": r"(Unknown or inappropriate tag|Parse error.*\.pdbqt)",
        "fault_class": "rescoring_io",
        "impact_class": "io_repair",
        "entrypoint": "meeko:PDBQTMolecule+RDKitMolCreate->batched_sdf",
        "summary": "Convert multi-mode Meeko/Uni-Dock PDBQT to batched multi-record .sdf before gnina --score_only.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gmx2026_em_gpu_pme",
        "pattern": r"(PME on GPU is not supported.*steep|steep.*pme.*gpu|POSRES.*without -r)",
        "fault_class": "gromacs2026_em",
        "impact_class": "io_repair",
        "entrypoint": "moldarwin.physics.prism_bridge:patch_gromacs2026_artifacts",
        "summary": "Run steepest-descent EM with -pme cpu and -r {start_gro}; keep GPU flags for NVT/NPT/MD.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gmx2026_tpr_v138_mdanalysis",
        "pattern": r"(TPR.*version\s*13[0-9]|unknown.*tpr.*version|File format.*138)",
        "fault_class": "trajectory_analysis",
        "impact_class": "io_repair",
        "entrypoint": "moldarwin.physics.prism_bridge:analyze_md_trajectory",
        "summary": "Auto-fallback via gmx trjconv -pbc whole to GRO+XTC + minimum-image PBC ligand unwrapping.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "prism_fep_sdf_gro_dispatch",
        "pattern": r"(invalid literal for int\(\) with base 10:\s*'N'|resolve_coord_source|hybrid.*gro.*sdf)",
        "fault_class": "prism_fep_prepare",
        "impact_class": "io_repair",
        "entrypoint": "moldarwin.physics.prism_fep:prepare_prism_fep_edge",
        "summary": "Scoped SDF->LIG.gro coordinate-verified guard without modifying asset/prism.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gmx2026_fep_dummy_mass_gpu_update",
        "pattern": r"(mass.*perturbed.*update.*gpu|Cannot run.*update.*gpu.*mass|DUM_.*mass)",
        "fault_class": "prism_fep_gpu",
        "impact_class": "physics_perturbation",
        "entrypoint": "moldarwin.physics.prism_fep:enforce_invariant_dummy_masses",
        "summary": "Keep dummy-atom masses equal to real endpoint masses so GROMACS 2026 enables -update gpu (requires Tier-1 ddG CPU-vs-GPU equivalence verification before default promotion).",
        "tier": "scoped_candidate",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "fep_low_adjacent_overlap",
        "pattern": r"(low_adjacent_overlap|overlap_min.*<\s*0\.03|overlap collapsed)",
        "fault_class": "fep_convergence",
        "impact_class": "physics_perturbation",
        "entrypoint": "moldarwin.physics.adaptive:refine_lambda_schedule_from_overlap",
        "summary": "Insert adaptive intermediate lambda states in failing intervals via thermodynamic-length density.",
        "tier": "scoped_candidate",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gpu_under_utilization_fep",
        "pattern": r"(gpu_util.*<\s*50|under.?utiliz|single.?window.*30%)",
        "fault_class": "compute_efficiency",
        "impact_class": "io_repair",
        "entrypoint": "moldarwin.physics.adaptive:render_packed_fep_runner",
        "summary": "Micro-benchmark k=1 vs 2 vs 3 concurrent jobs/GPU with disjoint -pinoffset CPU pinning.",
        "tier": "draft_lesson",
        "evidence": "measured_here",
    },
)


def remediation_digest(record: Mapping[str, Any]) -> str:
    """Content SHA-256 binding a remediation's executable identity and impact class."""
    canonical = json.dumps(
        {
            "remediation_id": str(record.get("remediation_id") or ""),
            "impact_class": str(record.get("impact_class") or "io_repair"),
            "fault_class": str(record.get("fault_class") or ""),
            "pattern": str(record.get("pattern") or ""),
            "entrypoint": str(record.get("entrypoint") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _empty_stats() -> dict[str, Any]:
    return {
        "attempts": 0,
        "successes": 0,
        "targets": set(),
        "equivalence_verified_count": 0,
        "equivalence_regressions": 0,
        "equivalence_targets": set(),
        "logged_filter_targets": set(),
        "unlogged_filter_successes": 0,
        "last_generation_stamp": DEFAULT_GENERATION_STAMP,
    }


class FaultRSIRegistry:
    """Append-only fault-signature -> executable remediation registry with admission gating."""

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        self.ledger_path = Path(ledger_path).resolve() if ledger_path is not None else None
        self._custom: dict[str, dict[str, Any]] = {}
        self._stats: dict[str, dict[str, Any]] = {}
        if self.ledger_path is not None and self.ledger_path.is_file():
            self._load_ledger()

    def _apply_outcome_to_stats(self, rid: str, ev: Mapping[str, Any]) -> dict[str, Any]:
        st = self._stats.setdefault(rid, _empty_stats())
        st["attempts"] += 1
        target = str(ev.get("target") or "")
        if ev.get("generation_stamp"):
            st["last_generation_stamp"] = str(ev["generation_stamp"])
        if ev.get("succeeded"):
            st["successes"] += 1
            if target:
                st["targets"].add(target)
            if ev.get("coverage_loss_logged"):
                if target:
                    st["logged_filter_targets"].add(target)
            elif "coverage_loss_logged" in ev:
                st["unlogged_filter_successes"] += 1
        eq = ev.get("equivalence_verified")
        if eq is True:
            st["equivalence_verified_count"] += 1
            if target:
                st["equivalence_targets"].add(target)
        elif eq is False:
            st["equivalence_regressions"] += 1
        return st

    def _load_ledger(self) -> None:
        assert self.ledger_path is not None
        for line in self.ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            kind = ev.get("event")
            rid = str(ev.get("remediation_id") or "")
            if kind == "register":
                rec = dict(ev["remediation"])
                rec.setdefault("impact_class", "io_repair")
                rec.setdefault("generation_stamp", ev.get("generation_stamp", DEFAULT_GENERATION_STAMP))
                self._custom[rid] = rec
            elif kind == "outcome" and rid:
                self._apply_outcome_to_stats(rid, ev)

    def _append_event(self, payload: Mapping[str, Any]) -> None:
        if self.ledger_path is None:
            return
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": FAULT_RSI_RECORD_SCHEMA,
            "timestamp": datetime.now(UTC).isoformat(),
            **dict(payload),
        }
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def all_remediations(self) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {r["remediation_id"]: dict(r) for r in BUILTIN_FAULT_REMEDIATIONS}
        merged.update(self._custom)
        out: list[dict[str, Any]] = []
        for rid, rec in sorted(merged.items()):
            impact = str(rec.get("impact_class") or "io_repair")
            st = self._stats.get(rid)
            attempts = st["attempts"] if st else 0
            successes = st["successes"] if st else 0
            targets = sorted(st["targets"]) if st else []
            eq_ok = st["equivalence_verified_count"] if st else 0
            eq_fail = st["equivalence_regressions"] if st else 0
            eq_targets = sorted(st["equivalence_targets"]) if st else []
            logged_filter_targets = sorted(st["logged_filter_targets"]) if st else []
            unlogged_filter = st["unlogged_filter_successes"] if st else 0
            gen_stamp = (
                st["last_generation_stamp"]
                if st
                else str(rec.get("generation_stamp") or DEFAULT_GENERATION_STAMP)
            )
            fix_rate = (successes / attempts) if attempts else None

            tier = str(rec.get("tier") or "draft_lesson")
            blocked_reason: str | None = None

            if impact == "physics_perturbation":
                if eq_fail > 0:
                    tier = "rejected_physics_regression"
                    blocked_reason = "tier1_physical_equivalence_regression"
                elif len(targets) >= 2 and fix_rate is not None and fix_rate >= 0.8:
                    if eq_ok >= 1:
                        tier = "cross_target_default"
                    else:
                        tier = "scoped_candidate"
                        blocked_reason = "awaiting_tier1_physical_equivalence_verification"
                elif successes >= 1 and tier == "draft_lesson":
                    tier = "scoped_candidate"
            elif impact == "input_filter":
                if len(logged_filter_targets) >= 2 and fix_rate is not None and fix_rate >= 0.8 and unlogged_filter == 0:
                    tier = "cross_target_default"
                elif len(targets) >= 2 and fix_rate is not None and fix_rate >= 0.8:
                    tier = "scoped_candidate"
                    blocked_reason = "input_filter_coverage_loss_unlogged"
                elif successes >= 1 and tier == "draft_lesson":
                    tier = "scoped_candidate"
            else:  # io_repair
                if len(targets) >= 2 and fix_rate is not None and fix_rate >= 0.8:
                    tier = "cross_target_default"
                elif successes >= 1 and tier == "draft_lesson":
                    tier = "scoped_candidate"

            out.append({
                **rec,
                "impact_class": impact,
                "remediation_digest": remediation_digest(rec),
                "generation_stamp": gen_stamp,
                "tier": tier,
                "promotion_blocked_reason": blocked_reason,
                "attempts": attempts,
                "successes": successes,
                "fix_rate": round(fix_rate, 3) if fix_rate is not None else None,
                "verified_targets": targets,
                "equivalence_verified_count": eq_ok,
                "equivalence_regressions": eq_fail,
                "equivalence_verified_targets": eq_targets,
                "logged_filter_targets": logged_filter_targets,
            })
        return out

    def get_remediation(self, remediation_id: str) -> dict[str, Any]:
        for rec in self.all_remediations():
            if rec["remediation_id"] == remediation_id:
                return rec
        raise KeyError(f"unknown fault RSI remediation: {remediation_id!r}")

    def register_remediation(
        self,
        *,
        remediation_id: str,
        pattern: str,
        fault_class: str,
        entrypoint: str,
        summary: str,
        impact_class: str = "io_repair",
        evidence: str = "measured_here",
        generation_stamp: str = DEFAULT_GENERATION_STAMP,
    ) -> dict[str, Any]:
        """Register a newly discovered fault pattern -> executable Python remediation."""
        if impact_class not in VALID_IMPACT_CLASSES:
            raise ValueError(
                f"impact_class must be one of {sorted(VALID_IMPACT_CLASSES)}, got {impact_class!r}"
            )
        re.compile(pattern)  # Validate regex upfront
        rec = {
            "remediation_id": remediation_id,
            "pattern": pattern,
            "fault_class": fault_class,
            "impact_class": impact_class,
            "entrypoint": entrypoint,
            "summary": summary,
            "tier": "draft_lesson",
            "evidence": evidence,
            "generation_stamp": generation_stamp,
        }
        rec["remediation_digest"] = remediation_digest(rec)
        self._custom[remediation_id] = rec
        self._append_event({
            "event": "register",
            "remediation_id": remediation_id,
            "generation_stamp": generation_stamp,
            "remediation": rec,
        })
        return rec

    def record_outcome(
        self,
        remediation_id: str,
        *,
        succeeded: bool,
        target: str,
        detail: str = "",
        equivalence_verified: bool | None = None,
        equivalence_evidence: str = "",
        coverage_loss_logged: bool | None = None,
        excluded_count: int | None = None,
        generation_stamp: str = DEFAULT_GENERATION_STAMP,
    ) -> dict[str, Any]:
        """Append one verified outcome to update empirical fix rate and admission-gated promotion."""
        event: dict[str, Any] = {
            "event": "outcome",
            "remediation_id": remediation_id,
            "succeeded": bool(succeeded),
            "target": target,
            "detail": detail[:300],
            "generation_stamp": generation_stamp,
        }
        if equivalence_verified is not None:
            event["equivalence_verified"] = bool(equivalence_verified)
        if equivalence_evidence:
            event["equivalence_evidence"] = equivalence_evidence[:300]
        if coverage_loss_logged is not None:
            event["coverage_loss_logged"] = bool(coverage_loss_logged)
        if excluded_count is not None:
            event["excluded_count"] = int(excluded_count)

        st = self._apply_outcome_to_stats(remediation_id, event)
        self._append_event(event)
        return {
            "remediation_id": remediation_id,
            "attempts": st["attempts"],
            "successes": st["successes"],
            "verified_targets": sorted(st["targets"]),
            "equivalence_verified_count": st["equivalence_verified_count"],
            "equivalence_regressions": st["equivalence_regressions"],
            "generation_stamp": generation_stamp,
        }

    def match(self, error_text: str, *, fault_class: str | None = None) -> dict[str, Any]:
        """Match an error/traceback or diagnostic flag against all known executable remediations."""
        tier_rank = {
            "cross_target_default": 3,
            "scoped_candidate": 2,
            "draft_lesson": 1,
            "rejected_physics_regression": 0,
        }
        hits: list[dict[str, Any]] = []
        for rec in self.all_remediations():
            if fault_class and rec.get("fault_class") != fault_class:
                continue
            if re.search(rec["pattern"], error_text, flags=re.IGNORECASE | re.DOTALL):
                hits.append(rec)
        hits.sort(
            key=lambda r: (tier_rank.get(r["tier"], 0), r["fix_rate"] or 0.0, r["successes"]),
            reverse=True,
        )
        return {
            "schema": FAULT_RSI_SCHEMA,
            "query_chars": len(error_text),
            "match_count": len(hits),
            "matches": hits,
        }

    def record_in_journal(
        self,
        journal: Any,
        remediation_id: str,
        *,
        target: str,
        directory: str | Path,
        generation_stamp: str = DEFAULT_GENERATION_STAMP,
        detail: str = "",
        equivalence_report: Mapping[str, Any] | None = None,
        parents: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Write a content-hashed remediation receipt into ``ResearchJournal`` for ``relied_on`` binding.

        Returns the journal ``artifact_id`` so downstream ``Experiment.inputs`` or
        ``Observation.evidence`` can bind the exact remediation digest, impact class, and
        physical equivalence verification state into MolDarwin's provenance graph.
        """
        from moldarwin.boundary.prism_v1 import file_identity
        from moldarwin.research.schema import Artifact

        rec = self.get_remediation(remediation_id)
        out_dir = Path(directory).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_target = re.sub(r"[^A-Za-z0-9._-]+", "_", target).strip("_") or "target"
        receipt_path = out_dir / f"fault_rsi_{remediation_id}_{safe_target}.json"
        payload = {
            "schema": FAULT_RSI_RECEIPT_SCHEMA,
            "recorded_at": datetime.now(UTC).isoformat(),
            "remediation_id": rec["remediation_id"],
            "remediation_digest": rec["remediation_digest"],
            "impact_class": rec["impact_class"],
            "tier": rec["tier"],
            "promotion_blocked_reason": rec["promotion_blocked_reason"],
            "entrypoint": rec["entrypoint"],
            "target": target,
            "generation_stamp": generation_stamp,
            "equivalence_verified_count": rec["equivalence_verified_count"],
            "equivalence_regressions": rec["equivalence_regressions"],
            "detail": detail,
            "equivalence_report": dict(equivalence_report) if equivalence_report is not None else None,
        }
        receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        ident = file_identity(receipt_path)
        artifact = Artifact(
            path=str(receipt_path),
            sha256=ident["sha256"],
            bytes=ident["bytes"],
            source_kind="new_execution",
            role="diagnostic",
            bindings={
                "fault_rsi_remediation_id": rec["remediation_id"],
                "fault_rsi_digest": rec["remediation_digest"],
                "fault_rsi_impact_class": rec["impact_class"],
                "fault_rsi_tier": rec["tier"],
                "fault_rsi_equivalence_verified": rec["equivalence_verified_count"] > 0,
                "generation_stamp": generation_stamp,
                "target": target,
            },
            parents=tuple(parents),
        )
        artifact_id = journal.record(artifact)
        return {
            "artifact_id": artifact_id,
            "receipt_path": str(receipt_path),
            "remediation_id": rec["remediation_id"],
            "remediation_digest": rec["remediation_digest"],
            "impact_class": rec["impact_class"],
            "tier": rec["tier"],
            "generation_stamp": generation_stamp,
        }


def match_known_faults(
    error_text: str,
    *,
    ledger_path: str | Path | None = None,
    fault_class: str | None = None,
) -> dict[str, Any]:
    """Convenience entrypoint matching stderr/diagnostic text against executable RSI fixes."""
    return FaultRSIRegistry(ledger_path).match(error_text, fault_class=fault_class)


__all__ = [
    "BUILTIN_FAULT_REMEDIATIONS",
    "DEFAULT_GENERATION_STAMP",
    "FAULT_RSI_RECEIPT_SCHEMA",
    "FAULT_RSI_RECORD_SCHEMA",
    "FAULT_RSI_SCHEMA",
    "VALID_IMPACT_CLASSES",
    "FaultRSIRegistry",
    "match_known_faults",
    "remediation_digest",
]
