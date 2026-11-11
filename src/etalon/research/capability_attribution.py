"""Which capability produced this record.

Measured on the real journals at `2xpro6000:/home/zx/etalon/runs/*/research.sqlite`
(2026-11-10, read-only): 2001 events, 1565 research records, and **no MCP tool name appears
anywhere in them** -- no event body carries a tool-identifying key either. ETALON records
what was produced and never which capability produced it. Two consequences, both load-bearing:

* A result's provenance chain does not include the tool that made it, so "which of the 89
  verbs are core" cannot be answered from existing data. Every proposal to sparsify the
  tool surface -- host-routed or, later, learned -- needs that answer first. This module is
  the precondition, which is why it comes before any router.
* `source_kind` looks like it answers this and does not. Its vocabulary is
  `{fixture, existing_real_artifact, new_execution}` (`schema.py:45`), it answers whether
  the bytes were produced or staged, and `rows.py:156` already depends on that reading to
  separate `synthetic_fixture` from `measured`. On the real records it is a constant:
  1231 of 1231 are `new_execution` and 1231 of 1231 have `role: diagnostic`, so neither
  field carries any distinguishing information. It is a legitimate, load-bearing field and
  must not be repurposed.

So attribution goes in `bindings`, which is free-form JSON already used to carry exact
evidence_refs, under one reserved key. Nothing in the serialized `Artifact` format or its
digest rules changes (`schema.py:32-34`).

**Declared, never inferred.** A caller that does not say which capability it is gets
`not_recorded`, not a guess. CLAUDE.md constraint 7: a quantity that cannot be obtained is
reported as not obtained. A guessed attribution would be worse than none here, because the
whole purpose is to be the evidence a later routing decision rests on, and an inferred
value is indistinguishable from a measured one later
(`.claude/skills/etalon-step-corpus/SKILL.md:30-35`).

**What this is not.** It records which capability ran, not that the capability was
appropriate, and never that its output is admissible. Attribution is `used`-class
information about a record's making; it is not a premise and it carries no admission
(`ADMISSION_PROPAGATION.md` §11). A host must not read a populated attribution as a sign
that anything was validated.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

#: The reserved bindings key. Namespaced so a future sibling (a routing decision, say) can
#: live beside it without either having to guess the other's shape.
KEY = "produced_by"

#: Written when the caller did not say. Deliberately not absent: a record whose attribution
#: is missing and a record that predates attribution read the same way, and both are honest.
NOT_RECORDED = "not_recorded"

#: A caller naming the capability in the call that writes the record.
DECLARED = "declared"

#: The MCP dispatch layer naming the verb whose execution is in progress. This is **not** an
#: inference and does not weaken the declared-never-inferred rule: `mcp/_common.py::tool`
#: wraps every registered tool and holds `function.__name__`, so the dispatch layer is the
#: one place that *knows* which verb is running. The claim it records is exactly that --
#: which verb's execution wrote this record -- and not that the verb computed the number or
#: that it was the right verb to use.
MCP_TOOL = "mcp_tool"

#: How the attribution was come by. `declared` is the only value a caller may supply; the
#: others exist so a reader can tell "nobody said" apart from "a tool said so itself".
BASES = (DECLARED, MCP_TOOL, NOT_RECORDED)

#: The capability whose execution is in progress, for the records written inside it.
#:
#: A `ContextVar` rather than a module global because `mcp/_common.py::threaded_tool` runs the
#: guarded call through `anyio.to_thread.run_sync`, and because two campaigns may be served
#: concurrently; a global would attribute one tool's records to another's name, which is worse
#: than no attribution. `set`/`reset` with the token restores an outer verb when one tool calls
#: through another, and `with_attribution` keeps the first writer either way.
_RUNNING: ContextVar[str | None] = ContextVar("etalon_running_capability", default=None)


@contextmanager
def running_capability(name: str | None):
    """Name the capability executing for the duration of this block.

    Called by the MCP dispatch wrapper, which is the only layer that knows the verb's name
    without being told. A `None` name is accepted and records nothing, so a caller need not
    branch on whether it has one.
    """

    if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 200):
        raise ValueError("a running capability must be a short nonempty name")
    token = _RUNNING.set(name)
    try:
        yield
    finally:
        _RUNNING.reset(token)


def current_capability() -> str | None:
    """The capability currently executing, or `None` outside any dispatched call.

    `None` is the ordinary answer for direct library use and for a campaign driven from a
    script, and it must stay `None` rather than becoming a guess: a record written outside any
    dispatched verb genuinely has no verb to name.
    """

    return _RUNNING.get()


def attribution(capability: str | None = None, *, basis: str = "declared",
                version: str | None = None) -> dict[str, Any]:
    """One attribution block for a record's `bindings`.

    `capability` is the name a host would recognise -- an MCP tool name such as
    `etalon_method_criterion`, a skill slug, or a registered executor id. `version` pins the
    bundle or protocol identity where the caller has one; it is omitted rather than invented.
    """

    if basis not in BASES:
        raise ValueError(f"attribution basis must be one of {BASES}")
    if capability is None or (isinstance(capability, str) and not capability.strip()):
        return {"capability": NOT_RECORDED, "basis": NOT_RECORDED}
    if not isinstance(capability, str) or len(capability) > 200:
        raise ValueError("capability must be a short name")
    if basis == NOT_RECORDED:
        raise ValueError("a named capability cannot have basis not_recorded")
    block: dict[str, Any] = {"capability": capability, "basis": basis}
    if version is not None:
        if not isinstance(version, str) or len(version) > 200:
            raise ValueError("version must be a short string")
        block["version"] = version
    return block


def with_attribution(bindings: dict[str, Any] | None, capability: str | None = None, *,
                     basis: str = DECLARED, version: str | None = None) -> dict[str, Any]:
    """Add the attribution block to a bindings mapping without disturbing the rest.

    An attribution already present is kept: the first writer is the one that ran, and a
    later layer overwriting it would be recording its own name for someone else's work.

    A caller that names no capability gets the verb currently executing, if there is one.
    The consultation lives here rather than at each write seam on purpose: it was in
    `components.record_json` first, which meant every other caller had to remember the same
    three-line branch -- the debt pattern this round named, a feature enumerating its
    subjects instead of reading a property they already have. An explicit name still
    outranks the verb, because it is the more specific claim: the verb is only the entry
    point to whatever skill or executor actually ran.
    """

    merged = dict(bindings or {})
    if KEY in merged:
        return merged
    if capability is None:
        running = current_capability()
        if running is not None:
            capability, basis = running, MCP_TOOL
    merged[KEY] = attribution(capability, basis=basis, version=version)
    return merged


def read_attribution(record: dict[str, Any]) -> dict[str, Any]:
    """What a record says produced it. Never raises; absence is a value, not an error."""

    bindings = record.get("bindings")
    block = bindings.get(KEY) if isinstance(bindings, dict) else None
    if not isinstance(block, dict) or not isinstance(block.get("capability"), str):
        return {"capability": NOT_RECORDED, "basis": NOT_RECORDED}
    return block


def census(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Count records by the capability that produced them, with the unattributed shown.

    This is the shape the tool-surface question needs: which capabilities actually produce
    records, over what denominator, with the unattributed remainder visible rather than
    dropped. Reported as counts and a denominator, never as a share of the attributed
    subset -- a rate over only the attributed records would read as coverage it does not have.
    """

    by: dict[str, int] = {}
    bases: dict[str, int] = {}
    for record in records:
        block = read_attribution(record)
        name = block["capability"]
        by[name] = by.get(name, 0) + 1
        basis = block.get("basis", NOT_RECORDED)
        bases[basis] = bases.get(basis, 0) + 1
    total = len(records)
    unattributed = by.get(NOT_RECORDED, 0)
    return {
        "schema": "etalon-capability-census/1",
        "records": total,
        "attributed": total - unattributed,
        "not_recorded": unattributed,
        "by_capability": dict(sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))),
        # Reported beside the counts because the two bases are not interchangeable evidence. A
        # `declared` name is as specific as its writer chose to be; an `mcp_tool` name is the
        # verb that was dispatched, which is the right denominator for a tool-surface question
        # and the wrong one for "which skill did this". A census that hid the split would let a
        # routing decision rest on a mixture nobody could separate afterwards.
        "by_basis": dict(sorted(bases.items(), key=lambda kv: (-kv[1], kv[0]))),
        "basis": ("the produced_by binding each record carries: named by its writer, or by the "
                  "MCP dispatch layer for the verb it was executing. Never inferred"),
        "does_not_establish": ("that a capability was appropriate, or that anything it "
                               "produced is admissible. Attribution is used-class "
                               "information about a record's making."),
    }
