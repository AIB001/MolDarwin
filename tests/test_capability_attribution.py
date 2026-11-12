"""A record says which capability produced it, or says it was not recorded.

The gap this closes was measured on the real journals (2xpro6000, 2026-11-10, read-only):
1565 research records, no MCP tool name anywhere, no tool-identifying key on any event
body. `source_kind` is not an answer -- 1231 of 1231 real records carry `new_execution` and
1231 of 1231 carry `role: diagnostic`, so both fields are constants, and `rows.py:156`
already depends on `source_kind`'s own meaning.
"""
from __future__ import annotations

import pytest

from etalon.research.capability_attribution import (
    KEY,
    NOT_RECORDED,
    attribution,
    census,
    read_attribution,
    with_attribution,
)


def test_a_caller_that_does_not_say_gets_not_recorded_rather_than_a_guess():
    """Constraint 7: a quantity that cannot be obtained is reported as not obtained."""

    for absent in (None, "", "   "):
        block = attribution(absent)
        assert block == {"capability": NOT_RECORDED, "basis": NOT_RECORDED}


def test_a_named_capability_records_its_name_and_basis():
    block = attribution("etalon_method_criterion", version="etalon-capability-version/1")
    assert block["capability"] == "etalon_method_criterion"
    assert block["basis"] == "declared"
    assert block["version"] == "etalon-capability-version/1"


def test_a_version_is_omitted_rather_than_invented():
    assert "version" not in attribution("etalon_evidence_query")


def test_a_named_capability_cannot_claim_it_was_not_recorded():
    with pytest.raises(ValueError):
        attribution("etalon_method_criterion", basis=NOT_RECORDED)
    with pytest.raises(ValueError):
        attribution("etalon_method_criterion", basis="guessed")


def test_the_first_writer_keeps_the_attribution():
    """A later layer overwriting it would record its own name for someone else's work."""

    first = with_attribution({"kind": "evidence"}, "etalon_sweep_emit")
    second = with_attribution(first, "etalon_workflow_advance")
    assert second[KEY]["capability"] == "etalon_sweep_emit"
    assert second["kind"] == "evidence", "the rest of the bindings must be untouched"


def test_reading_a_record_that_predates_attribution_never_raises():
    """Every one of the 1565 real records is this shape."""

    for record in ({}, {"bindings": {}}, {"bindings": None},
                   {"bindings": {"kind": "poses"}}, {"bindings": {KEY: "not a dict"}},
                   {"bindings": {KEY: {"basis": "declared"}}}):
        assert read_attribution(record)["capability"] == NOT_RECORDED


def test_the_census_shows_the_unattributed_rather_than_dropping_them():
    """A rate over only the attributed records would read as coverage it does not have."""

    records = [
        {"bindings": with_attribution(None, "etalon_method_criterion")},
        {"bindings": with_attribution(None, "etalon_method_criterion")},
        {"bindings": with_attribution(None, "etalon_evidence_query")},
        {"bindings": {"kind": "poses"}},
        {},
    ]
    out = census(records)
    assert (out["records"], out["attributed"], out["not_recorded"]) == (5, 3, 2)
    assert list(out["by_capability"]) == ["etalon_method_criterion", NOT_RECORDED,
                                          "etalon_evidence_query"]
    assert "does_not_establish" in out


def test_the_census_over_the_real_record_shape_reports_zero_attributed():
    """The measurement that motivated the module, reproduced on its shape.

    Every real record carries `source_kind: new_execution` and `role: diagnostic` and no
    attribution, so the census must report 0 attributed over a real denominator -- not an
    empty result, which would read as "nothing to see".
    """

    real = [{"bindings": {"kind": "evidence"}, "source_kind": "new_execution",
             "role": "diagnostic"} for _ in range(1231)]
    out = census(real)
    assert (out["records"], out["attributed"], out["not_recorded"]) == (1231, 0, 1231)
    assert out["by_capability"] == {NOT_RECORDED: 1231}


