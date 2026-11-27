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

    # Second independent target promotes automatically to cross_target_default for io_repair!
    reg.record_outcome("custom_lincs_dt_fix", succeeded=True, target="KEAP1")
    reloaded = FaultRSIRegistry(tmp_path / "fault_rsi.jsonl")
    m2 = reloaded.match("LINCS WARNING relative constraint deviation")
    assert m2["matches"][0]["tier"] == "cross_target_default"
    assert m2["matches"][0]["verified_targets"] == ["KEAP1", "TYK2"]
    assert m2["matches"][0]["impact_class"] == "io_repair"
    assert len(m2["matches"][0]["remediation_digest"]) == 64


def test_fault_rsi_physics_perturbation_and_input_filter_admission_gates_and_journal(tmp_path):
    """Completion != admission: physics_perturbation needs Tier-1 equivalence, input_filter needs
    logged coverage loss, and applied remediations bind into ResearchJournal."""
    from moldarwin.active import CampaignSpec, CampaignStore, Endpoint
    from moldarwin.research import ResearchJournal

    reg = FaultRSIRegistry(tmp_path / "fault_rsi_gated.jsonl")

    # 1. physics_perturbation cannot promote on completion alone across 2 targets
    reg.record_outcome("gmx2026_fep_dummy_mass_gpu_update", succeeded=True, target="TYK2")
    reg.record_outcome("gmx2026_fep_dummy_mass_gpu_update", succeeded=True, target="CDK2")
    rec_unverified = reg.get_remediation("gmx2026_fep_dummy_mass_gpu_update")
    assert rec_unverified["tier"] == "scoped_candidate"
    assert rec_unverified["promotion_blocked_reason"] == "awaiting_tier1_physical_equivalence_verification"

    # Passing Tier-1 CPU-vs-GPU ddG equivalence unlocks cross_target_default
    reg.record_outcome(
        "gmx2026_fep_dummy_mass_gpu_update",
        succeeded=True,
        target="TYK2",
        equivalence_verified=True,
        equivalence_evidence="|ddG_gpu - ddG_cpu| = 0.08 kcal/mol <= 0.30",
        generation_stamp="gen-2026-11-26",
    )
    rec_verified = reg.get_remediation("gmx2026_fep_dummy_mass_gpu_update")
    assert rec_verified["tier"] == "cross_target_default"
    assert rec_verified["equivalence_verified_count"] == 1
    assert rec_verified["generation_stamp"] == "gen-2026-11-26"

    # A failing Tier-1 equivalence check immediately rejects the perturbation
    reg.register_remediation(
        remediation_id="bad_timestep_4fs",
        pattern=r"slow_sampling",
        fault_class="fep_speed",
        impact_class="physics_perturbation",
        entrypoint="moldarwin.physics.prism_fep:patch_prism_fep_mdps",
        summary="Aggressive 4 fs timestep without HMR.",
    )
    reg.record_outcome("bad_timestep_4fs", succeeded=True, target="TYK2", equivalence_verified=False)
    assert reg.get_remediation("bad_timestep_4fs")["tier"] == "rejected_physics_regression"

    # 2. input_filter blocks promotion if coverage loss is unlogged
    reg.register_remediation(
        remediation_id="drop_boron_filter",
        pattern=r"boron_unsupported",
        fault_class="docking_preflight",
        impact_class="input_filter",
        entrypoint="moldarwin.physics.preflight:preflight_scorer_elements",
        summary="Drop boron molecules before docking.",
    )
    reg.record_outcome("drop_boron_filter", succeeded=True, target="SND1", coverage_loss_logged=False)
    reg.record_outcome("drop_boron_filter", succeeded=True, target="KEAP1", coverage_loss_logged=True, excluded_count=3)
    rec_filt = reg.get_remediation("drop_boron_filter")
    assert rec_filt["tier"] == "scoped_candidate"
    assert rec_filt["promotion_blocked_reason"] == "input_filter_coverage_loss_unlogged"

    # 3. Record remediation receipt directly into ResearchJournal for relied_on binding
    store = CampaignStore(tmp_path / "campaign.sqlite")
    store.configure(
        CampaignSpec(
            objective="rbfe",
            budget=100.0,
            cost_unit="gpu_min",
            representation="fp",
        ),
        [
            Endpoint(
                id="rbfe",
                target="TYK2",
                quantity="anchored_relative_dg",
                units="kcal/mol",
                protocol="prism_20win",
                cost=5.0,
                requires_handoff=False,
            )
        ],
    )
    journal = ResearchJournal(store)
    receipt = reg.record_in_journal(
        journal,
        "gmx2026_fep_dummy_mass_gpu_update",
        target="TYK2",
        directory=tmp_path / "receipts",
        generation_stamp="gen-2026-11-26",
        detail="Verified on TYK2 ejm_46->ejm_45",
        equivalence_report={"delta_gpu_minus_cpu_kcal": 0.08, "passed": True},
    )
    assert receipt["artifact_id"].startswith("artifact-")
    stored = journal.get(receipt["artifact_id"])
    assert stored["bindings"]["fault_rsi_remediation_id"] == "gmx2026_fep_dummy_mass_gpu_update"
    assert stored["bindings"]["fault_rsi_equivalence_verified"] is True
    assert stored["bindings"]["generation_stamp"] == "gen-2026-11-26"


