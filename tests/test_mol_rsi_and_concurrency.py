"""Tests for GPU concurrency packing RSI and whole-MolDarwin end-to-end RSI loop."""

from __future__ import annotations

import pytest

from moldarwin.active.schema import CampaignSpec, Candidate, Endpoint
from moldarwin.active.store import CampaignStore
from moldarwin.research.rsi_loop import (
    RSI_CYCLE_SCHEMA,
    RSI_PROMOTION_SCHEMA,
    build_active_evaluations_from_physics,
    evaluate_rsi_promotion,
    summarize_rsi_cycle,
)
from moldarwin.runtime.concurrency import (
    CONCURRENCY_PLAN_SCHEMA,
    CONCURRENCY_TUNING_SCHEMA,
    plan_gpu_packing,
    select_optimal_concurrency,
)


def test_gpu_packing_assigns_disjoint_cpu_cores_and_selects_optimal_k():
    plan = plan_gpu_packing(
        idle_gpus=[0, 1, 2, 3, 4, 5, 6, 7],
        cpu_cores=96,
        mem_per_job_mb=700.0,
        gpu_vram_mb=98304.0,
        single_job_sm_util_pct=32.0,
    )
    assert plan["schema"] == CONCURRENCY_PLAN_SCHEMA
    assert plan["jobs_per_gpu"] == 2
    assert plan["total_concurrent_slots"] == 16
    assert plan["omp_threads_per_slot"] == 6
    # Verify every slot gets a distinct non-overlapping CPU core offset
    offsets = [s["pinoffset"] for s in plan["slots"]]
    assert len(set(offsets)) == 16
    assert max(offsets) + plan["omp_threads_per_slot"] <= 96

    # Micro-benchmark: k=2 gives ~1.72x aggregate ns/day, k=3 has a failed job -> rejected
    tuning = select_optimal_concurrency(
        [
            {"jobs_per_gpu": 1, "wall_s": 60.0, "work_completed_per_job": 0.25, "gpu_util_pct": 33.0, "work_unit": "ns"},
            {"jobs_per_gpu": 2, "wall_s": 70.0, "work_completed_per_job": 0.25, "gpu_util_pct": 68.0, "work_unit": "ns"},
            {"jobs_per_gpu": 3, "wall_s": 90.0, "work_completed_per_job": 0.25, "failed_jobs": 1, "work_unit": "ns"},
        ]
    )
    assert tuning["schema"] == CONCURRENCY_TUNING_SCHEMA
    assert tuning["selected_jobs_per_gpu"] == 2
    assert tuning["verdict"] == "pack_multiple_jobs_per_gpu"
    assert tuning["speedup_vs_baseline"] == pytest.approx(1.714, abs=0.01)
    assert len(tuning["rejected"]) == 1

    # Marginal gain (< 1.10x) stays at baseline k=1
    marginal = select_optimal_concurrency([
        {"jobs_per_gpu": 1, "wall_s": 60.0, "work_completed_per_job": 1.0},
        {"jobs_per_gpu": 2, "wall_s": 115.0, "work_completed_per_job": 1.0},
    ])
    assert marginal["selected_jobs_per_gpu"] == 1
    assert marginal["verdict"] == "keep_baseline_marginal_gain"


