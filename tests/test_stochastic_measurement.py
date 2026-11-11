"""A single draw is not a measurement, and a declared replica count is not a measured one.

Implements the verification ``docs/thin-harness/STOCHASTIC_MEASUREMENT.md`` §7 asks for: not a
score, and not "fewer single-draw results were published", but the two mechanisms by construction.

* **The falsifier the specification names.** Declare ``replicas=5`` against a campaign holding two
  authorised replicate actions. Before, the declaration cleared ``F_SINGLE_REPLICA_ESTIMATE`` and
  nothing in the record disagreed; the derived count fires the fault and reports the disagreement.
* **The identity.** A protocol that declares nothing keeps the exact ``protocol_id`` it had before
  this change -- shown against the digest recomputed the old way -- and a declared policy makes a
  new one, which is what hands this change the existing "protocol changed under an existing id"
  and alias refusals for free.

Stage 2 of the specification -- emitting ``evaluable=False`` where the declared and authorised
counts disagree -- is gated behind the admission-propagation recomputability audit and is *not*
implemented, so these tests assert that the disagreement is reported and that no ``Ruling`` moves.

``prism`` and ``molcascade`` are not importable in this environment, so the registration and
end-to-end dispatch paths cannot be exercised here; the dispatch refusal is tested at the seam the
dispatcher calls, with the record shape it passes.
"""

from __future__ import annotations

import pytest

from etalon.active.aggregation import (
    DEFAULT,
    NOT_TAKEN,
    AggregationPolicy,
    PolicyError,
    authorised_draws,
    coverage,
    dispatch_refusal,
    dispersion_figure,
    per_task_dispersion,
    policy_from_stage,
    trajectory_from_authorised_replicates,
)
from etalon.active.cascade import CascadeRecipe
from etalon.active.schema import Endpoint, canonical, digest
from etalon.faults.stability import check_stability, from_prism
from etalon.runtime.executors import _aggregation_block, aggregation_provenance

RMSD = {"values_nm": [0.12, 0.13, 0.11, 0.12, 0.13, 0.12, 0.11, 0.12, 0.13, 0.12]}


def action(candidate="m1", endpoint="mmpbsa", replicate=0, status="completed"):
    return {"candidate_id": candidate, "endpoint_id": endpoint, "replicate": replicate,
            "status": status}


def recipe(**overrides):
    body = {"configuration": '{"tiers":[]}', "readout_json": '{"stage_id":"s"}',
            "infrastructure_commit": "abc123", "input_files": (("/tmp/w.pt", "deadbeef"),)}
    body.update(overrides)
    return CascadeRecipe(**body)


def _fired(observations, code):
    return next(o for o in observations if o.code == code).fired


# -- the falsifier: declared against authorised -------------------------------------------------


def test_a_declared_replica_count_clears_the_fault_against_two_authorised_actions():
    """The defect, stated as the specification states it.

    ``Trajectory.replicas`` is a caller-supplied integer and ``from_prism`` passes it through, so
    the clearing of ``F_SINGLE_REPLICA_ESTIMATE`` rests on an unverified declaration. This is the
    "before": a five-replica claim over two authorised actions, and nothing in the result disagrees.
    """

    declared = from_prism(RMSD, replicas=5)

    assert declared.replicas == 5
    assert _fired(check_stability(declared), "F_SINGLE_REPLICA_ESTIMATE") is False


def test_the_derived_count_refuses_to_inherit_the_declaration():
    """The same campaign, with the count measured from the authorised replicate actions."""

    rows = [action(replicate=0), action(replicate=1)]

    trajectory, basis = trajectory_from_authorised_replicates(
        RMSD, actions=rows, candidate_id="m1", endpoint_id="mmpbsa", seeds=[11, 22, 33])

    assert trajectory.replicas == 2, "two authorised actions are two draws, whatever was declared"
    assert basis["authorised_draws"] == 2 and basis["replicate_indices"] == [0, 1]
    assert basis["basis"].startswith("measured_here")
    # F_SINGLE_REPLICA_ESTIMATE is a precision fault: it annotates and does not withhold, and this
    # change does not touch its band, its routing or its consequence.
    assert _fired(check_stability(trajectory), "F_SINGLE_REPLICA_ESTIMATE") is False


def test_one_authorised_action_fires_the_single_replica_fault():
    trajectory, basis = trajectory_from_authorised_replicates(
        RMSD, actions=[action(replicate=0)], candidate_id="m1", endpoint_id="mmpbsa", seeds=[11])

    assert trajectory.replicas == 1 and basis["authorised_draws"] == 1
    assert _fired(check_stability(trajectory), "F_SINGLE_REPLICA_ESTIMATE") is True


