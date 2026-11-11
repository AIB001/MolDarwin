"""Tests for the node-level admission view (docs/thin-harness/ADMISSION_PROPAGATION.md, v2).

Test names carry the invariant (I1..I12) or the section (s10_x) they hold.
"""

from __future__ import annotations

import copy
import dataclasses
import os
import sqlite3
from datetime import date

import pytest

import etalon.learn.admission_view as av
from etalon.active.schema import canonical, digest
from etalon.faults.attribution import Observation
from etalon.faults.taxonomy import BY_CODE, FAULTS, Consequence, Evidence, Exactness, Phase
from etalon.judgment.waiver import Waiver, WaiverSet
from etalon.learn.admissible import Measurement, rule
from etalon.learn.admission_view import (
    UNCATALOGUED_BLOCKING_CODES,
    AdmissionViewMismatch,
    admission_view,
    catalogue_digest,
    compare_views,
)
from etalon.research.evidence_refs import make_ref
from etalon.research.graph_memory import GRAPH, node_identity
from etalon.research.graph_scope import SCOPE

# ---------------------------------------------------------------- helpers

_REFS: dict[str, dict] = {}


def _ref(name: str) -> dict:
    if name not in _REFS:
        _REFS[name] = make_ref("src", name, {"name": name})
    return _REFS[name]


def nid(name: str) -> str:
    return node_identity(_ref(name))


def _good_receipt() -> dict:
    return {
        "schema": SCOPE, "traversal_complete": True, "reference_coverage_complete": True,
        "deliberate_boundary_refs": [], "boundary_relations": [], "issues": [],
    }


def seal(graph: dict) -> dict:
    """Give a graph its correct view_id, the way graph_scope does."""

    graph.pop("view_id", None)
    graph["view_id"] = "research-graph-" + digest(graph)
    return graph


def regraph(graph: dict, change) -> dict:
    """Copy a graph, apply ``change`` and re-seal it so the edit is the only difference."""

    out = copy.deepcopy(graph)
    change(out)
    return seal(out)


def make_graph(names, edges, *, truncated=False, kinds=None, receipt="good", view_id=True,
               regimes=None, experiences=None):
    """edges: (from_name, to_name, kind, relation_or_None) in graph direction.

    The default graph asserts completeness (section 10.4): a scope_receipt with schema
    ``SCOPE``, ``issues == []`` and a correct graph view_id.

    ``experiences`` maps a node name to the ``experience`` projection block
    ``_project_node`` writes for an ``etalon-method-experience/1`` record. Mirrors
    ``regimes`` and is passed verbatim for the same reason: the v4 membrane keys on
    the presence of that block, so a test must show the block it depends on.

    ``regimes`` maps a node name to the ``evaluation`` projection block
    ``research/graph_memory._project_node`` writes for an
    ``etalon-method-evaluation/1`` record. The block is passed verbatim rather
    than built from a shorthand, so each membrane test shows the exact projected
    shape it depends on -- including the case that matters most for migration,
    where ``assessment_role_basis`` is simply absent.
    """

    kinds = kinds or {}
    regimes = regimes or {}
    experiences = experiences or {}
    nodes = [
        {"node_id": nid(n), "ref": _ref(n), "home": "Judge", "kind": kinds.get(n, "J"),
         "kind_basis": "legacy_record_semantics_inferred", "scope": "task", "task_id": "t1",
         **({"evaluation": regimes[n]} if n in regimes else {}),
         **({"experience": experiences[n]} if n in experiences else {})}
        for n in names
    ]
    out = []
    for a, b, kind, relation in edges:
        e = {"from": nid(a), "to": nid(b), "kind": kind, "basis_ref": _ref(a)}
        if relation is not None:
            e["relation"] = relation
        out.append(e)
    graph = {
        "schema": GRAPH, "checkpoint_ref": _ref("ckpt"), "task_id": "t1",
        "nodes": nodes, "edges": out, "truncated": truncated, "issues": [],
        "execution_permission": "not_granted", "automatic_retry": False,
    }
    if receipt == "good":
        graph["scope_receipt"] = _good_receipt()
    elif receipt is not None:
        graph["scope_receipt"] = receipt
    return seal(graph) if view_id else graph


def _ruling_dict(name, admission, action):
    blocking, waived = [], []
    if admission == "withheld":
        blocking = ["F_HYDROGENS_IMPLICIT", "NO_EXPENSIVE_VALUE", "F_POSE_LEFT_THE_SITE"]
    elif admission == "admitted_under_waiver":
        waived = ["F_PROTONATION_UNDECIDED"]
    return {
        "parent_id": name, "admission": admission, "teaches": admission != "withheld",
        "reproducible": True, "blocking": blocking, "waived": waived, "bounded": [],
        "unverifiable": [], "unchecked": [], "notes": [action],
    }


def binding_from_ruling(name, ruling, *, status="ok", store_admitted=None, supersedes=None,
                        scope=None, action="a1"):
    if store_admitted is None:
        store_admitted = status == "ok" and ruling["teaches"]
    return {
        "node_id": nid(name), "ruling": ruling, "ruling_digest": digest(ruling),
        "dispatch_ref": {"store": "campaign", "action_id": action},
        "claim_scope": scope or {"parent_id": ruling["parent_id"], "endpoint": "dG",
                                 "units": "kcal/mol"},
        "store_status": status, "store_admitted": store_admitted,
        "supersedes": [] if supersedes is None else [supersedes],
    }


def binding(name, admission, *, supersedes=None, scope=None, action="a1"):
    return binding_from_ruling(name, _ruling_dict(name, admission, action),
                               supersedes=supersedes, scope=scope, action=action)


def redigest(b):
    b["ruling_digest"] = digest(b["ruling"])
    return b


def by_id(view, name):
    return next(n for n in view["nodes"] if n["node_id"] == nid(name))


def j_graph(relation="measured_result", **kw):
    return make_graph(
        ["J", "p1", "p2", "p3"],
        [("J", p, "depends_on", relation) for p in ("p1", "p2", "p3")], **kw,
    )


def reid(view):
    """Re-seal a hand-edited view so only the edited condition can refuse a comparison."""

    view = copy.deepcopy(view)
    view.pop("view_id", None)
    view["view_id"] = "admission-view-" + digest(view)
    return view


# ---------------------------------------------------------------- fixtures for I1 / I12

I1_DIGEST = "d003268d06fc8267b3d30cccd54bc8248ca457ee158167e477edaab7398f082a"
#: Second pin: rule(..., require_comparator=False), the path CampaignStore uses.
#: Computed from the unmodified rule() with
#:   PYTHONPATH=src /tmp/etalon-venv/bin/python /tmp/i1_pin2.py
I1_DIGEST_NO_COMPARATOR = "c756480f629f1c820e787d64cb7d3366a682fb8a9a9ae6ac3f0291078ca6b635"
I1_WHEN = date(2026, 11, 5)

_WAIVERS = WaiverSet((Waiver(
    code="F_PROTONATION_UNDECIDED",
    reason="Ligand protonation is undecided by the upstream tool; accepted for this campaign.",
    granted_by="test operator", expires=date(2027, 1, 1),
    granted_at="2026-11-01T00:00:00+00:00"),))


def _obs(code, fired=True, evaluable=True):
    return Observation(code=code, fired=fired, detail="d", evaluable=evaluable)


def _i1_cases():
    return _WAIVERS, [
        ("clean", Measurement("m_clean", -7.0, -8.0), "admitted"),
        ("wrong_subject", Measurement("m_ws", -7.0, -8.0, (_obs("F_HYDROGENS_IMPLICIT"),)), "withheld"),
        ("wrong_size", Measurement("m_size", -7.0, -8.0, (_obs("F_STEREO_CHOSEN_BY_EMBEDDING"),)), "admitted"),
        ("unverifiable", Measurement("m_unv", -7.0, -8.0, (_obs("F_RUN_NOT_REPRODUCIBLE"),)), "admitted"),
        ("waived", Measurement("m_waived", -7.0, -8.0, (_obs("F_PROTONATION_UNDECIDED"),)), "admitted_under_waiver"),
        ("unevaluable", Measurement("m_uneval", -7.0, -8.0, (_obs("F_POSE_LEFT_THE_SITE", False, False),)), "admitted"),
        ("nonfinite", Measurement("m_nan", float("nan"), -8.0), "withheld"),
        ("no_cheap", Measurement("m_nocheap", None, -8.0), "withheld"),
        ("no_expensive", Measurement("m_noexp", -7.0, None), "withheld"),
    ]


def _i1b_cases():
    """The CampaignStore path: require_comparator=False. Admissions pinned literally."""

    inf, nan = float("inf"), float("nan")
    return _WAIVERS, [
        ("clean", Measurement("m_clean", -7.0, -8.0), "admitted"),
        ("wrong_subject", Measurement("m_ws", -7.0, -8.0, (_obs("F_HYDROGENS_IMPLICIT"),)), "withheld"),
        ("threshold_only", Measurement("m_thr", -7.0, -8.0, (_obs("F_POSE_LEFT_THE_SITE"),)), "withheld"),
        ("wrong_size", Measurement("m_size", -7.0, -8.0, (_obs("F_STEREO_CHOSEN_BY_EMBEDDING"),)), "admitted"),
        ("unverifiable", Measurement("m_unv", -7.0, -8.0, (_obs("F_RUN_NOT_REPRODUCIBLE"),)), "admitted"),
        ("waived", Measurement("m_waived", -7.0, -8.0, (_obs("F_PROTONATION_UNDECIDED"),)), "admitted_under_waiver"),
        ("unevaluable", Measurement("m_uneval", -7.0, -8.0, (_obs("F_HYDROGENS_IMPLICIT", False, False),)), "admitted"),
        ("nonfinite_expensive", Measurement("m_infexp", -7.0, inf), "withheld"),
        ("nonfinite_cheap", Measurement("m_nancheap", nan, -8.0), "withheld"),
        # With require_comparator=False a missing cheap value does not block.
        ("no_cheap", Measurement("m_nocheap", None, -8.0), "admitted"),
        ("no_expensive", Measurement("m_noexp", -7.0, None), "withheld"),
        ("no_cheap_nonfinite_expensive", Measurement("m_both", None, nan), "withheld"),
    ]


def _real(case_name, require_comparator=False, parent=None):
    waivers, cases = _i1b_cases()
    m = next(m for n, m, _ in cases if n == case_name)
    if parent is not None:  # distinct parent_id so that two nodes never share a ruling digest
        m = dataclasses.replace(m, parent_id=parent)
    return rule(m, waivers, when=I1_WHEN, require_comparator=require_comparator).as_dict()


# ---------------------------------------------------------------- I1

def test_i1_rule_unchanged_pinned_digest():
    waivers, cases = _i1_cases()
    rulings = [rule(m, waivers, when=I1_WHEN) for _, m, _ in cases]
    for (name, _, expected), ruling in zip(cases, rulings):
        assert ruling.admission.value == expected, name
    assert digest([r.as_dict() for r in rulings]) == I1_DIGEST


