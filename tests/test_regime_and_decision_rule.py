"""Explicit regime entry, and the decision rule travelling with the measurement.

Two of the three parts a two-regime system needs, demonstrated by construction
rather than by a score. Each case states the transcript that worked before the
change and is refused after it, or -- for the regime-unknown path -- the
transcript that propagated before and declines to now.

(a) Explicit entry. `composition.record_evaluation` defaulted
    `assessment_role="diagnostic"`, so the freely-explorable regime was entered by
    omission. The argument is required now; omitting it still works, warns, and is
    recorded as `assessment_role_basis="defaulted_deprecated"` so a later reader
    can tell an omission from a choice. Records written before the argument carry
    no basis at all and are regime-unknown: usable, never relied on.

(d) The decision rule. The `evaluation_plan` step could not represent `operator`
    or `threshold`, and `record_evaluation` took prose. Both are representable
    now, and a conclusion claiming support against a replay of the declared rule
    is refused.

Nothing here asserts a scientific finding; the fixtures establish software
behaviour only.
"""
from __future__ import annotations

import copy
import warnings
from dataclasses import replace

import pytest

import etalon.learn.admission_view as av
from etalon.active.schema import canonical, digest
from etalon.learn.admission_view import admission_view
from etalon.research.assessment_regime import regime, regime_of_node
from etalon.research.components import record_json
from etalon.research.composition import record_evaluation
from etalon.research.continuation import validate_content
from etalon.research.decision_rule import (
    REPLAY, build_decision_rule, plan_rules, replay, validate_decision_rule,
    validate_plan_metric_rule,
)
from etalon.research.evidence_refs import EvidenceError
from etalon.research.graph_memory import build_research_graph
from etalon.research.schema import MethodEvaluation, method_record_from_dict
from test_research_composition import evaluation_plan
from test_research_continuation import case, checkpoint, publish, save

RULE = {"operator": "le", "threshold": 2.0, "threshold_evidence": "literature"}


def ruled_plan(case, rule=None, metric_name="correct"):
    """The fixture plan with a decision rule on one of its two metrics."""

    plan = evaluation_plan(case)
    metric = next(m for m in plan["detail"]["metrics"] if m["name"] == metric_name)
    metric.update(RULE if rule is None else rule)
    return plan


def evaluate(case, plan_ref, **kw):
    journal, evidence, _, root = case
    kw.setdefault("conclusion", "fixture only; no adoption")
    kw.setdefault("scope", "fixture")
    kw.setdefault("result_refs", (evidence["record_id"],))
    return record_evaluation(journal, plan_ref, directory=root / "content",
                             source_id="research", source_kind="fixture", **kw)


def obs(name="correct", value=1.0, evidence="measured_here"):
    return [{"name": name, "value": value, "evidence": evidence}]


# ---------------------------------------------------------------- (a) explicit entry


def test_omitting_assessment_role_still_works_and_is_recorded_as_an_omission(case):
    """The old call. It is not broken; it is no longer silent."""

    journal = case[0]
    plan = save(case, evaluation_plan(case))
    with pytest.warns(DeprecationWarning, match="requires an explicit assessment_role"):
        out = evaluate(case, plan)
    assert out["assessment_role"] == "diagnostic"
    assert out["assessment_role_basis"] == "defaulted_deprecated"
    assert out["premise_eligibility"] == "used_only"
    record = journal.get(out["evaluation_ref"]["record_id"])
    assert record["assessment_role_basis"] == "defaulted_deprecated"


def test_declaring_the_role_explicitly_warns_about_nothing(case):
    journal = case[0]
    plan = save(case, evaluation_plan(case))
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        out = evaluate(case, plan, assessment_role="diagnostic")
    assert out["assessment_role_basis"] == "explicitly_declared"
    assert journal.get(out["evaluation_ref"]["record_id"])["assessment_role_basis"] == "explicitly_declared"
    # Still diagnostic, so still not a premise: the explicit choice does not promote.
    assert out["premise_eligibility"] == "used_only"


