"""Checks that refuse a change breaking a `CLAUDE.md` hard constraint.

`docs/thin-harness/HARD_CONSTRAINT_ENFORCEMENT.md` is the ledger: it records, per
constraint, what refuses it today and what is still a promise. This file holds the checks
that ledger cites. The reason for having them at all is recorded one scale smaller in
`tests/test_vendoring.py:137-145`: "prose is the part of a provenance chain with no reader
that checks it, so it needs one."

Scope note. A constraint absent from this file is not thereby respected or violated -- it
is unchecked, and the ledger says which. Nothing here reaches a host with shell access;
what these checks buy is that a violation is refused by the suite rather than noticed
later, which is the difference between a stated constraint and an enforced one.
"""
from __future__ import annotations

import json

import pytest


# ============================================================ constraint 1
# "Do not change the semantics of rule(Measurement) -> Ruling. Node-level admission is a
# new read-only derived export view."
#
# The strongest check for this existed only in tools/falsify_optional_guard.py probe C,
# which runs when somebody remembers to run it. A constraint whose check is opt-in is a
# promise with extra steps, so the property is mirrored here where the suite takes it.


def test_c1_a_complete_observation_set_rules_identically_through_the_tool_and_through_rule():
    """The MCP coverage layer may only touch the INCOMPLETE case.

    `moldarwin_rule_admissible` grew a minting/coverage layer. If that layer changed what a
    complete, honest observation set rules, it would have changed `rule`'s semantics by
    way of its caller -- which constraint 1 forbids whether or not `admissible.py` itself
    was edited. Byte identity over `as_dict()` is the form of "unchanged" that leaves no
    room for a field to drift.
    """
    pytest.importorskip("pydantic", reason="the MCP tool surface imports pydantic")

    from moldarwin.faults.attribution import Observation
    from moldarwin.faults.taxonomy import FAULTS
    from moldarwin.learn.admissible import Measurement, rule
    from moldarwin.mcp.governance import register

    tools: dict = {}

    class Collector:
        def tool(self):
            def decorate(function):
                tools[function.__name__] = function
                return function
            return decorate

    register(Collector())

    rows = [{"code": fault.code, "fired": False, "evaluable": True,
             "detail": "checked by the constraint test"} for fault in FAULTS]
    payload = json.dumps([{"parent_id": "complete", "cheap_value": -9.1,
                           "expensive_value": -10.4, "observations": rows}])

    through_tool = json.loads(tools["moldarwin_rule_admissible"](payload))["report"]["rulings"][0]
    direct = rule(Measurement(
        parent_id="complete", cheap_value=-9.1, expensive_value=-10.4,
        observations=tuple(Observation(r["code"], fired=False, detail=r["detail"],
                                       evaluable=True) for r in rows))).as_dict()

    assert json.dumps(through_tool, sort_keys=True) == json.dumps(direct, sort_keys=True), (
        "the Ruling differs between the MCP tool and rule() on a COMPLETE observation set. "
        "Constraint 1 is about the semantics, not about whether learn/admissible.py was "
        "edited: a caller that changes the verdict on a complete set has changed them.\n"
        f"through the tool: {through_tool}\ndirect:           {direct}")


# ============================================================ constraint 6 (second half)
# "Do not merge RuntimeStore / CampaignStore / ResearchJournal."
#
# The constraint reads as three peers to keep apart; the code is not shaped that way.
# ResearchJournal has no store of its own -- it is a prefixed view over a CampaignStore,
# deliberately ("Research belongs to a configured campaign, not a shadow database",
# research/journal.py:22). So "three distinct files" would fail on correct code and "no
# module imports two" fails on three legitimate coordinators. What is checkable is that
# the three remain three distinct types and that the journal stays a view.
#
# RESTATED 2026-11-10. The ledger asked the owner to say what "merge" forbids: one file,
# one type, one record namespace, or one transaction boundary. The answer is the THIRD,
# and it is read off what would actually be lost. Each store IS a set of refusals --
# ResearchJournal refuses to rewrite an identity, CampaignStore refuses a protocol changed
# under an existing id, RuntimeStore has its own -- so merging them means a row can be
# written through the weakest of the three disciplines and read as though it carried the
# strongest. That is the indistinguishable-later harm, stated exactly.
#
# The other three readings are refused for reasons in the code, not preferences:
#   one file        -- already shared, deliberately. metadata holds `research:`, `design:`,
#                      `resource:`, `budget:execution:`, `candidate-handoff:` and more,
#                      written by five modules. Forbidding that forbids the current design.
#   one type        -- what the two tests above pin. A proxy for the harm, not the harm.
#   one transaction -- the journal shares the campaign's connection by design; forbidding a
#                      shared transaction would forbid `ResearchJournal.__init__`.
# So: sharing a file and a transaction is permitted; sharing a key namespace, or writing
# into another owner's namespace, is not.