def test_i1_second_pin_require_comparator_false_path():
    waivers, cases = _i1b_cases()
    rulings = [rule(m, waivers, when=I1_WHEN, require_comparator=False) for _, m, _ in cases]
    for (name, _, expected), ruling in zip(cases, rulings):
        assert ruling.admission.value == expected, name
    blocking = {name: list(r.blocking) for (name, _, _), r in zip(cases, rulings)}
    assert blocking["nonfinite_expensive"] == ["NONFINITE_EXPENSIVE_VALUE"]
    assert blocking["no_cheap"] == []  # a missing cheap value does not block on this path
    assert blocking["no_cheap_nonfinite_expensive"] == ["NONFINITE_EXPENSIVE_VALUE"]
    assert digest([r.as_dict() for r in rulings]) == I1_DIGEST_NO_COMPARATOR


# ---------------------------------------------------------------- I12 and s10.5

def _blocking_codes_of_both_fixtures():
    codes = set()
    for fixture, comparator in ((_i1_cases, True), (_i1b_cases, False)):
        waivers, cases = fixture()
        for _, m, _ in cases:
            codes.update(rule(m, waivers, when=I1_WHEN, require_comparator=comparator).blocking)
    return codes


def test_i12_every_i1_blocking_code_is_catalogued_or_declared_uncatalogued():
    codes = _blocking_codes_of_both_fixtures()
    assert {"NO_CHEAP_VALUE", "NO_EXPENSIVE_VALUE", "NONFINITE_CHEAP_VALUE",
            "NONFINITE_EXPENSIVE_VALUE", "F_HYDROGENS_IMPLICIT"} <= codes  # fixtures reach them
    undeclared = {c for c in codes if c not in BY_CODE and c not in UNCATALOGUED_BLOCKING_CODES}
    assert undeclared == set()


def test_s10_5_uncatalogued_blocking_codes_are_those_five_and_not_faults():
    assert set(UNCATALOGUED_BLOCKING_CODES) == {
        "NONFINITE_CHEAP_VALUE", "NONFINITE_EXPENSIVE_VALUE", "NO_EXPENSIVE_VALUE",
        "NO_CHEAP_VALUE", "PROTOCOL_EVIDENCE_MISMATCH"}
    assert not set(UNCATALOGUED_BLOCKING_CODES) & set(BY_CODE)


def test_s10_5_coverage_block_in_output_and_digest_docstring_says_so():
    view = admission_view(j_graph(), [])
    assert view["catalogue_coverage"] == {
        "blocking_surface_complete": False,
        "uncatalogued_blocking_codes": sorted(UNCATALOGUED_BLOCKING_CODES),
    }
    doc = catalogue_digest.__doc__
    assert "does NOT cover" in doc and "UNCATALOGUED_BLOCKING_CODES" in doc


# ---------------------------------------------------------------- fixture self-checks (s10.4, graph digest)

def test_fixture_graph_asserts_completeness_with_scope_schema_and_correct_view_id():
    graph = j_graph()
    assert graph["scope_receipt"]["schema"] == SCOPE == av._COMPLETENESS_SCHEMA
    rest = {k: v for k, v in graph.items() if k != "view_id"}
    assert graph["view_id"] == "research-graph-" + digest(rest)
    view = admission_view(graph, [])
    assert view["graph_completeness"] == {"asserted": True, "missing": []}
    assert view["graph_view_id"] == graph["view_id"]


def test_graph_view_id_digest_check_is_exercised_by_a_tampered_graph():
    graph = j_graph()
    graph["question"] = "edited after sealing"  # view_id not recomputed
    with pytest.raises(ValueError, match="digest mismatch"):
        admission_view(graph, [])


# ---------------------------------------------------------------- J downgrade (3 named tests)

def test_j_downgrade_to_withheld_names_the_withheld_premise():
    graph = j_graph()
    bindings = [binding("p1", "admitted"), binding("p2", "admitted"), binding("p3", "withheld")]
    view = admission_view(graph, bindings)
    j = by_id(view, "J")
    assert j["admission"] == "withheld"
    assert j["limited_by"] == [nid("p3")]
    assert nid("p3") in j["limiting_leaves"]
    assert j["limiting_leaves"] == [nid("p3")]
    assert view["binding_provenance"] == "caller_declared"


def test_j_all_admitted_control():
    bindings = [binding(p, "admitted") for p in ("p1", "p2", "p3")]
    j = by_id(admission_view(j_graph(), bindings), "J")
    assert j["admission"] == "admitted"
    assert j["leaf"] is None


def test_history_retained_after_supersede():
    graph = j_graph()
    first = binding("p1", "admitted", scope={"parent_id": "p1", "endpoint": "old"})
    second = binding("p1", "withheld", supersedes=first["ruling_digest"], action="a2")
    bindings = [first, binding("p2", "admitted"), binding("p3", "admitted"), second]
    view = admission_view(graph, bindings)
    p1 = by_id(view, "p1")
    assert p1["admission"] == "withheld"
    assert p1["leaf"] == "withheld"
    assert p1["history"] == [{
        "admission": "admitted", "ruling_digest": first["ruling_digest"],
        "claim_scope": {"parent_id": "p1", "endpoint": "old"},
        "superseded_by": second["ruling_digest"],
    }]
    j = by_id(view, "J")
    assert j["admission"] == "withheld"
    assert j["rests_on_superseded_premise"] is True
    assert by_id(view, "p2")["rests_on_superseded_premise"] is False


# ---------------------------------------------------------------- I2

def test_i2_no_mutation_no_file_written_and_no_sqlite(tmp_path, monkeypatch):
    graph = make_graph(["J", "s", "p1"], [("s", "J", "supports", None),
                                          ("J", "p1", "depends_on", "measured_result")])
    labels = {f"{nid('s')}|{nid('J')}|supports": "used"}
    with_chain = binding("p1", "admitted")
    bindings = [with_chain, binding("p1", "withheld", supersedes=with_chain["ruling_digest"], action="a2")]
    no_supersedes_key = binding("s", "admitted")
    del no_supersedes_key["supersedes"]
    bindings.append(no_supersedes_key)
    snapshot = copy.deepcopy((graph, bindings, labels))

    def boom(*a, **k):
        raise AssertionError("the view must not open a store")

    monkeypatch.setattr(sqlite3, "connect", boom)
    monkeypatch.chdir(tmp_path)
    admission_view(graph, bindings, labels=labels)
    assert (graph, bindings, labels) == snapshot
    assert "supersedes" not in bindings[-1]  # nothing was setdefault-ed into the caller's binding
    assert "teaches" in bindings[0]["ruling"] and set(bindings[0]) == set(snapshot[1][0])
    assert os.listdir(tmp_path) == []


def test_i2_binding_without_supersedes_key_is_accepted_and_unchanged():
    b = binding("p1", "admitted")
    del b["supersedes"]
    before = copy.deepcopy(b)
    view = admission_view(j_graph(), [b])
    assert b == before
    assert by_id(view, "p1")["leaf"] == "admitted"
    assert by_id(view, "p1")["history"] == []


def test_i2_rulings_are_not_mutated_by_derivation():
    ruling = _real("wrong_subject")
    b = binding_from_ruling("p1", ruling)
    before = copy.deepcopy(b)
    admission_view(j_graph(), [b])
    assert b == before and ruling == before["ruling"]


# ---------------------------------------------------------------- I3 / s10.7 (two or more hops)

def _chain_graph():
    # J -> m -> p1, J -> w : p1 two hops below J
    return make_graph(["J", "m", "p1", "w"], [
        ("J", "m", "depends_on", "measured_result"),
        ("m", "p1", "depends_on", "measured_result"),
        ("J", "w", "depends_on", "measured_result"),
    ])


def test_i3_s10_7_superseded_premise_two_hops_below_marks_the_top():
    first = binding("p1", "admitted")
    second = binding("p1", "admitted", supersedes=first["ruling_digest"], action="a2")
    view = admission_view(_chain_graph(), [first, second, binding("w", "admitted")])
    assert [by_id(view, n)["rests_on_superseded_premise"] for n in ("J", "m", "p1", "w")] == [
        True, True, True, False]
    assert by_id(view, "J")["admission"] == "admitted"


def test_i3_s10_7_mark_holds_when_the_superseded_premise_does_not_attain_the_minimum():
    first = binding("p1", "admitted")
    second = binding("p1", "admitted", supersedes=first["ruling_digest"], action="a2")
    view = admission_view(_chain_graph(), [first, second, binding("w", "withheld")])
    j = by_id(view, "J")
    assert j["admission"] == "withheld"
    assert j["limiting_leaves"] == [nid("w")]
    assert j["rests_on_superseded_premise"] is True  # p1 two hops down, not limiting


def test_i3_s10_7_bound_node_with_own_history_is_marked_though_its_leaf_is_above_the_floor():
    first = binding("m", "admitted")
    second = binding("m", "admitted", supersedes=first["ruling_digest"], action="a2")
    graph = make_graph(["m", "p"], [("m", "p", "depends_on", "measured_result")])
    view = admission_view(graph, [first, second, binding("p", "withheld")])
    m = by_id(view, "m")
    assert m["leaf"] == "admitted" and m["admission"] == "withheld"
    assert m["limiting_leaves"] == [nid("p")]  # m's own leaf does not attain the floor
    assert m["rests_on_superseded_premise"] is True


def test_i3_unsuperseded_graph_marks_nothing():
    view = admission_view(_chain_graph(), [binding("p1", "admitted"), binding("w", "admitted")])
    assert not any(n["rests_on_superseded_premise"] for n in view["nodes"])


# ---------------------------------------------------------------- limiting_leaves (two or more hops)

def test_limiting_leaves_names_the_bottom_leaf_not_the_intermediate_node_two_hops():
    graph = make_graph(["J", "m", "p"], [("J", "m", "depends_on", "measured_result"),
                                         ("m", "p", "depends_on", "measured_result")])
    view = admission_view(graph, [binding("m", "admitted"), binding("p", "withheld")])
    j, m = by_id(view, "J"), by_id(view, "m")
    assert j["admission"] == "withheld"
    assert j["limited_by"] == [nid("m")]
    assert j["limiting_leaves"] == [nid("p")]
    assert m["limited_by"] == [nid("p")] and m["limiting_leaves"] == [nid("p")]


def test_limiting_leaves_three_hops_and_unbound_bottom():
    graph = make_graph(["J", "a", "b", "u"], [
        ("J", "a", "depends_on", "measured_result"),
        ("a", "b", "depends_on", "measured_result"),
        ("b", "u", "depends_on", "measured_result"),
    ])
    view = admission_view(graph, [binding("a", "admitted"), binding("b", "admitted")])
    for name in ("J", "a", "b"):
        node = by_id(view, name)
        assert node["admission"] == "not_recorded"
        assert node["limiting_leaves"] == [nid("u")]  # u is not_recorded and lists itself
    assert by_id(view, "J")["limited_by"] == [nid("a")]


def test_limiting_leaves_two_branches_both_reported():
    graph = make_graph(["J", "m1", "m2", "p1", "p2"], [
        ("J", "m1", "depends_on", "measured_result"), ("J", "m2", "depends_on", "measured_result"),
        ("m1", "p1", "depends_on", "measured_result"), ("m2", "p2", "depends_on", "measured_result"),
    ])
    view = admission_view(graph, [binding("p1", "withheld"), binding("p2", "withheld"),
                                  binding("m1", "admitted"), binding("m2", "admitted")])
    assert by_id(view, "J")["limiting_leaves"] == sorted([nid("p1"), nid("p2")])


