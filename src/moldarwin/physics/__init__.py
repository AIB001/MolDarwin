"""Thin, composable physics preflight and PRISM <-> MolDarwin RSI primitives.

Deliberately avoids rigid monolithic workflows: hardens only low-level physical/ABI
invariants (blank SDF titles, scorer element compatibility, GROMACS 2026 EM/posre
compatibility, TPR v138 trajectory fallback) and structured physical readouts so
host agents stay free to adapt protocols while PRISM MD/FEP reality feeds MolDarwin's
RSI loop. Never edits ``asset/`` (Hard Constraint 6).
"""

from moldarwin.physics.preflight import (
    COMPLEX_ORIGINS,
    SCORER_SUPPORTED_ELEMENTS,
    annotate_medchem_liabilities,
    preflight_scorer_elements,
    sanitize_ligand_sdf,
    select_conserved_pocket_waters,
    validate_complex_handoff,
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
    compare_rescorers_for_rsi,
    evaluate_rescorer_panel,
)

__all__ = [
    "COMPLEX_ORIGINS",
    "FEP_NETWORK_SCHEMA",
    "MD_READOUT_SCHEMA",
    "RESCORE_COMPARE_SCHEMA",
    "RESCORE_EVAL_SCHEMA",
    "SCORER_SUPPORTED_ELEMENTS",
    "analyze_fep_network",
    "analyze_md_trajectory",
    "annotate_medchem_liabilities",
    "compare_docking_vs_md",
    "compare_rescorers_for_rsi",
    "discover_prism_generators",
    "enforce_invariant_dummy_masses",
    "evaluate_md_control_gate",
    "evaluate_prism_fep_edge",
    "evaluate_rescorer_panel",
    "patch_gromacs2026_artifacts",
    "patch_prism_fep_mdps",
    "preflight_scorer_elements",
    "prepare_prism_fep_edge",
    "prepare_prism_md_system",
    "prepare_prism_mmpbsa_system",
    "qualify_generated_poses",
    "record_fep_readout",
    "record_md_readout",
    "sanitize_ligand_sdf",
    "select_conserved_pocket_waters",
    "validate_complex_handoff",
    "validate_gro_integrity",
]
