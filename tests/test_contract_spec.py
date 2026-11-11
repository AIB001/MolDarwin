"""The acceptance criterion is readable before the work, and it is not a verdict.

`research/contract_spec.py` publishes the specification half of an evaluation contract.
The line it holds -- publish the specification, never the oracle -- is enforced by what the
module does not import, so these tests pin both halves: that the rules a host needs are
present, and that nothing here can produce a judgement.

The motivating measurement is external and is cited, not reproduced: on SMDD-Bench an agent
computed the right quantity, saw it matched 3 of the reference's 6 features twice, and
submitted, because no threshold was stated; two further submissions were already unable to
pass at hand-in because the metric punished extra features and nothing said so.
"""
from __future__ import annotations

import inspect

import pytest

from etalon.research import contract_spec
from etalon.research.contract_spec import specification
from etalon.research.evaluation_contract import _OPS, STATUSES, _aggregate


def _ref(source_id, fill):
    """A valid `etalon-evidence-ref/1`: source_id, record_id and a 64-hex record_digest."""

    return {"schema": "etalon-evidence-ref/1", "source_id": source_id,
            "record_id": f"{source_id}-1", "record_digest": fill * 64}


def _contract(**over):
    """A minimal valid contract. Fields mirror `build_evaluation_contract`'s signature."""

    from etalon.research.evaluation_contract import build_evaluation_contract

    base = dict(
        task_id="t-1", scope="fixture",
        conditions={"receptor": "fixed"},
        protocol_ref=_ref("protocol", "a"),
        initial_conditions_ref=_ref("conditions", "b"),
        inputs=[{"name": "res", "ref": _ref("results", "c"), "kind": "result"}],
        metrics=[{"name": "overlap", "family": "regression",
                  "measure": {"operation": "value", "left": {"input": "res", "pointer": "/x"},
                              "right": None},
                  "operator": "gt", "threshold": 0.75, "threshold_evidence": "convention",
                  "unit": "fraction",
                  "denominator": "candidates", "denominator_selector": {"input": "res", "pointer": "/n"},
                  "missing_policy": "insufficient"}],
        comparability=[{"check_id": "same-receptor",
                        "selector": {"input": "res", "pointer": "/receptor"},
                        "expected": True}],
        required_checks=[{"check_id": "complete", "selector": {"input": "res", "pointer": "/ok"},
                          "expected": True}],
        provenance={"mode": "retrospective", "note": "fixture", "basis_refs": []},
    )
    base.update(over)
    return build_evaluation_contract(**base)


def test_the_criterion_names_the_bar_and_what_it_punishes():
    """The clause whose absence cost two SMDD submissions their run."""

    spec = specification(_contract())
    metric = spec["metrics"][0]
    assert (metric["operator"], metric["threshold"]) == ("gt", 0.75)
    assert metric["punishes"] == "a value at or below the threshold"
    assert metric["measure"]["operation"] == "value", "the bar without the quantity is half a criterion"
    assert metric["missing_policy"] == "insufficient"
    assert spec["aggregation"]["consequence"].startswith("a passing cost metric never erases")


def test_the_criterion_says_where_the_threshold_came_from():
    """The other half of a bar: a host cannot weigh `> 0.75` without knowing its origin.

    Before this round the contract schema carried no provenance field while the
    `evaluation_plan` step required one, so the number that *decided* the verdict was the
    one with no recorded origin. That inconsistency resolved toward the stricter side,
    because the alternative lets a record look better founded than it is.
    """

    metric = specification(_contract())["metrics"][0]
    assert metric["threshold_evidence"] == "convention"
    assert "threshold_evidence_note" not in metric, (
        "a validated contract records its provenance, so the not_recorded note is wrong here")


def test_a_contract_that_skipped_validation_says_not_recorded_rather_than_guessing():
    """`validate=False` is the only way to reach the sentinel; it must not invent a tag."""

    from etalon.research.evaluation_contract import THRESHOLD_EVIDENCE_NOT_RECORDED

    bare = _contract()
    bare["metrics"] = [{k: v for k, v in m.items() if k != "threshold_evidence"}
                       for m in bare["metrics"]]
    metric = specification(bare, validate=False)["metrics"][0]
    assert metric["threshold_evidence"] == THRESHOLD_EVIDENCE_NOT_RECORDED
    assert "convention presented as a measurement" in metric["threshold_evidence_note"]
    assert "cannot reach this state" in metric["threshold_evidence_note"]


