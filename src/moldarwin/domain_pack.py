"""Pluggable Three-Pillar CADD DomainPack cleanly separating MolDarwin's kernel from its engines.

Restores ETALON's foundational three-pillar architecture for real Drug Design rather than
centering the platform on a single simulation engine:

  1. **Domain-Agnostic Epistemic & RSI Kernel**: ``ResearchJournal``, ``admission_view``,
     ``reserved_bindings``, ``authority`` (``0/7`` unguarded SPENDS), ``FaultRSIRegistry``
     (Tier-1 physical equivalence gating), ``subagents``, and 3-tier lazy ``skill_index``.
  2. **Three Equal Vendored CADD Engine Pillars** (read-only pinned in ``asset/MANIFEST.json``):
     - **MolOrigin** (``data`` pack): target/assay/literature evidence, crystal templates,
       selectivity data, analogue search, and purchasable compound sourcing.
     - **MolCat** (``screening`` pack): 53 contract-enforced CADD plugins — standardization,
       docking (Uni-Dock/Gnina/KarmaDock/Redock), Boltz2, OpenADMET/ADMET-AI, Lilly & medchem
       rules/alerts, AiZynthFinder retrosynthesis, SA/SCScore, specificity panel, diversity.
     - **PRISM** (``prism`` pack): 3D SBDD generation (6 models), explicit-solvent MD/FEP/
       MM-PBSA/PMF/REST2, trajectory interaction analysis (and upstream ``prism/design``
       grounded local editing when vendored).
  3. **Cross-Pillar Drug-Design Reasoning Brain** (``moldarwin.design`` + ``moldarwin.evolve``):
     the scientific intelligence layer that none of the three engines owns alone — 3D pocket &
     isoform-selectivity vector calculus, Bayesian Free–Wilson/MMP/Activity-Cliff SAR &
     deconfounding, continuous MPO/LLE scoring, 4D uncertainty-aware EHVI, and Graph-Laplacian
     A-optimal DMTA batch/bridge selection.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOMAIN_PACK_SCHEMA = "moldarwin-domain-pack/2"
CADD_DOMAIN_PACK_ID = "cadd_drug_design"
LEGACY_CADD_DOMAIN_PACK_ID = "cadd_prism_rbfe"

#: Balanced three-pillar engine contract + cross-pillar MolDarwin reasoning layer.
CADD_ENGINE_PILLARS: dict[str, dict[str, Any]] = {
    "molorigin": {
        "role": "target_evidence_and_sourcing",
        "mcp_pack": "data",
        "boundary_module": "moldarwin.boundary.quarry",
        "capabilities": (
            "target_modulators",
            "assay_literature",
            "structure_templates",
            "selectivity_evidence",
            "analogue_search",
            "compound_sourcing",
        ),
    },
    "molcat": {
        "role": "multi_parameter_screening_admet_and_retrosynthesis",
        "mcp_pack": "screening",
        "boundary_module": "moldarwin.boundary.screen",
        "capabilities": (
            "standardization_and_hard_gates",
            "docking_and_boltz2_cofolding",
            "admet_openadmet_and_lilly_medchem",
            "aizynthfinder_retrosynthesis_and_sa_scscore",
            "specificity_panel_pose_strain_and_diversity",
            "chemprop_qsar_and_md_handoff",
        ),
    },
    "prism": {
        "role": "3d_generation_grounded_editing_and_explicit_solvent_physics",
        "mcp_pack": "prism",
        "boundary_module": "moldarwin.boundary.simulate",
        "capabilities": (
            "sbdd_3d_generation_6_models",
            "grounded_local_design_upstream",
            "explicit_solvent_md_and_mmpbsa",
            "alchemical_rbfe_fep_and_rest2",
            "trajectory_contact_and_hbond_analysis",
        ),
    },
    "moldarwin_design": {
        "role": "cross_pillar_drug_design_reasoning_and_dmta_decision",
        "mcp_pack": "thin_core_sdk",
        "boundary_module": "moldarwin.design",
        "capabilities": (
            "3d_pocket_exit_vectors_and_isoform_selectivity_map",
            "bayesian_free_wilson_mmp_and_activity_cliff_sar",
            "partial_correlation_physicochemical_deconfounding",
            "continuous_oral_cns_ppi_mpo_and_lle_profiling",
            "uncertainty_aware_multi_objective_ehvi",
            "graph_laplacian_a_optimal_dmta_batch_and_bridge_selection",
        ),
    },
}

#: End-to-end 5-tier Drug-Design DMTA ladder spanning all three pillars + MolDarwin design.
CADD_FIDELITY_LADDER: tuple[dict[str, Any], ...] = (
    {
        "tier": 0,
        "name": "target_evidence_and_sourcing",
        "pillar": "molorigin",
        "entrypoint": "moldarwin.boundary.quarry:describe",
        "hard_gate": "sealed_provenance_and_explicit_assay_review",
        "tier1_equivalence_required": False,
    },
    {
        "tier": 1,
        "name": "pocket_selectivity_and_quantitative_sar",
        "pillar": "moldarwin_design",
        "entrypoint": "moldarwin.design.sar:fit_bayesian_free_wilson",
        "hard_gate": "deconfounded_sar_signal_and_anchor_protected_exit_vectors",
        "tier1_equivalence_required": False,
    },
    {
        "tier": 2,
        "name": "generation_and_molcat_mpo_qualification",
        "pillar": "molcat+prism",
        "entrypoint": "moldarwin.boundary.screen:Screen",
        "hard_gate": "control_calibrated_ranking_admet_and_retrosynthesis_checks",
        "tier1_equivalence_required": False,
    },
    {
        "tier": 3,
        "name": "explicit_solvent_md_and_rbfe_verification",
        "pillar": "prism",
        "entrypoint": "moldarwin.physics.prism_fep:analyze_fep_network",
        "hard_gate": "replica_md_stability_mbar_overlap_and_cycle_closure_le_1.0_kcal",
        "tier1_equivalence_required": True,
        "default_update_mode": "cpu",
        "escalation_ladder": (
            "tier0_adaptive_lambda_cpu_update",
            "tier1_expanded_ensemble_or_rest2_lite",
            "tier2_gmx_mpi_multidir_hrex",
        ),
    },
    {
        "tier": 4,
        "name": "multi_objective_ehvi_and_a_optimal_dmta",
        "pillar": "moldarwin_design",
        "entrypoint": "moldarwin.design.dmta:select_a_optimal_dmta_batch",
        "hard_gate": "uncertainty_aware_ehvi_lle_selectivity_and_synthesizable_dossier",
        "tier1_equivalence_required": False,
    },
)

#: Grouping of MolCat's builtin plugins by drug-design capability (read-only introspection).
_MOLCAT_PLUGIN_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("admet_medchem", ("admet", "openadmet", "druglikeness", "lilly", "medchem", "alert", "ringtopology", "chembl")),
    ("synthesis_retrosynthesis", ("aizynth", "sascore", "scscore", "synthesis")),
    ("docking_cofold_pose", ("unidock", "gnina", "karmadock", "redock", "boltz2", "conformer", "posestrain", "docking")),
    ("specificity_qsar_diversity", ("specificity", "chemprop", "custommodel", "murcko", "scaffold", "diversity", "similarity", "fpsim2", "leader", "hashbudget")),
    ("standardization_gates_handoff", ("standardize", "hardgate", "property", "mordred", "fingerprint", "evidencegate", "decisionjoin", "mdhandoff", "source", "shortlist")),
)


def _read_asset_manifest() -> dict[str, Any]:
    from moldarwin.boundary.infra import asset_directory

    manifest_path = asset_directory() / "MANIFEST.json"
    if not manifest_path.is_file():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")).get("assets", {})
    except Exception:  # noqa: BLE001
        return {}


def _introspect_molcat_plugins() -> dict[str, Any]:
    """Read MolCat's shipped builtin plugins cleanly via AST without importing heavy ML deps."""
    from moldarwin.boundary.infra import asset_directory

    init_file = asset_directory() / "molcat" / "src" / "molcat" / "plugins" / "builtin" / "__init__.py"
    if not init_file.is_file():
        return {"available": False, "plugin_count": 0, "by_family": {}}
    try:
        tree = ast.parse(init_file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {exc}", "plugin_count": 0}

    plugin_classes: list[str] = []
    for node in tree.body:
        targets = []
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        if "BUILTIN_STAGE_PLUGINS" in targets and isinstance(value, (ast.Tuple, ast.List)):
            for elt in value.elts:
                if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name):
                    plugin_classes.append(elt.func.id)

    by_family: dict[str, list[str]] = {fam: [] for fam, _ in _MOLCAT_PLUGIN_FAMILY_RULES}
    by_family["other"] = []
    for cls_name in plugin_classes:
        low = cls_name.lower()
        placed = False
        for fam, keywords in _MOLCAT_PLUGIN_FAMILY_RULES:
            if any(kw in low for kw in keywords):
                by_family[fam].append(cls_name)
                placed = True
                break
        if not placed:
            by_family["other"].append(cls_name)
    if not by_family["other"]:
        by_family.pop("other")

    return {
        "available": True,
        "plugin_count": len(plugin_classes),
        "family_counts": {k: len(v) for k, v in by_family.items()},
        "by_family": by_family,
    }


