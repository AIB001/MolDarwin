"""Compare a skill or method revision with the version it replaces, and say how far to adopt it.

Before this module the adoption gate was this, in ``resolve_method_revision``: the candidate
must appear in the evaluation's subjects, and ``result_refs`` and ``accounting_refs`` must be
non-empty. Three existence checks. Nothing read the evaluation's *verdict*, nothing compared the
two versions on the same tasks, and nothing asked whether the difference was larger than what the
tasks could resolve. A revision that was measurably worse could be adopted by a host that wrote
``outcome="adopt"``, and the record would look exactly like a revision that had earned it.

That is the characteristic way a self-improving loop goes wrong. It is not that a bad revision
gets in once; it is that the loop keeps reporting improvement while drifting, because the
acceptance step is a formality and the number it would have needed was never computed.

What this module refuses to do
------------------------------

**It does not return one score.** A single number would let a cost saving pay for a quality
regression, and those are not the same currency -- ``docs/thin-harness/memory-four-graphs/
DESIGN.md`` says the evaluation is "指标向量，不默认用 LLM 自评压成统一总分" (a metric vector,
not collapsed by LLM self-assessment into one total). The output here is one verdict per
dimension plus an *adoption* level, and the degree of acceptance lives in the **scope** the
candidate is adopted for, not in a scalar.

**It does not estimate what it cannot count.** Hard constraint 7. A dimension with no paired
observations comes back ``NOT_MEASURED``; a dimension with too few discordant pairs comes back
``UNDERPOWERED``. Neither is silently folded into "no change".

**It does not conflate "cannot tell" with "too small to matter".** Those are separate verdicts
(``WITHIN_NOISE`` and ``BELOW_MINIMUM``) because they call for opposite responses: the first
says measure more, the second says stop measuring and spend the effort elsewhere.

What it counts
--------------

Admission states come from ``learn.admission_view``'s closed vocabulary, and the counting rules
are ``docs/thin-harness/RSI_REWARD.md``'s, not new ones:

* only ``admitted`` is a win (RSI_REWARD section on wins),
* ``admitted_under_waiver`` is **not** a win and is charged to cost (D3),
* ``not_recorded`` is a loss -- in the denominator, not the numerator (D4),
* two sides that do not share a fault-catalogue digest are not comparable at all, and the
  comparison raises rather than returning a number nobody can interpret.

The test
--------

Tasks are **paired**: both versions ran the same declared task, and a task present on one side
only is refused rather than dropped quietly, because dropping it is how a candidate that fails
to produce an answer looks better than one that produces a wrong one.

For a binary dimension the instrument is McNemar's exact test -- only the discordant pairs carry
information, and under the null they split evenly. For a cost dimension it is the sign test on
the paired differences, which is distribution-free; wall-clock on a shared machine is heavy
tailed and a mean difference there is a number about the machine's other tenants.

``MINIMUM_DISCORDANT_PAIRS = 6`` is arithmetic, not taste: with five discordant pairs all
pointing the same way the two-sided exact p is 2/2**5 = 0.0625, which no conventional alpha
admits, so a comparison with five cannot reach a conclusion whichever way it falls. The
arithmetic is exact; ``DEFAULT_ALPHA = 0.05`` is the convention, and is labelled as one.

Statistical caveats this module does not fix: alpha is per dimension and per comparison, with no
correction for the repeated use of one task set across many revisions, and the tasks are a
convenience set rather than a sample from a declared population. A ``BETTER`` here is evidence
under the declared regime, not a generalisation claim. That is why ``assessment_role`` caps the
adoption level independently of every verdict.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from numbers import Integral, Real

from moldarwin.economics.stage import Evidence

#: The admission states this module reads, worst first, mirroring
#: ``learn.admission_view._ORDER``. Imported as a literal rather than from that module so a
#: comparison does not pull the whole admission view in; the order is asserted against it by
#: ``tests/test_revision_score.py``.
ADMISSION_STATES = ("withheld", "not_recorded", "admitted_under_waiver", "admitted")

#: A fault-catalogue digest, in the shape ``admission_view.catalogue_digest()`` produces and
#: the research step's validator accepts. The two must agree or a measured adoption cannot
#: be recorded at all.
_SHA256 = re.compile(r"[0-9a-f]{64}")

#: The one admission state that counts toward the numerator. RSI_REWARD: a waiver is not a win.
WARRANTED_STATE = "admitted"

#: Smallest number of discordant pairs at which a two-sided exact sign test can reach
#: :data:`DEFAULT_ALPHA` even when every pair agrees. Evidence: the arithmetic is exact
#: (2/2**6 = 0.03125 <= 0.05 < 0.0625 = 2/2**5); applying 0.05 is the convention below.
MINIMUM_DISCORDANT_PAIRS = 6

#: Evidence: ``convention``. Nothing in this project has measured an error rate at which a skill
#: revision becomes worth accepting; 0.05 is the familiar choice and is recorded as a choice.
DEFAULT_ALPHA = 0.05
DEFAULT_ALPHA_EVIDENCE = Evidence.CONVENTION


class Family(StrEnum):
    """What a dimension measures, which fixes its direction and its test.

    The direction is a property of the family and not of the caller, because a caller who can
    declare that rising cost is an improvement can declare any revision an improvement.
    """

    #: Per task: was the decision warranted, i.e. did its admission state reach ``admitted``.
    #: Binary, higher is better. This is RSI_REWARD's numerator.
    WARRANT = "warrant"
    #: Per task: did the version correctly refuse a task it should not have answered. Binary,
    #: higher is better. Separated from WARRANT because a revision that answers everything scores
    #: well on warrant-among-answers while being strictly worse: refusing is a capability.
    REFUSAL = "refusal"
    #: Per task: did the version produce any recorded outcome at all. Binary, higher is better.
    #: A candidate that silently declines half the tasks must not read as an improvement on the
    #: half it kept.
    COVERAGE = "coverage"
    #: Per task: did the outcome carry the evidence links it claims. Binary, higher is better.
    PROVENANCE = "provenance"
    #: Per task: a real quantity to be minimised -- spend, wall seconds, expensive-tier calls.
    COST = "cost"


#: Families whose observations are admission states rather than plain booleans.
_ADMISSION_FAMILIES = frozenset({Family.WARRANT})
#: Families whose per-task observation is a real number, lower being better.
_REAL_FAMILIES = frozenset({Family.COST})


class Verdict(StrEnum):
    """One dimension's answer. Six, because six different things call for different responses."""

    BETTER = "better"
    WORSE = "worse"
    #: Resolved, real, and smaller than the minimum the caller declared worth acting on. Act on
    #: something else.
    BELOW_MINIMUM = "below_minimum"
    #: The difference is not larger than what these tasks can resolve. May be real; these tasks
    #: cannot say. Measure more.
    WITHIN_NOISE = "within_noise"
    #: Too few discordant pairs for any conclusion. Not the same as no difference.
    UNDERPOWERED = "underpowered"
    #: No paired observations were supplied for this dimension. Reported, never imputed.
    NOT_MEASURED = "not_measured"