# ---------------------------------------------------------------- I4 / s10.6 catalogue_digest membership

def _patched_digest(monkeypatch, faults):
    monkeypatch.setattr(av, "FAULTS", tuple(faults))
    return av.catalogue_digest()


def _other(enum_cls, member):
    return next(m for m in enum_cls if m is not member)


@pytest.mark.parametrize("field", ["summary", "observable", "source", "remedy"])
def test_i4_catalogue_digest_ignores_prose_fields(monkeypatch, field):
    base = catalogue_digest()
    changed = list(FAULTS)
    changed[-1] = dataclasses.replace(changed[-1], **{field: getattr(changed[-1], field) + " reworded"})
    assert changed[-1] != FAULTS[-1]
    assert _patched_digest(monkeypatch, changed) == base


@pytest.mark.parametrize("field", ["code", "phase", "exactness", "consequence",
                                   "lower_kcal_mol", "upper_kcal_mol", "evidence"])
def test_i4_catalogue_digest_covers_semantic_fields(monkeypatch, field):
    base = catalogue_digest()
    last = FAULTS[-1]
    new = {
        "code": last.code + "_X",
        "phase": _other(Phase, last.phase),
        "exactness": _other(Exactness, last.exactness),
        "consequence": _other(Consequence, last.consequence),
        "lower_kcal_mol": (last.lower_kcal_mol or 0.0) + 1.0,
        "upper_kcal_mol": (last.upper_kcal_mol or 0.0) + 1.0,
        "evidence": _other(Evidence, last.evidence),
    }[field]
    changed = list(FAULTS)
    changed[-1] = dataclasses.replace(last, **{field: new})
    assert _patched_digest(monkeypatch, changed) != base


def test_i4_catalogue_digest_changes_when_a_fault_is_added_or_removed(monkeypatch):
    base = catalogue_digest()
    assert _patched_digest(monkeypatch, FAULTS[:-1]) != base
    assert _patched_digest(monkeypatch, FAULTS[1:]) != base
    extra = dataclasses.replace(FAULTS[0], code="F_AN_ADDED_FAULT")
    assert _patched_digest(monkeypatch, [*FAULTS, extra]) != base


def test_i4_catalogue_digest_unpatched_value_is_restored_after_monkeypatch():
    assert catalogue_digest() == catalogue_digest() and len(catalogue_digest()) == 64


def test_i4_view_carries_version_and_catalogue_digest():
    view = admission_view(j_graph(), [binding("p1", "admitted")])
    # v3 because the membrane changes derived values: a stored v2 view and a v3
    # view are two propagation rules, and compare_views must refuse the pair.
    assert view["view_version"] == "etalon-admission-view/4"
    assert view["schema"] == "etalon-admission-view/4"
    assert view["catalogue_digest"] == catalogue_digest()


# ---------------------------------------------------------------- I6, I5

def test_i6_unbound_node_without_premises_is_not_recorded():
    view = admission_view(make_graph(["lonely"], []), [])
    node = by_id(view, "lonely")
    assert node["admission"] == "not_recorded"
    assert node["exact_admission"] == "not_recorded"
    assert node["leaf"] is None
    assert node["limiting_leaves"] == [nid("lonely")]
    assert node["exact_limiting_leaves"] == [nid("lonely")]


def test_i6_all_nodes_not_recorded_when_nothing_bound():
    view = admission_view(j_graph(), [])
    assert {n["admission"] for n in view["nodes"]} == {"not_recorded"}
    assert {n["exact_admission"] for n in view["nodes"]} == {"not_recorded"}


def test_i5_unbound_premise_bounds_owner_below_waiver():
    bindings = [binding("p1", "admitted"), binding("p2", "admitted_under_waiver")]
    j = by_id(admission_view(j_graph(), bindings), "J")  # p3 unbound
    assert j["admission"] == "not_recorded"
    assert j["limited_by"] == [nid("p3")]
    bindings.append(binding("p3", "admitted"))
    j = by_id(admission_view(j_graph(), bindings), "J")
    assert j["admission"] == "admitted_under_waiver"
    assert j["limited_by"] == [nid("p2")]


def test_own_leaf_bounds_owner():
    bindings = [binding("J", "withheld"), binding("p1", "admitted"),
                binding("p2", "admitted"), binding("p3", "admitted")]
    j = by_id(admission_view(j_graph(), bindings), "J")
    assert j["admission"] == "withheld"
    assert j["limited_by"] == []
    assert j["limiting_leaves"] == [nid("J")]


# ---------------------------------------------------------------- I7

@pytest.mark.parametrize("kind,relation", [
    ("depends_on", "prior_use"), ("depends_on", None), ("depends_on", "visible_at_selection"),
    ("depends_on", "selection_output"), ("derived_from", None), ("tests", None),
    ("refutes", None), ("supersedes", None), ("flow", None),
])
def test_i7_used_and_not_premise_edges_do_not_propagate(kind, relation):
    graph = make_graph(["J", "side", "p1"], [
        ("J", "p1", "depends_on", "measured_result"),
        ("J", "side", kind, relation),
    ])
    results = []
    for side in ("admitted", "withheld"):
        view = admission_view(graph, [binding("p1", "admitted"), binding("side", side)])
        results.append((by_id(view, "J")["admission"], by_id(view, "J")["exact_admission"]))
    assert results == [("admitted", "admitted")] * 2


# ---------------------------------------------------------------- s10.3 classification

def _supports_graph():
    return make_graph(["J", "s"], [("s", "J", "supports", None)])  # graph direction: premise -> owner


def test_s10_3_supports_defaults_to_used():
    view = admission_view(_supports_graph(), [binding("s", "withheld")])
    j = by_id(view, "J")
    assert j["admission"] == "not_recorded"
    assert j["premises"] == []
    edge = view["edges"][0]
    assert (edge["owner"], edge["premise"]) == (nid("J"), nid("s"))
    assert (edge["premise_class"], edge["class_basis"]) == ("used", "unlabelled_default")
    assert "premise_basis" not in j


def test_s10_3_sole_admitted_supports_edge_gives_not_recorded_not_admitted():
    """Review 2.1: under the old default this case raised J to admitted."""

    view = admission_view(_supports_graph(), [binding("s", "admitted")])
    j = by_id(view, "J")
    assert j["admission"] == "not_recorded" and j["exact_admission"] == "not_recorded"
    assert j["reasons"] == ["no_binding_and_no_relied_on_premise"]


def test_s10_3_unlabelled_candidate_premises_lists_default_edges_only():
    graph = make_graph(["J", "s1", "s2", "e", "p"], [
        ("s1", "J", "supports", None), ("s2", "J", "supports", None),
        ("J", "e", "depends_on", "evaluated_node"), ("J", "p", "depends_on", "measured_result"),
    ])
    view = admission_view(graph, [], labels={f"{nid('s2')}|{nid('J')}|supports": "relied_on"})
    assert by_id(view, "J")["unlabelled_candidate_premises"] == sorted([nid("s1"), nid("e")])
    assert by_id(view, "s1")["unlabelled_candidate_premises"] == []
    view = admission_view(graph, [], labels={f"{nid('s2')}|{nid('J')}|supports": "used"})
    assert by_id(view, "J")["unlabelled_candidate_premises"] == sorted([nid("s1"), nid("e")])
    view = admission_view(graph, [], labels={
        f"{nid('s1')}|{nid('J')}|supports": "used", f"{nid('s2')}|{nid('J')}|supports": "relied_on",
        f"{nid('J')}|{nid('e')}|depends_on": "used"})
    assert by_id(view, "J")["unlabelled_candidate_premises"] == []


def test_s10_3_label_relied_on_switches_supports_to_relied_on():
    labels = {f"{nid('s')}|{nid('J')}|supports": "relied_on"}
    view = admission_view(_supports_graph(), [binding("s", "withheld")], labels=labels)
    j = by_id(view, "J")
    assert j["admission"] == "withheld" and j["premises"] == [nid("s")]
    assert (view["edges"][0]["premise_class"], view["edges"][0]["class_basis"]) == (
        "relied_on", "human_label")
    assert j["unlabelled_candidate_premises"] == []
    view = admission_view(_supports_graph(), [binding("s", "admitted")], labels=labels)
    assert by_id(view, "J")["admission"] == "admitted"


def test_s10_3_label_used_is_recorded_as_human_label():
    labels = {f"{nid('s')}|{nid('J')}|supports": "used"}
    view = admission_view(_supports_graph(), [binding("s", "withheld")], labels=labels)
    assert by_id(view, "J")["admission"] == "not_recorded"
    assert (view["edges"][0]["premise_class"], view["edges"][0]["class_basis"]) == ("used", "human_label")


def test_s10_3_evaluated_node_defaults_to_used_and_label_switches_it():
    graph = make_graph(["J", "e"], [("J", "e", "depends_on", "evaluated_node")])
    view = admission_view(graph, [binding("e", "withheld")])
    assert by_id(view, "J")["admission"] == "not_recorded"
    assert view["edges"][0]["class_basis"] == "unlabelled_default"
    assert by_id(view, "J")["unlabelled_candidate_premises"] == [nid("e")]
    sole = admission_view(graph, [binding("e", "admitted")])
    assert by_id(sole, "J")["admission"] == "not_recorded"
    labels = {f"{nid('J')}|{nid('e')}|depends_on": "relied_on"}
    view = admission_view(graph, [binding("e", "withheld")], labels=labels)
    assert by_id(view, "J")["admission"] == "withheld"
    assert view["edges"][0]["class_basis"] == "human_label"
    labels = {f"{nid('J')}|{nid('e')}|depends_on": "used"}
    view = admission_view(graph, [binding("e", "withheld")], labels=labels)
    assert by_id(view, "J")["admission"] == "not_recorded"


def test_s10_3_label_key_collision_between_two_kinds_on_one_pair_is_resolved_by_kind():
    # one ordered pair (a, b) carries a supports edge (owner b) and an evaluated_node edge (owner a)
    graph = make_graph(["a", "b"], [("a", "b", "supports", None),
                                    ("a", "b", "depends_on", "evaluated_node")])
    labels = {f"{nid('a')}|{nid('b')}|supports": "relied_on"}
    view = admission_view(graph, [binding("a", "withheld"), binding("b", "admitted")], labels=labels)
    rows = {e["kind"]: e for e in view["edges"]}
    assert (rows["supports"]["premise_class"], rows["supports"]["class_basis"]) == (
        "relied_on", "human_label")
    assert (rows["depends_on"]["premise_class"], rows["depends_on"]["class_basis"]) == (
        "used", "unlabelled_default")
    assert by_id(view, "b")["admission"] == "withheld"  # b relies on a (supports, labelled)
    assert by_id(view, "a")["admission"] == "withheld"  # a's own leaf; no reliance on b
    assert by_id(view, "a")["premises"] == []
    labels = {f"{nid('a')}|{nid('b')}|depends_on": "relied_on"}
    view = admission_view(graph, [binding("a", "withheld"), binding("b", "admitted")], labels=labels)
    rows = {e["kind"]: e for e in view["edges"]}
    assert rows["supports"]["class_basis"] == "unlabelled_default"
    assert rows["depends_on"]["class_basis"] == "human_label"
    assert by_id(view, "a")["premises"] == [nid("b")] and by_id(view, "b")["premises"] == []


