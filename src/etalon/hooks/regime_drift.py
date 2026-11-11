"""Surface a session that has stayed in ``diagnostic`` while its conclusions started to rely.

**The two regimes.** ``research/journal.py``'s ``_validate_method_evaluation`` contains a two-line
early return::

    if value.assessment_role == 'diagnostic':
        return

Everything after it is the strongest predeclaration machinery in the repository, and it runs only
for ``independent_validation``: results must be ``validation-`` receipts bound to a ``phi-`` frozen
policy whose search configuration equals the exact subjects/comparators/protocol/split/initial-
conditions binding; inputs must have been recorded *before* the freeze and evidence *after* it; and a
content-addressed loop refuses when bytes already seen are relabelled -- *"already seen artifact
bytes cannot be relabelled as independent validation"*. That is predeclaration enforced on a durable
event sequence rather than asserted. A ``diagnostic`` evaluation receives none of it, and
``research/composition.py`` defaults ``assessment_role="diagnostic"``.

**Why this is surfaced and never refused.** ``diagnostic`` is a legitimate role and freely
explorable is the point of it: nothing propagates, so nothing is at risk from exploring in it. The
architecture review is explicit that forcing the stronger role would make the record *less* honest,
not more -- a host that must declare independent validation to record anything will declare it. And
the failure signature the review names is itself only visible as a report: *"a shift toward
diagnostic with unchanged conclusion language is the failure signature, and it is visible only if
the ratio is reported."* So this hook reports the ratio and the language, and refuses nothing.

**What "language that presumes reliance" means here, and what it does not.** ETALON's fixed
vocabulary separates ``relied_on`` -- a premise the claim rests on, along which admission propagates
-- from ``used``, an input that does not propagate. A diagnostic conclusion that says a method
*established*, *confirms* or *outperforms* something is writing a ``relied_on`` sentence in a lane
where nothing propagates. That is a mismatch worth seeing.

It is a **lexical count and is reported as one**. The matched phrases come back verbatim with the
conclusion they were found in, so the operator reads the sentences rather than trusting the counter;
the lexicon is tagged ``convention`` because somebody chose the words. Conclusions that already
carry the repository's own negative-assertion idiom -- ``not_demonstrated``, ``not_certified``,
``descriptive``, ``diagnostic`` -- are counted as hedged and subtracted, because that idiom is
exactly the honest form and a hook that flagged it would be punishing the right behaviour.

Read-only throughout: the committed event stream through ``runtime.api.read_events`` against a
campaign log opened ``read_only=True``. Nothing is written and no record is amended.
"""

from __future__ import annotations

import re
from typing import Any

from etalon.hooks.session import Interruption, bounded_text, quiet

HOOK = "regime_drift"

EVALUATION_SCHEMA = "etalon-method-evaluation/1"

#: Interrupt at or above this many consecutive ``diagnostic`` evaluations with no
#: ``independent_validation`` among them. Evidence: ``convention``. Nothing has measured where "many
#: steps" begins; eight is a campaign round's batch_size default times two, chosen so that a short
#: exploratory burst does not trip it and a sustained regime does.
DIAGNOSTIC_STEP_FLOOR = 8

#: Interrupt at or above this many reliance phrases across the window's diagnostic conclusions,
#: after hedged conclusions are subtracted. Also ``convention``.
RELIANCE_PHRASE_FLOOR = 3

#: Phrases that write a ``relied_on`` sentence. Evidence: ``convention`` -- somebody chose these
#: words. Each is a verb of establishment or a comparative claim, which are the two shapes that
#: presume the conclusion may be leaned on.
RELIANCE_PHRASES: tuple[str, ...] = (
    "establishes",
    "established",
    "confirms",
    "confirmed",
    "demonstrates",
    "demonstrated",
    "validates",
    "validated",
    "proves",
    "shows that",
    "outperforms",
    "better than",
    "superior to",
    "we adopt",
    "adopt the",
    "recommend adopting",
    "should be used",
    "therefore the",
    "supports the decision",
    "is the best",
)