def test_a_record_predating_the_argument_parses_with_no_basis_and_is_refused_reliance(case):
    """The migration case. Old bytes have no `assessment_role_basis` key at all.

    The two halves of the migration land on the same answer, which is why it needs
    no case analysis. A legacy *diagnostic* record has a known regime and that
    regime cannot settle a premise. A legacy *independent_validation* record has a
    role we cannot attribute to a choice, so it is `regime_unknown`. Neither
    permits reliance, and nothing is written to either record.
    """

    journal = case[0]
    plan = save(case, evaluation_plan(case))
    with pytest.warns(DeprecationWarning):
        out = evaluate(case, plan)
    record = journal.get(out["evaluation_ref"]["record_id"])
    legacy = {k: v for k, v in record.items() if k != "assessment_role_basis"}
    assert "assessment_role_basis" not in legacy
    # method_record_from_dict parses the old shape, and the missing field is None,
    # not a guess at what the author meant.
    parsed = method_record_from_dict(legacy)
    assert parsed.assessment_role_basis is None
    diagnostic = regime(parsed.assessment_role, parsed.assessment_role_basis)
    assert diagnostic["regime"] == "diagnostic" and diagnostic["permits_reliance"] is False
    unknown = regime("independent_validation", parsed.assessment_role_basis)
    assert unknown["regime"] == "regime_unknown" and unknown["permits_reliance"] is False


def test_only_the_diagnostic_role_can_be_reached_by_omission(case):
    journal = case[0]
    plan = save(case, evaluation_plan(case))
    with pytest.warns(DeprecationWarning):
        out = evaluate(case, plan)
    value = method_record_from_dict(journal.get(out["evaluation_ref"]["record_id"]))
    with pytest.raises(ValueError, match="reached by omission"):
        replace(value, assessment_role="independent_validation")


def test_an_unknown_role_basis_is_refused_rather_than_defaulted(case):
    journal = case[0]
    plan = save(case, evaluation_plan(case))
    with pytest.warns(DeprecationWarning):
        out = evaluate(case, plan)
    value = method_record_from_dict(journal.get(out["evaluation_ref"]["record_id"]))
    with pytest.raises(ValueError, match="unknown assessment role basis"):
        replace(value, assessment_role_basis="chosen_i_promise")


@pytest.mark.parametrize("role,basis,expected,reliance", [
    ("independent_validation", "explicitly_declared", "independent_validation", True),
    ("independent_validation", "defaulted_deprecated", "regime_unknown", False),
    ("independent_validation", None, "regime_unknown", False),
    ("diagnostic", "explicitly_declared", "diagnostic", False),
    ("diagnostic", "defaulted_deprecated", "diagnostic", False),
    ("diagnostic", None, "diagnostic", False),
])
def test_regime_table_is_total_and_only_one_cell_permits_reliance(role, basis, expected, reliance):
    out = regime(role, basis)
    assert out["regime"] == expected and out["permits_reliance"] is reliance


def test_regime_of_a_node_whose_schema_has_no_role_is_none():
    for node in ({}, {"evaluation": {}}, {"evaluation": {"conclusion": "x"}}, {"evaluation": None}):
        assert regime_of_node(node) is None


# ---------------------------------------------------------------- (d) the plan can carry the rule


def test_the_plan_step_accepts_operator_threshold_and_their_evidence(case):
    plan = ruled_plan(case)
    saved = validate_content(plan)
    assert plan_rules(saved["detail"]) == [
        {"name": "correct", "operator": "le", "threshold": 2.0,
         "threshold_evidence": "literature", "unit": "fraction"}]
    # Still recordable: the fields are a representable addition, not a new requirement.
    assert save(case, plan)


def test_a_plan_without_a_rule_is_still_valid_and_declares_none(case):
    plan = evaluation_plan(case)
    assert plan_rules(plan["detail"]) == []
    assert save(case, plan)


