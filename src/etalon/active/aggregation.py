"""A declared aggregation policy, so that one draw cannot be recorded as a measurement.

A value drawn once from a stochastic oracle is a draw. A measurement is a draw plus a declared
**aggregation policy** -- how many draws, what makes them independent, how they combine, what
counts as present -- and a **dispersion** figure over those draws. Absent either, the honest
record says the observable could not be evaluated; it does not say a number with a caveat
attached.

**Why this is a record-level concern and not a quality nicety.** An external grader pinned its
stochastic model's seed, which made a submission's score bit-reproducible across three days. The
same metric's spread across five seeds was 0.0000 on one task and 0.1364 on another. A seeded run
is reproducible and is not therefore robust: determinism is a property of the pipeline, dispersion
is a property of the question. Pinning the seed removed the evidence of the dispersion without
removing the dispersion. And because dispersion is a per-task property, a pooled figure over those
two tasks describes neither -- so every figure here is per task and nothing in this module pools
one.

**What is declared and what is measured.** ``draws`` is declared. The authorised count is
measured, from the replicate actions a campaign actually authorised with distinct seeds. Where the
two disagree the honest reading is that the larger number was never established, which is why
:func:`coverage` reports both and never substitutes one for the other, and why
``draws_evidence`` refuses ``measured_here``: a declared count is not a measurement of itself.
``F_SINGLE_REPLICA_ESTIMATE`` is cleared today by whatever integer a caller passed, which is the
defect this module exists to make visible.

**Where the refusal lands.** The policy is carried by the protocol that produced the readout and
folded into that protocol's digest, so it inherits three properties already built:
``active/store.py`` refuses *"protocol changed under an existing id; register a new endpoint id"*,
an alias is refused because *"this protocol is already registered; a new alias is not a new
experiment"*, and two campaigns that aggregated differently cannot be compared under one id. The
refusal itself lands at dispatch, beside the one ``runtime/executors.py`` already makes for the
replicated MM-PBSA executor, because dispatch is the moment at which a policy declaring five
independent draws either has five authorised seeds or does not. See
:func:`dispatch_refusal`.

Terminology follows ``CLAUDE.md`` verbatim: **completion** / **verification** / **admission**, and
Evidence provenance ``measured_here`` / ``measured_in_an_asset`` / ``literature`` /
``convention``. A claim about repeatability is **precision**; one about agreement with a measured
quantity is **validity**. A single draw is a precision defect: nothing here blocks a spend, and
nothing here moves a ``Ruling``.

Staging follows ``docs/thin-harness/STOCHASTIC_MEASUREMENT.md``. This module implements stage 1
(report, non-breaking) and the derivation of the replica count from authorised actions. Stage 2 --
emitting ``evaluable=False`` where declared and authorised counts disagree -- is deliberately not
implemented here: it moves nodes in a derived admission view, and the specification gates it
behind the admission-propagation recomputability audit. :func:`coverage` reports the disagreement
so that the audit has the counts it needs.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

#: Evidence provenance, exactly the vocabulary of ``CLAUDE.md`` hard constraint 5. ``convention``
#: is never presented as a measurement; it is a label for a number somebody chose.
PROVENANCE = ("measured_here", "measured_in_an_asset", "literature", "convention")

#: What makes a policy's draws independent. ``declared_not_established`` is the honest default: it
#: says the declaration exists and nothing has shown the draws are independent, which is a
#: different record from a claim of distinct authorised seeds.
INDEPENDENCE_BASES = ("distinct_authorised_seeds", "distinct_initial_conditions",
                      "declared_not_established")

#: How the draws combine into the reported value. ``best_of`` is legal and is *not* an estimate of
#: a mean -- ``research/panel.py`` takes best-of across replicate slots and closes with
#: ``'uncertainty': None, 'uncertainty_reason': 'correlated poses; no calibrated assay-error
#: model'``, which is the honest form. A policy declaring ``best_of`` declares that it is selecting
#: and not averaging, and its dispersion figure is about the selection.
COMBINERS = ("mean", "median", "best_of", "fraction_present")

#: The dispersion statistic the policy declares over its draws. ``none_declared`` is legal,
#: because a protocol may genuinely have no dispersion model, and it is the value that makes a
#: readout unevaluable where a decision would rely on a spread. Legal and consequential is the
#: right combination: illegal would push callers to declare ``sd`` over one draw.
DISPERSIONS = ("sd", "range", "none_declared")

#: Reported in place of a dispersion figure that could not be computed. Hard constraint 7: a
#: quantity that cannot be counted is reported as not obtained. Zero is the value a missing spread
#: most resembles, which is the whole reason this constant exists rather than a ``0.0``.
NOT_TAKEN = "not_taken"


class PolicyError(ValueError):
    """A declared aggregation policy that cannot mean what it says."""


@dataclass(frozen=True)
class AggregationPolicy:
    """What a protocol declares about turning draws into a value.

    Every field is part of the declaration and therefore part of the protocol's identity. Changing
    one is a new protocol, not a reinterpretation of the old one's records.
    """

    #: Independent draws the policy declares. Declared, never measured -- see ``draws_evidence``.
    draws: int = 1
    independence_basis: str = "declared_not_established"
    combine: str = "mean"
    dispersion: str = "none_declared"
    #: Where ``draws`` came from. ``measured_here`` is refused: see :meth:`__post_init__`.
    draws_evidence: str = "convention"
    #: The citation or the reasoning behind ``draws``, in full. Required above one draw, because
    #: that is where the number starts costing something and starts clearing a fault.
    draws_source: str = ""
    #: For ``fraction_present``: the per-draw cutoff, and the share of draws needed. Each carries
    #: its own provenance, following ``economics/stage.py``'s per-quantity labelling for the reason
    #: that module gives -- one label over several numbers laundered three of them.
    present_threshold: float | None = None
    present_threshold_evidence: str | None = None
    pass_threshold: float | None = None
    pass_threshold_evidence: str | None = None

    def __post_init__(self) -> None:
        if type(self.draws) is not int or self.draws < 1:
            raise PolicyError("draws must be an integer of at least one")
        for name, allowed in (("independence_basis", INDEPENDENCE_BASES),
                              ("combine", COMBINERS), ("dispersion", DISPERSIONS)):
            if getattr(self, name) not in allowed:
                raise PolicyError(f"{name} must be one of {allowed}")
        if self.draws_evidence not in PROVENANCE:
            raise PolicyError(f"draws_evidence must be one of {PROVENANCE}")
        if self.draws_evidence == "measured_here":
            # The distinction this module exists for. A declared count is not a measurement of
            # itself; what is measured is the number of authorised replicate actions, and
            # ``coverage`` reports that separately so the two can disagree in the open.
            raise PolicyError(
                "a declared draw count is not measured_here. The declaration is the protocol's; "
                "what is measured is the count of authorised replicate actions behind the value, "
                "which authorised_draws() reads from the campaign's own records"
            )
        if not isinstance(self.draws_source, str):
            raise PolicyError("draws_source must be text")
        if self.draws > 1 and not self.draws_source.strip():
            raise PolicyError(
                "a policy declaring more than one draw must say where that count came from; it "
                "prices the campaign and it clears F_SINGLE_REPLICA_ESTIMATE"
            )
        if self.dispersion in {"sd", "range"} and self.draws < 2:
            # Refused rather than silently reported as 0.0. A spread over one draw is not a small
            # spread; there is no spread, and the two read identically once recorded.
            raise PolicyError(
                "a dispersion figure over one draw is not a spread. Declare "
                "dispersion='none_declared', or declare the draws the spread would be computed over"
            )
        thresholds = (self.present_threshold, self.pass_threshold)
        evidences = (self.present_threshold_evidence, self.pass_threshold_evidence)
        if self.combine == "fraction_present":
            if any(value is None for value in thresholds):
                raise PolicyError(
                    "fraction_present needs both a per-draw present_threshold and the "
                    "pass_threshold share of draws; without them the combiner has no definition"
                )
            for name, value in (("present_threshold", self.present_threshold),
                                ("pass_threshold", self.pass_threshold)):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise PolicyError(f"{name} must be a real number in [0, 1]")
                if not 0.0 <= float(value) <= 1.0:
                    raise PolicyError(f"{name} must be a real number in [0, 1]")
            for name, value in (("present_threshold_evidence", self.present_threshold_evidence),
                                ("pass_threshold_evidence", self.pass_threshold_evidence)):
                if value not in PROVENANCE:
                    raise PolicyError(f"{name} must be one of {PROVENANCE}; a threshold nobody "
                                      "sourced is a convention and must say so")
        elif any(value is not None for value in thresholds + evidences):
            raise PolicyError(
                f"present_threshold and pass_threshold are read only by combine='fraction_present'; "
                f"combine={self.combine!r} would carry them into the protocol identity without "
                "their affecting the protocol"
            )

    @classmethod
    def declare(cls, value: Mapping[str, Any] | AggregationPolicy | None) -> AggregationPolicy:
        """Build a policy from a declaration, refusing a field this module does not define.

        ``None`` is the stage-1 default: one draw, combined as a mean, no dispersion declared, and
        independence declared rather than established. That default is what every protocol
        registered before this change already means, which is why declaring it explicitly changes
        no protocol identity -- see ``CascadeRecipe.protocol_id``.
        """

        if value is None:
            return DEFAULT
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise PolicyError("an aggregation policy must be a mapping of declared fields")
        known = {field.name for field in cls.__dataclass_fields__.values()}
        unknown = sorted(set(value) - known)
        if unknown:
            raise PolicyError(f"aggregation policy does not define {unknown}")
        return cls(**dict(value))

    def as_dict(self) -> dict[str, Any]:
        """The declaration, with unset optional fields omitted so the digest stays tidy."""

        return {key: item for key, item in asdict(self).items() if item is not None}

    @property
    def is_default(self) -> bool:
        """Whether this is the stage-1 default, i.e. what an undeclared protocol already means."""

        return self == DEFAULT

    def declares_independent_draws(self) -> bool:
        """Whether the policy claims more than one draw at all."""

        return self.draws > 1


#: What a protocol that declares nothing already means. Stage 1 of the specification defaults every
#: existing protocol to exactly this, so that nothing changes behaviour and every protocol becomes
#: legible. It is also why a default policy is omitted from a protocol's digest: recording it
#: explicitly would change every protocol id that exists, which is a migration and not a
#: clarification.
DEFAULT = AggregationPolicy()


def policy_from_stage(stage: Any) -> AggregationPolicy:
    """The default source of a declared policy's draw count: the priced stage catalogue.

    ``economics/stage.py`` is the right **input** to a policy and the wrong home for it. Its
    predicates are binding on cost, surface as a note rather than a refusal, and -- until this
    module -- nothing in ``active/`` read them. Reading them here means a protocol that declares a
    count inherits a number with a provenance rather than a number somebody typed.

    The ensemble default follows ``F_SINGLE_REPLICA_ESTIMATE``'s own remedy rather than this
    module's taste: *"report its median with a quantile interval rather than a mean with a standard
    deviation, because the distribution is skewed and heavy-tailed."* So an ensemble policy
    combines by ``median`` and declares ``range``, and declaring ``sd`` over a skewed heavy-tailed
    distribution stays the caller's explicit choice rather than this function's default.
    """

    from etalon.economics.stage import (
        ENSEMBLE_REPLICAS_EVIDENCE,
        ENSEMBLE_REPLICAS_SOURCE,
        ONE_RUN_THRESHOLD_KCAL_MOL,
    )

    draws = int(stage.replicas_for_a_measurement())
    if draws > 1:
        return AggregationPolicy(
            draws=draws,
            independence_basis="declared_not_established",
            combine="median",
            dispersion="range",
            draws_evidence=str(ENSEMBLE_REPLICAS_EVIDENCE),
            draws_source=ENSEMBLE_REPLICAS_SOURCE,
        )
    return AggregationPolicy(
        draws=1,
        draws_evidence="convention",
        draws_source=(
            f"{stage.id} is treated as reproducible from one run because its recorded run-to-run "
            f"spread is {stage.run_to_run_kcal_mol} kcal/mol against the "
            f"{ONE_RUN_THRESHOLD_KCAL_MOL} kcal/mol threshold (RT*ln(10) at 310 K, one log unit of "
            f"affinity). The threshold is this project's convention; the spread's own provenance is "
            f"{stage.evidence.value}: {stage.source}"
        ),
    )


def authorised_draws(actions: Sequence[Mapping[str, Any]], *, candidate_id: str, endpoint_id: str,
                     seeds: Sequence[int] | None = None,
                     counted_statuses: Sequence[str] = ("completed",)) -> dict[str, Any]:
    """Count the authorised replicate actions behind one candidate's readout at one endpoint.

    This is the measured half of the declared/measured pair, and it is deliberately read from the
    action rows rather than taken from a caller. ``active/prism.py`` already authorises one distinct
    seed per replicate and refuses *"no authorized seed for this action; next-round plan is not
    dispatch permission"*; ``active/store.py`` allocates ``replicate`` as the count of prior
    attempts and refuses a reservation past ``max_replicates``. So a replicate index below the
    number of declared seeds is an authorised draw, and nothing else is.

    Per task, never pooled: one candidate at one endpoint. A count over several candidates would
    describe none of them.

    Args:
        actions: Action rows, as ``CampaignStore.actions()`` returns them.
        candidate_id: The one candidate this count is about.
        endpoint_id: The one endpoint this count is about.
        seeds: The seeds the executor declared, where it declares any. A replicate index at or
            above their number carries no authorised seed and is not counted.
        counted_statuses: Action statuses that count as a draw. Defaults to ``completed``, which
            ``active/store.py`` writes only where the observation was admitted -- a failed,
            blocked or withheld action produced no draw a consensus may rest on, and a reserved or
            running one has not produced a draw yet. So the default counts admitted draws and
            nothing else, which is the count that should be clearing a replica fault.

    Returns:
        A mapping carrying the count, the distinct replicate indices behind it, and the basis --
        never a count without the basis, because the count clears a fault.
    """

    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("authorised_draws needs one candidate id")
    if not isinstance(endpoint_id, str) or not endpoint_id.strip():
        raise ValueError("authorised_draws needs one endpoint id")
    declared_seeds = None if seeds is None else len(set(seeds))
    if seeds is not None and declared_seeds != len(seeds):
        # The executors refuse this at registration ("a repeated seed is a retry, not a replica").
        # Refused here too rather than silently counting the duplicate as a draw.
        raise ValueError("declared seeds must be distinct; a repeated seed is a retry, not a replica")
    indices: set[int] = set()
    unauthorised: list[int] = []
    examined = 0
    for row in actions:
        if not isinstance(row, Mapping):
            continue
        if row.get("candidate_id") != candidate_id or row.get("endpoint_id") != endpoint_id:
            continue
        examined += 1
        if row.get("status") not in tuple(counted_statuses):
            continue
        index = row.get("replicate")
        if type(index) is not int or index < 0:
            continue
        if declared_seeds is not None and index >= declared_seeds:
            unauthorised.append(index)
            continue
        indices.add(index)
    return {
        "authorised_draws": len(indices),
        "replicate_indices": sorted(indices),
        "actions_examined": examined,
        "seeds_declared": declared_seeds,
        "replicates_without_an_authorised_seed": sorted(unauthorised),
        "candidate_id": candidate_id,
        "endpoint_id": endpoint_id,
        "basis": (
            "measured_here: distinct replicate indices of "
            f"{tuple(counted_statuses)} actions at this candidate and endpoint"
            + ("" if declared_seeds is None else f", below the {declared_seeds} declared seeds")
        ),
        "pooled": False,
    }


def dispersion_figure(values: Sequence[float], policy: AggregationPolicy) -> dict[str, Any]:
    """The spread over one task's draws, or the statement that it was not taken.

    Reported the way ``active/benchmark.py`` already reports ``sd_*``: ``None`` at n = 1, rather
    than a zero. A task whose dispersion cannot be computed because it has one draw is reported as
    not taken and never as zero dispersion -- hard constraint 7, and the trap that makes this
    whole change necessary rather than obvious.
    """

    numbers = [float(value) for value in values]
    if policy.dispersion == "none_declared":
        return {"statistic": "none_declared", "figure": None, "draws_used": len(numbers),
                "basis": "the protocol declares no dispersion model, so no figure is claimed",
                "pooled": False}
    if len(numbers) < 2:
        return {"statistic": policy.dispersion, "figure": None, "draws_used": len(numbers),
                "basis": f"{NOT_TAKEN}: dispersion needs at least two draws and this task has "
                         f"{len(numbers)}. Zero is the value a missing spread most resembles, so "
                         "it is not reported",
                "pooled": False}
    figure = (statistics.stdev(numbers) if policy.dispersion == "sd"
              else max(numbers) - min(numbers))
    return {"statistic": policy.dispersion, "figure": float(figure), "draws_used": len(numbers),
            "basis": f"measured_here: {policy.dispersion} over this task's {len(numbers)} draws",
            "pooled": False}


def coverage(policy: AggregationPolicy, authorised: Mapping[str, Any], *,
             values: Sequence[float] = ()) -> dict[str, Any]:
    """Stage 1 of the specification: the policy and its coverage, beside the value.

    Nothing is refused here and no ``Ruling`` moves. What the block establishes is that the
    declared and the authorised counts are separately visible, so that the case the record used to
    be unable to express -- a one-draw value clearing ``F_SINGLE_REPLICA_ESTIMATE`` because a
    caller passed ``replicas=5`` -- now reads differently from a five-draw consensus.

    ``missing_policy`` is reported as ``"insufficient"`` where the declaration is the bare default,
    following the vocabulary the specification names, because an undeclared policy is not a
    declared single draw.
    """

    declared = policy.draws
    measured = int(authorised.get("authorised_draws", 0))
    spread = dispersion_figure(values, policy)
    return {
        "declared_draws": declared,
        "authorised_draws": measured,
        "agrees": declared == measured,
        "combine": policy.combine,
        "dispersion": policy.dispersion,
        "dispersion_figure": spread["figure"] if spread["figure"] is not None else NOT_TAKEN,
        "dispersion_detail": spread,
        "independence_basis": policy.independence_basis,
        "draws_evidence": policy.draws_evidence,
        "draws_source": policy.draws_source,
        "missing_policy": "insufficient" if policy.is_default else "declared",
        "candidate_id": authorised.get("candidate_id"),
        "endpoint_id": authorised.get("endpoint_id"),
        "authorisation_basis": authorised.get("basis"),
        "pooled": False,
        "note": (
            "declared is the protocol's claim and authorised is measured from this campaign's "
            "action rows. Where they disagree the larger number was never established. This block "
            "reports; it moves no Ruling and blocks no spend, and the stage that emits "
            "evaluable=False on a disagreement is gated behind the admission-propagation "
            "recomputability audit"
        ),
    }


def per_task_dispersion(observations: Sequence[Mapping[str, Any]], policy: AggregationPolicy, *,
                        endpoint_id: str | None = None) -> dict[str, Any]:
    """The spread of every task's admitted draws, one task at a time.

    Keyed by candidate at one endpoint, because dispersion is a per-task property: across five
    seeds one task's spread was 0.0000 and another's 0.1364, and a pooled figure over those two
    describes neither. The return value therefore carries no total, no mean of the spreads and no
    pooled statistic -- there is deliberately nothing here to pool.

    A task with one draw reports its figure as not taken. ``active/benchmark.py`` already reports
    ``sd_*`` as ``None`` at n = 1 and this follows it exactly.
    """

    draws: dict[str, list[float]] = {}
    for row in observations:
        result = row.get("result") if isinstance(row, Mapping) else None
        if not isinstance(result, Mapping) or not row.get("admitted"):
            continue
        if endpoint_id is not None and result.get("endpoint_id") != endpoint_id:
            continue
        value = result.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        draws.setdefault(str(result.get("candidate_id")), []).append(float(value))
    return {
        "tasks": {key: {**dispersion_figure(values, policy), "draws": len(values)}
                  for key, values in sorted(draws.items())},
        "endpoint_id": endpoint_id,
        "pooled": False,
        "method": (
            "per candidate at one endpoint, over admitted observations; no pooled figure is "
            "produced because dispersion is a property of the task and not of the campaign"
        ),
    }


def dispatch_refusal(policy: AggregationPolicy, *, max_replicates: int,
                     declared_seeds: int | None = None,
                     authorised: Mapping[str, Any] | None = None) -> str | None:
    """Why this policy cannot be dispatched here, or ``None``.

    The general form of the refusal ``runtime/executors.py`` already makes for one executor kind.
    That refusal was taken at cost and for the right reason -- the alternative was that *"a
    three-replica endpoint would quietly run as one unseeded trajectory per action and report the
    result under a protocol id that claims recorded seeds"*. Keyed on a declared policy rather
    than on an executor kind, the same argument reaches every endpoint: the two shipped
    dispatchable kinds have ``max_replicates = 1``, and a policy declaring five draws against them
    must refuse rather than quietly run one.

    Nothing is refused for a policy that declares one draw, which is every protocol registered
    before this change.
    """

    if not policy.declares_independent_draws():
        return None
    if type(max_replicates) is not int or max_replicates < 1:
        return "the endpoint declares no usable replicate limit"
    if policy.draws > max_replicates:
        return (
            f"the protocol declares {policy.draws} independent draws and this endpoint authorises "
            f"at most {max_replicates}. Dispatching would run fewer draws than the protocol id "
            "claims, and the value would be recorded under a policy it does not satisfy"
        )
    if declared_seeds is not None and policy.draws > declared_seeds:
        return (
            f"the protocol declares {policy.draws} independent draws and the executor declares "
            f"{declared_seeds} distinct seed(s). A draw with no authorised seed is not an "
            "independent repetition"
        )
    if (policy.independence_basis == "distinct_authorised_seeds" and declared_seeds is None):
        return (
            "the protocol claims distinct authorised seeds as its independence basis and this "
            "executor declares no seeds, so nothing records what made the draws independent"
        )
    if authorised is not None:
        without_seed = authorised.get("replicates_without_an_authorised_seed") or ()
        if without_seed:
            return (
                f"replicate index {sorted(without_seed)[0]} carries no authorised seed; a "
                "next-round plan is not dispatch permission"
            )
    return None


def trajectory_from_authorised_replicates(
    rmsd_result: Mapping[str, Any],
    contacts_result: Mapping[str, Any] | None = None,
    *,
    actions: Sequence[Mapping[str, Any]],
    candidate_id: str,
    endpoint_id: str,
    seeds: Sequence[int] | None = None,
    scored_contacts: Sequence[str] = (),
    nanoseconds: float = 0.0,
) -> tuple[Any, dict[str, Any]]:
    """Build a :class:`etalon.faults.stability.Trajectory` whose replica count was measured.

    ``Trajectory.replicas`` is a caller-supplied integer defaulting to 1, and ``from_prism`` passes
    it straight through, so the clearing of ``F_SINGLE_REPLICA_ESTIMATE`` rests today on an
    unverified declaration: ``replicas=5`` against a campaign holding two authorised replicate
    actions reads exactly like five replicas. This constructor takes no ``replicas`` argument. It
    counts the authorised replicate actions and passes that count, so the cleared fault and the
    records agree by construction.

    Returns:
        The trajectory and the authorisation record the count came from. The second element is
        returned rather than logged because a count that clears a fault must travel with its basis.
    """

    from etalon.faults.stability import from_prism

    authorised = authorised_draws(actions, candidate_id=candidate_id, endpoint_id=endpoint_id,
                                  seeds=seeds)
    return (
        from_prism(rmsd_result, contacts_result, scored_contacts=scored_contacts,
                   replicas=max(1, authorised["authorised_draws"]), nanoseconds=nanoseconds),
        {**authorised, "replicas_passed": max(1, authorised["authorised_draws"]),
         "replicas_floor_note": (
             "a campaign with no completed replicate action still has one trajectory in hand; the "
             "floor of one is the trajectory being read, not an authorised draw"
         )},
    )


__all__ = [
    "COMBINERS",
    "DEFAULT",
    "DISPERSIONS",
    "INDEPENDENCE_BASES",
    "NOT_TAKEN",
    "PROVENANCE",
    "AggregationPolicy",
    "PolicyError",
    "authorised_draws",
    "coverage",
    "dispatch_refusal",
    "dispersion_figure",
    "per_task_dispersion",
    "policy_from_stage",
    "trajectory_from_authorised_replicates",
]