def test_source_kind_is_not_repurposed_as_attribution():
    """Its vocabulary answers a different question and `rows.py` depends on that reading."""

    from etalon.research.schema import Artifact

    record = {"source_kind": "new_execution", "bindings": {}}
    assert read_attribution(record)["capability"] == NOT_RECORDED, (
        "source_kind must never be read as attribution: it says whether bytes were produced "
        "or staged, not which capability produced them")
    assert "source_kind" in {f.name for f in __import__("dataclasses").fields(Artifact)}


def test_record_json_accepts_the_capability_and_leaves_the_artifact_format_alone():
    """`record_json` carries the *declared* name. It is not where the guarantee lives.

    This docstring previously read "wired at `record_json`, which every artifact write
    funnels through". That was false, and the census says by how much: 40 calls reach
    `ResearchJournal.record` and exactly one of them is `record_json`. Every other write
    site builds its own `Record`, so under the old wiring 27 bindings-bearing sites
    produced records the verb census could not attribute. The guarantee now lives at
    `ResearchJournal.record` and is held by
    `test_a_bindings_bearing_record_cannot_reach_the_journal_unattributed`; what stays here
    is the ability to declare something more specific than the dispatched verb.
    """

    import inspect

    from etalon.research.components import record_json

    parameters = inspect.signature(record_json).parameters
    for name in ("capability", "capability_basis", "capability_version"):
        assert name in parameters, f"record_json lost its {name} parameter"
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["capability"].default is None, "attribution must be declared, not defaulted"


# -- the dispatch layer names the verb ----------------------------------------------------------


def test_the_running_capability_is_empty_outside_any_dispatched_call():
    """`None`, never a guess. Direct library use genuinely has no verb to name."""

    from etalon.research.capability_attribution import current_capability

    assert current_capability() is None


def test_a_nested_call_restores_the_outer_verb_rather_than_leaking_its_own():
    """One tool calling through another must not rename the outer tool's later records."""

    from etalon.research.capability_attribution import current_capability, running_capability

    with running_capability("etalon_outer"):
        assert current_capability() == "etalon_outer"
        with running_capability("etalon_inner"):
            assert current_capability() == "etalon_inner"
        assert current_capability() == "etalon_outer"
    assert current_capability() is None


def test_a_running_capability_must_be_a_short_nonempty_name():
    from etalon.research.capability_attribution import running_capability

    for bad in ("", "   ", "x" * 201, 7):
        with pytest.raises(ValueError):
            with running_capability(bad):
                pass
    with running_capability(None):
        pass  # accepted, records nothing, so a caller need not branch


def test_the_mcp_tool_wrapper_names_the_verb_it_is_executing():
    """The whole point of landing this at the wrapper: 89 verbs, one change.

    `mcp/_common.py::tool` decorates every registered tool and already holds
    `function.__name__`, so the dispatch layer is the one place that knows the capability
    without being told. Attributing from there is not an inference, which is why `mcp_tool`
    was already in `BASES` before anything set it.
    """

    from etalon.mcp._common import Cost, tool
    from etalon.research.capability_attribution import current_capability

    @tool(Cost.FREE)
    def etalon_probe_verb() -> str:
        return current_capability() or "none"

    assert etalon_probe_verb() == "etalon_probe_verb"
    assert current_capability() is None, "the wrapper must not leak past its own call"


