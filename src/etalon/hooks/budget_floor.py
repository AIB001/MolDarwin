"""Granted beside consumed, partitioned by reason, at the moment the agent declares ready.

**The measurement.** Against an external benchmark, a minimally-scaffolded agent used 2.0-2.9 of 8
structure-oracle calls and 2.4-6.0 of 15 property-oracle calls, and declared itself finished. Every
quantity gate in ``active/`` is an upper bound: ``active/budget.py`` is three functions about not
exceeding an allowance -- ``fits_budget``, ``affordable_capacity`` and a deliberately conservative
``cost_quote`` -- and none about failing to use one. ``Endpoint.max_replicates`` is enforced as a
ceiling in three places and there is no ``min_replicates``. ``active/store.py``'s ``_balance``
returns exactly ``{"budget", "spent", "reserved", "remaining"}``, and ``remaining`` is read only to
decide whether the next action fits; nothing anywhere reads a large ``remaining`` as a problem.
``len(summary["actions"]) < spec.batch_size`` is computable by any reader and computed by nothing.

**Why this is a hook and not a floor in the code.** Under-spend is sometimes the designed outcome.
``active/decision_benchmark.py`` states it: *"Equal budget means equal caps and charged warm starts,
not necessarily equal expenditure: a confirmation guard may deliberately leave unusable budget."*
``protocol_stopping_benchmark.py`` reports ``budget_saved`` as a virtue. And the measurement that
motivates reporting rather than pushing is input 4's own: passing tasks used **fewer** turns (mean
12.0) than failing ones (18.3), so a harness that reacted to under-use by encouraging spend would
optimise the quantity the data says is not the problem. A refusal here would refuse correct
behaviour. What under-use earns is visibility, so that slack and its reason arrive together.

**Why the partition is the whole difficulty.** A low ratio is consistent with an agent that stopped
early, an agent that was refused, and an agent that could not afford the next call, and those demand
opposite responses. So the report is four states, not one number, and the ``deliberately_reserved``
state has a principled basis rather than a heuristic: it is recomputed from
``CampaignSpec.confirmation_reserve`` and the guard at ``active/store.py``'s reservation
transaction, which is the quantity that raises ``BudgetExhausted("proxy action would consume the
objective confirmation budget")``. Where the campaign's policy does not arm that guard, the reserve
is **zero with a stated reason** rather than absent, because "no reserve was represented" and "no
reserve was wanted" are different facts.

**The second signal, which costs nothing.** ``active/runner.py``'s round summary records a
cumulative balance and a ``stop_reason`` of ``"ready"``, so a round that used 2 of 8 slots and one
that used 8 of 8 are recorded identically. This hook reports, per round, the slots granted
(``spec.batch_size``), the slots used (``len(actions)``) and the recorded ``stop_reason`` -- and the
count of rounds whose ``stop_reason`` is ``"ready"`` while their slot use was short. That count is
the architecture review's own mechanism quantity for this change.

Nothing here writes. The store is opened ``read_only=True``; hard constraint 6 is not at risk,
because this reads one store and reports per store with no aggregate across the three.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from etalon.hooks.session import Interruption, field, quiet, rounds_of

HOOK = "budget_floor"

#: Interrupt below this fraction of the granted allowance consumed, when nothing was reserved.
#:
#: Evidence: ``convention``. Nothing has measured where the real boundary is, and this is not
#: dressed as a measurement. It was *chosen against* measurements and that is a different claim:
#: the observed under-use was 2.0-2.9 of 8 (0.25-0.36) and 2.4-6.0 of 15 (0.16-0.40), so a floor at
#: one half sits above every measured under-use and below full consumption. A campaign that
#: deliberately stops at a third of its allowance will trip this and should, because the hook asks
#: for the reason rather than for the spend.
CONSUMPTION_FLOOR = 0.5

#: Report a round as short when its slot use is below this fraction of ``batch_size``. Also
#: ``convention``, and deliberately looser than :data:`CONSUMPTION_FLOOR`: a single short round is
#: ordinary, and what matters is how many of them were recorded as ``"ready"``.
SLOT_FLOOR = 0.75

#: The ``stop_reason`` values that already explain a short round. A round stopping for one of these
#: is not silent about its slack, so it is counted and not flagged. Taken from every assignment in
#: ``active/runner.py``; ``"ready"`` is deliberately absent, which is the point of the hook.
def _short_round_vocabulary() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(reasons that explain a short round, reasons whose explanation was not obtained).

    Derived from ``active/rounds.py``, which owns the vocabulary because it is the module
    that *writes* these values; this hook only reads them. The dependency runs hook ->
    record and never the other way, which is the same direction ``rounds.py`` states for
    itself: a record must not depend on an advisory module.

    It was a literal list here until this round, and the two copies had already drifted:
    this one was missing ``selected_action`` and all three ``ready_short_*`` values, so a
    round that recorded its reason was counted as a round recorded without one. The import
    is deferred because ``etalon.active`` pulls the runner -- 28 ms measured, Evidence
    ``measured_here`` -- and a session hook must stay cheap to import.
    """

    from etalon.active.rounds import EXPLAINS_A_SHORT_ROUND, SHORT_ROUND_REASON_NOT_OBTAINED

    return tuple(sorted(EXPLAINS_A_SHORT_ROUND)), tuple(sorted(SHORT_ROUND_REASON_NOT_OBTAINED))