def test_protocol_branch_pruning_protects_overlapping_confidence_intervals():
    """Branches with score_se > 0 whose UCB overlaps cutoff_lcb must not be prematurely killed."""
    tourn = prune_protocol_branches(
        [
            {"branch_id": "b_leader", "gate_passed": True, "primary_score": 0.85, "score_se": 0.04, "gpus_leased": [0, 1]},
            # Point estimate is lower (0.80), but UCB = 0.80 + 1.96*0.05 = 0.898 >= leader LCB (0.7716) -> PROTECTED!
            {"branch_id": "b_uncertain_high_upside", "gate_passed": True, "primary_score": 0.80, "score_se": 0.05, "gpus_leased": [2, 3]},
            # UCB = 0.65 + 1.96*0.02 = 0.6892 < leader LCB (0.7716) -> STATISTICALLY PRUNED!
            {"branch_id": "b_clearly_worse", "gate_passed": True, "primary_score": 0.65, "score_se": 0.02, "gpus_leased": [4, 5]},
        ],
        max_survivors=1,
        uncertainty_z=1.96,
    )
    assert tourn["uncertain_protected_branches"] == ["b_uncertain_high_upside"]
    assert [s["branch_id"] for s in tourn["survivors"]] == ["b_leader", "b_uncertain_high_upside"]
    assert [p["branch_id"] for p in tourn["pruned"]] == ["b_clearly_worse"]
    assert tourn["pruned"][0]["reason"] == "statistically_dominated_below_lcb"
    assert tourn["freed_gpus"] == [4, 5]


def test_bioisostere_evolution_respects_sar_weights_and_custom_neutral_rules():
    """Target-learned SAR weights and custom SMIRKS take priority under max_analogs while preserving neutrality."""
    import pytest

    pytest.importorskip("rdkit")
    from moldarwin.evolve import generate_bioisostere_analogs

    out = generate_bioisostere_analogs(
        "Cc1ccc(Cl)cc1",
        parent_id="lead1",
        max_analogs=2,
        sar_mutation_weights={"chloro_to_cyano": 5.0, "custom_cl_to_ome": 10.0},
        custom_mutations=[
            {"name": "custom_cl_to_ome", "smirks": "[c:1]Cl>>[c:1]OC", "rationale": "TYK2 hinge HBA"},
        ],
    )
    assert out["sar_weighted"] is True
    assert out["custom_rule_count"] == 1
    assert out["analog_count"] == 2
    assert [a["mutation"] for a in out["analogs"]] == ["custom_cl_to_ome", "chloro_to_cyano"]
    assert out["analogs"][0]["mutation_source"] == "target_custom"
    assert all(a["formal_charge"] == 0 for a in out["analogs"])


def test_verb_census_probe_counts_live_jsonl_calls(tmp_path):
    """tools/verb_census.py mechanically counts MCP tool calls and reports thin/pack coverage."""
    import importlib.util
    import json

    log = tmp_path / "run_alpha" / "logs" / "codex-events.jsonl"
    log.parent.mkdir(parents=True)
    events = [
        {"item": {"type": "mcp_tool_call", "tool": "moldarwin_research_context"}},
        {"item": {"type": "mcp_tool_call", "tool": "moldarwin_skill_find"}},
        {"item": {"type": "mcp_tool_call", "tool": "moldarwin_skill_read"}},
        {"item": {"type": "mcp_tool_call", "tool": "moldarwin_physics_preflight"}},
        {"item": {"type": "other", "tool": "ignored"}},
    ]
    log.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

    probe = Path(__file__).resolve().parents[1] / "tools" / "verb_census.py"
    spec = importlib.util.spec_from_file_location("verb_census", probe)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rep = module.census_logs([tmp_path])
    assert rep["schema"] == "moldarwin-verb-census/1"
    assert rep["total_calls"] == 4
    assert rep["distinct_verbs_used"] == 4
    assert rep["thin_core_call_share"] == 0.75
    assert rep["thin_plus_prism_call_share"] == 1.0
    assert "screening" in rep["zero_use_packs"]


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
