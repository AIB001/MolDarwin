"""Tests for the thin MCP tool profile, composable packs, and tiered lazy skill discovery."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from moldarwin import skills
from moldarwin.active import CampaignSpec, CampaignStore, Candidate, Endpoint, Evaluation
from moldarwin.active.schema import canonical
from moldarwin.boundary.prism_v1 import file_identity
from moldarwin.mcp.profiles import (
    ENV_PACKS,
    ENV_PROFILE,
    THIN_CORE_TOOLS,
    TOOL_PACKS,
    pack_summary,
)
from moldarwin.mcp.server import build, tool_catalog
from moldarwin.research import Artifact, ResearchJournal
from moldarwin.research.admission_bindings import record_artifact_with_admission
from moldarwin.skill_index import ENV_SKILL_DIRS, find_skills


def _call_mcp(server, tool_name: str, arguments: dict) -> dict:
    raw = asyncio.run(server.call_tool(tool_name, arguments))
    blocks = raw[0] if isinstance(raw, tuple) else raw
    return json.loads(blocks[0].text)


def test_thin_profile_and_domain_packs_partition_entire_catalog_cleanly(monkeypatch):
    full_names = set(tool_catalog())
    assert len(THIN_CORE_TOOLS) == 16
    assert full_names >= THIN_CORE_TOOLS

    # Packs must be pairwise disjoint, disjoint from THIN_CORE_TOOLS, and cover 100% of full.
    seen = set(THIN_CORE_TOOLS)
    for pack_name, pack_tools in TOOL_PACKS.items():
        assert pack_tools <= full_names, f"unknown tool in pack {pack_name}"
        overlap = seen & pack_tools
        assert not overlap, f"pack {pack_name} overlaps earlier tools: {sorted(overlap)}"
        seen |= pack_tools
    assert seen == full_names, f"tools missing from profiles/packs: {sorted(full_names - seen)}"

    # Thin server registers ONLY the 16 core primitives.
    thin_server = build(profile="thin")
    thin_registered = {item.name for item in asyncio.run(thin_server.list_tools())}
    assert thin_registered == set(THIN_CORE_TOOLS)
    assert len(thin_registered) == 16

    # moldarwin_capabilities(detail="summary") reports only registered tools + available_packs.
    caps = _call_mcp(
        thin_server,
        "moldarwin_capabilities",
        {"detail": "summary", "skills": [], "operations": []},
    )
    assert caps["ok"] is True
    assert set(caps["tools"]) == set(THIN_CORE_TOOLS)
    assert caps["available_packs"] == pack_summary()

    # Composing packs on top of thin adds exact domain tools while keeping authorization signatures.
    monkeypatch.setenv(ENV_PROFILE, "thin")
    monkeypatch.setenv(ENV_PACKS, "screening,governance")
    combo_server = build()
    combo_tools = {item.name: item for item in asyncio.run(combo_server.list_tools())}
    expected = set(THIN_CORE_TOOLS) | set(TOOL_PACKS["screening"]) | set(TOOL_PACKS["governance"])
    assert set(combo_tools) == expected
    assert "gate_json" in combo_tools["moldarwin_screen_submit"].inputSchema["properties"]
    assert "authorization_json" in combo_tools["moldarwin_method_call"].inputSchema["properties"]
    assert "authorization_json" in combo_tools["moldarwin_action_submit"].inputSchema["properties"]


def _write_generated_skill(
    root: Path,
    slug: str,
    *,
    domain: str,
    tags: list[str],
    description: str,
    applicable_when: str,
    invalid_when: str,
    body: str,
    maturity: str = "validated",
    references: dict[str, str] | None = None,
) -> Path:
    skill_dir = root / slug
    skill_dir.mkdir(parents=True)
    tags_yaml = "[" + ", ".join(tags) + "]"
    content = (
        f"---\n"
        f"name: {slug}\n"
        f"description: {description}\n"
        f"domain: {domain}\n"
        f"tags: {tags_yaml}\n"
        f"applicable_when: {applicable_when}\n"
        f"invalid_when: {invalid_when}\n"
        f"maturity: {maturity}\n"
        f"---\n\n"
        f"{body}\n"
    )
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    for rel, text in (references or {}).items():
        target = skill_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return skill_dir


def test_tiered_lazy_skill_discovery_and_live_generated_skills_without_restart(
    tmp_path, monkeypatch
):
    gen_dir = tmp_path / "generated-skills"
    gen_dir.mkdir()

    _write_generated_skill(
        gen_dir,
        "kinase-hinge-protonation",
        domain="target-prep",
        tags=["kinase", "hinge", "protonation", "histidine"],
        description="Assign hinge-region histidine tautomers and pKa states before kinase docking.",
        applicable_when="Target is a protein kinase with a hinge or catalytic His/Asp pair.",
        invalid_when="Non-kinase allosteric pocket with no ionizable hinge residues.",
        body="# Kinase Hinge Protonation\nBODY_SENTINEL_NEVER_READ_AT_TIER1\nSee references/pka.md.",
        references={"references/pka.md": "Hinge His pKa reference table.\n"},
    )
    _write_generated_skill(
        gen_dir,
        "shallow-ppi-box-sizing",
        domain="docking",
        tags=["shallow-ppi", "tudor", "box-sizing"],
        description="Define expanded docking grids for shallow aromatic-cage PPI surfaces.",
        applicable_when="Target has a shallow open PPI pocket such as SND1 Tudor domain.",
        invalid_when="Deep buried catalytic cleft with tight co-crystal ligand.",
        body="# Shallow PPI Box Sizing\nSHALLOW_BODY_SENTINEL",
    )
    _write_generated_skill(
        gen_dir,
        "legacy-cutoff-v0",
        domain="screening",
        tags=["cutoff", "legacy"],
        description="Retired static docking cutoff note.",
        applicable_when="Never — retired.",
        invalid_when="All targets.",
        body="RETIRED_BODY",
        maturity="retired",
    )

    # Also drop a symlinked directory to prove fail-closed skipping.
    outside = tmp_path / "outside-skill"
    outside.mkdir()
    (outside / "SKILL.md").write_text(
        "---\nname: symlinked-bad\ndescription: Should be skipped.\n---\nBody\n", encoding="utf-8"
    )
    (gen_dir / "symlinked-bad").symlink_to(outside)

    monkeypatch.setenv(ENV_SKILL_DIRS, str(gen_dir))
    server = build(profile="thin")

    # Tier 1A: Taxonomy overview across built-in + live generated skills (zero bodies read).
    tax = _call_mcp(server, "moldarwin_skill_find", {"list_domains": True})
    assert tax["ok"] is True
    assert tax["mode"] == "taxonomy"
    assert tax["by_source"]["generated"] == 2
    assert tax["retired_hidden"] == 1
    assert tax["by_domain"]["target-prep"] == 1
    assert tax["coverage"]["bodies_read"] == 0
    assert any("symlink" in row["reason"] for row in tax["coverage"]["skipped_entries"])

    # Tier 1B: Targeted search returns compact card with boundaries & zero body leak.
    hit = _call_mcp(
        server,
        "moldarwin_skill_find",
        {"query": "kinase histidine protonation", "limit": 3},
    )
    assert hit["ok"] is True
    assert hit["coverage"]["bodies_read"] == 0
    assert "BODY_SENTINEL_NEVER_READ_AT_TIER1" not in json.dumps(hit)
    top = hit["skills"][0]
    assert top["slug"] == "kinase-hinge-protonation"
    assert top["source"] == "generated"
    assert top["domain"] == "target-prep"
    assert top["applicable_when"].startswith("Target is a protein kinase")
    assert top["invalid_when"].startswith("Non-kinase allosteric pocket")
    assert top["member_counts"] == {"references": 1, "scripts": 0}
    assert any(m.startswith("tags:") for m in top["matched_on"])

    # Tier 2: Pass the returned read handle directly into moldarwin_skill_read (full SHA-256 check).
    tier2 = _call_mcp(server, top["read"]["tool"], top["read"]["arguments"])
    assert tier2["ok"] is True
    assert "BODY_SENTINEL_NEVER_READ_AT_TIER1" in tier2["content"]
    assert tier2["available_members"] == ["references/pka.md"]

    # Tier 3: Load the deep reference only when explicitly requested.
    tier3 = _call_mcp(
        server,
        "moldarwin_skill_read",
        {**top["read"]["arguments"], "member": "references/pka.md"},
    )
    assert tier3["ok"] is True
    assert "Hinge His pKa reference table." in tier3["content"]

    # Live RSI generation mid-session: write a brand-new fine-grained skill with NO server restart.
    _write_generated_skill(
        gen_dir,
        "fep-net-charge-alchemy",
        domain="md-fep",
        tags=["fep", "net-charge", "alchemical", "co-alchemical-ion"],
        description="Handle net-charge-changing FEP edges with co-alchemical counterions.",
        applicable_when="FEP perturbation changes formal ligand charge.",
        invalid_when="Charge-conserving R-group series.",
        body="# FEP Net-Charge Alchemy\nUse co-alchemical ion pair.",
    )
    live_hit = _call_mcp(
        server, "moldarwin_skill_find", {"query": "fep net charge alchemy", "limit": 2}
    )
    assert live_hit["ok"] is True
    assert live_hit["skills"][0]["slug"] == "fep-net-charge-alchemy"
    live_read = _call_mcp(
        server,
        live_hit["skills"][0]["read"]["tool"],
        live_hit["skills"][0]["read"]["arguments"],
    )
    assert live_read["ok"] is True
    assert "co-alchemical ion pair" in live_read["content"]

    # Retired skills stay hidden by default and appear only when include_retired=True.
    hidden = find_skills(query="legacy cutoff", source="generated")
    assert hidden["skills"] == []
    shown = find_skills(query="legacy cutoff", source="generated", include_retired=True)
    assert [row["slug"] for row in shown["skills"]] == ["legacy-cutoff-v0"]

    # Built-in skills remain discoverable and include available_members on Tier-2 read.
    builtin = find_skills(query="target parameters docking threshold", source="builtin", limit=3)
    assert any(row["slug"] == "target-parameters" for row in builtin["skills"])
    read_builtin = skills.read_member("campaign")
    assert isinstance(read_builtin["available_members"], list)


def test_stealth_record_artifact_with_admission_binds_in_one_call(tmp_path):
    store = CampaignStore(tmp_path / "stealth.sqlite")
    store.configure(
        CampaignSpec("fep", 20.0, "gpu_hour", "stealth-fixture"),
        [Endpoint("fep", "target", "fep", "kcal/mol", "fep/1", 1.0, queryable=True)],
    )
    store.add_candidates([Candidate("mol-s1", "CCO", (1.0,))])
    journal = ResearchJournal(store)

    r1 = store.start_round({"reason": "stealth"})
    action = store.reserve(r1, "mol-s1", "fep", {"reason": "stealth"})
    store.resolve(action.id, Evaluation("mol-s1", "fep", -9.6, "kcal/mol", 1.0, status="ok"))
    store.finish_round(r1, {"done": True})

    out_file = tmp_path / "fep_out.txt"
    out_file.write_text("dG = -9.6 kcal/mol", encoding="utf-8")
    artifact = Artifact(
        str(out_file),
        **file_identity(out_file),
        source_kind="new_execution",
        role="diagnostic",
        bindings={},
    )

    res = record_artifact_with_admission(
        journal,
        artifact,
        action_id=action.id,
        claim_scope={"parent_id": "mol-s1", "protocol": "fep/1"},
        bindings_directory=tmp_path / "bindings",
    )
    assert res["leaf_record_id"] == artifact.id
    assert res["binding"]["admission"] == "admitted"
    assert res["binding"]["target_record_id"] == artifact.id
    # Leaf record itself was never mutated.
    assert canonical(journal.get(artifact.id)) == canonical(journal.get(res["leaf_record_id"]))