def _detect_gmx_mpi_support() -> dict[str, Any]:
    """Check whether an external-MPI GROMACS binary (required for -multidir HREX) is available."""
    gmx_mpi = shutil.which("gmx_mpi")
    if gmx_mpi is None and Path("/usr/local/gromacs/bin/gmx_mpi").is_file():
        gmx_mpi = "/usr/local/gromacs/bin/gmx_mpi"
    gmx_std = os.environ.get("GMX_BIN") or shutil.which("gmx")
    if gmx_std is None and Path("/usr/local/gromacs/bin/gmx").is_file():
        gmx_std = "/usr/local/gromacs/bin/gmx"
    mpi_library: str | None = None
    binary = gmx_mpi or gmx_std
    if binary:
        try:
            out = subprocess.check_output([binary, "--version"], text=True, stderr=subprocess.STDOUT, timeout=5)
            for line in out.splitlines():
                if "MPI library:" in line:
                    mpi_library = line.split(":", 1)[1].strip()
                    break
        except Exception:  # noqa: BLE001
            mpi_library = None
    external_mpi = bool(gmx_mpi) or (
        mpi_library is not None and mpi_library.lower() not in {"none", "thread_mpi"}
    )
    return {
        "gmx_path": gmx_std,
        "gmx_mpi_path": gmx_mpi,
        "mpi_library": mpi_library,
        "hrex_multidir_available": external_mpi,
        "expanded_ensemble_available": bool(binary),
    }


