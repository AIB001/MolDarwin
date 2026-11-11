"""Whether a round stopped having used what it was granted, or stopped short.

``active/runner.py`` recorded ``{"stop_reason": "ready"}`` for a round that used 8 of 8 granted
slots and for a round that used 2 of 8 and simply stopped. The two records were byte-identical, so
a cheap, under-explored answer and a thorough one could not be told apart afterwards -- the
precise harm the hardening criterion is about: *harden in code where a mistake becomes
indistinguishable from a correct record later.* ``len(summary["actions"]) < spec.batch_size`` was
computable by any reader and computed by nothing.

**This is not a request to spend more, and it must not become one.** On an external benchmark a
minimally-scaffolded agent used 2.0-2.9 of 8 structure-oracle calls and 2.4-6.0 of 15
property-oracle calls, and the tasks that *passed* used fewer turns (mean 12.0) than those that
failed (18.3). So iteration is not the lever, and a floor here would refuse correct behaviour.
Nothing in this module gates a spend, changes selection, or stops a campaign: it names two cases
apart in the record. How many candidates to explore and when to stop exploring stay the host's,
per ``docs/thin-harness/HARDENING_CRITERION.md`` §3.

**No new threshold.** The partition is exact -- slots used against slots granted, no fraction --
and the only judgement in it, whether a short round deliberately held something back, is
recomputed from the campaign's own confirmation guard via
:func:`etalon.active.budget.confirmation_guard`, which is the arithmetic the reservation
transaction itself raises ``BudgetExhausted`` on. Where that guard is not armed the reserve is
zero **with a stated reason**, because "no reserve was represented" and "no reserve was wanted"
are different facts; where its quantity cannot be recomputed the reason says the reserve was not
obtained rather than calling it zero, per hard constraint 7.

Every ``stop_reason`` that already explained a short round keeps its exact value. Those are
reasons a round was cut off -- a refusal, an exhausted budget, a changed state -- and
reclassifying them would lose the diagnosis that distinguishes them from an allowance nobody
attempted to use. Only ``"ready"``, the one value that explained nothing, is partitioned.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The planning reason this module partitions: choices existed and nothing refused them.
READY = "ready"

#: The round used every slot it was granted.
READY_EXHAUSTED = "ready_slots_exhausted"

#: The round stopped short and the campaign represents a deliberate confirmation reserve.
READY_SHORT_RESERVED = "ready_short_reserve_represented"

#: The round stopped short and no reserve is represented. The accounting block carries why, and
#: "nobody wanted one" and "the policy cannot express one" read differently there.
READY_SHORT_UNRESERVED = "ready_short_no_reserve"

#: The round stopped short and the reserve quantity could not be recomputed. Reported as not
#: obtained rather than as zero: zero is what a missing reserve most resembles.
READY_SHORT_RESERVE_NOT_OBTAINED = "ready_short_reserve_not_obtained"

#: Every reason meaning "this round completed and the campaign may continue". ``READY`` stays a
#: member so a planning reason and a recorded one can be tested the same way, and so a campaign
#: resuming over records written before this change keeps its loop semantics.
READY_REASONS = frozenset({READY, READY_EXHAUSTED, READY_SHORT_RESERVED, READY_SHORT_UNRESERVED,
                           READY_SHORT_RESERVE_NOT_OBTAINED})

#: Reasons that already explain a short round, and are therefore never reclassified. Taken from
#: every assignment in ``active/runner.py``; the vocabulary is shared with
#: ``hooks/budget_floor.EXPLAINED_STOPS``, and it is restated here rather than imported because
#: that hook's output is advisory and a record must not depend on an advisory module.
SHORT_ROUND_EXPLAINED = frozenset({
    "empty_pool",
    "no_executable_endpoints",
    "confirmation_unaffordable",
    "budget_exhausted",
    "no_eligible_actions",
    "protocol_limit_reached",
    "state_changed",
    "reservation_rejected",
    "selected_action",
})

#: Every reason that explains a short round, the pre-existing ones plus the two new values
#: that carry an explanation of their own. This is the set a reader should test against, and
#: it is why `hooks/budget_floor.py` derives its `EXPLAINED_STOPS` from here instead of
#: keeping a second list: before it did, the hook's list was missing `selected_action` and
#: all three `ready_short_*` values, so a round that recorded its reason was reported as a
#: round recorded without one. The dependency runs hook -> record and never the other way,
#: for the reason stated above `SHORT_ROUND_EXPLAINED`.
EXPLAINS_A_SHORT_ROUND = SHORT_ROUND_EXPLAINED | {READY_SHORT_RESERVED, READY_SHORT_UNRESERVED}

#: The third state, and the reason this is not a two-way partition. A round whose reserve
#: quantity could not be recomputed has neither been explained nor silently left bare: hard
#: constraint 7 says such a quantity is reported as not obtained, and folding it into the
#: explained set would claim the shortness was accounted for when the accounting is exactly
#: what failed. `READY` is absent from all three sets on purpose -- it is the value that
#: explained nothing, which is what this module exists to partition.
SHORT_ROUND_REASON_NOT_OBTAINED = frozenset({READY_SHORT_RESERVE_NOT_OBTAINED})


def is_ready(reason: str) -> bool:
    """Whether a recorded reason means the round finished and the campaign may continue."""

    return reason in READY_REASONS


#: Where a partition was taken. At ``planning`` nothing has been dispatched yet, so the count is
#: the slots the policy offered; at ``round_end`` it is the actions the round resolved. Kept
#: in the block because the same reason string means a slightly different measured thing in each,
#: and a reader should not have to infer which.
COUNTED_AT = ("planning", "round_end")


def partition_reason(reason: str, *, slots_granted: int, slots_used: int,
                     reserve: Mapping[str, Any] | None = None,
                     slots_planned: int | None = None,
                     counted_at: str = "round_end") -> tuple[str, dict[str, Any]]:
    """Name a short round apart from an exhausted one, and say what the slack was for.

    Args:
        reason: The reason the round would have recorded. Anything other than ``"ready"`` is
            returned unchanged, because it already explains the round's slack.
        slots_granted: The slots the round was granted, i.e. ``CampaignSpec.batch_size``.
        slots_used: Actions the round actually reserved and resolved.
        reserve: The output of :func:`etalon.active.budget.confirmation_guard`, or ``None`` where
            it was not recomputed.
        slots_planned: Slots the policy offered, where the caller knows it. Recorded because a
            round can be short for two different upstream reasons -- the policy offered fewer
            choices than the grant, or fewer of the offered choices were dispatched -- and the
            record should not need the reader to guess which.
        counted_at: ``"round_end"`` where ``slots_used`` counts resolved actions, or
            ``"planning"`` where it counts the slots the policy offered before any dispatch.

    Returns:
        The reason to record, and the accounting block to record beside it. The block is returned
        even when the reason is unchanged, because granted-beside-used is worth recording for
        every round and costs nothing.
    """

    if type(slots_granted) is not int or slots_granted < 1:
        raise ValueError("slots_granted must be the positive integer the round was granted")
    if type(slots_used) is not int or slots_used < 0:
        raise ValueError("slots_used must be a nonnegative integer")
    if counted_at not in COUNTED_AT:
        raise ValueError(f"counted_at must be one of {COUNTED_AT}")
    quote = None if reserve is None else reserve.get("quote")
    exhausted = slots_used >= slots_granted
    accounting: dict[str, Any] = {
        "slots_granted": slots_granted,
        "slots_planned": slots_planned,
        "slots_used": slots_used,
        "slots_unused": max(0, slots_granted - slots_used),
        "exhausted": exhausted,
        "counted_at": counted_at,
        "planning_reason": reason,
        "confirmation_reserve": dict(reserve) if reserve is not None else None,
        "evidence": {
            "slots_granted": "measured_here: CampaignSpec.batch_size, the slots this round was granted",
            "slots_used": ("measured_here: the actions this round reserved and resolved"
                           if counted_at == "round_end" else
                           "measured_here: the slots the policy offered, before any dispatch"),
            "deliberate_reserve": (None if reserve is None else reserve.get("basis")),
        },
        "method": (
            "slots_used against slots_granted exactly; there is no fraction and no threshold. A "
            "deliberate reserve is the campaign's own confirmation guard recomputed, not a "
            "judgement about whether the slack was reasonable"
        ),
        "not_a_spend_signal": (
            "Under-use is reported, never pressed. The measurement behind this partition is that "
            "passing tasks used fewer turns (mean 12.0) than failing ones (18.3), so more "
            "iteration is not the lever; what the slack earns is a name"
        ),
    }
    # `READY` and not `READY_REASONS`. The two differ on the three `ready_short_*` values,
    # which are this function's own *outputs*: gating on membership of `READY_REASONS` let a
    # second pass re-derive an already-recorded reason from whatever `reserve` the second
    # caller happened to supply, so `ready_short_reserve_represented` could come back as
    # `ready_short_no_reserve` -- a recorded reason rewritten with no trace that it had been.
    # `READY_REASONS` is the right set for `is_ready`'s loop semantics and the wrong one here.
    # Latent rather than live: all three call sites in `active/runner.py` pass a fresh planning
    # reason. The docstring above already stated the narrow reading, so this is the code
    # catching up with it, in the direction that cannot rewrite a record.
    if reason != READY:
        accounting["partitioned"] = False
        accounting["partition_note"] = (
            f"{reason!r} already explains a short round, so it is recorded unchanged"
            if reason in EXPLAINS_A_SHORT_ROUND or reason in SHORT_ROUND_REASON_NOT_OBTAINED else
            f"{reason!r} is not a reason this partition knows, so it is recorded unchanged rather "
            "than interpreted"
        )
        return reason, accounting

    accounting["partitioned"] = True
    if exhausted:
        accounting["partition_note"] = (
            "the round used every slot it was granted, which is the case that used to record the "
            "same reason as a round that stopped short"
        )
        return READY_EXHAUSTED, accounting
    if quote is None:
        accounting["partition_note"] = (
            "the round stopped short and the confirmation guard's quantity could not be "
            "recomputed, so whether anything was held back deliberately is not obtained"
        )
        return READY_SHORT_RESERVE_NOT_OBTAINED, accounting
    if float(quote) > 0.0:
        accounting["partition_note"] = (
            "the round stopped short and the campaign represents a deliberate confirmation "
            "reserve of this quote, which is the only representation of a deliberate reserve it has"
        )
        return READY_SHORT_RESERVED, accounting
    accounting["partition_note"] = (
        "the round stopped short and no reserve is represented. The reserve's own basis says "
        "whether the policy cannot express one or the campaign declined it; the slack is not "
        "accounted for by a reserve either way"
    )
    return READY_SHORT_UNRESERVED, accounting


__all__ = [
    "COUNTED_AT",
    "READY",
    "READY_EXHAUSTED",
    "READY_REASONS",
    "READY_SHORT_RESERVED",
    "READY_SHORT_RESERVE_NOT_OBTAINED",
    "READY_SHORT_UNRESERVED",
    "EXPLAINS_A_SHORT_ROUND",
    "SHORT_ROUND_EXPLAINED",
    "SHORT_ROUND_REASON_NOT_OBTAINED",
    "is_ready",
    "partition_reason",
]