def test_a_record_written_inside_a_verb_carries_that_verb_with_basis_mcp_tool(tmp_path):
    """End to end through `record_json`, the write every artifact funnels through.

    Exercised against a real journal rather than a mirrored branch: a copy of the three
    attribution lines would keep passing after the product stopped attributing anything.
    """

    from etalon.active.schema import CampaignSpec, Endpoint
    from etalon.active.store import CampaignStore
    from etalon.research.capability_attribution import (
        MCP_TOOL, read_attribution, running_capability)
    from etalon.research.components import record_json
    from etalon.research.journal import ResearchJournal

    store = CampaignStore(tmp_path / "research.sqlite")
    store.configure(CampaignSpec("attribution", 0, "wall_second", "attribution-fixture"),
                    [Endpoint("attribution", "fixture", "unmeasured", "count", "fixture/1", 0,
                              queryable=False)])
    journal = ResearchJournal(store)

    def written(payload, **kwargs):
        rid = record_json(journal, payload, tmp_path / "records", source_kind="fixture", **kwargs)
        return read_attribution(journal.get(rid))

    with running_capability("etalon_method_criterion"):
        implicit = written({"n": 1})
        explicit = written({"n": 2}, capability="etalon-step-corpus")
    outside = written({"n": 3})

    assert implicit == {"capability": "etalon_method_criterion", "basis": MCP_TOOL}
    # An explicit name outranks the verb: it is the more specific claim, because the verb is
    # only the entry point to whatever skill or executor actually ran.
    assert explicit == {"capability": "etalon-step-corpus", "basis": "declared"}
    assert outside == {"capability": NOT_RECORDED, "basis": NOT_RECORDED}


def test_the_census_separates_a_declared_name_from_a_dispatched_verb():
    """Two bases are not interchangeable evidence for a routing decision."""

    from etalon.research.capability_attribution import MCP_TOOL

    records = [
        {"bindings": {KEY: attribution("etalon_method_criterion", basis=MCP_TOOL)}},
        {"bindings": {KEY: attribution("etalon-step-corpus")}},
        {},
    ]
    out = census(records)
    assert out["by_basis"] == {MCP_TOOL: 1, "declared": 1, NOT_RECORDED: 1}
    assert (out["records"], out["attributed"], out["not_recorded"]) == (3, 2, 1)
    assert "Never inferred" in out["basis"]


def test_the_running_verb_is_read_where_bindings_are_assembled_not_per_write_site():
    """Where the consultation lives, and why it moved there.

    It was in `components.record_json` first. `tests/test_reserved_bindings.py` then called
    `with_attribution` directly inside a running verb and got `not_recorded`, which showed
    the branch was per-write-site rather than per-concept: every other caller assembling
    bindings would have had to copy the same three lines. That is the debt pattern this round
    named -- a feature enumerating its subjects instead of reading a property they already
    have -- so the read moved into `with_attribution`, and the write seam holds no branch.
    """

    import inspect

    from etalon.research.capability_attribution import (
        MCP_TOOL, current_capability, running_capability, with_attribution)
    from etalon.research.components import record_json

    with running_capability("etalon_probe_verb"):
        assert current_capability() == "etalon_probe_verb"
        assert with_attribution(None)[KEY] == {
            "capability": "etalon_probe_verb", "basis": MCP_TOOL}
        # An explicit name is the more specific claim and still outranks the verb.
        assert with_attribution(None, "etalon-step-corpus")[KEY]["basis"] == "declared"
    assert with_attribution(None)[KEY]["capability"] == NOT_RECORDED

    assert "current_capability" not in inspect.getsource(record_json), (
        "the write seam grew its own copy of the consultation again"
    )


# -- the seam: every Record lands at ResearchJournal.record --------------------------------------


def _journal(tmp_path):
    from etalon.active.schema import CampaignSpec, Endpoint
    from etalon.active.store import CampaignStore
    from etalon.research.journal import ResearchJournal

    store = CampaignStore(tmp_path / "research.sqlite")
    store.configure(CampaignSpec("attribution", 0, "wall_second", "attribution-fixture"),
                    [Endpoint("attribution", "fixture", "unmeasured", "count", "fixture/1", 0,
                              queryable=False)])
    return ResearchJournal(store)


def _artifact(tmp_path, name, payload, **overrides):
    import json

    from etalon.boundary.prism_v1 import file_identity
    from etalon.research.schema import Artifact

    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    fields = {"source_kind": "fixture", "role": "diagnostic", "bindings": {}, **overrides}
    return Artifact(str(path), **file_identity(path), **fields)


def _stored_records(journal):
    """Every research record in the store, read back the way a census would read them."""

    import json

    with journal.store.connection() as db:
        return [json.loads(row[0]) for row in
                db.execute("SELECT body FROM metadata WHERE key LIKE 'research:%'")]


