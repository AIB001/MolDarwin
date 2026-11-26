"""Codex CLI and Claude Code host/advisor parity tests."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from moldarwin import host, host_skills
from moldarwin.judgment import AdvisorError, Advisory, ClaudeCli, CodexCli
from moldarwin.judgment.proposal import Act
from moldarwin.judgment.providers import transport_from_env
from moldarwin.mcp import server as mcp_server
from moldarwin.skill_index import write_generated_skill


def _read_launch_env(project: Path, consumer: str) -> dict[str, str]:
    if consumer == "codex":
        parsed = tomllib.loads((project / ".codex/config.toml").read_text(encoding="utf-8"))
        return dict(parsed["mcp_servers"]["moldarwin"]["env"])
    parsed = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    return dict(parsed["mcpServers"]["moldarwin"]["env"])


@pytest.mark.parametrize("consumer", ["codex", "claude"])
def test_thin_profile_packs_and_skill_dirs_are_symmetric_across_hosts(tmp_path, consumer):
    live_skills = (tmp_path / "live-skills").resolve()
    live_skills.mkdir()
    target = tmp_path / f"export-{consumer}"
    report = host.export(
        target,
        consumer,
        selected_skills=[],
        mcp_profile="thin",
        mcp_packs=["screening", "data"],
        skill_dirs=[live_skills],
    )
    assert report["mcp_profile"] == "thin"
    assert report["mcp_packs"] == ["screening", "data"]
    assert report["skill_dirs"] == [str(live_skills)]
    assert report["skills"] == []

    env = _read_launch_env(target, consumer)
    assert env["MOLDARWIN_MCP_PROFILE"] == "thin"
    assert env["MOLDARWIN_MCP_PACKS"] == "screening,data"
    assert env["MOLDARWIN_SKILL_DIRS"] == str(live_skills)

    verified = host.verify(target)
    assert verified["export_matches_manifest"]
    assert verified["matches_current_source"]
    assert verified["runtime_matches"]

    doc = host.doctor(target)
    assert doc["mcp_profile"] == "thin"
    assert doc["mcp_packs"] == ["screening", "data"]
    assert doc["skill_dirs"] == [str(live_skills)]


@pytest.mark.parametrize("consumer", ["codex", "claude"])
def test_portable_install_rebind_preserves_thin_profile_and_packs(tmp_path, consumer):
    entry = tmp_path / "entry.json"
    entry.write_text("{}", encoding="utf-8")
    live_skills = (tmp_path / "gen-skills").resolve()
    live_skills.mkdir()
    before = tmp_path / f"before-{consumer}"

    installed = host.install(
        before,
        research_entry=entry,
        host=consumer,
        selected_skills=[],
        mcp_profile="thin",
        mcp_packs=["screening"],
        skill_dirs=[live_skills],
    )
    assert installed["status"] == "installed"
    assert installed["mcp_profile"] == "thin"

    after = tmp_path / f"after-{consumer}"
    shutil.copytree(before, after)
    next_entry = tmp_path / "next-entry.json"
    next_entry.write_text("{}", encoding="utf-8")

    rebound = host.install(after, research_entry=next_entry, host=consumer)
    assert rebound["status"] == "rebound"
    env = _read_launch_env(after, consumer)
    assert env["MOLDARWIN_MCP_PROFILE"] == "thin"
    assert env["MOLDARWIN_MCP_PACKS"] == "screening"
    assert env["MOLDARWIN_SKILL_DIRS"] == str(live_skills)
    assert host.verify(after)["matches_current_source"]

    # Explicit switch back to full cleanly drops inherited packs.
    full = host.install(after, research_entry=next_entry, host=consumer, mcp_profile="full")
    assert full["status"] == "rebound"
    env_full = _read_launch_env(after, consumer)
    assert env_full["MOLDARWIN_MCP_PROFILE"] == "full"
    assert "MOLDARWIN_MCP_PACKS" not in env_full


def test_host_export_rejects_invalid_mcp_profile_options(tmp_path):
    with pytest.raises(ValueError, match="mcp_packs requires mcp_profile='thin'"):
        host.export(tmp_path / "bad-full", "codex", mcp_profile="full", mcp_packs=["screening"])
    with pytest.raises(ValueError, match="absolute path"):
        host.export(tmp_path / "bad-rel", "claude", skill_dirs=["relative/skills"])
    with pytest.raises(ValueError, match="unknown MCP tool packs"):
        host.export(tmp_path / "bad-pack", "codex", mcp_profile="thin", mcp_packs=["nonexistent"])


@pytest.mark.parametrize("consumer", ["codex", "claude"])
def test_exported_thin_host_config_serves_16_core_tools_and_live_skills_over_stdio(tmp_path, consumer):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    live_skills = (tmp_path / "live-skills").resolve()
    write_generated_skill(
        live_skills,
        name="alk2-hinge-parity-probe",
        description="Targeted ALK2 hinge calibration for parity test.",
        body="# ALK2 Parity\nCalibrate against ALK2 controls.\n",
        domain="screening",
        tags=("alk2", "parity"),
        applicable_when="ALK2 kinase hinge screening with paired active/inactive controls",
        invalid_when="Missing inactive controls or non-kinase pocket",
    )

    target = tmp_path / f"stdio-{consumer}"
    host.export(target, consumer, selected_skills=[], mcp_profile="thin", skill_dirs=[live_skills])

    if consumer == "codex":
        spec = tomllib.loads((target / ".codex/config.toml").read_text(encoding="utf-8"))["mcp_servers"]["moldarwin"]
    else:
        spec = json.loads((target / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["moldarwin"]

    params = StdioServerParameters(
        command=spec["command"],
        args=spec["args"],
        env={**os.environ, **spec["env"]},
        cwd=str(tmp_path),
    )

    async def probe():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            found = await session.call_tool("moldarwin_skill_find", {"query": "alk2 parity", "limit": 3})
            return [t.name for t in tools.tools], json.loads(found.content[0].text)

    tool_names, found_payload = asyncio.run(asyncio.wait_for(probe(), timeout=30))
    assert len(tool_names) == 16
    assert "moldarwin_skill_find" in tool_names
    assert "moldarwin_revision_compare" in tool_names
    assert found_payload["skills"][0]["slug"] == "alk2-hinge-parity-probe"
    assert found_payload["coverage"]["bodies_read"] == 0


@pytest.mark.parametrize("consumer", ["codex", "claude"])
def test_skills_install_supports_both_codex_and_claude(tmp_path, consumer):
    root = tmp_path / f"proj-{consumer}"
    first = host.install_skills(root, selected_skills=["research"], host=consumer)
    assert first["host"] == consumer
    assert first["verified"]
    expected_root = ".agents/skills" if consumer == "codex" else ".claude/skills"
    assert (root / expected_root / "moldarwin-research" / "SKILL.md").is_file()
    assert Path(first["manifest"]) == root / host_skills.MANIFESTS[consumer]

    again = host.install_skills(root, selected_skills=["research"], host=consumer)
    assert again["written_files"] == 0
    assert again["removed_files"] == 0
    assert again["status"] == "unchanged"


def test_transport_from_env_supports_codex_cli_and_claude_cli(monkeypatch):
    monkeypatch.setenv("MOLDARWIN_LLM_MODEL", "gpt-5.4")
    monkeypatch.setenv("MOLDARWIN_LLM_PROVIDER", "codex-cli")
    codex = transport_from_env()
    assert isinstance(codex, CodexCli)
    assert codex.model == "gpt-5.4"
    assert codex.name == "codex-cli"

    monkeypatch.setenv("MOLDARWIN_LLM_MODEL", "sonnet")
    monkeypatch.setenv("MOLDARWIN_LLM_PROVIDER", "claude-cli")
    claude = transport_from_env()
    assert isinstance(claude, ClaudeCli)
    assert claude.model == "sonnet"


def test_codex_cli_executes_ephemeral_read_only_and_parses_output_file(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(command, *, input, capture_output, text, check, timeout, cwd):
        captured["command"] = list(command)
        captured["input"] = input
        captured["cwd"] = cwd
        out_index = command.index("-o") + 1
        Path(command[out_index]).write_text('{"ids": ["mol-1"], "reason": "best calibrated"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="noisy banner\n", stderr="")

    monkeypatch.setattr("moldarwin.judgment.advisor.shutil.which", lambda b: "/usr/local/bin/codex")
    monkeypatch.setattr("moldarwin.judgment.advisor.subprocess.run", fake_run)

    transport = CodexCli(model="gpt-5.4")
    reply = transport.ask("Return decision JSON")
    assert json.loads(reply)["ids"] == ["mol-1"]
    cmd = captured["command"]
    assert cmd[:8] == [
        "/usr/local/bin/codex", "exec", "--sandbox", "read-only",
        "--skip-git-repo-check", "--ephemeral", "--color", "never",
    ]
    assert "--model" in cmd and "gpt-5.4" in cmd
    assert cmd[-1] == "-"
    assert captured["input"] == "Return decision JSON"

    proposal = Advisory(transport, "codex-test", attempts=1).ask(
        Act.SPEND, "Pick candidate", required=["ids"]
    )
    assert proposal.payload["ids"] == ["mol-1"]


def test_codex_cli_errors_surface_as_advisor_error(monkeypatch):
    monkeypatch.setattr("moldarwin.judgment.advisor.shutil.which", lambda b: None)
    with pytest.raises(AdvisorError, match="no 'codex' on PATH"):
        CodexCli(model="gpt-5.4").ask("Pick")

    monkeypatch.setattr("moldarwin.judgment.advisor.shutil.which", lambda b: "/usr/local/bin/codex")

    def fake_fail(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="auth missing")

    monkeypatch.setattr("moldarwin.judgment.advisor.subprocess.run", fake_fail)
    with pytest.raises(AdvisorError, match="exited 2: auth missing"):
        CodexCli(model="gpt-5.4").ask("Pick")


def test_mcp_server_main_preserves_zero_arg_build_and_role_fallback(tmp_path, monkeypatch):
    role = tmp_path / "HOST.md"
    role.write_text("fallback instructions\n", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "ROLE_PATH", role)
    built = mcp_server.build()
    assert built is not None

    called = []

    class DummyServer:
        def run(self):
            called.append("run")

    def zero_arg_build():
        called.append("build")
        return DummyServer()

    monkeypatch.setattr(mcp_server, "build", zero_arg_build)
    mcp_server.main([])
    assert called == ["build", "run"]
