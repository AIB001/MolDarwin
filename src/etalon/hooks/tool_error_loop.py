"""On the second occurrence of one tool error, inject the fact that ends the loop.

**The measurement.** A minimally-scaffolded agent repeatedly assumed variables persisted across
calls to a stateless code tool and ate ``NameError`` after ``NameError`` without adapting. An
independent benchmark puts the base rate behind that: of 6617 tool errors, models responded to
**32.9%** and changed a parameter in only **6.6%**. So roughly two thirds of errors produce no
response at all, and of the responses, four fifths change nothing about the call.

**Why a hook.** The failure is visible and recoverable in the same session by construction -- the
error is in the transcript, the next call has not happened yet, and nothing has been recorded. What
is missing is not information; it is the one fact that makes the error legible, delivered on the
occurrence where it still saves work.

**Why the second occurrence and not the first.** A first error is information and the ordinary
response to it is to read it. A second *identical* error is the signal: the input digest did not
move, so whatever was read did not reach the call. One occurrence cannot distinguish a tool that
failed from an agent that is not adapting; two can, and that is the whole of the discrimination.

**What ETALON already does better than the harness those numbers were measured on**, and why this
hook is small. ``runtime/method.py``'s ``_failure_details`` returns a typed ``kind`` in
``{process_exit, missing_output, invalid_result}`` with a ``returncode``, a ``missing_outputs``
list, a 2048-byte ``stderr_tail`` with ``stderr_truncated``, a content-addressed ``stderr`` pin,
and ``stderr_read_error`` kept separate so a log-read failure is not confused with the program's.
Exit code 0 is not read as success: ``"scientific_status": "not_inferred_from_exit_code"``. Retry is
structurally forbidden rather than merely omitted. ``mcp/_common.py`` carries a ``retryable`` flag
and says in the hint when calling again will produce the same thing. The substrate is good. Nothing
counted repetitions.

**The stateless-process fact.** For a code tool, the fact is that each snippet runs as a fresh
process, so nothing assigned in an earlier call is defined in this one. ETALON's own contract states
the same thing from the other side and is worth quoting to an agent that has lost track of it:
``method.run`` is a whole declared program with explicit absolute argv and no shell, it runs as its
own OS process under a detached supervisor, and state crosses steps through ``$ref`` and the step
directory -- so *"variables did not persist across calls"* is not a failure that contract can
produce.

Facts are matched by signature, and where no signature matches, the general fact is **derived rather
than canned**: the count, and the argument names whose values are byte-identical across the
occurrences. That is the fact the 6.6% figure is about.
"""

from __future__ import annotations

import re
from typing import Any

from etalon.hooks.session import Interruption, bounded_text, digest, quiet, session_state

HOOK = "tool_error_loop"

#: Occurrence on which the hook speaks. Two, for the reason in the module docstring: one occurrence
#: cannot distinguish a tool that failed from an agent that is not adapting. Evidence:
#: ``convention``, chosen for that discrimination and not measured.
SPEAK_ON_OCCURRENCE = 2

#: Digits, hex blobs, paths, line numbers and addresses are removed before an error is compared with
#: an earlier one, so that two errors differing only in a temporary directory are recognised as one.
#: Over-normalising would merge two different errors, so this is deliberately short and each pattern
#: is here because it varies between runs of the same mistake.
_NOISE = (
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),
    (re.compile(r"\b[0-9a-f]{12,64}\b"), "<digest>"),
    (re.compile(r"(?:/[\w.\-@+]+){2,}"), "<path>"),
    (re.compile(r"\bline \d+\b"), "line <n>"),
    (re.compile(r"\d+"), "<n>"),
)