@pytest.mark.parametrize("rule,match", [
    ({"operator": "le"}, "together or none"),
    ({"threshold": 2.0}, "together or none"),
    ({"threshold_evidence": "literature"}, "together or none"),
    ({"operator": "le", "threshold": 2.0}, "together or none"),
    ({"operator": "approximately", "threshold": 2.0, "threshold_evidence": "literature"}, "comparator"),
    ({"operator": "le", "threshold": "2.0", "threshold_evidence": "literature"}, "finite numeric threshold"),
    ({"operator": "le", "threshold": 2.0, "threshold_evidence": "i_measured_it"}, "threshold evidence"),
    ({"operator": "le", "threshold": 2.0, "threshold_evidence": None}, "threshold evidence"),
])
def test_half_a_rule_or_a_threshold_of_unstated_origin_is_refused(case, rule, match):
    """CLAUDE.md constraint 5: a threshold is a new number and carries its provenance.

    A threshold somebody chose is `convention` and must not be presented as a
    measured one, so the tag is required with the pair rather than optional
    beside it.
    """

    plan = evaluation_plan(case)
    next(m for m in plan["detail"]["metrics"] if m["name"] == "correct").update(rule)
    with pytest.raises(EvidenceError, match=match):
        validate_content(plan)


@pytest.mark.parametrize("threshold", [float("inf"), float("-inf"), float("nan")])
def test_a_nonfinite_threshold_is_refused_by_the_rule_and_by_the_record(case, threshold):
    """Two refusals, and the order matters only for the message.

    `continuation.validate_content` canonicalises the step before the extension
    validator sees it, and `active.schema.canonical` is `allow_nan=False`, so a
    non-finite threshold never reaches a stored plan. The rule validator refuses
    it on its own too, which is what a caller holding a metric dict gets.
    """

    rule = {"operator": "le", "threshold": threshold, "threshold_evidence": "literature"}
    with pytest.raises(EvidenceError, match="finite numeric threshold"):
        validate_plan_metric_rule({"name": "correct", "unit": "fraction", **rule})
    plan = evaluation_plan(case)
    next(m for m in plan["detail"]["metrics"] if m["name"] == "correct").update(rule)
    with pytest.raises(ValueError, match="not JSON compliant"):
        validate_content(plan)


@pytest.mark.parametrize("tag", ["measured_here", "measured_in_an_asset", "literature", "convention"])
def test_every_evidence_provenance_is_accepted_as_a_threshold_origin(case, tag):
    plan = ruled_plan(case, {**RULE, "threshold_evidence": tag})
    assert plan_rules(validate_content(plan)["detail"])[0]["threshold_evidence"] == tag


# ---------------------------------------------------------------- (d) the replay


def test_replay_with_no_rules_is_not_declared_rather_than_passed():
    """`_aggregate`'s own answer for an empty set, kept rather than reinterpreted."""

    assert replay([], []) == {"metrics": [], "status": "not_declared"}


@pytest.mark.parametrize("operator,threshold,value,status", [
    ("le", 2.0, 2.0, "criteria_passed"),
    ("le", 2.0, 2.0001, "criteria_failed"),
    ("lt", 2.0, 2.0, "criteria_failed"),
    ("ge", 0.9, 0.95, "criteria_passed"),
    ("gt", 0.9, 0.9, "criteria_failed"),
    ("eq", 41, 41, "criteria_passed"),
    ("eq", 41, 40, "criteria_failed"),
])
def test_every_comparator_replays_against_the_boundary(operator, threshold, value, status):
    rules = [{"name": "m", "operator": operator, "threshold": threshold,
              "threshold_evidence": "convention", "unit": "unit"}]
    out = replay(rules, [{"name": "m", "value": value, "evidence": "measured_here"}])
    assert out["status"] == status and out["metrics"][0]["status"] == status


def test_a_value_that_was_not_obtained_is_insufficient_and_never_estimated():
    """CLAUDE.md constraint 7, and `missing_policy: "insufficient"`'s own rule."""

    rules = [{"name": "m", "operator": "le", "threshold": 2.0,
              "threshold_evidence": "convention", "unit": "unit"}]
    out = replay(rules, [{"name": "m", "value": None, "evidence": "measured_here"}])
    assert out["status"] == "insufficient"
    assert out["metrics"][0]["observed"] is None
    assert "not obtained" in out["metrics"][0]["reason"]


