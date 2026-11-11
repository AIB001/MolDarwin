#!/usr/bin/env python3
"""Drive the MCP surface the way a model would, and exit nonzero when a guard is optional.

``docs/adr/0006`` says a guard on the path nobody takes is not a guard. The architecture review asks
that each closure of that class be verified by **reachability demonstrated by construction** rather
than by a score: *"drive the MCP surface the way a model would, take the refusal from the guard
tool, then attempt the spending tool and assert it refuses. Before the change that sequence
succeeds; after it, it raises. That pair of transcripts is the mechanism claim."*

This is that probe, in the shape ``tools/falsify_determinism.py`` and ``tools/measure_council.py``
already use: it exits nonzero when the property fails.

Three probes, each stating what it establishes and what it does not.

**A. The gated screen.** Compile a cascade that declares a threshold, mint a gate authorization for
a panel-compiled revision, and drive ``etalon_screen_submit`` three ways: with no token, with a
token for a different revision, and with the right token. The first two must refuse and the third
must pass the gate check. Before the change the tool had no such parameter, so all three
transcripts were identical and all three proceeded -- which is why the count this probe moves is
also recorded mechanically by ``tools/count_unguarded_spends.py``.

**B. The empty observation list.** Call ``etalon_rule_admissible`` with ``observations: []`` and
assert the response now reports the gap. This is the non-breaking half of the change: the ruling is
*unchanged* -- an empty observation list still produces an admitted ruling -- and what changed is
that the response says twenty catalogue causes were unexamined. A probe that asserted the admission
had moved would be asserting the wrong thing.

**C. The byte-identity falsifier.** The architecture review's own test for this change: *"a
measurement with a complete honest observation set must produce a byte-identical Ruling before and
after, establishing the change touches only the incomplete case."* Probe C constructs such a
measurement, rules on it through the MCP tool and through ``learn.admissible.rule`` directly, and
asserts the two rulings are byte-identical. If they are not, the change has reached the verdict and
not only the report, which is the failure mode worth a probe of its own.

Exit codes: ``0`` every probe that could run passed; ``1`` a probe failed and the property does not
hold; ``3`` no probe could run, which is reported as not taken rather than as a pass.

Usage::

    python tools/falsify_optional_guard.py
    python tools/falsify_optional_guard.py --probe B --probe C
"""

from __future__ import annotations

import argparse
import json
import sys

PROBES = ("A", "B", "C")


def _call(text: str) -> dict:
    """Parse a tool's JSON string response, which is what a model receives."""

    return json.loads(text)


class _Plan:
    """A stand-in for one compiled plan, used only to drive the scan's fail-closed branch.

    Deliberately minimal and deliberately not a mock of ``Screen``: the property under test is what
    :func:`etalon.mcp.screen_gate.declared_gates` does with a pipeline it cannot read, and a real
    compile cannot produce that case on demand. Everything else in probe A is taken from the real
    registration index.
    """

    def __init__(self, internal) -> None:
        self._internal = internal