#: Signature to fact. Each entry is matched against the normalised error text and the tool name, and
#: each fact is the single thing that ends that loop rather than a list of advice.
FACTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bname '?\w*'? is not defined|\bnameerror\b|\bunboundlocalerror\b", re.I),
        "Each snippet runs as a fresh process. Nothing you assigned in an earlier call is defined "
        "in this one, and no amount of repeating the call will make it defined. State crosses calls "
        "only through files you write and read back, or through arguments you pass in. ETALON's own "
        "execution contract works the same way from the other side: method.run is a declared "
        "program running as its own OS process, and state crosses steps through $ref and the step "
        "directory -- which is why 'the variable did not persist' is not a failure it can produce.",
    ),
    (
        re.compile(r"\bmodulenotfounderror\b|\bno module named\b|\bimporterror\b", re.I),
        "The import is not available in the process that runs this snippet, and that process is a "
        "new one each time. Install or vendor it, or do the work without it. If the call reaches a "
        "vendored asset, a shadowed import is the usual cause and etalon_infrastructure reports it.",
    ),
    (
        re.compile(r"must be an absolute path|paths must be absolute", re.I),
        "A stdio server inherits the working directory of whatever launched it, so a relative path "
        "names different files for different callers and is refused rather than resolved. Pass the "
        "absolute path.",
    ),
    (
        re.compile(r"\bfilenotfound|\bno such file or directory\b", re.I),
        "The path does not exist at the moment of the call. Repeating the call cannot create it: "
        "either the file was never written, or it was written somewhere else. Check what the "
        "producing step actually declared as its output before calling this again.",
    ),
    (
        re.compile(r"waived must be a json array|bare fault code", re.I),
        "A bare fault code releases a check without recording who accepted the consequence, which "
        "is the one thing a waiver is for. Call etalon_recommend_waiver, show the result to the "
        "operator, and pass back what they granted under their own name.",
    ),
    (
        re.compile(r"gate authorization|no gate authorization", re.I),
        "This is a refusal, not a transient failure, and its three causes have different remedies: "
        "no token, an expired or tampered token, and a token minted for a different funnel "
        "revision. A batch library compiles to its own revision, so re-screening the panel does "
        "not make a mismatched revision match -- pass gate_revision_id from etalon_screen_plan "
        "called with reference_library set to the panel's library.",
    ),
    (
        re.compile(r"plan changed|inspect a new plan", re.I),
        "The config or library digest moved after the plan was made, so the plan no longer "
        "describes what would run. Make a new plan and submit that one; the identity check is the "
        "point, not an obstacle.",
    ),
)

#: The general fact, used when no signature matches. Formatted with the repetition count and the
#: arguments that did not change.
GENERAL = (
    "You have now called {tool} {count} times and received the same error. The arguments that are "
    "byte-identical across those calls are: {unchanged}. Measured on 6617 tool errors, models "
    "responded to 32.9% of them and changed a parameter in 6.6%; an unchanged argument list is what "
    "that second number is about. The error is reported as {retryable}, so read the hint before "
    "deciding whether the call or the input is what has to move."
)


def normalise(text: str) -> str:
    """Strip the parts of an error message that vary between two runs of one mistake."""

    value = " ".join(str(text).split()).lower()
    for pattern, replacement in _NOISE:
        value = pattern.sub(replacement, value)
    return value[:600]


def signature(*, tool_name: str, code: str, message: str) -> str:
    """The identity two occurrences must share to be one error.

    ``code`` and the tool name are kept exact; only the message is normalised. ``mcp/_common.py``
    flattens ``StateError``'s whole subtree -- ``BudgetExhausted`` included -- into
    ``code == "StateError"``, so the message is what distinguishes a budget refusal from any other
    state refusal and it must participate in the identity.
    """

    return digest({"tool": tool_name, "code": code, "message": normalise(message)})