def test_a_failure_outranks_an_insufficient_which_outranks_a_pass():
    """`evaluation_contract._aggregate`'s precedence, reached from here unchanged."""

    rules = [{"name": n, "operator": "le", "threshold": 1.0,
              "threshold_evidence": "convention", "unit": "u"} for n in ("a", "b", "c")]
    observed = [{"name": "a", "value": 0.5, "evidence": "measured_here"},
                {"name": "b", "value": None, "evidence": "measured_here"},
                {"name": "c", "value": 9.0, "evidence": "measured_here"}]
    assert replay(rules, observed)["status"] == "criteria_failed"
    assert replay(rules[:2], observed[:2])["status"] == "insufficient"
    assert replay(rules[:1], observed[:1])["status"] == "criteria_passed"


@pytest.mark.parametrize("observed,match", [
    ([], "missing"),
    ([{"name": "other", "value": 1.0, "evidence": "measured_here"}], "missing"),
    (obs() + [{"name": "extra", "value": 1.0, "evidence": "measured_here"}], "not in the plan"),
    (obs() * 2, "one observation per metric"),
    ([{"name": "correct", "value": 1.0}], "names exactly"),
    ([{"name": "correct", "value": 1.0, "evidence": "eyeballed"}], "Evidence provenance"),
    ([{"name": "correct", "value": "1.0", "evidence": "measured_here"}], "finite number or explicit null"),
    ([{"name": "correct", "value": float("nan"), "evidence": "measured_here"}], "finite number or explicit null"),
])
def test_observations_must_cover_exactly_the_ruled_metrics_and_carry_provenance(observed, match):
    rules = [{"name": "correct", "operator": "le", "threshold": 2.0,
              "threshold_evidence": "literature", "unit": "fraction"}]
    with pytest.raises(EvidenceError, match=match):
        replay(rules, observed)


def test_a_forged_verdict_is_refused_because_the_block_is_recomputed():
    """The same discipline `record_evaluation_artifact` applies to a report."""

    rules = [{"name": "correct", "operator": "le", "threshold": 2.0,
              "threshold_evidence": "literature", "unit": "fraction"}]
    good = build_decision_rule(rules, obs(value=9.0), "not_supported")
    assert good["replayed_status"] == "criteria_failed"
    forged = {**good, "replayed_status": "criteria_passed"}
    with pytest.raises(EvidenceError, match="differs from the recorded verdict"):
        validate_decision_rule(forged)
    forged_rows = copy.deepcopy(good)
    forged_rows["metrics"][0]["status"] = "criteria_passed"
    with pytest.raises(EvidenceError, match="differs from the recorded verdict"):
        validate_decision_rule(forged_rows)
    # And the forged verdict cannot be smuggled in through the record either.
    with pytest.raises(ValueError, match="differs from the recorded verdict"):
        MethodEvaluation(("s",), ("c",), "p", "tasksplit-x", "i", (), (), "diagnostic",
                         "looks fine", "fixture", decision_rule=forged)


@pytest.mark.parametrize("edit,match", [
    (lambda b: b.update(claim="probably"), "claim must be one of"),
    (lambda b: b.update(schema="etalon-something-else/1"), "replay schema"),
    (lambda b: b.update(basis="no_operator_or_threshold_declared_in_the_evaluation_plan"), "basis must be"),
    (lambda b: b.pop("observed"), "names exactly"),
    (lambda b: b.update(extra=1), "names exactly"),
])
def test_decision_rule_block_shape_is_refused_not_defaulted(edit, match):
    rules = [{"name": "correct", "operator": "le", "threshold": 2.0,
              "threshold_evidence": "literature", "unit": "fraction"}]
    block = build_decision_rule(rules, obs(), "supported")
    edit(block)
    with pytest.raises(EvidenceError, match=match):
        validate_decision_rule(block)


# ------------------------------------------- (d) record_evaluation refuses the contradiction