def __getattr__(name: str):
    """Resolve the derived vocabularies on first attribute access, then cache them.

    PEP 562, so that ``EXPLAINED_STOPS`` stays an importable module constant without paying
    the record layer's import cost for every session hook that loads this file.
    """

    if name in ("EXPLAINED_STOPS", "REASON_NOT_OBTAINED_STOPS"):
        explained, not_obtained = _short_round_vocabulary()
        globals()["EXPLAINED_STOPS"] = explained
        globals()["REASON_NOT_OBTAINED_STOPS"] = not_obtained
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def confirmation_reserve_quote(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Recompute the confirmation guard's own quantity, or say why it is not armed.

    This is ``active/store.py``'s guard arithmetic read from a snapshot instead of from inside the
    reservation transaction: ``min(confirmation_reserve, eligible) * cost_quote(objective, history)``,
    where ``eligible`` counts candidates still under the objective endpoint's ``max_replicates`` and,
    where the endpoint requires one, holding a handoff.

    Recomputed rather than copied because the guard is the only representation of a deliberate
    reserve that exists, and a partition that invented its own definition of "reserved on purpose"
    would be a heuristic wearing a mechanism's clothes. Where a field the arithmetic needs is
    missing from the snapshot, the quote is reported as not taken -- never as zero, which would move
    the whole of a real reserve into ``not_attempted``.
    """

    spec = snapshot.get("spec")
    endpoints = snapshot.get("endpoints") or {}
    objective_id = getattr(spec, "objective", None)
    reserve = getattr(spec, "confirmation_reserve", None)
    policy = getattr(spec, "policy", None)
    objective = endpoints.get(objective_id) if isinstance(endpoints, dict) else None

    if spec is None or objective is None or not isinstance(reserve, int):
        return {
            "quote": None,
            "armed": False,
            "basis": "not_taken: the snapshot carries no spec, objective endpoint or reserve count",
        }
    if policy != "decision_aware":
        return {
            "quote": 0.0,
            "armed": False,
            "basis": (
                f"measured_here: the guard arms only under policy 'decision_aware' and this "
                f"campaign declares {policy!r}, so no budget is reserved on purpose. The reserve is "
                "zero because none is represented, not because none was wanted."
            ),
        }
    if not reserve or not getattr(objective, "queryable", False):
        return {
            "quote": 0.0,
            "armed": False,
            "basis": (
                "measured_here: confirmation_reserve is 0 or the objective endpoint is not "
                "queryable, so the guard cannot arm"
            ),
        }

    candidates = snapshot.get("candidates") or {}
    # ``cost_quote`` reads o["result"]["cost"|"endpoint_id"|"status"], which is the shape the
    # store's own history uses; an observation row already carries those fields.
    history = [
        {"result": dict(row) if isinstance(row, Mapping) else row}
        for row in (snapshot.get("observations") or ())
    ]
    eligible = 0
    counted = 0
    for candidate in (candidates.values() if isinstance(candidates, dict) else candidates):
        counted += 1
        used = sum(
            1
            for action in (snapshot.get("actions") or ())
            if field(action, "endpoint_id") == objective_id
            and field(action, "candidate_id") == getattr(candidate, "id", None)
        )
        if used < getattr(objective, "max_replicates", 1) and (
            not getattr(objective, "requires_handoff", False) or bool(getattr(candidate, "handoff", None))
        ):
            eligible += 1

    try:
        from etalon.active.budget import cost_quote

        unit = cost_quote(objective, history)
    except Exception as error:  # noqa: BLE001 -- reported, never defaulted to a passing value
        return {
            "quote": None,
            "armed": True,
            "eligible_candidates": eligible,
            "candidates_examined": counted,
            "basis": f"not_taken: cost_quote refused ({type(error).__name__}: {error})",
        }
    return {
        "quote": min(reserve, eligible) * float(unit),
        "armed": True,
        "eligible_candidates": eligible,
        "candidates_examined": counted,
        "confirmation_reserve": reserve,
        "objective_unit_quote": float(unit),
        "basis": (
            "measured_here: min(confirmation_reserve, eligible) * cost_quote(objective, history), "
            "the same arithmetic the reservation transaction raises BudgetExhausted on"
        ),
    }


def reconcile(snapshot: dict[str, Any], balance: dict[str, Any]) -> dict[str, Any]:
    """Recompute consumption from the action rows and compare it with the store's own balance.

    This is the check that makes the partition evidence rather than arithmetic over a number the
    report was handed. The architecture review asks exactly this of the change: the reconciliation
    *is* the mechanism claim, because it establishes the report reads the records rather than
    inferring from them.

    When the rows do not carry the fields the sum needs, the comparison is reported as not taken and
    the caller stays quiet. A partition nobody could reconcile is not a finding.
    """

    rows = snapshot.get("actions") or ()
    if not isinstance(rows, (list, tuple)):
        return {"status": "not_taken", "reason": "the snapshot carries no action rows"}
    spent = 0.0
    reserved = 0.0
    missing = 0
    for row in rows:
        cost = _finite(field(row, "cost"))
        if cost is None:
            missing += 1
        else:
            spent += cost
        if field(row, "status") in {"reserved", "running"}:
            held = _finite(field(row, "reservation"))
            if held is None:
                missing += 1
            else:
                reserved += held
    executions = snapshot.get("resource_executions") or ()
    execution_spend = 0.0
    for row in executions if isinstance(executions, (list, tuple)) else ():
        cost = _finite(field(row, "cost"))
        if cost is not None:
            execution_spend += cost

    recorded_spent = _finite(field(balance, "spent"))
    if recorded_spent is None:
        return {"status": "not_taken", "reason": "the balance carries no finite spent value"}
    summed = spent + execution_spend
    agrees = math.isclose(summed, recorded_spent, rel_tol=1e-9, abs_tol=1e-9)
    return {
        "status": "reconciled" if agrees and not missing else "disagrees" if not agrees else "partial",
        "summed_from_rows": round(summed, 6),
        "recorded_spent": round(recorded_spent, 6),
        "rows_examined": len(rows),
        "rows_missing_a_cost_field": missing,
        "resource_execution_spend": round(execution_spend, 6),
        "reserved_from_rows": round(reserved, 6),
        "method": (
            "sum of actions.cost plus resource_executions.cost against balance['spent']; "
            "denominator is rows_examined"
        ),
    }


def partition(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Granted split into consumed / deliberately_reserved / not_attempted / unresolved.

    The four sum to ``granted`` exactly and the residual is reported so a reader can check that
    rather than take it on trust. ``unresolved`` is the honest home of a reservation whose true
    charge is not yet known: hard constraint 7 forbids filling an unknown charge with an estimate,
    so an outstanding action's cost is reported as held and not as spent.
    """

    balance = snapshot.get("balance") or {}
    granted = _finite(field(balance, "budget"))
    consumed = _finite(field(balance, "spent"))
    unresolved = _finite(field(balance, "reserved"))
    if granted is None or consumed is None or unresolved is None:
        return {
            "status": "not_taken",
            "reason": "the campaign balance does not carry finite budget/spent/reserved values",
        }

    reserve = confirmation_reserve_quote(snapshot)
    quote = reserve["quote"]
    free = granted - consumed - unresolved
    if quote is None:
        deliberately_reserved: float | None = None
        not_attempted: float | None = None
    else:
        # A reserve larger than what is left is not reserved; it is unaffordable, which
        # ``stop_reason == 'confirmation_unaffordable'`` already names.
        deliberately_reserved = max(0.0, min(float(quote), max(0.0, free)))
        not_attempted = free - deliberately_reserved

    states = {
        "consumed": round(consumed, 6),
        "deliberately_reserved": None if deliberately_reserved is None else round(deliberately_reserved, 6),
        "not_attempted": None if not_attempted is None else round(not_attempted, 6),
        "unresolved": round(unresolved, 6),
    }
    residual = (
        None
        if deliberately_reserved is None or not_attempted is None
        else round(granted - (consumed + deliberately_reserved + not_attempted + unresolved), 9)
    )
    return {
        "status": "taken" if residual is not None else "partial",
        "granted": round(granted, 6),
        "cost_unit": getattr(snapshot.get("spec"), "cost_unit", None),
        "states": states,
        "residual": residual,
        "additive": False,
        "additive_note": (
            "per store. RuntimeStore, CampaignStore and ResearchJournal are not merged, so no "
            "figure here is additive with another store's"
        ),
        "consumed_fraction": None if granted <= 0 else round(consumed / granted, 4),
        "deliberately_reserved_basis": reserve["basis"],
        "reserve_detail": {k: v for k, v in reserve.items() if k != "basis"},
    }


def short_rounds(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Rounds whose recorded ``stop_reason`` disagrees with their slot use."""

    spec = snapshot.get("spec")
    slots = getattr(spec, "batch_size", None)
    if not isinstance(slots, int) or slots < 1:
        return {"status": "not_taken", "reason": "the spec carries no batch_size"}
    explained_stops, not_obtained_stops = _short_round_vocabulary()
    examined = 0
    short = 0
    unexplained: list[dict[str, Any]] = []
    not_obtained: list[dict[str, Any]] = []
    for row in rounds_of(snapshot):
        actions = row.get("actions")
        if not isinstance(actions, (list, tuple)):
            continue
        examined += 1
        used = len(actions)
        if used >= slots * SLOT_FLOOR:
            continue
        short += 1
        reason = row.get("stop_reason")
        entry = {"round_id": row.get("round_id"), "slots_used": used, "slots_granted": slots,
                 "stop_reason": reason}
        # Three states, not two. A reason that could not be recomputed is reported as not
        # obtained rather than counted as missing (hard constraint 7): "nobody said why" and
        # "the accounting failed" call for different responses, and merging them would also
        # make the headline count read as more silence than the records contain.
        if reason in not_obtained_stops:
            not_obtained.append(entry)
        elif reason not in explained_stops:
            unexplained.append(entry)
    return {
        "status": "taken",
        "rounds_examined": examined,
        "rounds_short": short,
        "rounds_short_recorded_without_a_reason": len(unexplained),
        "rounds_short_whose_reason_was_not_obtained": len(not_obtained),
        "detail": unexplained[:16],
        "detail_reason_not_obtained": not_obtained[:16],
        "method": (
            f"len(summary['actions']) < batch_size * {SLOT_FLOOR}, against every recorded round; "
            "denominator is rounds_examined. A reason is explained when it is in "
            "active/rounds.EXPLAINS_A_SHORT_ROUND, reported separately when it is in "
            "SHORT_ROUND_REASON_NOT_OBTAINED, and counted as missing otherwise"
        ),
    }


def assess(database: str) -> Interruption:
    """Read one campaign store and decide whether ``ready`` deserves an interruption.

    Args:
        database: Absolute path to the campaign journal. Opened ``read_only=True``; a write through
            that handle raises before it reaches the records.
    """

    try:
        from etalon.active.store import CampaignStore

        store = CampaignStore(database, read_only=True)
        snapshot = store.snapshot()
    except Exception as error:  # noqa: BLE001
        return quiet(
            HOOK,
            f"the campaign journal could not be read, so no allowance figure was taken "
            f"({type(error).__name__}: {error})",
            database=str(database),
        )

    split = partition(snapshot)
    slots = short_rounds(snapshot)
    checked = reconcile(snapshot, snapshot.get("balance") or {})

    evidence = {
        "granted_and_consumed": "measured_here: CampaignStore(read_only=True).snapshot()['balance']",
        "deliberately_reserved": split.get("deliberately_reserved_basis"),
        "reconciliation": checked.get("method", checked.get("reason")),
        "consumption_floor": (
            f"convention: {CONSUMPTION_FLOOR}. Chosen against measured under-use of 0.25-0.36 and "
            "0.16-0.40 of the granted oracle calls; nothing has measured where the real boundary is"
        ),
        "slot_floor": f"convention: {SLOT_FLOOR}",
    }
    finding = {"partition": split, "rounds": slots, "reconciliation": checked}

    if split["status"] == "not_taken":
        return quiet(HOOK, split["reason"], **finding)
    if checked["status"] in {"not_taken", "disagrees"}:
        # Reported, never interrupted on. A partition whose consumption does not reconcile with the
        # records it was summed from is a defect in this hook or in the store, and either way it is
        # not evidence about the agent's spending.
        return quiet(
            HOOK,
            "the allowance partition did not reconcile against the action rows, so it is reported "
            "rather than acted on",
            **finding,
        )

    fraction = split["consumed_fraction"]
    reserved = split["states"]["deliberately_reserved"]
    interrupting = (
        fraction is not None
        and fraction < CONSUMPTION_FLOOR
        and (reserved is not None and reserved <= 0.0)
    )
    if not interrupting and not slots.get("rounds_short_recorded_without_a_reason"):
        return quiet(
            HOOK,
            "the granted allowance was consumed above the convention floor, or the remainder is "
            "accounted for by the confirmation reserve",
            **finding,
        )

    headline = (
        f"ready declared with {fraction:.0%} of the granted allowance consumed and nothing "
        f"deliberately reserved"
        if interrupting
        else f"{slots['rounds_short_recorded_without_a_reason']} of {slots['rounds_examined']} "
        "round(s) ran short of their slots and recorded no reason for it"
    )
    return Interruption(
        hook=HOOK,
        status="interrupt",
        headline=headline,
        finding=finding,
        evidence=evidence,
        alternatives=(
            "Say what the unused allowance is for. A reserve is a legitimate answer and is already "
            "representable: CampaignSpec.confirmation_reserve under policy 'decision_aware' is the "
            "quantity this report would have counted as deliberately_reserved.",
            "Say that the question is answered at this spend. That is also a legitimate answer, and "
            "the measurement behind this hook is that more iteration was not the lever -- passing "
            "tasks used fewer turns (mean 12.0) than failing ones (18.3).",
            "If a refusal stopped the next action, its stop_reason names it: budget_exhausted, "
            "confirmation_unaffordable and no_eligible_actions are different problems from an "
            "allowance nobody attempted to use.",
            "This hook does not ask for more spend. It asks that the slack and its reason arrive "
            "together, because a low ratio alone cannot distinguish an agent that stopped early "
            "from one that was refused.",
        ),
    )


__all__ = [
    "CONSUMPTION_FLOOR",
    "EXPLAINED_STOPS",
    "HOOK",
    "REASON_NOT_OBTAINED_STOPS",
    "SLOT_FLOOR",
    "assess",
    "confirmation_reserve_quote",
    "partition",
    "reconcile",
    "short_rounds",
]
