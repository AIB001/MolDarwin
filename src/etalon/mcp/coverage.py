"""Mint the observations an admission ruling rests on; report the rest as absent, never as clean.

``authority/grant.py`` carries the strongest construction in this repository and states it in its
own docstring: :func:`~etalon.authority.grant.authorize` *"does not take a verdict from the caller
-- it calls ``etalon.faults.preflight.check_record`` itself. A function that accepted 'this one
passed' as an argument would be a guard on the path nobody takes with extra steps."* That guard
stands in front of a GPU-hour.

``etalon_rule_admissible`` stands in front of the path ``learn/admissible.py``'s own docstring
calls the more consequential one -- *"withholding a good measurement costs one molecule's
information; admitting a bad one costs a shift in the policy applied to all of them"* -- and it
took the entire observation list as JSON from the model, constructing each entry with
``fired=item.get("fired", False)`` and ``evaluable=item.get("evaluable", True)``. The code was
visibly careful about one adjacent hazard: a comment ensures ``evaluable=0`` cannot become an
unchecked pass. But an **omitted** observation is not ``unchecked``. It is absent, and
:func:`~etalon.learn.admissible.rule` has nothing to sort. A caller passing ``observations: []``
received a ``Ruling`` with an empty ``blocking`` set, which is ``Admission.ADMITTED``, and
``AdmissionReport.rate`` counted it as admitted. Ten preflight causes unexamined read as a clean
ruling.

This module is ``authorize()``'s construction applied to that path, and it is hardened code rather
than an in-session hook for the reason ``.claude/skills/etalon-step-corpus/SKILL.md`` gives about a
different field: *"an inferred value here is indistinguishable from a measured one later, which is
the failure this project has a vocabulary to avoid."* A clean ruling taken over absent observations
is indistinguishable, a year later, from a clean ruling taken over observations that were made.
Nothing here constrains which checks a campaign performs or how; it constrains only what may be
recorded about checks that were not performed, and who computed the ones that were.

Three policies, and the ladder is deliberate -- ``docs/thin-harness/ADMISSION_PROPAGATION.md``'s
staging and the architecture review's P2 both require the first to ship alone:

``report``
    Non-breaking. Where the caller supplies the recorded handoff rows, ETALON mints the per-record
    preflight observations itself; everything else is reported in a ``coverage`` block naming the
    catalogue codes for which no observation exists, split by :class:`~etalon.faults.taxonomy.Phase`
    and :class:`~etalon.faults.taxonomy.Exactness`. No ``Ruling`` changes.

``unchecked_when_absent``
    The architecture review's P2 stage 2. Synthesises ``Observation(code, fired=False,
    evaluable=False)`` for every ``Phase.PREFLIGHT`` code no observation covers, so ``rule()``
    sorts it into ``unchecked`` by its existing branch and writes the note it already has --
    *"clean only as far as anyone looked"* -- about every host-driven ruling rather than only about
    the honest ones.

``unchecked_unless_minted``
    The full form: a host assertion that a check did **not** fire, for a code ETALON did not
    compute, is recorded as unevaluable. This is not a new rule; it is
    ``council/convene``'s bound applied to the same surface -- *a council may move a check from
    unevaluable to fired and may never move one to cleared* -- and the reason is identical. A
    firing host assertion is always kept, because that is the direction that withholds, and because
    a council finding from ``etalon_council_adjudicate`` arrives exactly that way.

Both of the latter two **refuse without a recomputability audit** taken for the live catalogue.
That is not ceremony. ``learn/admission_view.py`` maps an ``unchecked`` code that is exact and
``WRONG_SUBJECT`` to ``not_recorded``, and ``docs/thin-harness/RSI_REWARD.md`` (D4) counts
``not_recorded`` as a loss: *"it is in the denominator and not in the numerator."* Filling
``unchecked`` therefore moves nodes in a derived view, and the honest reading -- that this
*reveals* unestablished warrant rather than creating it -- is a reading somebody has to take with
the counts in hand. ``.claude/skills/etalon-recomputability-audit/SKILL.md`` prescribes those
counts. Requiring the audit as an argument is the same move as requiring the waiver object instead
of the bare code: the decision becomes a record with a name on it rather than a default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover -- the fault layer is imported lazily at call time
    from pathlib import Path

    from etalon.faults.attribution import Observation

#: The policies, weakest first. The order is the rollout order and the only order in which these
#: may be adopted: each later one changes recorded verdicts that the one before it only reported.
POLICIES: tuple[str, ...] = ("report", "unchecked_when_absent", "unchecked_unless_minted")

#: The audit schema the two stricter policies require. Versioned, because an audit is taken for one
#: catalogue and one rule version and
#: ``.claude/skills/etalon-recomputability-audit/SKILL.md`` is explicit that *"a later change needs
#: its own audit; this one does not transfer."*
AUDIT_SCHEMA = "etalon-recomputability-audit/1"

#: The four classes the audit skill requires counted separately, because they fail for different
#: reasons and only one of them is recoverable by work.
AUDIT_CLASSES: tuple[str, ...] = (
    "absent_observations",
    "legacy_record_semantics_inferred",
    "comparatorless_measurements",
    "undecidable_premise_edges",
)

#: What a class whose count could not be taken must say. Per the audit skill: *"A count that could
#: not be taken is reported as not taken; it is not replaced by a plausible figure, and the audit is
#: more useful with a gap in it than with a number nobody measured."* Accepted here, and echoed
#: loudly, rather than silently treated as zero.
NOT_TAKEN = "not_taken"

_MINTABLE: tuple[str, ...] | None = None


def mintable_codes() -> tuple[str, ...]:
    """The codes ETALON can compute from one handoff row, measured rather than declared.

    Taken by calling :func:`~etalon.faults.preflight.check_record` on an empty row and reading back
    which observations it returns. A hand-maintained list of the same codes would be a second
    statement of the same fact, free to drift from the function, and the drift would be invisible
    exactly where it matters: a code that left ``check_record`` would go on being reported as
    mintable and would never be minted.

    This is nine of the ten ``Phase.PREFLIGHT`` faults. ``F_HANDOFF_ABSENT`` is not among them and
    cannot be: it is a fault about a record that is not there, which
    :func:`~etalon.faults.preflight.check_population` answers from the pool rather than from a row.
    """

    global _MINTABLE
    if _MINTABLE is None:
        from etalon.faults.preflight import check_record

        _MINTABLE = tuple(entry.code for entry in check_record({}))
    return _MINTABLE


def mint_from_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    receptor_path: Path | None = None,
    toolchain_active: bool | None = None,
) -> dict[str, tuple[Observation, ...]]:
    """Compute each row's preflight observations here, keyed by ``parent_id``.

    The same call ``authorize()`` makes, for the same reason, on the other path.

    Raises:
        ValueError: When two rows carry one ``parent_id``. Silently keeping the last would let a
            second row's clean checks stand in for a first row's failing ones, which is the
            WRONG_SUBJECT shape applied to the record itself.
    """

    from etalon.faults.preflight import check_record

    minted: dict[str, tuple[Observation, ...]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each record must be an md_system_input/v1 object")
        parent = str(row.get("parent_id", "")).strip()
        if not parent:
            raise ValueError(
                "a record with no parent_id cannot be joined to the measurement it is the "
                "evidence for, and minting it under a placeholder would file one molecule's "
                "checks against another's number"
            )
        if parent in minted:
            raise ValueError(
                f"two records carry parent_id {parent!r}. Which row's checks stand behind the "
                "measurement is then decided by argument order, and the clean one wins as often "
                "as not."
            )
        minted[parent] = check_record(
            row, receptor_path=receptor_path, toolchain_active=toolchain_active
        )
    return minted


def merge(
    minted: Iterable[Observation],
    asserted: Iterable[Observation],
) -> tuple[tuple[Observation, ...], dict[str, list[str]]]:
    """Combine computed and host-supplied observations, moving only toward withholding.

    Two rules, and both have the same justification as ``council/convene``'s bound.

    A code ETALON minted is taken from the minted observation: the host's reading of a check ETALON
    performed is a second opinion about a digest comparison, and the comparison is the evidence.

    A host assertion that **fires** is never discarded, even against a minted observation that did
    not fire. Moving a check to fired is the one direction a non-computing party may move it, it is
    how an ``etalon_council_adjudicate`` finding reaches this tool, and a wrong one costs compute
    and shows up in the admission rate rather than buying a clean record.

    Returns:
        The merged observations in catalogue order where known, and a provenance index with keys
        ``minted``, ``asserted``, ``superseded_by_minted`` and ``asserted_kept_as_fired`` -- each a
        sorted list of codes, so a reader of the response can see who computed what.
    """

    minted_by_code = {entry.code: entry for entry in minted}
    asserted_by_code = {entry.code: entry for entry in asserted}

    merged: dict[str, Observation] = dict(asserted_by_code)
    superseded: list[str] = []
    kept_fired: list[str] = []
    for code, entry in minted_by_code.items():
        previous = merged.get(code)
        if previous is not None and previous.fired and not entry.fired:
            kept_fired.append(code)
            continue
        if previous is not None:
            superseded.append(code)
        merged[code] = entry

    index = {
        "minted": sorted(minted_by_code),
        "asserted": sorted(asserted_by_code),
        "superseded_by_minted": sorted(superseded),
        "asserted_kept_as_fired": sorted(kept_fired),
    }
    return tuple(_in_catalogue_order(merged)), index


def _in_catalogue_order(entries: Mapping[str, Observation]) -> list[Observation]:
    from etalon.faults.taxonomy import FAULTS

    order = {fault.code: position for position, fault in enumerate(FAULTS)}
    return sorted(entries.values(), key=lambda entry: (order.get(entry.code, len(order)), entry.code))


def absent_codes(present: Iterable[str]) -> dict[str, dict[str, list[str]]]:
    """Catalogue codes no observation covers, split by phase and by exactness.

    Split both ways because the two splits answer different questions. The phase says whether the
    check could have been performed before the spend; the exactness says what a missing check costs
    the reward, which ``RSI_REWARD.md`` restricts to ``EXACT`` observables *"ungameable by
    construction rather than by vigilance"*. An absent ``EXACT`` preflight code is the expensive
    kind of gap; an absent ``THRESHOLD`` postflight code is a diagnostic nobody ran.
    """

    from etalon.faults.taxonomy import FAULTS

    seen = set(present)
    result: dict[str, dict[str, list[str]]] = {}
    for fault in FAULTS:
        if fault.code in seen:
            continue
        result.setdefault(fault.phase.value, {}).setdefault(fault.exactness.value, []).append(
            fault.code
        )
    return result


def synthesised_unchecked(present: Iterable[str]) -> tuple[Observation, ...]:
    """``Observation(code, fired=False, evaluable=False)`` for every absent preflight code.

    Preflight only. A postflight cause needs the trajectory or the estimate, and this boundary has
    seen neither; synthesising those would assert that a check which could not have been made here
    was attempted here. They stay in the ``coverage`` block, which is where an absence that nothing
    at this boundary could have resolved belongs.

    ``rule()`` sorts these into ``unchecked`` through the branch it already has, and the note it
    already writes becomes true: *"N check(s) could not be evaluated, so this measurement is clean
    only as far as anyone looked."*
    """

    from etalon.faults.attribution import Observation
    from etalon.faults.taxonomy import Phase, preflight_faults

    seen = set(present)
    return tuple(
        Observation(
            fault.code,
            fired=False,
            detail=(
                "no observation was supplied or minted for this cause at the admission boundary, "
                "so it is recorded as unevaluable rather than as absent"
            ),
            evaluable=False,
        )
        for fault in preflight_faults()
        if fault.code not in seen and fault.phase is Phase.PREFLIGHT
    )


def downgrade_unminted_assertions(
    merged: Iterable[Observation],
    *,
    minted: Iterable[str],
) -> tuple[tuple[Observation, ...], list[str]]:
    """Record a non-firing host assertion for an uncomputed code as unevaluable.

    The strictest rung, and the one the brief's criterion names: a quantity that can reach
    ``admission`` is either computed here from a recorded primitive, or it is host-asserted and
    cannot clear a cause. A firing assertion is untouched for the reason :func:`merge` gives.

    Returns the observations and the sorted codes that were downgraded, so the response can name
    them rather than leaving a caller to notice an admission that moved.
    """

    from etalon.faults.attribution import Observation

    computed = set(minted)
    downgraded: list[str] = []
    result: list[Observation] = []
    for entry in merged:
        if entry.evaluable and not entry.fired and entry.code not in computed:
            downgraded.append(entry.code)
            result.append(
                Observation(
                    entry.code,
                    fired=False,
                    detail=(
                        "host-asserted as not fired and not computed here; recorded as "
                        "unevaluable, because a party that did not make the comparison may move a "
                        "check to fired and may not move one to cleared. Supply the recorded "
                        f"handoff row to have this minted. Host detail: {entry.detail[:200]}"
                    ),
                    evaluable=False,
                )
            )
            continue
        result.append(entry)
    return tuple(result), sorted(set(downgraded))


def catalogue_digest_or_not_taken() -> tuple[str | None, str]:
    """The live catalogue digest, or ``None`` with a reason.

    Imported lazily from ``learn/admission_view.py`` and reported as not taken when it cannot be,
    per hard constraint 7: a quantity that cannot be counted is reported as not taken rather than
    replaced. The import is deliberately not a hard dependency -- that module is the export view and
    is owned elsewhere -- and the only thing lost when it is unavailable is the ability to check an
    audit against the catalogue it was taken for, which is precisely why the stricter policies
    refuse in that case rather than proceeding.
    """

    try:
        from etalon.learn.admission_view import catalogue_digest
    except Exception as error:  # noqa: BLE001 -- the reason is reported, not swallowed
        return None, f"not_taken: catalogue_digest unavailable ({type(error).__name__})"
    try:
        return catalogue_digest(), "measured_here"
    except Exception as error:  # noqa: BLE001
        return None, f"not_taken: catalogue_digest raised ({type(error).__name__})"


def require_audit(payload: Any, *, policy: str) -> dict[str, Any]:
    """Accept a recomputability audit for the live catalogue, or refuse the policy.

    Checks that the audit exists, names this schema, carries all four classes the audit skill
    requires -- each as either a count with its denominator or the literal ``"not_taken"`` -- and
    was taken for the catalogue now loaded. A count without a denominator is refused: *"A
    proportion without its denominator cannot be checked by anyone else."*

    What this cannot check is whether the counts are true. The audit is echoed in full in the
    response for the same reason a waiver is: the defence against a fabricated figure is an
    operator reading it, not a parser.

    Returns:
        The audit, plus a ``classes_not_taken`` list and the digest comparison that was made.

    Raises:
        ValueError: With the remedy in the message, which for this refusal is the name of the skill
            that takes the counts.
    """

    remedy = (
        f"coverage_policy={policy!r} changes recorded verdicts: it fills `unchecked`, and "
        "learn/admission_view maps an unchecked exact WRONG_SUBJECT code to `not_recorded`, which "
        "RSI_REWARD.md (D4) counts as a loss. Run the etalon-recomputability-audit skill, publish "
        "its four counts each with its denominator, and pass the result as audit_json. Use "
        "coverage_policy='report' until then: it reports the same gap and moves no verdict."
    )
    if not isinstance(payload, Mapping):
        raise ValueError(f"audit_json must be a {AUDIT_SCHEMA} object. {remedy}")
    if payload.get("schema") != AUDIT_SCHEMA:
        raise ValueError(
            f"audit_json names schema {payload.get('schema')!r}, not {AUDIT_SCHEMA}. {remedy}"
        )
    for field in ("catalogue_digest", "rule_version", "taken_at", "counted_by"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"audit_json is missing {field}. An audit is taken for one catalogue and one rule "
                "version, and who counted is what makes it answerable later. " + remedy
            )

    not_taken: list[str] = []
    for name in AUDIT_CLASSES:
        if name not in payload:
            raise ValueError(
                f"audit_json does not report {name}. The four classes fail for different reasons "
                "and only one is recoverable by work, so an audit that omits one is not an audit "
                "of this change. " + remedy
            )
        value = payload[name]
        if value == NOT_TAKEN:
            not_taken.append(name)
            continue
        if not isinstance(value, Mapping) or not isinstance(value.get("count"), int) or not isinstance(
            value.get("denominator"), int
        ):
            raise ValueError(
                f"audit_json reports {name} as {value!r}; it must be "
                '{"count": <int>, "denominator": <int>} or the string "not_taken". A proportion '
                "without its denominator cannot be checked by anyone else. " + remedy
            )
        if value["denominator"] < 0 or value["count"] < 0 or value["count"] > value["denominator"]:
            raise ValueError(
                f"audit_json reports {name} as {dict(value)!r}, which is not a count within its "
                "denominator. " + remedy
            )

    live, basis = catalogue_digest_or_not_taken()
    if live is None:
        raise ValueError(
            f"the live catalogue digest could not be taken ({basis}), so this audit cannot be "
            f"shown to have been taken for the catalogue now loaded. {remedy}"
        )
    if payload["catalogue_digest"] != live:
        raise ValueError(
            f"audit_json was taken for catalogue {payload['catalogue_digest'][:12]} and the live "
            f"catalogue is {live[:12]}. A later change needs its own audit; this one does not "
            f"transfer. {remedy}"
        )

    return {
        "audit": dict(payload),
        "classes_not_taken": not_taken,
        "catalogue_digest": live,
        "catalogue_digest_basis": basis,
        "checked": "schema, four classes with denominators, catalogue digest equality",
        "not_checked": "whether the counts are true; read counted_by and the counts themselves",
    }


def coverage_block(
    parent_id: str,
    *,
    provenance: Mapping[str, list[str]],
    observations: Sequence[Observation],
    synthesised: Sequence[str] = (),
    downgraded: Sequence[str] = (),
) -> dict[str, Any]:
    """One measurement's coverage, as counts with their denominator.

    Every number here is ``measured_here`` under hard constraint 5: each is a count over the loaded
    catalogue and this call's own arguments, taken by this function. None of them is a band, a
    threshold or a convention, so none needs a citation -- and the denominator is stated beside each
    rather than left to a reader, per the counting rule both local skills insist on.
    """

    from etalon.faults.taxonomy import FAULTS

    covered = sorted({entry.code for entry in observations})
    unevaluable = sorted({entry.code for entry in observations if not entry.evaluable})
    return {
        "parent_id": parent_id,
        "catalogue_codes": len(FAULTS),
        "codes_with_an_observation": len(covered),
        "codes_with_no_observation": len(FAULTS) - len(covered),
        "absent": absent_codes(covered),
        "minted_by_etalon": provenance["minted"],
        "asserted_by_the_host": provenance["asserted"],
        "host_assertion_superseded_by_minted": provenance["superseded_by_minted"],
        "host_assertion_kept_because_it_fired": provenance["asserted_kept_as_fired"],
        "synthesised_as_unevaluable": list(synthesised),
        "host_assertion_downgraded_to_unevaluable": list(downgraded),
        "codes_recorded_unevaluable": unevaluable,
        "evidence": "measured_here",
        "basis": (
            "counts over etalon.faults.taxonomy.FAULTS as loaded and the observations this call "
            "received or computed; denominator is catalogue_codes"
        ),
        "reading": (
            "codes_with_no_observation is not a count of checks that passed. An absent observation "
            "is neither clean nor dirty; under coverage_policy='report' it does not reach the "
            "Ruling at all, which is why it is reported here."
        ),
    }


__all__ = [
    "AUDIT_CLASSES",
    "AUDIT_SCHEMA",
    "NOT_TAKEN",
    "POLICIES",
    "absent_codes",
    "catalogue_digest_or_not_taken",
    "coverage_block",
    "downgrade_unminted_assertions",
    "merge",
    "mint_from_records",
    "mintable_codes",
    "require_audit",
    "synthesised_unchecked",
]