def test_a_conclusion_claiming_support_against_a_failed_replay_is_refused(case):
    """The transcript that succeeded before the change.

    Before: the plan could not carry `le 2.0`, `record_evaluation` took the prose
    `"candidate is within tolerance"` and validated it as nonempty text, and the
    record was written. After: the rule is in the plan, the replay says
    `criteria_failed`, and the record is not written.
    """

    journal = case[0]
    plan = save(case, ruled_plan(case))
    before = journal.store.events()
    with pytest.raises(EvidenceError, match="does not reach that conclusion"):
        evaluate(case, plan, assessment_role="diagnostic", claim="supported",
                 observed=obs(value=9.5),
                 conclusion="Candidate is within tolerance and should be adopted")
    assert journal.store.events() == before


def test_a_conclusion_claiming_support_against_an_unobtained_value_is_refused(case):
    """The external failure this guards: an answer unable to pass at submission."""

    journal = case[0]
    plan = save(case, ruled_plan(case))
    before = journal.store.events()
    with pytest.raises(EvidenceError, match="replayed insufficient"):
        evaluate(case, plan, assessment_role="diagnostic", claim="supported",
                 observed=obs(value=None), conclusion="Candidate passed")
    assert journal.store.events() == before


def test_a_conclusion_claiming_support_with_no_rule_declared_anywhere_is_refused(case):
    """Measurement with no decision rule cannot claim a finding."""

    journal = case[0]
    plan = save(case, evaluation_plan(case))
    before = journal.store.events()
    with pytest.raises(EvidenceError, match="replayed not_declared"):
        evaluate(case, plan, assessment_role="diagnostic", claim="supported",
                 conclusion="Candidate passed")
    assert journal.store.events() == before


def test_a_ruled_plan_requires_the_claim_and_the_observations(case):
    journal = case[0]
    plan = save(case, ruled_plan(case))
    before = journal.store.events()
    for kw in ({}, {"claim": "supported"}, {"observed": obs()}):
        with pytest.raises(EvidenceError, match="requires an explicit claim"):
            evaluate(case, plan, assessment_role="diagnostic", **kw)
    assert journal.store.events() == before


def test_support_against_a_passing_replay_is_recorded_with_its_verdict(case):
    journal = case[0]
    plan = save(case, ruled_plan(case))
    out = evaluate(case, plan, assessment_role="diagnostic", claim="supported",
                   observed=obs(value=1.5), conclusion="Within the declared tolerance")
    assert out["decision_rule"] == {"replayed_status": "criteria_passed", "claim": "supported",
                                    "basis": "replayed_from_evaluation_plan_metrics"}
    record = journal.get(out["evaluation_ref"]["record_id"])
    rule = record["decision_rule"]
    assert rule["schema"] == REPLAY and rule["replayed_status"] == "criteria_passed"
    assert rule["rules"][0]["threshold"] == 2.0 and rule["rules"][0]["threshold_evidence"] == "literature"
    assert rule["observed"][0]["evidence"] == "measured_here"
    # Idempotent: the same declared rule and the same observation are the same record.
    assert evaluate(case, plan, assessment_role="diagnostic", claim="supported",
                    observed=obs(value=1.5), conclusion="Within the declared tolerance") == out


@pytest.mark.parametrize("claim", ["not_supported", "not_claimed"])
def test_declining_to_claim_support_where_the_rule_passed_is_allowed(case, claim):
    """The refusal runs one way. A host may have reasons the rule does not cover,
    and that choice stays visible in the same record beside the verdict."""

    out = evaluate(case, save(case, ruled_plan(case)), assessment_role="diagnostic",
                   claim=claim, observed=obs(value=1.0), conclusion="Not adopting yet")
    assert out["decision_rule"]["replayed_status"] == "criteria_passed"
    assert out["decision_rule"]["claim"] == claim


