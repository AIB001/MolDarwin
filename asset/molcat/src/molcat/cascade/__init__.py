"""Tier-first screening cascades.

A cascade is the authoring surface: an ordered funnel of tiers, each holding
criteria that run in series or in parallel, each carrying its own threshold.
:func:`~molcat.cascade.lower.lower_cascade` renders it into the flat,
ordered pipeline the compiler and runtime already execute.
"""

from molcat.cascade.catalog import (
    CRITERIA,
    CRITERIA_BY_ID,
    STAGE_GROUPS,
    BackendOption,
    CriterionSpec,
    StageGroup,
    ThresholdField,
    catalogue_json,
)
from molcat.cascade.defaults import build_criterion, default_cascade
from molcat.cascade.funnel import FunnelReport, FunnelStep, FunnelTier, build_funnel
from molcat.cascade.introspect import config_fields, with_schema_version
from molcat.cascade.library import ResolvedLibrary, detect_format, resolve_library
from molcat.cascade.load import (
    ScreeningConfig,
    dump_cascade_json,
    load_cascade_config,
    load_screening_config,
    parse_cascade_config,
    parse_screening_config,
)
from molcat.cascade.lower import LoweredCascade, StageOrigin, lower_cascade
from molcat.cascade.models import (
    CASCADE_SCHEMA_VERSION,
    BoxConfig,
    CascadeConfig,
    CriterionConfig,
    FinalizeConfig,
    GateConfig,
    LibraryConfig,
    LibraryFormat,
    StepConfig,
    TargetConfig,
    TierConfig,
    TierMode,
)

__all__ = [
    "CASCADE_SCHEMA_VERSION",
    "CRITERIA",
    "CRITERIA_BY_ID",
    "STAGE_GROUPS",
    "BackendOption",
    "BoxConfig",
    "CascadeConfig",
    "CriterionConfig",
    "CriterionSpec",
    "FinalizeConfig",
    "FunnelReport",
    "FunnelStep",
    "FunnelTier",
    "GateConfig",
    "LibraryConfig",
    "LibraryFormat",
    "LoweredCascade",
    "ResolvedLibrary",
    "ScreeningConfig",
    "StageGroup",
    "StageOrigin",
    "StepConfig",
    "TargetConfig",
    "ThresholdField",
    "TierConfig",
    "TierMode",
    "build_criterion",
    "build_funnel",
    "catalogue_json",
    "config_fields",
    "default_cascade",
    "detect_format",
    "dump_cascade_json",
    "load_cascade_config",
    "load_screening_config",
    "lower_cascade",
    "parse_cascade_config",
    "parse_screening_config",
    "resolve_library",
    "with_schema_version",
]