def test_c6_the_three_stores_remain_three_distinct_types():
    from moldarwin.active.store import CampaignStore
    from moldarwin.research.journal import ResearchJournal
    from moldarwin.runtime.store import RuntimeStore

    three = (RuntimeStore, CampaignStore, ResearchJournal)
    assert len({id(cls) for cls in three}) == 3, "two of the three names now denote one class"
    for cls in three:
        others = [o for o in three if o is not cls]
        for other in others:
            assert not issubclass(cls, other), (
                f"{cls.__name__} became a subclass of {other.__name__}; constraint 6 "
                "forbids merging the three, and a subclass is a merge with a new name")
    assert {cls.__module__ for cls in three} == {
        "moldarwin.runtime.store", "moldarwin.active.store", "moldarwin.research.journal"}, (
        "a store moved module; update the ledger entry for constraint 6 with the new home")


def test_c6_the_research_journal_stays_a_view_over_a_campaign_store():
    """Giving research its own database would be the merge's mirror image: a split.

    Both directions break the recorded design. `ResearchJournal.__init__` takes a
    `CampaignStore` and calls `store.configuration()`, so a journal cannot exist outside a
    configured campaign. If this ever takes a path instead of a store, the comment at
    research/journal.py:22 and this check disagree, and the ledger entry for constraint 6
    is what needs revisiting -- not this assertion.
    """
    import inspect

    from moldarwin.active.store import CampaignStore
    from moldarwin.research.journal import ResearchJournal

    signature = inspect.signature(ResearchJournal.__init__)
    assert "store" in signature.parameters, (
        "ResearchJournal no longer takes a store; if it now opens its own connection, "
        "research has acquired the shadow database journal.py:22 refuses")
    annotation = signature.parameters["store"].annotation
    assert annotation in (CampaignStore, "CampaignStore"), (
        f"ResearchJournal's store parameter is annotated {annotation!r}; the recorded "
        "design is that research rows live in a configured campaign's store")


def _configured(tmp_path):
    """A configured campaign and a journal over it, which is the only legal pairing."""

    from moldarwin.active.schema import CampaignSpec, Endpoint
    from moldarwin.active.store import CampaignStore
    from moldarwin.research.journal import ResearchJournal

    store = CampaignStore(tmp_path / "campaign.sqlite")
    store.configure(CampaignSpec("c6", 0, "wall_second", "c6-fixture"),
                    [Endpoint("c6", "fixture", "unmeasured", "count", "fixture/1", 0,
                              queryable=False)])
    return store, ResearchJournal(store)


def _metadata_keys(store):
    with store.connection() as db:
        return {row[0] for row in db.execute("SELECT key FROM metadata")}


def test_c6_the_research_journal_writes_only_inside_its_own_key_namespace(tmp_path):
    """The restated constraint, measured on a real store rather than read off the source.

    Measured and not inferred because the namespace is a runtime property of what gets
    written: a source scan over twelve `INSERT INTO metadata` sites would have to guess each
    key expression, and the thing that matters is the keys that actually land.
    """

    from moldarwin.boundary.prism_v1 import file_identity
    from moldarwin.research.journal import PREFIX
    from moldarwin.research.schema import Artifact

    store, journal = _configured(tmp_path)
    campaign_keys = _metadata_keys(store)
    assert campaign_keys, "the fixture must write something, or this check is vacuous"
    assert not {k for k in campaign_keys if k.startswith(PREFIX)}, (
        "a campaign write landed in the research namespace before any research happened: "
        f"{sorted(k for k in campaign_keys if k.startswith(PREFIX))}")

    evidence = tmp_path / "input.txt"
    evidence.write_text("c6 fixture evidence")
    journal.record(Artifact(str(evidence), **file_identity(evidence), source_kind="fixture",
                            role="diagnostic", bindings={}))

    written = _metadata_keys(store) - campaign_keys
    assert written, "the journal wrote nothing, so this check would pass on a broken journal"
    outside = sorted(k for k in written if not k.startswith(PREFIX))
    assert not outside, (
        f"ResearchJournal wrote {outside} outside {PREFIX!r}. Constraint 6 forbids merging "
        "the stores' record namespaces: a row written outside this prefix is a row another "
        "owner's discipline governs, and afterwards nobody can tell which rules it passed")