def test_the_constructor_takes_no_replica_count_at_all():
    """The derivation is not an option beside the declaration; there is nothing to pass."""

    with pytest.raises(TypeError):
        trajectory_from_authorised_replicates(  # type: ignore[call-arg]
            RMSD, actions=[action()], candidate_id="m1", endpoint_id="mmpbsa", replicas=5)


def test_a_replicate_with_no_authorised_seed_is_not_a_draw():
    """``active/prism.py``: a next-round plan is not dispatch permission."""

    rows = [action(replicate=0), action(replicate=1), action(replicate=2)]
    counted = authorised_draws(rows, candidate_id="m1", endpoint_id="mmpbsa", seeds=[11, 22])

    assert counted["authorised_draws"] == 2
    assert counted["replicates_without_an_authorised_seed"] == [2]


@pytest.mark.parametrize("status", ["reserved", "running", "failed", "invalid", "blocked"])
def test_only_an_admitted_draw_counts(status):
    """``completed`` is written only where the observation was admitted.

    A withheld or failed action produced no draw a consensus may rest on, and an unresolved one
    has not produced one yet -- so neither may clear a replica fault.
    """

    rows = [action(replicate=0), action(replicate=1, status=status)]

    assert authorised_draws(rows, candidate_id="m1", endpoint_id="mmpbsa",
                            seeds=[1, 2, 3])["authorised_draws"] == 1


def test_a_count_is_per_task_and_never_pooled():
    """Dispersion and draw counts are per-task properties; a pooled figure describes neither."""

    rows = [action(candidate="m1", replicate=0), action(candidate="m2", replicate=0),
            action(candidate="m2", replicate=1)]

    first = authorised_draws(rows, candidate_id="m1", endpoint_id="mmpbsa", seeds=[1, 2])
    second = authorised_draws(rows, candidate_id="m2", endpoint_id="mmpbsa", seeds=[1, 2])

    assert (first["authorised_draws"], second["authorised_draws"]) == (1, 2)
    assert first["pooled"] is False and second["pooled"] is False


def test_coverage_reports_the_disagreement_without_moving_a_ruling():
    """Stage 1: declared and authorised side by side, nothing refused.

    Stage 2 would emit ``evaluable=False`` here. It is gated behind the admission-propagation
    recomputability audit, because turning declared replicas into unevaluable observations moves
    nodes in a derived view, and ``RSI_REWARD.md`` (D4) counts ``not_recorded`` as a loss.
    """

    policy = AggregationPolicy(draws=5, combine="median", dispersion="range",
                               draws_evidence="literature", draws_source="ESMACS/TIES")
    counted = authorised_draws([action(replicate=0), action(replicate=1)],
                               candidate_id="m1", endpoint_id="mmpbsa", seeds=[1, 2, 3, 4, 5])

    block = coverage(policy, counted, values=[-31.2, -29.8])

    assert block["declared_draws"] == 5 and block["authorised_draws"] == 2
    assert block["agrees"] is False
    assert block["missing_policy"] == "declared"
    assert block["dispersion_figure"] == pytest.approx(1.4)
    assert block["pooled"] is False


def test_an_undeclared_policy_is_insufficient_rather_than_a_declared_single_draw():
    counted = authorised_draws([action(replicate=0)], candidate_id="m1", endpoint_id="mmpbsa")
    block = coverage(DEFAULT, counted, values=[-31.2])

    assert block["missing_policy"] == "insufficient"
    assert block["declared_draws"] == block["authorised_draws"] == 1


# -- dispersion: not taken, never zero ----------------------------------------------------------


def test_one_draw_reports_no_dispersion_rather_than_zero():
    """Zero is the value a missing spread most resembles, which is why it is refused here."""

    policy = AggregationPolicy(draws=5, dispersion="sd", draws_evidence="literature",
                               draws_source="ESMACS/TIES")
    figure = dispersion_figure([-31.2], policy)

    assert figure["figure"] is None
    assert figure["basis"].startswith(NOT_TAKEN)
    assert coverage(policy, authorised_draws([action()], candidate_id="m1", endpoint_id="mmpbsa"),
                    values=[-31.2])["dispersion_figure"] == NOT_TAKEN


