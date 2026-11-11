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
    """Wired at `record_json`, which every artifact write funnels through."""

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
