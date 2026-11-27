"""Pluggable CADD DomainPack boundary cleanly separating MolDarwin's physics stack from its kernel.

After the empirical 6-campaign Verb Census (``tools/verb_census.py``) showed that 16 core
epistemic/RSI verbs + 6 PRISM physics verbs cover 98.5-100% of live work, this module
formalizes the two-layer seam:

  1. **Domain-Agnostic Epistemic & RSI Kernel**: ``ResearchJournal``, ``admission_view``,
     ``reserved_bindings``, ``authority`` (``0/7`` unguarded SPENDS), ``FaultRSIRegistry``
     (Tier-1 physical admission gating), ``subagents``, and lazy ``skill_index``.
  2. **CADD Multi-Fidelity Physics & Evolution DomainPack** (``CaddDomainPack``):
     digest-pinned ``MolCat`` / ``PRISM`` / ``MolOrigin`` + GROMACS 2026 adaptive RBFE +
     Gnina/Uni-Dock rescoring + neutral bioisostere Pareto evolution.

This clean seam keeps MolDarwin v2 lightweight and allows plugging MolDarwin's entire
wet-lab-calibrated CADD stack directly into external domain-agnostic scientific kernels
(e.g., METRON) without dragging 70+ legacy MCP verbs or 21 historical skills along.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOMAIN_PACK_SCHEMA = "moldarwin-domain-pack/1"
CADD_DOMAIN_PACK_ID = "cadd_prism_rbfe"

#: Ordered multi-fidelity CADD verification ladder exported by this DomainPack.
CADD_FIDELITY_LADDER: tuple[dict[str, Any], ...] = (
    {
        "tier": 0,
        "name": "chemistry_preflight",
        "entrypoint": "moldarwin.physics.preflight:preflight_scorer_elements",
        "hard_gate": "valid_neutral_chemistry_and_logged_coverage_loss",
        "tier1_equivalence_required": False,
    },
    {
        "tier": 1,
        "name": "receptor_rescoring_calibration",
        "entrypoint": "moldarwin.physics.rescoring:compare_rescorers",
        "hard_gate": "active_vs_inactive_control_roc_and_property_shortcut_check",
        "tier1_equivalence_required": False,
    },
    {
        "tier": 2,
        "name": "explicit_solvent_md_control",
        "entrypoint": "moldarwin.physics.prism_bridge:evaluate_md_control_gate",
        "hard_gate": "multi_replica_crystal_rmsd_and_pocket_occupancy",
        "tier1_equivalence_required": False,
    },
    {
        "tier": 3,
        "name": "adaptive_rbfe_fep",
        "entrypoint": "moldarwin.physics.adaptive:refine_lambda_schedule_from_overlap",
        "hard_gate": "mbar_adjacent_overlap_ge_0.03_and_cycle_closure_le_1.0_kcal",
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
        "name": "bioisostere_pareto_evolution",
        "entrypoint": "moldarwin.evolve.engine:rank_evolution_generation",
        "hard_gate": "neutral_synthesizable_pareto_over_potency_selectivity_and_risk",
        "tier1_equivalence_required": False,
    },
)


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


@dataclass(frozen=True, slots=True)
class CaddDomainPack:
    """Introspectable descriptor and capability probe for MolDarwin's CADD DomainPack."""

    pack_id: str = CADD_DOMAIN_PACK_ID
    version: str = "2.0"

    def manifest(self) -> dict[str, Any]:
        """Return the self-contained DomainPack contract without importing heavy CADD binaries."""
        from moldarwin.mcp.profiles import RECOMMENDED_V2_PACKS, THIN_CORE_TOOLS, TOOL_PACKS
        from moldarwin.skill_index import ACTIVE_V2_BUILTIN_SKILLS

        prism_tools = sorted(TOOL_PACKS["prism"])
        return {
            "schema": DOMAIN_PACK_SCHEMA,
            "pack_id": self.pack_id,
            "version": self.version,
            "domain": "computational_chemistry_drug_discovery",
            "noise_regime": "stochastic_multi_fidelity_physics",
            "kernel_contract": {
                "admission_rule": "moldarwin.learn.admissible:rule",
                "journal": "moldarwin.research:ResearchJournal",
                "fault_rsi": "moldarwin.research.fault_rsi:FaultRSIRegistry",
                "authority_package": "moldarwin.authority",
                "subagent_leases": "moldarwin.runtime.subagents:partition_resources_for_subagents",
                "gpu_packing": "moldarwin.runtime.concurrency:plan_gpu_packing",
            },
            "mcp_surface": {
                "profile": "thin",
                "packs": list(RECOMMENDED_V2_PACKS),
                "core_tool_count": len(THIN_CORE_TOOLS),
                "domain_tool_count": len(prism_tools),
                "total_v2_tools": len(THIN_CORE_TOOLS) + len(prism_tools),
                "domain_tools": prism_tools,
            },
            "active_skills": sorted(ACTIVE_V2_BUILTIN_SKILLS),
            "active_skill_count": len(ACTIVE_V2_BUILTIN_SKILLS),
            "fidelity_ladder": list(CADD_FIDELITY_LADDER),
        }

    def probe_capabilities(self) -> dict[str, Any]:
        """Probe live compute, CADD engines, and HREX/MPI readiness on the current host."""
        from moldarwin.runtime.environment import probe_environment

        env = probe_environment()
        gmx_info = _detect_gmx_mpi_support()
        py_engines = {
            mod: importlib.util.find_spec(mod) is not None
            for mod in ("rdkit", "alchemlyb", "pymbar", "openmm", "openmmtools", "scipy")
        }
        return {
            "schema": "moldarwin-domain-pack-capabilities/1",
            "pack_id": self.pack_id,
            "environment": env,
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
    """Return the canonical MolDarwin CADD DomainPack instance."""
    return CaddDomainPack()


__all__ = [
    "CADD_DOMAIN_PACK_ID",
    "CADD_FIDELITY_LADDER",
    "DOMAIN_PACK_SCHEMA",
    "CaddDomainPack",
    "get_cadd_domain_pack",
]