def test_two_tasks_with_different_spreads_are_reported_separately():
    """The measurement that forbids a pooled figure: 0.0000 on one task and 0.1364 on another."""

    policy = AggregationPolicy(draws=5, dispersion="range", draws_evidence="literature",
                               draws_source="ESMACS/TIES")

    flat = dispersion_figure([0.7, 0.7, 0.7, 0.7, 0.7], policy)
    spread = dispersion_figure([0.6818, 0.8182, 0.7273, 0.7727, 0.6818], policy)

    assert flat["figure"] == pytest.approx(0.0)
    assert spread["figure"] == pytest.approx(0.1364)
    # A pooled figure over these two describes neither, so nothing here produces one.
    assert flat["pooled"] is spread["pooled"] is False


def test_per_task_dispersion_produces_nothing_poolable():
    """Over real observation rows, per candidate, with no total and no mean of the spreads."""

    policy = AggregationPolicy(draws=5, dispersion="range", draws_evidence="literature",
                               draws_source="ESMACS/TIES")
    rows = [
        {"admitted": True, "result": {"candidate_id": "flat", "endpoint_id": "e", "value": 0.7}},
        {"admitted": True, "result": {"candidate_id": "flat", "endpoint_id": "e", "value": 0.7}},
        {"admitted": True, "result": {"candidate_id": "wide", "endpoint_id": "e", "value": 0.6818}},
        {"admitted": True, "result": {"candidate_id": "wide", "endpoint_id": "e", "value": 0.8182}},
        {"admitted": True, "result": {"candidate_id": "once", "endpoint_id": "e", "value": 0.5}},
        # Not admitted, so not a draw this campaign may aggregate.
        {"admitted": False, "result": {"candidate_id": "wide", "endpoint_id": "e", "value": 9.9}},
    ]

    report = per_task_dispersion(rows, policy, endpoint_id="e")

    assert report["tasks"]["flat"]["figure"] == pytest.approx(0.0)
    assert report["tasks"]["wide"]["figure"] == pytest.approx(0.1364)
    assert report["tasks"]["once"]["figure"] is None
    assert report["tasks"]["once"]["basis"].startswith(NOT_TAKEN)
    assert report["pooled"] is False
    assert not {"total", "mean", "sd"} & set(report)


def test_a_dispersion_declared_over_one_draw_is_refused_at_declaration():
    with pytest.raises(PolicyError, match="not a spread"):
        AggregationPolicy(draws=1, dispersion="sd")


# -- the policy's own refusals -------------------------------------------------------------------


def test_a_declared_draw_count_cannot_claim_to_be_measured_here():
    """``draws`` is declared; the authorised count is what is measured."""

    with pytest.raises(PolicyError, match="not measured_here"):
        AggregationPolicy(draws=5, draws_evidence="measured_here", draws_source="x")


def test_more_than_one_draw_must_say_where_the_count_came_from():
    with pytest.raises(PolicyError, match="where that count came from"):
        AggregationPolicy(draws=5, combine="median", dispersion="range",
                          draws_evidence="literature")


def test_fraction_present_needs_both_thresholds_each_with_a_provenance():
    with pytest.raises(PolicyError, match="pass_threshold share"):
        AggregationPolicy(draws=5, combine="fraction_present", dispersion="range",
                          draws_evidence="literature", draws_source="x", present_threshold=0.3)
    with pytest.raises(PolicyError, match="present_threshold_evidence"):
        AggregationPolicy(draws=5, combine="fraction_present", dispersion="range",
                          draws_evidence="literature", draws_source="x",
                          present_threshold=0.3, pass_threshold=0.6)
    policy = AggregationPolicy(draws=5, combine="fraction_present", dispersion="range",
                               draws_evidence="literature", draws_source="x",
                               present_threshold=0.3, present_threshold_evidence="convention",
                               pass_threshold=0.6, pass_threshold_evidence="convention")
    assert policy.as_dict()["present_threshold_evidence"] == "convention"


def test_a_threshold_no_combiner_reads_is_refused():
    with pytest.raises(PolicyError, match="read only by"):
        AggregationPolicy(draws=5, combine="mean", dispersion="range", draws_evidence="literature",
                          draws_source="x", present_threshold=0.3,
                          present_threshold_evidence="convention")


def test_an_unknown_field_is_not_silently_accepted():
    with pytest.raises(PolicyError, match="does not define"):
        AggregationPolicy.declare({"draws": 5, "replicas": 5})


def test_best_of_is_legal_and_is_not_an_estimate_of_a_mean():
    policy = AggregationPolicy(draws=5, combine="best_of", dispersion="range",
                               draws_evidence="literature", draws_source="x")
    assert policy.combine == "best_of"


# -- the priced catalogue as the default source --------------------------------------------------


