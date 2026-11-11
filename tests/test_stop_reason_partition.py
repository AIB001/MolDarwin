"""A round that used its whole grant must not record what a round that stopped short records.

The defect these tests pin, in the form the hardening criterion asks for: name the two records --
the correct one and the mistaken one -- and show that they were byte-identical.
:func:`test_before_the_partition_the_two_rounds_record_the_same_reason` does exactly that against
the value the planner still returns, which is the value rounds used to record, and the tests after
it show the recorded reason now separating them.

The mechanism quantity is counted in
:func:`test_mechanism_count_over_a_constructed_corpus`, and it is **constructed**: these campaigns
are built by this file. No real campaign store exists on this machine, so the real-record
incidence is reported as not obtained rather than estimated -- hard constraint 7.

Nothing here asserts that more spend is better. The partition exists so that a deliberate reserve
and an allowance nobody attempted to use are different recorded facts; the measurement behind it
is that passing tasks used fewer turns than failing ones.
"""

from __future__ import annotations

import pytest

from etalon.active import (
    ActiveCampaign,
    CampaignSpec,
    CampaignStore,
    Candidate,
    Endpoint,
    Evaluation,
)
from etalon.active.budget import confirmation_guard
from etalon.active.rounds import (
    EXPLAINS_A_SHORT_ROUND,
    READY,
    READY_EXHAUSTED,
    READY_REASONS,
    READY_SHORT_RESERVE_NOT_OBTAINED,
    READY_SHORT_RESERVED,
    READY_SHORT_UNRESERVED,
    SHORT_ROUND_EXPLAINED,
    SHORT_ROUND_REASON_NOT_OBTAINED,
    is_ready,
    partition_reason,
)


def campaign(tmp_path, *, name="journal", candidates=6, batch_size=2, budget=20.0, **settings):
    """A campaign whose granted slots and available candidates are set independently.

    ``candidates`` below ``batch_size`` is how a short round is constructed without refusing
    anything: the policy offers every candidate it may, which is fewer than the grant, and the
    planner still reports ``ready``.
    """

    store = CampaignStore(tmp_path / f"{name}.sqlite")
    endpoint = Endpoint("objective", "target", "score", "u", "test/1", 1, requires_handoff=False)
    store.configure(CampaignSpec(endpoint.id, budget, "quotes", "vector/1",
                                 batch_size=batch_size, **settings), [endpoint])
    store.add_candidates([Candidate(f"m{i}", "CCO", (float(i),)) for i in range(candidates)])

    def execute(action, candidate, endpoint, grant):
        return Evaluation(candidate.id, endpoint.id, candidate.features[0], endpoint.units,
                          endpoint.cost)

    return ActiveCampaign(store, execute)


def overspending_campaign(tmp_path, *, name="overrun"):
    """A campaign whose tool charges above its reservation, so a round is cut off mid-loop.

    This is how ``budget_exhausted`` is reached from inside the round rather than from planning:
    the policy never offers a choice it cannot afford, so the only way to run out part-way through
    a granted batch is a real charge above the quote -- which is kept rather than rewritten.
    """

    store = CampaignStore(tmp_path / f"{name}.sqlite")
    endpoint = Endpoint("objective", "target", "score", "u", "test/1", 1, requires_handoff=False)
    store.configure(CampaignSpec(endpoint.id, 20.0, "quotes", "vector/1", batch_size=4), [endpoint])
    store.add_candidates([Candidate(f"m{i}", "CCO", (float(i),)) for i in range(6)])
    return ActiveCampaign(store, lambda a, c, e, g: Evaluation(
        c.id, e.id, c.features[0], e.units, 19.0))


def two_endpoint_campaign(tmp_path, *, name="decision", batch_size=4, **settings):
    """A ``decision_aware`` campaign, which is the one policy that represents a reserve."""

    spec = CampaignSpec("high", 40.0, "quote", "test/1", policy="decision_aware",
                        batch_size=batch_size, **settings)
    high = Endpoint("high", "t", "reference", "u", "h1", 5, requires_handoff=False)
    low = Endpoint("low", "t", "proxy", "v", "l1", 1, requires_handoff=False)
    store = CampaignStore(tmp_path / f"{name}.sqlite")
    store.configure(spec, [high, low])
    store.add_candidates([Candidate(f"m{i}", "CCO", (float(i),)) for i in range(8)])
    return ActiveCampaign(store, lambda a, c, e, g: Evaluation(c.id, e.id, c.features[0], e.units,
                                                               e.cost))