def _probe_prism_asset() -> dict[str, Any]:
    """Honestly report pinned PRISM subpackage inventory without fabricating weights or features."""
    from moldarwin.boundary.infra import asset_directory
    from moldarwin.physics import PHYSICS_MODULE_BOUNDARIES

    prism_root = asset_directory() / "prism" / "prism"
    subpackages = sorted(
        p.name for p in prism_root.iterdir() if p.is_dir() and not p.name.startswith("_")
    ) if prism_root.is_dir() else []
    gen_models: list[str] = []
    adapters_dir = prism_root / "generation" / "adapters"
    if adapters_dir.is_dir():
        gen_models = sorted(
            p.stem for p in adapters_dir.glob("*.py")
            if p.stem not in {"__init__", "base", "common"}
        )
    has_prism_design = (prism_root / "design").is_dir()
    shims = sorted(
        name for name, meta in PHYSICS_MODULE_BOUNDARIES.items()
        if meta["layer"] == "prism_runtime_compat_shim"
    )
    return {
        "pinned_root_present": prism_root.is_dir(),
        "subpackages": subpackages,
        "generation_adapters_present": gen_models,
        "prism_design_present_in_pinned_asset": has_prism_design,
        "prism_design_note": (
            "prism/design is available in pinned asset."
            if has_prism_design
            else (
                "Pinned asset/prism predates upstream AIB001/PRISM@84b5dfa (prism/design grounded "
                "editing + FLOWR + LLM planner); refresh via tools/vendor_assets.py --asset prism "
                "when ready to adopt it."
            )
        ),
        "runtime_compat_shims_in_moldarwin": shims,
    }


