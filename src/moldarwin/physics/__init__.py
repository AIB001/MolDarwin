"""Physics verification boundary and explicitly bounded PRISM runtime compatibility shims.

Architectural boundary (see ``docs/thin-harness/THREE_PILLAR_BOUNDARY.md``):
  1. **MolDarwin scientific verification boundary** (``moldarwin_scientific_boundary``):
     ``preflight``, ``rescoring``, and ``prism_gen`` enforce Any-Origin 3D geometry/element
     invariants, tie-aware rescorer calibration, and pose qualification across engines.
  2. **PRISM runtime compatibility shims** (``prism_runtime_compat_shim``):
     ``prism_bridge``, ``prism_fep``, ``adaptive``, and ``enhanced_sampling`` bridge pinned
     ``asset/prism`` (commit ``f0492d9``, frozen under Hard Constraint 6) to GROMACS 2026 and
     provide sampling/network diagnostics. These modules are frozen to bugfixes only and
     scheduled for upstream migration into ``AIB001/PRISM`` — they are NOT MolDarwin's core
     drug-design identity.

Never edits ``asset/`` (Hard Constraint 6).
"""

from moldarwin.physics.adaptive import (
    ADAPTIVE_LAMBDA_SCHEMA,
    PACKED_FEP_RUNNER_SCHEMA,
    WINDOW_EXTENSION_SCHEMA,
    plan_selective_window_extensions,
    refine_lambda_schedule_from_overlap,
    render_packed_fep_runner,
)
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
from moldarwin.physics.preflight import (
    COMPLEX_ORIGINS,
    RBFE_MAPPING_AUDIT_SCHEMA,
    SCORER_SUPPORTED_ELEMENTS,
    SHALLOW_PPI_PROTOCOL_SCHEMA,
    annotate_medchem_liabilities,
    plan_shallow_ppi_physics_protocol,
    preflight_scorer_elements,
    sanitize_ligand_sdf,
    select_conserved_pocket_waters,
    validate_complex_handoff,
    verify_bond_consistent_atom_mapping,
)
from moldarwin.physics.prism_bridge import (
    MD_READOUT_SCHEMA,
    analyze_md_trajectory,
    compare_docking_vs_md,
    evaluate_md_control_gate,
    patch_gromacs2026_artifacts,
    prepare_prism_md_system,
    record_md_readout,
    validate_gro_integrity,
)
from moldarwin.physics.prism_fep import (
    FEP_NETWORK_SCHEMA,
    analyze_fep_network,
    enforce_invariant_dummy_masses,
    evaluate_prism_fep_edge,
    patch_prism_fep_mdps,
    prepare_prism_fep_edge,
    prepare_prism_mmpbsa_system,
    record_fep_readout,
)
from moldarwin.physics.prism_gen import (
    discover_prism_generators,
    qualify_generated_poses,
)
from moldarwin.physics.rescoring import (
    RESCORE_COMPARE_SCHEMA,
    RESCORE_EVAL_SCHEMA,
    check_property_shortcut_and_mmp,
    compare_rescorers_for_rsi,
    evaluate_rescorer_panel,
)