def test_s10_3_old_two_part_label_key_is_refused():
    with pytest.raises(ValueError, match="labels"):
        admission_view(_supports_graph(), [], labels={f"{nid('s')}|{nid('J')}": "used"})


@pytest.mark.parametrize("kind", ["supports", "derived_from", "supersedes", "tests", "refutes", "flow"])
def test_s10_3_relation_on_non_depends_on_kind_is_refused(kind):
    graph = make_graph(["a", "b"], [("a", "b", kind, "measured_result")])
    with pytest.raises(ValueError, match="unknown"):
        admission_view(graph, [])


def test_relied_on_wins_per_pair():
    graph = make_graph(["J", "p"], [
        ("J", "p", "depends_on", None),
        ("J", "p", "depends_on", "measured_result"),
    ])
    j = by_id(admission_view(graph, [binding("p", "withheld")]), "J")
    assert j["admission"] == "withheld"


@pytest.mark.parametrize("relation", sorted(
    ["measured_result", "evaluation_result", "selection_basis"]))
def test_declared_relied_on_relations(relation):
    graph = make_graph(["J", "p"], [("J", "p", "depends_on", relation)])
    assert by_id(admission_view(graph, [binding("p", "withheld")]), "J")["admission"] == "withheld"


# ---------------------------------------------------------------- cycle rule

def test_cycle_gets_not_recorded_with_reason_on_both_facets():
    graph = make_graph(["a", "b", "top"], [
        ("a", "b", "depends_on", "measured_result"),
        ("b", "a", "depends_on", "measured_result"),
        ("top", "a", "depends_on", "measured_result"),
    ])
    view = admission_view(graph, [binding("a", "admitted"), binding("b", "admitted")])
    for name in ("a", "b"):
        node = by_id(view, name)
        assert node["admission"] == node["exact_admission"] == "not_recorded"
        assert "circular_reliance" in node["reasons"]
    top = by_id(view, "top")
    assert top["admission"] == "not_recorded"
    assert "circular_reliance" not in top["reasons"]


def test_self_loop_is_circular_and_withheld_still_wins():
    graph = make_graph(["a"], [("a", "a", "depends_on", "measured_result")])
    assert by_id(admission_view(graph, [binding("a", "admitted")]), "a")["admission"] == "not_recorded"
    assert by_id(admission_view(graph, [binding("a", "withheld")]), "a")["admission"] == "withheld"


# ---------------------------------------------------------------- descriptive splits

def test_blocking_split_by_exactness_and_catalogue():
    view = admission_view(make_graph(["p"], []), [binding("p", "withheld")])
    b = by_id(view, "p")["binding"]
    assert b["exact_blocking"] == ["F_HYDROGENS_IMPLICIT"]
    assert b["threshold_blocking"] == ["F_POSE_LEFT_THE_SITE"]
    assert b["derived_blocking"] == []
    assert b["uncatalogued_blocking"] == ["NO_EXPENSIVE_VALUE"]
    assert (b["store_status"], b["store_admitted"]) == ("ok", False)


# ---------------------------------------------------------------- real rulings into bindings

@pytest.mark.parametrize("case,admission,exact", [
    ("wrong_subject", "withheld", "withheld"),
    ("clean", "admitted", "admitted"),
    ("waived", "admitted_under_waiver", "admitted_under_waiver"),
    ("threshold_only", "withheld", "admitted"),
])
def test_real_rulings_bind_and_propagate(case, admission, exact):
    ruling = _real(case)
    assert ruling["admission"] == admission
    view = admission_view(make_graph(["x"], []), [binding_from_ruling("x", ruling)])
    node = by_id(view, "x")
    assert node["leaf"] == node["admission"] == admission
    assert node["exact_leaf"] == node["exact_admission"] == exact


def test_real_rulings_propagate_to_an_owner_across_facets():
    bindings = [binding_from_ruling("p1", _real("clean")),
                binding_from_ruling("p2", _real("waived")),
                binding_from_ruling("p3", _real("threshold_only"))]
    j = by_id(admission_view(j_graph(), bindings), "J")
    assert j["admission"] == "withheld" and j["limited_by"] == [nid("p3")]
    assert j["exact_admission"] == "admitted_under_waiver"
    assert j["exact_limited_by"] == [nid("p2")] and j["exact_limiting_leaves"] == [nid("p2")]


def test_real_ruling_from_require_comparator_true_path_also_binds():
    ruling = _real("no_cheap", require_comparator=True)
    assert ruling["admission"] == "withheld" and ruling["blocking"] == ["NO_CHEAP_VALUE"]
    node = by_id(admission_view(make_graph(["x"], []), [binding_from_ruling("x", ruling)]), "x")
    assert node["admission"] == "withheld" and node["exact_admission"] == "not_recorded"


# ---------------------------------------------------------------- s10.1 / I11 refusals

def _refuses(b, match, names=("a",)):
    with pytest.raises(ValueError, match=match):
        admission_view(make_graph(list(names), []), b if isinstance(b, list) else [b])


def test_s10_1_inconsistent_ruling_admitted_with_blocking_is_refused():
    ruling = _real("clean")
    ruling["blocking"] = ["F_HYDROGENS_IMPLICIT"]  # admission still "admitted"
    _refuses(redigest(binding_from_ruling("a", ruling)), "inconsistent ruling")


@pytest.mark.parametrize("base,change", [
    ("wrong_subject", lambda r: r.update(blocking=[])),          # withheld with nothing blocking
    ("waived", lambda r: r.update(waived=[])),                   # waiver admission, nothing waived
    ("waived", lambda r: r.update(admission="admitted")),        # admitted while waived is non-empty
    ("wrong_subject", lambda r: r.update(admission="admitted_under_waiver", waived=["F_PROTONATION_UNDECIDED"])),
], ids=["withheld_no_blocking", "waiver_no_waived", "admitted_with_waived", "waiver_with_blocking"])
def test_s10_1_inconsistent_ruling_other_admission_blocking_waived_pairs(base, change):
    ruling = _real(base)
    change(ruling)
    b = redigest(binding_from_ruling("a", ruling, store_admitted=ruling["teaches"]))
    _refuses(b, "inconsistent ruling")


def test_s10_1_inconsistent_ruling_teaches_not_equal_to_admission():
    ruling = _real("clean")
    ruling["teaches"] = False
    _refuses(redigest(binding_from_ruling("a", ruling, store_admitted=False)), "teaches must equal")


def test_s10_1_inconsistent_ruling_reproducible_not_equal_to_unverifiable_empty():
    ruling = _real("unverifiable")
    assert ruling["unverifiable"] and ruling["reproducible"] is False
    ruling["reproducible"] = True
    _refuses(redigest(binding_from_ruling("a", ruling)), "reproducible must equal")


def test_s10_1_ruling_keys_must_be_exactly_those_of_as_dict():
    ruling = _real("clean")
    extra = {**ruling, "extra": 1}
    _refuses(redigest(binding_from_ruling("a", extra)), "exactly the keys")
    short = {k: v for k, v in ruling.items() if k != "unchecked"}
    _refuses(redigest(binding_from_ruling("a", short)), "exactly the keys")


def test_s10_1_ruling_digest_mismatch_refused():
    b = binding("a", "admitted")
    b["ruling_digest"] = "0" * 64
    _refuses(b, "ruling_digest")
    b = binding("a", "admitted")
    b["ruling"]["notes"] = ["tampered"]
    _refuses(b, "ruling_digest")


def test_s10_1_not_recorded_as_a_ruling_admission_is_refused():
    ruling = _real("clean")
    ruling["admission"] = "not_recorded"
    _refuses(redigest(binding_from_ruling("a", ruling)), "no valid ruling admission")


@pytest.mark.parametrize("status,admitted", [("ok", False), ("failed", True), ("blocked", True)])
def test_s10_1_store_admitted_disagreeing_with_store_formula_is_refused(status, admitted):
    ruling = _real("clean") if status == "ok" else _real("threshold_only")
    b = binding_from_ruling("a", ruling, status=status, store_admitted=admitted)
    _refuses(b, "store's own formula")


def test_s10_1_ruling_teaches_not_equal_store_admitted_is_refused():
    # status failed + teaches True: the formula says store_admitted False, and it is False,
    # but the ruling teaches: two "admitted" answers that disagree.
    b = binding_from_ruling("a", _real("clean"), status="failed", store_admitted=False)
    _refuses(b, "teaches != store_admitted")


@pytest.mark.parametrize("status,admitted", [("weird", False), (None, False), ("ok", 1), ("ok", "yes")])
def test_s10_1_bad_store_status_or_non_bool_store_admitted_is_refused(status, admitted):
    b = binding("a", "admitted")
    b["store_status"], b["store_admitted"] = status, admitted
    _refuses(b, "store_status must be one of")


@pytest.mark.parametrize("key", ["node_id", "ruling", "ruling_digest", "dispatch_ref", "claim_scope",
                                 "store_status", "store_admitted"])
def test_s10_1_missing_required_key_is_refused(key):
    b = binding("a", "admitted")
    del b[key]
    with pytest.raises(ValueError):
        admission_view(make_graph(["a"], []), [b])


def test_s10_1_unknown_binding_key_is_refused():
    b = binding("a", "admitted")
    b["note"] = "free text"
    _refuses(b, "unknown keys")


@pytest.mark.parametrize("dispatch", [
    {"store": "runtime", "action_id": "a1"}, {"store": "campaign", "action_id": ""},
    {"store": "campaign", "action_id": 7}, {"store": "campaign"}, {"action_id": "a1"},
    {"store": "campaign", "action_id": "a1", "extra": 1}, "a1", None,
])
def test_s10_1_bad_dispatch_ref_is_refused(dispatch):
    b = binding("a", "admitted")
    b["dispatch_ref"] = dispatch
    _refuses(b, "dispatch_ref")


@pytest.mark.parametrize("scope", [["parent_id"], "a", None, 3])
def test_s10_1_non_object_claim_scope_is_refused(scope):
    b = binding("a", "admitted")
    b["claim_scope"] = scope
    _refuses(b, "claim_scope must be an object")


def test_s10_1_claim_scope_parent_id_disagreeing_with_ruling_is_refused():
    b = binding("a", "admitted")
    b["claim_scope"] = {**b["claim_scope"], "parent_id": "other"}
    _refuses(b, "claim_scope parent_id")
    b = binding("a", "admitted")
    b["claim_scope"] = {"endpoint": "dG"}
    _refuses(b, "claim_scope parent_id")


def test_s10_1_same_ruling_digest_bound_to_two_nodes_is_refused():
    one = binding("a", "admitted")
    two = {**copy.deepcopy(one), "node_id": nid("b")}
    _refuses([one, two], "more than one node", names=("a", "b"))


def test_s10_1_chain_whose_claim_scope_parent_id_changes_is_refused():
    first = binding("a", "admitted")
    second_ruling = _ruling_dict("a_renamed", "withheld", "a2")
    second = binding_from_ruling("a", second_ruling, supersedes=first["ruling_digest"], action="a2")
    _refuses([first, second], "changes claim_scope parent_id")