def test_an_unruled_plan_records_that_no_rule_travelled_with_it(case):
    """A negative-assertion field, following the repository's own idiom, so the
    absence of a decision rule is a recorded fact rather than a missing one."""

    journal = case[0]
    out = evaluate(case, save(case, evaluation_plan(case)), assessment_role="diagnostic")
    rule = journal.get(out["evaluation_ref"]["record_id"])["decision_rule"]
    assert rule["replayed_status"] == "not_declared" and rule["claim"] == "not_claimed"
    assert rule["basis"] == "no_operator_or_threshold_declared_in_the_evaluation_plan"
    assert rule["rules"] == [] and rule["observed"] == []


# ------------------------------- (d) the mechanism quantity the review named


def test_count_of_prose_conclusions_asserting_success_against_a_replayed_failure(case):
    """The review's metric, computed by construction with its denominator.

    Each row is a conclusion a host could have recorded before this change, with
    the observation it actually rested on. The count is how many assert a positive
    finding while the replayed status is `criteria_failed` or `insufficient`; the
    denominator is the number replayed. Per hard constraint 7 this is a count over
    a constructed corpus of six, not an estimate of the rate on real records,
    which needs journals this machine does not have.
    """

    corpus = [
        ("Candidate is within tolerance and should be adopted", "supported", 9.5),
        ("Candidate passed the declared check", "supported", 2.5),
        ("Candidate passed", "supported", None),
        ("Within the declared tolerance", "supported", 1.5),
        ("Below threshold on every case", "supported", 0.1),
        ("Exceeded the tolerance; not adopting", "not_supported", 9.5),
    ]
    plan = save(case, ruled_plan(case))
    replayed, contradictions, recorded = 0, 0, 0
    for conclusion, claim, value in corpus:
        replayed += 1
        try:
            evaluate(case, plan, assessment_role="diagnostic", claim=claim,
                     observed=obs(value=value), conclusion=conclusion)
            recorded += 1
        except EvidenceError as exc:
            assert "does not reach that conclusion" in str(exc)
            contradictions += 1
    assert (replayed, contradictions, recorded) == (6, 3, 3)
    # Before the change all six were recordable: the prose was validated as
    # nonempty text and the plan could not carry the rule to contradict it.
    unruled = save(case, evaluation_plan(case))
    assert sum(1 for conclusion, _, _ in corpus
               if evaluate(case, unruled, assessment_role="diagnostic",
                           conclusion=conclusion)) == 6


# ------------------------------- (d) the rule and the contract stay one rule


def test_a_plan_carrying_the_contracts_rule_still_binds(case):
    from test_evaluation_contract import setup
    from etalon.research.evaluation_contract import evaluate_contract
    from etalon.research.method_revision import journal_ref

    contract, _ = setup(case)
    declared = contract["metrics"][0]
    plan = evaluation_plan(case)
    d = plan["detail"]
    d["protocol_ref"] = contract["protocol_ref"]
    d["initial_conditions_ref"] = contract["initial_conditions_ref"]
    d["metrics"] = [{**{k: m[k] for k in ("name", "family", "unit", "denominator", "missing_policy")},
                     "operator": m["operator"], "threshold": m["threshold"],
                     "threshold_evidence": "convention"} for m in contract["metrics"]]
    plan_ref = save(case, plan)
    out = evaluate(case, plan_ref, assessment_role="diagnostic", claim="supported",
                   observed=[{"name": declared["name"], "value": 0.001, "evidence": "measured_here"}],
                   result_refs=[contract["inputs"][0]["ref"]["record_id"]])
    contract.update(plan_ref=plan_ref, evaluation_ref=out["evaluation_ref"],
                    subjects=d["subjects"], comparators=d["comparators"])
    assert evaluate_contract(publish(case), contract)["status"] == "criteria_passed"


