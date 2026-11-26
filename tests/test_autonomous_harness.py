"""Tests for the thin autonomous planning harness, compute probe, and TB-Science verifier."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from moldarwin.mcp.profiles import THIN_CORE_TOOLS
from moldarwin.mcp.server import build as build_mcp
from moldarwin.runtime import environment


def test_probe_environment_separates_idle_and_busy_gpus(monkeypatch, tmp_path):
    fake_csv = (
        "0, NVIDIA RTX PRO 6000, 98304, 120, 0\n"
        "1, NVIDIA RTX PRO 6000, 98304, 42000, 88\n"
        "2, NVIDIA RTX PRO 6000, 98304, 763, 2\n"
        "3, NVIDIA RTX PRO 6000, 98304, 800, 60\n"
    )
    monkeypatch.setattr(environment.shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd in {"nvidia-smi", "unidock", "gnina", "gmx"} else None)
    monkeypatch.setattr(
        environment.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=fake_csv, stderr=""),
    )
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.delenv("MOLDARWIN_ALLOWED_GPUS", raising=False)

    charter = tmp_path / "charter.json"
    charter.write_text(json.dumps({"wall_clock_min": 45, "gpu_policy": "idle_only"}), encoding="utf-8")

    env = environment.probe_environment(tmp_path, charter_path=charter)
    assert env["schema"] == environment.ENV_SCHEMA
    assert env["gpus"]["idle_gpus"] == [0, 2]
    assert env["gpus"]["busy_gpus"] == [1, 3]
    assert env["engines_cli"] == ["gmx", "gnina", "unidock"]
    assert env["charter"]["wall_clock_min"] == 45

    card = environment.format_environment_card(env)
    assert "[moldarwin-env]" in card
    assert "idle_gpus=[0, 2]" in card
    assert "busy_gpus=[1, 3](DO_NOT_USE)" in card
    assert "wall_clock_min=45" in card
    # Keep card ultra-compact (< 500 bytes ≈ ~120 tokens)
    assert len(card.encode("utf-8")) < 500


def test_estimate_experiment_budget_scales_from_micro_pilot():
    est = environment.estimate_experiment_budget(
        pilot_items=120,
        pilot_wall_s=36.0,
        remaining_wall_min=30.0,
        available_gpus=8,
        pilot_gpus=1,
        safety_fraction=0.5,
        target_items=10000,
    )
    assert est["throughput_items_per_gpu_min"] == pytest.approx(200.0)
    assert est["recommended_max_items"] == 24000
    assert est["estimated_target_wall_min"] == pytest.approx(6.25)
    assert est["fits_budget"] is True


def test_thin_core_unchanged_and_capabilities_supports_include_environment():
    assert len(THIN_CORE_TOOLS) == 16
    mcp = build_mcp(profile="thin")
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert len(names) == 16

    raw = asyncio.run(
        mcp.call_tool(
            "moldarwin_capabilities",
            {
                "detail": "summary",
                "skills": [],
                "tools": [],
                "operations": [],
                "include_environment": True,
            },
        )
    )
    payload = json.loads(raw[0][0].text) if isinstance(raw, tuple) else json.loads(raw[0].text)
    assert payload["ok"] is True
    assert payload["environment"]["schema"] == environment.ENV_SCHEMA
    assert "[moldarwin-env]" in payload["environment_card"]


def test_autonomous_planning_skill_is_lazily_discoverable():
    mcp = build_mcp(profile="thin")
    raw = asyncio.run(
        mcp.call_tool(
            "moldarwin_skill_find",
            {"query": "autonomous planning budget micro-pilot idle gpu tb-science"},
        )
    )
    payload = json.loads(raw[0][0].text) if isinstance(raw, tuple) else json.loads(raw[0].text)
    items = payload.get("hits") or payload.get("cards") or payload.get("skills") or []
    slugs = [c["slug"] for c in items]
    assert "autonomous-planning" in slugs


def test_tb_science_verifier_grades_go_nogo_and_rejects_uncalibrated_screen(tmp_path):
    verifier_path = Path(__file__).resolve().parents[1] / "benchmarks" / "tb_science" / "verify_delivery.py"
    spec = importlib.util.spec_from_file_location("tb_verify", verifier_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    charter = tmp_path / "charter.json"
    charter.write_text(json.dumps({"task_id": "test_task", "wall_clock_min": 45}), encoding="utf-8")

    # Case 1: valid calibrated Go run with MD validation
    run_go = tmp_path / "run_go"
    (run_go / "delivery").mkdir(parents=True)
    (run_go / "delivery" / "REPORT.md").write_text("# Report\n" + ("Measured details. " * 30), encoding="utf-8")
    (run_go / "delivery" / "summary.json").write_text(
        json.dumps({
            "target": "HSP90",
            "gate_passed": True,
            "control_calibration": {"positives_scored": 4, "negatives_scored": 120, "roc_auc": 0.89, "ef5": 12.0},
            "screened_count": 10000,
            "physics_validation": {"trajectories_completed": 6},
            "wall_clock_s": 1800,
        }),
        encoding="utf-8",
    )
    (run_go / "delivery" / "top_candidates.csv").write_text(
        "compound_id,smiles,score\n" + "\n".join(f"C{i},CCO{-i%2 or ''},{-8.0 - i*0.1}" for i in range(6)),
        encoding="utf-8",
    )
    grade_go = mod.verify_run(run_go, charter)
    assert grade_go["passed"] is True
    assert grade_go["reward"] == 1.0

    # Case 2: dishonest run that screens 10k despite gate_passed=False -> MUST FAIL
    run_bad = tmp_path / "run_bad"
    (run_bad / "delivery").mkdir(parents=True)
    (run_bad / "delivery" / "REPORT.md").write_text("# Report\n" + ("Details. " * 50), encoding="utf-8")
    (run_bad / "delivery" / "summary.json").write_text(
        json.dumps({
            "target": "KEAP1",
            "gate_passed": False,
            "control_calibration": {"positives_scored": 2, "negatives_scored": 120, "roc_auc": 0.35},
            "screened_count": 10000,
            "physics_validation": {"trajectories_completed": 2},
            "wall_clock_s": 900,
        }),
        encoding="utf-8",
    )
    grade_bad = mod.verify_run(run_bad, charter)
    assert grade_bad["passed"] is False
    assert grade_bad["checks"]["candidate_table_valid"]["passed"] is False


def test_session_start_hook_injects_env_card_only_when_opted_in(monkeypatch, tmp_path):
    from moldarwin import research_hooks
    from moldarwin.active.schema import CampaignSpec, Endpoint
    from moldarwin.active.store import CampaignStore
    from moldarwin.research.journal import ResearchJournal
    from moldarwin.research.notes import save_progress

    store = CampaignStore(tmp_path / "campaign.sqlite")
    store.configure(
        CampaignSpec(objective="md", budget=10.0, cost_unit="gpu", representation="3d"),
        [Endpoint(id="md", target="HSP90", quantity="rmsd", units="A", protocol="gmx", cost=1.0, requires_handoff=False)],
    )
    entry = tmp_path / "entry.json"
    save_progress(
        ResearchJournal(store),
        entry,
        {
            "task_id": "env-hook-test",
            "branch_id": "main",
            "question": "Verify optional SessionStart env card injection",
            "summary": "init",
        },
    )

    monkeypatch.delenv("MOLDARWIN_SESSION_ENV_PROBE", raising=False)
    monkeypatch.delenv("MOLDARWIN_CHARTER_PATH", raising=False)
    r_off = research_hooks.handle_event(
        str(entry),
        {"hook_event_name": "SessionStart", "session_id": "s1", "event_id": "e1"},
        host="codex",
        state_dir=tmp_path / "hooks_off",
    )
    assert "[moldarwin-env]" not in r_off["host_output"]["hookSpecificOutput"]["additionalContext"]

    monkeypatch.setenv("MOLDARWIN_SESSION_ENV_PROBE", "1")
    r_on = research_hooks.handle_event(
        str(entry),
        {"hook_event_name": "SessionStart", "session_id": "s2", "event_id": "e2"},
        host="codex",
        state_dir=tmp_path / "hooks_on",
    )
    assert "[moldarwin-env]" in r_on["host_output"]["hookSpecificOutput"]["additionalContext"]