def test_s10_1_supersedes_with_two_entries_is_refused():
    b = binding("a", "admitted")
    b["supersedes"] = ["x" * 64, "y" * 64]
    _refuses(b, "0 or 1 digest")


def test_i8_binding_for_unknown_node_refused():
    b = binding("a", "admitted")
    b["node_id"] = "research-node-doesnotexist"
    _refuses(b, "not in the graph")


def test_i8_forked_chain_refused():
    first = binding("a", "admitted")
    s1 = binding("a", "withheld", supersedes=first["ruling_digest"], action="x")
    s2 = binding("a", "admitted_under_waiver", supersedes=first["ruling_digest"], action="y")
    _refuses([first, s1, s2], "fork")


def test_i8_two_unrelated_heads_refused():
    _refuses([binding("a", "admitted", action="x"), binding("a", "withheld", action="y")], "heads")


def test_i8_dangling_supersedes_refused():
    _refuses(binding("a", "admitted", supersedes="f" * 64), "dangling")


def test_i8_supersedes_cycle_refused():
    x = binding("a", "admitted", action="x")
    y = binding("a", "withheld", action="y")
    x["supersedes"], y["supersedes"] = [y["ruling_digest"]], [x["ruling_digest"]]
    _refuses([x, y], "heads")


def test_i8_unknown_kind_relation_refused():
    for edge in [("a", "b", "depends_on", "no_such_relation"), ("a", "b", "skipped_because", None)]:
        with pytest.raises(ValueError, match="unknown"):
            admission_view(make_graph(["a", "b"], [edge]), [])


def test_i8_label_on_non_labelable_edge_refused():
    graph = make_graph(["a", "b"], [("a", "b", "depends_on", "measured_result")])
    with pytest.raises(ValueError, match="labels"):
        admission_view(graph, [], labels={f"{nid('a')}|{nid('b')}|depends_on": "used"})
    with pytest.raises(ValueError, match="labels"):
        admission_view(graph, [], labels={f"{nid('b')}|{nid('a')}|depends_on": "used"})


def test_i8_label_with_bad_value_refused():
    graph = make_graph(["a", "b"], [("b", "a", "supports", None)])
    with pytest.raises(ValueError, match="must be 'relied_on' or 'used'"):
        admission_view(graph, [], labels={f"{nid('b')}|{nid('a')}|supports": "admitted"})


def test_i8_label_with_wrong_kind_in_key_refused():
    graph = make_graph(["a", "b"], [("b", "a", "supports", None)])
    with pytest.raises(ValueError, match="labels"):
        admission_view(graph, [], labels={f"{nid('b')}|{nid('a')}|depends_on": "used"})


# ---------------------------------------------------------------- s10.2 exact facet (one test per table row)

def _exact_of(ruling, *, status="ok"):
    b = binding_from_ruling("x", ruling, status=status)
    node = by_id(admission_view(make_graph(["x"], []), [b]), "x")
    return node["exact_leaf"], node["binding"]["exact_reasons"], node


def test_s10_2_row_store_status_not_ok_is_withheld():
    # a ruling that does not teach (threshold-only) so that D7's consistency allows status != ok
    leaf, reasons, node = _exact_of(_real("threshold_only"), status="failed")
    assert (leaf, reasons) == ("withheld", [])
    assert _exact_of(_real("threshold_only"), status="ok")[0] == "admitted"  # status is the cause
    for status in ("invalid", "blocked"):
        assert _exact_of(_real("threshold_only"), status=status)[0] == "withheld"
    assert node["admission"] == "withheld"


def test_s10_2_row_exact_wrong_subject_in_blocking_is_withheld():
    leaf, reasons, _ = _exact_of(_real("wrong_subject"))
    assert (leaf, reasons) == ("withheld", ["F_HYDROGENS_IMPLICIT"])


def test_s10_2_row_blocking_code_outside_catalogue_is_not_recorded():
    for case, code in (("no_expensive", "NO_EXPENSIVE_VALUE"), ("nonfinite_expensive", "NONFINITE_EXPENSIVE_VALUE")):
        leaf, reasons, node = _exact_of(_real(case))
        assert (leaf, reasons) == ("not_recorded", [code]), case
        assert node["admission"] == "withheld"


def test_s10_2_row_exact_wrong_subject_in_unchecked_is_not_recorded():
    """I10: EXACT and WRONG_SUBJECT in unchecked; rule() admits, the exact facet does not."""

    ruling = _real("unevaluable")
    assert ruling["admission"] == "admitted" and ruling["unchecked"] == ["F_HYDROGENS_IMPLICIT"]
    leaf, reasons, node = _exact_of(ruling)
    assert (leaf, reasons) == ("not_recorded", ["F_HYDROGENS_IMPLICIT"])
    assert node["admission"] == "admitted" and node["exact_admission"] == "not_recorded"


def test_s10_2_row_exact_wrong_subject_in_waived_is_admitted_under_waiver():
    leaf, reasons, _ = _exact_of(_real("waived"))
    assert (leaf, reasons) == ("admitted_under_waiver", ["F_PROTONATION_UNDECIDED"])


def test_s10_2_row_otherwise_admitted_clean_and_bounded_and_unverifiable():
    for case in ("clean", "wrong_size", "unverifiable"):
        assert _exact_of(_real(case))[:2] == ("admitted", []), case


def test_i10_threshold_only_withheld_has_exact_leaf_admitted():
    ruling = _real("threshold_only")
    assert ruling["admission"] == "withheld" and ruling["blocking"] == ["F_POSE_LEFT_THE_SITE"]
    leaf, reasons, node = _exact_of(ruling)
    assert (leaf, reasons) == ("admitted", [])
    assert node["admission"] == "withheld" and node["exact_admission"] == "admitted"
    assert node["binding"]["threshold_blocking"] == ["F_POSE_LEFT_THE_SITE"]


def test_s10_2_threshold_codes_are_ignored_in_every_list():
    waivers = WaiverSet((Waiver(
        code="F_POSE_LEFT_THE_SITE", reason="The pose is allowed to leave the site in this campaign.",
        granted_by="test operator", expires=date(2027, 1, 1), granted_at="2026-11-01T00:00:00+00:00"),))
    waived = rule(Measurement("m_tw", -7.0, -8.0, (_obs("F_POSE_LEFT_THE_SITE"),)), waivers,
                  when=I1_WHEN, require_comparator=False).as_dict()
    assert waived["admission"] == "admitted_under_waiver" and waived["waived"] == ["F_POSE_LEFT_THE_SITE"]
    unchecked = rule(Measurement("m_tu", -7.0, -8.0, (_obs("F_POSE_LEFT_THE_SITE", False, False),)),
                     when=I1_WHEN, require_comparator=False).as_dict()
    assert unchecked["unchecked"] == ["F_POSE_LEFT_THE_SITE"]
    assert _exact_of(waived)[:2] == ("admitted", [])
    assert _exact_of(unchecked)[:2] == ("admitted", [])


@pytest.mark.parametrize("consequence", [Consequence.WRONG_SIZE, Consequence.UNVERIFIABLE])
def test_s10_2_exact_but_not_wrong_subject_codes_in_unchecked_are_ignored(consequence):
    """Only EXACT and WRONG_SUBJECT counts: an EXACT code of another consequence does not."""

    code = next(f.code for f in FAULTS if f.exactness is Exactness.EXACT and f.consequence is consequence)
    ruling = rule(Measurement("m_other", -7.0, -8.0, (_obs(code, False, False),)),
                  when=I1_WHEN, require_comparator=False).as_dict()
    assert ruling["unchecked"] == [code] and ruling["admission"] == "admitted"
    assert _exact_of(ruling)[:2] == ("admitted", [])


def test_s10_2_worst_row_wins_and_reasons_name_only_the_worst_rows_codes():
    ruling = _real("wrong_subject")
    ruling["unchecked"] = ["F_STAGE_NEVER_RAN"]
    ruling["waived"] = []
    ruling["blocking"] = ["F_HYDROGENS_IMPLICIT", "NO_EXPENSIVE_VALUE"]
    leaf, reasons, _ = _exact_of(ruling)
    assert (leaf, reasons) == ("withheld", ["F_HYDROGENS_IMPLICIT"])
    ruling["blocking"] = ["NO_EXPENSIVE_VALUE", "NO_CHEAP_VALUE"]
    leaf, reasons, _ = _exact_of(ruling)
    assert (leaf, reasons) == ("not_recorded", ["F_STAGE_NEVER_RAN", "NO_CHEAP_VALUE", "NO_EXPENSIVE_VALUE"])


def test_s10_2_exact_propagation_is_a_min_over_premises_independent_of_admission():
    bindings = [binding_from_ruling("p1", _real("threshold_only")),   # adm withheld, exact admitted
                binding_from_ruling("p2", _real("unevaluable")),      # adm admitted, exact not_recorded
                binding_from_ruling("p3", _real("clean"))]
    j = by_id(admission_view(j_graph(), bindings), "J")
    assert j["admission"] == "withheld" and j["limited_by"] == [nid("p1")]
    assert j["limiting_leaves"] == [nid("p1")]
    assert j["exact_admission"] == "not_recorded"
    assert j["exact_limited_by"] == [nid("p2")] and j["exact_limiting_leaves"] == [nid("p2")]


def test_s10_2_exact_propagation_two_hops_names_the_bottom_exact_leaf():
    graph = make_graph(["J", "m", "p"], [("J", "m", "depends_on", "measured_result"),
                                         ("m", "p", "depends_on", "measured_result")])
    view = admission_view(graph, [binding_from_ruling("m", _real("clean")),
                                  binding_from_ruling("p", _real("wrong_subject"))])
    j = by_id(view, "J")
    assert j["exact_admission"] == "withheld"
    assert j["exact_limited_by"] == [nid("m")] and j["exact_limiting_leaves"] == [nid("p")]


def test_s10_2_exact_facet_is_vacuous_not_admitted_without_bindings_or_premises():
    graph = make_graph(["J", "s"], [("s", "J", "supports", None)])
    view = admission_view(graph, [binding_from_ruling("s", _real("clean"))])
    assert by_id(view, "J")["exact_admission"] == "not_recorded"


def test_s10_2_exact_leaf_follows_the_chain_head():
    old = {**_real("wrong_subject"), "parent_id": "x"}
    new = {**_real("clean"), "parent_id": "x"}
    first = binding_from_ruling("x", old, action="a1")
    second = binding_from_ruling("x", new, supersedes=first["ruling_digest"], action="a2")
    node = by_id(admission_view(make_graph(["x"], []), [first, second]), "x")
    assert node["exact_leaf"] == "admitted" and node["leaf"] == "admitted"
    assert node["history"][0]["admission"] == "withheld"


# ---------------------------------------------------------------- s10.4 / I9 completeness

def _set(key, value):
    return lambda g: g.__setitem__(key, value)


def _receipt(key, value):
    return lambda g: g["scope_receipt"].__setitem__(key, value)


