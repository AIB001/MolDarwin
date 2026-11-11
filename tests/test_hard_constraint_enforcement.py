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

    `etalon_rule_admissible` grew a minting/coverage layer. If that layer changed what a
    complete, honest observation set rules, it would have changed `rule`'s semantics by
    way of its caller -- which constraint 1 forbids whether or not `admissible.py` itself
    was edited. Byte identity over `as_dict()` is the form of "unchanged" that leaves no
    room for a field to drift.
    """
    pytest.importorskip("pydantic", reason="the MCP tool surface imports pydantic")

    from etalon.faults.attribution import Observation
    from etalon.faults.taxonomy import FAULTS
    from etalon.learn.admissible import Measurement, rule
    from etalon.mcp.governance import register

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

    through_tool = json.loads(tools["etalon_rule_admissible"](payload))["report"]["rulings"][0]
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
    from etalon.active.store import CampaignStore
    from etalon.research.journal import ResearchJournal
    from etalon.runtime.store import RuntimeStore

    three = (RuntimeStore, CampaignStore, ResearchJournal)
    assert len({id(cls) for cls in three}) == 3, "two of the three names now denote one class"
    for cls in three:
        others = [o for o in three if o is not cls]
        for other in others:
            assert not issubclass(cls, other), (
                f"{cls.__name__} became a subclass of {other.__name__}; constraint 6 "
                "forbids merging the three, and a subclass is a merge with a new name")
    assert {cls.__module__ for cls in three} == {
        "etalon.runtime.store", "etalon.active.store", "etalon.research.journal"}, (
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

    from etalon.active.store import CampaignStore
    from etalon.research.journal import ResearchJournal

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

    from etalon.active.schema import CampaignSpec, Endpoint
    from etalon.active.store import CampaignStore
    from etalon.research.journal import ResearchJournal

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

    from etalon.boundary.prism_v1 import file_identity
    from etalon.research.journal import PREFIX
    from etalon.research.schema import Artifact

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

    from etalon.data.design import PREFIX as design_prefix
    from etalon.research.journal import PREFIX as research_prefix

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

    from etalon.active.store import StateError

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

    from etalon.active.schema import canonical
    from etalon.learn.admission_view import admission_view

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

    from etalon.learn.admission_view import admission_view

    graph, bindings = _leaf_inputs()
    first = admission_view(graph, bindings)
    second = admission_view(graph, bindings)
    assert first["view_id"] == second["view_id"]
    assert first == second
