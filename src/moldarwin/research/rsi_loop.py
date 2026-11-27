"""Whole-MolDarwin end-to-end RSI cycle summarization, promotion gating, and active-physics bridge.

Weaves Recursive Self-Improvement (RSI) cleanly across every MolDarwin layer without
mutating leaf evidence records (Hard Constraint 2) or creating rigid monolithic workflows:
  1. ``summarize_rsi_cycle``: derives a compact unified RSI audit view across compute
     concurrency tuning, rescorer calibration, explicit-solvent MD control gates, RBFE
     convergence, and multi-round DMTA active learning.
  2. ``evaluate_rsi_promotion``: enforces MolDarwin's strict evidence ladder
     (``rejected`` -> ``draft_lesson`` -> ``scoped_candidate`` -> ``cross_target_default``)
     preventing single-target thresholds or unconverged pilots from becoming global defaults.
  3. ``build_active_evaluations_from_physics``: bridges verified per-molecule MD readouts
     or converged cycle-closed *anchored* RBFE MLE free energies into
     :class:`moldarwin.active.schema.Evaluation` objects for multi-round active learning.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from moldarwin.active.schema import Evaluation
from moldarwin.faults.attribution import Observation

RSI_CYCLE_SCHEMA = "moldarwin-rsi-cycle-summary/1"
RSI_PROMOTION_SCHEMA = "moldarwin-rsi-promotion/1"

#: Minimum independent targets showing paired gain with zero regressions required before
#: promoting any method/knob/skill to a cross-target default (Evidence: convention).
DEFAULT_MIN_INDEPENDENT_TARGETS: int = 2


def summarize_rsi_cycle(
    *,
    task_id: str,
    target: str,
    concurrency_tuning: Mapping[str, Any] | None = None,
    rescore_comparison: Mapping[str, Any] | None = None,
    md_control_gate: Mapping[str, Any] | None = None,
    docking_vs_md: Mapping[str, Any] | None = None,
    fep_network: Mapping[str, Any] | None = None,
    active_round_metrics: Sequence[Mapping[str, Any]] | None = None,
    skills_recalled: Sequence[str] = (),
    skills_generated: Sequence[str] = (),
) -> dict[str, Any]:
    """Derive a read-only end-to-end RSI summary spanning compute, oracle, physics, and DMTA."""
    layers: dict[str, Any] = {}
    blocking_gates: list[str] = []
    verified_gains: list[str] = []

    if concurrency_tuning is not None:
        spd = concurrency_tuning.get("speedup_vs_baseline")
        sel_k = concurrency_tuning.get("selected_jobs_per_gpu")
        verdict = concurrency_tuning.get("verdict")
        layers["compute_concurrency"] = {
            "selected_jobs_per_gpu": sel_k,
            "speedup_vs_baseline": spd,
            "verdict": verdict,
        }
        if verdict == "pack_multiple_jobs_per_gpu" and isinstance(spd, (int, float)) and spd > 1.0:
            verified_gains.append(f"gpu_packing_k={sel_k} ({spd:.2f}x throughput)")

    if rescore_comparison is not None:
        verdict = rescore_comparison.get("verdict")
        layers["rescoring_oracle"] = {
            "baseline": rescore_comparison.get("baseline_scorer"),
            "candidate": rescore_comparison.get("candidate_scorer"),
            "delta_roc_auc": rescore_comparison.get("delta_roc_auc"),
            "delta_ef5": rescore_comparison.get("delta_ef5"),
            "delta_top1_rmsd_A": rescore_comparison.get("delta_top1_rmsd_A"),
            "verdict": verdict,
        }
        if verdict == "improved_and_calibrated":
            verified_gains.append(
                f"rescorer={rescore_comparison.get('candidate_scorer')} "
                f"(dAUC={rescore_comparison.get('delta_roc_auc')})"
            )
        elif not rescore_comparison.get("candidate_passed_gate"):
            blocking_gates.append("rescoring_control_gate_failed")

    if md_control_gate is not None:
        passed = bool(md_control_gate.get("passed_gate"))
        layers["md_control_gate"] = {
            "replicas_evaluated": md_control_gate.get("replicas_evaluated"),
            "median_tail_rmsd_A": md_control_gate.get("median_tail_rmsd_A"),
            "median_pocket_occupancy": md_control_gate.get("median_pocket_occupancy"),
            "passed_gate": passed,
            "diagnosis": md_control_gate.get("diagnosis"),
        }
        if not passed:
            blocking_gates.append("md_crystal_control_gate_failed")

    if docking_vs_md is not None:
        layers["docking_vs_md_arbitration"] = {
            "n_candidates": docking_vs_md.get("n_candidates"),
            "stable_count": docking_vs_md.get("stable_count"),
            "drifted_count": docking_vs_md.get("drifted_count"),
            "spearman_docking_vs_rmsd": docking_vs_md.get("spearman_docking_vs_rmsd"),
        }

    if fep_network is not None:
        conv = bool(fep_network.get("network_converged"))
        layers["rbfe_fep_network"] = {
            "n_edges_valid": fep_network.get("n_edges_valid"),
            "n_edges_failed": fep_network.get("n_edges_failed"),
            "max_cycle_closure_abs_kcal_mol": fep_network.get("max_cycle_closure_abs_kcal_mol"),
            "network_converged": conv,
        }
        if conv:
            verified_gains.append(
                f"rbfe_converged (max_hysteresis={fep_network.get('max_cycle_closure_abs_kcal_mol')} kcal/mol)"
            )
        else:
            blocking_gates.append("rbfe_network_not_converged")

    if active_round_metrics:
        rounds = list(active_round_metrics)
        layers["active_dmta"] = {
            "rounds_completed": len(rounds),
            "first_round_best": rounds[0].get("best_value"),
            "latest_round_best": rounds[-1].get("best_value"),
            "total_evaluated": sum(int(r.get("evaluated_count") or 0) for r in rounds),
        }

    return {
        "schema": RSI_CYCLE_SCHEMA,
        "derived_view_only": True,
        "task_id": task_id,
        "target": target,
        "layers_recorded": sorted(layers.keys()),
        "layers": layers,
        "verified_gains": verified_gains,
        "blocking_gates": blocking_gates,
        "all_recorded_gates_passed": not blocking_gates,
        "skills_recalled": list(skills_recalled),
        "skills_generated": list(skills_generated),
    }


def evaluate_rsi_promotion(
    artifact_name: str,
    target_validations: Sequence[Mapping[str, Any]],
    *,
    artifact_kind: str = "method",
    min_independent_targets: int = DEFAULT_MIN_INDEPENDENT_TARGETS,
) -> dict[str, Any]:
    """Decide safe RSI promotion tier from paired multi-target evidence.

    Each entry in ``target_validations`` requires:
      - ``target`` (str)
      - ``paired_gain`` (bool)
      - ``gate_passed`` (bool)
      - ``warrant_regression`` (bool, default False)
      - ``independent_validation`` (bool, default False)
    """
    if not target_validations:
        return {
            "schema": RSI_PROMOTION_SCHEMA,
            "artifact_name": artifact_name,
            "artifact_kind": artifact_kind,
            "promotion_tier": "rejected_or_unverified",
            "reason": "no paired validation records supplied",
            "targets_evaluated": 0,
        }

    regressed_targets: list[str] = []
    passing_gain_targets: set[str] = set()
    independent_gain_targets: set[str] = set()
    all_targets: set[str] = set()

    for row in target_validations:
        tgt = str(row["target"])
        all_targets.add(tgt)
        if bool(row.get("warrant_regression", False)):
            regressed_targets.append(tgt)
            continue
        if bool(row.get("paired_gain")) and bool(row.get("gate_passed")):
            passing_gain_targets.add(tgt)
            if bool(row.get("independent_validation", False)):
                independent_gain_targets.add(tgt)

    if regressed_targets:
        tier = "rejected_or_unverified"
        reason = f"warrant or quality regression observed on {sorted(set(regressed_targets))}"
    elif len(independent_gain_targets) >= min_independent_targets:
        tier = "cross_target_default"
        reason = (
            f"paired independent gain with passing gates on {len(independent_gain_targets)} "
            f"distinct targets ({sorted(independent_gain_targets)})"
        )
    elif passing_gain_targets:
        tier = "scoped_candidate"
        reason = (
            f"paired gain with passing gates on {sorted(passing_gain_targets)}; "
            f"needs >= {min_independent_targets} independent targets before default promotion"
        )
    else:
        tier = "draft_lesson"
        reason = "diagnostic or single-run observation only; no calibrated paired gain established"

    return {
        "schema": RSI_PROMOTION_SCHEMA,
        "artifact_name": artifact_name,
        "artifact_kind": artifact_kind,
        "promotion_tier": tier,
        "reason": reason,
        "targets_evaluated": len(all_targets),
        "passing_gain_targets": sorted(passing_gain_targets),
        "independent_gain_targets": sorted(independent_gain_targets),
        "regressed_targets": sorted(set(regressed_targets)),
        "min_independent_targets_for_default": min_independent_targets,
        "threshold_evidence": "convention",
    }


def build_active_evaluations_from_physics(
    *,
    endpoint_id: str,
    md_readouts: Sequence[Mapping[str, Any]] | None = None,
    fep_network: Mapping[str, Any] | None = None,
    cost_per_evaluation: float = 1.0,
    md_metric: str = "ligand_rmsd_last_20pct_A",
) -> list[Evaluation]:
    """Convert audited PRISM MD or converged anchored RBFE readouts into active-learning Evaluations.

    Enforces strict epistemic hygiene:
      - Never admits unconverged RBFE networks as ``status='ok'`` evaluations.
      - Labels anchored RBFE values transparently with ``units='kcal/mol_rel_to_anchor'``
        and anchor provenance so relative free energies are never confused with absolute dG.
    """
    if (md_readouts is None) == (fep_network is None):
        raise ValueError("supply exactly one of md_readouts or fep_network")

    evaluations: list[Evaluation] = []

    if md_readouts is not None:
        for row in md_readouts:
            cid = str(row["candidate_id"])
            val = row.get(md_metric)
            occ = row.get("pocket_contact_occupancy")
            is_valid = val is not None and math.isfinite(float(val))
            checks = [
                Observation(
                    code="F_STAGE_NEVER_RAN",
                    fired=not is_valid,
                    detail=f"{md_metric}={val}, occupancy={occ}",
                )
            ]
            if occ is not None and math.isfinite(float(occ)):
                checks.append(
                    Observation(
                        code="F_POSE_LEFT_THE_SITE",
                        fired=float(occ) < 0.5,
                        detail=f"pocket_contact_occupancy={occ}",
                    )
                )
            evaluations.append(
                Evaluation(
                    candidate_id=cid,
                    endpoint_id=endpoint_id,
                    value=float(val) if is_valid else None,
                    units="A" if "rmsd" in md_metric else "dimensionless",
                    cost=float(cost_per_evaluation),
                    status="ok" if is_valid else "failed",
                    checks=tuple(checks),
                    provenance={
                        "source_schema": row.get("schema", "moldarwin-md-readout/1"),
                        "metric": md_metric,
                        "pocket_contact_occupancy": occ,
                        "trajectory_sha256": row.get("trajectory_sha256"),
                    },
                )
            )
        return evaluations

    assert fep_network is not None
    converged = bool(fep_network.get("network_converged"))
    rel_dg = fep_network.get("relative_dg_kcal_mol")
    anchor = fep_network.get("anchor_ligand")
    max_hyst = fep_network.get("max_cycle_closure_abs_kcal_mol")
    if not converged or not isinstance(rel_dg, Mapping):
        raise ValueError(
            "refusing to ingest unconverged or empty FEP network into active learning "
            f"(network_converged={converged}, max_cycle_closure_abs_kcal_mol={max_hyst})"
        )

    for cid, val in sorted(rel_dg.items()):
        if str(cid) == str(anchor):
            continue  # Anchor defines the additive zero offset; do not treat as an independent readout.
        evaluations.append(
            Evaluation(
                candidate_id=str(cid),
                endpoint_id=endpoint_id,
                value=float(val),
                units="kcal/mol_rel_to_anchor",
                cost=float(cost_per_evaluation),
                uncertainty=float(max_hyst) if isinstance(max_hyst, (int, float)) else None,
                status="ok",
                checks=(
                    Observation(
                        code="F_CONVERGENCE_NOT_ASSESSABLE",
                        fired=False,
                        detail=f"anchor={anchor}, max_cycle_closure_kcal={max_hyst}",
                    ),
                ),
                provenance={
                    "source_schema": fep_network.get("schema", "moldarwin-fep-network/1"),
                    "anchor_ligand": anchor,
                    "max_cycle_closure_abs_kcal_mol": max_hyst,
                    "n_edges_valid": fep_network.get("n_edges_valid"),
                },
            )
        )
    return evaluations