_INCOMPLETE = [
    ("truncated", _set("truncated", True), "truncated"),
    ("truncated_key_absent", lambda g: g.pop("truncated"), "truncated"),
    ("graph_issues", _set("issues", [{"reason": "premise record unavailable"}]), "issues"),
    ("graph_issues_absent", lambda g: g.pop("issues"), "issues"),
    ("receipt_absent", lambda g: g.pop("scope_receipt"), "scope_receipt"),
    ("receipt_schema", _receipt("schema", "etalon-research-graph-scope/0"), "scope_receipt.schema"),
    ("traversal_incomplete", _receipt("traversal_complete", False), "scope_receipt.traversal_complete"),
    ("traversal_not_true", _receipt("traversal_complete", 1), "scope_receipt.traversal_complete"),
    ("reference_coverage_incomplete", _receipt("reference_coverage_complete", False),
     "scope_receipt.reference_coverage_complete"),
    ("boundary_refs", _receipt("deliberate_boundary_refs", [_ref("far")]),
     "scope_receipt.deliberate_boundary_refs"),
    ("boundary_relations", _receipt("boundary_relations", [{"from": "a", "to": "b", "relation": "r"}]),
     "scope_receipt.boundary_relations"),
    ("receipt_issues", _receipt("issues", [{"reason": "x"}]), "scope_receipt.issues"),
]


@pytest.mark.parametrize("change,missing", [(c, m) for _, c, m in _INCOMPLETE],
                         ids=[n for n, _, _ in _INCOMPLETE])
def test_i9_each_failed_completeness_condition_caps_both_facets_and_is_named(change, missing):
    graph = regraph(j_graph(), change)
    bindings = [binding_from_ruling(p, _real("clean", parent=p)) for p in ("p1", "p2", "p3")]
    view = admission_view(graph, bindings)
    assert view["graph_completeness"] == {"asserted": False, "missing": [missing]}
    for node in view["nodes"]:
        assert node["admission"] == "not_recorded", node["node_id"]
        assert node["exact_admission"] == "not_recorded", node["node_id"]
        assert "graph_completeness_not_asserted" in node["reasons"]
    # leaf values are still reported
    assert by_id(view, "p1")["leaf"] == "admitted" and by_id(view, "p1")["exact_leaf"] == "admitted"


def test_i9_complete_graph_is_not_capped_control():
    bindings = [binding_from_ruling(p, _real("clean", parent=p)) for p in ("p1", "p2", "p3")]
    view = admission_view(j_graph(), bindings)
    assert view["graph_completeness"] == {"asserted": True, "missing": []}
    assert by_id(view, "J")["admission"] == by_id(view, "J")["exact_admission"] == "admitted"
    assert all("graph_completeness_not_asserted" not in n["reasons"] for n in view["nodes"])


def test_i9_truncated_graph_is_capped_not_refused():
    graph = make_graph(["a", "b"], [("a", "b", "depends_on", "measured_result")], truncated=True)
    view = admission_view(graph, [binding("b", "admitted")])
    assert by_id(view, "a")["admission"] == "not_recorded"
    assert view["graph_completeness"]["missing"] == ["truncated"]


def test_i9_cap_lowers_only_and_a_withheld_node_stays_withheld_on_both_facets():
    graph = regraph(j_graph(), _receipt("traversal_complete", False))
    view = admission_view(graph, [binding_from_ruling("p1", _real("wrong_subject"))])
    p1 = by_id(view, "p1")
    assert p1["admission"] == "withheld" and p1["exact_admission"] == "withheld"
    assert by_id(view, "J")["admission"] == "withheld"


def test_i9_several_failed_conditions_are_all_named_in_order():
    graph = regraph(j_graph(), lambda g: (g.__setitem__("truncated", True),
                                          g["scope_receipt"].__setitem__("issues", ["x"])))
    view = admission_view(graph, [])
    assert view["graph_completeness"]["missing"] == ["truncated", "scope_receipt.issues"]


def test_i9_unscoped_graph_without_a_scope_receipt_never_asserts():
    view = admission_view(make_graph(["a"], [], receipt=None), [binding("a", "admitted")])
    assert view["graph_completeness"] == {"asserted": False, "missing": ["scope_receipt"]}
    assert by_id(view, "a")["admission"] == "not_recorded"


# ---------------------------------------------------------------- s10.6 / I4 comparison

def _view(*bindings, graph=None):
    return admission_view(graph or j_graph(), list(bindings))


def test_s10_6_compare_refuses_view_version_mismatch():
    a = _view(binding("p1", "admitted"))
    b = reid({**a, "view_version": "etalon-admission-view/1"})
    with pytest.raises(AdmissionViewMismatch, match="view_version"):
        compare_views(a, b)


def test_s10_6_compare_refuses_catalogue_digest_mismatch():
    a = _view(binding("p1", "admitted"))
    b = reid({**a, "catalogue_digest": "0" * 64})
    with pytest.raises(AdmissionViewMismatch, match="catalogue_digest"):
        compare_views(a, b)


def test_s10_6_compare_refuses_catalogue_coverage_mismatch():
    a = _view(binding("p1", "admitted"))
    b = reid({**a, "catalogue_coverage": {"blocking_surface_complete": True,
                                          "uncatalogued_blocking_codes": []}})
    with pytest.raises(AdmissionViewMismatch, match="catalogue_coverage"):
        compare_views(a, b)


def test_s10_6_compare_refuses_missing_graph_view_id_on_either_side_or_both():
    sealed = _view(binding("p1", "admitted"))
    bare_graph = make_graph(["J", "p1", "p2", "p3"],
                            [("J", p, "depends_on", "measured_result") for p in ("p1", "p2", "p3")],
                            view_id=False)
    bare = admission_view(bare_graph, [binding("p1", "admitted")])
    assert bare["graph_view_id"] is None
    for x, y in ((sealed, bare), (bare, sealed), (bare, bare)):
        with pytest.raises(AdmissionViewMismatch, match="graph_view_id"):
            compare_views(x, y)


def test_s10_6_compare_refuses_differing_graph_view_id():
    a = _view(binding("p1", "admitted"))
    other = regraph(j_graph(), _set("task_id", "t1"))  # same content, re-sealed: same id
    assert compare_views(a, admission_view(other, [binding("p1", "admitted")]))["only_in_a"] == []
    changed = regraph(j_graph(), lambda g: g["edges"].pop())
    b = admission_view(changed, [binding("p1", "admitted")])
    assert a["graph_view_id"] != b["graph_view_id"]
    with pytest.raises(AdmissionViewMismatch, match="graph_view_id differs"):
        compare_views(a, b)


def test_s10_6_compare_refuses_a_view_edited_after_it_was_computed():
    a = _view(binding("p1", "admitted"))
    b = copy.deepcopy(a)
    b["nodes"][0]["admission"] = "admitted"  # edited node value, view_id not recomputed
    b["nodes"][0]["exact_admission"] = "admitted"
    assert b["nodes"][0]["admission"] != a["nodes"][0]["admission"]
    for x, y in ((a, b), (b, a)):
        with pytest.raises(AdmissionViewMismatch, match="view_id"):
            compare_views(x, y)


def test_s10_6_untouched_views_compare():
    a = _view(binding("p1", "admitted"))
    assert compare_views(a, copy.deepcopy(a))["only_in_a"] == []


_R = {name: (lambda n=name: _real(n)) for name in
      ("clean", "threshold_only", "wrong_subject", "unevaluable")}


@pytest.mark.parametrize("before,after,adm,exact", [
    ("threshold_only", "clean", "raised", "unchanged"),
    ("clean", "threshold_only", "lowered", "unchanged"),
    ("wrong_subject", "clean", "raised", "raised"),
    ("clean", "wrong_subject", "lowered", "lowered"),
    ("clean", "unevaluable", "unchanged", "lowered"),
    ("unevaluable", "clean", "unchanged", "raised"),
    ("clean", "clean", "unchanged", "unchanged"),
])
def test_s10_6_direction_for_both_facets(before, after, adm, exact):
    graph = make_graph(["x"], [])
    a = admission_view(graph, [binding_from_ruling("x", _R[before](), action="a1")])
    b = admission_view(graph, [binding_from_ruling("x", _R[after](), action="a2")])
    result = compare_views(a, b)["nodes"][nid("x")]
    assert result["admission"]["direction"] == adm
    assert result["exact_admission"]["direction"] == exact
    for facet in ("admission", "exact_admission"):
        assert result[facet]["moved"] == (result[facet]["direction"] != "unchanged")
        assert result[facet]["a"] == a["nodes"][0][facet] and result[facet]["b"] == b["nodes"][0][facet]


def test_s10_6_direction_follows_the_section_4_order_including_not_recorded():
    graph = j_graph()
    nothing = admission_view(graph, [])  # J not_recorded
    withheld = admission_view(graph, [binding("p1", "withheld"), binding("p2", "admitted"),
                                      binding("p3", "admitted")])
    waiver = admission_view(graph, [binding(p, "admitted_under_waiver") for p in ("p1", "p2", "p3")])
    assert compare_views(nothing, withheld)["nodes"][nid("J")]["admission"]["direction"] == "lowered"
    assert compare_views(withheld, nothing)["nodes"][nid("J")]["admission"]["direction"] == "raised"
    assert compare_views(nothing, waiver)["nodes"][nid("J")]["admission"]["direction"] == "raised"


def test_compare_reports_one_sided_nodes():
    a = _view(binding("p1", "admitted"))
    smaller = copy.deepcopy(a)
    smaller["nodes"] = [n for n in smaller["nodes"] if n["node_id"] != nid("p3")]
    b = reid(smaller)
    result = compare_views(a, b)
    assert result["only_in_a"] == [nid("p3")] and result["only_in_b"] == []
    assert compare_views(b, a)["only_in_b"] == [nid("p3")]


# ---------------------------------------------------------------- view identity

def test_view_id_is_digest_of_rest_and_deterministic():
    graph = j_graph()
    bs = [binding("p1", "admitted")]
    v1, v2 = admission_view(graph, bs), admission_view(graph, bs)
    assert v1 == v2
    rest = {k: v for k, v in v1.items() if k != "view_id"}
    assert v1["view_id"] == "admission-view-" + digest(rest)
    assert canonical(v1)


# ---------------------------------------------------------------- the regime membrane (v3)
#
# The membrane is the half of the two-regime design that edge classification was
# missing: `assessment_role` reached journal.py, composition.py, graph_memory.py and
# schema.py and never reached a premise edge, so a record produced under
# `diagnostic` -- no predeclaration, already-seen bytes, cheap proxies, no comparator
# pairing -- propagated admission exactly as a fully predeclared one did.
#
# Each pair below is the demonstration by construction. The two graphs differ in one
# projected field and in nothing else; the first propagates and the second does not.

#: What research/graph_memory._project_node writes for an etalon-method-evaluation/1
#: record. Only the two regime fields matter here; the rest is carried for shape.
def _evaluation_block(role, basis=...):
    block = {"subjects": ["mv-1"], "comparators": ["mv-0"], "assessment_role": role,
             "conclusion": "fixture", "scope": "fixture"}
    if basis is not ...:
        block["assessment_role_basis"] = basis
    return block


def _membrane_graph(role, basis=..., relation="evaluation_result"):
    """J relies on p1 by a declared relied-class relation; p1 declares a regime.

    `evaluation_result` is the real reachable case: research/method_links.py emits it
    from an `etalon-research-step/1` evaluation step to the `etalon-method-evaluation/1`
    record it bound, and that record is the only projection carrying a regime.
    """

    return make_graph(["J", "p1"], [("J", "p1", "depends_on", relation)],
                      regimes={"p1": _evaluation_block(role, basis)})


