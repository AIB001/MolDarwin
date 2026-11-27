"""First-principles cross-pillar Drug-Design reasoning brain for MolDarwin.

Connects MolOrigin (target/assay/sourcing), MolCat (53-plugin screening/ADMET/retrosynthesis),
and PRISM (3D generation/grounded editing/MD/FEP) through three mathematical modules:

  - ``moldarwin.design.pocket``: 3D interaction roles, locked pharmacophore anchors, analytical
    radial exit-vector clearance, and Kabsch-aligned isoform selectivity difference mapping.
  - ``moldarwin.design.sar``: ring-preserving MCS/MMP decomposition, heteroscedastic Bayesian
    Free-Wilson + pairwise epistasis (Activity Cliffs), exact hat-matrix LOO CV, novel untested
    R-group Cartesian recombination, and Frisch-Waugh-Lovell physicochemical deconfounding.
  - ``moldarwin.design.dmta``: LE/LLE/LELP & continuous Oral/CNS/PPI MPO profiling, targeted
    metabolic soft-spot triage, uncertainty-aware multi-objective EHVI, Graph-Laplacian
    A-optimal DMTA batch/bridge selection, and evidence-bound Design Dossiers.
"""

from moldarwin.design.dmta import (
    A_OPTIMAL_DMTA_SCHEMA,
    DESIGN_DOSSIER_SCHEMA,
    EHVI_RANKING_SCHEMA,
    MPO_PROFILE_SCHEMA,
    build_design_dossier,
    rank_candidates_ehvi,
    score_drug_design_mpo,
    select_a_optimal_dmta_batch,
)
from moldarwin.design.pocket import (
    POCKET_PROFILE_SCHEMA,
    SELECTIVITY_MAP_SCHEMA,
    map_isoform_selectivity_vectors,
    profile_3d_pocket_and_vectors,
)
from moldarwin.design.sar import (
    DECONFOUND_SCHEMA,
    FREE_WILSON_SCHEMA,
    MMP_DECOMPOSITION_SCHEMA,
    decompose_congeneric_series,
    deconfound_sar_signal,
    fit_bayesian_free_wilson,
)

__all__ = [
    "A_OPTIMAL_DMTA_SCHEMA",
    "DECONFOUND_SCHEMA",
    "DESIGN_DOSSIER_SCHEMA",
    "EHVI_RANKING_SCHEMA",
    "FREE_WILSON_SCHEMA",
    "MMP_DECOMPOSITION_SCHEMA",
    "MPO_PROFILE_SCHEMA",
    "POCKET_PROFILE_SCHEMA",
    "SELECTIVITY_MAP_SCHEMA",
    "build_design_dossier",
    "deconfound_sar_signal",
    "decompose_congeneric_series",
    "fit_bayesian_free_wilson",
    "map_isoform_selectivity_vectors",
    "profile_3d_pocket_and_vectors",
    "rank_candidates_ehvi",
    "score_drug_design_mpo",
    "select_a_optimal_dmta_batch",
]