class Adoption(StrEnum):
    """How far the candidate may be taken. This is the "degree of acceptance"."""

    #: Better where it matters, measured under independent validation, across the declared scope.
    FULL = "full"
    #: Adopt, but only for the conditions actually measured. The declared scope was wider than
    #: the evidence, or a reservation applies.
    SCOPED = "scoped"
    #: May be tried locally; may not be claimed as an improvement or made anyone's default,
    #: because the measurement was taken in the diagnostic lane.
    DIAGNOSTIC_ONLY = "diagnostic_only"
    #: Keep the previous version.
    REFUSED = "refused"


class Gain(StrEnum):
    """What, if anything, the candidate was shown to buy."""

    QUALITY = "quality"
    COST = "cost"
    BOTH = "both"
    NONE = "none"


#: Maps an adoption level onto the outcome vocabulary ``resolve_method_revision`` already takes,
#: so this module adds a verdict rather than a second, parallel set of words for the same act.
_OUTCOME = {
    Adoption.FULL: "adopt",
    Adoption.SCOPED: "adopt",
    Adoption.DIAGNOSTIC_ONLY: "retain",
    Adoption.REFUSED: "retain",
}


class NotComparable(ValueError):
    """The two sides cannot be compared, and a number would misrepresent that they can."""


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    try:
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be a finite real number")
    except (OverflowError, TypeError):
        raise ValueError(f"{name} must be a finite real number") from None
    return float(value)


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return int(value)


