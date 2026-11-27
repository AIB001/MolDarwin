#!/usr/bin/env python3
"""Empirical MCP Verb Census from live campaign logs against MolDarwin's registered tool surface.

Answers ``docs/thin-harness/RSI_ARCHITECTURE.md`` §9 mechanically: scans one or more run
directories containing Codex/host JSONL transcripts (``*events*.jsonl``), tallies actual MCP
tool invocations, and reports coverage by ``THIN_CORE_TOOLS`` and optional ``TOOL_PACKS`` along
with zero-use verbs eligible for deprecation or pack-folding.

Usage::

    python tools/verb_census.py /path/to/runs
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any


def census_logs(roots: list[Path]) -> dict[str, Any]:
    from moldarwin.mcp.profiles import THIN_CORE_TOOLS, TOOL_PACKS
    from moldarwin.mcp.server import tool_catalog

    catalog = tool_catalog()
    total_counts: collections.Counter[str] = collections.Counter()
    per_run: dict[str, collections.Counter[str]] = {}
    scanned_files: list[str] = []

    for root in roots:
        if root.is_file():
            files = [root]
        else:
            files = sorted({*root.glob("*/*.jsonl"), *root.glob("*/*/*.jsonl"), *root.glob("*.jsonl")})
        for path in files:
            scanned_files.append(str(path))
            run_id = path.parent.parent.name if path.parent.name == "logs" else path.parent.name
            rc = per_run.setdefault(run_id, collections.Counter())
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item = obj.get("item") if isinstance(obj, dict) else None
                if isinstance(item, dict) and item.get("type") == "mcp_tool_call":
                    tool_name = item.get("tool") or item.get("name")
                    if isinstance(tool_name, str) and tool_name:
                        total_counts[tool_name] += 1
                        rc[tool_name] += 1

    total_calls = sum(total_counts.values())
    used_verbs = sorted(total_counts)
    unused_verbs = sorted(set(catalog) - set(used_verbs))
    thin_calls = sum(v for k, v in total_counts.items() if k in THIN_CORE_TOOLS)
    thin_plus_prism = THIN_CORE_TOOLS | TOOL_PACKS.get("prism", frozenset())
    thin_prism_calls = sum(v for k, v in total_counts.items() if k in thin_plus_prism)

    by_pack: dict[str, dict[str, Any]] = {}
    for pack, tools in sorted(TOOL_PACKS.items()):
        pack_calls = sum(total_counts.get(t, 0) for t in tools)
        pack_used = sorted(t for t in tools if total_counts.get(t, 0) > 0)
        by_pack[pack] = {
            "tool_count": len(tools),
            "used_tools": pack_used,
            "calls": pack_calls,
            "zero_use_pack": pack_calls == 0,
        }

    return {
        "schema": "moldarwin-verb-census/1",
        "evidence": "measured_here",
        "scanned_files": len(scanned_files),
        "runs_with_mcp_calls": sum(1 for c in per_run.values() if c),
        "catalog_tool_count": len(catalog),
        "distinct_verbs_used": len(used_verbs),
        "total_calls": total_calls,
        "surface_utilization_fraction": round(len(used_verbs) / max(len(catalog), 1), 4),
        "thin_core_tool_count": len(THIN_CORE_TOOLS),
        "thin_core_call_share": round(thin_calls / max(total_calls, 1), 4) if total_calls else 0.0,
        "thin_plus_prism_call_share": round(thin_prism_calls / max(total_calls, 1), 4) if total_calls else 0.0,
        "verb_counts": dict(total_counts.most_common()),
        "by_pack": by_pack,
        "zero_use_packs": sorted(p for p, info in by_pack.items() if info["zero_use_pack"]),
        "zero_use_tool_count": len(unused_verbs),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path, help="Run directory or JSONL transcript path(s)")
    args = parser.parse_args(argv)
    report = census_logs(args.roots)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
