"""A revision comparison refuses the ways a self-improving loop usually flatters itself.

Each test here is one failure mode the adoption gate had before this module existed, when
``resolve_method_revision`` checked only that the candidate appeared in the evaluation's subjects
and that two reference lists were non-empty.
"""

from __future__ import annotations

import pytest

from moldarwin.economics.stage import Evidence
from moldarwin.learn import admission_view
from moldarwin.research.revision_score import (
    ADMISSION_STATES,
    DEFAULT_ALPHA,
    MINIMUM_DISCORDANT_PAIRS,
    Adoption,
    Dimension,
    Family,
    Gain,
    NotComparable,
    Verdict,
    compare_dimension,
    compare_revision,
    median_difference_interval,
    two_sided_sign_p,
)

TASKS = tuple(f"t{index}" for index in range(12))
WARRANT = Dimension("warranted_decisions", Family.WARRANT)
COVERAGE = Dimension("answered", Family.COVERAGE)
COST = Dimension("wall", Family.COST, minimum_gain=60.0, unit="wall_second",
                 minimum_gain_source="fixture: a minute of wall time, chosen here")
DIGEST = "catalogue-digest-fixture"


def states(admitted: int, waived: int = 0) -> dict[str, str]:
    """Admission states for :data:`TASKS`: so many admitted, so many waived, rest withheld."""

    return {
        task: "admitted" if index < admitted
        else "admitted_under_waiver" if index < admitted + waived
        else "withheld"
        for index, task in enumerate(TASKS)
    }


def flags(true_count: int) -> dict[str, bool]:
    return {task: index < true_count for index, task in enumerate(TASKS)}


def revision(dimensions, *, role="independent_validation", declared=("the declared scope",),
             measured=()):
    return compare_revision(
        dimensions=dimensions, assessment_role=role, base_catalogue_digest=DIGEST,
        candidate_catalogue_digest=DIGEST, declared_scope=declared, measured_scope=measured)


# -- the statistics, which have to be exact because the counts are small -------------------


def test_the_minimum_discordant_pairs_is_the_fewest_that_could_ever_reach_alpha():
    """The constant is arithmetic, not taste: at five, a unanimous split still cannot pass."""

    assert two_sided_sign_p(MINIMUM_DISCORDANT_PAIRS, 0) <= DEFAULT_ALPHA
    assert two_sided_sign_p(MINIMUM_DISCORDANT_PAIRS - 1, 0) > DEFAULT_ALPHA
    assert two_sided_sign_p(6, 0) == pytest.approx(2 / 2**6)
    assert two_sided_sign_p(5, 0) == pytest.approx(2 / 2**5)


def test_the_sign_test_is_symmetric_and_bounded():
    assert two_sided_sign_p(0, 0) == 1.0
    assert two_sided_sign_p(3, 3) == 1.0
    assert two_sided_sign_p(9, 2) == two_sided_sign_p(2, 9)
    for wins in range(12):
        for losses in range(12):
            assert 0.0 <= two_sided_sign_p(wins, losses) <= 1.0