def two_sided_sign_p(wins: int, losses: int) -> float:
    """Exact two-sided p for discordant pairs splitting evenly under the null.

    Returned rather than approximated because the counts here are small -- a dozen tasks is a
    normal evaluation -- and a normal approximation at n = 8 is a different test wearing this
    one's name.
    """

    wins, losses = _count(wins, "wins"), _count(losses, "losses")
    total = wins + losses
    if total == 0:
        return 1.0
    smaller = min(wins, losses)
    tail = sum(math.comb(total, i) for i in range(smaller + 1)) / (2.0**total)
    return min(1.0, 2.0 * tail)


def minimum_discordant_pairs(alpha: float = DEFAULT_ALPHA) -> int:
    """Smallest discordant pair count at which a unanimous two-sided sign test can reach ``alpha``.

    Exact arithmetic: ``2 / 2**n <= alpha``. Equals :data:`MINIMUM_DISCORDANT_PAIRS` (6) at
    :data:`DEFAULT_ALPHA` (0.05), 8 at 0.01, and so on.
    """

    alpha = _finite(alpha, "alpha")
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie strictly between 0 and 1")
    n = 1
    while 2.0 / (2.0**n) > alpha:
        n += 1
    return n


def median_difference_interval(differences: Sequence[float], *, alpha: float = DEFAULT_ALPHA):
    """Distribution-free interval for the median paired difference, or ``None``.

    Order statistics, so it assumes nothing about the shape of the differences. ``None`` when
    the pairs are too few for any interval at this alpha -- hard constraint 7: an interval that
    cannot be computed is reported as absent, never widened into a guess.
    """

    values = sorted(_finite(d, "difference") for d in differences)
    n = len(values)
    if n == 0:
        return None
    k = 0
    while k < n // 2:
        # Coverage of [values[k], values[n-1-k]] is 1 - 2*P(Bin(n, 0.5) <= k-1)... computed
        # directly as the tail below, so the loop stops at the tightest interval that still holds.
        tail = sum(math.comb(n, i) for i in range(k + 1)) / (2.0**n)
        if 2.0 * tail > alpha:
            break
        k += 1
    if k == 0:
        tail = 2.0 * (1.0 / (2.0**n))
        if tail > alpha:
            return None
    index = max(k - 1, 0)
    return (values[index], values[n - 1 - index])


@dataclass(frozen=True, slots=True)
class Dimension:
    """One thing being compared, with the minimum difference worth acting on and where it is from.

    ``minimum_gain`` exists because "resolved" and "worth doing" are different questions, and a
    loop that adopts every resolved difference spends its whole budget on revisions that moved a
    number it can measure by an amount nobody can use.
    """

    name: str
    family: Family
    #: Smallest difference worth acting on, in the dimension's own units. For binary families it
    #: is a difference in the count of winning tasks; for COST it is in the cost unit.
    minimum_gain: float = 0.0
    #: Where :attr:`minimum_gain` comes from. Hard constraint 5 -- a threshold with no stated
    #: origin reads as a measurement and is usually a preference.
    minimum_gain_evidence: Evidence = Evidence.CONVENTION
    minimum_gain_source: str = ""
    #: The unit the cost family is counted in. Required for COST, refused for the others, because
    #: a cost with no unit cannot be added to anything or compared across runs.
    unit: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("a dimension needs a name")
        if not isinstance(self.family, Family):
            raise ValueError("family must be a Family, not an unverified string")
        if _finite(self.minimum_gain, "minimum_gain") < 0:
            raise ValueError("minimum_gain is a magnitude and cannot be negative")
        if not isinstance(self.minimum_gain_evidence, Evidence):
            raise ValueError("minimum_gain_evidence must be an Evidence value")
        # A nonzero threshold decides what counts as worth adopting, so every one of them names
        # where it came from -- not only the measured ones. A `convention` with no source is the
        # common case and the dangerous one: it reads to a later reader exactly like a number
        # somebody established. Zero is exempt because it asserts nothing.
        if self.minimum_gain > 0 and not self.minimum_gain_source:
            raise ValueError(
                f"minimum_gain={self.minimum_gain:g} is declared "
                f"{self.minimum_gain_evidence.value} with no source. Name the run, the citation, "
                "or whose choice it was; a threshold with no stated origin is read as a "
                "measurement and is usually a preference.")
        if self.family in _REAL_FAMILIES and not self.unit:
            raise ValueError("a cost dimension must name its unit")
        if self.family not in _REAL_FAMILIES and self.unit:
            raise ValueError("only a cost dimension carries a unit")