def test_a_plan_whose_rule_disagrees_with_the_contract_is_refused(case):
    """Two declared thresholds that disagree are two criteria, not one."""

    from test_evaluation_contract import setup
    from etalon.research.evaluation_contract import evaluate_contract

    contract, _ = setup(case)
    plan = evaluation_plan(case)
    d = plan["detail"]
    d["protocol_ref"] = contract["protocol_ref"]
    d["initial_conditions_ref"] = contract["initial_conditions_ref"]
    d["metrics"] = [{**{k: m[k] for k in ("name", "family", "unit", "denominator", "missing_policy")},
                     "operator": m["operator"], "threshold": m["threshold"] * 1000,
                     "threshold_evidence": "convention"} for m in contract["metrics"]]
    plan_ref = save(case, plan)
    contract.update(plan_ref=plan_ref, subjects=d["subjects"], comparators=d["comparators"])
    result = evaluate_contract(publish(case), contract)
    assert result["status"] == "incomparable"
    assert any("decision rule differs from the contract" in row.get("reason", "")
               for row in result["bindings"])


def test_a_plan_claiming_a_better_founded_threshold_than_the_contract_is_refused(case):
    """The same refusal on the third field of the rule, and the direction is the point.

    Operator and threshold identical; the plan says the bar is `literature` where the
    contract says `convention`. That is the plan asserting the number is better founded
    than the contract records -- the one direction an inconsistency must never resolve in.
    Before `threshold_evidence` was checked with the pair it travels with, this passed.
    """

    from test_evaluation_contract import setup
    from etalon.research.evaluation_contract import evaluate_contract

    contract, _ = setup(case)
    assert contract["metrics"][0]["threshold_evidence"] == "convention", "fixture premise"
    plan = evaluation_plan(case)
    d = plan["detail"]
    d["protocol_ref"] = contract["protocol_ref"]
    d["initial_conditions_ref"] = contract["initial_conditions_ref"]
    d["metrics"] = [{**{k: m[k] for k in ("name", "family", "unit", "denominator", "missing_policy")},
                     "operator": m["operator"], "threshold": m["threshold"],
                     "threshold_evidence": "literature"} for m in contract["metrics"]]
    plan_ref = save(case, plan)
    contract.update(plan_ref=plan_ref, subjects=d["subjects"], comparators=d["comparators"])
    result = evaluate_contract(publish(case), contract)
    assert result["status"] == "incomparable"
    assert any("decision rule differs from the contract" in row.get("reason", "")
               for row in result["bindings"])


# ------------------------------- (b) the membrane over a real graph


def test_the_membrane_refuses_a_real_diagnostic_evaluation_as_a_premise(case):
    """End to end over records a journal actually wrote and a graph actually built.

    `research/method_links.py` emits `evaluation_result` from the evaluation step
    to the `MethodEvaluation` it bound, and `admission_view` classifies that
    relation `relied_on`. The projection carries the regime
    (`graph_memory._project_node`), the membrane reads it, and the edge is `used`.
    """

    journal = case[0]
    plan = save(case, evaluation_plan(case))
    out = evaluate(case, plan, assessment_role="diagnostic")
    cp = save(case, checkpoint(case, plan, step_refs=[plan, out["step_ref"]]))
    graph = build_research_graph(publish(case), checkpoint_ref=cp, max_nodes=128, max_bytes=131072)

    evaluation_nodes = [n for n in graph["nodes"] if "evaluation" in n]
    assert len(evaluation_nodes) == 1
    block = evaluation_nodes[0]["evaluation"]
    assert block["assessment_role"] == "diagnostic"
    assert block["assessment_role_basis"] == "explicitly_declared"
    assert block["decision_rule"]["replayed_status"] == "not_declared"
    premise_id = evaluation_nodes[0]["node_id"]

    edge = next(e for e in graph["edges"] if e.get("relation") == "evaluation_result")
    assert edge["to"] == premise_id
    # Before the membrane the table alone made this a premise, and it still would.
    assert av._declared_class(edge)[:2] == ("relied_on", "declared_relation")

    view = admission_view(graph, [])
    row = next(e for e in view["edges"] if (e["owner"], e["premise"]) == (edge["from"], edge["to"])
               and e["relation"] == "evaluation_result")
    assert (row["premise_class"], row["class_basis"]) == ("used", "regime_cannot_settle")
    assert row["premise_regime"] == "diagnostic"
    assert view["membrane"]["degraded_edges"] == 1
    assert view["membrane"]["relied_class_edges"] >= 1
    owner = next(n for n in view["nodes"] if n["node_id"] == edge["from"])
    assert premise_id in owner["regime_refused_premises"]
    assert "premise_regime_cannot_carry_reliance" in owner["reasons"]
    # An unscoped graph never asserts completeness, so every derived value is
    # capped regardless; the edge classification is the mechanism evidence here.
    assert view["graph_completeness"]["asserted"] is False
    assert digest(journal.get(out["evaluation_ref"]["record_id"]))