def test_not_recorded_is_an_absence_and_never_a_fifth_kind_of_evidence():
    """Mirrors `_aggregate`'s `not_declared`, which is deliberately not in `STATUSES`.

    If the sentinel were a member of the vocabulary, "nobody said" would sit in the same
    column as "somebody measured it" at every site that validates against the tuple.
    """

    from etalon.research.evaluation_contract import (
        PROVENANCE, THRESHOLD_EVIDENCE_NOT_RECORDED)

    assert THRESHOLD_EVIDENCE_NOT_RECORDED not in PROVENANCE
    assert _aggregate([]) not in STATUSES, "the pattern this follows"


def test_the_contract_schema_requires_a_provenance_tag_from_the_one_vocabulary():
    from etalon.research.evaluation_contract import (
        PROVENANCE, THRESHOLD_EVIDENCE_NOT_RECORDED, validate_evaluation_contract)
    from etalon.runtime.files import EvidenceError

    for bad in (None, "i_measured_it", "", THRESHOLD_EVIDENCE_NOT_RECORDED):
        contract = _contract()
        contract["metrics"][0]["threshold_evidence"] = bad
        with pytest.raises(EvidenceError):
            validate_evaluation_contract(contract)
    contract = _contract()
    del contract["metrics"][0]["threshold_evidence"]
    with pytest.raises(EvidenceError):
        validate_evaluation_contract(contract)
    for good in PROVENANCE:
        contract = _contract()
        contract["metrics"][0]["threshold_evidence"] = good
        assert validate_evaluation_contract(contract)["metrics"][0]["threshold_evidence"] == good


def test_relabelling_a_threshold_s_provenance_is_a_new_rule_identity():
    """Why provenance is inside the rules digest rather than beside it.

    `evaluation_rules_digest` strips the observed inputs so one rule keeps its identity
    while the evidence under it changes. Provenance is not evidence under the rule; it is
    part of what the rule claims. If it sat outside the digest, a bar could be relabelled
    `convention` -> `literature` under one identity and no later reader could tell that rule
    from one whose number was always literature-backed.
    """

    from etalon.research.evaluation_contract import evaluation_rules_digest

    convention = _contract()
    literature = _contract()
    literature["metrics"][0]["threshold_evidence"] = "literature"
    assert evaluation_rules_digest(convention) != evaluation_rules_digest(literature)
    assert evaluation_rules_digest(convention) == evaluation_rules_digest(_contract()), (
        "the digest must still be stable for an unchanged rule")


def test_the_published_criterion_says_what_each_provenance_tag_licenses():
    """The host is good at design judgement and cannot exercise it on a bare number.

    Deciding how hard to argue with a bar is method judgement, which stays free; the
    harness's job here is only to hand over the input that judgement needs.
    """

    from etalon.research.evaluation_contract import PROVENANCE

    block = specification(_contract())["threshold_provenance"]
    assert block["vocabulary"] == list(PROVENANCE)
    for tag in PROVENANCE:
        assert isinstance(block[tag], str) and block[tag].strip(), tag
    assert "somebody chose this number" in block["convention"]
    assert "citable" in block["literature"]
    assert "rules_digest" in block["in_the_rules_digest"]


def test_one_provenance_vocabulary_serves_the_plan_the_contract_and_the_fault_catalogue():
    """Three definitions existed; two now share one, and this refuses the drift.

    `hooks/budget_floor.py::EXPLAINED_STOPS` is the repository's own example of a vocabulary
    maintained twice and already stale against the stop reasons it explains. The research
    layer does not import `faults/`, so `Evidence` cannot be the shared import without
    crossing a layer boundary that is currently clean -- which makes a test the right
    instrument: it holds the agreement without creating the dependency.
    """

    from etalon.faults.taxonomy import Evidence
    from etalon.research.decision_rule import PROVENANCE as plan_side
    from etalon.research.evaluation_contract import PROVENANCE as contract_side

    assert plan_side is contract_side, "the plan side must import, not restate"
    assert tuple(e.value for e in Evidence) == contract_side, (
        "the fault catalogue's Evidence and the research layer's PROVENANCE have drifted; "
        "CLAUDE.md constraint 5 fixes one vocabulary, so one of them is now wrong")


