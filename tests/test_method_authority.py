"""``method.run`` may not dispatch a declaration nobody prepared.

ADR 0006's second live instance, closed. The review's verification standard is not a score -- *"not
'fewer bad screens ran' ... the mechanism evidence is reachability, demonstrated by construction:
drive the MCP surface the way a model would, take the refusal from the guard tool, then attempt the
spending tool and assert it refuses"* -- so the central test here is a transcript, not an assertion
about an internal.

Three groups:

* :func:`test_reachability_*` drive the real registered tools. Before this change the same sequence
  completed: ``operations.preflight("method.run", ...)`` returned ``{"inputs": ...}`` and there was
  no authorization object anywhere in the tree to refuse with. That half is recorded by running
  these against a HEAD checkout, which is why each one states what it establishes.
* :func:`test_refusal_*` pin the boundary classification. ``NotAuthorizedMethod`` subclasses
  ``PermissionError`` -> ``OSError``, so without the ``_refusal`` intercept a refusal reaches the
  model as *"it looks transient ... calling again is reasonable once"*. It must also be matched
  **before** ``NotAuthorized``, or the model is told to calibrate a screening panel.
* :func:`test_extraction_*` establish that factoring the shared base out of ``grant.py`` and
  ``gate.py`` changed no byte either of them signs.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from etalon.authority.method import (
    NotAuthorizedMethod,
    authorize_method,
    method_request_subject,
    require_method,
    stage,
)
from etalon.runtime import operations


class Collector:
    """The registration shim ``tools/falsify_optional_guard.py`` uses, so the tools under test are
    the registered ones and not a hand-built copy of them."""

    def __init__(self) -> None:
        self.tools: dict = {}

    def tool(self):
        def decorate(function):
            self.tools[function.__name__] = function
            return function

        return decorate


def registered() -> dict:
    from etalon.mcp.runtime import register

    collector = Collector()
    register(collector)
    return collector.tools


def call(tool, *args, **kwargs) -> dict:
    """Invoke a registered tool the way the server does and parse what a model receives."""

    result = tool(*args, **kwargs)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return json.loads(result)


def declaration(tmp_path, *, inputs=None, name="method.py", method_id="fixture-sum-v1"):
    script = tmp_path / name
    script.write_text(
        "import argparse,json\n"
        "from pathlib import Path\n"
        "p=argparse.ArgumentParser();p.add_argument('--request');p.add_argument('--result')\n"
        "a=p.parse_args()\n"
        "Path(a.result).write_text(json.dumps({'schema':'etalon-method-result/1',"
        "'summary':'fixture, not scientific efficacy','outputs':{}}))\n",
        encoding="utf-8",
    )
    return {
        "method_id": method_id,
        "command": [sys.executable, str(script)],
        "files": [str(script)],
        "inputs": inputs or {},
    }


def action_request(arguments, request_id="probe-method"):
    return {
        "schema": "etalon-action/1",
        "request_id": request_id,
        "operation": "method.run",
        "arguments": arguments,
        "limits": {"wall_second": 40},
    }


# --------------------------------------------------------------------------------------------
# Reachability, demonstrated by construction.
# --------------------------------------------------------------------------------------------


def test_reachability_the_guard_tool_mints_and_the_spending_tool_rules_on_it(tmp_path):
    """The transcript pair, as the review specifies it.

    Establishes: a model that drives ``etalon_action_prepare`` receives an authorization it did not
    construct, and ``etalon_action_submit`` refuses a declaration that authorization was not minted
    on. Before the change ``etalon_action_prepare`` returned no authorization of any kind and the
    substituted declaration reached dispatch unremarked.

    Does not establish: that the argv anybody authorised is safe to run. The token binds identity,
    not intent, and ``MethodAuthorization`` says so in its own docstring.
    """

    tools = registered()
    arguments = declaration(tmp_path)

    prepared = call(tools["etalon_action_prepare"], action_request(arguments))
    assert prepared["ok"] is True
    token = prepared["request"]["arguments"]["authorization"]
    assert token["signature"] and token["method_id"] == "fixture-sum-v1"
    assert prepared["authorization"]["nodes_without_one"] == []

    # The model now submits a different program carrying the token it was given. This is the
    # realistic failure -- a resumed or re-planned run, or a catalogue entry whose command[0] was
    # rewritten -- not an attack.
    substituted = dict(arguments, command=[sys.executable, "-c", "import os; os.system('id')"])
    substituted["authorization"] = token
    refused = call(
        tools["etalon_action_submit"],
        action_request(substituted),
        str(tmp_path / "runtime"),
        prepared["prepared"]["plan_id"],
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] == "NotAuthorizedMethod"
    assert refused["error"]["retryable"] is False
    assert "etalon_action_prepare" in refused["error"]["hint"]
    assert "WRONG_SUBJECT" in refused["error"]["message"]


def test_reachability_the_plan_tool_mints_for_every_method_node(tmp_path):
    """``etalon_workflow_plan`` is the workflow half of the same transcript.

    Establishes: the returned spec carries a token per ``method.run`` node and plans to the
    ``plan_id`` returned beside it, so a host that submits what it was handed is authorised without
    constructing anything.
    """

    from etalon.runtime.service import plan

    tools = registered()
    node = {"id": "first", "operation": "method.run", "arguments": declaration(tmp_path),
            "resources": {"wall_second": 40}}
    spec = {"schema": "etalon-workflow/1", "objective": "probe", "nodes": [node],
            "limits": {"wall_second": 180}, "max_seconds": 120}

    planned = call(tools["etalon_workflow_plan"], spec)
    assert planned["ok"] is True
    assert planned["method_authorization"]["first"]["state"] == "minted"
    assert planned["spec"]["nodes"][0]["arguments"]["authorization"]["signature"]
    # The plan_id the host is told to submit is the plan_id the authorized spec plans to.
    assert plan(planned["spec"])["plan_id"] == planned["plan_id"]


def test_reachability_dispatch_refuses_a_token_minted_on_another_declaration(tmp_path):
    """Every field of the subject is load-bearing, checked one substitution at a time."""

    arguments = declaration(tmp_path)
    token = authorize_method(arguments).as_dict()
    script = tmp_path / "method.py"

    substitutions = {
        "argv": dict(arguments, command=[sys.executable, "-c", "pass"]),
        "inputs": dict(arguments, inputs={"factor": 2}),
        "outputs": dict(arguments, outputs={"table": "out.csv"}),
        "method_id": dict(arguments, method_id="something-else"),
    }
    for label, substituted in substitutions.items():
        with pytest.raises(NotAuthorizedMethod) as refusal:
            operations.preflight("method.run", dict(substituted, authorization=token),
                                 {"wall_second": 40})
        assert "WRONG_SUBJECT" in str(refusal.value), label

    # The file's *contents*, not its path: an edit between the plan and the dispatch invalidates
    # the token, which a digest over paths would have missed.
    script.write_text("print('a different program entirely')", encoding="utf-8")
    with pytest.raises(NotAuthorizedMethod):
        operations.preflight("method.run", dict(arguments, authorization=token), {"wall_second": 40})


def test_reachability_stage_two_refuses_a_dispatch_with_no_token(tmp_path, monkeypatch):
    """Stage 2, which is implemented and not the default.

    Establishes: the required stage exists and refuses, and its message names the tool that mints
    the token and what it is minted on. A refusal a host cannot act on is a wall.
    """

    arguments = declaration(tmp_path)
    monkeypatch.setenv("ETALON_METHOD_AUTHORITY", "required")
    assert stage() == "required"
    with pytest.raises(NotAuthorizedMethod) as refusal:
        operations.preflight("method.run", arguments, {"wall_second": 40})
    message = str(refusal.value)
    assert "etalon_action_prepare" in message and "etalon_workflow_plan" in message
    assert "method_id, the argv" in message

    # The same declaration carrying its token passes under the same stage.
    authorized = dict(arguments, authorization=authorize_method(arguments).as_dict())
    assert operations.preflight("method.run", authorized, {"wall_second": 40})[
        "method_authorization"
    ]["state"] == "authorized"


def test_stage_one_is_the_default_and_records_the_gap_without_minting_one(tmp_path, monkeypatch):
    """The rollout mitigation, stated as what it is.

    A request with no token is not refused and is also not quietly authorised: nothing is minted at
    dispatch on the caller's behalf, because an authorization object in a receipt that nothing
    authorised is worse than the gap it hides.
    """

    monkeypatch.delenv("ETALON_METHOD_AUTHORITY", raising=False)
    assert stage() == "optional"
    record = operations.preflight("method.run", declaration(tmp_path), {"wall_second": 40})[
        "method_authorization"
    ]
    assert record["state"] == "absent"
    assert "authorization" not in record
    assert record["established"].startswith("nothing")
    assert record["would_refuse_under"] == "ETALON_METHOD_AUTHORITY=required"


def test_the_stage_is_read_at_dispatch_and_never_backfilled(tmp_path, monkeypatch):
    """Hard constraint 4: authorization is decided at dispatch, not at import and not afterwards."""

    arguments = declaration(tmp_path)
    monkeypatch.delenv("ETALON_METHOD_AUTHORITY", raising=False)
    assert require_method(arguments)["state"] == "absent"
    monkeypatch.setenv("ETALON_METHOD_AUTHORITY", "required")
    with pytest.raises(NotAuthorizedMethod):
        require_method(arguments)
    monkeypatch.setenv("ETALON_METHOD_AUTHORITY", "nonsense")
    with pytest.raises(ValueError):
        require_method(arguments)


def test_a_deferred_declaration_is_reported_not_taken_rather_than_minted(tmp_path):
    """Hard constraint 7: a token that could never cover its dispatch is not issued.

    A node whose inputs are another node's output has no final declaration at plan time. Minting
    there would guarantee a refusal at dispatch for the planner's reason, not the host's.
    """

    from etalon.mcp import method_authority

    arguments = dict(declaration(tmp_path), inputs={"value": {"$ref": "first.outputs"}})
    _, record = method_authority.authorize_arguments(arguments)
    assert record["state"] == "not_taken" and "$ref" in record["reason"]


def test_an_unpinnable_executable_is_recorded_rather_than_refused(tmp_path):
    """``gate.py``'s rule, applied here: "we did not look" must not read as "it is the same"."""

    from etalon.authority.method import EXECUTABLE_NOT_PINNED

    arguments = dict(declaration(tmp_path), command=["/usr/bin/does-not-exist-here", "--go"])
    _, unchecked = method_request_subject(arguments)
    assert EXECUTABLE_NOT_PINNED in unchecked
    token = authorize_method(arguments)
    assert token.unchecked == (EXECUTABLE_NOT_PINNED,)
    # It still covers its own declaration, and still refuses a different argv.
    assert token.covers(arguments)
    assert not token.covers(dict(arguments, command=["/usr/bin/does-not-exist-here", "--stop"]))