# -- the before/after demonstration ------------------------------------------------------------


def test_before_the_partition_the_two_rounds_record_the_same_reason(tmp_path):
    """The two records this change exists for, shown byte-identical before it.

    ``_plan_snapshot`` still returns the unpartitioned planning reason, and that string is what a
    round used to record. A round that fills its whole grant and a round that fills a quarter of it
    produce the same one, so nothing in the record could tell a thorough answer from a cheap one.
    """

    exhausted = campaign(tmp_path, name="exhausted", candidates=6, batch_size=2)
    short = campaign(tmp_path, name="short", candidates=1, batch_size=4)

    assert exhausted.plan()[2] == READY
    assert short.plan()[2] == READY
    # The old record, reconstructed: everything a round wrote about why it stopped.
    assert {"stop_reason": exhausted.plan()[2]} == {"stop_reason": short.plan()[2]}
    # And the slot counts that would have distinguished them were computable all along.
    assert len(exhausted.plan()[1]) == 2 and len(short.plan()[1]) == 1


def test_after_the_partition_the_recorded_reasons_differ(tmp_path):
    exhausted = campaign(tmp_path, name="exhausted", candidates=6, batch_size=2)
    short = campaign(tmp_path, name="short", candidates=1, batch_size=4)

    full = exhausted.run_round()
    partial = short.run_round()

    assert full["stop_reason"] == READY_EXHAUSTED
    assert partial["stop_reason"] == READY_SHORT_UNRESERVED
    assert full["stop_reason"] != partial["stop_reason"]
    # In the record and not only in the return value: the round row is what survives the session.
    assert exhausted.store.rounds()[0]["stop_reason"] == READY_EXHAUSTED
    assert short.store.rounds()[0]["stop_reason"] == READY_SHORT_UNRESERVED


def test_the_record_carries_granted_beside_used_and_the_reserve_basis(tmp_path):
    short = campaign(tmp_path, name="short", candidates=1, batch_size=4)
    short.run_round()
    accounting = short.store.rounds()[0]["slot_accounting"]

    assert accounting["slots_granted"] == 4
    assert accounting["slots_used"] == 1
    assert accounting["slots_unused"] == 3
    assert accounting["exhausted"] is False
    assert accounting["counted_at"] == "round_end"
    assert accounting["planning_reason"] == READY
    # Zero with a stated reason, never a bare zero: "no reserve was represented" and "no reserve
    # was wanted" are different facts.
    reserve = accounting["confirmation_reserve"]
    assert reserve["quote"] == 0.0 and reserve["armed"] is False
    assert "none is represented, not because none was wanted" in reserve["basis"]
    # Every branch carries the same keys, so a reader cannot mistake an omitted count for a zero.
    assert set(reserve) >= {"armed", "quote", "eligible_candidates", "confirmation_reserve", "basis"}
    assert accounting["evidence"]["slots_granted"].startswith("measured_here")


def test_a_deliberate_reserve_is_named_apart_from_an_unexplained_short_round(tmp_path):
    """The one principled basis available, rather than a threshold invented for the occasion."""

    run = two_endpoint_campaign(tmp_path, batch_size=4, confirmation_reserve=1)
    outcome = run.run_round()

    assert outcome["stop_reason"] == READY_SHORT_RESERVED
    reserve = outcome["slot_accounting"]["confirmation_reserve"]
    assert reserve["armed"] is True and reserve["quote"] > 0
    assert reserve["basis"].startswith("measured_here: min(confirmation_reserve, eligible)")
    assert reserve["objective_unit_quote_evidence"].startswith(("measured_here", "convention"))


def test_a_campaign_that_wanted_no_reserve_reads_differently_from_one_that_cannot_hold_it(tmp_path):
    armed = two_endpoint_campaign(tmp_path, name="armed", confirmation_reserve=1)
    declined = two_endpoint_campaign(tmp_path, name="declined", confirmation_reserve=0)

    assert armed.run_round()["stop_reason"] == READY_SHORT_RESERVED
    outcome = declined.run_round()
    assert outcome["stop_reason"] == READY_SHORT_UNRESERVED
    assert "confirmation_reserve is 0" in outcome["slot_accounting"]["confirmation_reserve"]["basis"]


# -- what must not change ----------------------------------------------------------------------