def test_attribution_reaches_exactly_the_record_types_that_own_a_bindings_mapping():
    """Scope. The reserved `bindings` block is ETALON's; a record's payload is not.

    A previous overreach in this area annotated content that belonged to callers' own
    documents. So the stamp is confined to the one mapping `reserved_bindings.py` already
    governs, and the types that own it are pinned here: a record type that grows or loses
    `bindings` changes what the seam can reach, and that is a decision, not a side effect.
    """

    import dataclasses

    from etalon.research import schema

    types = (schema.Artifact, schema.Experiment, schema.Observation, schema.Contrast,
             schema.Revision, schema.TaskSplit, schema.MethodVersion, schema.MethodUse,
             schema.MethodEvaluation)
    owning = {c.__name__ for c in types
              if "bindings" in {f.name for f in dataclasses.fields(c)}}
    assert owning == {"Artifact", "Experiment"}, (
        "the set of records that can carry attribution changed; the other seven carry no "
        "bindings mapping and must not be grown one to hold ETALON's annotation")


def test_a_bindings_bearing_record_cannot_reach_the_journal_unattributed(tmp_path):
    """The property, held by its consequence, over the journal rather than a list of sites.

    Nothing below names a write site. Three unrelated real paths write records -- one that
    builds its own `Artifact` and calls `journal.record` (the shape 27 sites use), one that
    goes through `record_json`, and `audit_json`, which writes an `Artifact`, an
    `Experiment` and an `Observation` in a single call -- and then *every* research record
    in the store is counted. A site nobody enumerated fails this exactly as a known one
    does, because the thing under test is the census denominator itself: a record that got
    in without attribution shows up as the `not_recorded` remainder, which is precisely how
    the defect read before (an under-counted denominator that looks like a capability which
    produced nothing).
    """

    from etalon.research.capability_attribution import MCP_TOOL, running_capability
    from etalon.research.components import record_json
    from etalon.research.journal import audit_json

    journal = _journal(tmp_path)
    with running_capability("etalon_probe_verb"):
        journal.record(_artifact(tmp_path, "raw.json", {"n": 1}))
        record_json(journal, {"n": 2}, tmp_path / "records", source_kind="fixture")
        audit_json(journal, _artifact(tmp_path, "audited.json", {"n": 3}),
                   task_id="attribution-task", selectors={"n": ("n",)})

    carrying = [r for r in _stored_records(journal) if isinstance(r.get("bindings"), dict)]
    assert len(carrying) >= 4, "the write paths under test produced no bindings-bearing records"
    out = census(carrying)
    assert out["not_recorded"] == 0, (
        f"{out['not_recorded']} of {out['records']} records reached the journal carrying a "
        "bindings mapping and no attribution: the verb census under-counts by that many, and "
        "afterwards they are indistinguishable from records produced outside any verb")
    assert out["by_capability"] == {"etalon_probe_verb": len(carrying)}
    assert out["by_basis"] == {MCP_TOOL: len(carrying)}


def test_a_record_written_outside_any_verb_is_labelled_rather_than_left_blank(tmp_path):
    """Constraint 7: not obtained is reported as not obtained, and reporting it is a write.

    Direct library use genuinely has no verb to name. The honest value is the one `BASES`
    already allows and `assessment_role_basis` already uses for the analogous case -- the
    key present, saying `not_recorded` -- because an omitted key and a record predating
    attribution read identically, and only one of those is a fact about this record.
    """

    journal = _journal(tmp_path)
    identifier = journal.record(_artifact(tmp_path, "outside.json", {"n": 1}))
    body = journal.get(identifier)
    assert KEY in body["bindings"], "the attribution was omitted rather than labelled"
    assert read_attribution(body) == {"capability": NOT_RECORDED, "basis": NOT_RECORDED}