def test_a_legacy_evaluation_node_without_a_basis_is_regime_unknown_on_a_real_graph(case):
    """The vice-versa case: this propagated before the change and declines to now."""

    plan = save(case, evaluation_plan(case))
    out = evaluate(case, plan, assessment_role="diagnostic")
    cp = save(case, checkpoint(case, plan, step_refs=[plan, out["step_ref"]]))
    graph = build_research_graph(publish(case), checkpoint_ref=cp, max_nodes=128, max_bytes=131072)

    legacy = copy.deepcopy(graph)
    for node in legacy["nodes"]:
        if "evaluation" in node:
            # What a record written before the required argument projects to: the
            # role it declared, and no statement about how it got there.
            node["evaluation"].pop("assessment_role_basis")
            node["evaluation"]["assessment_role"] = "independent_validation"
    legacy.pop("view_id", None)
    legacy["view_id"] = "research-graph-" + digest(legacy)

    view = admission_view(legacy, [])
    row = next(e for e in view["edges"] if e["relation"] == "evaluation_result")
    assert (row["premise_class"], row["class_basis"]) == ("used", "regime_not_declared")
    assert row["premise_regime"] == "regime_unknown"
    assert view["membrane"]["by_class_basis"]["regime_not_declared"] == 1
    assert canonical(view)

# --- I18: the triggers the declaration names, which had no fixture before ---


def test_i18_a_null_role_and_an_out_of_enum_role_demote():
    """The reachable weak cases: the key is present, its value cannot be read as a regime."""
    from etalon.research.assessment_regime import REGIME_UNKNOWN, NOT_DECLARED, regime_of_node

    for role in (None, "", "validated", "INDEPENDENT_VALIDATION", 0):
        got = regime_of_node({"evaluation": {"assessment_role": role}})
        assert got["regime"] == REGIME_UNKNOWN, role
        assert got["permits_reliance"] is False, role
        assert got["degrade_basis"] == NOT_DECLARED, role


def test_i18_absent_is_unreachable_because_the_field_is_required():
    """`regime_of_node` reads a block with no `assessment_role` key as not an assessment.

    That is safe only because the field is required with no default, so a parsed record
    always carries one and a block without the key is not a real projection. If the field
    ever acquires a default, the key can go missing on a real record and the missing-key
    branch becomes a hole that permits reliance on an undeclared regime -- so this test
    guards the premise rather than the branch. ADMISSION_PROPAGATION.md §11.6 I18 and
    ASSESSMENT_REGIMES.md §3.6 both name `absent` as a trigger; what makes that clause
    unreachable rather than unimplemented is exactly the requirement asserted here.
    """
    import dataclasses
    from etalon.research.schema import MethodEvaluation

    field = {f.name: f for f in dataclasses.fields(MethodEvaluation)}["assessment_role"]
    assert field.default is dataclasses.MISSING, (
        "assessment_role acquired a default; a real projection can now omit the key, so "
        "regime_of_node's missing-key branch must change from not_applicable to "
        "REGIME_UNKNOWN or it permits reliance on an undeclared regime")
    assert field.default_factory is dataclasses.MISSING


def test_i18_a_node_with_no_evaluation_block_is_still_not_applicable():
    """The scope decision of §11.3 is unchanged: an artifact or a receipt is left alone."""
    from etalon.research.assessment_regime import regime_of_node

    assert regime_of_node({}) is None
    assert regime_of_node({"artifact": {"role": "input"}}) is None
    assert regime_of_node({"evaluation": "not a dict"}) is None