@dataclass(frozen=True, slots=True)
class DimensionResult:
    """What one dimension concluded, with everything needed to recompute it."""

    dimension: Dimension
    verdict: Verdict
    pairs: int
    #: Tasks where the candidate won and the base lost.
    candidate_wins: int
    #: Tasks where the base won and the candidate lost.
    base_wins: int
    ties: int
    #: Observed difference in the dimension's own units, signed so that positive is an
    #: improvement for every family -- for COST that means a saving.
    effect: float
    p_value: float
    #: Only for COST, and only when the pairs allow one. ``None`` means not obtained.
    effect_interval: tuple[float, float] | None
    note: str
    #: Significance threshold actually used for this ruling (recorded rather than assumed default).
    alpha: float = DEFAULT_ALPHA

    @property
    def improved(self) -> bool:
        return self.verdict is Verdict.BETTER

    @property
    def regressed(self) -> bool:
        return self.verdict is Verdict.WORSE

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.dimension.name,
            "family": self.dimension.family.value,
            "verdict": self.verdict.value,
            "pairs": self.pairs,
            "candidate_wins": self.candidate_wins,
            "base_wins": self.base_wins,
            "ties": self.ties,
            "effect": self.effect,
            "unit": self.dimension.unit or "task",
            "p_value": self.p_value,
            "alpha": self.alpha,
            "alpha_evidence": DEFAULT_ALPHA_EVIDENCE.value,
            "minimum_gain": self.dimension.minimum_gain,
            "minimum_gain_evidence": self.dimension.minimum_gain_evidence.value,
            "minimum_gain_source": self.dimension.minimum_gain_source,
            "effect_interval": list(self.effect_interval) if self.effect_interval else None,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Comparison:
    """The whole verdict: every dimension, how far to adopt, and why it stopped there."""

    adoption: Adoption
    gain: Gain
    dimensions: tuple[DimensionResult, ...]
    tasks: tuple[str, ...]
    assessment_role: str
    catalogue_digest: str
    #: Conditions the evidence covers. Narrower than ``declared_scope`` when ``measured_scope`` is
    #: a proper subset; when ``adoption`` is ``SCOPED`` for another reservation (e.g. a cost
    #: regression, extra waivers, or an underpowered dimension), ``reservations`` names the bound.
    scope: tuple[str, ...]
    declared_scope: tuple[str, ...]
    #: Why the adoption is not FULL, one reason per cap that applied. Empty iff FULL.
    reservations: tuple[str, ...]
    waiver_change: int
    note: str

    @property
    def outcome(self) -> str:
        """The word ``resolve_method_revision`` takes: adopt or retain.

        Never ``rollback``: rollback additionally requires that the candidate was previously in
        use, which is a fact about the journal and not about this comparison.
        """

        return _OUTCOME[self.adoption]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "moldarwin-revision-comparison/1",
            "adoption": self.adoption.value,
            "outcome": self.outcome,
            "gain": self.gain.value,
            "assessment_role": self.assessment_role,
            "catalogue_digest": self.catalogue_digest,
            "tasks": list(self.tasks),
            "scope": list(self.scope),
            "declared_scope": list(self.declared_scope),
            "reservations": list(self.reservations),
            "waiver_change": self.waiver_change,
            "dimensions": [result.as_dict() for result in self.dimensions],
            "note": self.note,
            "default_changed": False,
        }


def _paired(base: Mapping[str, object], candidate: Mapping[str, object], name: str):
    """Task ids present on both sides, refusing rather than dropping a one-sided task."""

    for side, label in ((base, "base"), (candidate, "candidate")):
        if not isinstance(side, Mapping):
            raise NotComparable(f"{name}: {label} observations must be a mapping of task to value")
    missing = set(base) ^ set(candidate)
    if missing:
        raise NotComparable(
            f"{name}: {len(missing)} task(s) were observed on one side only "
            f"({', '.join(sorted(map(str, missing))[:5])}). Dropping them would let a candidate "
            "that produced no answer outscore one that produced a poor answer; supply the missing "
            "observations or remove the task from both sides."
        )
    return sorted(base)


