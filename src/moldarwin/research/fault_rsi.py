"""Fault-signature indexed executable code-level RSI registry.

Elevates RSI from passive prose notes to active executable immunity:
  - Maps concrete stderr/traceback regexes and physical diagnostic codes to verified
    Python remediation entrypoints (module:function) and applicability conditions.
  - Tracks live hit counts, verified fix successes/failures, and independent target count
    in an append-only JSONL ledger (preserving history, never mutating prior events).
  - Ships pre-seeded with empirically discovered MolDarwin x PRISM x GROMACS 2026 faults
    verified across live multi-GPU campaigns (2026-11-26).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAULT_RSI_SCHEMA = "moldarwin-fault-rsi-match/1"
FAULT_RSI_RECORD_SCHEMA = "moldarwin-fault-rsi-event/1"

#: Empirically verified built-in fault signatures -> executable MolDarwin remediations.
BUILTIN_FAULT_REMEDIATIONS: tuple[dict[str, Any], ...] = (
    {
        "remediation_id": "unidock_unsupported_elements",
        "pattern": r"(unsupported atom type|unknown atom type|element\s+(B|Si|Se)\b|AutoDock.*type)",
        "fault_class": "docking_preflight",
        "entrypoint": "moldarwin.physics.preflight:preflight_scorer_elements",
        "summary": "Filter B/Si/Se/metals before Meeko/Uni-Dock PDBQT generation (caught 9/123 boron crashes).",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "prism_blank_sdf_title",
        "pattern": r"(IG\s+L|blank.*title|corrupted.*GRO|invalid literal for float.*IG)",
        "fault_class": "prism_topology",
        "entrypoint": "moldarwin.physics.preflight:sanitize_ligand_sdf",
        "summary": "Repair blank SDF line-0 titles before PRISMBuilder to prevent GRO/ITP column corruption.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gnina_meeko_pdbqt_tag",
        "pattern": r"(Unknown or inappropriate tag|Parse error.*\.pdbqt)",
        "fault_class": "rescoring_io",
        "entrypoint": "meeko:PDBQTMolecule+RDKitMolCreate->batched_sdf",
        "summary": "Convert multi-mode Meeko/Uni-Dock PDBQT to batched multi-record .sdf before gnina --score_only.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gmx2026_em_gpu_pme",
        "pattern": r"(PME on GPU is not supported.*steep|steep.*pme.*gpu|POSRES.*without -r)",
        "fault_class": "gromacs2026_em",
        "entrypoint": "moldarwin.physics.prism_bridge:patch_gromacs2026_artifacts",
        "summary": "Run steepest-descent EM with -pme cpu and -r {start_gro}; keep GPU flags for NVT/NPT/MD.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gmx2026_tpr_v138_mdanalysis",
        "pattern": r"(TPR.*version\s*13[0-9]|unknown.*tpr.*version|File format.*138)",
        "fault_class": "trajectory_analysis",
        "entrypoint": "moldarwin.physics.prism_bridge:analyze_md_trajectory",
        "summary": "Auto-fallback via gmx trjconv -pbc whole to GRO+XTC + minimum-image PBC ligand unwrapping.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "prism_fep_sdf_gro_dispatch",
        "pattern": r"(invalid literal for int\(\) with base 10:\s*'N'|resolve_coord_source|hybrid.*gro.*sdf)",
        "fault_class": "prism_fep_prepare",
        "entrypoint": "moldarwin.physics.prism_fep:prepare_prism_fep_edge",
        "summary": "Scoped SDF->LIG.gro coordinate-verified guard without modifying asset/prism.",
        "tier": "cross_target_default",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gmx2026_fep_dummy_mass_gpu_update",
        "pattern": r"(mass.*perturbed.*update.*gpu|Cannot run.*update.*gpu.*mass|DUM_.*mass)",
        "fault_class": "prism_fep_gpu",
        "entrypoint": "moldarwin.physics.prism_fep:enforce_invariant_dummy_masses",
        "summary": "Keep dummy-atom masses equal to real endpoint masses so GROMACS 2026 enables -update gpu.",
        "tier": "scoped_candidate",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "fep_low_adjacent_overlap",
        "pattern": r"(low_adjacent_overlap|overlap_min.*<\s*0\.03|overlap collapsed)",
        "fault_class": "fep_convergence",
        "entrypoint": "moldarwin.physics.adaptive:refine_lambda_schedule_from_overlap",
        "summary": "Insert adaptive intermediate lambda states in failing intervals via thermodynamic-length density.",
        "tier": "scoped_candidate",
        "evidence": "measured_here",
    },
    {
        "remediation_id": "gpu_under_utilization_fep",
        "pattern": r"(gpu_util.*<\s*50|under.?utiliz|single.?window.*30%)",
        "fault_class": "compute_efficiency",
        "entrypoint": "moldarwin.physics.adaptive:render_packed_fep_runner",
        "summary": "Micro-benchmark k=1 vs 2 vs 3 concurrent jobs/GPU with disjoint -pinoffset CPU pinning.",
        "tier": "draft_lesson",
        "evidence": "measured_here",
    },
)


class FaultRSIRegistry:
    """Append-only fault-signature -> executable remediation registry."""

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        self.ledger_path = Path(ledger_path).resolve() if ledger_path is not None else None
        self._custom: dict[str, dict[str, Any]] = {}
        self._stats: dict[str, dict[str, Any]] = {}
        if self.ledger_path is not None and self.ledger_path.is_file():
            self._load_ledger()

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
                self._custom[rid] = dict(ev["remediation"])
            elif kind == "outcome" and rid:
                st = self._stats.setdefault(rid, {"attempts": 0, "successes": 0, "targets": set()})
                st["attempts"] += 1
                if ev.get("succeeded"):
                    st["successes"] += 1
                    if ev.get("target"):
                        st["targets"].add(str(ev["target"]))

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
            st = self._stats.get(rid)
            attempts = st["attempts"] if st else 0
            successes = st["successes"] if st else 0
            targets = sorted(st["targets"]) if st else []
            tier = rec.get("tier", "draft_lesson")
            if len(targets) >= 2 and attempts > 0 and (successes / attempts) >= 0.8:
                tier = "cross_target_default"
            elif successes >= 1 and tier == "draft_lesson":
                tier = "scoped_candidate"
            out.append({
                **rec,
                "tier": tier,
                "attempts": attempts,
                "successes": successes,
                "fix_rate": round(successes / attempts, 3) if attempts else None,
                "verified_targets": targets,
            })
        return out

    def register_remediation(
        self,
        *,
        remediation_id: str,
        pattern: str,
        fault_class: str,
        entrypoint: str,
        summary: str,
        evidence: str = "measured_here",
    ) -> dict[str, Any]:
        """Register a newly discovered fault pattern -> executable Python remediation."""
        re.compile(pattern)  # Validate regex upfront
        rec = {
            "remediation_id": remediation_id,
            "pattern": pattern,
            "fault_class": fault_class,
            "entrypoint": entrypoint,
            "summary": summary,
            "tier": "draft_lesson",
            "evidence": evidence,
        }
        self._custom[remediation_id] = rec
        self._append_event({"event": "register", "remediation_id": remediation_id, "remediation": rec})
        return rec

    def record_outcome(
        self,
        remediation_id: str,
        *,
        succeeded: bool,
        target: str,
        detail: str = "",
    ) -> dict[str, Any]:
        """Append one verified outcome to update empirical fix rate and cross-target promotion."""
        st = self._stats.setdefault(remediation_id, {"attempts": 0, "successes": 0, "targets": set()})
        st["attempts"] += 1
        if succeeded:
            st["successes"] += 1
            st["targets"].add(target)
        self._append_event({
            "event": "outcome",
            "remediation_id": remediation_id,
            "succeeded": bool(succeeded),
            "target": target,
            "detail": detail[:300],
        })
        return {
            "remediation_id": remediation_id,
            "attempts": st["attempts"],
            "successes": st["successes"],
            "verified_targets": sorted(st["targets"]),
        }

    def match(self, error_text: str, *, fault_class: str | None = None) -> dict[str, Any]:
        """Match an error/traceback or diagnostic flag against all known executable remediations."""
        tier_rank = {"cross_target_default": 3, "scoped_candidate": 2, "draft_lesson": 1}
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


def match_known_faults(
    error_text: str,
    *,
    ledger_path: str | Path | None = None,
    fault_class: str | None = None,
) -> dict[str, Any]:
    """Convenience single-call fault lookup across built-in and persisted RSI remediations."""
    return FaultRSIRegistry(ledger_path).match(error_text, fault_class=fault_class)
