"""Tests for MolDarwin 2.0 core engines: subagents, adaptive physics, fault RSI, and evolution."""

from __future__ import annotations

from pathlib import Path

from moldarwin.evolve import (
    EVOLUTION_GENERATION_SCHEMA,
    PROTOCOL_TOURNAMENT_SCHEMA,
    prune_protocol_branches,
    rank_evolution_generation,
)
from moldarwin.physics import (
    ADAPTIVE_LAMBDA_SCHEMA,
    PACKED_FEP_RUNNER_SCHEMA,
    WINDOW_EXTENSION_SCHEMA,
    check_property_shortcut_and_mmp,
    plan_selective_window_extensions,
    refine_lambda_schedule_from_overlap,
    render_packed_fep_runner,
)
from moldarwin.research.fault_rsi import FAULT_RSI_SCHEMA, FaultRSIRegistry, match_known_faults
from moldarwin.runtime.concurrency import plan_gpu_packing
from moldarwin.runtime.subagents import (
    SUBAGENT_BRIEF_SCHEMA,
    SUBAGENT_PARTITION_SCHEMA,
    build_subagent_brief,
    partition_resources_for_subagents,
    validate_subagent_handoff,
)


def test_subagent_resource_partitioner_is_strictly_disjoint_and_enforces_compact_handoff(tmp_path):
    fake_env = {
        "cpu_cores": 96,
        "gpus": {
            "idle_gpus": [0, 1, 2, 3, 4, 5, 6, 7],
            "devices": [{"index": i, "memory_total_mb": 98304} for i in range(8)],
        },
    }
    part = partition_resources_for_subagents(
        fake_env,
        [
            {"name": "intake", "role": "intake", "needs_gpu": False},
            {"name": "branch_tyk2", "role": "gpu_branch", "gpu_weight": 1.0, "jobs_per_gpu": 2},
            {"name": "branch_jak2", "role": "gpu_branch", "gpu_weight": 1.0, "jobs_per_gpu": 2},
            {"name": "verifier", "role": "verifier", "needs_gpu": False},
        ],
        work_root=tmp_path,
        total_wall_clock_min=180.0,
    )
    assert part["schema"] == SUBAGENT_PARTITION_SCHEMA
    by_name = {lease["name"]: lease for lease in part["leases"]}
    assert set(by_name["branch_tyk2"]["gpus"]).isdisjoint(set(by_name["branch_jak2"]["gpus"]))
    assert len(by_name["branch_tyk2"]["gpus"]) == 4
    assert len(by_name["branch_jak2"]["gpus"]) == 4
    assert by_name["intake"]["gpus"] == []

    # Verify global CPU pinoffsets across BOTH GPU branches are completely disjoint!
    pins_a = {s["pinoffset"] for s in by_name["branch_tyk2"]["packing"]["slots"]}
    pins_b = {s["pinoffset"] for s in by_name["branch_jak2"]["packing"]["slots"]}
    assert pins_a.isdisjoint(pins_b)
    assert len(pins_a) == 8 and len(pins_b) == 8

    brief = build_subagent_brief(
        by_name["branch_tyk2"],
        objective="Run converged TYK2 RBFE edges",
        done_criteria=["overlap_min >= 0.03", "cycle_closure <= 1.0 kcal/mol"],
    )
    assert brief["schema"] == SUBAGENT_BRIEF_SCHEMA
    assert brief["resource_lease"]["jobs_per_gpu"] == 2

    ok_handoff = validate_subagent_handoff({
        "status": "completed",
        "summary": "8 TYK2 edges converged.",
        "metrics": {"rmse_kcal": 0.78, "overlap_min": 0.06},
        "artifacts": {"edges_csv": "subagents/branch_tyk2/edges.csv"},
        "failures": [],
    })
    assert ok_handoff["valid"] is True

    bloated = validate_subagent_handoff(
        {
            "status": "completed",
            "summary": "x" * 4000,
            "metrics": {},
            "artifacts": {},
            "failures": [],
        },
        max_bytes=2048,
    )
    assert bloated["valid"] is False
    assert any("exceeds max_bytes" in msg for msg in bloated["issues"])


def test_adaptive_lambda_refinement_window_extensions_and_packed_runner(tmp_path):
    # Simulate Run 5's exact failure: 11 windows with severe endpoint overlap collapse!
    lams = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    ovs = [0.0005, 0.08, 0.15, 0.20, 0.22, 0.18, 0.16, 0.12, 0.09, 0.0012]
    ref = refine_lambda_schedule_from_overlap(lams, ovs, min_overlap=0.05, max_new_windows=8)
    assert ref["schema"] == ADAPTIVE_LAMBDA_SCHEMA
    assert ref["converged"] is False
    assert ref["added_windows"] >= 2
    assert ref["new_count"] == len(ref["refined_lambdas"])
    # Verify new points were added strictly inside the failing endpoint intervals [0, 0.1] and [0.9, 1.0]
    assert any(0.0 < x < 0.1 for x in ref["refined_lambdas"])
    assert any(0.9 < x < 1.0 for x in ref["refined_lambdas"])
    assert not any(0.4 < x < 0.5 for x in ref["refined_lambdas"])

    # Selective extension only touches unconverged windows
    ext = plan_selective_window_extensions(
        [
            {"window_id": "window_00", "current_ns": 1.5, "half_delta_kcal": 0.12, "uncertainty_kcal": 0.08},
            {"window_id": "window_05", "current_ns": 1.5, "half_delta_kcal": 0.88, "uncertainty_kcal": 0.19},
            {"window_id": "window_19", "current_ns": 6.0, "half_delta_kcal": 0.95, "uncertainty_kcal": 0.30},
        ],
        extend_ns=1.0,
        max_total_ns=6.0,
    )
    assert ext["schema"] == WINDOW_EXTENSION_SCHEMA
    assert ext["converged_windows"] == ["window_00"]
    assert [w["window_id"] for w in ext["windows_to_extend"]] == ["window_05"]
    assert ext["windows_to_extend"][0]["gmx_convert_tpr_arg"] == "-extend 1000"
    assert ext["at_cap_windows"] == ["window_19"]

    # Packed GPU runner emits disjoint -pinoffset slots
    pack = plan_gpu_packing([0, 1, 2, 3], cpu_cores=48, jobs_per_gpu=2)
    run_rep = render_packed_fep_runner(tmp_path / "bound" / "repeat1", pack, update_mode="gpu")
    assert run_rep["schema"] == PACKED_FEP_RUNNER_SCHEMA
    assert run_rep["total_slots"] == 8
    txt = Path(run_rep["script_path"]).read_text(encoding="utf-8")
    assert "SLOT_GPUS=(0 0 1 1 2 2 3 3)" in txt
    assert "-update gpu" in txt
    assert "-pinoffset" in txt