def test_unified_rsi_cycle_promotion_ladder_and_active_physics_bridge(tmp_path):
    summary = summarize_rsi_cycle(
        task_id="tyk2-flagship",
        target="TYK2",
        concurrency_tuning={"selected_jobs_per_gpu": 2, "speedup_vs_baseline": 1.72, "verdict": "pack_multiple_jobs_per_gpu"},
        rescore_comparison={"baseline_scorer": "vina", "candidate_scorer": "gnina_cnn_vs", "delta_roc_auc": 0.61, "delta_ef5": 8.71, "delta_top1_rmsd_A": -3.1, "candidate_passed_gate": True, "verdict": "improved_and_calibrated"},
        md_control_gate={"replicas_evaluated": 3, "median_tail_rmsd_A": 1.067, "median_pocket_occupancy": 1.0, "passed_gate": True, "diagnosis": "control_stable_protocol_calibrated"},
        fep_network={"n_edges_valid": 8, "n_edges_failed": 0, "max_cycle_closure_abs_kcal_mol": 0.42, "network_converged": True},
        active_round_metrics=[{"best_value": -7.2, "evaluated_count": 6}, {"best_value": -9.4, "evaluated_count": 6}],
        skills_recalled=["prism-physics", "autonomous-planning"],
        skills_generated=["tyk2-rbfe-packed-20win"],
    )
    assert summary["schema"] == RSI_CYCLE_SCHEMA
    assert summary["derived_view_only"] is True
    assert summary["all_recorded_gates_passed"] is True
    assert len(summary["verified_gains"]) == 3

    # Promotion ladder: 1 target -> scoped_candidate; 2 independent targets -> cross_target_default; any regression -> rejected
    p1 = evaluate_rsi_promotion("gnina_cnn_vs", [{"target": "SND1", "paired_gain": True, "gate_passed": True, "independent_validation": True}])
    assert p1["schema"] == RSI_PROMOTION_SCHEMA
    assert p1["promotion_tier"] == "scoped_candidate"

    p2 = evaluate_rsi_promotion(
        "gnina_cnn_vs",
        [
            {"target": "SND1", "paired_gain": True, "gate_passed": True, "independent_validation": True},
            {"target": "TYK2", "paired_gain": True, "gate_passed": True, "independent_validation": True},
        ],
    )
    assert p2["promotion_tier"] == "cross_target_default"

    p_reg = evaluate_rsi_promotion(
        "bad_knob",
        [
            {"target": "SND1", "paired_gain": True, "gate_passed": True, "independent_validation": True},
            {"target": "KEAP1", "paired_gain": False, "gate_passed": False, "warrant_regression": True},
        ],
    )
    assert p_reg["promotion_tier"] == "rejected_or_unverified"

    # Active-learning bridge: refuses unconverged FEP network, accepts converged anchored network & MD readouts
    with pytest.raises(ValueError, match="unconverged"):
        build_active_evaluations_from_physics(
            endpoint_id="rbfe_anchored",
            fep_network={"network_converged": False, "relative_dg_kcal_mol": {"ejm_31": 0.0, "ejm_42": -0.2}},
        )

    evals = build_active_evaluations_from_physics(
        endpoint_id="rbfe_anchored",
        fep_network={
            "schema": "moldarwin-fep-network/1",
            "network_converged": True,
            "anchor_ligand": "ejm_31",
            "max_cycle_closure_abs_kcal_mol": 0.35,
            "n_edges_valid": 8,
            "relative_dg_kcal_mol": {"ejm_31": 0.0, "ejm_42": -0.25, "ejm_46": -1.60},
        },
        cost_per_evaluation=5.0,
    )
    assert [e.candidate_id for e in evals] == ["ejm_42", "ejm_46"]  # anchor excluded!
    assert all(e.units == "kcal/mol_rel_to_anchor" for e in evals)

    # Verify compatibility with real CampaignStore
    store = CampaignStore(tmp_path / "dmta.sqlite")
    store.configure(
        CampaignSpec(objective="rbfe_anchored", budget=100.0, cost_unit="gpu_min", representation="fp"),
        [Endpoint(id="rbfe_anchored", target="TYK2", quantity="anchored_relative_dg", units="kcal/mol_rel_to_anchor", protocol="prism_20win", cost=5.0, requires_handoff=False)],
    )
    store.add_candidates([
        Candidate(id="ejm_42", smiles="CC", features=(1.0, 0.0)),
        Candidate(id="ejm_46", smiles="CCC", features=(0.0, 1.0)),
    ])
    for ev in evals:
        store.import_evaluation(ev, source_id=f"fep:{ev.candidate_id}")
    assert len(store.observations(admitted_only=True)) == 2
