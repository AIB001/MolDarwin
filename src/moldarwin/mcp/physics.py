"""Optional ``prism`` MCP pack: 3 atomic physics preflight, build, and RSI readout primitives.

Deliberately avoids monolithic MD workflows: hardens only low-level invariants (blank SDF
titles, scorer element compatibility, GROMACS 2026 EM/posre compatibility, TPR v138
fallback) and returns compact physical observables that feed MolDarwin's RSI loop.
"""

from __future__ import annotations

from typing import Any, Literal

from moldarwin.mcp._common import Cost, absolute_path, ok, tool


def register(mcp: Any) -> None:
    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_physics_preflight(
        receptor_pdb: str | None = None,
        ligand_path: str | None = None,
        smiles_batch: list[str] | None = None,
        origin: Literal["llm", "cofold", "prism_gen", "docked", "crystal", "unknown"] = "unknown",
        scorer: Literal["unidock", "vina", "smina"] | None = None,
        sanitize_sdf_to: str | None = None,
    ) -> str:
        """FREE. Preflight any 3D protein-ligand complex or SMILES batch before docking or MD.

        Catches blank SDF titles (before PRISM build), unsupported scorer elements (such as
        boron for Uni-Dock), 2D flat depictions, steric clashes, and detached poses across
        LLM, co-fold, generative, docked, or crystal structures. No simulation is started.
        """
        from moldarwin.physics.preflight import (
            preflight_scorer_elements,
            sanitize_ligand_sdf,
            validate_complex_handoff,
        )

        report: dict[str, Any] = {}
        if smiles_batch is not None:
            report["scorer_elements"] = preflight_scorer_elements(
                smiles_batch, scorer=scorer or "unidock"
            )
        if receptor_pdb is not None and ligand_path is not None:
            rec = absolute_path(receptor_pdb, label="receptor_pdb")
            lig = absolute_path(ligand_path, label="ligand_path")
            report["complex"] = validate_complex_handoff(
                rec, lig, origin=origin, scorer=scorer
            )
        if sanitize_sdf_to is not None:
            if ligand_path is None:
                raise ValueError("sanitize_sdf_to requires ligand_path")
            report["sdf_sanitization"] = sanitize_ligand_sdf(
                absolute_path(ligand_path, label="ligand_path"),
                out_path=absolute_path(sanitize_sdf_to, label="sanitize_sdf_to"),
            )
        if not report:
            raise ValueError(
                "supply smiles_batch, (receptor_pdb + ligand_path), or (ligand_path + sanitize_sdf_to)"
            )
        return ok(**report)

    @mcp.tool()
    @tool(Cost.CHEAP)
    def moldarwin_prism_prepare(
        receptor_pdb: str,
        ligand_sdf: str,
        out_dir: str,
        ligand_forcefield: str = "gaff2",
        forcefield: str = "amber14sb",
        water_model: str = "tip3p",
        ligand_resname: str = "LIG",
        prod_ns: float | None = 5.0,
        overwrite: bool = False,
    ) -> str:
        """CHEAP. Sanitize inputs and build a GROMACS 2026-ready explicit-solvent PRISM system.

        Repairs blank ligand SDF titles before calling pinned PRISM, validates generated GRO
        column integrity, stages ligand position restraints, and writes an editable
        run_md_gmx2026.sh script (CPU PME for EM; GPU PME/NB/bonded/update for NVT/NPT/MD).
        Does not launch GPU production MD so the host stays free to schedule runs directly.
        """
        from moldarwin.physics.prism_bridge import prepare_prism_md_system

        result = prepare_prism_md_system(
            absolute_path(receptor_pdb, label="receptor_pdb"),
            absolute_path(ligand_sdf, label="ligand_sdf"),
            absolute_path(out_dir, label="out_dir"),
            ligand_forcefield=ligand_forcefield,
            forcefield=forcefield,
            water_model=water_model,
            ligand_resname=ligand_resname,
            prod_ns=prod_ns,
            overwrite=overwrite,
        )
        return ok(**result)

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_prism_analyze(
        md_dir: str,
        gro_path: str | None = None,
        xtc_path: str | None = None,
        tpr_path: str | None = None,
        ligand_resname: str = "LIG",
        pocket_cutoff_A: float = 4.5,
        hbond_dist_A: float = 3.5,
        key_residues: list[int] | None = None,
        stride: int = 1,
    ) -> str:
        """FREE. Extract compact physical stability observables from a completed MD trajectory.

        Automatically falls back from TPR to whole-molecule GRO+XTC via gmx trjconv when
        MDAnalysis rejects GROMACS 2026 TPR v138. Returns backbone/ligand RMSD and pocket
        contact occupancies for RSI comparison without claiming binding free energy.
        """
        from moldarwin.physics.prism_bridge import analyze_md_trajectory

        result = analyze_md_trajectory(
            absolute_path(md_dir, label="md_dir"),
            gro_path=absolute_path(gro_path, label="gro_path") if gro_path else None,
            xtc_path=absolute_path(xtc_path, label="xtc_path") if xtc_path else None,
            tpr_path=absolute_path(tpr_path, label="tpr_path") if tpr_path else None,
            ligand_resname=ligand_resname,
            pocket_cutoff_A=pocket_cutoff_A,
            hbond_dist_A=hbond_dist_A,
            key_residues=key_residues,
            stride=stride,
        )
        return ok(**result)