#: Phrases that mark a conclusion as already hedged in the repository's own idiom. A conclusion
#: carrying one of these is counted and subtracted rather than flagged.
HEDGE_PHRASES: tuple[str, ...] = (
    "not_demonstrated",
    "not demonstrated",
    "not_certified",
    "not certified",
    "not_established",
    "not established",
    "descriptive",
    "diagnostic only",
    "not causal",
    "no independent",
    "provisional",
    "not_performed",
    "unresolved",
)

def _matches(text: str, phrases: tuple[str, ...]) -> list[str]:
    lowered = " ".join(str(text).split()).lower()
    return [phrase for phrase in phrases if phrase in lowered]


def read_evaluations(database: str, *, limit: int = 200) -> tuple[list[dict[str, Any]], str]:
    """Recorded method evaluations in commit order, read-only.

    Taken from the committed event stream rather than from a graph projection, because commit order
    is the quantity the window is over and because the event body carries the whole record: a
    ``research_recorded`` event's body is ``{"id": <record id>, "record": <record>}``, so
    ``assessment_role`` is directly available with no second read.

    Returns the evaluations and the basis. On any read failure the basis says so and the list is
    empty -- never a partial window silently reported as the whole one.
    """

    try:
        from etalon.runtime.api import read_events
    except Exception as error:  # noqa: BLE001
        return [], f"not_taken: the event reader is unavailable ({type(error).__name__})"

    rows: list[dict[str, Any]] = []
    cursor = 0
    pages = 0
    try:
        while pages < 8:
            page = read_events(
                {"kind": "campaign", "database": str(database)},
                after_sequence=cursor,
                limit=min(100, limit),
            )
            events = page.get("events") or ()
            for event in events:
                body = event.get("body")
                record = body.get("record") if isinstance(body, dict) else None
                if isinstance(record, dict) and record.get("schema") == EVALUATION_SCHEMA:
                    rows.append(
                        {
                            "record_id": body.get("id"),
                            "sequence": event.get("sequence"),
                            "assessment_role": record.get("assessment_role"),
                            "conclusion": record.get("conclusion", ""),
                            "scope": record.get("scope", ""),
                        }
                    )
            if not page.get("has_more") or not events:
                break
            cursor = (page.get("next_cursor") or {}).get("after_sequence", cursor)
            pages += 1
    except Exception as error:  # noqa: BLE001
        return [], f"not_taken: the campaign event log could not be read ({type(error).__name__}: {error})"
    rows.sort(key=lambda row: row.get("sequence") or 0)
    return rows[-limit:], (
        f"measured_here: research_recorded events carrying {EVALUATION_SCHEMA}, in commit order, "
        f"over at most {pages + 1} page(s)"
    )