def _edge_of(view, owner, premise, kind="depends_on"):
    return next(e for e in view["edges"]
                if (e["owner"], e["premise"], e["kind"]) == (nid(owner), nid(premise), kind))


def test_membrane_independent_validation_premise_still_propagates():
    """The before state. An explicitly declared independent validation is a premise."""

    view = admission_view(_membrane_graph("independent_validation", "explicitly_declared"),
                          [binding("p1", "admitted")])
    edge = _edge_of(view, "J", "p1")
    assert (edge["premise_class"], edge["class_basis"]) == ("relied_on", "declared_relation")
    assert edge["premise_regime"] == "independent_validation"
    assert by_id(view, "J")["admission"] == "admitted"
    assert by_id(view, "J")["premises"] == [nid("p1")]
    assert view["membrane"]["degraded_edges"] == 0


def test_membrane_diagnostic_premise_degrades_relied_on_to_used():
    """The after state. One projected field differs; the premise is gone."""

    view = admission_view(_membrane_graph("diagnostic", "explicitly_declared"),
                          [binding("p1", "admitted")])
    edge = _edge_of(view, "J", "p1")
    assert (edge["premise_class"], edge["class_basis"]) == ("used", "regime_cannot_settle")
    assert edge["premise_regime"] == "diagnostic"
    # p1's own leaf is still reported as admitted: the membrane refuses reliance, it
    # does not reach back and change what the ruling said.
    assert by_id(view, "p1")["leaf"] == "admitted" and by_id(view, "p1")["admission"] == "admitted"
    assert by_id(view, "J")["premises"] == [] and by_id(view, "J")["admission"] == "not_recorded"
    assert "premise_regime_cannot_carry_reliance" in by_id(view, "J")["reasons"]
    assert by_id(view, "J")["regime_refused_premises"] == [nid("p1")]


def test_membrane_regime_unknown_premise_is_used_never_relied_on():
    """A record that predates the required argument carries no basis at all.

    Nothing is written to it and no admission is backfilled (CLAUDE.md constraint 4):
    reliance is declined, which is the conservative direction admissible.py argues for.
    """

    view = admission_view(_membrane_graph("independent_validation"),  # basis key absent
                          [binding("p1", "admitted")])
    edge = _edge_of(view, "J", "p1")
    assert (edge["premise_class"], edge["class_basis"]) == ("used", "regime_not_declared")
    assert edge["premise_regime"] == "regime_unknown"
    assert by_id(view, "p1")["assessment_regime"] == "regime_unknown"
    assert by_id(view, "J")["admission"] == "not_recorded"


def test_membrane_an_explicitly_null_basis_is_also_regime_unknown():
    view = admission_view(_membrane_graph("independent_validation", None),
                          [binding("p1", "admitted")])
    assert _edge_of(view, "J", "p1")["class_basis"] == "regime_not_declared"


def test_membrane_defaulted_diagnostic_is_the_same_regime_as_a_chosen_one():
    """A role reached by omission and one chosen are one regime, and it cannot settle.

    So the migration needs no case analysis: the record says `defaulted_deprecated`
    for the reader's sake, and propagation does not depend on it.
    """

    chosen = admission_view(_membrane_graph("diagnostic", "explicitly_declared"),
                            [binding("p1", "admitted")])
    omitted = admission_view(_membrane_graph("diagnostic", "defaulted_deprecated"),
                             [binding("p1", "admitted")])
    for view in (chosen, omitted):
        assert _edge_of(view, "J", "p1")["class_basis"] == "regime_cannot_settle"
        assert by_id(view, "J")["admission"] == "not_recorded"


@pytest.mark.parametrize("relation", sorted(av._RELIED_BY_RELATION))
def test_membrane_covers_every_declared_relied_class_relation(relation):
    permitted = admission_view(
        _membrane_graph("independent_validation", "explicitly_declared", relation=relation),
        [binding("p1", "admitted")])
    refused = admission_view(_membrane_graph("diagnostic", "explicitly_declared", relation=relation),
                             [binding("p1", "admitted")])
    assert by_id(permitted, "J")["admission"] == "admitted"
    assert by_id(refused, "J")["admission"] == "not_recorded"


def test_membrane_a_human_label_cannot_pierce_it():
    """A label says a person read the edge as reliance. The membrane says the record
    on the far end was never held to a standard that could carry it."""

    graph = make_graph(["J", "p1"], [("p1", "J", "supports", None)],
                       regimes={"p1": _evaluation_block("diagnostic", "explicitly_declared")})
    labels = {f"{nid('p1')}|{nid('J')}|supports": "relied_on"}
    view = admission_view(graph, [binding("p1", "admitted")], labels=labels)
    edge = _edge_of(view, "J", "p1", kind="supports")
    assert (edge["premise_class"], edge["class_basis"]) == ("used", "regime_cannot_settle")
    assert by_id(view, "J")["admission"] == "not_recorded"
    # The label was still consumed, so it is not reported as targeting no edge.
    assert by_id(view, "J")["unlabelled_candidate_premises"] == []


def test_membrane_label_to_an_independent_validation_premise_still_promotes():
    graph = make_graph(["J", "p1"], [("p1", "J", "supports", None)],
                       regimes={"p1": _evaluation_block("independent_validation",
                                                        "explicitly_declared")})
    labels = {f"{nid('p1')}|{nid('J')}|supports": "relied_on"}
    view = admission_view(graph, [binding("p1", "admitted")], labels=labels)
    edge = _edge_of(view, "J", "p1", kind="supports")
    assert (edge["premise_class"], edge["class_basis"]) == ("relied_on", "human_label")
    assert by_id(view, "J")["admission"] == "admitted"


def test_membrane_leaves_a_premise_whose_schema_has_no_regime_alone():
    """The membrane is about the regime of an assessment, not about every record.

    An artifact or a receipt is in neither regime. Treating it as regime-unknown
    would cap every derived value in the repository and say nothing new.
    """

    view = admission_view(j_graph(), [binding("p1", "admitted")])
    for premise in ("p1", "p2", "p3"):
        edge = _edge_of(view, "J", premise)
        assert (edge["premise_class"], edge["premise_regime"]) == ("relied_on", "not_applicable")
        assert by_id(view, premise)["assessment_regime"] == "not_applicable"
    assert view["membrane"]["degraded_edges"] == 0
    assert by_id(view, "J")["regime_refused_premises"] == []


def test_membrane_ignores_a_block_that_is_not_an_evaluation_projection():
    """A node carrying something other than the projection block is not a regime claim."""

    for block in ({}, {"conclusion": "fixture"}, "diagnostic", None, []):
        graph = make_graph(["J", "p1"], [("J", "p1", "depends_on", "measured_result")],
                           regimes={"p1": block})
        view = admission_view(graph, [binding("p1", "admitted")])
        assert _edge_of(view, "J", "p1")["premise_class"] == "relied_on"
        assert by_id(view, "J")["admission"] == "admitted"


def test_membrane_degrades_the_exact_facet_by_the_same_rule():
    view = admission_view(_membrane_graph("diagnostic", "explicitly_declared"),
                          [binding("p1", "admitted")])
    assert by_id(view, "J")["exact_admission"] == "not_recorded"
    assert by_id(view, "p1")["exact_leaf"] == "admitted"
    assert by_id(view, "J")["exact_limited_by"] == [] and by_id(view, "J")["exact_limiting_leaves"] == [nid("J")]


def test_membrane_counts_carry_their_denominator():
    """Mechanism evidence, not a rate: how many premises the regime refused, over how
    many relied-class edges there were. A rate over a handful of edges says less."""

    graph = make_graph(
        ["J", "ok", "diag", "legacy", "plain"],
        [("J", n, "depends_on", "evaluation_result") for n in ("ok", "diag", "legacy", "plain")],
        regimes={"ok": _evaluation_block("independent_validation", "explicitly_declared"),
                 "diag": _evaluation_block("diagnostic", "explicitly_declared"),
                 "legacy": _evaluation_block("independent_validation")},
    )
    view = admission_view(graph, [binding(n, "admitted") for n in ("ok", "diag", "legacy", "plain")])
    assert view["membrane"] == {
        "basis": "assessment_regime_of_the_premise_record",
        "relied_class_edges": 4, "degraded_edges": 2,
        "by_class_basis": {"lesson_cannot_settle": 0, "regime_cannot_settle": 1,
                           "regime_not_declared": 1},
        "regime_source": "projected_record_only_never_inferred",
        # The record side, over its own denominator. This fixture happens to cover all three
        # answers and the exclusion: `ok` and `diag` declared their basis, `legacy` predates
        # the field, and `plain` carries no assessment role so it is not in the denominator.
        "records_by_role_basis": {
            "records_carrying_an_assessment_role": 3,
            "by_basis": {"explicitly_declared": 2, "defaulted_deprecated": 0,
                         "not_recorded": 1},
            "basis": ("the assessment_role_basis each record carries; declared by its writer "
                      "at dispatch and never inferred here"),
            "not_recorded_means": ("the record predates assessment_role_basis, which is a "
                                   "different fact from an omission that was recorded as one"),
        },
    }
    assert by_id(view, "J")["premises"] == sorted([nid("ok"), nid("plain")])
    assert by_id(view, "J")["regime_refused_premises"] == sorted([nid("diag"), nid("legacy")])
    # Two admitted premises survive, so J is still admitted: the membrane removed
    # premises, it did not withhold.
    assert by_id(view, "J")["admission"] == "admitted"


def test_membrane_does_not_count_a_used_edge_in_its_denominator():
    graph = make_graph(["J", "p1"], [("J", "p1", "depends_on", "evaluated_candidate")],
                       regimes={"p1": _evaluation_block("diagnostic", "explicitly_declared")})
    view = admission_view(graph, [binding("p1", "admitted")])
    edge = _edge_of(view, "J", "p1")
    assert (edge["premise_class"], edge["class_basis"]) == ("used", "declared_relation")
    assert view["membrane"]["relied_class_edges"] == 0


@pytest.mark.parametrize("admission", ["withheld", "admitted_under_waiver", "admitted"])
def test_membrane_never_lifts_a_derived_value_above_not_recorded(admission):
    """I13. Refusing a premise never derives a value better than `not_recorded`.

    This is the invariant that actually holds, and it is weaker than "can only
    lower" on purpose. Section 10.3 already records that the unidirectional claim
    was refuted for the `supports` default; the same thing is true here, and the
    next test pins the one case.
    """

    bs = [binding("p1", admission)]
    before = admission_view(_membrane_graph("independent_validation", "explicitly_declared"), bs)
    after = admission_view(_membrane_graph("diagnostic", "explicitly_declared"), bs)
    for facet in ("admission", "exact_admission"):
        assert av._RANK[by_id(after, "J")[facet]] <= max(
            av._RANK[by_id(before, "J")[facet]], av._RANK["not_recorded"])
        assert av._RANK[by_id(after, "J")[facet]] <= av._RANK["not_recorded"]


