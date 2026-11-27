"""Tests for first-principles geodesic lambda scheduling, Metropolized-Gibbs expanded ensemble,
and outlier-aware robust FEP network inference."""

from __future__ import annotations

from moldarwin.physics.enhanced_sampling import (
    EE_CONVERGENCE_SCHEMA,
    ESCALATION_PLAN_SCHEMA,
    GEODESIC_SCHEDULE_SCHEMA,
    ROBUST_NETWORK_SCHEMA,
    analyze_expanded_ensemble_convergence,
    build_expanded_ensemble_mdp,
    interpolate_lambda_weights,
    optimize_lambda_geodesic,
    parse_final_mc_lambda_weights,
    plan_sampling_escalation,
    solve_robust_fep_network,
)


def test_geodesic_lambda_schedule_concentrates_windows_in_low_overlap_pinch_and_rounds_4dp():
    lams = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    # Severe overlap cliff strictly in [0.2, 0.4]
    ovs = [0.35, 0.001, 0.40, 0.38, 0.35]
    out = optimize_lambda_geodesic(lams, ovs, n_windows=16)
    assert out["schema"] == GEODESIC_SCHEDULE_SCHEMA
    new_lams = out["geodesic_lambdas"]
    assert len(new_lams) == 16
    assert new_lams[0] == 0.0 and new_lams[-1] == 1.0
    assert all(new_lams[i] < new_lams[i + 1] for i in range(len(new_lams) - 1))
    assert all(round(x, 4) == x for x in new_lams)
    # Pinch interval [0.2, 0.4] must receive strictly more interior windows than flat [0.6, 0.8]
    in_pinch = sum(1 for x in new_lams if 0.2 < x < 0.4)
    in_flat = sum(1 for x in new_lams if 0.6 < x < 0.8)
    assert in_pinch > in_flat
    assert out["predicted_uniform_overlap"] > 0.001


def test_expanded_ensemble_mdp_warm_start_weight_parsing_and_bidirectional_convergence():
    w_new = interpolate_lambda_weights([0.0, 0.5, 1.0], [1.0, 3.0, 5.0], [0.0, 0.25, 0.5, 0.75, 1.0])
    assert w_new == [0.0, 1.0, 2.0, 3.0, 4.0]

    base_mdp = """
integrator = sd
nsteps = 50000
free-energy = yes
init-lambda-state = 0
coul-lambdas = 0.0 0.5 1.0
vdw-lambdas = 0.0 0.5 1.0
bonded-lambdas = 0.0 0.5 1.0
mass-lambdas = 0.0 0.5 1.0
"""
    ee_wl = build_expanded_ensemble_mdp(
        base_mdp,
        lambdas=[0.0, 0.25, 0.5, 0.75, 1.0],
        init_lambda_state=4,
        init_weights_kt=w_new,
        nsteps=250000,
        mode="equil_wl",
    )
    assert "integrator = md-vv" in ee_wl
    assert "free-energy = expanded" in ee_wl
    assert "lmc-move                 = metropolized-gibbs" in ee_wl
    assert "lmc-stats                = wang-landau" in ee_wl
    assert "init-lambda-state = 4" in ee_wl

    ee_prod = build_expanded_ensemble_mdp(
        ee_wl,
        lambdas=[0.0, 0.25, 0.5, 0.75, 1.0],
        init_lambda_state=0,
        init_weights_kt=w_new,
        nsteps=1000000,
        mode="prod_fixed",
    )
    assert "lmc-stats                = no" in ee_prod
    assert "wang-landau" not in ee_prod

    fake_log = """
            MC-lambda information
  Wang-Landau incrementor is: 0.01
    N  coul-l  vdw-l  Count   G(in kT)
    1  0.0000  0.0000   120    0.00000 <<
    2  0.2500  0.2500   118    1.25000
    3  0.5000  0.5000   115    2.40000
    4  0.7500  0.7500   119    3.10000
    5  1.0000  1.0000   121    4.05000
"""
    parsed = parse_final_mc_lambda_weights(fake_log, n_states=5)
    assert parsed == [0.0, 1.25, 2.4, 3.1, 4.05]

    conv = analyze_expanded_ensemble_convergence(
        [
            [0, 1, 2, 3, 4, 3, 2, 1, 0, 2, 4, 2, 0],  # 2 full round trips!
            [4, 3, 2, 1, 0, 1, 2, 3, 4],              # 1 full round trip!
        ],
        n_states=5,
        dg_a_seeded_kcal=-5.10,
        dg_b_seeded_kcal=-5.35,
    )
    assert conv["schema"] == EE_CONVERGENCE_SCHEMA
    assert conv["total_round_trips"] == 3
    assert conv["all_states_visited"] is True
    assert conv["bidirectional_gap_kcal"] == 0.25
    assert conv["memory_erased"] is True


def test_robust_fep_network_isolates_kinetic_trap_outlier_and_plans_targeted_escalation():
    # Ground truth: A=0, B=-1.0, C=-2.0, D=-1.5. Edge B->C has a +2.8 kcal/mol kinetic trap!
    edges = [
        {"edge_id": "A->B", "from_id": "A", "to_id": "B", "ddg_kcal_mol": -1.0, "uncertainty_kcal_mol": 0.1, "temporal_half_delta_kcal_mol": 0.1, "overlap_min": 0.08, "min_uncorrelated_samples": 600},
        {"edge_id": "A->D", "from_id": "A", "to_id": "D", "ddg_kcal_mol": -1.5, "uncertainty_kcal_mol": 0.1, "temporal_half_delta_kcal_mol": 0.1, "overlap_min": 0.07, "min_uncorrelated_samples": 600},
        {"edge_id": "D->C", "from_id": "D", "to_id": "C", "ddg_kcal_mol": -0.5, "uncertainty_kcal_mol": 0.1, "temporal_half_delta_kcal_mol": 0.1, "overlap_min": 0.06, "min_uncorrelated_samples": 600},
        {"edge_id": "A->C", "from_id": "A", "to_id": "C", "ddg_kcal_mol": -2.0, "uncertainty_kcal_mol": 0.1, "temporal_half_delta_kcal_mol": 0.1, "overlap_min": 0.06, "min_uncorrelated_samples": 600},
        {"edge_id": "B->C", "from_id": "B", "to_id": "C", "ddg_kcal_mol": +1.8, "uncertainty_kcal_mol": 0.1, "temporal_half_delta_kcal_mol": 1.3, "overlap_min": 0.005, "min_uncorrelated_samples": 18},
    ]
    rob = solve_robust_fep_network(edges, anchor_ligand="A")
    assert rob["schema"] == ROBUST_NETWORK_SCHEMA
    assert rob["outlier_edges"] == ["B->C"]
    # Robust MLE recovers C ~ -2.0 despite B->C's +2.8 kcal/mol kinetic-trap corruption!
    assert abs(rob["relative_dg_kcal_mol"]["C"] - (-2.0)) < 0.15

    plan = plan_sampling_escalation(edges, mpi_hrex_available=False, outlier_edges=rob["outlier_edges"])
    assert plan["schema"] == ESCALATION_PLAN_SCHEMA
    assert plan["converged_edges"] == ["A->B", "A->D", "D->C", "A->C"]
    assert [e["edge_id"] for e in plan["escalate_enhanced_sampling"]] == ["B->C"]
    assert plan["escalate_enhanced_sampling"][0]["target_tier"] == "tier1_metropolized_gibbs_expanded_ensemble"