def assess(database: str, *, limit: int = 200) -> Interruption:
    """Report the regime ratio and the reliance language in the diagnostic lane.

    Args:
        database: Absolute path to the campaign journal holding the research records.
        limit: How many evaluations to read back. A window, not a history: the hook is about the
            session's recent regime.
    """

    rows, basis = read_evaluations(database, limit=limit)
    if not rows:
        return quiet(HOOK, basis if basis.startswith("not_taken") else (
            "no method evaluations are recorded in this journal, so there is no regime to report"
        ), basis=basis)

    diagnostic = [row for row in rows if row.get("assessment_role") == "diagnostic"]
    independent = [row for row in rows if row.get("assessment_role") == "independent_validation"]
    other = [
        row
        for row in rows
        if row.get("assessment_role") not in {"diagnostic", "independent_validation"}
    ]

    # The run of consecutive diagnostic records at the end of the window. A session that validated
    # ten records and then explored twice is not drifting; a session that has not left the
    # diagnostic lane for its last twenty is the case this hook is about.
    streak = 0
    for row in reversed(rows):
        if row.get("assessment_role") == "diagnostic":
            streak += 1
        else:
            break

    flagged: list[dict[str, Any]] = []
    hedged = 0
    phrase_total = 0
    for row in diagnostic:
        reliance = _matches(row.get("conclusion", ""), RELIANCE_PHRASES)
        hedges = _matches(row.get("conclusion", ""), HEDGE_PHRASES)
        if not reliance:
            continue
        if hedges:
            hedged += 1
            continue
        phrase_total += len(reliance)
        flagged.append(
            {
                "record_id": row.get("record_id"),
                "sequence": row.get("sequence"),
                "phrases": reliance,
                "conclusion": bounded_text(row.get("conclusion", ""), limit=600),
                "scope": bounded_text(row.get("scope", ""), limit=300),
            }
        )

    finding = {
        "evaluations_examined": len(rows),
        "diagnostic": len(diagnostic),
        "independent_validation": len(independent),
        "unrecognised_role": len(other),
        "ratio_independent_to_diagnostic": (
            None if not diagnostic else round(len(independent) / len(diagnostic), 4)
        ),
        "consecutive_diagnostic_at_the_end_of_the_window": streak,
        "diagnostic_conclusions_with_reliance_language": len(flagged),
        "diagnostic_conclusions_already_hedged": hedged,
        "reliance_phrases_matched": phrase_total,
        "detail": flagged[:8],
        "what_diagnostic_skips": (
            "the frozen-policy binding, the before/after-freeze chronology on the durable record "
            "sequence, the held-out comparison from the frozen initial state, the evidence-role "
            "requirement, and the content-addressed check that already-seen bytes are not "
            "relabelled"
        ),
    }
    evidence = {
        "counts": basis + "; denominator is evaluations_examined",
        "ratio": (
            "measured_here: independent_validation records over diagnostic records in this window. "
            "Reported because a shift toward diagnostic with unchanged conclusion language is the "
            "failure signature and is invisible in any pass rate."
        ),
        "lexicon": (
            f"convention: {len(RELIANCE_PHRASES)} reliance phrases and {len(HEDGE_PHRASES)} hedge "
            "phrases, chosen for this hook. A lexical count, not a reading of the claim -- the "
            "matched sentences are returned verbatim so the operator reads them."
        ),
        "thresholds": (
            f"convention: {DIAGNOSTIC_STEP_FLOOR} consecutive diagnostic records and "
            f"{RELIANCE_PHRASE_FLOOR} unhedged reliance phrases. Nothing has measured where either "
            "boundary is."
        ),
    }

    if streak < DIAGNOSTIC_STEP_FLOOR or phrase_total < RELIANCE_PHRASE_FLOOR:
        return quiet(
            HOOK,
            "the diagnostic run is short of the convention floor, or its conclusions carry no "
            "unhedged reliance language",
            **finding,
        )

    return Interruption(
        hook=HOOK,
        status="interrupt",
        headline=(
            f"{streak} consecutive evaluations recorded as diagnostic, and "
            f"{len(flagged)} of their conclusions are written as though they may be relied on"
        ),
        finding=finding,
        evidence=evidence,
        alternatives=(
            "Nothing is refused and diagnostic is a legitimate role. The mismatch is that a "
            "diagnostic record propagates nothing, while a conclusion saying something was "
            "established or outperformed is a relied_on sentence.",
            "Either restate the conclusions in the diagnostic register -- the repository's own "
            "idiom writes the negative assertion into the record, as in "
            "improvement_policy_learning: 'not_demonstrated' and 'causal_attribution: unresolved; "
            "factorial differences are descriptive' -- or record the next one as "
            "independent_validation and let the chronology gate run.",
            "Recording as independent_validation is a real cost and that is deliberate: it requires "
            "a frozen policy, inputs recorded before the freeze, evidence after it, and bytes that "
            "have not been seen. If that cost cannot be paid yet, the honest record is diagnostic "
            "with a diagnostic conclusion.",
            "This hook does not ask for more independent_validation records. Forcing the stronger "
            "role would make the record less honest, not more.",
        ),
    )


__all__ = [
    "DIAGNOSTIC_STEP_FLOOR",
    "EVALUATION_SCHEMA",
    "HEDGE_PHRASES",
    "HOOK",
    "RELIANCE_PHRASES",
    "RELIANCE_PHRASE_FLOOR",
    "assess",
    "read_evaluations",
]