#: Explicit architectural classification of every module in ``moldarwin.physics``.
#: Prevents GROMACS/PRISM simulation internals from silently growing inside MolDarwin.
PHYSICS_MODULE_BOUNDARIES: dict[str, dict[str, str]] = {
    "preflight": {
        "layer": "moldarwin_scientific_boundary",
        "owner": "moldarwin",
        "freeze_policy": "active_boundary",
        "summary": "Any-Origin 3D geometry/clash/element preflight, conserved bridge waters, soft medchem flags.",
    },
    "rescoring": {
        "layer": "moldarwin_scientific_boundary",
        "owner": "moldarwin",
        "freeze_policy": "active_boundary",
        "summary": "Tie-aware ROC-AUC/EF calibration, paired RSI rescorer comparison, property-shortcut check.",
    },
    "prism_gen": {
        "layer": "moldarwin_scientific_boundary",
        "owner": "moldarwin",
        "freeze_policy": "active_boundary",
        "summary": "Honest PRISM 6-model SBDD adapter discovery and Any-Origin 3D pose qualification.",
    },
    "prism_bridge": {
        "layer": "prism_runtime_compat_shim",
        "owner": "upstream_prism_candidate",
        "upstream_target": "AIB001/PRISM:prism/builder + prism/analysis",
        "freeze_policy": "bugfix_only_until_upstreamed_to_prism",
        "summary": "GROMACS 2026 EM/posre/PROPKA/TPR-v138/PBC-unwrap shim around frozen asset/prism.",
    },
    "prism_fep": {
        "layer": "prism_runtime_compat_shim",
        "owner": "upstream_prism_candidate",
        "upstream_target": "AIB001/PRISM:prism/fep",
        "freeze_policy": "bugfix_only_until_upstreamed_to_prism",
        "summary": "PRISM v1.2.0 SDF->GRO guard, MBAR MDP patching, 4-decimal lambda rounding, cycle-closure audit.",
    },
    "adaptive": {
        "layer": "prism_runtime_compat_shim",
        "owner": "upstream_prism_candidate",
        "upstream_target": "AIB001/PRISM:prism/fep + prism/sim",
        "freeze_policy": "bugfix_only_until_upstreamed_to_prism",
        "summary": "Overlap-driven adaptive lambda refinement, selective window extension, -update cpu packed runner.",
    },
    "enhanced_sampling": {
        "layer": "prism_runtime_compat_shim",
        "owner": "upstream_prism_candidate",
        "upstream_target": "AIB001/PRISM:prism/fep + prism/sim",
        "freeze_policy": "bugfix_only_until_upstreamed_to_prism",
        "summary": "Geodesic thermodynamic-length lambda schedule, Metropolized-Gibbs EE MDP builder, Huber FEP graph.",
    },
}

__all__ = [
    "ADAPTIVE_LAMBDA_SCHEMA",
    "COMPLEX_ORIGINS",
    "EE_CONVERGENCE_SCHEMA",
    "ESCALATION_PLAN_SCHEMA",
    "FEP_NETWORK_SCHEMA",
    "GEODESIC_SCHEDULE_SCHEMA",
    "MD_READOUT_SCHEMA",
    "PACKED_FEP_RUNNER_SCHEMA",
    "PHYSICS_MODULE_BOUNDARIES",
    "RBFE_MAPPING_AUDIT_SCHEMA",
    "RESCORE_COMPARE_SCHEMA",
    "RESCORE_EVAL_SCHEMA",
    "ROBUST_NETWORK_SCHEMA",
    "SCORER_SUPPORTED_ELEMENTS",
    "SHALLOW_PPI_PROTOCOL_SCHEMA",
    "WINDOW_EXTENSION_SCHEMA",
    "analyze_expanded_ensemble_convergence",
    "analyze_fep_network",
    "analyze_md_trajectory",
    "annotate_medchem_liabilities",
    "build_expanded_ensemble_mdp",
    "check_property_shortcut_and_mmp",
    "compare_docking_vs_md",
    "compare_rescorers_for_rsi",
    "discover_prism_generators",
    "enforce_invariant_dummy_masses",
    "evaluate_md_control_gate",
    "evaluate_prism_fep_edge",
    "evaluate_rescorer_panel",
    "interpolate_lambda_weights",
    "optimize_lambda_geodesic",
    "parse_final_mc_lambda_weights",
    "patch_gromacs2026_artifacts",
    "patch_prism_fep_mdps",
    "plan_sampling_escalation",
    "plan_selective_window_extensions",
    "plan_shallow_ppi_physics_protocol",
    "preflight_scorer_elements",
    "prepare_prism_fep_edge",
    "prepare_prism_md_system",
    "prepare_prism_mmpbsa_system",
    "qualify_generated_poses",
    "record_fep_readout",
    "record_md_readout",
    "refine_lambda_schedule_from_overlap",
    "render_packed_fep_runner",
    "sanitize_ligand_sdf",
    "select_conserved_pocket_waters",
    "solve_robust_fep_network",
    "validate_complex_handoff",
    "validate_gro_integrity",
    "verify_bond_consistent_atom_mapping",
]
