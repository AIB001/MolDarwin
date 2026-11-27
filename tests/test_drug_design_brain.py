"""First-principles tests for MolDarwin's Drug-Design Brain (pocket, SAR, DMTA, and evolution)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from moldarwin.design import (
    A_OPTIMAL_DMTA_SCHEMA,
    DECONFOUND_SCHEMA,
    DESIGN_DOSSIER_SCHEMA,
    EHVI_RANKING_SCHEMA,
    FREE_WILSON_SCHEMA,
    MMP_DECOMPOSITION_SCHEMA,
    MPO_PROFILE_SCHEMA,
    POCKET_PROFILE_SCHEMA,
    SELECTIVITY_MAP_SCHEMA,
    build_design_dossier,
    decompose_congeneric_series,
    deconfound_sar_signal,
    fit_bayesian_free_wilson,
    map_isoform_selectivity_vectors,
    profile_3d_pocket_and_vectors,
    rank_candidates_ehvi,
    score_drug_design_mpo,
    select_a_optimal_dmta_batch,
)
from moldarwin.evolve import (
    REACTION_ENUMERATION_SCHEMA,
    enumerate_reaction_analogs,
    generate_bioisostere_analogs,
)


def _format_pdb_atom(
    serial: int,
    atom_name: str,
    resname: str,
    chain: str,
    resseq: int,
    xyz: tuple[float, float, float],
    elem: str,
    rec: str = "ATOM",
) -> str:
    x, y, z = xyz
    return (
        f"{rec:<6}{serial:>5d} {atom_name:<4s} {resname:>3s} {chain:1s}{resseq:>4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00          {elem:>2s}"
    )


def _write_synthetic_3d_pocket_and_offtarget(tmp_path: Path) -> tuple[Path, Path, Path, int]:
    """Build a realistic 3D ligand + target pocket + rotated/mutated off-target pocket."""
    # 2-aminopyridine ligand: ring N & exocyclic NH2 form hinge H-bonds; ring CH faces ALA/VAL subpocket
    mol = Chem.AddHs(Chem.MolFromSmiles("Nc1ccccn1"))
    AllChem.EmbedMolecule(mol, randomSeed=7)
    AllChem.MMFFOptimizeMolecule(mol)
    conf = mol.GetConformer()

    # Identify the exocyclic amine N (anchor) and the para/meta carbon C with H (growth vector)
    no_h = Chem.RemoveHs(mol)
    heavy_coords = []
    heavy_syms = []
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() > 1:
            p = conf.GetAtomPosition(atom.GetIdx())
            heavy_coords.append(np.array([p.x, p.y, p.z], dtype=float))
            heavy_syms.append(atom.GetSymbol())

    lig_sdf = tmp_path / "ref_lig.sdf"
    writer = Chem.SDWriter(str(lig_sdf))
    writer.write(mol)
    writer.close()

    # Anchor N is heavy index 0 (exocyclic NH2)
    nh2_xyz = heavy_coords[0]
    # Find farthest aromatic C from NH2 to serve as our isoform-selectivity exit vector
    c_indices = [i for i, sym in enumerate(heavy_syms) if sym == "C"]
    far_c_idx = max(c_indices, key=lambda i: float(np.linalg.norm(heavy_coords[i] - nh2_xyz)))
    far_c_xyz = heavy_coords[far_c_idx]
    ring_center = np.mean(np.vstack(heavy_coords[1:]), axis=0)
    outward_dir = far_c_xyz - ring_center
    outward_dir = outward_dir / np.linalg.norm(outward_dir)
    ortho_dir = np.cross(outward_dir, np.array([0.0, 0.0, 1.0]))
    if np.linalg.norm(ortho_dir) < 1e-3:
        ortho_dir = np.cross(outward_dir, np.array([0.0, 1.0, 0.0]))
    ortho_dir = ortho_dir / np.linalg.norm(ortho_dir)
    z_dir = np.cross(outward_dir, ortho_dir)

    # Target pocket residues:
    # 101 VAL (hinge backbone O at 2.85 A from NH2 -> anchor_locked!)
    hinge_o = nh2_xyz - 2.85 * outward_dir
    hinge_ca = hinge_o + np.array([0.0, 2.2, 0.0])
    # 102 ALA (divergent residue along outward_dir from far_c_xyz at 5.2 A -> open subpocket!)
    div_ca = far_c_xyz + 5.2 * outward_dir
    div_cb = far_c_xyz + 4.5 * outward_dir
    # 103 LEU, 104 ILE, 105 PHE conserved scaffold residues around the pocket
    c103_ca = ring_center + 4.8 * ortho_dir + 1.5 * z_dir
    c104_ca = ring_center - 4.8 * ortho_dir + 1.5 * z_dir
    c105_ca = ring_center + 4.5 * z_dir
    # Retained bridging crystal water near ring
    wat_xyz = ring_center - 3.1 * z_dir

    target_atoms = [
        ("CA", "VAL", 101, hinge_ca, "C"),
        ("O", "VAL", 101, hinge_o, "O"),
        ("CA", "ALA", 102, div_ca, "C"),
        ("CB", "ALA", 102, div_cb, "C"),
        ("CA", "LEU", 103, c103_ca, "C"),
        ("CD1", "LEU", 103, c103_ca - 1.4 * ortho_dir, "C"),
        ("CA", "ILE", 104, c104_ca, "C"),
        ("CD1", "ILE", 104, c104_ca + 1.4 * ortho_dir, "C"),
        ("CA", "PHE", 105, c105_ca, "C"),
        ("CZ", "PHE", 105, c105_ca - 1.1 * z_dir, "C"),
    ]
    target_lines = [
        _format_pdb_atom(i + 1, an, rn, "A", rseq, tuple(xyz), el)
        for i, (an, rn, rseq, xyz, el) in enumerate(target_atoms)
    ]
    target_lines.append(_format_pdb_atom(99, "O", "HOH", "A", 501, tuple(wat_xyz), "O", rec="HETATM"))
    target_lines.append("END")
    target_pdb = tmp_path / "target.pdb"
    target_pdb.write_text("\n".join(target_lines) + "\n", encoding="utf-8")

    # Off-target pocket: mutate 102 ALA -> VAL (bulkier by +51.4 A^3) AND apply rigid 3D rotation + translation!
    angle = 0.65
    rot = np.array([
        [math.cos(angle), -math.sin(angle), 0.0],
        [math.sin(angle), math.cos(angle), 0.0],
        [0.0, 0.0, 1.0],
    ])
    shift = np.array([12.5, -7.2, 4.1])
    off_lines = []
    for i, (an, rn, rseq, xyz, el) in enumerate(target_atoms):
        off_rn = "VAL" if rseq == 102 else rn
        moved = xyz @ rot.T + shift
        off_lines.append(_format_pdb_atom(i + 1, an, off_rn, "A", rseq, tuple(moved), el))
    off_lines.append("END")
    off_pdb = tmp_path / "offtarget.pdb"
    off_pdb.write_text("\n".join(off_lines) + "\n", encoding="utf-8")
    assert no_h.GetNumAtoms() == len(heavy_coords)
    return target_pdb, off_pdb, lig_sdf, far_c_idx


def test_pocket_profile_anchors_exit_vectors_and_kabsch_isoform_selectivity(tmp_path):
    target_pdb, off_pdb, lig_sdf, far_c_idx = _write_synthetic_3d_pocket_and_offtarget(tmp_path)

    prof = profile_3d_pocket_and_vectors(target_pdb, lig_sdf)
    assert prof["schema"] == POCKET_PROFILE_SCHEMA
    # Exocyclic NH2 (heavy index 0) makes 2.85 A H-bond to VAL101 O -> anchor_locked!
    assert 0 in prof["anchor_atom_indices"]
    assert 0 not in prof["editable_atom_indices"]
    # Far aromatic CH points toward ALA102 with clear room -> editable growth vector!
    assert far_c_idx in prof["editable_atom_indices"]
    assert len(prof["water_adjacent_indices"]) >= 1

    sel = map_isoform_selectivity_vectors(target_pdb, off_pdb, lig_sdf, auto_kabsch_align=True)
    assert sel["schema"] == SELECTIVITY_MAP_SCHEMA
    # Kabsch SVD recovers exact rigid-body superposition to sub-0.01 A RMSD
    assert sel["alignment_ca_rmsd_A"] is not None
    assert sel["alignment_ca_rmsd_A"] < 0.01
    assert sel["divergent_residue_count"] == 1
    d0 = sel["selectivity_directives"][0]
    assert d0["target_residue"] == "A:ALA102"
    assert d0["offtarget_residue"] == "A:VAL102"
    assert d0["delta_volume_A3"] == pytest.approx(-51.4, abs=0.2)
    assert d0["mechanism"] == "steric_clash_offtarget_opportunity"
    assert d0["paired_exit_vector"] is not None
    assert d0["paired_exit_vector"]["ligand_heavy_index"] == far_c_idx


def test_bayesian_free_wilson_mmp_activity_cliff_recombination_and_deconfounding():
    # 2-site congeneric N-phenylbenzamide series: R1 (para on aniline ring) x R2 (para on benzoyl ring)
    # True additive effects: R1 (H=0, F=-0.6, Cl=-1.2, CN=-1.8), R2 (H=0, Me=-0.5, OMe=-1.4)
    # Plant one synergistic Activity Cliff at (F, OMe) AND withhold optimal (CN, OMe) to test recombination!
    def _mk(r1: str, r2: str) -> str:
        # r1 on aniline para (prefix attached via carbon/halogen, so nitrile is N#C), r2 on benzoyl para
        p1 = "" if r1 == "H" else r1
        p2 = "" if r2 == "H" else r2
        return f"{p1}c1ccc(NC(=O)c2ccc({p2})cc2)cc1" if p2 else f"{p1}c1ccc(NC(=O)c2ccccc2)cc1"

    base = -8.0
    r1_eff = {"H": 0.0, "F": -0.6, "Cl": -1.2, "N#C": -1.8}
    r2_eff = {"H": 0.0, "C": -0.5, "OC": -1.4}

    records = []
    idx = 0
    for k1, e1 in r1_eff.items():
        for k2, e2 in r2_eff.items():
            # Withhold the optimal (N#C, OC) combination so Free-Wilson must discover & reconstruct it!
            if (k1, k2) == ("N#C", "OC"):
                continue
            idx += 1
            dg = base + e1 + e2
            if (k1, k2) == ("F", "OC"):
                dg -= 1.8  # Planted synergistic Activity Cliff!
            records.append({
                "id": f"cmp_{idx}_{k1}_{k2}",
                "smiles": _mk(k1, k2),
                "target_dg_kcal": dg,
                "uncertainty_kcal": 0.25,
            })

    dec = decompose_congeneric_series(records)
    assert dec["schema"] == MMP_DECOMPOSITION_SCHEMA
    assert dec["decomposed_count"] == len(records)
    assert dec["mmp_count"] >= 10
    assert any(m["classification"] == "activity_cliff" for m in dec["mmps"])

    fw = fit_bayesian_free_wilson(records, include_epistasis=True)
    assert fw["schema"] == FREE_WILSON_SCHEMA
    assert len(fw["varying_sites"]) == 2
    assert fw["loo_cv"]["rmse_kcal"] < 1.2
    # Planted synergistic activity cliff (F, OMe) is caught!
    assert len(fw["activity_cliffs"]) >= 1
    assert any(
        c.get("compound_id", "").endswith("_F_OC") or c.get("direction") == "synergistic_gain"
        for c in fw["activity_cliffs"]
    )
    # Novel withheld combination (N#C, OC) is reconstructed with valid exact canonical SMILES!
    expected_novel_smi = Chem.MolToSmiles(Chem.MolFromSmiles(_mk("N#C", "OC")), canonical=True)
    reconstructed = {p["smiles"]: p for p in fw["novel_combinations"]}
    assert expected_novel_smi in reconstructed
    top_prop = reconstructed[expected_novel_smi]
    assert top_prop["predicted_dg_kcal"] < -10.0
    assert top_prop["prob_improve_over_best"] > 0.0

    # Deconfounding: Case 1 = pure lipophilicity shortcut (must warn!)
    shortcut_rows = []
    alkanes = ["CCC", "CCCC", "CCCCC", "CCCCCC", "CCCCCCC", "CCCCCCCC", "CCCCCCCCC", "CCCCCCCCCC"]
    for i, smi in enumerate(alkanes):
        m = Chem.MolFromSmiles(smi)
        clogp = Chem.Descriptors.MolLogP(m)
        shortcut_rows.append({
            "smiles": smi,
            "score": -1.2 * clogp + (0.05 if i % 2 else -0.05),
            "target_dg_kcal": -1.1 * clogp + (-0.05 if i % 2 else 0.05),
        })
    sc_rep = deconfound_sar_signal(shortcut_rows)
    assert sc_rep["schema"] == DECONFOUND_SCHEMA
    assert sc_rep["raw_pearson_r"] > 0.95
    assert sc_rep["shortcut_warning"] is True
    assert sc_rep["verdict"] == "physicochemical_shortcut_suspected"

    # Case 2 = genuine 3D recognition orthogonal to 2D descriptors (must pass!)
    rng = np.random.default_rng(123)
    true_signal = np.array([-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0])
    genuine_rows = []
    for i, smi in enumerate(alkanes):
        # Shuffle true_signal relative to alkane length so it is orthogonal to MW/cLogP
        sig = float(true_signal[(i * 3) % len(true_signal)])
        genuine_rows.append({
            "smiles": smi,
            "score": sig + float(rng.normal(0, 0.1)),
            "target_dg_kcal": -8.0 + sig + float(rng.normal(0, 0.1)),
        })
    gen_rep = deconfound_sar_signal(genuine_rows)
    assert gen_rep["partial_pearson_r"] > 0.85
    assert gen_rep["shortcut_warning"] is False
    assert gen_rep["verdict"] == "genuine_3d_recognition_signal"


def test_mpo_ehvi_a_optimal_sherman_morrison_and_design_dossier():
    # 1. MPO across Oral, CNS, and PPI-bRo5 + honest MolCat status
    clean_lead = "N#Cc1ccc(NC(=O)c2ccncc2)cc1"
    greasy_aniline = "Cc1ccc(Nc2ccc(CCCC)cc2)cc1"
    m_clean = score_drug_design_mpo(
        clean_lead, target_dg_kcal=-10.5, offtarget_dg_kcal=-7.8, profile="oral"
    )
    m_greasy = score_drug_design_mpo(
        greasy_aniline, target_dg_kcal=-10.5, offtarget_dg_kcal=-10.2, profile="oral"
    )
    assert m_clean["schema"] == MPO_PROFILE_SCHEMA
    assert m_clean["mpo_score"] > m_greasy["mpo_score"]
    assert m_clean["efficiency"]["lle_lipe"] > m_greasy["efficiency"]["lle_lipe"]
    assert m_clean["efficiency"]["selectivity_dddg_kcal"] == pytest.approx(-2.7, abs=1e-3)
    assert m_clean["efficiency"]["selectivity_fold"] > 80.0
    assert m_clean["molcat_plugins"]["status"] == "not_run"
    assert len(m_greasy["metabolic_soft_spots"]) >= 1

    # Supplying MolCat AiZynthFinder readout updates synthesis_score honestly
    m_with_mc = score_drug_design_mpo(
        clean_lead,
        target_dg_kcal=-10.5,
        profile="cns",
        molcat_annotations={"aizynth_solved": True, "aizynth_steps": 2},
    )
    assert m_with_mc["molcat_plugins"]["status"] == "supplied"
    assert m_with_mc["molcat_plugins"]["synthesis_score"] > 0.8

    # 2. Multi-Objective EHVI ranking with uncertainty & hard instability exclusion
    ehvi = rank_candidates_ehvi([
        {
            "candidate_id": "selective_clean",
            "target_dg_kcal": -10.6,
            "target_dg_se": 0.3,
            "selectivity_dddg_kcal": -2.8,
            "mpo_score": 0.88,
            "synthesis_score": 0.90,
        },
        {
            "candidate_id": "dominated_greasy",
            "target_dg_kcal": -8.2,
            "target_dg_se": 0.2,
            "selectivity_dddg_kcal": -0.2,
            "mpo_score": 0.35,
            "synthesis_score": 0.50,
        },
        {
            "candidate_id": "uncertain_upside",
            "target_dg_kcal": -9.8,
            "target_dg_se": 1.4,
            "selectivity_dddg_kcal": -2.0,
            "mpo_score": 0.80,
            "synthesis_score": 0.85,
        },
        {
            "candidate_id": "acyl_chloride_bad",
            "target_dg_kcal": -12.0,
            "selectivity_dddg_kcal": -3.0,
            "mpo_score": 0.90,
            "synthesis_score": 0.90,
            "hard_red_flags": ["acyl_halide"],
        },
    ])
    assert ehvi["schema"] == EHVI_RANKING_SCHEMA
    assert ehvi["rejected_count"] == 1
    by_id = {r["candidate_id"]: r for r in ehvi["ranked"]}
    assert by_id["selective_clean"]["ehvi"] > by_id["dominated_greasy"]["ehvi"]
    assert by_id["uncertain_upside"]["ehvi"] > by_id["dominated_greasy"]["ehvi"]

    # 3. Graph-Laplacian A-Optimal DMTA batch selection + singleton detection
    pool = [
        {"candidate_id": "anchor_1", "smiles": "Nc1ccc(NC(=O)c2ccccc2)cc1", "ehvi": 0.1},
        {"candidate_id": "analog_F", "smiles": "Fc1ccc(NC(=O)c2ccccc2)cc1", "ehvi": 0.45},
        {"candidate_id": "analog_Cl", "smiles": "Clc1ccc(NC(=O)c2ccccc2)cc1", "ehvi": 0.40},
        {"candidate_id": "analog_CN", "smiles": "N#Cc1ccc(NC(=O)c2ccccc2)cc1", "ehvi": 0.55},
        {"candidate_id": "singleton_scaffold", "smiles": "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O", "ehvi": 0.30},
    ]
    batch = select_a_optimal_dmta_batch(pool, measured_ids=["anchor_1"], budget=3)
    assert batch["schema"] == A_OPTIMAL_DMTA_SCHEMA
    assert len(batch["selected_batch"]) == 3
    assert batch["final_posterior_trace"] < batch["initial_posterior_trace"]
    assert batch["trace_reduction_fraction"] > 0.3
    assert "singleton_scaffold" in batch["singleton_candidates"]
    modes = {row["candidate_id"]: row["recommended_fep_mode"] for row in batch["selected_batch"]}
    if "singleton_scaffold" in modes:
        assert modes["singleton_scaffold"] == "abfe_or_bridge_needed"

    # 4. Evidence-bound Design Dossier
    dossier = build_design_dossier(
        [
            {
                "candidate_id": "analog_CN",
                "smiles": clean_lead,
                "target_dg_kcal": -10.5,
                "offtarget_dg_kcal": -7.8,
                "recommended_fep_mode": "rbfe_connected_to_anchor",
                "rationale": "Selectivity vector growth toward ALA102 + Free-Wilson optimal CN",
            }
        ],
        target_name="TYK2",
        offtarget_name="JAK2",
    )
    assert dossier["schema"] == DESIGN_DOSSIER_SCHEMA
    assert "| `analog_CN` |" in dossier["markdown_summary"]


def test_evolve_anchor_protection_and_reaction_enumeration():
    # 1. Anchor protection: 4-chloro-2-methyl-1-fluorobenzene — protect the Cl atom so chloro_* rules skip it!
    parent_smi = "Cc1cc(Cl)ccc1F"
    mol = Chem.MolFromSmiles(parent_smi)
    cl_idx = next(a.GetIdx() for a in mol.GetAtoms() if a.GetSymbol() == "Cl")

    unprotected = generate_bioisostere_analogs(parent_smi, max_analogs=30)
    protected = generate_bioisostere_analogs(
        parent_smi, max_analogs=30, protected_atom_indices=[cl_idx]
    )
    assert any(a["mutation"].startswith("chloro_") for a in unprotected["analogs"])
    assert not any(a["mutation"].startswith("chloro_") for a in protected["analogs"])
    # Unprotected methyl/fluoro vectors still mutate cleanly!
    assert any(a["mutation"].startswith("methyl_") for a in protected["analogs"])

    # 2. Classic medchem reaction enumeration: Amide coupling & Suzuki-Miyaura
    amides = enumerate_reaction_analogs(
        "O=C(O)c1ccncc1",  # isonicotinic acid core
        [
            {"id": "an_cn", "smiles": "Nc1ccc(C#N)cc1"},
            {"id": "an_f", "smiles": "Nc1ccc(F)cc1"},
            {"id": "morph", "smiles": "C1COCCN1"},
        ],
        reaction_name="amide_coupling",
        core_id="isonic",
    )
    assert amides["schema"] == REACTION_ENUMERATION_SCHEMA
    assert amides["product_count"] == 3
    assert all(p["mpo_score"] > 0.5 for p in amides["products"])

    suzuki = enumerate_reaction_analogs(
        "Brc1ccc(C#N)cc1",
        ["OB(O)c1ccncc1", "OB(O)c1ccc(F)cc1"],
        reaction_name="suzuki_miyaura",
        core_id="arbr",
    )
    assert suzuki["product_count"] == 2
