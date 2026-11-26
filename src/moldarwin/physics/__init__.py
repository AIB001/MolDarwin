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
    preflight_scorer_elements,
    sanitize_ligand_sdf,
    validate_complex_handoff,
)
from moldarwin.physics.prism_bridge import (
    MD_READOUT_SCHEMA,
    analyze_md_trajectory,
    compare_docking_vs_md,
    patch_gromacs2026_artifacts,
    prepare_prism_md_system,
    record_md_readout,
    validate_gro_integrity,
)

__all__ = [
    "COMPLEX_ORIGINS",
    "MD_READOUT_SCHEMA",
    "SCORER_SUPPORTED_ELEMENTS",
    "analyze_md_trajectory",
    "compare_docking_vs_md",
    "patch_gromacs2026_artifacts",
    "preflight_scorer_elements",
    "prepare_prism_md_system",
    "record_md_readout",
    "sanitize_ligand_sdf",
    "validate_complex_handoff",
    "validate_gro_integrity",
]
