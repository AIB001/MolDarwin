"""End-to-end tests for dispatch-time admission bindings and live moldarwin_admission_view."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from moldarwin.active import CampaignSpec, CampaignStore, Candidate, Endpoint, Evaluation
from moldarwin.active.schema import canonical
from moldarwin.active.store import StateError
from moldarwin.faults.attribution import Observation
from moldarwin.judgment.waiver import Waiver, WaiverSet
from moldarwin.learn.admission_view import compare_views
from moldarwin.mcp._common import Cost
from moldarwin.mcp.evidence import register as register_evidence
from moldarwin.mcp.server import tool_catalog
from moldarwin.research import Artifact, ResearchJournal
from moldarwin.research.admission_bindings import (
    SCHEMA,
    build_admission_view,
    record_admission_binding,
)
from moldarwin.research.continuation import CHECKPOINT, STEP, record_content
from moldarwin.research.entry import make_read_context
from moldarwin.research.evidence_refs import EvidenceError, file_identity, make_ref
from moldarwin.research.graph_memory import build_research_graph, node_identity


def _evidence_tools() -> dict:
    tools: dict = {}

    class Collector:
        def tool(self):
            def decorate(fn):
                tools[fn.__name__] = fn
                return fn

            return decorate

    register_evidence(Collector())
    return tools


def _make_campaign_graph(tmp_path: Path) -> dict:
    store = CampaignStore(tmp_path / "campaign.sqlite")
    store.configure(
        CampaignSpec("fep", 100.0, "gpu_hour", "admission-binding-fixture"),
        [
            Endpoint(
                "fep",
                "target-a",
                "fep",
                "kcal/mol",
                "fep/1",
                1.0,
                queryable=True,
                max_replicates=4,
            )
        ],
    )
    store.add_candidates([Candidate("mol-1", "CCO", (1.0, 2.0))])
    journal = ResearchJournal(store)

    def raw(name: str, text: str) -> tuple[str, dict]:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        item = Artifact(
            str(path),
            **file_identity(path),
            source_kind="new_execution",
            role="diagnostic",
            bindings={},
        )
        rid = journal.record(item)
        return rid, make_ref("science", rid, journal.get(rid))

    def save(content: dict) -> tuple[str, dict]:
        rid = record_content(
            journal,
            content,
            tmp_path / "content",
            source_id="science",
            source_kind="new_execution",
        )
        return rid, make_ref("science", rid, journal.get(rid))

    measured_id, measured_ref = raw("measured.txt", "fep output for mol-1")
    unbound_id, unbound_ref = raw("historical.txt", "older historical note with no dispatch ruling")

    decision_step = {
        "schema": STEP,
        "task_id": "t-admission",
        "question": "Does mol-1 merit synthesis?",
        "branch_id": "main",
        "operation": "decision",
        "reason": "Select based on measured FEP output",
        "input_refs": [measured_ref],
        "output_refs": [],
        "method_refs": [],
        "accounting_refs": [],
        "source_watermarks": [],
        "supersedes": [],
        "detail": {
            "choice": "proceed",
            "alternatives": [{"branch_id": "alt", "disposition": "skip", "reason": "higher cost"}],
            "basis_refs": [measured_ref],
            "reconsider_when": "if mol-1 ruling is withheld",
        },
    }
    decision_id, decision_ref = save(decision_step)

    authority = tmp_path / "STATUS.md"
    authority.write_text("Active fixture.", encoding="utf-8")
    checkpoint = {
        "schema": CHECKPOINT,
        "task_id": "t-admission",
        "question": "Does mol-1 merit synthesis?",
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
                "reconsider_when": "new data",
            }
        ],
        "supersedes": [],
        "status_guards": [
            {"location": str(authority), **file_identity(authority), "state": "active"}
        ],
    }
    _, cp_ref = save(checkpoint)

    workspace = tmp_path / "workspace.json"
    entry = tmp_path / "entry.json"

    def publish() -> Path:
        workspace.write_text(
            json.dumps(
                {
                    "schema": "moldarwin-evidence-workspace/1",
                    "workspace_id": "admission-fixture",
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
                }
            ),
            encoding="utf-8",
        )
        entry.write_text(
            json.dumps({"workspace": "workspace.json", "checkpoint_ref": cp_ref}),
            encoding="utf-8",
        )
        return workspace

    publish()
    return {
        "store": store,
        "journal": journal,
        "workspace": workspace,
        "entry": entry,
        "checkpoint": cp_ref,
        "publish": publish,
        "measured_id": measured_id,
        "measured_ref": measured_ref,
        "unbound_id": unbound_id,
        "unbound_ref": unbound_ref,
        "decision_id": decision_id,
        "decision_ref": decision_ref,
        "bindings_dir": tmp_path / "bindings",
    }


def _resolve_action(
    store: CampaignStore,
    *,
    value: float = -9.5,
    checks: tuple[Observation, ...] = (),
    waivers: WaiverSet | None = None,
) -> str:
    round_id = store.start_round({"reason": "fixture"})
    action = store.reserve(round_id, "mol-1", "fep", {"reason": "fixture"})
    store.resolve(
        action.id,
        Evaluation(
            candidate_id="mol-1",
            endpoint_id="fep",
            value=value,
            units="kcal/mol",
            cost=1.0,
            status="ok",
            checks=checks,
        ),
        waivers=waivers,
    )
    store.finish_round(round_id, {"done": True})
    return action.id


def test_dispatch_binding_propagates_through_live_mcp_admission_view(tmp_path):
    case = _make_campaign_graph(tmp_path)
    store, journal = case["store"], case["journal"]
    scope = {"root_refs": [case["decision_ref"], case["unbound_ref"]], "ordinary_hops": 1}

    leaf_before = canonical(journal.get(case["measured_id"]))
    graph_before = build_research_graph(
        case["workspace"], checkpoint_ref=case["checkpoint"], scope=scope
    )

    action_id = _resolve_action(store, value=-9.5)
    recorded = record_admission_binding(
        journal,
        target_record_id=case["measured_id"],
        action_id=action_id,
        claim_scope={"parent_id": "mol-1", "protocol": "fep/1"},
        directory=case["bindings_dir"],
    )
    assert recorded["admission"] == "admitted"
    assert recorded["record_id"].startswith("artifact-")

    # C2: target leaf record is untouched.
    assert canonical(journal.get(case["measured_id"])) == leaf_before

    case["publish"]()
    graph_after = build_research_graph(
        case["workspace"], checkpoint_ref=case["checkpoint"], scope=scope
    )
    # Binding artifacts never pollute the research graph's nodes or edges.
    assert graph_after["nodes"] == graph_before["nodes"]
    assert graph_after["edges"] == graph_before["edges"]

    tools = _evidence_tools()
    response = json.loads(
        tools["moldarwin_admission_view"](
            workspace=str(case["workspace"]),
            checkpoint_ref=case["checkpoint"],
            scope=scope,
        )
    )
    assert response["ok"] is True
    assert response["execution_permission"] == "not_granted"
    assert response["automatic_retry"] is False

    extraction = response["binding_extraction"]
    assert extraction["schema"] == SCHEMA
    assert extraction["binding_records_verified"] == 1
    assert extraction["matched_bindings"] == 1
    assert extraction["unmatched_bindings"] == 0
    assert extraction["bound_nodes"] == 1
    assert extraction["binding_source_mode"] == "recorded_dispatch_bindings"

    view = response["view"]
    assert view["graph_completeness"]["asserted"] is True
    by_id = {node["node_id"]: node for node in view["nodes"]}
    measured_nid = node_identity(case["measured_ref"])
    decision_nid = node_identity(case["decision_ref"])
    unbound_nid = node_identity(case["unbound_ref"])

    assert by_id[measured_nid]["leaf"] == "admitted"
    assert by_id[measured_nid]["admission"] == "admitted"
    assert by_id[measured_nid]["binding"]["dispatch_ref"] == {
        "store": "campaign",
        "action_id": action_id,
    }
    assert by_id[decision_nid]["leaf"] is None
    assert by_id[decision_nid]["admission"] == "admitted"
    assert by_id[decision_nid]["limiting_leaves"] == [measured_nid]

    # C4: historical unbound node stays not_recorded, never backfilled.
    assert by_id[unbound_nid]["leaf"] is None
    assert by_id[unbound_nid]["admission"] == "not_recorded"

    # Entry selector produces the exact same untouched admission view, directly comparable.
    via_entry = json.loads(
        tools["moldarwin_admission_view"](entry=str(case["entry"]), scope=scope)
    )
    assert via_entry["ok"] is True
    diff = compare_views(view, via_entry["view"])
    assert all(not row["admission"]["moved"] for row in diff["nodes"].values())


def test_withheld_binding_blocks_dependent_and_supersedes_preserves_history(tmp_path):
    case = _make_campaign_graph(tmp_path)
    store, journal = case["store"], case["journal"]
    scope = {"root_refs": [case["decision_ref"], case["unbound_ref"]], "ordinary_hops": 1}

    bad_check = (
        Observation(
            "F_HYDROGENS_IMPLICIT",
            fired=True,
            detail="ligand lacked explicit hydrogens",
            evaluable=True,
        ),
    )
    a_withheld = _resolve_action(store, value=-8.2, checks=bad_check)
    first = record_admission_binding(
        journal,
        target_record_id=case["measured_id"],
        action_id=a_withheld,
        claim_scope={"parent_id": "mol-1", "review_stage": "initial-dispatch"},
        directory=case["bindings_dir"],
    )
    assert first["admission"] == "withheld"

    case["publish"]()
    v1 = build_admission_view(
        case["workspace"], checkpoint_ref=case["checkpoint"], scope=scope
    )["view"]
    n1 = {node["node_id"]: node for node in v1["nodes"]}
    measured_nid = node_identity(case["measured_ref"])
    decision_nid = node_identity(case["decision_ref"])
    assert n1[measured_nid]["admission"] == "withheld"
    assert n1[measured_nid]["binding"]["exact_blocking"] == ["F_HYDROGENS_IMPLICIT"]
    assert n1[decision_nid]["admission"] == "withheld"
    assert n1[decision_nid]["limiting_leaves"] == [measured_nid]

    # Second action with an explicit waiver produces admitted_under_waiver.
    waiver = WaiverSet(
        (
            Waiver(
                code="F_HYDROGENS_IMPLICIT",
                reason="reviewed explicit hydrogen protonation externally",
                granted_by="reviewer",
                expires=date(2030, 1, 1),
            ),
        )
    )
    a_waived = _resolve_action(store, value=-8.2, checks=bad_check, waivers=waiver)

    # Attempting to overwrite without supersedes is refused.
    with pytest.raises(StateError, match="supersedes"):
        record_admission_binding(
            journal,
            target_record_id=case["measured_id"],
            action_id=a_waived,
            claim_scope={"parent_id": "mol-1", "review_stage": "waived-review"},
            directory=case["bindings_dir"],
        )

    second = record_admission_binding(
        journal,
        target_record_id=case["measured_id"],
        action_id=a_waived,
        claim_scope={"parent_id": "mol-1", "review_stage": "waived-review"},
        directory=case["bindings_dir"],
        supersedes=first["record_id"],
    )
    assert second["admission"] == "admitted_under_waiver"
    assert second["supersedes_ruling_digest"] == first["ruling_digest"]
    assert second["prior_binding_id"] == first["record_id"]

    # Forking from the already-superseded binding is refused.
    a_clean = _resolve_action(store, value=-9.1)
    with pytest.raises(StateError, match="cannot fork"):
        record_admission_binding(
            journal,
            target_record_id=case["measured_id"],
            action_id=a_clean,
            claim_scope={"parent_id": "mol-1", "review_stage": "fork-attempt"},
            directory=case["bindings_dir"],
            supersedes=first["ruling_digest"],
        )

    case["publish"]()
    v2 = build_admission_view(
        case["workspace"], checkpoint_ref=case["checkpoint"], scope=scope
    )["view"]
    n2 = {node["node_id"]: node for node in v2["nodes"]}
    assert n2[measured_nid]["admission"] == "admitted_under_waiver"
    assert n2[measured_nid]["binding"]["claim_scope"] == {
        "parent_id": "mol-1",
        "review_stage": "waived-review",
    }
    assert n2[measured_nid]["history"] == [
        {
            "admission": "withheld",
            "ruling_digest": first["ruling_digest"],
            "claim_scope": {"parent_id": "mol-1", "review_stage": "initial-dispatch"},
            "superseded_by": second["ruling_digest"],
        }
    ]
    assert n2[measured_nid]["rests_on_superseded_premise"] is True
    assert n2[decision_nid]["admission"] == "admitted_under_waiver"
    assert n2[decision_nid]["rests_on_superseded_premise"] is True


def test_missing_observation_refused_and_tampered_binding_fails_closed(tmp_path):
    case = _make_campaign_graph(tmp_path)
    store, journal = case["store"], case["journal"]
    scope = {"root_refs": [case["decision_ref"]], "ordinary_hops": 1}

    # Uncommitted (nonexistent) action is refused.
    with pytest.raises(StateError, match="committed CampaignStore observation"):
        record_admission_binding(
            journal,
            target_record_id=case["measured_id"],
            action_id="action-never-committed",
            claim_scope={"parent_id": "mol-1"},
            directory=case["bindings_dir"],
        )

    # Reserved but unresolved action is also refused (no Ruling exists yet).
    round_id = store.start_round({"reason": "pending"})
    pending = store.reserve(round_id, "mol-1", "fep", {"reason": "pending"}).id
    with pytest.raises(StateError, match="committed CampaignStore observation"):
        record_admission_binding(
            journal,
            target_record_id=case["measured_id"],
            action_id=pending,
            claim_scope={"parent_id": "mol-1"},
            directory=case["bindings_dir"],
        )

    # Resolve pending action as withheld, bind it, publish, then tamper the binding artifact file.
    store.resolve(
        pending,
        Evaluation(
            candidate_id="mol-1",
            endpoint_id="fep",
            value=-7.0,
            units="kcal/mol",
            cost=1.0,
            status="ok",
            checks=(
                Observation(
                    "F_STRUCTURE_UNREADABLE", fired=True, detail="corrupt", evaluable=True
                ),
            ),
        ),
    )

    # Mismatched claim_scope.parent_id is refused.
    with pytest.raises(ValueError, match="parent_id"):
        record_admission_binding(
            journal,
            target_record_id=case["measured_id"],
            action_id=pending,
            claim_scope={"parent_id": "different-mol"},
            directory=case["bindings_dir"],
        )

    binding_rec = record_admission_binding(
        journal,
        target_record_id=case["measured_id"],
        action_id=pending,
        claim_scope={"parent_id": "mol-1"},
        directory=case["bindings_dir"],
    )
    case["publish"]()

    # Tampering with the withheld binding file must FAIL CLOSED, never silently revert to not_recorded.
    Path(binding_rec["path"]).write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises(EvidenceError, match="unavailable or identity changed"):
        build_admission_view(case["workspace"], checkpoint_ref=case["checkpoint"], scope=scope)


def test_idempotent_retry_read_context_pinning_and_catalog_cost(tmp_path):
    case = _make_campaign_graph(tmp_path)
    store, journal = case["store"], case["journal"]
    scope = {"root_refs": [case["decision_ref"]], "ordinary_hops": 1}

    action_id = _resolve_action(store, value=-9.2)
    first = record_admission_binding(
        journal,
        target_record_id=case["measured_id"],
        action_id=action_id,
        claim_scope={"parent_id": "mol-1"},
        directory=case["bindings_dir"],
    )
    again = record_admission_binding(
        journal,
        target_record_id=case["measured_id"],
        action_id=action_id,
        claim_scope={"parent_id": "mol-1"},
        directory=case["bindings_dir"],
    )
    assert again == first

    case["publish"]()
    ctx = make_read_context(case["workspace"], case["checkpoint"], purpose="research")
    res = build_admission_view(read_context=ctx, scope=scope)
    assert res["binding_extraction"]["bound_nodes"] == 1

    with pytest.raises(EvidenceError, match="read_context already pins purpose"):
        build_admission_view(read_context=ctx, purpose="evaluation", scope=scope)

    catalog = tool_catalog()
    assert catalog["moldarwin_admission_view"]["cost"] == Cost.FREE.value


def test_live_membrane_degrades_diagnostic_evaluation_even_when_dispatch_bound(tmp_path):
    """End-to-end check: a diagnostic MethodEvaluation bound to an admitted ruling still
    degrades relied_on -> used at the assessment-regime membrane in moldarwin_admission_view."""

    from moldarwin.research.schema import MethodEvaluation, MethodVersion, TaskSplit

    store = CampaignStore(tmp_path / "membrane.sqlite")
    store.configure(
        CampaignSpec("fep", 100.0, "gpu_hour", "membrane-fixture"),
        [
            Endpoint(
                "fep",
                "target-a",
                "fep",
                "kcal/mol",
                "fep/1",
                1.0,
                queryable=True,
                max_replicates=4,
            )
        ],
    )
    store.add_candidates([Candidate("mol-m1", "CCO", (1.0,))])
    journal = ResearchJournal(store)

    def raw(name: str, text: str) -> tuple[str, dict]:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        item = Artifact(
            str(path),
            **file_identity(path),
            source_kind="new_execution",
            role="diagnostic",
            bindings={},
        )
        rid = journal.record(item)
        return rid, make_ref("science", rid, journal.get(rid))

    def save(content: dict) -> tuple[str, dict]:
        rid = record_content(
            journal,
            content,
            tmp_path / "content",
            source_id="science",
            source_kind="new_execution",
        )
        return rid, make_ref("science", rid, journal.get(rid))

    measured_id, measured_ref = raw("measured.txt", "measured result")
    proto_id, proto_ref = raw("proto.txt", "protocol")
    init_id, init_ref = raw("init.txt", "initial conditions")

    mv_base = journal.record(
        MethodVersion(
            name="score-base",
            roles=("scoring",),
            content_ref={"artifact_id": proto_id},
        )
    )
    mv_cand = journal.record(
        MethodVersion(
            name="score-cand",
            roles=("scoring",),
            content_ref={"artifact_id": init_id},
        )
    )
    split_id = journal.record(
        TaskSplit(
            development=("t-mem",),
            validation=(),
            transfer=(),
            frozen_initial_configuration={"t-mem": "not-released"},
            independent_objective="kcal/mol",
        )
    )
    diag_eval_id = journal.record(
        MethodEvaluation(
            subjects=(mv_cand,),
            comparators=(mv_base,),
            protocol_ref=proto_id,
            task_split_ref=split_id,
            initial_conditions_ref=init_id,
            result_refs=(measured_id,),
            accounting_refs=(),
            assessment_role="diagnostic",
            assessment_role_basis="explicitly_declared",
            conclusion="diagnostic exploration only",
            scope="fixture",
        )
    )
    diag_eval_ref = make_ref("science", diag_eval_id, journal.get(diag_eval_id))

    decision_id, decision_ref = save(
        {
            "schema": STEP,
            "task_id": "t-mem",
            "question": "Can diagnostic evaluation settle a decision?",
            "branch_id": "main",
            "operation": "decision",
            "reason": "Attempt to rely on diagnostic evaluation",
            "input_refs": [],
            "output_refs": [],
            "method_refs": [],
            "accounting_refs": [],
            "source_watermarks": [],
            "supersedes": [],
            "detail": {
                "choice": "proceed",
                "alternatives": [{"branch_id": "alt", "disposition": "skip", "reason": "none"}],
                "basis_refs": [diag_eval_ref],
                "reconsider_when": "after independent validation",
            },
        }
    )
    authority = tmp_path / "STATUS.md"
    authority.write_text("Active fixture.", encoding="utf-8")
    _, cp_ref = save(
        {
            "schema": CHECKPOINT,
            "task_id": "t-mem",
            "question": "Can diagnostic evaluation settle a decision?",
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
                    "next_read_refs": [],
                    "reconsider_when": "independent validation",
                }
            ],
            "supersedes": [],
            "status_guards": [
                {"location": str(authority), **file_identity(authority), "state": "active"}
            ],
        }
    )

    # Bind a committed admitted ruling to the leaf measured_id; diag_eval derives admitted
    # through its relied_on (measured_result) edge, then the membrane stops propagation to decision.
    round_id = store.start_round({"reason": "membrane"})
    a_meas = store.reserve(round_id, "mol-m1", "fep", {"reason": "m"}).id
    store.resolve(a_meas, Evaluation("mol-m1", "fep", -9.4, "kcal/mol", 1.0, status="ok"))
    store.finish_round(round_id, {"done": True})

    record_admission_binding(
        journal,
        target_record_id=measured_id,
        action_id=a_meas,
        claim_scope={"parent_id": "mol-m1"},
        directory=tmp_path / "bindings",
    )

    workspace = tmp_path / "workspace.json"
    workspace.write_text(
        json.dumps(
            {
                "schema": "moldarwin-evidence-workspace/1",
                "workspace_id": "membrane-ws",
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
            }
        ),
        encoding="utf-8",
    )

    # Include decision + diag_eval + all its linked refs so completeness is asserted.
    all_roots = [
        decision_ref,
        diag_eval_ref,
        measured_ref,
        proto_ref,
        init_ref,
        make_ref("science", mv_base, journal.get(mv_base)),
        make_ref("science", mv_cand, journal.get(mv_cand)),
        make_ref("science", split_id, journal.get(split_id)),
    ]
    tools = _evidence_tools()
    resp = json.loads(
        tools["moldarwin_admission_view"](
            workspace=str(workspace),
            checkpoint_ref=cp_ref,
            scope={"root_refs": all_roots, "ordinary_hops": 1},
        )
    )
    assert resp["ok"] is True
    view = resp["view"]
    assert view["graph_completeness"]["asserted"] is True
    assert view["membrane"]["degraded_edges"] == 1
    assert view["membrane"]["by_class_basis"]["regime_cannot_settle"] == 1

    by_id = {node["node_id"]: node for node in view["nodes"]}
    measured_nid = node_identity(measured_ref)
    diag_nid = node_identity(diag_eval_ref)
    decision_nid = node_identity(decision_ref)

    # measured_id is bound as admitted -> diag_eval derives admitted via measured_result ->
    # decision relying on diag_eval hits the diagnostic membrane and stays not_recorded.
    assert by_id[measured_nid]["leaf"] == "admitted"
    assert by_id[diag_nid]["leaf"] is None
    assert by_id[diag_nid]["admission"] == "admitted"
    assert by_id[diag_nid]["limiting_leaves"] == [measured_nid]
    assert by_id[decision_nid]["premises"] == []
    assert by_id[decision_nid]["regime_refused_premises"] == [diag_nid]
    assert by_id[decision_nid]["admission"] == "not_recorded"
    assert "premise_regime_cannot_carry_reliance" in by_id[decision_nid]["reasons"]