def read_error(event: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the error out of a native tool event, in any of the three shapes it arrives in.

    Every ETALON tool returns a JSON *string*, so a failure is ``{"ok": false, "error": {...}}``
    inside text that has to be parsed. A non-ETALON tool's failure is whatever the host put in
    ``tool_response``/``error``, and the host's own ``is_error`` flag is honoured. A response that
    cannot be parsed is reported as unparsed rather than as success:
    ``research_hooks._tool_outcome`` makes the same distinction for the same reason.
    """

    import json

    response = event.get("tool_response")
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except (ValueError, RecursionError):
            response = {"_unparsed": bounded_text(response, limit=600)}
    if isinstance(response, dict):
        error = response.get("error")
        if response.get("ok") is False and isinstance(error, dict):
            context = error.get("context") if isinstance(error.get("context"), dict) else {}
            return {
                "code": str(error.get("code", "")),
                "message": bounded_text(error.get("message", "")),
                "hint": bounded_text(error.get("hint", ""), limit=1024),
                "retryable": bool(error.get("retryable")),
                "tool": str(context.get("tool") or event.get("tool_name") or ""),
            }
        if "_unparsed" in response and event.get("is_error") is True:
            return {
                "code": "UnparsedToolResponse",
                "message": response["_unparsed"],
                "hint": "",
                "retryable": False,
                "tool": str(event.get("tool_name") or ""),
            }
    if event.get("error") is not None or event.get("is_error") is True or (
        event.get("hook_event_name") == "PostToolUseFailure"
    ):
        return {
            "code": str(type(event.get("error")).__name__ if not isinstance(event.get("error"), str) else "ToolError"),
            "message": bounded_text(event.get("error") or response or ""),
            "hint": "",
            "retryable": False,
            "tool": str(event.get("tool_name") or ""),
        }
    return None


def _unchanged_arguments(previous: dict[str, Any], current: Any) -> list[str]:
    """Argument names whose values are byte-identical to the earlier failing call."""

    earlier = previous.get("argument_digests") or {}
    if not isinstance(current, dict):
        return sorted(earlier)
    same = [
        name
        for name, value in current.items()
        if name in earlier and earlier[name] == digest(value)
    ]
    return sorted(same)


def assess(event: dict[str, Any], *, state_dir: str, session_id: str = "") -> Interruption:
    """Record one tool event and speak on the second identical error.

    Args:
        event: The native hook event. ``tool_name``, ``tool_input`` and either ``tool_response``,
            ``error`` or ``is_error`` are read; nothing else is.
        state_dir: Directory for this hook's session memory. Host state, never a scientific record.
        session_id: The host's session id. Falls back to the event's.
    """

    session = session_id or str(event.get("session_id") or "")
    if not session:
        return quiet(HOOK, "the event carries no session id, so no repetition can be counted")
    error = read_error(event)
    if error is None:
        return quiet(HOOK, "the tool returned no error signal")
    tool_name = error["tool"] or str(event.get("tool_name") or "unknown")
    key = signature(tool_name=tool_name, code=error["code"], message=error["message"])
    arguments = event.get("tool_input")

    with session_state(state_dir, session_id=session, hook=HOOK) as state:
        seen = state.setdefault("errors", {})
        previous = seen.get(key)
        count = int(previous.get("count", 0)) + 1 if isinstance(previous, dict) else 1
        unchanged = _unchanged_arguments(previous, arguments) if isinstance(previous, dict) else []
        seen[key] = {
            "count": count,
            "tool": tool_name,
            "code": error["code"],
            "normalised_message": normalise(error["message"]),
            "argument_digests": (
                {name: digest(value) for name, value in arguments.items()}
                if isinstance(arguments, dict)
                else {}
            ),
        }
        state["distinct_errors"] = len(seen)
        state["total_errors"] = sum(
            int(row.get("count", 0)) for row in seen.values() if isinstance(row, dict)
        )
        totals = {"distinct": state["distinct_errors"], "total": state["total_errors"]}

    if count < SPEAK_ON_OCCURRENCE:
        return quiet(
            HOOK,
            "first occurrence of this error; reading it is the ordinary response and the hook stays "
            "out of the way",
            signature=key,
            tool=tool_name,
            code=error["code"],
            session_totals=totals,
        )

    fact = None
    haystack = f"{error['code']} {error['message']}"
    for pattern, text in FACTS:
        if pattern.search(haystack):
            fact = text
            break
    if fact is None:
        fact = GENERAL.format(
            tool=tool_name,
            count=count,
            unchanged=", ".join(unchanged) or "(the call carried no comparable arguments)",
            retryable="retryable" if error["retryable"] else "not retryable",
        )

    return Interruption(
        hook=HOOK,
        status="interrupt",
        headline=f"{tool_name} has returned the same error {count} times",
        finding={
            "signature": key,
            "occurrences": count,
            "tool": tool_name,
            "code": error["code"],
            "message": error["message"],
            "host_hint": error["hint"],
            "retryable": error["retryable"],
            "arguments_unchanged_since_the_previous_failure": unchanged,
            "session_totals": totals,
            "fact": fact,
        },
        evidence={
            "occurrences": (
                "measured_here: a count of events with this exact (tool, code, normalised message) "
                "signature in this session; denominator is session_totals.total"
            ),
            "arguments_unchanged": (
                "measured_here: per-argument sha256 of the current call against the previous "
                "failing call"
            ),
            "speak_on_occurrence": f"convention: {SPEAK_ON_OCCURRENCE}",
            "base_rates": (
                "literature: 32.9% responded and 6.6% changed a parameter, of 6617 tool errors in "
                "an independent benchmark. Cited as the motivation for counting repetitions, not "
                "as a property of this session."
            ),
            "fact": (
                "convention: matched by signature from this module's FACTS table, or derived from "
                "the unchanged arguments when no signature matches"
            ),
        },
        alternatives=(
            fact,
            "If the error is reported as not retryable, calling again will produce it again. That "
            "is what the flag means, and the hint beside it names what to change.",
            "Changing nothing and calling again is the observed default. It is also the one option "
            "that cannot work for an unchanged input.",
        ),
    )


__all__ = [
    "FACTS",
    "GENERAL",
    "HOOK",
    "SPEAK_ON_OCCURRENCE",
    "assess",
    "normalise",
    "read_error",
    "signature",
]
