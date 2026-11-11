"""The names `bindings` reserves, and what each must be if it appears.

`bindings` is free-form on purpose -- it carries exact evidence refs, publication ids, a
pose label, whatever the writer needs. It is also where ETALON's own annotations about a
record live: `produced_by` is described in `capability_attribution.py` as *the reserved
bindings key*. Both things are true at once, and that is the whole problem. A key in
`bindings` is read later as ETALON's annotation, so two classes of name are not the
caller's to spend:

``IN_USE``
    ETALON writes it and defines its shape. A caller may pass one, but only well formed:
    a malformed block under a reserved name would read afterwards as ETALON's own output.

``WITHDRAWN``
    ETALON decided **not** to compute it. Nothing produces it, so any value under that name
    is a host's judgement wearing a field's name -- indistinguishable from a computed one
    the moment the session ends, which is the harm `admission` exists to refuse.

**Why this is code and not a convention.** The hazard was created by prose: a skill told the
host to fill soundness and progress "from rules over the fault codes", and the paragraph's
own closing clause explained why that was unsafe. Prose asking a host not to do something is
the mechanism this round measured as ineffective (`FIXED_TERMINOLOGY_STATUS.md` §6.4), and
the first repair attempted was a *second* piece of prose-policing: a regular expression
hunting imperatives in 28 skill files. That probe silently matched nothing twice. The
instrument was wrong, not the pattern.

So the question was re-asked at the right layer -- *why can a field that does not exist be
written at all?* -- and answered where it binds. Measured before building this, read-only
except for a throwaway campaign (2026-11-10, Evidence ``measured_here``):

* ``Artifact(bindings={"soundness": "sound", "progress": "advanced"})`` was written and read
  back intact. The hole.
* ``MethodEvaluation(..., soundness="sound")`` already raised ``TypeError``: a typed record
  with fixed fields was never exposed.

A field that cannot be written needs no document forbidding it. And by the hardening
criterion this refusal is the cheap kind: the write fails in the same session, visibly, so
nothing is lost that a later reader would have to reconstruct.

**What this does not do.** It does not police a record's *payload*. A payload is the
caller's own document, its schema is the caller's, and `progress` in one may legitimately
mean how far a screen got -- `boundary/screen.py:178` has exactly that field. Payloads that
claim to be ETALON records carry `schema` and go through typed validation instead. Nor does
it match substrings: `as_of_progress_not_live_heartbeat` is a *value* in
`examples/research_closeout.py` and a key named `progress_note` is the caller's own. Only
the exact names ETALON claimed are refused.
"""
from __future__ import annotations

from typing import Any

from .capability_attribution import KEY as PRODUCED_BY


def _valid_attribution(value: Any) -> bool:
    """Whether a `produced_by` block is one `capability_attribution` would have written."""

    from .capability_attribution import BASES

    if not isinstance(value, dict) or set(value) - {"capability", "basis", "version"}:
        return False
    if not isinstance(value.get("capability"), str) or not value["capability"].strip():
        return False
    if value.get("basis") not in BASES:
        return False
    return "version" not in value or isinstance(value["version"], str)


#: Reserved and in use: ETALON writes these and defines their shape.
IN_USE: dict[str, tuple[Any, str]] = {
    PRODUCED_BY: (_valid_attribution,
                  "which capability produced the record; written by "
                  "research/capability_attribution.py, shape {capability, basis, version?}"),
}

#: Reserved and withdrawn: ETALON decided not to compute these, so nothing may carry them.
#: One definition for the whole repository -- `CLAUDE.md`'s 已撤回的固定术语 section and
#: `tests/test_normative_consistency.py` read this rather than restating the names, because a
#: vocabulary maintained twice goes stale and this one has consequences at a write.
WITHDRAWN: dict[str, str] = {
    "soundness": (
        "withdrawn 2026-11-10 (FIXED_TERMINOLOGY_STATUS.md §6). Nothing computes it. What it "
        "would have named is already carried, and carried more finely, by Ruling's "
        "blocking/waived/bounded/unverifiable/unchecked split and each fault's Consequence "
        "of WRONG_SUBJECT/WRONG_SIZE/UNVERIFIABLE. Read it off the ruling instead."
    ),
    "progress": (
        "withdrawn 2026-11-10 (FIXED_TERMINOLOGY_STATUS.md §6). Nothing computes it, and its "
        "three proposed values do not share a subject: `advanced` at research/entry.py:114 is "
        "checkpoint freshness and `regressed` at learn/acquire.py:10 is statistical regression "
        "to a conditional mean. Compare against a retained baseline if that is the question."
    ),
}


class ReservedBindingError(ValueError):
    """A record tried to carry a reserved binding it may not carry."""


def validate_bindings(bindings: Any, *, record: str = "record") -> None:
    """Refuse a reserved name a caller may not spend. Silent on everything else.

    Called from the record types that own a `bindings` mapping, so the refusal lands at the
    write rather than at a reader's discretion. A non-mapping is left to the caller's own
    validation: this function has one job and overlapping two validators would make the
    error message depend on import order.
    """

    if not isinstance(bindings, dict):
        return
    for key in bindings:
        if key in WITHDRAWN:
            raise ReservedBindingError(
                f"{record} bindings carry {key!r}, which is a withdrawn ETALON field name: "
                f"{WITHDRAWN[key]} A value here would be your judgement under a field's name, "
                "which no later reader can tell from a computed one. Record it under a name of "
                "your own if you need it kept."
            )
        if key in IN_USE and not IN_USE[key][0](bindings[key]):
            raise ReservedBindingError(
                f"{record} bindings carry a malformed {key!r}: {IN_USE[key][1]}. A reserved "
                "name with the wrong shape reads afterwards as ETALON's own output."
            )


__all__ = ["IN_USE", "WITHDRAWN", "ReservedBindingError", "validate_bindings"]