def test_the_ensemble_default_comes_from_the_catalogue_with_its_provenance():
    """``economics/stage.py`` is the right input to a policy, and ``active/`` now reads it."""

    from etalon.economics.stage import BY_ID

    policy = policy_from_stage(BY_ID["mmgbsa_single"])

    assert policy.draws == 5
    assert policy.draws_evidence == "literature"
    assert "ESMACS" in policy.draws_source
    # F_SINGLE_REPLICA_ESTIMATE's own remedy: a median with a quantile interval, because the
    # distribution is skewed and heavy-tailed -- not a mean with a standard deviation.
    assert (policy.combine, policy.dispersion) == ("median", "range")


def test_a_stage_reproducible_from_one_run_declares_one_draw_as_a_convention():
    from etalon.economics.stage import BY_ID

    policy = policy_from_stage(BY_ID["docking"])

    assert policy.draws == 1 and policy.draws_evidence == "convention"
    assert "RT*ln(10)" in policy.draws_source or "1.42" in policy.draws_source


# -- protocol identity ---------------------------------------------------------------------------


def test_an_undeclared_policy_leaves_every_existing_protocol_id_unchanged():
    """The digest recomputed the way it was computed before the field existed.

    Hard constraint 4: nothing backfills. Digesting an explicit default would move every protocol
    id already registered, and ``runtime/executors._verify`` would then read every registered
    executor as having changed since preparation.
    """

    base = recipe()
    before = "molcascade-recipe/1:" + digest({
        "configuration": base.configuration, "readout_json": base.readout_json,
        "infrastructure_commit": base.infrastructure_commit, "input_files": base.input_files})

    assert base.aggregation_json == ""
    assert base.protocol_id == before
    assert base.aggregation() == DEFAULT


def test_a_declared_policy_is_part_of_the_protocol_identity():
    """So that changing it is a new protocol, refused under the old id rather than reinterpreted."""

    policy = AggregationPolicy(draws=5, combine="median", dispersion="range",
                               draws_evidence="literature", draws_source="ESMACS/TIES")
    other = AggregationPolicy(draws=3, combine="median", dispersion="range",
                              draws_evidence="literature", draws_source="ESMACS/TIES")

    declared = recipe(aggregation_json=canonical(policy.as_dict()))
    changed = recipe(aggregation_json=canonical(other.as_dict()))

    assert declared.protocol_id != recipe().protocol_id
    assert declared.protocol_id != changed.protocol_id
    assert declared.aggregation() == policy


# -- the refusal at dispatch, generalised --------------------------------------------------------


def test_a_policy_declaring_more_draws_than_the_endpoint_authorises_is_refused():
    policy = AggregationPolicy(draws=5, combine="median", dispersion="range",
                               draws_evidence="literature", draws_source="ESMACS/TIES")

    refusal = dispatch_refusal(policy, max_replicates=1)

    assert refusal is not None and "authorises at most 1" in refusal


def test_fewer_declared_seeds_than_draws_is_refused():
    policy = AggregationPolicy(draws=5, combine="median", dispersion="range",
                               draws_evidence="literature", draws_source="ESMACS/TIES")

    assert "distinct seed" in dispatch_refusal(policy, max_replicates=5, declared_seeds=3)


def test_claiming_authorised_seeds_without_any_is_refused():
    policy = AggregationPolicy(draws=3, independence_basis="distinct_authorised_seeds",
                               combine="median", dispersion="range", draws_evidence="literature",
                               draws_source="ESMACS/TIES")

    assert "declares no seeds" in dispatch_refusal(policy, max_replicates=3)


def test_a_single_draw_policy_refuses_nothing():
    """Every protocol registered before this change declares one draw, and nothing changes for it."""

    assert dispatch_refusal(DEFAULT, max_replicates=1) is None
    assert dispatch_refusal(AggregationPolicy(draws=1), max_replicates=3) is None


def test_the_dispatcher_refuses_a_dispatchable_kind_and_not_only_the_replicated_one():
    """The generalisation: the refusal is keyed on the policy, not on an executor kind.

    ``prism_mmpbsa_replicated`` was refused by name, and every other kind fell through to a branch
    that runs one trajectory. A molcascade endpoint is dispatchable and fixed-seed, so a protocol
    declaring three independent draws against it must be refused rather than run once and recorded
    under a protocol id claiming three.
    """

    endpoint = Endpoint("cheap", "t", "score", "u", "molcascade-recipe/1:abc", 1.0,
                        requires_handoff=False)
    policy = AggregationPolicy(draws=3, combine="median", dispersion="range",
                               draws_evidence="literature", draws_source="ESMACS/TIES")
    record = {"kind": "molcascade", "executor_id": "e1",
              "configuration": {"aggregation": policy.as_dict()}}

    blocked = _aggregation_block(record, endpoint, "m1")

    assert blocked is not None
    assert blocked.status == "blocked" and blocked.value is None
    assert blocked.cost == 0.0, "a refusal starts nothing, so it charges nothing"
    assert blocked.provenance["cost_basis"] == "not dispatched"
    assert blocked.provenance["phase"] == "executor_dispatch"
    assert blocked.provenance["declared_aggregation"]["draws"] == 3


