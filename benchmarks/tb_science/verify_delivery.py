#!/usr/bin/env python3
"""Isolated TB-Science-style objective verifier for autonomous MolDarwin runs.

Grades any completed Codex or Claude Code run directory on:
  1. Artifact completeness & valid JSON/CSV structure
  2. Explicit control calibration with real denominators & honest gate discipline
  3. Recomputable candidate table hygiene (no empty/NaN/duplicate IDs)
  4. Real higher-fidelity physics validation evidence (no static-score-only claims)
  5. Charter compliance (wall-clock budget)
  6. Token, turn, and MCP telemetry extraction for cross-host (Codex vs Claude) comparison
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any


def _extract_telemetry(run_dir: Path) -> dict[str, Any]:
    """Parse Codex JSONL or Claude Code JSONL event logs if present."""
    logs_dir = run_dir / "logs"
    codex_log = logs_dir / "codex-events.jsonl"
    claude_log = logs_dir / "claude-events.jsonl"

    if codex_log.is_file():
        turns = 0
        mcp_calls = 0
        input_tokens = 0
        cached_tokens = 0
        output_tokens = 0
        for line in codex_log.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = ev.get("type")
            if et == "turn.completed":
                turns += 1
                usage = ev.get("usage") or {}
                input_tokens += int(usage.get("input_tokens") or 0)
                cached_tokens += int(usage.get("cached_input_tokens") or 0)
                output_tokens += int(usage.get("output_tokens") or 0)
            elif et == "item.completed" and (ev.get("item") or {}).get("type") == "mcp_tool_call":
                mcp_calls += 1
        return {
            "host": "codex",
            "turns": turns,
            "mcp_calls": mcp_calls,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens,
        }

    if claude_log.is_file():
        turns = 0
        mcp_calls = 0
        input_tokens = 0
        cached_tokens = 0
        output_tokens = 0
        for line in claude_log.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                turns += 1
                msg = ev.get("message") or {}
                usage = msg.get("usage") or {}
                input_tokens += int(usage.get("input_tokens") or 0)
                cached_tokens += int(usage.get("cache_read_input_tokens") or 0)
                output_tokens += int(usage.get("output_tokens") or 0)
                for block in msg.get("content") or []:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                        and str(block.get("name", "")).startswith("mcp__moldarwin")
                    ):
                        mcp_calls += 1
        return {
            "host": "claude",
            "turns": turns,
            "mcp_calls": mcp_calls,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens,
        }

    return {"host": "unknown", "turns": None, "mcp_calls": None}


def verify_run(run_dir: Path, charter_path: Path | None = None) -> dict[str, Any]:
    """Grade a finished autonomous MolDarwin run objectively from disk artifacts."""
    delivery = run_dir / "delivery"
    report_path = delivery / "REPORT.md"
    summary_path = delivery / "summary.json"
    candidates_path = delivery / "top_candidates.csv"

    charter: dict[str, Any] = {}
    if charter_path and charter_path.is_file():
        charter = json.loads(charter_path.read_text(encoding="utf-8"))

    checks: dict[str, dict[str, Any]] = {}

    # 1. Deliverables exist & parse cleanly
    report_ok = report_path.is_file() and report_path.stat().st_size >= 300
    summary_data: dict[str, Any] | None = None
    summary_err: str | None = None
    if summary_path.is_file():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary_data = loaded
            else:
                summary_err = "summary.json is not a JSON object"
        except json.JSONDecodeError as exc:
            summary_err = str(exc)
    else:
        summary_err = "missing delivery/summary.json"

    checks["deliverables_present"] = {
        "passed": bool(report_ok and summary_data is not None),
        "report_bytes": report_path.stat().st_size if report_path.is_file() else 0,
        "summary_error": summary_err,
    }

    if summary_data is None:
        return {
            "schema": "moldarwin-tb-science-grade/1",
            "run_dir": str(run_dir),
            "passed": False,
            "reward": 0.0,
            "checks": checks,
            "telemetry": _extract_telemetry(run_dir),
        }

    # 2. Control calibration & epistemic honesty
    cal = summary_data.get("control_calibration")
    gate_passed = bool(summary_data.get("gate_passed"))
    cal_has_denoms = False
    if isinstance(cal, dict):
        pos = cal.get("positives_scored") or cal.get("n_positives")
        neg = cal.get("negatives_scored") or cal.get("n_negatives") or cal.get("n_backgrounds")
        if (pos is None or neg is None) and isinstance(cal.get("label_counts"), dict):
            lc = cal["label_counts"]
            pos = lc.get("strong") or lc.get("positives") or lc.get("active")
            neg = lc.get("weak") or lc.get("negatives") or lc.get("inactive")
            if isinstance(pos, dict):
                pos = pos.get("pooled") or pos.get("total")
            if isinstance(neg, dict):
                neg = neg.get("pooled") or neg.get("total")
        has_metric = any(
            cal.get(k) is not None
            for k in ("roc_auc", "ef5", "cognate_max_top1_rmsd_A", "best_roc_auc", "settings")
        )
        cal_has_denoms = bool(
            (isinstance(pos, int) and pos > 0 and isinstance(neg, int) and neg > 0 and has_metric)
            or (isinstance(cal.get("unique_labeled_assay_controls"), int) and cal["unique_labeled_assay_controls"] > 0 and has_metric)
        )
    checks["control_calibration_recorded"] = {
        "passed": cal_has_denoms,
        "gate_passed": gate_passed,
    }

    # 3. Candidate shortlist integrity (or honest empty/absent shortlist when gate_passed=False)
    screened_count = int(summary_data.get("screened_count") or 0)
    if gate_passed:
        rows: list[dict[str, str]] = []
        valid_rows = 0
        seen_ids: set[str] = set()
        duplicate_ids = 0
        if candidates_path.is_file():
            with candidates_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rows.append(row)
                    cid = (
                        row.get("compound_id")
                        or row.get("id")
                        or row.get("mcule_id")
                        or row.get("name")
                        or ""
                    ).strip()
                    smi = (row.get("smiles") or row.get("SMILES") or "").strip()
                    if cid:
                        if cid in seen_ids:
                            duplicate_ids += 1
                        seen_ids.add(cid)
                    if cid and smi and smi.lower() not in {"na", "nan", "none", "tbd"}:
                        valid_rows += 1
        cand_ok = valid_rows >= 5 and duplicate_ids == 0 and screened_count > 0
        checks["candidate_table_valid"] = {
            "passed": cand_ok,
            "rows": len(rows),
            "valid_rows": valid_rows,
            "duplicate_ids": duplicate_ids,
            "screened_count": screened_count,
        }
    else:
        # Honest no-go must NOT fabricate a large calibrated screen!
        honest_nogo = screened_count == 0
        checks["candidate_table_valid"] = {
            "passed": honest_nogo,
            "mode": "honest_no_go",
            "screened_count": screened_count,
        }

    # 4. Higher-fidelity physics validation present (MD / MM-GBSA / FEP)
    phys = summary_data.get("physics_validation")
    phys_ok = False
    if isinstance(phys, dict) and phys:
        n_traj = (
            phys.get("trajectories_completed")
            or phys.get("completed_systems")
            or phys.get("production_replica_count")
            or 0
        )
        has_obs = bool(
            (isinstance(n_traj, int) and n_traj >= 1)
            or phys.get("systems")
            or phys.get("replicas")
            or phys.get("md_readouts")
            or phys.get("fep_edges")
            or phys.get("status") in {"completed", "partial"}
        )
        phys_ok = has_obs
    elif isinstance(phys, list) and len(phys) >= 1:
        phys_ok = True
    checks["physics_validation_present"] = {"passed": phys_ok}

    # 5. Charter wall-clock compliance (10% grace margin for final writeout)
    wall_s = summary_data.get("wall_clock_s")
    max_min = charter.get("wall_clock_min")
    charter_ok = True
    if max_min is not None and wall_s is not None:
        try:
            wall_val = float(wall_s)
            charter_ok = math.isfinite(wall_val) and wall_val <= float(max_min) * 60.0 * 1.10
        except (TypeError, ValueError):
            charter_ok = False
    checks["charter_wall_clock"] = {
        "passed": charter_ok,
        "wall_clock_s": wall_s,
        "limit_min": max_min,
    }

    all_passed = all(c["passed"] for c in checks.values())
    return {
        "schema": "moldarwin-tb-science-grade/1",
        "run_dir": str(run_dir),
        "task_id": charter.get("task_id"),
        "passed": all_passed,
        "reward": 1.0 if all_passed else 0.0,
        "checks": checks,
        "telemetry": _extract_telemetry(run_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an autonomous MolDarwin TB-Science run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--charter", default=None, type=Path)
    args = parser.parse_args(argv)

    grade = verify_run(args.run_dir.resolve(), args.charter.resolve() if args.charter else None)
    print(json.dumps(grade, indent=2, sort_keys=True))
    return 0 if grade["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
