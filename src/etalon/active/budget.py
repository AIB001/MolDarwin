"""Conservative empirical cost quotes, shared by selection and transactional reservation.

Every quantity gate here is an upper bound: these functions are about not exceeding an allowance.
:func:`confirmation_guard` is the one quantity in this module about an allowance deliberately left
unspent, and it exists so that the round record can say which of the two a short round was. It is
not a floor and it creates no pressure to spend: on an external benchmark the tasks that passed
used *fewer* turns (mean 12.0) than those that failed (18.3), so a harness reacting to under-use by
pushing for spend would optimise the quantity the measurement says is not the lever. What under-use
earns is a name in the record.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from etalon.active.schema import CampaignSpec, Endpoint, finite


def fits_budget(cost: float, remaining: float) -> bool:
    """Compare charges in their declared units without creating a free absolute allowance.

    The small relative tolerance accommodates ordinary arithmetic roundoff only between
    positive finite amounts. A zero/negative balance cannot fund a positive quote.
    """
    finite(cost, "cost", minimum=0.0)
    finite(remaining, "remaining budget")
    return remaining >= 0 and (cost <= remaining or (
        cost > 0 and remaining > 0 and math.isclose(cost, remaining, rel_tol=1e-12, abs_tol=0.0)))


def affordable_capacity(cost: float, remaining: float, *, limit: int) -> int:
    """Maximum affordable count within an explicit action cap, using the same comparison.

    Binary search avoids division overflow for tiny quotes and prevents an absolute
    epsilon from manufacturing allowance at zero remaining budget.
    """
    finite(cost, "cost", minimum=0.0)
    finite(remaining, "remaining budget")
    if cost <= 0 or isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("capacity needs a positive quote and a nonnegative integer limit")
    low, high = 0, limit
    while low < high:
        count = (low + high + 1) // 2
        try:
            charge = cost * count
        except OverflowError:
            charge = math.inf
        if math.isfinite(charge) and fits_budget(charge, remaining):
            low = count
        else:
            high = count - 1
    return low


def cost_quote(endpoint: Endpoint, observations: Sequence[dict[str, Any]]) -> float:
    """At least the configured quote and the observed 90th-percentile positive charge.

    This is a planning heuristic, not a bound on a real tool's runtime. A preflight refusal has
    no runtime evidence. Historical imports with zero (sunk) cost do not make new jobs free.
    Actual overruns remain visible and can exceed the campaign budget.
    """
    costs = sorted(float(o["result"]["cost"]) for o in observations
                   if o["result"]["endpoint_id"] == endpoint.id
                   and o["result"]["status"] != "blocked" and o["result"]["cost"] > 0)
    return max(endpoint.cost, costs[math.ceil(0.9 * len(costs)) - 1]) if costs else endpoint.cost


def _quote_provenance(endpoint: Endpoint, observations: Sequence[dict[str, Any]]) -> str:
    """Whether a unit quote was recomputed from recorded charges or is the declared quote."""

    charged = any(o["result"]["endpoint_id"] == endpoint.id
                  and o["result"]["status"] != "blocked" and o["result"]["cost"] > 0
                  for o in observations)
    return ("measured_here: the 90th-percentile positive charge recorded for this endpoint in this "
            "campaign, floored at its declared quote"
            if charged else
            "convention: the endpoint's declared quote; this campaign has recorded no positive "
            "charge at it yet, so nothing has been measured")


def confirmation_guard(spec: CampaignSpec, endpoints: Mapping[str, Endpoint],
                       candidates: Iterable[Any], attempts: Mapping[str, int],
                       observations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The confirmation reserve the reservation transaction enforces, or why there is none.

    ``min(confirmation_reserve, eligible) * cost_quote(objective, history)``, where ``eligible``
    counts candidates still under the objective endpoint's ``max_replicates`` and, where that
    endpoint requires one, holding a handoff. This is the arithmetic
    ``CampaignStore.reserve`` raises ``BudgetExhausted("proxy action would consume the objective
    confirmation budget")`` on, factored out so that the transaction and any report of a
    deliberate reserve are the same quantity rather than two definitions that can drift. A
    partition that invented its own definition of "reserved on purpose" would be a heuristic
    wearing a mechanism's clothes, and this is the only representation of a deliberate reserve the
    campaign has.

    Where the policy does not arm the guard the quote is **zero with a stated reason**, because
    "no reserve was represented" and "no reserve was wanted" are different facts and a bare zero
    cannot tell them apart. Where a field the arithmetic needs is missing, the quote is ``None``
    and the basis says it was not obtained -- hard constraint 7, and never a zero, which would
    move a real reserve into the unattempted column.

    Args:
        spec: The campaign's spec.
        endpoints: Registered endpoints by id.
        candidates: The registered candidates.
        attempts: Candidate id to the number of actions already taken at the objective endpoint.
        observations: Observation history rows, in ``{"result": {...}}`` shape.
    """

    objective = endpoints.get(getattr(spec, "objective", None)) if endpoints else None
    reserve = getattr(spec, "confirmation_reserve", None)
    policy = getattr(spec, "policy", None)
    # Every return carries the same keys, so a caller reading ``eligible_candidates`` cannot be
    # surprised by a branch that omits it. ``None`` there fails closed in the reservation
    # transaction, which is the safe direction for a quantity that could not be recomputed.
    if spec is None or objective is None or type(reserve) is not int:
        return {"armed": False, "quote": None, "eligible_candidates": None,
                "confirmation_reserve": reserve if type(reserve) is int else None, "basis":
                "not_obtained: no spec, objective endpoint or reserve count was available, so the "
                "guard's own quantity could not be recomputed"}
    if policy != "decision_aware":
        return {"armed": False, "quote": 0.0, "eligible_candidates": None,
                "confirmation_reserve": reserve, "basis":
                f"measured_here: the guard arms only under policy 'decision_aware' and this "
                f"campaign declares {policy!r}, so no budget is reserved on purpose. Zero because "
                "none is represented, not because none was wanted"}
    if not reserve or not objective.queryable:
        return {"armed": False, "quote": 0.0, "eligible_candidates": None,
                "confirmation_reserve": reserve, "basis":
                "measured_here: confirmation_reserve is 0 or the objective endpoint is not "
                "queryable, so the guard cannot arm. Zero because none is represented, not "
                "because none was wanted"}
    eligible = 0
    examined = 0
    for candidate in candidates:
        examined += 1
        if (int(attempts.get(candidate.id, 0)) < objective.max_replicates
                and (not objective.requires_handoff or bool(candidate.handoff))):
            eligible += 1
    unit = cost_quote(objective, observations)
    return {
        "armed": True,
        "quote": min(reserve, eligible) * float(unit),
        "confirmation_reserve": reserve,
        "eligible_candidates": eligible,
        "candidates_examined": examined,
        "objective_unit_quote": float(unit),
        "objective_unit_quote_evidence": _quote_provenance(objective, observations),
        "basis": ("measured_here: min(confirmation_reserve, eligible) * cost_quote(objective, "
                  "history), the same arithmetic the reservation transaction raises "
                  "BudgetExhausted on"),
    }