def test_membrane_moves_a_withheld_owner_up_to_not_recorded_and_that_is_still_a_loss():
    """The one direction in which the membrane moves a value up the section 4 order.

    A node whose sole premise was withheld was `withheld`; once the membrane
    refuses that premise the node has no premise at all, so it is `not_recorded`,
    which section 4 ranks above `withheld`. The view cannot honestly keep the
    `withheld` value: it would be asserting a withholding on the strength of a
    premise it has just declined to rely on. Under D4 of
    ADMISSION_PROPAGATION_DECISIONS.md both values are losses -- `not_recorded`
    is in the denominator and not in the numerator -- so no reward is gained by
    turning this knob, which is the same answer D4 gave for an omitted binding.
    """

    bs = [binding("p1", "withheld")]
    before = admission_view(_membrane_graph("independent_validation", "explicitly_declared"), bs)
    after = admission_view(_membrane_graph("diagnostic", "explicitly_declared"), bs)
    assert by_id(before, "J")["admission"] == "withheld"
    assert by_id(after, "J")["admission"] == "not_recorded"
    assert av._RANK["withheld"] < av._RANK["not_recorded"]
    # Neither value is an admission, which is what makes the move unexploitable.
    assert by_id(after, "J")["admission"] not in {"admitted", "admitted_under_waiver"}
    assert by_id(before, "J")["admission"] not in {"admitted", "admitted_under_waiver"}


def test_membrane_is_read_only_and_the_graph_is_unchanged():
    """I2 again, over the input the membrane actually reads."""

    graph = _membrane_graph("diagnostic", "explicitly_declared")
    pinned = copy.deepcopy(graph)
    admission_view(graph, [binding("p1", "admitted")])
    assert graph == pinned


def test_membrane_classify_is_pure_in_the_regime_argument():
    """A derivation, not a judgement: same edge and same regime, same answer twice."""

    edge = {"from": nid("J"), "to": nid("p1"), "kind": "depends_on", "relation": "measured_result"}
    for role, basis, expected in (
        ("independent_validation", "explicitly_declared", ("relied_on", "declared_relation")),
        ("diagnostic", "explicitly_declared", ("used", "regime_cannot_settle")),
        ("independent_validation", None, ("used", "regime_not_declared")),
    ):
        from etalon.research.assessment_regime import regime
        out = [av._classify(edge, regime(role, basis))[:2] for _ in range(2)]
        assert out == [expected, expected]


def test_i17_two_relied_edges_on_one_pair_still_resolve_to_used():
    """I17 (ADMISSION_PROPAGATION.md §11.2, §11.6): the membrane applies AFTER §4's
    per-pair resolution in which `relied_on` wins.

    Applied before, a second relied-class edge between the same owner and the same
    premise silently restores what the membrane removed -- the optional-guard shape
    ADR 0006 is named for. Every other membrane fixture carries exactly one edge, so
    this ordering was previously held only by reading `relied_pairs` in the source.
    """

    graph = make_graph(
        ["J", "p1"],
        [("J", "p1", "depends_on", "evaluation_result"),
         ("J", "p1", "depends_on", "measured_result")],
        regimes={"p1": _evaluation_block("diagnostic", "explicitly_declared")})
    view = admission_view(graph, [binding("p1", "admitted")])

    pair = [e for e in view["edges"] if e["owner"] == nid("J") and e["premise"] == nid("p1")]
    assert len(pair) == 2, "the fixture must put two relied-class edges on one pair"
    for edge in pair:
        assert (edge["premise_class"], edge["class_basis"]) == ("used", "regime_cannot_settle")

    # The pair did not survive as a premise by way of the second edge.
    assert by_id(view, "J")["premises"] == []
    assert by_id(view, "J")["admission"] == "not_recorded"
    assert by_id(view, "J")["regime_refused_premises"] == [nid("p1")]
    assert view["membrane"]["degraded_edges"] == 2
    assert view["membrane"]["by_class_basis"]["regime_cannot_settle"] == 2


def test_i17_two_relied_edges_on_one_pair_still_propagate_when_the_regime_permits():
    """The same fixture with a permitting regime: both edges stay relied_on and carry."""

    graph = make_graph(
        ["J", "p1"],
        [("J", "p1", "depends_on", "evaluation_result"),
         ("J", "p1", "depends_on", "measured_result")],
        regimes={"p1": _evaluation_block("independent_validation", "explicitly_declared")})
    view = admission_view(graph, [binding("p1", "admitted")])

    pair = [e for e in view["edges"] if e["owner"] == nid("J") and e["premise"] == nid("p1")]
    assert {e["premise_class"] for e in pair} == {"relied_on"}
    assert by_id(view, "J")["premises"] == [nid("p1")]
    assert by_id(view, "J")["admission"] == "admitted"
    assert view["membrane"]["degraded_edges"] == 0


def test_an_omission_that_was_recorded_is_counted_apart_from_a_record_that_predates_the_field():
    """Why the decision never to refuse an omitted regime is honest only with this count.

    `ASSESSMENT_REGIMES.md` §2 settled that an omitted `assessment_role` is warned about and
    recorded, never refused, on the ground that `assessment_role_basis` makes the omission
    distinguishable afterwards. That holds only while somebody can see how large the
    population is: a set nothing reports grows unwatched, and "it is countable" is not a
    count. So `defaulted_deprecated` is reported beside `explicitly_declared`, and both apart
    from `not_recorded` -- a record written before the field existed, which is every real one
    measured so far and is a different fact from an omission the writer was warned about.
    """

    defaulted = admission_view(_membrane_graph("diagnostic", "defaulted_deprecated"),
                               [binding("p1", "admitted")])["membrane"]["records_by_role_basis"]
    assert defaulted["by_basis"]["defaulted_deprecated"] == 1
    assert defaulted["by_basis"]["not_recorded"] == 0

    predating = admission_view(_membrane_graph("diagnostic", None),
                               [binding("p1", "admitted")])["membrane"]["records_by_role_basis"]
    assert predating["by_basis"]["not_recorded"] == 1
    assert predating["by_basis"]["defaulted_deprecated"] == 0

    # Counts over a stated denominator, never a share of the subset that answered.
    for census in (defaulted, predating):
        assert census["records_carrying_an_assessment_role"] == sum(census["by_basis"].values())


# -- v4: a lesson is not an assessment ---------------------------------------------------------


def _lesson_block(outcome="adopt"):
    """The `experience` projection block, as `_project_node` writes it for a lesson.

    Verbatim rather than a shorthand: the membrane keys on this block's presence, so a test
    that built it from a helper would stop showing what the behaviour depends on.
    """

    return {"outcome": outcome, "invalid_when": "the panel changes",
            "capability_id": "cap-1", "conditions": [], "scope": "fixture",
            "support_refs": ["r1"], "counter_refs": [], "supersedes": None,
            "lesson": "prefer the cheaper proxy first"}


def test_i21_a_lesson_cannot_be_a_premise_and_no_label_restores_it():
    """I21. The route a loose internal judge would otherwise take into the premise set.

    `etalon-method-experience/1` is a legal premise ref, and two edges reached `relied_on`:
    a decision step's `basis_refs` (relation `selection_basis`, in `_RELIED_BY_RELATION`),
    and a `supports` edge that `_declared_class` marks labelable. Both are checked here,
    and the label clause is the one that was false before v4 -- §11's prose claimed no label
    could pierce the membrane while a lesson sat outside its scope entirely.
    """

    graph = make_graph(["J", "lesson"], [("J", "lesson", "depends_on", "selection_basis")],
                       experiences={"lesson": _lesson_block()})
    view = admission_view(graph, [binding("lesson", "admitted")])
    edge = view["edges"][0]
    assert (edge["premise_class"], edge["class_basis"]) == ("used", "lesson_cannot_settle")
    assert by_id(view, "J")["regime_refused_premises"] == [nid("lesson")]
    assert view["membrane"]["by_class_basis"]["lesson_cannot_settle"] == 1

    # The labelable route, with the label applied: `_classify` labels first and then reads
    # the regime, so the degrade still wins.
    # A `supports` edge runs premise -> claim, the opposite of `depends_on`, so the lesson
    # is the `from` node here. Writing it the other way round made the probe assert about an
    # edge whose premise was the conclusion, which is how the first version of this test
    # passed its own intent by accident.
    labelled = make_graph(["lesson", "J"], [("lesson", "J", "supports", None)],
                          experiences={"lesson": _lesson_block()})
    out = admission_view(labelled, [binding("lesson", "admitted")],
                         labels={f"{nid('lesson')}|{nid('J')}|supports": "relied_on"})
    row = out["edges"][0]
    assert (row["premise_class"], row["class_basis"]) == ("used", "lesson_cannot_settle"), (
        "a human label restored reliance on a lesson; the membrane's own promise that no "
        "label can make a record have been held to a standard is what this holds")


def test_i21_a_lesson_declares_not_an_assessment_rather_than_an_unknown_regime():
    """The distinction v4 adds, and why it is not `NOT_APPLICABLE` or `regime_unknown`.

    `not_applicable` leaves derived values alone (an artifact, a receipt). `regime_unknown`
    says an assessment did not say which regime it was produced under. A lesson is neither:
    it is a record type with no freeze and no comparator, so it has no regime to declare and
    no reliance to permit. Collapsing it into either of the other two loses that.
    """

    from etalon.research.assessment_regime import (
        LESSON_CANNOT_SETTLE, NOT_AN_ASSESSMENT, NOT_APPLICABLE, REGIME_UNKNOWN,
        regime_of_node)

    block = regime_of_node({"node_id": "n", "experience": _lesson_block()})
    assert block["regime"] == NOT_AN_ASSESSMENT
    assert block["permits_reliance"] is False
    assert block["degrade_basis"] == LESSON_CANNOT_SETTLE
    assert NOT_AN_ASSESSMENT not in (NOT_APPLICABLE, REGIME_UNKNOWN)
    # A node the membrane has no business with still gets None, unchanged from v3.
    assert regime_of_node({"node_id": "n"}) is None

    graph = make_graph(["J", "lesson"], [("J", "lesson", "depends_on", "selection_basis")],
                       experiences={"lesson": _lesson_block()})
    view = admission_view(graph, [binding("lesson", "admitted")])
    assert by_id(view, "lesson")["assessment_regime"] == NOT_AN_ASSESSMENT


def test_i22_a_lesson_stays_out_of_the_assessment_role_census():
    """I22. The census counts records carrying an assessment role; a lesson carries none.

    Counting its absent `role_basis` as `not_recorded` would pad the one figure that census
    exists to keep honest -- the figure the decision never to refuse an omitted regime rests
    on. A number quietly inflated by records that were never supposed to answer is worse
    than no number.
    """

    graph = make_graph(
        ["J", "lesson", "evaluated"],
        [("J", "lesson", "depends_on", "selection_basis"),
         ("J", "evaluated", "depends_on", "evaluation_result")],
        experiences={"lesson": _lesson_block()},
        regimes={"evaluated": _evaluation_block("diagnostic", "explicitly_declared")},
    )
    census = admission_view(graph, [binding(n, "admitted") for n in ("lesson", "evaluated")]
                            )["membrane"]["records_by_role_basis"]
    assert census["records_carrying_an_assessment_role"] == 1, (
        "the lesson entered the denominator of a census about assessment roles")
    assert census["by_basis"] == {"explicitly_declared": 1, "defaulted_deprecated": 0,
                                  "not_recorded": 0}