def test_c6_the_namespaces_the_shared_table_carries_are_pairwise_disjoint():
    """One file is permitted; one namespace is not. This is where that line sits.

    `data/design.py` defines its own `PREFIX` and writes into the same `metadata` table. If
    either prefix were ever changed to the other's value, the two owners' rows would share a
    key space and the weaker discipline would govern both, with no error anywhere.
    """

    from moldarwin.data.design import PREFIX as design_prefix
    from moldarwin.research.journal import PREFIX as research_prefix

    prefixes = {"research/journal.py": research_prefix, "data/design.py": design_prefix}
    for owner, prefix in prefixes.items():
        assert prefix and prefix.endswith(":"), f"{owner}'s namespace prefix is not a prefix"
    for owner, prefix in prefixes.items():
        for other_owner, other in prefixes.items():
            if owner == other_owner:
                continue
            assert not prefix.startswith(other) and not other.startswith(prefix), (
                f"{owner}'s namespace {prefix!r} and {other_owner}'s {other!r} are not "
                "disjoint; one owner's rows are now reachable as the other's")


def test_c6_a_recorded_research_identity_still_cannot_be_rewritten(tmp_path):
    """The write discipline half: a namespace without its rules is just a string prefix.

    `ResearchJournal._put` refuses a second, different body under an identity already
    recorded. That refusal is what the namespace protects; a merge that kept the prefix and
    lost the refusal would pass the two checks above and break the constraint.
    """

    from moldarwin.active.store import StateError

    store, journal = _configured(tmp_path)
    with store.connection() as db:
        journal._put(db, "c6-identity", {"schema": "fixture/1", "value": 1})
        journal._put(db, "c6-identity", {"schema": "fixture/1", "value": 1})  # identical: fine
        with pytest.raises(StateError, match="identity cannot be rewritten"):
            journal._put(db, "c6-identity", {"schema": "fixture/1", "value": 2})


# ============================================================ constraint 2
# "The export view never writes back to leaf records."
#
# The ledger ranked this second by payoff over cost, and named why the remaining half is the
# one that matters: a derived view that edits its own inputs cannot be re-derived, so the
# view stops being a view. `test_admission_view.py::test_membrane_is_read_only_and_the_graph
# _is_unchanged` pins the input *graph*; nothing pinned the leaf *records* or the bindings
# that carry their admissions, which are the inputs the propagation actually reads.


def _leaf_inputs():
    """The smallest shape the constraint is about, built by the real fixture helpers.

    Imported from `test_admission_view` rather than hand-rolled: a graph literal written here
    would be this file's idea of a projection, and the first time `graph_memory` changed its
    shape the check would be pinning something the view never sees.
    """

    from test_admission_view import binding, make_graph

    graph = make_graph(["derived-1", "leaf-1"],
                       [("derived-1", "leaf-1", "depends_on", "measured_result")])
    return graph, [binding("leaf-1", "admitted")]


def test_c2_taking_the_view_leaves_the_leaf_records_and_their_bindings_byte_identical():
    """Deep equality over every input, before and after, including the nested dicts.

    Deep rather than `is`-identity because the failure this refuses is an in-place edit of a
    nested mapping, which leaves every top-level object the same object. Canonical bytes
    beside `==`, so a key whose order changed is caught too: the view's identity is a digest,
    and a reordered input would re-derive differently while still comparing equal.
    """

    import copy

    from moldarwin.active.schema import canonical
    from moldarwin.learn.admission_view import admission_view

    graph, bindings = _leaf_inputs()
    pinned_graph, pinned_bindings = copy.deepcopy(graph), copy.deepcopy(bindings)
    pinned_bytes = canonical({"graph": graph, "bindings": bindings})

    view = admission_view(graph, bindings)
    assert view["nodes"], "the fixture must produce a view, or this check is vacuous"

    assert graph == pinned_graph, "the view edited the graph it was given"
    assert bindings == pinned_bindings, (
        "the view edited the leaf bindings it was given. Constraint 2 forbids writing back to "
        "leaf records: an export view that edits its own inputs cannot be re-derived, so a "
        "later reader cannot tell a derived value from a recorded one")
    assert canonical({"graph": graph, "bindings": bindings}) == pinned_bytes


