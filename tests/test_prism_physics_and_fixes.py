"""Tests for the 6 live-discovered fixes and the thin PRISM <-> RSI physics bridge."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from moldarwin.active.schema import CampaignSpec, Endpoint
from moldarwin.active.store import CampaignStore
from moldarwin.authority import subject as auth_subject
from moldarwin.authority.method import authorize_method, require_method
from moldarwin.mcp import method_authority
from moldarwin.mcp.profiles import THIN_CORE_TOOLS, TOOL_PACKS
from moldarwin.mcp.server import build as build_mcp
from moldarwin.physics import (
    MD_READOUT_SCHEMA,
    compare_docking_vs_md,
    patch_gromacs2026_artifacts,
    preflight_scorer_elements,
    record_md_readout,
    sanitize_ligand_sdf,
    validate_complex_handoff,
    validate_gro_integrity,
)
from moldarwin.research.admission_bindings import build_admission_view
from moldarwin.research.journal import ResearchJournal
from moldarwin.research.notes import save_progress


def _sample_sdf(title: str = "", z: float = 1.5, extra_atom: str = "C") -> str:
    hz = 0.3 if abs(z) > 0.0 else 0.0
    return (
        f"{title}\n"
        "  RDKit          3D\n"
        "\n"
        "  3  2  0  0  0  0  0  0  0  0999 V2000\n"
        f"    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
        f"    1.4000    0.0000    {z:6.4f} {extra_atom:<3s} 0  0  0  0  0  0  0  0  0  0  0  0\n"
        f"   -0.5000    0.9000    {hz:6.4f} H   0  0  0  0  0  0  0  0  0  0  0  0\n"
        "  1  2  1  0\n"
        "  1  3  1  0\n"
        "M  END\n"
        "$$$$\n"
    )


def _sample_receptor_pdb(x: float = 3.0) -> str:
    return (
        f"ATOM      1  CA  TYR A 766    {x:8.3f}   0.000   0.000  1.00 20.00           C\n"
        f"ATOM      2  OH  TYR A 766    {x + 1.2:8.3f}   0.500   0.200  1.00 20.00           O\n"
        "END\n"
    )


def test_blank_sdf_title_is_repaired_without_mutating_source(tmp_path):
    raw = tmp_path / "blank.sdf"
    raw.write_text(_sample_sdf(title="   "), encoding="utf-8")
    out = tmp_path / "clean.sdf"

    report = sanitize_ligand_sdf(raw, out_path=out, fallback_name="LIG")
    assert report["titles_repaired"] == 1
    assert report["is_3d"] is True
    assert report["has_explicit_hydrogens"] is True
    assert raw.read_text(encoding="utf-8").splitlines()[0] == "   "
    assert out.read_text(encoding="utf-8").splitlines()[0] == "LIG"


def test_validate_gro_integrity_catches_prism_ig_l_corruption(tmp_path):
    good = tmp_path / "good.gro"
    good.write_text(
        "Clean system\n"
        "1\n"
        "    1LIG     C1    1   1.234   2.345   3.456\n"
        "   5.00000   5.00000   5.00000\n",
        encoding="utf-8",
    )
    ok_rep = validate_gro_integrity(good)
    assert ok_rep["valid"] is True
    assert ok_rep["declared_atoms"] == 1

    corrupt = tmp_path / "corrupt.gro"
    corrupt.write_text(
        "Corrupted system\n"
        "1\n"
        "    1LIG     C1IG  L   1.234   2.345   3.456\n"
        "   5.00000   5.00000   5.00000\n",
        encoding="utf-8",
    )
    bad_rep = validate_gro_integrity(corrupt)
    assert bad_rep["valid"] is False
    assert bad_rep["errors"][0]["reason"] == "corrupted_columns"


def test_scorer_element_preflight_catches_boron_for_unidock():
    batch = [
        {"id": "ok_1", "smiles": "CC(=O)Nc1ccc(O)cc1"},
        {"id": "boron_1", "smiles": "OB(O)c1ccccc1"},
        {"id": "silicon_1", "smiles": "C[Si](C)(C)c1ccccc1"},
    ]
    res_unidock = preflight_scorer_elements(batch, scorer="unidock")
    assert res_unidock["admitted_count"] == 1
    assert res_unidock["excluded_count"] == 2
    assert res_unidock["excluded_by_element"] == {"B": 1, "Si": 1}
    assert res_unidock["supported_elements_evidence"] == "measured_here"

    res_smina = preflight_scorer_elements(batch, scorer="smina")
    assert res_smina["admitted_count"] == 3


def test_any_origin_complex_preflight_detects_2d_detached_clash_and_boron(tmp_path):
    rec = tmp_path / "rec.pdb"
    rec.write_text(_sample_receptor_pdb(x=3.0), encoding="utf-8")

    # Good LLM-origin 3D complex
    good_lig = tmp_path / "good.sdf"
    good_lig.write_text(_sample_sdf(title="C26_A2", z=1.5), encoding="utf-8")
    good = validate_complex_handoff(rec, good_lig, origin="llm", scorer="unidock")
    assert good["ready"] is True
    assert good["origin"] == "llm"
    assert good["blocking_issues"] == []

    # 2D flat depiction + boron + blank title
    bad_lig = tmp_path / "bad.sdf"
    bad_lig.write_text(_sample_sdf(title="", z=0.0, extra_atom="B"), encoding="utf-8")
    bad = validate_complex_handoff(rec, bad_lig, origin="cofold", scorer="unidock")
    assert bad["ready"] is False
    codes = {item["code"] for item in bad["blocking_issues"]}
    assert "F_COORDINATES_ARE_A_DEPICTION" in codes
    assert "F_SCORER_UNSUPPORTED_ELEMENTS" in codes
    assert any(w["code"] == "W_BLANK_OR_UNSAFE_SDF_TITLE" for w in bad["warnings"])

    # Detached ligand (> 5 A from receptor)
    far_rec = tmp_path / "far.pdb"
    far_rec.write_text(_sample_receptor_pdb(x=30.0), encoding="utf-8")
    detached = validate_complex_handoff(far_rec, good_lig, origin="docked")
    assert detached["ready"] is False
    assert any(i["code"] == "F_LIGAND_DETACHED_FROM_RECEPTOR" for i in detached["blocking_issues"])


def test_patch_gromacs2026_stages_posre_and_writes_cpu_em_gpu_md_script(tmp_path):
    md_dir = tmp_path / "GMX_PROLIG_MD"
    md_dir.mkdir()
    (md_dir / "solv_ions.gro").write_text("x\n0\n1 1 1\n", encoding="utf-8")
    (md_dir / "em.mdp").write_text("integrator = steep\n", encoding="utf-8")
    (md_dir / "md.mdp").write_text("dt = 0.002\nnsteps = 500000\n", encoding="utf-8")
    (md_dir / "LIG.itp").write_text("[ moleculetype ]\nLIG 3\n", encoding="utf-8")
    (md_dir / "posre_lig.itp").write_text("[ position_restraints ]\n1 1 1000 1000 1000\n", encoding="utf-8")

    rep = patch_gromacs2026_artifacts(md_dir, prod_ns=10.0)
    assert rep["posre"]["patched"] is True
    assert '#include "posre_lig.itp"' in (md_dir / "LIG.itp").read_text(encoding="utf-8")
    assert "nsteps = 5000000" in (md_dir / "md.mdp").read_text(encoding="utf-8")
    script = (md_dir / "run_md_gmx2026.sh").read_text(encoding="utf-8")
    assert 'export OMP_NUM_THREADS="$NTOMP"' in script
    assert "-deffnm em" in script and "-pme cpu" in script and "-r solv_ions.gro" in script
    assert '-deffnm "${OUT_PREFIX}md"' in script and "-nb gpu -pme gpu -bonded gpu -update gpu" in script


def test_patch_gromacs2026_stages_sibling_mdps_and_detects_amb2gmx_posre(tmp_path):
    # Matches exact PRISMBuilder output tree: sibling mdps/ and LIG.amb2gmx/ next to GMX_PROLIG_MD/
    md_dir = tmp_path / "GMX_PROLIG_MD"
    mdps_dir = tmp_path / "mdps"
    amb_dir = tmp_path / "LIG.amb2gmx"
    for d in (md_dir, mdps_dir, amb_dir):
        d.mkdir()
    (md_dir / "solv_ions.gro").write_text("x\n0\n1 1 1\n", encoding="utf-8")
    (mdps_dir / "em.mdp").write_text("define = -DPOSRES\nintegrator = steep\n", encoding="utf-8")
    (mdps_dir / "md.mdp").write_text("dt = 0.002\nnsteps = 250000000\n", encoding="utf-8")
    (amb_dir / "posre_LIG.itp").write_text("[ position_restraints ]\n1 1 1000 1000 1000\n", encoding="utf-8")
    (amb_dir / "LIG.itp").write_text('#ifdef POSRES\n#include "posre_LIG.itp"\n#endif\n', encoding="utf-8")

    rep = patch_gromacs2026_artifacts(md_dir, prod_ns=5.0)
    assert set(rep["staged_mdps"]) == {"em.mdp", "md.mdp"}
    assert rep["md_mdp_patched"] is True
    assert rep["md_nsteps"] == 2500000
    assert "nsteps = 2500000" in (md_dir / "md.mdp").read_text(encoding="utf-8")
    assert rep["posre"]["status"] == "already_included"
    assert rep["posre"]["patched"] is False


def test_prepare_prism_refuses_heavy_atom_only_sdf_before_ambertools(tmp_path):
    from moldarwin.physics import prepare_prism_md_system

    rec = tmp_path / "rec.pdb"
    rec.write_text(_sample_receptor_pdb(x=3.0), encoding="utf-8")
    no_h = tmp_path / "no_h.sdf"
    no_h.write_text(
        "C26\n  RDKit 3D\n\n"
        "  2  1  0  0  0  0  0  0  0  0999 V2000\n"
        "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
        "    1.4000    0.0000    1.5000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
        "  1  2  1  0\nM  END\n$$$$\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="explicit hydrogens"):
        prepare_prism_md_system(rec, no_h, tmp_path / "out")


def test_process_secret_propagates_across_worker_boundary(monkeypatch, tmp_path):
    monkeypatch.delenv("MOLDARWIN_AUTHORITY_KEY", raising=False)
    monkeypatch.setattr(auth_subject, "_PROCESS_SECRET", None)
    secret_bytes = auth_subject.campaign_secret()
    secret_text = secret_bytes.decode("utf-8")
    assert len(secret_text) == 64

    script = tmp_path / "m.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    args = {
        "method_id": "test-method",
        "command": ["python3", str(script)],
        "files": [str(script)],
        "inputs": {"a": 1},
    }
    token = authorize_method(args)

    # Simulate a detached worker inheriting MOLDARWIN_AUTHORITY_KEY from parent service._launch()
    monkeypatch.setattr(auth_subject, "_PROCESS_SECRET", None)
    monkeypatch.setenv("MOLDARWIN_AUTHORITY_KEY", secret_text)
    verified = require_method({**args, "authorization": token.as_dict()}, required=True)
    assert verified["method_id"] == "test-method"

    # Convenience unwrap in tokens_from_json works on authorization_token wrapper too
    unwrapped = method_authority.tokens_from_json(json.dumps({"authorization_token": token.as_dict()}))
    assert unwrapped["action"]["signature"] == token.signature


def test_admission_view_supports_thin_note_entry_gracefully(tmp_path):
    store = CampaignStore(tmp_path / "campaign.sqlite")
    store.configure(
        CampaignSpec(objective="md", budget=10.0, cost_unit="gpu", representation="fp"),
        [Endpoint(id="md", target="SND1", quantity="rmsd", units="A", protocol="gmx", cost=1.0, requires_handoff=False)],
    )
    journal = ResearchJournal(store)
    entry = tmp_path / "entry.json"
    save_progress(
        journal,
        entry,
        {
            "task_id": "snd1-note-test",
            "branch_id": "main",
            "question": "Test note-only admission view",
            "summary": "Initialized note without graph checkpoint",
        },
        directory=tmp_path / "notes",
    )

    view = build_admission_view(entry=str(entry), detail="summary", shadow_nodes=["node-1"])
    assert view["entry_mode"] == "note_entry"
    assert view["graph_checkpoint_present"] is False
    assert view["scientific_admission"] == "not_propagated_without_graph_checkpoint"
    assert view["summary"]["observations_total"] == 0
    assert view["shadow_report"]["status"] == "not_applicable_without_graph_checkpoint"


def test_prism_rsi_readout_recording_and_docking_vs_md_rank_shift(tmp_path):
    store = CampaignStore(tmp_path / "rsi.sqlite")
    store.configure(
        CampaignSpec(objective="md", budget=10.0, cost_unit="gpu", representation="fp"),
        [Endpoint(id="md", target="SND1", quantity="rmsd", units="A", protocol="gmx", cost=1.0, requires_handoff=False)],
    )
    journal = ResearchJournal(store)
    readout = {
        "schema": MD_READOUT_SCHEMA,
        "sim_ns": 10.0,
        "ligand_heavy_rmsd_A": {"mean": 1.1, "final": 0.9, "max": 1.6, "last_20pct_mean": 0.95},
        "pocket_contact_occupancy": 0.98,
    }
    rec = record_md_readout(
        journal,
        readout,
        directory=tmp_path / "readouts",
        candidate_id="C26_A2",
        complex_origin="crystal",
        docking_score=-8.4,
    )
    assert Path(rec["path"]).is_file()
    stored = journal.get(rec["record_id"])
    assert stored["bindings"]["schema"] == MD_READOUT_SCHEMA
    assert stored["bindings"]["candidate_id"] == "C26_A2"

    cmp = compare_docking_vs_md([
        {"candidate_id": "hit_drifter", "docking_score": -9.2, "ligand_rmsd_last_20pct_A": 7.4, "pocket_contact_occupancy": 0.12},
        {"candidate_id": "C26_ctrl", "docking_score": -8.4, "ligand_rmsd_last_20pct_A": 1.0, "pocket_contact_occupancy": 0.99},
        {"candidate_id": "hit_stable", "docking_score": -8.1, "ligand_rmsd_last_20pct_A": 1.4, "pocket_contact_occupancy": 0.94},
    ])
    assert cmp["stable_count"] == 2
    assert cmp["false_positive_drifters"] == ["hit_drifter"]
    assert cmp["spearman_status"] == "measured_here"


def test_prism_mcp_pack_preserves_16_core_thin_tools_and_serves_preflight(tmp_path):
    pytest.importorskip("mcp")
    assert len(THIN_CORE_TOOLS) == 16
    assert "prism" in TOOL_PACKS
    assert TOOL_PACKS["prism"] == frozenset({
        "moldarwin_physics_preflight",
        "moldarwin_prism_prepare",
        "moldarwin_prism_analyze",
        "moldarwin_prism_fep_prepare",
        "moldarwin_prism_fep_analyze",
        "moldarwin_rescore_evaluate",
    })

    mcp = build_mcp(profile="thin", packs=["prism"])

    async def call_preflight():
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        res = await mcp.call_tool(
            "moldarwin_physics_preflight",
            {"smiles_batch": ["CCO", "OB(O)c1ccccc1"], "scorer": "unidock"},
        )
        content = res[0] if isinstance(res, tuple) else res
        return names, json.loads(content[0].text)

    names, payload = asyncio.run(call_preflight())
    assert len(names) == 22
    assert payload["ok"] is True
    assert payload["scorer_elements"]["excluded_by_element"] == {"B": 1}


def test_fep_network_cycle_closure_mle_and_journal_recording(tmp_path):
    from moldarwin.physics import FEP_NETWORK_SCHEMA, analyze_fep_network, record_fep_readout

    # Clean converged 3-cycle: A->B (-1.0), B->C (-0.5), C->A (+1.4) -> hysteresis -0.1 kcal/mol
    clean = analyze_fep_network(
        [
            {"edge_id": "e1", "from_id": "A", "to_id": "B", "ddg_kcal_mol": -1.0, "uncertainty_kcal_mol": 0.2, "overlap_min": 0.15},
            {"edge_id": "e2", "from_id": "B", "to_id": "C", "ddg_kcal_mol": -0.5, "uncertainty_kcal_mol": 0.2, "overlap_min": 0.12},
            {"edge_id": "e3", "from_id": "C", "to_id": "A", "ddg_kcal_mol": 1.4, "uncertainty_kcal_mol": 0.2, "overlap_min": 0.10},
        ],
        anchor_ligand="A",
    )
    assert clean["schema"] == FEP_NETWORK_SCHEMA
    assert clean["network_converged"] is True
    assert clean["cycles_checked"] == 1
    assert abs(clean["max_cycle_closure_abs_kcal_mol"] - 0.1) < 1e-6
    assert clean["relative_dg_kcal_mol"]["A"] == 0.0
    assert clean["relative_dg_kcal_mol"]["C"] < clean["relative_dg_kcal_mol"]["B"] < 0.0

    # Broken hysteresis 3-cycle (+2.5 kcal/mol) must fail convergence
    bad = analyze_fep_network([
        {"from_id": "A", "to_id": "B", "ddg_kcal_mol": -1.0, "uncertainty_kcal_mol": 0.2},
        {"from_id": "B", "to_id": "C", "ddg_kcal_mol": -0.5, "uncertainty_kcal_mol": 0.2},
        {"from_id": "C", "to_id": "A", "ddg_kcal_mol": 4.0, "uncertainty_kcal_mol": 0.2},
    ])
    assert bad["network_converged"] is False
    assert bad["cycles_exceeding_limit"] == 1

    store = CampaignStore(tmp_path / "fep.sqlite")
    store.configure(
        CampaignSpec(objective="md", budget=10.0, cost_unit="gpu", representation="fp"),
        [Endpoint(id="md", target="SND1", quantity="rmsd", units="A", protocol="gmx", cost=1.0, requires_handoff=False)],
    )
    rec = record_fep_readout(ResearchJournal(store), clean, directory=tmp_path / "fep-out", target="SND1", series_id="C26")
    assert Path(rec["path"]).is_file()


def test_rescorer_evaluation_and_paired_rsi_rescue_verdict():
    from moldarwin.physics import compare_rescorers_for_rsi, evaluate_rescorer_panel

    # Reproduce SND1-MTDH pattern: Vina samples 1.11 A best pose, but ranks poorly (AUC < 0.4)
    vina_panel = [
        {"id": "C26_A2", "is_positive": True, "score": -6.2, "top1_rmsd_A": 4.11, "best_mode_rmsd_A": 1.11},
        {"id": "C26_A6", "is_positive": True, "score": -6.0, "top1_rmsd_A": 6.50, "best_mode_rmsd_A": 1.13},
        *[{"id": f"bg_{i}", "is_positive": False, "score": -7.5 + 0.08 * i} for i in range(30)],
    ]
    base = evaluate_rescorer_panel(vina_panel, scorer_name="vina", higher_better=False)
    assert base["passed_gate"] is False
    assert base["diagnosis"] == "sampling_succeeded_but_ranking_failed"
    assert base["sampling_succeeded"] is True
    assert base["top1_pose_recovered"] is False

    # Candidate CNN rescorer rescues top-1 pose to 1.15 A and pushes positives to top ranks
    cnn_panel = [
        {"id": "C26_A2", "is_positive": True, "score": 0.92, "top1_rmsd_A": 1.15, "best_mode_rmsd_A": 1.11},
        {"id": "C26_A6", "is_positive": True, "score": 0.88, "top1_rmsd_A": 1.30, "best_mode_rmsd_A": 1.13},
        *[{"id": f"bg_{i}", "is_positive": False, "score": 0.70 - 0.02 * i} for i in range(30)],
    ]
    cand = evaluate_rescorer_panel(cnn_panel, scorer_name="gnina_cnn", higher_better=True)
    assert cand["passed_gate"] is True
    assert cand["roc_auc"] == 1.0
    assert cand["ef5"] > 1.0

    cmp = compare_rescorers_for_rsi(base, cand)
    assert cmp["verdict"] == "improved_and_calibrated"
    assert cmp["delta_roc_auc"] > 0.5
    assert cmp["delta_top1_rmsd_A"] < -4.0


def test_prism_gen_qualification_and_builtin_prism_skill_discoverable(tmp_path):
    from moldarwin.physics import qualify_generated_poses
    from moldarwin.skill_index import find_skills

    rec = tmp_path / "rec.pdb"
    rec.write_text(_sample_receptor_pdb(x=3.0), encoding="utf-8")
    p1 = tmp_path / "p1.sdf"
    p2 = tmp_path / "p2_dup.sdf"
    p3 = tmp_path / "p3_bad.sdf"
    p1.write_text(_sample_sdf(title="", z=1.5), encoding="utf-8")
    p2.write_text(_sample_sdf(title="", z=1.5), encoding="utf-8")
    p3.write_text(_sample_sdf(title="B1", z=0.0, extra_atom="B"), encoding="utf-8")

    qual = qualify_generated_poses(rec, [p1, p2, p3], origin="prism_gen", scorer="unidock", sanitize_dir=tmp_path / "san")
    assert qual["ready_count"] == 1
    assert qual["duplicate_count"] == 1
    assert qual["rejected_count"] == 1
    assert Path(qual["ready"][0]["sanitized_path"]).read_text(encoding="utf-8").splitlines()[0] == "GEN1"

    found = find_skills(query="prism gromacs fep rescoring", limit=5)
    assert any(card["slug"] == "prism-physics" for card in found["skills"])
    assert found["coverage"]["bodies_read"] == 0


def test_fep_sdf_gro_coordinate_verification_accepts_match_and_rejects_drift(tmp_path):
    from moldarwin.physics.prism_fep import _verify_sdf_matches_gro

    sdf = tmp_path / "lig.sdf"
    sdf.write_text(
        "LIG\n  MolDarwin\n\n  2  1  0  0  0  0  0  0  0  0999 V2000\n"
        "    1.0000    2.0000    3.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n"
        "    2.0000    2.0000    3.0000 H   0  0  0  0  0  0  0  0  0  0  0  0\n"
        "  1  2  1  0\nM  END\n$$$$\n",
        encoding="utf-8",
    )
    gro_ok = tmp_path / "LIG_ok.gro"
    gro_ok.write_text(
        "LIG\n2\n"
        "    1LIG     C1    1   0.100   0.200   0.300\n"
        "    1LIG     H1    2   0.200   0.200   0.300\n"
        "   5.00000   5.00000   5.00000\n",
        encoding="utf-8",
    )
    rec = _verify_sdf_matches_gro(sdf, gro_ok)
    assert rec["atoms"] == 2
    assert rec["max_displacement_A"] == pytest.approx(0.0)

    gro_bad = tmp_path / "LIG_bad.gro"
    gro_bad.write_text(
        "LIG\n2\n"
        "    1LIG     C1    1   0.500   0.200   0.300\n"
        "    1LIG     H1    2   0.200   0.200   0.300\n"
        "   5.00000   5.00000   5.00000\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="coordinate drift"):
        _verify_sdf_matches_gro(sdf, gro_bad)


def test_conserved_pocket_waters_md_control_gate_and_fep_mdp_patch(tmp_path):
    from moldarwin.physics import (
        evaluate_md_control_gate,
        patch_gromacs2026_artifacts,
        patch_prism_fep_mdps,
        select_conserved_pocket_waters,
    )

    # 1. Conserved bridging water selection: retains W1 (bridge, low B), rejects W2 (high B), W3 (far bulk)
    raw_pdb = tmp_path / "raw.pdb"
    raw_pdb.write_text(
        "ATOM      1  OG  SER A  10       3.000   0.000   0.000  1.00 20.00           O\n"
        "HETATM    2  O   HOH A 201       1.500   1.000   0.000  1.00 22.00           O\n"
        "HETATM    3  O   HOH A 202       1.500  -1.000   0.000  1.00 60.00           O\n"
        "HETATM    4  O   HOH A 203      15.000  15.000  15.000  1.00 18.00           O\n"
        "END\n",
        encoding="utf-8",
    )
    lig_sdf = tmp_path / "lig.sdf"
    lig_sdf.write_text(_sample_sdf(title="LIG", z=0.5), encoding="utf-8")
    w_rep = select_conserved_pocket_waters(
        raw_pdb, lig_sdf, out_pdb=tmp_path / "rec_with_wat.pdb", receptor_base_pdb=raw_pdb
    )
    assert w_rep["total_crystal_waters"] == 3
    assert w_rep["retained_count"] == 1
    assert w_rep["retained_waters"][0]["water_id"] == "A:201"
    assert Path(w_rep["written_pdb"]).is_file()

    # 2. Multi-replica MD control gate
    g_pass = evaluate_md_control_gate([
        {"ligand_rmsd_last_20pct_A": 0.75, "pocket_contact_occupancy": 1.0},
        {"ligand_rmsd_last_20pct_A": 1.48, "pocket_contact_occupancy": 0.98},
        {"ligand_rmsd_last_20pct_A": 1.20, "pocket_contact_occupancy": 0.99},
    ])
    assert g_pass["passed_gate"] is True
    assert g_pass["median_tail_rmsd_A"] == pytest.approx(1.2)

    g_fail = evaluate_md_control_gate([
        {"ligand_rmsd_last_20pct_A": 4.72, "pocket_contact_occupancy": 1.0},
        {"ligand_rmsd_last_20pct_A": 3.80, "pocket_contact_occupancy": 1.0},
    ])
    assert g_fail["passed_gate"] is False

    # 3. PRISM FEP prod_*.mdp patching (500 ns -> 2.0 ns, calc-lambda-neighbors -> -1, zero trr)
    fep_dir = tmp_path / "GMX_PROLIG_FEP"
    mdp_dir = fep_dir / "bound" / "repeat1" / "mdps"
    mdp_dir.mkdir(parents=True)
    (mdp_dir / "prod_00.mdp").write_text(
        "integrator = md\ndt = 0.002\nnsteps = 250000000\n"
        "nstxout = 5000\nnstvout = 5000\nnstxout-compressed = 250000\n"
        "calc-lambda-neighbors = 1\n",
        encoding="utf-8",
    )
    fep_patch = patch_prism_fep_mdps(fep_dir, prod_ns=2.0, calc_lambda_neighbors=-1, zero_trr=True)
    assert fep_patch["patched_count"] == 1
    assert fep_patch["target_nsteps"] == 1000000
    patched_txt = (mdp_dir / "prod_00.mdp").read_text(encoding="utf-8")
    assert "nsteps = 1000000" in patched_txt
    assert "calc-lambda-neighbors = -1" in patched_txt
    assert "nstxout = 0" in patched_txt

    # 4. Staged equilibration + replica seed support in run_md_gmx2026.sh
    md_dir = tmp_path / "md_staged"
    md_dir.mkdir()
    (md_dir / "solv_ions.gro").write_text("S\n0\n 5 5 5\n", encoding="utf-8")
    (md_dir / "npt.mdp").write_text("define = -DPOSRES\nnsteps = 50000\n", encoding="utf-8")
    (md_dir / "md.mdp").write_text("dt = 0.002\nnsteps = 1000\n", encoding="utf-8")
    p_rep = patch_gromacs2026_artifacts(md_dir, prod_ns=10.0, staged_equilibration=True)
    assert p_rep["staged_equilibration"] is True
    assert (md_dir / "npt_release.mdp").is_file()
    sh = Path(p_rep["script_path"]).read_text(encoding="utf-8")
    assert "GMX_GEN_SEED" in sh
    assert "npt_release.mdp" in sh

    # 5. Invariant dummy-atom mass patching for GROMACS 2026 -update gpu
    from moldarwin.physics import enforce_invariant_dummy_masses

    hyb = tmp_path / "hybrid.itp"
    hyb.write_text(
        "[ atoms ]\n"
        "     1       DUM_ha      1    LIG    H12      1   0.000000   12.01100           ha   0.100000    1.00800 ; dummy->H\n"
        "     2           ca      1    LIG     C1      2  -0.120000   12.01100           ca  -0.120000   12.01100 ; common\n",
        encoding="utf-8",
    )
    m_rep = enforce_invariant_dummy_masses(hyb)
    assert m_rep["changed_atoms"] == 1
    assert m_rep["changes"][0]["new_mass"] == pytest.approx(1.008)
    assert "1.00800" in hyb.read_text(encoding="utf-8").splitlines()[1]
    assert (tmp_path / "hybrid.itp.prism_original").is_file()
