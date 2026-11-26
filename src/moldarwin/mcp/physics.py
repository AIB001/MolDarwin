"""Optional ``prism`` MCP pack: 6 atomic physics preflight, MD/FEP build, and RSI readout primitives.

Deliberately avoids monolithic MD/FEP workflows: hardens only low-level invariants (blank SDF
titles, explicit hydrogens, scorer element compatibility, GROMACS 2026 EM/posre compatibility,
TPR v138 fallback) and returns compact physical observables that feed MolDarwin's RSI loop.
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

    @mcp.tool()
    @tool(Cost.CHEAP)
    def moldarwin_prism_fep_prepare(
        receptor_pdb: str,
        ref_ligand_sdf: str,
        mut_ligand_sdf: str,
        out_dir: str,
        ligand_forcefield: str = "gaff2",
        forcefield: str = "amber14sb",
        water_model: str = "tip3p",
        lambda_windows: int = 11,
        lambda_strategy: str = "decoupled",
        overwrite: bool = False,
    ) -> str:
        """CHEAP. Sanitize reference and mutant ligands and build one pinned PRISM RBFE/FEP edge.

        Enforces blank-title repair and explicit-hydrogen checks on both aligned 3D endpoints
        before calling pinned PRISM, then validates generated GRO integrity. Does not launch
        GPU lambda windows so the host schedules execution freely.
        """
        from moldarwin.physics.prism_fep import prepare_prism_fep_edge

        result = prepare_prism_fep_edge(
            absolute_path(receptor_pdb, label="receptor_pdb"),
            absolute_path(ref_ligand_sdf, label="ref_ligand_sdf"),
            absolute_path(mut_ligand_sdf, label="mut_ligand_sdf"),
            absolute_path(out_dir, label="out_dir"),
            ligand_forcefield=ligand_forcefield,
            forcefield=forcefield,
            water_model=water_model,
            lambda_windows=lambda_windows,
            lambda_strategy=lambda_strategy,
            overwrite=overwrite,
        )
        return ok(**result)

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_prism_fep_analyze(
        edges: list[dict],
        anchor_ligand: str | None = None,
        cycle_closure_limit_kcal: float = 1.0,
        max_edge_uncertainty_kcal: float = 1.0,
    ) -> str:
        """FREE. Audit an RBFE/FEP perturbation network for cycle-closure hysteresis and MLE dG.

        Computes exact 3- and 4-node thermodynamic cycle closure residuals, flags failed or
        high-uncertainty/low-overlap edges, and fits weighted least-squares relative free
        energies without mutating any journal records.
        """
        from moldarwin.physics.prism_fep import analyze_fep_network

        result = analyze_fep_network(
            edges,
            anchor_ligand=anchor_ligand,
            cycle_closure_limit_kcal=cycle_closure_limit_kcal,
            max_edge_uncertainty_kcal=max_edge_uncertainty_kcal,
        )
        return ok(**result)

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_rescore_evaluate(
        records: list[dict],
        scorer_name: str,
        higher_better: bool = False,
        baseline_records: list[dict] | None = None,
        baseline_scorer_name: str = "vina",
        baseline_higher_better: bool = False,
        top_rmsd_cutoff_A: float = 2.0,
        auc_gate: float = 0.70,
        ef5_gate: float = 1.0,
    ) -> str:
        """FREE. Evaluate a scoring or rescoring function on a paired control panel for RSI.

        Computes tie-aware ROC-AUC, fractional-occupancy EF1%/EF5%, positive percentiles, and
        sampling-vs-ranking diagnosis. When baseline_records are provided on the same panel,
        also returns a paired RSI comparison verdict.
        """
        from moldarwin.physics.rescoring import (
            compare_rescorers_for_rsi,
            evaluate_rescorer_panel,
        )

        candidate = evaluate_rescorer_panel(
            records,
            scorer_name=scorer_name,
            higher_better=higher_better,
            top_rmsd_cutoff_A=top_rmsd_cutoff_A,
            auc_gate=auc_gate,
            ef5_gate=ef5_gate,
        )
        out: dict[str, Any] = {"evaluation": candidate}
        if baseline_records is not None:
            baseline = evaluate_rescorer_panel(
                baseline_records,
                scorer_name=baseline_scorer_name,
                higher_better=baseline_higher_better,
                top_rmsd_cutoff_A=top_rmsd_cutoff_A,
                auc_gate=auc_gate,
                ef5_gate=ef5_gate,
            )
            out["baseline"] = baseline
            out["rsi_comparison"] = compare_rescorers_for_rsi(baseline, candidate)
        return ok(**out)
