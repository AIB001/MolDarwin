"""Tie-aware multi-mode pose rescoring calibration and paired RSI comparison.

Addresses the classic shallow-PPI failure mode observed live on SND1-MTDH (7KNW/7KNX,
2026-11-26): Uni-Dock sampled the true crystal pose (1.11 A best-of-modes RMSD), but Vina
ranked it poorly (4.11 A top-1 RMSD, ROC-AUC 0.33, EF5% 0.0). Separates pose *sampling*
from pose *ranking* and evaluates candidate rescorers (Gnina CNN, Vinardo, AD4, MM-PBSA,
3D shape+pharmacophore) on identical control panels for MolDarwin RSI promotion.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

RESCORE_EVAL_SCHEMA = "moldarwin-rescore-calibration/1"
RESCORE_COMPARE_SCHEMA = "moldarwin-rescore-rsi-compare/1"

#: Default control-calibration bar (Evidence: convention, matching SND1-MTDH run gate).
DEFAULT_TOP1_RMSD_CUTOFF_A: float = 2.0
DEFAULT_AUC_GATE: float = 0.70
DEFAULT_EF5_GATE: float = 1.0


def _midranks(values: list[float], *, higher_better: bool) -> list[float]:
    """1-based average ranks (rank 1 = best) with exact midrank tie handling."""
    n = len(values)
    order = sorted(range(n), key=lambda i: (-values[i] if higher_better else values[i], i))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i + 1
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        avg_rank = 0.5 * ((i + 1) + j)
        for k in range(i, j):
            ranks[order[k]] = avg_rank
        i = j
    return ranks


def _tie_aware_ef(labels: list[bool], values: list[float], *, fraction: float, higher_better: bool) -> float:
    """Expected fractional occupancy EF at ceil(N * fraction) slots under ties."""
    n = len(labels)
    n_pos = sum(labels)
    if n == 0 or n_pos == 0:
        return 0.0
    cutoff_slots = max(1, int(math.ceil(n * fraction)))
    order = sorted(range(n), key=lambda i: (-values[i] if higher_better else values[i], i))

    selected_pos = 0.0
    filled = 0
    i = 0
    while i < n and filled < cutoff_slots:
        j = i + 1
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        group = order[i:j]
        group_size = len(group)
        group_pos = sum(1 for idx in group if labels[idx])
        take = min(group_size, cutoff_slots - filled)
        selected_pos += group_pos * (take / group_size)
        filled += take
        i = j

    expected_random = n_pos * (cutoff_slots / n)
    return selected_pos / expected_random if expected_random > 0 else 0.0


def evaluate_rescorer_panel(
    records: Sequence[dict[str, Any]],
    *,
    scorer_name: str,
    higher_better: bool = False,
    top_rmsd_cutoff_A: float = DEFAULT_TOP1_RMSD_CUTOFF_A,
    auc_gate: float = DEFAULT_AUC_GATE,
    ef5_gate: float = DEFAULT_EF5_GATE,
) -> dict[str, Any]:
    """Evaluate one scoring/rescoring method on a paired control panel.

    Each record requires:
      - ``id`` (str)
      - ``is_positive`` (bool)
      - ``score`` (float | None; ``None`` counts as a scoring failure in denominator)
    Optional cognate pose fields (for crystal positives):
      - ``top1_rmsd_A`` (float)
      - ``best_mode_rmsd_A`` (float)
    """
    total = len(records)
    scored: list[dict[str, Any]] = []
    failed_ids: list[str] = []

    for row in records:
        cid = str(row["id"])
        val = row.get("score")
        if val is None or (isinstance(val, float) and not math.isfinite(val)):
            failed_ids.append(cid)
            continue
        scored.append({
            "id": cid,
            "is_positive": bool(row["is_positive"]),
            "score": float(val),
            "top1_rmsd_A": float(row["top1_rmsd_A"]) if row.get("top1_rmsd_A") is not None else None,
            "best_mode_rmsd_A": float(row["best_mode_rmsd_A"]) if row.get("best_mode_rmsd_A") is not None else None,
        })

    n_scored = len(scored)
    labels = [r["is_positive"] for r in scored]
    values = [r["score"] for r in scored]
    n_pos = sum(labels)
    n_neg = n_scored - n_pos

    roc_auc: float | None = None
    ef1: float | None = None
    ef5: float | None = None
    pos_percentiles: dict[str, float] = {}

    if n_pos > 0 and n_neg > 0:
        ranks = _midranks(values, higher_better=higher_better)
        # Mann-Whitney U with rank 1 = best -> smaller rank sum for positives means higher AUC.
        sum_pos_ranks = sum(r for r, is_p in zip(ranks, labels, strict=True) if is_p)
        u_pos = n_pos * n_neg - (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0)
        roc_auc = round(u_pos / (n_pos * n_neg), 4)
        ef1 = round(_tie_aware_ef(labels, values, fraction=0.01, higher_better=higher_better), 4)
        ef5 = round(_tie_aware_ef(labels, values, fraction=0.05, higher_better=higher_better), 4)
        for row, rk in zip(scored, ranks, strict=True):
            if row["is_positive"]:
                pos_percentiles[row["id"]] = round(100.0 * rk / n_scored, 2)

    cognate_top1 = [r["top1_rmsd_A"] for r in scored if r["is_positive"] and r["top1_rmsd_A"] is not None]
    cognate_best = [r["best_mode_rmsd_A"] for r in scored if r["is_positive"] and r["best_mode_rmsd_A"] is not None]
    max_top1_rmsd = round(max(cognate_top1), 3) if cognate_top1 else None
    max_best_rmsd = round(max(cognate_best), 3) if cognate_best else None

    coverage = round(n_scored / total, 4) if total else 0.0
    sampling_ok = (max_best_rmsd <= top_rmsd_cutoff_A) if max_best_rmsd is not None else None
    top1_pose_ok = (max_top1_rmsd <= top_rmsd_cutoff_A) if max_top1_rmsd is not None else None

    gate_checks = {
        "coverage_ge_95pct": coverage >= 0.95,
        "all_positives_scored": n_pos == sum(1 for r in records if bool(r["is_positive"])) and n_pos > 0,
        "roc_auc_passed": roc_auc is not None and roc_auc >= auc_gate,
        "ef5_passed": ef5 is not None and ef5 > ef5_gate,
        "top1_pose_passed": top1_pose_ok if top1_pose_ok is not None else True,
    }
    passed_gate = all(gate_checks.values())

    diagnosis = "calibrated_go"
    if not passed_gate:
        if sampling_ok is True and top1_pose_ok is False:
            diagnosis = "sampling_succeeded_but_ranking_failed"
        elif sampling_ok is False:
            diagnosis = "pose_sampling_failed"
        else:
            diagnosis = "enrichment_failed"

    return {
        "schema": RESCORE_EVAL_SCHEMA,
        "scorer_name": scorer_name,
        "higher_better": higher_better,
        "total_inputs": total,
        "scored_count": n_scored,
        "failed_count": len(failed_ids),
        "failed_ids": failed_ids[:50],
        "coverage": coverage,
        "positives_scored": n_pos,
        "negatives_scored": n_neg,
        "roc_auc": roc_auc,
        "ef1": ef1,
        "ef5": ef5,
        "positive_percentiles_lower_is_better": pos_percentiles,
        "cognate_max_top1_rmsd_A": max_top1_rmsd,
        "cognate_max_best_mode_rmsd_A": max_best_rmsd,
        "sampling_succeeded": sampling_ok,
        "top1_pose_recovered": top1_pose_ok,
        "gate_checks": gate_checks,
        "passed_gate": passed_gate,
        "diagnosis": diagnosis,
        "gates": {
            "top_rmsd_cutoff_A": top_rmsd_cutoff_A,
            "auc_gate": auc_gate,
            "ef5_gate": ef5_gate,
            "evidence": "convention",
        },
    }


def compare_rescorers_for_rsi(
    baseline_eval: dict[str, Any],
    candidate_eval: dict[str, Any],
) -> dict[str, Any]:
    """Paired RSI verdict comparing a candidate rescorer against a baseline on the same panel."""
    for label, rep in (("baseline", baseline_eval), ("candidate", candidate_eval)):
        if rep.get("schema") != RESCORE_EVAL_SCHEMA:
            raise ValueError(f"{label} must be a {RESCORE_EVAL_SCHEMA} report")

    if baseline_eval["total_inputs"] != candidate_eval["total_inputs"]:
        raise ValueError("paired rescorer comparison requires identical panel denominators")

    b_auc = baseline_eval["roc_auc"]
    c_auc = candidate_eval["roc_auc"]
    b_ef5 = baseline_eval["ef5"]
    c_ef5 = candidate_eval["ef5"]
    b_rmsd = baseline_eval["cognate_max_top1_rmsd_A"]
    c_rmsd = candidate_eval["cognate_max_top1_rmsd_A"]

    delta_auc = round(c_auc - b_auc, 4) if (b_auc is not None and c_auc is not None) else None
    delta_ef5 = round(c_ef5 - b_ef5, 4) if (b_ef5 is not None and c_ef5 is not None) else None
    delta_rmsd = round(c_rmsd - b_rmsd, 3) if (b_rmsd is not None and c_rmsd is not None) else None

    improved = bool(
        (delta_auc is not None and delta_auc > 0.05)
        or (delta_ef5 is not None and delta_ef5 > 0.5)
        or (delta_rmsd is not None and delta_rmsd < -0.5)
    )
    regressed = bool(
        (delta_auc is not None and delta_auc < -0.05)
        or (candidate_eval["coverage"] < baseline_eval["coverage"] - 0.05)
    )

    if candidate_eval["passed_gate"] and (not baseline_eval["passed_gate"] or improved):
        verdict = "improved_and_calibrated"
    elif regressed:
        verdict = "regressed"
    elif improved:
        verdict = "improved_but_uncalibrated"
    else:
        verdict = "no_meaningful_gain"

    return {
        "schema": RESCORE_COMPARE_SCHEMA,
        "baseline_scorer": baseline_eval["scorer_name"],
        "candidate_scorer": candidate_eval["scorer_name"],
        "panel_size": baseline_eval["total_inputs"],
        "baseline_passed_gate": baseline_eval["passed_gate"],
        "candidate_passed_gate": candidate_eval["passed_gate"],
        "delta_roc_auc": delta_auc,
        "delta_ef5": delta_ef5,
        "delta_top1_rmsd_A": delta_rmsd,
        "verdict": verdict,
        "adoption_note": (
            "Validates control rescue on this target panel only; promote as a reusable "
            "default only after paired independent validation across targets."
        ),
    }