def test_c2_taking_the_view_twice_over_the_same_inputs_derives_the_same_view_id():
    """The constraint held by its consequence, which is the stronger form.

    If the first derivation wrote anything back, the second would read different inputs and
    `view_id` -- a digest over the view's own content -- would move. So this fails for any
    write-back, including one this file did not think to pin.
    """

    from moldarwin.learn.admission_view import admission_view

    graph, bindings = _leaf_inputs()
    first = admission_view(graph, bindings)
    second = admission_view(graph, bindings)
    assert first["view_id"] == second["view_id"]
    assert first == second


# ============================================================ constraint 3
# "An admission state change keeps the old value and claim scope, per `supersedes`,
# without erasing."
#
# Refusals for malformed `supersedes` (dangling, cyclic, multi-parent) already live in
# `tests/test_admission_view.py`. What was missing was the positive clause: an actual state
# change must keep both the prior admission and the prior claim scope readable in the
# journal AND in the derived view, while refusing an unchained overwrite.


def test_c3_supersedes_preserves_old_admission_and_claim_scope_in_derived_view():
    """Positive check over `admission_view`: old admission and old claim_scope survive."""

    from test_admission_view import binding, make_graph, nid

    from moldarwin.learn.admission_view import admission_view

    graph = make_graph(
        ["decision-1", "leaf-1"],
        [("decision-1", "leaf-1", "depends_on", "measured_result")],
    )
    old_scope = {"parent_id": "leaf-1", "protocol": "initial-run", "temperature_k": 300}
    new_scope = {"parent_id": "leaf-1", "protocol": "waived-review", "temperature_k": 300}

    first = binding("leaf-1", "withheld", action="act-1", scope=old_scope)
    second = binding(
        "leaf-1",
        "admitted_under_waiver",
        action="act-2",
        scope=new_scope,
        supersedes=first["ruling_digest"],
    )

    view = admission_view(graph, [first, second])
    by_id = {node["node_id"]: node for node in view["nodes"]}
    leaf_row = by_id[nid("leaf-1")]
    decision_row = by_id[nid("decision-1")]

    assert leaf_row["admission"] == "admitted_under_waiver"
    assert leaf_row["binding"]["claim_scope"] == new_scope
    assert leaf_row["history"] == [
        {
            "admission": "withheld",
            "ruling_digest": first["ruling_digest"],
            "claim_scope": old_scope,
            "superseded_by": second["ruling_digest"],
        }
    ]
    assert leaf_row["rests_on_superseded_premise"] is True
    assert decision_row["rests_on_superseded_premise"] is True