def test_the_contract_schema_requires_an_operator_and_a_finite_threshold():
    """Why the undeclared-metric branch below is defensive rather than reachable.

    `validate_evaluation_contract` refuses a metric whose operator is not in `_OPS` or whose
    threshold is not a finite number, so a *validated* contract always states its bar. That
    requirement is what makes the branch unreachable, so the requirement is what this test
    holds -- the same shape as `test_i18_absent_is_unreachable_because_the_field_is_required`.
    If it is ever relaxed, the branch stops being defensive and this test says where to look.
    """
    from etalon.runtime.files import EvidenceError

    for field, value in (("operator", None), ("operator", "approximately"), ("threshold", None)):
        contract = _contract()
        contract["metrics"][0][field] = value
        with pytest.raises(EvidenceError):
            from etalon.research.evaluation_contract import validate_evaluation_contract
            validate_evaluation_contract(contract)


def test_an_undeclared_metric_reads_as_unspecified_not_satisfied():
    """The defensive branch, exercised on a hand-made projection input.

    Unreachable through a validated contract (see the test above), and deliberately kept:
    `specification(validate=False)` exists for a caller that already validated, and a
    silently-absent rule must never read as a satisfied one.
    """
    contract = _contract()
    contract["metrics"][0]["operator"] = None
    contract["metrics"][0]["threshold"] = None
    spec = specification(contract, validate=False)
    metric = spec["metrics"][0]
    assert metric["declared"] is False and metric["punishes"] is None
    assert spec["metrics_without_a_declared_rule"] == ["overlap"]
    assert "unspecified rather than" in metric["note"]


def test_the_specification_cannot_produce_a_verdict():
    """Structural, not a promise: the module has no path to the oracle.

    `evaluate_contract` is the only function that reads published originals and returns a
    status. If this module imported it, a host could ask for the judgement and tune against
    one fixed draw of it -- which is the failure `RSI_REWARD.md` argues no split prevents.
    """

    # Checked over the parsed imports, not the source text: the module docstring argues at
    # length about `evaluate_contract` and a text scan would match that prose. Word appears
    # is not concept used -- the same distinction `test_normative_consistency.py` turns on.
    import ast

    tree = ast.parse(inspect.getsource(contract_spec))
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) for alias in node.names}
    imported |= {alias.name for node in ast.walk(tree)
                 if isinstance(node, ast.Import) for alias in node.names}
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "evaluate_contract" not in imported | called, (
        "contract_spec reached the oracle; the specification/oracle line is enforced by the "
        "absence of this import, so re-read research/contract_spec.py's module docstring "
        "before adding it")
    spec = specification(_contract())
    for forbidden in ("status", "verdict", "result", "passed"):
        assert forbidden not in spec, f"the specification published a {forbidden!r}"
    assert "not_published" in spec and "verdict" in spec["not_published"]


def test_no_input_bytes_or_refs_are_republished():
    """Input names and kinds, never their refs: a ref is a pointer at the oracle's data."""

    spec = specification(_contract())
    assert spec["inputs"] == [{"name": "res", "kind": "result"}]
    assert "record_digest" not in repr(spec) and "record_id" not in repr(spec)


def test_the_published_operator_list_cannot_drift_from_the_one_that_evaluates():
    """Every operator the contract can use has a `punishes` sentence, and no extras."""

    assert set(contract_spec._PUNISHES) == set(_OPS), (
        "the punishes listing and evaluation_contract._OPS disagree; a host would be told "
        "nothing about an operator that can judge it")


def test_the_published_precedence_is_the_precedence_that_aggregates():
    """Pinned against `_aggregate` itself, so the listing cannot become folklore."""

    order = contract_spec._PRECEDENCE
    assert set(order) == STATUSES
    assert _aggregate([]) == contract_spec._NO_STATUSES
    assert contract_spec._NO_STATUSES not in STATUSES, "a contract that judged nothing has not passed"
    for worse, better in zip(order, order[1:]):
        assert _aggregate([better, worse]) == worse, (
            f"_aggregate ranks {better!r} at or above {worse!r}, contradicting the published "
            "precedence_worst_first")