def _binary(value: object, *, family: Family, name: str, task: str) -> bool:
    if family in _ADMISSION_FAMILIES:
        if value not in ADMISSION_STATES:
            raise NotComparable(
                f"{name}: task {task} carries {value!r}, which is not one of {ADMISSION_STATES}. "
                "A warrant dimension reads admission states, so that a waiver cannot arrive "
                "disguised as a success."
            )
        return value == WARRANTED_STATE
    if not isinstance(value, bool):
        raise NotComparable(f"{name}: task {task} must be True or False, not {value!r}")
    return value


def compare_dimension(
    dimension: Dimension,
    base: Mapping[str, object],
    candidate: Mapping[str, object],
    *,
    alpha: float = DEFAULT_ALPHA,
) -> DimensionResult:
    """Rule on one dimension from paired per-task observations."""

    if not isinstance(dimension, Dimension):
        raise ValueError("dimension must be a Dimension")
    alpha = _finite(alpha, "alpha")
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie strictly between 0 and 1")
    tasks = _paired(base, candidate, dimension.name)
    if not tasks:
        return DimensionResult(
            dimension, Verdict.NOT_MEASURED, pairs=0, candidate_wins=0, base_wins=0, ties=0,
            effect=0.0, p_value=1.0, effect_interval=None,
            note="No paired observations. Not obtained, not zero.", alpha=alpha)

    differences: list[float] = []
    candidate_wins = base_wins = ties = 0
    if dimension.family in _REAL_FAMILIES:
        for task in tasks:
            before = _finite(base[task], f"{dimension.name}: base cost for {task}")
            after = _finite(candidate[task], f"{dimension.name}: candidate cost for {task}")
            saving = before - after  # positive is an improvement, as for every family here
            differences.append(saving)
            if saving > 0:
                candidate_wins += 1
            elif saving < 0:
                base_wins += 1
            else:
                ties += 1
        effect = statistics.median(differences)
        interval = median_difference_interval(differences, alpha=alpha)
    else:
        for task in tasks:
            before = _binary(base[task], family=dimension.family, name=dimension.name, task=task)
            after = _binary(candidate[task], family=dimension.family, name=dimension.name, task=task)
            if after and not before:
                candidate_wins += 1
            elif before and not after:
                base_wins += 1
            else:
                ties += 1
        effect = float(candidate_wins - base_wins)
        interval = None

    discordant = candidate_wins + base_wins
    min_discordant = minimum_discordant_pairs(alpha)
    p_value = two_sided_sign_p(candidate_wins, base_wins)
    unit = dimension.unit or "task"

    if discordant < min_discordant:
        return DimensionResult(
            dimension, Verdict.UNDERPOWERED, len(tasks), candidate_wins, base_wins, ties,
            effect, p_value, interval,
            f"{discordant} discordant pair(s) over {len(tasks)} task(s); {min_discordant} "
            f"is the fewest at which a two-sided exact test can reach alpha={alpha} even when "
            f"every pair agrees. The observed {effect:+g} {unit} is not evidence either way.",
            alpha=alpha)

    if p_value > alpha:
        return DimensionResult(
            dimension, Verdict.WITHIN_NOISE, len(tasks), candidate_wins, base_wins, ties,
            effect, p_value, interval,
            f"{effect:+g} {unit} with p={p_value:.3g} against alpha={alpha} "
            f"({DEFAULT_ALPHA_EVIDENCE.value}). The difference may be real and these {len(tasks)} "
            "task(s) cannot tell, which is not the same as no difference.",
            alpha=alpha)

    # Direction follows the sign test itself (candidate_wins vs base_wins), not ``effect > 0``:
    # on a COST dimension with ties >= n/2, a unanimous candidate win (e.g. 7-0 with 8 ties) has
    # median difference 0.0, which ``effect > 0`` would misclassify as WORSE.
    direction = Verdict.BETTER if candidate_wins > base_wins else Verdict.WORSE
    if direction is Verdict.BETTER and effect < dimension.minimum_gain:
        return DimensionResult(
            dimension, Verdict.BELOW_MINIMUM, len(tasks), candidate_wins, base_wins, ties,
            effect, p_value, interval,
            f"{effect:+g} {unit} is resolved (p={p_value:.3g}) but below the "
            f"{dimension.minimum_gain:g} {unit} declared worth acting on "
            f"({dimension.minimum_gain_evidence.value}"
            f"{': ' + dimension.minimum_gain_source if dimension.minimum_gain_source else ''}). "
            "Real and not worth the change.",
            alpha=alpha)

    return DimensionResult(
        dimension, direction, len(tasks), candidate_wins, base_wins, ties, effect, p_value,
        interval,
        f"{effect:+g} {unit} over {len(tasks)} task(s), p={p_value:.3g} against alpha={alpha} "
        f"({DEFAULT_ALPHA_EVIDENCE.value}). "
        + ("Larger than the declared minimum." if direction is Verdict.BETTER
           else "The candidate is worse on this dimension."),
        alpha=alpha)