def test_c3_recorded_admission_state_change_keeps_old_artifact_and_claim_scope_readable(tmp_path):
    """End-to-end persistence check: `supersedes` preserves the old artifact and scope on disk."""

    from datetime import date
    from pathlib import Path

    from moldarwin.active import CampaignSpec, CampaignStore, Candidate, Endpoint, Evaluation
    from moldarwin.active.store import StateError
    from moldarwin.boundary.prism_v1 import file_identity
    from moldarwin.faults.attribution import Observation
    from moldarwin.judgment.waiver import Waiver, WaiverSet
    from moldarwin.research.admission_bindings import record_admission_binding
    from moldarwin.research.journal import ResearchJournal
    from moldarwin.research.schema import Artifact

    store = CampaignStore(tmp_path / "c3.sqlite")
    store.configure(
        CampaignSpec("fep", 10.0, "gpu_hour", "c3-fixture"),
        [
            Endpoint(
                "fep",
                "target",
                "fep",
                "kcal/mol",
                "fep/1",
                1.0,
                queryable=True,
                max_replicates=3,
            )
        ],
    )
    store.add_candidates([Candidate("mol-c3", "CCO", (1.0,))])
    journal = ResearchJournal(store)

    leaf_path = tmp_path / "leaf.txt"
    leaf_path.write_text("c3 leaf evidence", encoding="utf-8")
    leaf_id = journal.record(
        Artifact(
            str(leaf_path),
            **file_identity(leaf_path),
            source_kind="new_execution",
            role="diagnostic",
            bindings={},
        )
    )

    bad_check = (
        Observation("F_HYDROGENS_IMPLICIT", fired=True, detail="implicit H", evaluable=True),
    )
    r1 = store.start_round({"reason": "initial"})
    a1 = store.reserve(r1, "mol-c3", "fep", {"reason": "initial"}).id
    store.resolve(
        a1,
        Evaluation("mol-c3", "fep", -8.0, "kcal/mol", 1.0, status="ok", checks=bad_check),
    )
    store.finish_round(r1, {"done": True})
    old_scope = {"parent_id": "mol-c3", "stage": "initial-ruling"}
    b1 = record_admission_binding(
        journal,
        target_record_id=leaf_id,
        action_id=a1,
        claim_scope=old_scope,
        directory=tmp_path / "bindings",
    )

    r2 = store.start_round({"reason": "waived"})
    a2 = store.reserve(r2, "mol-c3", "fep", {"reason": "waived"}).id
    waiver = WaiverSet(
        (
            Waiver(
                "F_HYDROGENS_IMPLICIT",
                "reviewed explicit hydrogen protonation externally",
                "reviewer",
                date(2030, 1, 1),
            ),
        )
    )
    store.resolve(
        a2,
        Evaluation("mol-c3", "fep", -8.0, "kcal/mol", 1.0, status="ok", checks=bad_check),
        waivers=waiver,
    )
    store.finish_round(r2, {"done": True})
    new_scope = {"parent_id": "mol-c3", "stage": "waived-ruling"}

    # Unchained overwrite is refused.
    with pytest.raises(StateError, match="supersedes"):
        record_admission_binding(
            journal,
            target_record_id=leaf_id,
            action_id=a2,
            claim_scope=new_scope,
            directory=tmp_path / "bindings",
        )

    b2 = record_admission_binding(
        journal,
        target_record_id=leaf_id,
        action_id=a2,
        claim_scope=new_scope,
        directory=tmp_path / "bindings",
        supersedes=b1["record_id"],
    )

    # Prior binding artifact and payload remain permanently readable and un-erased.
    old_record = journal.get(b1["record_id"])
    old_payload = json.loads(Path(old_record["path"]).read_text(encoding="utf-8"))
    new_record = journal.get(b2["record_id"])
    assert old_payload["ruling"]["admission"] == "withheld"
    assert old_payload["claim_scope"] == old_scope
    assert b1["record_id"] in new_record["parents"]


# ============================================================ constraint 4
# "`admission` is written at dispatch, never backfilled."
#
# The regime-unknown half is held by I20 in `test_admission_view.py`. The check below pins
# the direct dispatch-join contract: a record carries no admission until a committed
# `CampaignStore.observations` row exists, uncommitted/unknown dispatches are refused, and
# deriving a view over historical unbound nodes leaves them `not_recorded` without writing
# back to the store.


