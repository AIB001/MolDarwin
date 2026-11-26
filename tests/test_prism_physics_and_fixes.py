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
    assert "-deffnm em" in script and "-pme cpu" in script
    assert "-deffnm md" in script and "-nb gpu -pme gpu -bonded gpu -update gpu" in script


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
    assert len(names) == 19
    assert payload["ok"] is True
    assert payload["scorer_elements"]["excluded_by_element"] == {"B": 1}