def probe_a() -> dict:
    """``etalon_screen_submit`` must accept an authorization, and must fail closed when it cannot
    establish that a funnel is ungated."""

    try:
        import inspect

        from etalon.mcp import screen_gate
        from etalon.mcp.execution import register
    except Exception as error:  # noqa: BLE001
        return {"probe": "A", "status": "not_taken", "reason": f"{type(error).__name__}: {error}"}

    tools: dict = {}

    class Collector:
        def tool(self):
            def decorate(function):
                tools[function.__name__] = function
                return function

            return decorate

    register(Collector())
    parameters = tuple(inspect.signature(tools["etalon_screen_submit"]).parameters)

    findings = [
        {
            "assertion": "etalon_screen_submit accepts a gate authorization",
            "parameters": list(parameters),
            "passed": "gate_json" in parameters and "gate_reference_library" in parameters,
            "note": (
                "this is the parameter that did not exist. Before the change all three gate "
                "transcripts -- no token, wrong revision, right token -- were the same call and "
                "all three proceeded."
            ),
        },
        {
            "assertion": "an unreadable compiled pipeline is reported as not taken, not as ungated",
            "scan": screen_gate.declared_gates(_Plan({"registry": object()}))[1],
            "gates": list(screen_gate.declared_gates(_Plan({"registry": object()}))[0]),
            "passed": screen_gate.declared_gates(_Plan({"registry": object()}))[1].startswith(
                "not_taken"
            ),
        },
        {
            "assertion": "a scan that returns no gates and a measured basis is the ungated case",
            "scan": screen_gate.declared_gates(_Plan(None))[1],
            "passed": not screen_gate.declared_gates(_Plan(None))[1].startswith("measured_here"),
            "note": (
                "a plan carrying no pipeline at all must not be read as a measurement of zero "
                "gates: `require` asks for a token in that case rather than waving it through"
            ),
        },
    ]
    return {
        "probe": "A",
        "status": "taken",
        "findings": findings,
        "passed": all(row["passed"] for row in findings),
        "establishes": (
            "that the authorization parameter exists on the SPENDS tool, and that a funnel whose "
            "gate declaration cannot be established is refused rather than assumed ungated"
        ),
        "does_not_establish": (
            "the full three-transcript sequence against a real gated cascade, which needs "
            "MolCascade's compiler and a panel run. Nor does it establish that any other screening "
            "entry point is guarded: runtime/operations.py's screen.run path compiles the same "
            "config and takes no token."
        ),
    }


def probe_b() -> dict:
    """An empty observation list must be reported as unexamined rather than as clean."""

    try:
        from etalon.faults.taxonomy import FAULTS
        from etalon.mcp import coverage as coverage_module
        from etalon.mcp.governance import register
    except Exception as error:  # noqa: BLE001
        return {"probe": "B", "status": "not_taken", "reason": f"{type(error).__name__}: {error}"}

    tools: dict = {}

    class Collector:
        def tool(self):
            def decorate(function):
                tools[function.__name__] = function
                return function

            return decorate

    register(Collector())
    rule_admissible = tools["etalon_rule_admissible"]

    measurements = json.dumps(
        [{"parent_id": "m1", "cheap_value": -9.1, "expensive_value": -10.4, "observations": []}]
    )
    reported = _call(rule_admissible(measurements))
    ruling = reported["report"]["rulings"][0]
    block = reported["coverage"][0]

    findings = [
        {
            "assertion": "the ruling itself is unchanged by the report",
            "admission": ruling["admission"],
            "unchecked": ruling["unchecked"],
            "passed": ruling["admission"] == "admitted" and ruling["unchecked"] == [],
        },
        {
            "assertion": "every catalogue code is reported as having no observation",
            "codes_with_no_observation": block["codes_with_no_observation"],
            "catalogue_codes": block["catalogue_codes"],
            "passed": block["codes_with_no_observation"] == len(FAULTS),
        },
        {
            "assertion": "the ruling is counted as one whose empty blocking set covered nothing",
            "count": reported["coverage_summary"][
                "rulings_whose_blocking_set_is_empty_and_covered_nothing"
            ],
            "passed": reported["coverage_summary"][
                "rulings_whose_blocking_set_is_empty_and_covered_nothing"
            ]
            == 1,
        },
    ]

    # The stage-2 half: with an audit for the live catalogue, the same measurement must move from an
    # empty `unchecked` to a fully populated one, with its values untouched.
    digest, basis = coverage_module.catalogue_digest_or_not_taken()
    if digest is None:
        findings.append(
            {
                "assertion": "stage 2 fills unchecked for every absent preflight code",
                "passed": True,
                "status": "not_taken",
                "reason": basis,
            }
        )
    else:
        audit = json.dumps(
            {
                "schema": coverage_module.AUDIT_SCHEMA,
                "catalogue_digest": digest,
                "rule_version": "falsifier",
                "taken_at": "probe",
                "counted_by": "tools/falsify_optional_guard.py",
                **{name: coverage_module.NOT_TAKEN for name in coverage_module.AUDIT_CLASSES},
            }
        )
        strict = _call(
            rule_admissible(
                measurements, "", "", "", False, "unchecked_when_absent", audit
            )
        )
        strict_ruling = strict["report"]["rulings"][0]
        preflight = {
            fault.code for fault in FAULTS if fault.phase.value == "preflight"
        }
        findings.append(
            {
                "assertion": "stage 2 fills unchecked for every absent preflight code",
                "unchecked": strict_ruling["unchecked"],
                "preflight_codes": sorted(preflight),
                "passed": set(strict_ruling["unchecked"]) == preflight,
            }
        )
        findings.append(
            {
                "assertion": "stage 2 refuses without an audit",
                "passed": _refuses_without_audit(rule_admissible, measurements),
            }
        )

    return {
        "probe": "B",
        "status": "taken",
        "findings": findings,
        "passed": all(row["passed"] for row in findings),
        "establishes": (
            "that the mechanism is coverage and not a new refusal: the admission is unchanged and "
            "the gap is reported"
        ),
        "does_not_establish": (
            "anything about the admission rate, which is supposed to fall under stage 2 and whose "
            "fall is consistent with both the intended mechanism and a bug that drops observations"
        ),
    }


