#!/usr/bin/env python3
"""Count SPENDS tools whose signature accepts no authorization object, from the registration index.

The architecture review asks for this number rather than for a score: *"the number of SPENDS tools
whose signature accepts no authorization object, with the number of SPENDS tools as the
denominator. Today that is 7 of 7 for spend tokens; the proposal moves it, and the count is
checkable mechanically from the registration index."*

So it is taken mechanically. ``etalon.mcp.server.tool_catalog`` walks the one registration function
the server and the cost index share -- a missing cost classification or a duplicate tool name fails
index construction, which is why there is exactly one place to read -- and this probe inspects each
registered callable's signature for a parameter that carries a token.

Two docstrings in the tree reason *from* this census and had been stale by thirty tools and two
spenders. That is the reason this exists as a probe rather than as a sentence: a number a paragraph
argues from should be re-derivable by anybody reading the paragraph.

Exits nonzero when the count of unguarded SPENDS tools is above ``--max-unguarded``, so it can be
used as a falsifier the way ``tools/falsify_determinism.py`` and ``tools/measure_council.py`` are.
With no argument it reports and exits 0: a census is not a failure.

Usage::

    python tools/count_unguarded_spends.py
    python tools/count_unguarded_spends.py --max-unguarded 6
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys

#: Parameter names that carry an authorization. A gate authorization and a spend token are
#: different objects guarding different acts, and they are reported separately rather than summed:
#: ``authority/gate.py`` exists because removing the expensive stage makes every object in
#: ``authority/grant.py`` inert, not because the two are interchangeable.
GATE_PARAMETERS = ("gate_json", "gate")
SPEND_PARAMETERS = ("token", "token_json", "authorization", "authorization_json", "spend_token")


def census() -> dict[str, object]:
    from etalon.mcp import server

    catalog = server.tool_catalog()
    functions: dict[str, object] = {}

    class Collector:
        def tool(self):
            def decorate(function):
                functions[function.__name__] = function
                return function

            return decorate

    server.register_tools(Collector())

    spends = sorted(name for name, item in catalog.items() if item["cost"] == "spends")
    rows = []
    for name in spends:
        function = functions.get(name)
        try:
            parameters = tuple(inspect.signature(function).parameters)
        except (TypeError, ValueError):
            parameters = ()
        gate = [p for p in parameters if p in GATE_PARAMETERS]
        spend = [p for p in parameters if p in SPEND_PARAMETERS]
        rows.append(
            {
                "tool": name,
                "gate_authorization_parameters": gate,
                "spend_token_parameters": spend,
                "accepts_an_authorization_object": bool(gate or spend),
            }
        )
    unguarded = [row for row in rows if not row["accepts_an_authorization_object"]]
    costs: dict[str, int] = {}
    for item in catalog.values():
        costs[item["cost"]] = costs.get(item["cost"], 0) + 1
    return {
        "tools": len(catalog),
        "by_cost": dict(sorted(costs.items())),
        "spends_tools": len(spends),
        "spends_tools_accepting_no_authorization_object": len(unguarded),
        "denominator": len(spends),
        "spends_tools_accepting_a_spend_token": sum(1 for row in rows if row["spend_token_parameters"]),
        "spends_tools_accepting_a_gate_authorization": sum(
            1 for row in rows if row["gate_authorization_parameters"]
        ),
        "detail": rows,
        "method": (
            "etalon.mcp.server.tool_catalog for the cost class, inspect.signature for the "
            "parameters; a parameter is an authorization only if its name is in GATE_PARAMETERS or "
            "SPEND_PARAMETERS in this file"
        ),
        "evidence": "measured_here",
        "not_established": (
            "a parameter accepting a token does not establish that the tool refuses without one. "
            "That is reachability, and tools/falsify_optional_guard.py is the probe for it."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-unguarded",
        type=int,
        default=None,
        help="exit nonzero when more SPENDS tools than this accept no authorization object",
    )
    arguments = parser.parse_args(argv)
    report = census()
    print(json.dumps(report, indent=2, sort_keys=True))
    if arguments.max_unguarded is None:
        return 0
    observed = report["spends_tools_accepting_no_authorization_object"]
    if observed > arguments.max_unguarded:
        print(
            f"\nFAILED: {observed} of {report['denominator']} SPENDS tools accept no "
            f"authorization object, above the declared maximum of {arguments.max_unguarded}.",
            file=sys.stderr,
        )
        return 1
    print(
        f"\nPASSED: {observed} of {report['denominator']} SPENDS tools accept no authorization "
        f"object, at or below {arguments.max_unguarded}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