def _waiver_change(observations: Mapping[str, Mapping[str, object]] | None) -> int:
    """How many more tasks the candidate had to waive than the base did.

    D3: a waiver is not a win. It is also a signal in its own right -- a revision that keeps its
    pass rate by waiving more is not the same revision as one that keeps it by being right, and
    the two are indistinguishable if only ``admitted`` is counted.
    """

    if not observations:
        return 0
    base = observations.get("base", {})
    candidate = observations.get("candidate", {})
    waived = sum(1 for value in candidate.values() if value == "admitted_under_waiver")
    before = sum(1 for value in base.values() if value == "admitted_under_waiver")
    return waived - before


def compare_revision(
    *,
    dimensions: Sequence[tuple[Dimension, Mapping[str, object], Mapping[str, object]]],
    assessment_role: str,
    base_catalogue_digest: str,
    candidate_catalogue_digest: str,
    declared_scope: Sequence[str],
    measured_scope: Sequence[str] = (),
    alpha: float = DEFAULT_ALPHA,
) -> Comparison:
    """Rule on a whole revision: every dimension, then how far the result may be taken.

    ``dimensions`` is a sequence of ``(Dimension, base_observations, candidate_observations)``,
    each observation mapping task id to that task's value.

    ``measured_scope`` defaults to ``declared_scope``; supply the narrower set when the evaluation
    covered fewer conditions than the revision claims, which is the ordinary case and the reason
    :attr:`Adoption.SCOPED` exists.
    """

    if assessment_role not in {"diagnostic", "independent_validation"}:
        raise ValueError("assessment_role must be diagnostic or independent_validation")
    # A SHA-256, because that is what ``admission_view.catalogue_digest()`` returns and what the
    # research step's validator will accept. Checked here rather than at the record, so a
    # comparison that cannot be written down fails while its author is still looking at it.
    if not isinstance(base_catalogue_digest, str) or not _SHA256.fullmatch(base_catalogue_digest):
        raise ValueError(
            "the catalogue digest must be a 64-character lowercase SHA-256, as returned by "
            "learn.admission_view.catalogue_digest(). A comparison carrying anything else "
            "cannot be recorded on the decision step that would cite it.")
    if base_catalogue_digest != candidate_catalogue_digest:
        raise NotComparable(
            "the two sides were ruled under different fault catalogues "
            f"({base_catalogue_digest[:12]} and {candidate_catalogue_digest[:12]}). A difference "
            "across a catalogue change is a difference in what counts as a fault, not in the "
            "method. Re-rule one side under the other's catalogue before comparing.")
    declared = tuple(dict.fromkeys(str(item) for item in declared_scope))
    if not declared:
        raise ValueError("a revision must declare the scope it claims")
    measured = tuple(dict.fromkeys(str(item) for item in measured_scope)) or declared
    if not set(measured) <= set(declared):
        raise NotComparable(
            "the measured conditions are not inside the declared scope: "
            f"{sorted(set(measured) - set(declared))}. Widen the declaration or narrow the claim.")
    if not dimensions:
        raise ValueError("a comparison needs at least one dimension")

    results = tuple(compare_dimension(dimension, base, candidate, alpha=alpha)
                    for dimension, base, candidate in dimensions)
    tasks: tuple[str, ...] = tuple(sorted({
        task for _, base, _ in dimensions for task in base}))

    waiver_deltas = [
        _waiver_change({"base": base, "candidate": candidate})
        for dimension, base, candidate in dimensions
        if dimension.family in _ADMISSION_FAMILIES
    ]
    waiver_change = sum(waiver_deltas)
    waiver_increase = sum(delta for delta in waiver_deltas if delta > 0)

    by_family: dict[Family, list[DimensionResult]] = {}
    for result in results:
        by_family.setdefault(result.dimension.family, []).append(result)

    quality_families = (Family.WARRANT, Family.REFUSAL, Family.COVERAGE, Family.PROVENANCE)
    regressions = [r for r in results if r.regressed]
    quality_gain = any(r.improved for family in quality_families
                       for r in by_family.get(family, []))
    cost_gain = any(r.improved for r in by_family.get(Family.COST, []))

    reservations: list[str] = []
    adoption = Adoption.FULL

    def cap(level: Adoption, reason: str) -> None:
        nonlocal adoption
        order = (Adoption.FULL, Adoption.SCOPED, Adoption.DIAGNOSTIC_ONLY, Adoption.REFUSED)
        if order.index(level) > order.index(adoption):
            adoption = level
        reservations.append(reason)

    for result in regressions:
        if result.dimension.family in quality_families:
            cap(Adoption.REFUSED,
                f"{result.dimension.name}: the candidate is worse on a quality dimension "
                f"({result.effect:+g}, p={result.p_value:.3g}). A cost saving does not pay for it.")
        else:
            cap(Adoption.SCOPED,
                f"{result.dimension.name}: the candidate costs more "
                f"({-result.effect:+g} {result.dimension.unit}).")

    if not quality_gain and not cost_gain:
        cap(Adoption.REFUSED,
            "no dimension was shown to improve. Keep the previous version: adopting on an "
            "unestablished difference is how a loop reports progress every round while drifting.")
    elif regressions and not quality_gain:
        cap(Adoption.REFUSED,
            "the only gain is cost and there is a measured regression to pay for it.")

    if waiver_increase > 0:
        if quality_gain:
            cap(Adoption.SCOPED,
                f"the candidate waived {waiver_increase} more task(s) than the base. A waiver is "
                "not a win (RSI_REWARD D3); the gain holds only where no waiver was needed.")
        else:
            cap(Adoption.REFUSED,
                f"the candidate waived {waiver_increase} more task(s) and showed no quality gain. "
                "Keeping a pass rate by waiving more is not an improvement.")

    if assessment_role == "diagnostic" and adoption in (Adoption.FULL, Adoption.SCOPED):
        cap(Adoption.DIAGNOSTIC_ONLY,
            "measured in the diagnostic lane. The candidate may be tried locally; it may not be "
            "claimed as an improvement or made a default until an independent validation is "
            "frozen and run.")

    if set(measured) != set(declared) and adoption is Adoption.FULL:
        cap(Adoption.SCOPED,
            "the evidence covers "
            f"{len(measured)} of the {len(declared)} declared condition(s); adopt only for "
            f"{', '.join(measured)}.")

    underpowered = [r.dimension.name for r in results if r.verdict is Verdict.UNDERPOWERED]
    unmeasured = [r.dimension.name for r in results if r.verdict is Verdict.NOT_MEASURED]
    if underpowered and adoption is Adoption.FULL:
        cap(Adoption.SCOPED,
            f"not established on {', '.join(underpowered)}: too few discordant pairs. The "
            "adoption rests on the dimensions that were resolved.")
    if unmeasured and adoption is Adoption.FULL:
        cap(Adoption.SCOPED,
            f"no observations for {', '.join(unmeasured)}; these are not obtained rather than "
            "unchanged.")

    gain = (Gain.BOTH if quality_gain and cost_gain else
            Gain.QUALITY if quality_gain else Gain.COST if cost_gain else Gain.NONE)
    if adoption is Adoption.REFUSED:
        gain = Gain.NONE if not (quality_gain or cost_gain) else gain

    scope = declared if adoption is Adoption.FULL else measured
    headline = {
        Adoption.FULL: "Adopt across the declared scope.",
        Adoption.SCOPED: "Adopt, bounded by the reservations below.",
        Adoption.DIAGNOSTIC_ONLY: "Do not promote; the lane cannot carry the claim.",
        Adoption.REFUSED: "Keep the previous version.",
    }[adoption]
    note = f"{headline} Gain: {gain.value}. " + (
        " ".join(f"({i + 1}) {reason}" for i, reason in enumerate(reservations))
        if reservations else "No reservations.")

    return Comparison(
        adoption=adoption, gain=gain, dimensions=results, tasks=tasks,
        assessment_role=assessment_role, catalogue_digest=base_catalogue_digest,
        scope=scope, declared_scope=declared, reservations=tuple(reservations),
        waiver_change=waiver_change, note=note)


