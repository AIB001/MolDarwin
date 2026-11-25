"""Digest-pinned, cited, explicitly-provisioned model weights and rule tables."""

from molcat.assets.catalog import BUILTIN_ASSET_SPECS, asset_spec, iter_assets
from molcat.assets.models import (
    ASSET_SCHEMA_VERSION,
    AssetFile,
    AssetFileStatus,
    AssetKind,
    AssetSpec,
    AssetState,
    AssetStatus,
    Citation,
    PayloadTrust,
)
from molcat.assets.preflight import preflight_assets, required_asset_references
from molcat.assets.store import (
    ASSET_REFERENCE_PREFIX,
    asset_directory,
    asset_status,
    default_asset_root,
    is_asset_reference,
    resolve_path_or_reference,
    resolve_reference,
    split_reference,
)

__all__ = [
    "ASSET_REFERENCE_PREFIX",
    "ASSET_SCHEMA_VERSION",
    "BUILTIN_ASSET_SPECS",
    "AssetFile",
    "AssetFileStatus",
    "AssetKind",
    "AssetSpec",
    "AssetState",
    "AssetStatus",
    "Citation",
    "PayloadTrust",
    "asset_directory",
    "asset_spec",
    "asset_status",
    "default_asset_root",
    "is_asset_reference",
    "iter_assets",
    "preflight_assets",
    "required_asset_references",
    "resolve_path_or_reference",
    "resolve_reference",
    "split_reference",
]