@pytest.mark.parametrize("reason", sorted(SHORT_ROUND_EXPLAINED))
def test_a_reason_that_already_explained_a_short_round_is_never_reclassified(reason):
    """Taken from the record layer, which owns the vocabulary because it writes it.

    These name a round that was cut off -- refused, out of budget, overtaken by new evidence -- and
    those demand different responses from an allowance nobody attempted to use. Reclassifying them
    would lose the diagnosis.

    The source used to be `hooks/budget_floor.EXPLAINED_STOPS`, which made this test depend on an
    advisory module's copy of the vocabulary and quietly changed what it covered when that copy
    was derived. Drift between the two is now its own test, below.
    """

    recorded, accounting = partition_reason(reason, slots_granted=8, slots_used=1,
                                            reserve={"quote": 0.0, "basis": "x"})
    assert recorded == reason
    assert accounting["partitioned"] is False
    assert reason in accounting["partition_note"]


def test_a_short_round_does_not_stop_the_campaign(tmp_path):
    """The partition names the slack. It must not change when a campaign stops, in either direction."""

    run = campaign(tmp_path, candidates=6, batch_size=4)
    result = run.run(max_rounds=2)

    assert len(result["rounds"]) == 2
    assert all(is_ready(row["stop_reason"]) for row in result["rounds"])
    assert result["stop_reason"] == "round_limit"


def test_every_partitioned_reason_still_means_the_round_completed():
    for reason in READY_REASONS:
        assert is_ready(reason)
    assert not is_ready("budget_exhausted")


def test_an_uncountable_reserve_is_not_obtained_rather_than_zero():
    """Hard constraint 7. Zero is the value a missing reserve most resembles."""

    recorded, accounting = partition_reason(READY, slots_granted=8, slots_used=2, reserve=None)
    assert recorded == READY_SHORT_RESERVE_NOT_OBTAINED
    assert "not obtained" in accounting["partition_note"]

    quoted, _ = partition_reason(READY, slots_granted=8, slots_used=2,
                                 reserve={"quote": None, "basis": "not_obtained: no spec"})
    assert quoted == READY_SHORT_RESERVE_NOT_OBTAINED


def test_the_reserve_report_and_the_reservation_guard_are_one_arithmetic(tmp_path):
    """A report that defined "reserved on purpose" its own way would be a heuristic.

    ``CampaignStore.reserve`` raises ``BudgetExhausted`` on this quantity, so the quantity reported
    beside a round's reason is the same function the transaction calls, not a second definition.
    """

    run = two_endpoint_campaign(tmp_path, confirmation_reserve=1)
    spec, endpoints = run.store.configuration()
    history = run.store.observations()
    guard = confirmation_guard(spec, endpoints, run.store.candidates().values(), {}, history)

    assert guard["armed"] is True
    assert guard["quote"] == min(spec.confirmation_reserve, 8) * endpoints["high"].cost
    assert guard["eligible_candidates"] == 8 and guard["candidates_examined"] == 8


def test_planning_says_where_the_count_was_taken(tmp_path):
    """``inspect`` partitions the same way and says the count is of offered slots, not used ones."""

    run = campaign(tmp_path, candidates=1, batch_size=4)
    result = run.inspect()

    assert result["stop_reason"] == READY_SHORT_UNRESERVED
    assert result["slot_accounting"]["counted_at"] == "planning"
    assert "before any dispatch" in result["slot_accounting"]["evidence"]["slots_used"]


# -- the mechanism quantity --------------------------------------------------------------------


