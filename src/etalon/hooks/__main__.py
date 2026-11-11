"""One entry point for the four session hooks: ``python -m etalon.hooks --hook <name>``.

The transport is ``research_hooks.py``'s, deliberately: the hook event arrives as JSON on stdin,
the native host response goes to stdout as JSON, diagnostics go to stderr, and the exit code says
whether the hook ran rather than what it found. A host installs this beside the existing research
hook rather than instead of it; the two share no state directory and no receipt identity, so adding
one does not invalidate the other's receipts.

Exit codes:

``0``
    The hook ran. ``stdout`` carries the host response, which is ``{}`` for a quiet hook and a
    ``hookSpecificOutput`` envelope for an interruption or a block.
``1``
    The hook could not run -- a missing argument, an unreadable event, an unreadable journal.
    ``stderr`` carries the reason. A host that treats this as a failed tool call is reading it
    correctly: nothing was assessed.

A non-zero exit never means "the agent did something wrong". The one hook that can object does so
through ``permissionDecision`` in its own output, not through the exit code, so that a host without
hook-level enforcement still receives the finding as text. Blocking by exit code would make the
objection invisible to exactly the hosts that cannot act on it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from etalon.hooks.session import canonical, host_output

MAX_EVENT_BYTES = 1024 * 1024

HOOKS = ("rule_replay", "budget_floor", "tool_error_loop", "regime_drift")


def _event() -> dict:
    raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError("hook event exceeds byte limit")
    if not raw.strip():
        return {}
    event = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(event, dict):
        raise ValueError("hook event must be a JSON object")
    return event


def run(name: str, event: dict, arguments: argparse.Namespace):
    """Dispatch one hook. Each is a plain function and is callable without this module."""

    if name == "tool_error_loop":
        from etalon.hooks import tool_error_loop

        if not arguments.state_dir:
            raise ValueError("--state-dir is required: this hook counts repetitions across calls")
        return tool_error_loop.assess(
            event, state_dir=str(arguments.state_dir), session_id=arguments.session_id
        )
    if name == "budget_floor":
        from etalon.hooks import budget_floor

        if not arguments.database:
            raise ValueError("--database is required: the allowance is read from the campaign journal")
        return budget_floor.assess(str(arguments.database))
    if name == "regime_drift":
        from etalon.hooks import regime_drift

        if not arguments.database:
            raise ValueError("--database is required: the regime is read from the campaign journal")
        return regime_drift.assess(str(arguments.database), limit=arguments.window)
    if name == "rule_replay":
        from etalon.hooks import rule_replay

        contract = None
        if arguments.contract:
            contract = json.loads(Path(arguments.contract).read_text(encoding="utf-8-sig"))
        reference = None
        if arguments.contract_ref:
            reference = json.loads(Path(arguments.contract_ref).read_text(encoding="utf-8-sig"))
        # The declared outcome and the conclusion come from the event where the host puts them, so
        # a host that routes this hook on a submit tool need not restate them on the command line.
        payload = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        return rule_replay.assess(
            contract=contract,
            contract_ref=reference,
            workspace=str(arguments.workspace) if arguments.workspace else None,
            declared=arguments.declared or payload.get("claim") or payload.get("declared_status")
            or payload.get("judgment"),
            conclusion=arguments.conclusion or str(payload.get("conclusion") or ""),
            plan_detail=payload.get("plan_detail"),
            observed=payload.get("observed"),
        )
    raise ValueError(f"unknown hook {name!r}; choose from {HOOKS}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", choices=HOOKS, required=True)
    parser.add_argument("--state-dir", type=Path, help="session memory for tool_error_loop")
    parser.add_argument("--database", type=Path, help="campaign journal, read-only")
    parser.add_argument("--workspace", type=Path, help="published-evidence workspace for refs")
    parser.add_argument("--contract", type=Path, help="an evaluation contract, as a JSON file")
    parser.add_argument("--contract-ref", type=Path, help="an evidence ref, as a JSON file")
    parser.add_argument("--declared", default="", help="the claimed outcome, in the contract vocabulary")
    parser.add_argument("--conclusion", default="", help="the free-text conclusion, never blocked on")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--window", type=int, default=200)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="also write the full finding to stderr, including for a quiet hook",
    )
    arguments = parser.parse_args(argv)
    try:
        event = _event()
        interruption = run(arguments.hook, event, arguments)
        output = host_output(
            interruption, event_name=str(event.get("hook_event_name") or "PreToolUse")
        )
        if arguments.verbose:
            sys.stderr.buffer.write(canonical(interruption.as_dict()) + b"\n")
        sys.stdout.buffer.write(canonical(output) + b"\n")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        sys.stderr.buffer.write(
            canonical(
                {
                    "ok": False,
                    "hook": arguments.hook,
                    "error": {"type": type(error).__name__, "message": str(error)[:1024]},
                    "assessed": False,
                }
            )
            + b"\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