def test_the_record_the_caller_holds_keeps_the_identity_that_was_stored(tmp_path):
    """A record's id is a digest of its body, so stamping moves it. It must move before.

    `rows.py:27` returns `artifact.id` after recording, `method_execution.py:213` uses it as
    a dict key beside the returned id, and `audit_json` builds an `Observation` around
    `experiment.id`. If the seam handed back a different identity than the caller's object
    carries, those three would reference records that are not there.
    """

    from etalon.research.capability_attribution import running_capability

    journal = _journal(tmp_path)
    artifact = _artifact(tmp_path, "identity.json", {"n": 1})
    with running_capability("etalon_probe_verb"):
        identifier = journal.record(artifact)
    assert artifact.id == identifier
    assert journal.get(artifact.id)["bindings"][KEY]["capability"] == "etalon_probe_verb"


def test_the_stamp_does_not_reach_into_the_bindings_dict_the_caller_passed(tmp_path):
    """`pose.py:196` hands one caller-owned dict to every artifact in a loop.

    That dict is `request['input_identity']` -- the caller's own document. Mutating it in
    place would stamp ETALON's annotation into the request, and into every other record
    sharing the object. The record carries the block; what the caller passed does not.
    """

    from etalon.research.capability_attribution import running_capability

    journal = _journal(tmp_path)
    shared = {"kind": "poses"}
    with running_capability("etalon_probe_verb"):
        identifiers = [journal.record(_artifact(tmp_path, name, {"n": n}, bindings=shared))
                       for n, name in ((1, "a.json"), (2, "b.json"))]
    assert shared == {"kind": "poses"}, "the caller's own bindings dict was annotated"
    for identifier in identifiers:
        body = journal.get(identifier)
        assert body["bindings"]["kind"] == "poses", "the rest of the bindings must be untouched"
        assert body["bindings"][KEY]["capability"] == "etalon_probe_verb"


def test_the_seam_never_overwrites_a_more_specific_name(tmp_path):
    """Moving the stamp must not stamp twice or rename someone else's work.

    Both ways a specific name arrives: declared through `record_json`, and already present
    in the bindings of a record built elsewhere. The verb is only the entry point to
    whatever skill or executor actually ran, so it never outranks either.
    """

    from etalon.research.capability_attribution import running_capability
    from etalon.research.components import record_json

    journal = _journal(tmp_path)
    with running_capability("etalon_probe_verb"):
        through = record_json(journal, {"n": 1}, tmp_path / "records", source_kind="fixture",
                              capability="etalon-step-corpus")
        prestamped = journal.record(_artifact(
            tmp_path, "declared.json", {"n": 2},
            bindings=with_attribution({"kind": "poses"}, "etalon-step-corpus")))
    for identifier in (through, prestamped):
        assert read_attribution(journal.get(identifier)) == {
            "capability": "etalon-step-corpus", "basis": "declared"}


def test_attribution_is_stamped_at_the_write_and_never_backfilled(tmp_path):
    """`CLAUDE.md` constraint 4's discipline, applied to the same class of fact.

    `admission` is written at dispatch and never added afterwards, for the reason this
    module exists: a value added later is indistinguishable from one that was there. So
    re-recording a record already in the journal under a different verb must not reopen it,
    and the journal's own refusal to rewrite an identity must still be the thing standing
    behind that.
    """

    from etalon.active.store import StateError
    from etalon.research.capability_attribution import running_capability

    journal = _journal(tmp_path)
    artifact = _artifact(tmp_path, "backfill.json", {"n": 1})
    identifier = journal.record(artifact)
    assert read_attribution(journal.get(identifier))["capability"] == NOT_RECORDED

    with running_capability("etalon_later_verb"):
        assert journal.record(artifact) == identifier, "a second write renamed the producer"
    assert read_attribution(journal.get(identifier))["capability"] == NOT_RECORDED

    body = journal.get(identifier)
    body["bindings"] = {**body["bindings"], KEY: attribution("etalon_later_verb")}
    with pytest.raises(StateError), journal.store.connection(write=True) as db:
        journal._put(db, identifier, body)
