"""Reviewed plugins shipped with the MolCat distribution."""

from molcat.plugins.api import StagePlugin
from molcat.plugins.builtin.admet import ADMETAIV2PredictorPlugin
from molcat.plugins.builtin.aizynthfinder import AiZynthFinderRoutePlugin
from molcat.plugins.builtin.boltz2 import Boltz2AffinityPlugin
from molcat.plugins.builtin.chembl_check import ChemblStructureCheckPlugin
from molcat.plugins.builtin.chemprop_model import ChempropCheckpointPlugin
from molcat.plugins.builtin.custom_model import CustomModelPredictorPlugin
from molcat.plugins.builtin.diversity import (
    NativeHashBudgetSelectorPlugin,
    NativeScaffoldRoundRobinSelectorPlugin,
    NativeScaffoldRoundRobinSelectorV2Plugin,
    NativeStreamingLeaderPlugin,
    RDKitMurckoScaffoldPlugin,
    RDKitScaffoldGroupClusterPlugin,
)
from molcat.plugins.builtin.docking import (
    GninaPlugin,
    KarmaDockPlugin,
    RDKitLigandConformerPlugin,
    UniDockPlugin,
)
from molcat.plugins.builtin.docking.unidock import PipelinedUniDockPlugin
from molcat.plugins.builtin.docking.unidock import FineGrainedUniDockPlugin
from molcat.plugins.builtin.docking.unidock import LineageUniDockPlugin
from molcat.plugins.builtin.registered_geometry import RegisteredConformerPlugin
from molcat.plugins.builtin.docking.redock import RedockPlugin
from molcat.plugins.builtin.druglikeness import RDKitDrugLikenessPlugin
from molcat.plugins.builtin.evidence_gates import (
    NativeDerivedMetricEvidenceGatePlugin,
    NativeDockingScoreEvidenceGatePlugin,
    NativePredictionEvidenceGatePlugin,
    NativeSynthesisScoreEvidenceGatePlugin,
)
from molcat.plugins.builtin.exporters import (
    NativeSmilesShortlistPlugin,
    RDKitSDFShortlistPlugin,
)
from molcat.plugins.builtin.features import (
    OpenBabelPropertyPlugin,
    RDKitFingerprintPlugin,
    RDKitPropertyPlugin,
)
from molcat.plugins.builtin.hard_gate import RDKitHardGatePlugin
from molcat.plugins.builtin.lilly_medchem import LillyMedchemPlugin
from molcat.plugins.builtin.md_handoff import (
    MdHandoffFromConformerPlugin,
    MdHandoffPlugin,
)
from molcat.plugins.builtin.md_handoff_gate import MdHandoffGatePlugin
from molcat.plugins.builtin.medchem_alerts import MedchemAlertsPlugin
from molcat.plugins.builtin.medchem_rules import MedchemRulesPlugin
from molcat.plugins.builtin.mordred_gate import MordredDescriptorGatePlugin
from molcat.plugins.builtin.normalized_docking_score import (
    NormalizedDockingScorePlugin,
)
from molcat.plugins.builtin.openadmet import OpenADMETPredictorPlugin
from molcat.plugins.builtin.policy import NativeDecisionJoinPlugin
from molcat.plugins.builtin.pose_strain import PoseStrainPlugin
from molcat.plugins.builtin.property_gate import RDKitPropertyRangeGatePlugin
from molcat.plugins.builtin.rd_filters_alerts import RdFiltersAlertsPlugin
from molcat.plugins.builtin.ring_topology_gate import RDKitRingTopologyGatePlugin
from molcat.plugins.builtin.scscore import ScScorePlugin
from molcat.plugins.builtin.similarity import RDKitReferenceSimilarityPlugin
from molcat.plugins.builtin.similarity_fpsim2 import Fpsim2ReferenceSimilarityPlugin
from molcat.plugins.builtin.sources import (
    DelimitedSmilesSourcePlugin,
    Mol2DirectorySourcePlugin,
    RawMoleculeParquetSourcePlugin,
    SDFSourcePlugin,
    XlsxSourcePlugin,
)
from molcat.plugins.builtin.specificity_panel import SpecificityPanelPlugin
from molcat.plugins.builtin.registered_source import RegisteredParentSourcePlugin
from molcat.plugins.builtin.standardize import RDKitStandardizePlugin
from molcat.plugins.builtin.structural_alerts import RDKitStructuralAlertPlugin
from molcat.plugins.builtin.synthesis import RDKitSAScorePlugin

BUILTIN_STAGE_PLUGINS: tuple[StagePlugin, ...] = (
    RegisteredParentSourcePlugin(),
    DelimitedSmilesSourcePlugin(),
    SDFSourcePlugin(),
    RawMoleculeParquetSourcePlugin(),
    XlsxSourcePlugin(),
    Mol2DirectorySourcePlugin(),
    RDKitStandardizePlugin(),
    RDKitHardGatePlugin(),
    ChemblStructureCheckPlugin(),
    RDKitPropertyRangeGatePlugin(),
    RDKitRingTopologyGatePlugin(),
    MordredDescriptorGatePlugin(),
    RDKitDrugLikenessPlugin(),
    MedchemRulesPlugin(),
    RDKitStructuralAlertPlugin(),
    LillyMedchemPlugin(),
    MdHandoffPlugin(),
    MdHandoffFromConformerPlugin(),
    MdHandoffGatePlugin(),
    MedchemAlertsPlugin(),
    RdFiltersAlertsPlugin(),
    NativeDecisionJoinPlugin(),
    RDKitPropertyPlugin(),
    OpenBabelPropertyPlugin(),
    RDKitFingerprintPlugin(),
    RDKitReferenceSimilarityPlugin(),
    Fpsim2ReferenceSimilarityPlugin(),
    RDKitSAScorePlugin(),
    ScScorePlugin(),
    AiZynthFinderRoutePlugin(),
    RDKitLigandConformerPlugin(),
    UniDockPlugin(),
    PipelinedUniDockPlugin(),
    FineGrainedUniDockPlugin(),
    LineageUniDockPlugin(),
    RegisteredConformerPlugin(),
    KarmaDockPlugin(),
    GninaPlugin(),
    NativeDockingScoreEvidenceGatePlugin(),
    NormalizedDockingScorePlugin(),
    PoseStrainPlugin(),
    RedockPlugin(),
    SpecificityPanelPlugin(),
    NativeDerivedMetricEvidenceGatePlugin(),
    ADMETAIV2PredictorPlugin(),
    ChempropCheckpointPlugin(),
    CustomModelPredictorPlugin(),
    OpenADMETPredictorPlugin(),
    Boltz2AffinityPlugin(),
    NativePredictionEvidenceGatePlugin(),
    NativeSynthesisScoreEvidenceGatePlugin(),
    RDKitMurckoScaffoldPlugin(),
    NativeStreamingLeaderPlugin(),
    RDKitScaffoldGroupClusterPlugin(),
    NativeHashBudgetSelectorPlugin(),
    NativeScaffoldRoundRobinSelectorPlugin(),
    NativeScaffoldRoundRobinSelectorV2Plugin(),
    NativeSmilesShortlistPlugin(),
    RDKitSDFShortlistPlugin(),
)

__all__ = ["BUILTIN_STAGE_PLUGINS"]