def warrant_observations_from_admission_view(
    view: Mapping[str, object],
    task_nodes: Mapping[str, str],
    *,
    use_exact: bool = True,
) -> tuple[dict[str, str], str]:
    """Extract paired ``WARRANT`` observations and ``catalogue_digest`` from an admission view.

    Refuses any task whose mapped ``node_id`` is absent from ``view['nodes']`` rather than
    silently dropping tasks (preserves paired denominator honesty).
    """

    if not isinstance(view, Mapping) or "nodes" not in view or "catalogue_digest" not in view:
        raise ValueError("view must be an admission_view output carrying nodes and catalogue_digest")
    cat_digest = view["catalogue_digest"]
    if not isinstance(cat_digest, str) or not cat_digest:
        raise ValueError("view catalogue_digest must be nonempty text")
    nodes_raw = view["nodes"]
    if not isinstance(nodes_raw, Sequence):
        raise ValueError("view nodes must be a sequence")
    if not isinstance(task_nodes, Mapping) or not task_nodes:
        raise ValueError("task_nodes must map at least one task_id to a graph node_id")

    field = "exact_admission" if use_exact else "admission"
    by_id: dict[str, Mapping[str, object]] = {}
    for row in nodes_raw:
        if isinstance(row, Mapping) and isinstance(row.get("node_id"), str):
            by_id[row["node_id"]] = row

    observations: dict[str, str] = {}
    for task_id, node_id in task_nodes.items():
        if not isinstance(task_id, str) or not task_id or not isinstance(node_id, str) or not node_id:
            raise ValueError("task_nodes entries must be nonempty string pairs")
        row = by_id.get(node_id)
        if row is None:
            raise NotComparable(f"task {task_id!r} references node {node_id!r} absent from admission view")
        value = row.get(field)
        if not isinstance(value, str) or value not in ADMISSION_STATES:
            raise ValueError(f"node {node_id!r} carries invalid {field}: {value!r}")
        observations[task_id] = value
    return observations, cat_digest