def test_an_interval_too_few_pairs_to_support_is_absent_rather_than_widened():
    """Hard constraint 7: a quantity that cannot be counted is reported as not obtained."""

    assert median_difference_interval([1.0, 2.0, 3.0]) is None
    assert median_difference_interval([]) is None
    interval = median_difference_interval([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert interval is not None and interval[0] <= 3.5 <= interval[1]


def test_the_admission_vocabulary_matches_the_admission_view():
    """These states are read from records the admission view writes; a private copy must agree."""

    assert set(ADMISSION_STATES) == set(admission_view._ORDER)
    assert ADMISSION_STATES == admission_view._ORDER


# -- what cannot be compared at all --------------------------------------------------------


def test_a_task_observed_on_one_side_only_is_refused_rather_than_dropped():
    """Dropping it lets a candidate that produced no answer outscore one that answered poorly."""

    with pytest.raises(NotComparable, match="one side only"):
        compare_dimension(WARRANT, {"t0": "admitted"}, {"t0": "admitted", "t1": "withheld"})


def test_two_sides_ruled_under_different_fault_catalogues_are_not_comparable():
    with pytest.raises(NotComparable, match="different fault catalogues"):
        compare_revision(
            dimensions=[(WARRANT, states(2), states(9))],
            assessment_role="diagnostic", base_catalogue_digest="one",
            candidate_catalogue_digest="other", declared_scope=["x"])


def test_a_warrant_dimension_refuses_a_value_outside_the_admission_vocabulary():
    """So a plain True cannot arrive where a waiver would have been visible."""

    with pytest.raises(NotComparable, match="not one of"):
        compare_dimension(WARRANT, dict.fromkeys(TASKS, "admitted"), dict.fromkeys(TASKS, True))


def test_measured_conditions_outside_the_declared_scope_are_refused():
    with pytest.raises(NotComparable, match="not inside the declared scope"):
        revision([(WARRANT, states(2), states(9))], declared=("a",), measured=("b",))


@pytest.mark.parametrize("role", ["", "validation", "independent", None, "DIAGNOSTIC"])
def test_the_assessment_role_must_be_one_of_the_two_declared_lanes(role):
    with pytest.raises(ValueError):
        compare_revision(
            dimensions=[(WARRANT, states(2), states(9))], assessment_role=role,
            base_catalogue_digest=DIGEST, candidate_catalogue_digest=DIGEST,
            declared_scope=["x"])


def test_a_revision_must_declare_a_scope_and_at_least_one_dimension():
    with pytest.raises(ValueError):
        revision([(WARRANT, states(2), states(9))], declared=())
    with pytest.raises(ValueError):
        revision([])


# -- the dimension verdicts ----------------------------------------------------------------


def test_a_resolved_improvement_on_enough_discordant_pairs_is_better():
    result = compare_dimension(WARRANT, states(2), states(9))
    assert result.verdict is Verdict.BETTER
    assert (result.candidate_wins, result.base_wins) == (7, 0)
    assert result.effect == 7.0
    assert result.p_value <= DEFAULT_ALPHA


def test_too_few_discordant_pairs_is_underpowered_and_not_no_change():
    result = compare_dimension(WARRANT, states(2), states(5))
    assert result.verdict is Verdict.UNDERPOWERED
    assert result.candidate_wins == 3
    assert "not evidence either way" in result.note


def test_a_difference_the_tasks_cannot_resolve_is_separated_from_no_difference():
    result = compare_dimension(COVERAGE, flags(4), flags(5) | {"t9": True, "t10": True})
    assert result.verdict in (Verdict.WITHIN_NOISE, Verdict.UNDERPOWERED)
    assert "not the same as no difference" in result.note or "not evidence either way" in result.note


def test_a_resolved_difference_below_the_declared_minimum_is_its_own_verdict():
    """Resolved and not worth doing is a different answer from unresolved."""

    result = compare_dimension(COST, dict.fromkeys(TASKS, 1000.0), dict.fromkeys(TASKS, 990.0))
    assert result.verdict is Verdict.BELOW_MINIMUM
    assert result.p_value <= DEFAULT_ALPHA
    assert "below the 60" in result.note


def test_a_dimension_with_no_observations_is_not_measured_rather_than_unchanged():
    result = compare_dimension(WARRANT, {}, {})
    assert result.verdict is Verdict.NOT_MEASURED
    assert "not zero" in result.note


def test_cost_is_signed_so_that_positive_is_a_saving_for_every_family():
    cheaper = compare_dimension(COST, dict.fromkeys(TASKS, 1000.0), dict.fromkeys(TASKS, 100.0))
    dearer = compare_dimension(COST, dict.fromkeys(TASKS, 100.0), dict.fromkeys(TASKS, 1000.0))
    assert cheaper.verdict is Verdict.BETTER and cheaper.effect == 900.0
    assert dearer.verdict is Verdict.WORSE and dearer.effect == -900.0


# -- how far the candidate may be taken ----------------------------------------------------


def test_a_quality_gain_under_independent_validation_adopts_across_the_declared_scope():
    comparison = revision([(WARRANT, states(2), states(9))])
    assert comparison.adoption is Adoption.FULL
    assert comparison.gain is Gain.QUALITY
    assert comparison.outcome == "adopt"
    assert comparison.reservations == ()
    assert comparison.scope == comparison.declared_scope


def test_a_cost_saving_never_pays_for_a_measured_quality_regression():
    comparison = revision([
        (WARRANT, states(9), states(2)),
        (COST, dict.fromkeys(TASKS, 1000.0), dict.fromkeys(TASKS, 100.0)),
    ])
    assert comparison.adoption is Adoption.REFUSED
    assert comparison.outcome == "retain"
    assert any("does not pay for it" in reason for reason in comparison.reservations)


def test_the_refused_comparison_still_reports_the_cost_saving_it_measured():
    """Reporting gain NONE would hide a real measurement; the refusal is about the trade."""

    comparison = revision([
        (WARRANT, states(9), states(2)),
        (COST, dict.fromkeys(TASKS, 1000.0), dict.fromkeys(TASKS, 100.0)),
    ])
    assert comparison.gain is Gain.COST
    assert comparison.adoption is Adoption.REFUSED


def test_keeping_a_pass_rate_by_waiving_more_is_not_an_improvement():
    """RSI_REWARD D3: a waiver is not a win, and more waivers is a signal of its own."""

    comparison = revision([(WARRANT, states(2), states(2, waived=8))])
    assert comparison.waiver_change == 8
    assert comparison.adoption is Adoption.REFUSED
    assert any("waiv" in reason for reason in comparison.reservations)


def test_a_quality_gain_bought_with_extra_waivers_is_bounded_rather_than_refused():
    comparison = revision([(WARRANT, states(9, waived=2), states(2))])
    assert comparison.waiver_change == -2  # the candidate waived fewer
    comparison = revision([(WARRANT, states(2), states(9, waived=2))])
    assert comparison.waiver_change == 2
    assert comparison.adoption is Adoption.SCOPED
    assert any("D3" in reason for reason in comparison.reservations)


def test_the_diagnostic_lane_cannot_carry_a_promotion_however_large_the_gain():
    comparison = revision([(WARRANT, states(0), states(12))], role="diagnostic")
    assert comparison.dimensions[0].verdict is Verdict.BETTER
    assert comparison.adoption is Adoption.DIAGNOSTIC_ONLY
    assert comparison.outcome == "retain"
    assert any("diagnostic lane" in reason for reason in comparison.reservations)


def test_evidence_narrower_than_the_claim_adopts_only_what_was_measured():
    comparison = revision(
        [(WARRANT, states(2), states(9))],
        declared=("kinase ATP site", "shallow PPI groove"), measured=("kinase ATP site",))
    assert comparison.adoption is Adoption.SCOPED
    assert comparison.scope == ("kinase ATP site",)
    assert comparison.declared_scope == ("kinase ATP site", "shallow PPI groove")


def test_no_established_gain_on_any_dimension_keeps_the_previous_version():
    comparison = revision([(WARRANT, states(6), states(6))])
    assert comparison.adoption is Adoption.REFUSED
    assert comparison.gain is Gain.NONE
    assert any("drifting" in reason for reason in comparison.reservations)


def test_an_unresolved_dimension_bounds_an_otherwise_full_adoption():
    comparison = revision([
        (WARRANT, states(2), states(9)),
        (COST, dict.fromkeys(TASKS, 100.0), dict.fromkeys(TASKS, 100.0)),
    ])
    assert comparison.adoption is Adoption.SCOPED
    assert any("not established" in reason for reason in comparison.reservations)


def test_a_dimension_with_no_observations_bounds_an_otherwise_full_adoption():
    comparison = revision([(WARRANT, states(2), states(9)), (COST, {}, {})])
    assert comparison.adoption is Adoption.SCOPED
    assert any("not obtained" in reason for reason in comparison.reservations)


def test_the_comparison_never_changes_a_default_by_itself():
    comparison = revision([(WARRANT, states(0), states(12))])
    assert comparison.as_dict()["default_changed"] is False
    assert comparison.outcome in {"adopt", "retain"}


# -- the record it leaves ------------------------------------------------------------------


def test_the_recorded_comparison_carries_what_a_reader_needs_to_recompute_it():
    comparison = revision([(WARRANT, states(2), states(9)), (COST,
                           dict.fromkeys(TASKS, 1000.0), dict.fromkeys(TASKS, 100.0))])
    body = comparison.as_dict()
    assert body["schema"] == "moldarwin-revision-comparison/1"
    assert body["catalogue_digest"] == DIGEST
    assert body["assessment_role"] == "independent_validation"
    assert [d["name"] for d in body["dimensions"]] == ["warranted_decisions", "wall"]
    for dimension in body["dimensions"]:
        assert dimension["alpha"] == DEFAULT_ALPHA
        assert dimension["alpha_evidence"] == "convention"
        assert {"pairs", "candidate_wins", "base_wins", "ties", "effect", "p_value"} <= set(dimension)


def test_every_threshold_in_the_record_names_where_it_came_from():
    """Hard constraint 5: a number with no stated origin reads as a measurement."""

    measured = Dimension("wall", Family.COST, minimum_gain=60.0, unit="s",
                         minimum_gain_evidence=Evidence.MEASURED_HERE,
                         minimum_gain_source="findings/2026-11-25 overlap probe")
    body = compare_dimension(measured, dict.fromkeys(TASKS, 100.0),
                             dict.fromkeys(TASKS, 100.0)).as_dict()
    assert body["minimum_gain_evidence"] == "measured_here"
    assert body["minimum_gain_source"]


def test_any_nonzero_threshold_must_name_where_it_came_from():
    """Including a convention: that is the case a later reader mistakes for a measurement."""

    for evidence in (Evidence.MEASURED_HERE, Evidence.CONVENTION, Evidence.LITERATURE):
        with pytest.raises(ValueError, match="no source"):
            Dimension("wall", Family.COST, minimum_gain=60.0, unit="s",
                      minimum_gain_evidence=evidence)
    # Zero asserts nothing, so it needs no origin.
    Dimension("warrant", Family.WARRANT)


def test_a_cost_dimension_needs_a_unit_and_the_others_refuse_one():
    with pytest.raises(ValueError, match="must name its unit"):
        Dimension("wall", Family.COST, minimum_gain=1.0, minimum_gain_source="fixture")
    with pytest.raises(ValueError, match="only a cost dimension"):
        Dimension("warrant", Family.WARRANT, unit="wall_second")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_a_cost_observation_must_be_a_finite_number(value):
    with pytest.raises(ValueError):
        compare_dimension(COST, dict.fromkeys(TASKS, value), dict.fromkeys(TASKS, 1.0))


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5, float("nan")])
def test_alpha_must_lie_strictly_inside_zero_and_one(bad):
    with pytest.raises(ValueError):
        compare_dimension(WARRANT, states(2), states(9), alpha=bad)