def test_the_dispatcher_lets_an_undeclared_protocol_through_untouched():
    endpoint = Endpoint("cheap", "t", "score", "u", "molcascade-recipe/1:abc", 1.0,
                        requires_handoff=False)

    assert _aggregation_block({"kind": "molcascade", "executor_id": "e1", "configuration": {}},
                              endpoint, "m1") is None


def test_the_dispatcher_counts_the_declared_seeds_of_a_replicated_endpoint():
    """Registration stays complete and the frozen inputs stay valid; only dispatch refuses."""

    endpoint = Endpoint("mmpbsa", "t", "mmpbsa", "kcal/mol", "prism-mmpbsa-replicated/1:abc", 1.0,
                        max_replicates=3)
    policy = AggregationPolicy(draws=5, combine="median", dispersion="range",
                               draws_evidence="literature", draws_source="ESMACS/TIES")
    record = {"kind": "prism_mmpbsa_replicated", "executor_id": "e2",
              "configuration": {"seeds": [1, 2, 3], "aggregation": policy.as_dict()}}

    blocked = _aggregation_block(record, endpoint, "m1")
    assert blocked is not None and "authorises at most 3" in blocked.provenance["error"]

    matching = AggregationPolicy(draws=3, combine="median", dispersion="range",
                                 draws_evidence="literature", draws_source="ESMACS/TIES")
    agreeing = {**record, "configuration": {"seeds": [1, 2, 3], "aggregation": matching.as_dict()}}
    # Nothing here unwires that kind's own refusal, which is for a different and correct reason:
    # independent-replica MD and gmx_MMPBSA execution are not wired.
    assert _aggregation_block(agreeing, endpoint, "m1") is None


def test_the_dispatched_value_carries_the_policy_and_its_coverage():
    """Stage 1: the block travels beside the value, which is where a reader of the record is.

    The action being dispatched is itself an authorised draw, so a running action counts here --
    a post-hoc read of the same rows counts only completed ones, which is the honest difference
    between "this draw is being taken" and "this draw has been taken".
    """

    endpoint = Endpoint("mmpbsa", "t", "mmpbsa", "kcal/mol", "prism-mmpbsa-replicated/1:abc", 1.0,
                        max_replicates=3)
    policy = AggregationPolicy(draws=3, combine="median", dispersion="range",
                               draws_evidence="literature", draws_source="ESMACS/TIES")
    record = {"kind": "prism_mmpbsa_replicated", "executor_id": "e2",
              "configuration": {"seeds": [1, 2, 3], "aggregation": policy.as_dict()}}
    rows = [action(replicate=0), action(replicate=1, status="running")]
    observed = [{"admitted": True,
                 "result": {"candidate_id": "m1", "endpoint_id": "mmpbsa", "value": -31.2}}]

    block = aggregation_provenance(record, endpoint, candidate_id="m1", actions=rows,
                                   observations=observed)

    assert block["declared_draws"] == 3
    assert block["authorised_draws"] == 2, "the draw being dispatched counts as one"
    assert block["agrees"] is False
    assert block["dispersion_figure"] == NOT_TAKEN, "one admitted value is not a spread"
    assert block["combine"] == "median" and block["pooled"] is False


def test_an_undeclared_protocol_still_reports_its_coverage():
    endpoint = Endpoint("cheap", "t", "score", "u", "molcascade-recipe/1:abc", 1.0,
                        requires_handoff=False)

    block = aggregation_provenance({"kind": "molcascade", "configuration": {}}, endpoint,
                                   candidate_id="m1",
                                   actions=[action(endpoint="cheap", status="running")],
                                   observations=[])

    assert block["missing_policy"] == "insufficient"
    assert block["declared_draws"] == 1 and block["authorised_draws"] == 1
    assert block["agrees"] is True


def test_a_repeated_seed_is_refused_when_counting_draws():
    with pytest.raises(ValueError, match="retry, not a replica"):
        authorised_draws([action()], candidate_id="m1", endpoint_id="mmpbsa", seeds=[7, 7])