def test_mechanism_count_over_a_constructed_corpus(tmp_path):
    """Rounds whose recorded reason now separates short from exhausted, over rounds examined.

    Constructed, and labelled constructed: the corpus is the campaigns below and nothing else. The
    numerator counts rounds that used to record the bare ``ready``; the denominator is every
    completed round in the corpus, including the ones this change deliberately leaves alone.
    """

    corpus = [
        campaign(tmp_path, name="a", candidates=6, batch_size=2),   # fills its grant
        campaign(tmp_path, name="b", candidates=1, batch_size=4),   # short, no reserve
        campaign(tmp_path, name="c", candidates=2, batch_size=4),   # short, no reserve
        two_endpoint_campaign(tmp_path, name="d", confirmation_reserve=1),  # short, reserve held
        # A tool charging above its reservation stops the round mid-loop, which records
        # "budget_exhausted": that already explains its slack and is left exactly as it was.
        overspending_campaign(tmp_path, name="e"),
    ]
    for run in corpus:
        run.run(max_rounds=2)

    rounds = [row for run in corpus for row in run.store.rounds()]
    examined = len(rounds)
    partitioned = [row for row in rounds if row["stop_reason"] in READY_REASONS - {READY}]
    unchanged = [row for row in rounds if row["stop_reason"] not in READY_REASONS]

    # Every round that used to record the bare "ready" now records which case it was, and every
    # round that already explained itself is untouched.
    assert examined == len(partitioned) + len(unchanged)
    assert not any(row["stop_reason"] == READY for row in rounds)
    assert {row["stop_reason"] for row in partitioned} == {
        READY_EXHAUSTED, READY_SHORT_UNRESERVED, READY_SHORT_RESERVED}
    assert {row["stop_reason"] for row in unchanged} == {"budget_exhausted"}
    # The figure this test exists to report, as a count with its denominator: 6 of 7 rounds in
    # this constructed corpus now separate short from exhausted where they previously recorded the
    # same "ready" -- two filling their grant, two short with no reserve, two short against a
    # represented reserve. The seventh was cut off by a charge above its reservation and keeps the
    # reason that already explained it.
    assert (len(partitioned), examined) == (6, 7)
    for row in partitioned:
        assert row["slot_accounting"]["slots_granted"] >= row["slot_accounting"]["slots_used"]


# -- the vocabulary has one owner ---------------------------------------------------------------


def test_the_advisory_hook_derives_the_vocabulary_instead_of_keeping_a_second_copy():
    """The drift this derivation ended, and the check that it cannot start again.

    `hooks/budget_floor.py` listed these reasons itself until this round, and the two copies had
    already parted company: the hook was missing `selected_action` and all three `ready_short_*`
    values, so a round that recorded its reason was counted in
    `rounds_short_recorded_without_a_reason`. That is the debt pattern this round named -- a
    feature that enumerates its subjects instead of reading a property they declare -- and the
    repair is the direction of the dependency, not a second list kept in step by hand.
    """

    import etalon.hooks.budget_floor as hook

    assert set(hook.EXPLAINED_STOPS) == set(EXPLAINS_A_SHORT_ROUND)
    assert set(hook.REASON_NOT_OBTAINED_STOPS) == set(SHORT_ROUND_REASON_NOT_OBTAINED)
    assert not set(hook.EXPLAINED_STOPS) & set(hook.REASON_NOT_OBTAINED_STOPS)
    assert READY not in hook.EXPLAINED_STOPS, "the value that explains nothing is not an explanation"


def test_a_reason_whose_accounting_failed_is_reported_apart_from_a_reason_nobody_gave():
    """Three states, because hard constraint 7 makes "not obtained" its own answer.

    Folding `ready_short_reserve_not_obtained` into the explained set would claim the shortness
    was accounted for when the accounting is exactly what failed; folding it into the missing
    count would say nobody gave a reason when one was recorded. Both readings are available and
    both are wrong, which is why the hook reports a third number.
    """

    assert READY_SHORT_RESERVE_NOT_OBTAINED not in EXPLAINS_A_SHORT_ROUND
    assert READY_SHORT_RESERVE_NOT_OBTAINED in SHORT_ROUND_REASON_NOT_OBTAINED
    assert SHORT_ROUND_EXPLAINED <= EXPLAINS_A_SHORT_ROUND, "pre-existing reasons stay explained"
    assert {READY_SHORT_RESERVED, READY_SHORT_UNRESERVED} <= EXPLAINS_A_SHORT_ROUND


@pytest.mark.parametrize("already", sorted(
    {READY_SHORT_RESERVED, READY_SHORT_UNRESERVED, READY_SHORT_RESERVE_NOT_OBTAINED}))
def test_partitioning_a_reason_this_function_already_wrote_leaves_it_alone(already):
    """Idempotence, and the reason it is not a nicety.

    These three are this function's own outputs. Gating on `READY_REASONS` -- which contains them,
    correctly, for `is_ready`'s loop semantics -- let a second pass re-derive the reason from
    whatever `reserve` that caller held, so a recorded `ready_short_reserve_represented` could
    come back as `ready_short_no_reserve`: a record rewritten with nothing saying it had been.
    The gate is `!= READY`, which is what `partition_reason`'s own docstring always said.
    """

    recorded, accounting = partition_reason(already, slots_granted=8, slots_used=1,
                                            reserve={"quote": 0.0, "basis": "none represented"})
    assert recorded == already
    assert accounting["partitioned"] is False
    assert already in accounting["partition_note"]
    assert accounting["planning_reason"] == already