@dataclass(frozen=True, slots=True)
class CaddDomainPack:
    """Introspectable descriptor and three-pillar capability probe for MolDarwin's CADD pack."""

    pack_id: str = CADD_DOMAIN_PACK_ID
    version: str = "2.1"

    def manifest(self) -> dict[str, Any]:
        """Return the self-contained DomainPack contract without importing heavy CADD binaries."""
        from moldarwin.mcp.profiles import (
            RECOMMENDED_V2_PACKS,
            THIN_CORE_TOOLS,
            THREE_PILLAR_PACKS,
            TOOL_PACKS,
        )
        from moldarwin.skill_index import ACTIVE_V2_BUILTIN_SKILLS

        pillar_tools = {pack: sorted(TOOL_PACKS[pack]) for pack in THREE_PILLAR_PACKS}
        total_pillar_tools = sum(len(v) for v in pillar_tools.values())
        return {
            "schema": DOMAIN_PACK_SCHEMA,
            "pack_id": self.pack_id,
            "legacy_pack_id": LEGACY_CADD_DOMAIN_PACK_ID,
            "version": self.version,
            "domain": "computational_chemistry_drug_discovery",
            "noise_regime": "stochastic_multi_fidelity_physics_and_medchem",
            "kernel_contract": {
                "admission_rule": "moldarwin.learn.admissible:rule",
                "journal": "moldarwin.research:ResearchJournal",
                "fault_rsi": "moldarwin.research.fault_rsi:FaultRSIRegistry",
                "authority_package": "moldarwin.authority",
                "sidecar_auditor": "moldarwin.judgment.sidecar:run_sidecar_review",
                "compute_lease": "moldarwin.runtime.lease:ComputeLease",
                "subagent_leases": "moldarwin.runtime.subagents:partition_resources_for_subagents",
                "gpu_packing": "moldarwin.runtime.concurrency:plan_gpu_packing",
                "catalog_indexer": "moldarwin.evolve.catalog:build_building_block_index",
                "rbfe_mapping_guard": "moldarwin.physics.preflight:verify_bond_consistent_atom_mapping",
            },
            "engine_pillars": CADD_ENGINE_PILLARS,
            "mcp_surface": {
                "profile": "thin",
                "recommended_packs": list(RECOMMENDED_V2_PACKS),
                "core_tool_count": len(THIN_CORE_TOOLS),
                "pillar_tool_counts": {k: len(v) for k, v in pillar_tools.items()},
                "total_three_pillar_tools": len(THIN_CORE_TOOLS) + total_pillar_tools,
                "single_pillar_minimal_counts": {
                    k: len(THIN_CORE_TOOLS) + len(v) for k, v in pillar_tools.items()
                },
                "pillar_tools": pillar_tools,
            },
            "active_skills": sorted(ACTIVE_V2_BUILTIN_SKILLS),
            "active_skill_count": len(ACTIVE_V2_BUILTIN_SKILLS),
            "fidelity_ladder": list(CADD_FIDELITY_LADDER),
        }

    def probe_pillars(self) -> dict[str, Any]:
        """Read-only inventory of all three pinned CADD pillars plus MolDarwin's design brain."""
        from moldarwin import skills as skill_catalog

        manifest_assets = _read_asset_manifest()
        molorigin_skills = sorted(
            slug for slug in skill_catalog.WORKFLOWS if slug.startswith("molorigin-")
        )
        molcat_info = _introspect_molcat_plugins()
        prism_info = _probe_prism_asset()

        def _prov(name: str) -> dict[str, Any]:
            row = manifest_assets.get(name, {})
            return {
                "source_commit": row.get("source_commit"),
                "source_committed_at": row.get("source_committed_at"),
                "tree_sha256": row.get("tree_sha256"),
                "copied_files": row.get("copied_files"),
            }

        return {
            "schema": "moldarwin-three-pillar-inventory/1",
            "molorigin": {
                "provenance": _prov("molorigin"),
                "skill_count": len(molorigin_skills),
                "skills": molorigin_skills,
                "mcp_pack": "data",
            },
            "molcat": {
                "provenance": _prov("molcat"),
                **molcat_info,
                "mcp_pack": "screening",
            },
            "prism": {
                "provenance": _prov("prism"),
                **prism_info,
                "mcp_pack": "prism",
            },
            "moldarwin_design": {
                "modules": [
                    "moldarwin.design.pocket",
                    "moldarwin.design.sar",
                    "moldarwin.design.dmta",
                    "moldarwin.evolve.engine",
                ],
                "role": CADD_ENGINE_PILLARS["moldarwin_design"]["role"],
            },
        }

    def probe_capabilities(self) -> dict[str, Any]:
        """Probe live compute, all three CADD pillars, Python engines, and GROMACS readiness."""
        from moldarwin.runtime.environment import probe_environment

        env = probe_environment()
        gmx_info = _detect_gmx_mpi_support()
        pillars = self.probe_pillars()
        py_engines = {
            mod: importlib.util.find_spec(mod) is not None
            for mod in ("rdkit", "alchemlyb", "pymbar", "openmm", "openmmtools", "scipy", "numpy")
        }
        return {
            "schema": "moldarwin-domain-pack-capabilities/2",
            "pack_id": self.pack_id,
            "environment": env,
            "pillars": pillars,
            "gromacs": gmx_info,
            "python_engines": py_engines,
            "recommended_fep_sampling_tier": (
                "tier2_gmx_mpi_multidir_hrex"
                if gmx_info["hrex_multidir_available"]
                else (
                    "tier1_expanded_ensemble_or_rest2_lite"
                    if gmx_info["expanded_ensemble_available"]
                    else "unavailable"
                )
            ),
        }


def get_cadd_domain_pack() -> CaddDomainPack:
    """Return the canonical MolDarwin three-pillar CADD DomainPack instance."""
    return CaddDomainPack()


__all__ = [
    "CADD_DOMAIN_PACK_ID",
    "CADD_ENGINE_PILLARS",
    "CADD_FIDELITY_LADDER",
    "DOMAIN_PACK_SCHEMA",
    "LEGACY_CADD_DOMAIN_PACK_ID",
    "CaddDomainPack",
    "get_cadd_domain_pack",
]