def test_an_undigestible_declared_file_refuses_rather_than_minting_an_empty_subject(tmp_path):
    arguments = dict(declaration(tmp_path), files=[str(tmp_path / "absent.py")])
    with pytest.raises(NotAuthorizedMethod) as refusal:
        authorize_method(arguments)
    assert "cannot be read" in str(refusal.value)


# --------------------------------------------------------------------------------------------
# The boundary classification.
# --------------------------------------------------------------------------------------------


def test_refusal_is_intercepted_as_permanent_and_not_as_a_transient_oserror():
    """The hazard this repository has already been bitten by, pinned.

    ``NotAuthorizedMethod`` -> ``NotAuthorized`` -> ``PermissionError`` -> ``OSError``, and
    ``OSError`` is ``_TRANSIENT``. Without the intercept the one refusal that stops an unprepared
    program from running tells the model that calling again is reasonable once.
    """

    from etalon.mcp._common import _TRANSIENT, _refusal

    assert isinstance(NotAuthorizedMethod("x"), _TRANSIENT)
    hint = _refusal(NotAuthorizedMethod("x"))
    assert hint is not None
    assert "not a transient failure" in hint


def test_refusal_names_the_method_route_and_not_the_gate_route():
    """Matched before ``NotAuthorized``, or the remedy is about a screening panel.

    This is the ``threshold_evidence`` mistake restated: a refusal whose instructions cannot fix it
    is a wall with directions painted on.
    """

    from etalon.mcp._common import _refusal

    hint = _refusal(NotAuthorizedMethod("x"))
    assert "etalon_action_prepare" in hint and "etalon_workflow_plan" in hint
    assert "etalon_authorize_gates" not in hint

    from etalon.authority.grant import NotAuthorized

    gate_hint = _refusal(NotAuthorized("x"))
    assert "etalon_authorize_gates" in gate_hint