def test_c4_admission_requires_committed_dispatch_and_unbound_records_are_never_backfilled(
    tmp_path,
):
    from moldarwin.active import CampaignSpec, CampaignStore, Candidate, Endpoint
    from moldarwin.active.store import StateError
    from moldarwin.boundary.prism_v1 import file_identity
    from moldarwin.research.admission_bindings import (
        build_admission_view,
        record_admission_binding,
    )
    from moldarwin.research.continuation import CHECKPOINT, STEP, record_content
    from moldarwin.research.evidence_refs import make_ref
    from moldarwin.research.graph_memory import node_identity
    from moldarwin.research.journal import ResearchJournal
    from moldarwin.research.schema import Artifact

    store = CampaignStore(tmp_path / "c4.sqlite")
    store.configure(
        CampaignSpec("fep", 10.0, "gpu_hour", "c4-fixture"),
        [Endpoint("fep", "target", "fep", "kcal/mol", "fep/1", 1.0, queryable=True)],
    )
    store.add_candidates([Candidate("mol-c4", "CCO", (1.0,))])
    journal = ResearchJournal(store)

    leaf_path = tmp_path / "historical_leaf.txt"
    leaf_path.write_text("recorded before any dispatch ruling", encoding="utf-8")
    leaf_id = journal.record(
        Artifact(
            str(leaf_path),
            **file_identity(leaf_path),
            source_kind="fixture",
            role="diagnostic",
            bindings={},
        )
    )
    leaf_ref = make_ref("science", leaf_id, journal.get(leaf_id))

    # Unknown action_id and reserved-but-unresolved action_id are both refused.
    with pytest.raises(StateError, match="committed CampaignStore observation"):
        record_admission_binding(
            journal,
            target_record_id=leaf_id,
            action_id="missing-action",
            claim_scope={"parent_id": "mol-c4"},
            directory=tmp_path / "bindings",
        )

    r_pending = store.start_round({"reason": "not yet resolved"})
    pending_id = store.reserve(r_pending, "mol-c4", "fep", {"reason": "not yet resolved"}).id
    with pytest.raises(StateError, match="committed CampaignStore observation"):
        record_admission_binding(
            journal,
            target_record_id=leaf_id,
            action_id=pending_id,
            claim_scope={"parent_id": "mol-c4"},
            directory=tmp_path / "bindings",
        )

    # Publish a workspace containing the unbound historical leaf and derive an admission view.
    step_id = record_content(
        journal,
        {
            "schema": STEP,
            "task_id": "t-c4",
            "question": "Is historical leaf backfilled?",
            "branch_id": "main",
            "operation": "decision",
            "reason": "Inspect historical leaf without dispatch ruling",
            "input_refs": [leaf_ref],
            "output_refs": [],
            "method_refs": [],
            "accounting_refs": [],
            "source_watermarks": [],
            "supersedes": [],
            "detail": {
                "choice": "defer",
                "alternatives": [{"branch_id": "alt", "disposition": "skip", "reason": "none"}],
                "basis_refs": [leaf_ref],
                "reconsider_when": "after dispatch commits",
            },
        },
        tmp_path / "content",
        source_id="science",
        source_kind="fixture",
    )
    step_ref = make_ref("science", step_id, journal.get(step_id))
    authority = tmp_path / "STATUS.md"
    authority.write_text("Active fixture.", encoding="utf-8")
    cp_id = record_content(
        journal,
        {
            "schema": CHECKPOINT,
            "task_id": "t-c4",
            "question": "Is historical leaf backfilled?",
            "step_refs": [step_ref],
            "claim_refs": [],
            "counter_refs": [],
            "method_refs": [],
            "pending_handles": [],
            "source_watermarks": [],
            "branches": [
                {
                    "branch_id": "main",
                    "state": "open",
                    "basis_refs": [step_ref],
                    "next_read_refs": [],
                    "reconsider_when": "new dispatch",
                }
            ],
            "supersedes": [],
            "status_guards": [
                {"location": str(authority), **file_identity(authority), "state": "active"}
            ],
        },
        tmp_path / "content",
        source_id="science",
        source_kind="fixture",
    )
    cp_ref = make_ref("science", cp_id, journal.get(cp_id))
    workspace = tmp_path / "workspace.json"
    store_before = file_identity(store.path)
    workspace.write_text(
        json.dumps(
            {
                "schema": "moldarwin-evidence-workspace/1",
                "workspace_id": "c4-ws",
                "sources": [
                    {
                        "source_id": "science",
                        "kind": "journal",
                        "location": str(store.path),
                        "identity": {"kind": "snapshot_sha256", "value": store_before["sha256"]},
                    }
                ],
                "status_refs": [str(authority)],
                "location_map": [],
            }
        ),
        encoding="utf-8",
    )

    result = build_admission_view(
        workspace,
        checkpoint_ref=cp_ref,
        scope={"root_refs": [leaf_ref], "ordinary_hops": 0},
    )
    by_id = {node["node_id"]: node for node in result["view"]["nodes"]}
    assert by_id[node_identity(leaf_ref)]["leaf"] is None
    assert by_id[node_identity(leaf_ref)]["admission"] == "not_recorded"
    assert result["binding_extraction"]["bound_nodes"] == 0
    assert file_identity(store.path) == store_before