def test_fault_indexed_code_rsi_matches_live_bugs_and_promotes_across_targets(tmp_path):
    hit = match_known_faults("ValueError: invalid literal for int() with base 10: 'N' in resolve_coord_source")
    assert hit["schema"] == FAULT_RSI_SCHEMA
    assert hit["match_count"] >= 1
    assert hit["matches"][0]["remediation_id"] == "prism_fep_sdf_gro_dispatch"

    reg = FaultRSIRegistry(tmp_path / "fault_rsi.jsonl")
    reg.register_remediation(
        remediation_id="custom_lincs_dt_fix",
        pattern=r"LINCS WARNING.*relative constraint deviation",
        fault_class="md_stability",
        entrypoint="moldarwin.physics.prism_bridge:patch_gromacs2026_artifacts",
        summary="Use staged NPT release equilibration before production.",
    )
    reg.record_outcome("custom_lincs_dt_fix", succeeded=True, target="TYK2")
    m1 = reg.match("Step 100: LINCS WARNING relative constraint deviation > 1000")
    assert m1["matches"][0]["tier"] == "scoped_candidate"

    # Second independent target promotes automatically to cross_target_default!
    reg.record_outcome("custom_lincs_dt_fix", succeeded=True, target="KEAP1")
    reloaded = FaultRSIRegistry(tmp_path / "fault_rsi.jsonl")
    m2 = reloaded.match("LINCS WARNING relative constraint deviation")
    assert m2["matches"][0]["tier"] == "cross_target_default"
    assert m2["matches"][0]["verified_targets"] == ["KEAP1", "TYK2"]


def test_evolution_selectivity_pareto_protocol_pruning_and_shortcut_check():
    # Selectivity Pareto ranking: M2 is slightly weaker on target (-9.2 vs -9.5) but MUCH more selective (-3.2 vs -0.5) & clean!
    gen = rank_evolution_generation(
        [
            {"candidate_id": "M1_promiscuous", "target_dg_kcal": -9.5, "offtarget_dg_kcal": -9.0, "uncertainty_kcal": 0.2, "soft_flag_count": 2},
            {"candidate_id": "M2_selective", "target_dg_kcal": -9.2, "offtarget_dg_kcal": -6.0, "uncertainty_kcal": 0.2, "soft_flag_count": 0},
            {"candidate_id": "M3_dominated", "target_dg_kcal": -8.0, "offtarget_dg_kcal": -7.5, "uncertainty_kcal": 0.3, "soft_flag_count": 1},
            {"candidate_id": "M4_unstable", "target_dg_kcal": -11.0, "offtarget_dg_kcal": -5.0, "hard_red_flags": ["acyl_halide"]},
        ],
        generation=2,
        top_k=2,
    )
    assert gen["schema"] == EVOLUTION_GENERATION_SCHEMA
    assert gen["has_selectivity_objective"] is True
    assert "M2_selective" in gen["pareto_front"]
    assert "M3_dominated" not in gen["pareto_front"]
    assert gen["selected_for_next_generation"][0] == "M2_selective"
    assert gen["rejected_count"] == 1

    # Protocol branch pruning reclaims GPUs from failed & dominated branches
    tourn = prune_protocol_branches(
        [
            {"branch_id": "b_propka_water", "gate_passed": True, "primary_score": 0.94, "gpus_leased": [0, 1]},
            {"branch_id": "b_default_nowat", "gate_passed": False, "primary_score": 0.45, "gpus_leased": [2, 3], "failure_reason": "crystal_drifted_7.8A"},
            {"branch_id": "b_vinardo", "gate_passed": True, "primary_score": 0.72, "gpus_leased": [4, 5]},
        ],
        max_survivors=1,
    )
    assert tourn["schema"] == PROTOCOL_TOURNAMENT_SCHEMA
    assert [s["branch_id"] for s in tourn["survivors"]] == ["b_propka_water"]
    assert tourn["freed_gpus"] == [2, 3, 4, 5]

    # Lean property-shortcut sanity check catches MW bias
    biased = [
        {"id": f"p{i}", "is_positive": True, "score": -9.0 - 0.1 * i, "mw": 480 + i} for i in range(5)
    ] + [
        {"id": f"n{i}", "is_positive": False, "score": -6.0 - 0.1 * i, "mw": 250 + i} for i in range(10)
    ]
    sanity = check_property_shortcut_and_mmp(biased, higher_better=False)
    assert sanity["property_shortcut_flag"] is True
    assert sanity["property_shortcut_aucs"]["mw"] == 1.0