# --------------------------------------------------------------------------------------------
# The extraction.
# --------------------------------------------------------------------------------------------


def test_extraction_does_not_change_the_signed_bytes(monkeypatch):
    """The shared base is a factoring, not a new wire format.

    The two constants are the signatures the same fields produced at HEAD under the same key,
    recorded by running the identical construction against a ``git archive HEAD`` checkout. If a
    future edit to ``subject.py`` changes how a body is serialised, every token minted before it
    stops verifying -- silently, because an unverifiable token and an expired one take the same
    branch -- and this is the test that says so first.
    """

    monkeypatch.setenv("ETALON_AUTHORITY_KEY", "fixed")
    from etalon.authority.gate import GateAuthorization
    from etalon.authority.grant import _sign
    from etalon.authority.subject import sign

    spend = _sign(
        parent_id="m1", record_sha256="a" * 64, receptor_sha256="",
        issued_at="2026-01-01T00:00:00+00:00", expires_at="2030-01-01T00:00:00+00:00",
        proceeded_under_waiver=(), unchecked=("X",),
    )
    assert spend.signature == "f0758ff011b230daebbe7fd21b47427423ef64521b263f2c819a64fa3b9da0db"
    assert spend.as_dict()["unchecked"] == ["X"]  # lists, as a reader of the record sees them
    assert spend.valid()

    fields = dict(
        revision_id="r", calibration_sha256="c", infrastructure_sha256="", panel_size=8,
        actives=2, recall=1.0, rankable_engines=(), unchecked=("Y",),
        issued_at="2026-01-01T00:00:00+00:00", expires_at="2030-01-01T00:00:00+00:00",
    )
    assert sign(fields) == "31393a06ef985c5470eafc46786969ade6da4eb3f9c16bfc94ac8c5b773fde07"
    gate = GateAuthorization(**fields, signature=sign(fields))
    assert gate.valid() and gate.as_dict()["rankable_engines"] == []