def compact_comparison(comparison: Comparison) -> dict[str, object]:
    """Token-efficient summary card of a :class:`Comparison` preserving every decision fact."""

    return {
        "adoption": comparison.adoption.value,
        "outcome": comparison.outcome,
        "gain": comparison.gain.value,
        "assessment_role": comparison.assessment_role,
        "task_count": len(comparison.tasks),
        "waiver_change": comparison.waiver_change,
        "scope": list(comparison.scope),
        "declared_scope": list(comparison.declared_scope),
        "catalogue_digest": comparison.catalogue_digest,
        "dimensions": [
            {
                "name": item.dimension.name,
                "family": item.dimension.family.value,
                "verdict": item.verdict.value,
                "wins": f"{item.candidate_wins}-{item.base_wins} (ties:{item.ties})",
                "effect": item.effect,
                "unit": item.dimension.unit or "task",
                "p_value": round(item.p_value, 6),
            }
            for item in comparison.dimensions
        ],
        "reservations": list(comparison.reservations),
        "note": comparison.note,
    }


__all__ = [
    "ADMISSION_STATES",
    "Adoption",
    "Comparison",
    "DEFAULT_ALPHA",
    "Dimension",
    "DimensionResult",
    "Family",
    "Gain",
    "MINIMUM_DISCORDANT_PAIRS",
    "NotComparable",
    "Verdict",
    "WARRANTED_STATE",
    "compact_comparison",
    "compare_dimension",
    "compare_revision",
    "median_difference_interval",
    "minimum_discordant_pairs",
    "two_sided_sign_p",
    "warrant_observations_from_admission_view",
]