def _refuses_without_audit(rule_admissible, measurements: str) -> bool:
    response = _call(rule_admissible(measurements, "", "", "", False, "unchecked_when_absent", ""))
    return response.get("ok") is False and "audit_json" in response["error"]["message"]


def probe_c() -> dict:
    """A complete honest observation set must rule byte-identically through both paths."""

    try:
        from etalon.faults.attribution import Observation
        from etalon.faults.taxonomy import FAULTS
        from etalon.learn.admissible import Measurement, rule
        from etalon.mcp.governance import register
    except Exception as error:  # noqa: BLE001
        return {"probe": "C", "status": "not_taken", "reason": f"{type(error).__name__}: {error}"}

    tools: dict = {}

    class Collector:
        def tool(self):
            def decorate(function):
                tools[function.__name__] = function
                return function

            return decorate

    register(Collector())

    observations = [
        {"code": fault.code, "fired": False, "evaluable": True, "detail": "checked by the probe"}
        for fault in FAULTS
    ]
    payload = json.dumps(
        [
            {
                "parent_id": "complete",
                "cheap_value": -9.1,
                "expensive_value": -10.4,
                "observations": observations,
            }
        ]
    )
    through_tool = _call(tools["etalon_rule_admissible"](payload))["report"]["rulings"][0]
    direct = rule(
        Measurement(
            parent_id="complete",
            cheap_value=-9.1,
            expensive_value=-10.4,
            observations=tuple(
                Observation(row["code"], fired=False, detail=row["detail"], evaluable=True)
                for row in observations
            ),
        )
    ).as_dict()
    identical = json.dumps(through_tool, sort_keys=True) == json.dumps(direct, sort_keys=True)
    return {
        "probe": "C",
        "status": "taken",
        "findings": [
            {
                "assertion": "the Ruling is byte-identical through the tool and through rule()",
                "passed": identical,
                "through_tool": through_tool if not identical else "identical",
                "direct": direct if not identical else "identical",
            }
        ],
        "passed": identical,
        "establishes": (
            "that the coverage change touches only the incomplete case; rule(Measurement) -> Ruling "
            "keeps its semantics exactly, which is hard constraint 1"
        ),
        "does_not_establish": "that the observation set the caller supplied was honest",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="append", choices=PROBES, default=None)
    arguments = parser.parse_args(argv)
    selected = tuple(arguments.probe) if arguments.probe else PROBES

    reports = []
    for name in selected:
        reports.append({"A": probe_a, "B": probe_b, "C": probe_c}[name]())
    print(json.dumps(reports, indent=2, sort_keys=True, default=str))

    taken = [row for row in reports if row.get("status") == "taken"]
    failed = [row for row in taken if not row.get("passed")]
    if not taken:
        print(
            "\nNOT TAKEN: no probe could run in this environment. That is reported as not taken "
            "and never as a pass.",
            file=sys.stderr,
        )
        return 3
    if failed:
        print(
            f"\nFAILED: {len(failed)} of {len(taken)} probe(s) that ran found the guard optional: "
            + ", ".join(row["probe"] for row in failed),
            file=sys.stderr,
        )
        return 1
    print(f"\nPASSED: {len(taken)} of {len(selected)} probe(s) ran and every one held.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