def test_the_three_refusals_are_one_skeleton_with_three_subjects():
    """What the base actually shares, asserted rather than claimed.

    Each instance keeps its own ``covers`` -- a row's id plus content digest, a compiled revision
    id, a declaration's six digests -- and that is the difference the base deliberately does not
    absorb.
    """

    from etalon.authority import gate, grant, method
    from etalon.authority.subject import Signed

    assert all(issubclass(cls, Signed) for cls in
               (grant.SpendAuthorization, gate.GateAuthorization, method.MethodAuthorization))
    for cls in (grant.SpendAuthorization, gate.GateAuthorization, method.MethodAuthorization):
        assert "covers" in cls.__dict__, f"{cls.__name__} must define its own subject comparison"
        assert "_body" not in cls.__dict__ and "valid" not in cls.__dict__


# --------------------------------------------------------------------------------------------
# The countable.
# --------------------------------------------------------------------------------------------


def test_the_spends_census_is_taken_from_the_registration_index():
    """The review's countable: unguarded SPENDS tools over SPENDS tools.

    Counted by the probe rather than by hand, and asserted as a direction plus the two tools this
    change moved -- not as a literal, because a literal here is the stale-count failure the same
    probe exists to prevent.
    """

    import importlib.util
    from pathlib import Path

    probe = Path(__file__).resolve().parents[1] / "tools" / "count_unguarded_spends.py"
    spec = importlib.util.spec_from_file_location("count_unguarded_spends", probe)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = module.census()
    by_tool = {row["tool"]: row for row in report["detail"]}
    for name in ("etalon_action_submit", "etalon_workflow_submit", "etalon_workflow_advance"):
        assert by_tool[name]["spend_token_parameters"] == ["authorization_json"], name
    assert report["spends_tools_accepting_no_authorization_object"] < report["spends_tools"]
    # The class is not closed: these two remain unauthorized and this test says so out loud.
    for name in ("etalon_active_submit", "etalon_method_call"):
        assert by_tool[name]["accepts_an_authorization_object"] is False
