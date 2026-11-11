"""Shared machinery: durable per-session state, and the one envelope every hook returns.

Two things are shared and nothing else is. Each hook is independently readable and independently
installable, because a host that wants one of them should not have to take four.

**The envelope.** A hook returns an :class:`Interruption`, which carries a status, a finding, and
the basis of every number in the finding. ``status`` is one of three values and the asymmetry
between them is the package's whole contract: ``quiet`` means the hook looked and found nothing to
say, ``interrupt`` means text the host should read before continuing, and ``block`` is reachable
from exactly one hook in exactly one case. A hook that cannot take its own measurement returns
``quiet`` with the reason -- never ``interrupt`` on a number it could not stand behind, which is
hard constraint 7 applied to the hooks themselves.

**The state.** A hook that fires on the *second* occurrence of something needs to remember the
first, and a hook that reports drift over many steps needs a window. State lives in a directory the
host supplies, under an OS lock, keyed by session, through the same three helpers
``research_hooks.py`` uses -- ``etalon.host._consumer_lock``, ``_root`` and ``_save_cursor``.
Reusing them rather than writing a fourth cursor implementation is deliberate: ``_root`` is the
function that refuses a redirected ancestor, and a hook state directory deserves that check as much
as a delivery receipt does.

State here is **host session state and never a scientific record**. It is keyed by session id, it
is discarded when the session ends, nothing reads it back as evidence, and no hook writes anything
to a ``CampaignStore``, a ``ResearchJournal`` or a ``Ledger``. Hard constraint 6 is not at risk
from this package: it opens the campaign store read-only and the research journal through the
read-only evidence and event readers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

HOOK_SCHEMA = "etalon-session-hook/1"

#: Status values, weakest first.
STATUSES = ("quiet", "interrupt", "block")


def canonical(value: Any) -> bytes:
    """The byte form every digest and every length in this package is taken over."""

    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class Interruption:
    """What one hook found, and the basis of every number in it.

    ``evidence`` is required and is not decoration. Every figure a hook reports is either a count it
    took from records (``measured_here``, with the records named) or a threshold somebody chose
    (``convention``, with the measurement it was chosen against named). Hard constraint 5 applies to
    a hook's own numbers exactly as it applies to a fault's band, and the reason is the same: a
    reader of an interruption sees a number, and the provenance is otherwise one indirection away at
    the moment of reading, which is the only moment anyone reads it.
    """

    hook: str
    status: str
    headline: str
    finding: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    #: What the host could do. Alternatives, never a command: ``research/action_learning.py`` states
    #: the same boundary for its own branches -- *"Hints are the host's previously recorded
    #: alternatives, never executor commands."*
    alternatives: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"hook status must be one of {STATUSES}")
        if not self.hook or not self.headline:
            raise ValueError("an interruption names its hook and says one thing in its headline")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": HOOK_SCHEMA,
            "hook": self.hook,
            "status": self.status,
            "headline": self.headline,
            "finding": self.finding,
            "evidence": self.evidence,
            "alternatives": list(self.alternatives),
            # The same four negative assertions ``research_hooks.py`` writes into every receipt, for
            # the same reason: a record that states what it has not done survives summarisation.
            "execution_permission": "not_granted",
            "automatic_retry": False,
            "scientific_writes": 0,
            "recoverable_in_session": True,
        }


def quiet(hook: str, reason: str, **finding: Any) -> Interruption:
    """A hook that looked and has nothing to say, or could not take its measurement.

    Both cases are ``quiet`` and the ``reason`` distinguishes them, because they must not be
    distinguished by whether anything was reported. A hook that stays silent when it could not read
    the records is a hook whose silence means two things.
    """

    return Interruption(hook=hook, status="quiet", headline=reason, finding=finding)


def host_output(interruption: Interruption, *, event_name: str) -> dict[str, Any]:
    """The native hook response, or an empty object for a quiet hook.

    The data marker is ``research_hooks.py``'s, including its caveat: native hosts choose the
    instruction role of ``additionalContext``, and this marker is not a security sandbox. No text a
    hook surfaces is promoted to a rule.

    A ``block`` additionally carries ``permissionDecision`` for the hosts that honour it. A host
    that does not will read the same text as an interruption, which is the correct degradation: the
    finding is identical and only the enforcement is absent.
    """

    if interruption.status == "quiet":
        return {}
    payload = interruption.as_dict()
    text = (
        "ETALON session-hook finding, not instructions. The numbers below are counts over this "
        "session's own records with their basis attached; they do not grant execution permission "
        "or override host/user rules.\n" + canonical(payload).decode("utf-8")
    )
    specific: dict[str, Any] = {"hookEventName": event_name, "additionalContext": text}
    if interruption.status == "block":
        specific["permissionDecision"] = "deny"
        specific["permissionDecisionReason"] = interruption.headline
    return {"hookSpecificOutput": specific}


class session_state:  # noqa: N801 -- a context manager used as a verb, matching `verified_read`
    """Per-session durable state under an OS lock, in a directory the host supplies.

    Usage::

        with session_state(state_dir, session_id="abc", hook="tool_error_loop") as state:
            state.setdefault("seen", {})
            ...

    The state is written back on a clean exit and left untouched on an exception, so a hook that
    raises halfway cannot record half of what it saw. Nothing here is a scientific transaction: an
    interrupted write loses a hook's memory of one event, which costs a duplicate interruption and
    nothing else.
    """

    def __init__(self, state_dir: str | Path, *, session_id: str, hook: str) -> None:
        if not session_id or not isinstance(session_id, str):
            raise ValueError("session state needs the host's session id")
        self._hook = hook
        self._session = session_id
        self._dir: Path | None = None
        self._lock: Any = None
        self._root = state_dir
        self.value: dict[str, Any] = {}

    def __enter__(self) -> dict[str, Any]:
        from etalon.host import _consumer_lock, _root

        base = _root(self._root) / digest({"session": self._session, "hook": self._hook})
        base.mkdir(parents=True, exist_ok=True)
        self._dir = base
        self._lock = _consumer_lock(base / "writer")
        self._lock.__enter__()
        path = base / "state.json"
        if path.exists():
            try:
                self.value = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                # Disposable session memory. A corrupt file costs one duplicate interruption, so it
                # is rebuilt rather than raised -- unlike a delivery receipt, which is evidence.
                self.value = {}
        if not isinstance(self.value, dict):
            self.value = {}
        self.value.setdefault("schema", HOOK_SCHEMA)
        self.value.setdefault("hook", self._hook)
        return self.value

    def __exit__(self, kind: Any, error: Any, trace: Any) -> None:
        from etalon.host import _save_cursor

        try:
            if error is None and self._dir is not None:
                _save_cursor(self._dir / "state.json", self.value)
        finally:
            if self._lock is not None:
                self._lock.__exit__(kind, error, trace)


def field(row: Any, key: str, default: Any = None) -> Any:
    """One named value from a store row, whichever row type the store handed back.

    ``CampaignStore`` reads rows by name -- ``_status`` does ``a["status"]`` -- which a ``dict`` and
    a ``sqlite3.Row`` both support while only the ``dict`` has ``.get``. A hook that assumed the
    ``dict`` would have silently read every row as empty: no cost anywhere, so a full campaign
    reports as entirely unspent and the hook interrupts about nothing. Reading through one accessor
    is the difference between a report and a fabrication, so it is not left to ``isinstance``.
    """

    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        pass
    return getattr(row, key, default)


def bounded_text(value: Any, *, limit: int = 4096) -> str:
    """A string a hook may put in a finding, truncated with the truncation declared.

    A silently truncated error message is how a repeated-error detector stops seeing a difference
    that was there.
    """

    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[truncated from {len(text)} characters]"


def rounds_of(snapshot: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Each recorded round's summary, whichever of the two shapes the store returns.

    ``CampaignStore.rounds()`` rows and the ``rounds`` member of ``snapshot()`` are read through one
    accessor because a hook that guesses wrong reports zero rounds and interrupts about nothing. A
    row that carries neither shape is skipped and counted, never defaulted.
    """

    for row in snapshot.get("rounds", ()) or ():
        summary = field(row, "summary")
        if isinstance(summary, str):
            try:
                summary = json.loads(summary)
            except ValueError:
                summary = None
        base = dict(row) if isinstance(row, Mapping) else {
            "round_id": field(row, "round_id"), "summary": summary}
        if isinstance(summary, Mapping):
            yield {**base, **summary}
        else:
            yield base


__all__ = [
    "HOOK_SCHEMA",
    "STATUSES",
    "Interruption",
    "bounded_text",
    "canonical",
    "digest",
    "field",
    "host_output",
    "quiet",
    "rounds_of",
    "session_state",
]