def test_a_tighter_alpha_cannot_turn_a_refusal_into_an_acceptance():
    """Monotonicity: demanding more evidence never admits more revisions."""

    for alpha in (0.2, 0.1, 0.05, 0.01, 0.001):
        verdict = compare_dimension(WARRANT, states(2), states(9), alpha=alpha).verdict
        if verdict is Verdict.BETTER:
            assert alpha >= two_sided_sign_p(7, 0) - 1e-12


def test_cost_tie_majority_with_unanimous_savings_never_flips_to_worse():
    """Eight ties plus seven positive savings has median 0.0; sign test is 7-0 (p=0.0156).

    Previously ``effect > 0`` fell through to ``WORSE`` whenever ties pushed the overall median
    to 0.0, turning a 7-0 candidate win into a regression.
    """

    tasks = [f"task-{i:02d}" for i in range(15)]
    base = dict.fromkeys(tasks, 10.0)
    candidate = {task: (5.0 if i < 7 else 10.0) for i, task in enumerate(tasks)}

    zero_floor = Dimension("wall", Family.COST, unit="s")
    res_zero = compare_dimension(zero_floor, base, candidate)
    assert res_zero.candidate_wins == 7 and res_zero.base_wins == 0 and res_zero.ties == 8
    assert res_zero.effect == 0.0
    assert res_zero.verdict is Verdict.BETTER

    nonzero_floor = Dimension("wall", Family.COST, minimum_gain=1.0, unit="s",
                              minimum_gain_source="fixture")
    res_min = compare_dimension(nonzero_floor, base, candidate)
    assert res_min.verdict is Verdict.BELOW_MINIMUM
    assert not res_min.regressed