def test_the_mcp_tool_is_free_and_returns_the_specification():
    pytest.importorskip("pydantic", reason="the MCP tool surface imports pydantic")
    import json

    from etalon.mcp.methods import register

    tools: dict = {}

    class Collector:
        def tool(self):
            def decorate(function):
                tools[function.__name__] = function
                return function
            return decorate

    register(Collector())
    assert "etalon_method_criterion" in tools
    assert tools["etalon_method_criterion"].__doc__.startswith("FREE.")
    payload = json.loads(tools["etalon_method_criterion"](_contract()))
    assert payload["ok"] is True
    assert payload["metrics"][0]["threshold"] == 0.75


# --- the ref path: the case this module exists for ---


def test_exactly_one_of_contract_or_ref_is_required():
    from etalon.runtime.files import EvidenceError

    with pytest.raises(EvidenceError):
        specification()
    with pytest.raises(EvidenceError):
        specification(_contract(), contract_ref=_ref("c", "d"))


def test_the_ref_path_resolves_the_contract_and_nothing_else(monkeypatch):
    """Counted, not asserted in prose: exactly one material read, and it is the contract.

    The contract is the specification; its inputs and their results are the oracle. A tool
    that resolved `contract["inputs"][*]["ref"]` would be reading the oracle's data under a
    name that promises otherwise, so the single read is pinned by counting.
    """
    from etalon.research import contract_spec as mod
    from etalon.research import improvement

    contract = _contract()
    ref = _ref("contract", "d")
    reads: list = []

    def fake_read_material(workspace, r):
        reads.append(r)
        return {"ref": r, "record": {}, "content": contract, "complete": True}

    monkeypatch.setattr(improvement, "read_material", fake_read_material)
    monkeypatch.setattr("etalon.research.entry.resolve_read_workspace",
                        lambda ws, entry=None, read_context=None: "/nowhere")

    spec = mod.specification(contract_ref=ref, workspace="/nowhere")
    assert spec["metrics"][0]["threshold"] == 0.75
    assert len(reads) == 1, f"expected exactly the contract read, got {len(reads)}"
    assert reads[0]["source_id"] == "contract"
    input_refs = [i["ref"] for i in contract["inputs"]]
    assert all(r not in input_refs for r in reads), "an input ref was resolved"


def test_a_fragmentary_contract_is_refused_rather_than_assembled(monkeypatch):
    """A specification built from fragments is one nobody can check."""
    from etalon.research import contract_spec as mod
    from etalon.research import improvement
    from etalon.runtime.files import EvidenceError

    monkeypatch.setattr(improvement, "read_material",
                        lambda ws, r: {"ref": r, "record": {}, "content": None,
                                       "complete": False, "fragment": {"offset": 0}})
    monkeypatch.setattr("etalon.research.entry.resolve_read_workspace",
                        lambda ws, entry=None, read_context=None: "/nowhere")
    with pytest.raises(EvidenceError, match="incomplete"):
        mod.specification(contract_ref=_ref("contract", "d"), workspace="/nowhere")


def test_the_missing_provenance_refusal_names_the_field_and_the_legal_route():
    """A refusal a caller cannot act on is a wall. This one was, and cost real time.

    `_fields` is shared across the research schemas and says only that a field set
    mismatched. That is right for a caller who knows the schema and wrong for one meeting a
    newly required field: tracing one such refusal back through four example files is how
    this test came to exist. The same standard `research/reserved_bindings.py` is held to.
    """

    from etalon.research.evaluation_contract import PROVENANCE, validate_evaluation_contract
    from etalon.runtime.files import EvidenceError

    contract = _contract()
    del contract["metrics"][0]["threshold_evidence"]
    with pytest.raises(EvidenceError) as refused:
        validate_evaluation_contract(contract)
    message = str(refused.value)
    assert "threshold_evidence" in message
    assert all(tag in message for tag in PROVENANCE), "the legal values must be in the message"
    assert "convention" in message and "never be presented as a measurement" in message

    # Any other field-set problem keeps the shared message: this branch is for the one
    # field a caller could not have known about, not a replacement for schema validation.
    other = _contract()
    del other["metrics"][0]["unit"]
    with pytest.raises(EvidenceError, match="missing or unsupported"):
        validate_evaluation_contract(other)
