#!/usr/bin/env python3
"""Verify Track 1 + Track 2 token efficiency, live RSI loop, and falsifier controls.

Measures three concrete properties against the real MolDarwin stack (zero mocks of
admission, revision scoring, skill indexing, or MCP registration):

1. **Token efficiency (measured bytes):**
   - MCP ``thin`` profile (16 tools) vs ``full`` profile (92 tools) tool-schema payload size.
   - Tier-1 ``moldarwin_skill_find`` over built-in + 50 live generated fine-grained skills
     (``bodies_read == 0``) vs dumping the full catalog.
   - ``moldarwin_admission_view(detail='summary')`` vs ``detail='full'`` and
     ``moldarwin_revision_compare(detail='summary')`` vs ``detail='full'``.
2. **Low-friction live RSI loop (SND1 -> ALK2 cross-target transfer):**
   - ``ActiveCampaign.evaluate`` with stealth ``post_resolve=make_admission_binding_hook``
     commits ``CampaignStore.observations`` and ``moldarwin-admission-binding/1`` in one step.
   - Publishes a reusable callable method with ``applicable_when`` / ``invalid_when`` and a
     live fine-grained generated skill via ``write_generated_skill`` (zero server restart).
   - Fresh-session recall retrieves both with exact boundaries visible at Tier 1.
3. **Paired Pareto gate & shuffled-signal falsifier control:**
   - Genuine ``independent_validation`` gain (WARRANT + COST) -> ``scoped`` / ``full`` adopt.
   - Same numbers under ``diagnostic`` -> capped at ``diagnostic_only``.
   - Cost saving that regresses ``WARRANT`` -> ``refused``.
   - Shuffled-signal null control (even split across discordant pairs) -> ``refused``
     (``within_noise``, 0 false promotions).

Exit code 0 iff all probes pass.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from moldarwin import skills
from moldarwin.active import CampaignSpec, CampaignStore, Candidate, Endpoint, Evaluation
from moldarwin.active.runner import ActiveCampaign
from moldarwin.boundary.prism_v1 import file_identity
from moldarwin.mcp.server import build
from moldarwin.research import Artifact, ResearchJournal
from moldarwin.research.admission_bindings import (
    make_admission_binding_hook,
)
from moldarwin.research.continuation import CHECKPOINT, STEP, record_content
from moldarwin.research.evidence_refs import make_ref
from moldarwin.research.graph_memory import node_identity
from moldarwin.research.notes import save_progress
from moldarwin.research.resource_catalog import build_resource_catalog
from moldarwin.research.saved_methods import publish_method
from moldarwin.skill_index import find_skills, write_generated_skill


def _call_mcp(server, tool_name: str, arguments: dict) -> dict:
    raw = asyncio.run(server.call_tool(tool_name, arguments))
    blocks = raw[0] if isinstance(raw, tuple) else raw
    return json.loads(blocks[0].text)


def _tool_schema_bytes(server) -> tuple[int, int]:
    listed = asyncio.run(server.list_tools())
    serialized = json.dumps(
        [
            {
                "name": item.name,
                "description": item.description,
                "inputSchema": item.inputSchema,
            }
            for item in listed
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return len(listed), len(serialized.encode("utf-8"))


def run_probes() -> dict:
    with tempfile.TemporaryDirectory(prefix="moldarwin-track2-probe-") as tmp:
        root = Path(tmp).resolve()
        results: list[dict] = []

        # -------------------------------------------------- Probe 1: Token efficiency
        full_server = build(profile="full")
        thin_server = build(profile="thin")
        full_count, full_bytes = _tool_schema_bytes(full_server)
        thin_count, thin_bytes = _tool_schema_bytes(thin_server)
        tool_reduction = 1.0 - (thin_bytes / full_bytes)

        # Build 50 fine-grained generated skills to test O(1) Tier-1 lazy loading at scale.
        gen_dir = root / "generated-skills"
        gen_dir.mkdir()
        for idx in range(49):
            write_generated_skill(
                gen_dir,
                name=f"target-protocol-{idx:02d}",
                description=f"Specialized preparation recipe for target family {idx}.",
                body=f"# Protocol {idx}\n" + ("Detailed protocol notes.\n" * 60),
                domain="docking" if idx % 2 == 0 else "md-fep",
                tags=[f"family-{idx}", "docking" if idx % 2 == 0 else "fep"],
                applicable_when=f"Target belongs to family {idx}.",
                invalid_when=f"Target outside family {idx}.",
                maturity="validated",
            )
        write_generated_skill(
            gen_dir,
            name="snd1-percentile-calibration",
            description="Calibrate target-local Uni-Dock percentile cutoffs using active/inactive controls.",
            body="# SND1 Percentile Calibration\n" + ("Carry code, never -8.0 threshold.\n" * 60),
            domain="screening",
            tags=["snd1", "alk2", "calibration", "percentile", "unidock"],
            applicable_when="Moving a docking cascade to a new target with measured controls.",
            invalid_when="Target lacks verified inactive controls.",
            maturity="validated",
            references={"references/calibration.md": "Control-panel percentile math.\n"},
        )

        # Measure full catalog + 50 skill bodies vs Tier-1 moldarwin_skill_find.
        full_skill_bytes = len(json.dumps(skills.catalog(), ensure_ascii=False).encode("utf-8")) + sum(
            (p / "SKILL.md").stat().st_size for p in gen_dir.iterdir() if p.is_dir()
        )
        tier1 = _call_mcp(
            thin_server,
            "moldarwin_skill_find",
            {
                "query": "alk2 docking percentile calibration",
                "extra_dirs": [str(gen_dir)],
                "limit": 3,
            },
        )
        tier1_bytes = len(json.dumps(tier1, ensure_ascii=False).encode("utf-8"))
        skill_reduction = 1.0 - (tier1_bytes / full_skill_bytes)

        probe1_ok = (
            thin_count == 16
            and tool_reduction >= 0.75
            and tier1["ok"] is True
            and tier1["coverage"]["bodies_read"] == 0
            and tier1["coverage"]["scanned_skills"] >= 50
            and tier1["skills"][0]["slug"] == "snd1-percentile-calibration"
            and skill_reduction >= 0.90
        )
        results.append({
            "probe": "1_token_efficiency",
            "passed": probe1_ok,
            "evidence": "measured_here",
            "mcp_surface": {
                "full_tools": full_count,
                "thin_tools": thin_count,
                "full_schema_bytes": full_bytes,
                "thin_schema_bytes": thin_bytes,
                "byte_reduction_ratio": round(tool_reduction, 4),
            },
            "lazy_skill_index": {
                "scanned_skills": tier1["coverage"]["scanned_skills"],
                "bodies_read": tier1["coverage"]["bodies_read"],
                "all_bodies_plus_catalog_bytes": full_skill_bytes,
                "tier1_response_bytes": tier1_bytes,
                "byte_reduction_ratio": round(skill_reduction, 4),
                "top_hit": tier1["skills"][0]["slug"],
            },
        })

        # -------------------------------------------------- Probe 2: Stealth live RSI loop
        store = CampaignStore(root / "snd1.sqlite")
        store.configure(
            CampaignSpec("dock", 50.0, "wall_second", "snd1-alk2-probe"),
            [
                Endpoint(
                    "dock",
                    "SND1",
                    "docking",
                    "kcal/mol",
                    "unidock/1",
                    1.0,
                    requires_handoff=False,
                    queryable=True,
                    max_replicates=4,
                )
            ],
        )
        store.add_candidates([Candidate("snd1-act-1", "CCO", (1.0, 2.0))])
        journal = ResearchJournal(store)

        def _raw_artifact(filename: str, text: str) -> tuple[str, dict]:
            p = root / filename
            p.write_text(text, encoding="utf-8")
            art = Artifact(
                str(p), **file_identity(p), source_kind="new_execution", role="diagnostic", bindings={}
            )
            rid = journal.record(art)
            return rid, make_ref("science", rid, journal.get(rid))

        measured_id, measured_ref = _raw_artifact("snd1_calibrated.txt", "SND1 calibrated panel ok")
        unbound_id, unbound_ref = _raw_artifact("legacy_cutoff.txt", "Uncalibrated -8.0 transfer")

        decision_id = record_content(
            journal,
            {
                "schema": STEP,
                "task_id": "t-snd1",
                "question": "Adopt calibrated gate?",
                "branch_id": "main",
                "operation": "decision",
                "reason": "Calibrated on SND1 active/inactive controls",
                "input_refs": [measured_ref],
                "output_refs": [],
                "method_refs": [],
                "accounting_refs": [],
                "source_watermarks": [],
                "supersedes": [],
                "detail": {
                    "choice": "proceed",
                    "alternatives": [{"branch_id": "raw", "disposition": "skip", "reason": "0/8 recall"}],
                    "basis_refs": [measured_ref],
                    "reconsider_when": "new controls contradict calibration",
                },
            },
            root / "content",
            source_id="science",
            source_kind="new_execution",
        )
        decision_ref = make_ref("science", decision_id, journal.get(decision_id))
        authority = root / "STATUS.md"
        authority.write_text("Active.", encoding="utf-8")
        cp_id = record_content(
            journal,
            {
                "schema": CHECKPOINT,
                "task_id": "t-snd1",
                "question": "Adopt calibrated gate?",
                "step_refs": [decision_ref],
                "claim_refs": [],
                "counter_refs": [],
                "method_refs": [],
                "pending_handles": [],
                "source_watermarks": [],
                "branches": [
                    {
                        "branch_id": "main",
                        "state": "open",
                        "basis_refs": [decision_ref],
                        "next_read_refs": [unbound_ref],
                        "reconsider_when": "new target",
                    }
                ],
                "supersedes": [],
                "status_guards": [
                    {"location": str(authority), **file_identity(authority), "state": "active"}
                ],
            },
            root / "content",
            source_id="science",
            source_kind="new_execution",
        )
        cp_ref = make_ref("science", cp_id, journal.get(cp_id))

        # Stealth post_resolve automatically emits admission binding at dispatch commit.
        hook = make_admission_binding_hook(
            journal,
            directory=root / "bindings",
            target_resolver=lambda _action, _result: measured_id,
        )
        campaign = ActiveCampaign(
            store,
            executor=lambda _a, c, e, _g: Evaluation(c.id, e.id, -7.78, e.units, 1.0, status="ok"),
            post_resolve=hook,
        )
        campaign.evaluate("snd1-act-1", "dock")

        workspace = root / "workspace.json"
        workspace.write_text(
            json.dumps({
                "schema": "moldarwin-evidence-workspace/1",
                "workspace_id": "probe-ws",
                "sources": [
                    {
                        "source_id": "science",
                        "kind": "journal",
                        "location": str(store.path),
                        "identity": {
                            "kind": "snapshot_sha256",
                            "value": file_identity(store.path)["sha256"],
                        },
                    }
                ],
                "status_refs": [str(authority)],
                "location_map": [],
            }),
            encoding="utf-8",
        )
        scope = {"root_refs": [decision_ref, unbound_ref], "ordinary_hops": 1}

        view_full = _call_mcp(
            thin_server,
            "moldarwin_admission_view",
            {"workspace": str(workspace), "checkpoint_ref": cp_ref, "scope": scope, "detail": "full"},
        )
        view_summary = _call_mcp(
            thin_server,
            "moldarwin_admission_view",
            {"workspace": str(workspace), "checkpoint_ref": cp_ref, "scope": scope, "detail": "summary"},
        )
        full_view_bytes = len(json.dumps(view_full["view"]).encode("utf-8"))
        summary_view_bytes = len(json.dumps(view_summary["summary"]).encode("utf-8"))

        # Capture callable method with reuse boundaries and recall on fresh session (ALK2).
        entry_path = root / "ENTRY.json"
        save_progress(
            journal,
            entry_path,
            {
                "task_id": "t-snd1",
                "branch_id": "main",
                "question": "Reusable gate calibration",
                "summary": "Captured from SND1 panel",
                "conditions": {"engine": "unidock"},
                "evidence": [],
                "counterevidence": [],
                "resources": {},
            },
        )
        script = root / "calibrate.py"
        script.write_text("print('calibrated')\n", encoding="utf-8")
        publish_method(
            entry_path,
            "percentile-gate-calibrator",
            {"command": [sys.executable, str(script)], "files": [str(script)], "method_id": "cal/1", "inputs": {}},
            summary="Percentile cutoff from target-local controls.",
            conditions={"engine": "unidock"},
            applicable_when="New target has verified active and inactive controls.",
            invalid_when=["no_inactive_controls", "transferring_raw_cutoff_without_controls"],
        )
        recalled = build_resource_catalog(entry=entry_path, kinds=["method"])
        method_row = next(r for r in recalled["items"] if r["resource_id"] == "percentile-gate-calibrator")
        live_skill = find_skills(query="snd1 percentile calibration", extra_dirs=[str(gen_dir)], limit=1)["skills"][0]

        probe2_ok = (
            view_summary["ok"] is True
            and view_summary["binding_extraction"]["bound_nodes"] == 1
            and view_summary["summary"]["counts_by_admission"]["admitted"] == 2
            and summary_view_bytes < full_view_bytes
            and method_row["invalid_when"] == ["no_inactive_controls", "transferring_raw_cutoff_without_controls"]
            and live_skill["slug"] == "snd1-percentile-calibration"
        )
        results.append({
            "probe": "2_live_rsi_stealth_bind_and_cross_target_recall",
            "passed": probe2_ok,
            "evidence": "measured_here",
            "stealth_bound_nodes": view_summary["binding_extraction"]["bound_nodes"],
            "admission_view_bytes": {
                "full": full_view_bytes,
                "summary": summary_view_bytes,
                "reduction_ratio": round(1.0 - summary_view_bytes / full_view_bytes, 4),
            },
            "recalled_method_boundaries": method_row["invalid_when"],
            "recalled_live_skill": live_skill["slug"],
        })

        # -------------------------------------------------- Probe 3: Pareto gate & shuffled control
        base_view = view_full["view"]
        unbound_nid = node_identity(unbound_ref)
        decision_nid = node_identity(decision_ref)

        # 3a: Genuine independent_validation gain (8/8 warrant + 40% cost saving).
        tasks_win = {f"m{i}": {"base": unbound_nid, "candidate": decision_nid} for i in range(8)}
        cost_win = {
            "name": "wall_seconds",
            "family": "cost",
            "unit": "s",
            "base": {f"m{i}": 100.0 for i in range(8)},
            "candidate": {f"m{i}": 60.0 for i in range(8)},
        }
        genuine_summary = _call_mcp(
            thin_server,
            "moldarwin_revision_compare",
            {
                "assessment_role": "independent_validation",
                "declared_scope": ["SND1", "ALK2"],
                "measured_scope": ["SND1"],
                "base_view": base_view,
                "candidate_view": base_view,
                "task_nodes": tasks_win,
                "dimensions": [cost_win],
                "detail": "summary",
            },
        )
        genuine_full = _call_mcp(
            thin_server,
            "moldarwin_revision_compare",
            {
                "assessment_role": "independent_validation",
                "declared_scope": ["SND1", "ALK2"],
                "measured_scope": ["SND1"],
                "base_view": base_view,
                "candidate_view": base_view,
                "task_nodes": tasks_win,
                "dimensions": [cost_win],
                "detail": "full",
            },
        )

        # 3b: Same numbers in diagnostic lane -> capped at diagnostic_only.
        diag_cap = _call_mcp(
            thin_server,
            "moldarwin_revision_compare",
            {
                "assessment_role": "diagnostic",
                "declared_scope": ["SND1"],
                "base_view": base_view,
                "candidate_view": base_view,
                "task_nodes": tasks_win,
                "dimensions": [cost_win],
            },
        )

        # 3c: Cost saving that regresses warrant -> refused.
        tasks_regress = {f"m{i}": {"base": decision_nid, "candidate": unbound_nid} for i in range(8)}
        cost_cant_buy = _call_mcp(
            thin_server,
            "moldarwin_revision_compare",
            {
                "assessment_role": "independent_validation",
                "declared_scope": ["SND1"],
                "base_view": base_view,
                "candidate_view": base_view,
                "task_nodes": tasks_regress,
                "dimensions": [cost_win],
            },
        )

        # 3d: Shuffled-signal falsifier control (balanced 6-6 split over 12 tasks -> refused/within_noise).
        tasks_null = {
            f"n{i}": {
                "base": unbound_nid if i < 6 else decision_nid,
                "candidate": decision_nid if i < 6 else unbound_nid,
            }
            for i in range(12)
        }
        shuffled_null = _call_mcp(
            thin_server,
            "moldarwin_revision_compare",
            {
                "assessment_role": "independent_validation",
                "declared_scope": ["SND1"],
                "base_view": base_view,
                "candidate_view": base_view,
                "task_nodes": tasks_null,
            },
        )

        cmp_sum_bytes = len(json.dumps(genuine_summary["comparison"]).encode("utf-8"))
        cmp_full_bytes = len(json.dumps(genuine_full["comparison"]).encode("utf-8"))
        probe3_ok = (
            genuine_summary["comparison"]["adoption"] == "scoped"
            and genuine_summary["comparison"]["gain"] == "both"
            and diag_cap["comparison"]["adoption"] == "diagnostic_only"
            and cost_cant_buy["comparison"]["adoption"] == "refused"
            and shuffled_null["comparison"]["adoption"] == "refused"
            and shuffled_null["comparison"]["dimensions"][0]["verdict"] == "within_noise"
            and cmp_sum_bytes < cmp_full_bytes
        )
        results.append({
            "probe": "3_pareto_rsi_gate_and_shuffled_falsifier",
            "passed": probe3_ok,
            "evidence": "measured_here",
            "genuine_independent": {
                "adoption": genuine_summary["comparison"]["adoption"],
                "gain": genuine_summary["comparison"]["gain"],
                "summary_bytes": cmp_sum_bytes,
                "full_bytes": cmp_full_bytes,
                "reduction_ratio": round(1.0 - cmp_sum_bytes / cmp_full_bytes, 4),
            },
            "diagnostic_capped": diag_cap["comparison"]["adoption"],
            "cost_vs_warrant_regression": cost_cant_buy["comparison"]["adoption"],
            "shuffled_null_control": {
                "adoption": shuffled_null["comparison"]["adoption"],
                "verdict": shuffled_null["comparison"]["dimensions"][0]["verdict"],
            },
        })

        return {
            "passed": all(row["passed"] for row in results),
            "probes": results,
        }


def main() -> int:
    report = run_probes()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["passed"]:
        print(f"\nPASSED: {len(report['probes'])} of {len(report['probes'])} Track 1+2 probes held.")
        return 0
    print("\nFAILED: one or more Track 1+2 probes failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