def test_custom_alpha_is_recorded_faithfully_and_sets_minimum_discordant_pairs():
    """``as_dict`` must record the alpha actually used, and power checks must scale with it."""

    from moldarwin.research.revision_score import minimum_discordant_pairs

    assert minimum_discordant_pairs(0.05) == 6
    assert minimum_discordant_pairs(0.01) == 8

    tasks = [f"task-{i:02d}" for i in range(10)]
    base_7 = dict.fromkeys(tasks, "withheld")
    cand_7 = {task: ("admitted" if i < 7 else "withheld") for i, task in enumerate(tasks)}
    under = compare_dimension(WARRANT, base_7, cand_7, alpha=0.01)
    assert under.verdict is Verdict.UNDERPOWERED
    assert under.alpha == 0.01
    assert under.as_dict()["alpha"] == 0.01

    cand_8 = {task: ("admitted" if i < 8 else "withheld") for i, task in enumerate(tasks)}
    resolved = compare_dimension(WARRANT, base_7, cand_8, alpha=0.01)
    assert resolved.verdict is Verdict.BETTER
    assert resolved.as_dict()["alpha"] == 0.01


def test_extra_waivers_in_a_second_warrant_dimension_are_not_ignored():
    """``compare_revision`` must inspect waivers across every WARRANT dimension, not only the first."""

    warrant_a = Dimension("warrant_a", Family.WARRANT)
    warrant_b = Dimension("warrant_b", Family.WARRANT)
    base_a = dict.fromkeys(TASKS, "withheld")
    cand_a = dict.fromkeys(TASKS, "admitted")
    base_b = dict.fromkeys(TASKS, "admitted")
    cand_b = {t: ("admitted_under_waiver" if i < 2 else "admitted") for i, t in enumerate(TASKS)}

    comp = compare_revision(
        dimensions=[(warrant_a, base_a, cand_a), (warrant_b, base_b, cand_b)],
        assessment_role="independent_validation",
        base_catalogue_digest="a" * 64,
        candidate_catalogue_digest="a" * 64,
        declared_scope=["all"],
    )
    assert comp.waiver_change == 2
    assert comp.adoption is Adoption.SCOPED
    assert any("waived 2 more" in r for r in comp.reservations)
