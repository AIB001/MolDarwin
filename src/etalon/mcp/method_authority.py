"""Minting the method authorization at the plan step, on the surface a model actually drives.

``mcp/screen_gate.py`` is the sibling of this module and the precedent for its shape: the guard
lives beside the tool that spends, the authority package owns the ruling, and the module's job is
to put the token where the host will find it.

The difference is which way the rollout runs. ``etalon_screen_submit`` could be made to refuse
immediately, because the condition that makes a gate token necessary -- a compiled funnel that
declares a threshold -- is cheap to detect and a cascade without one is not asked for a token. There
is no equivalent condition for ``method.run``: every ``method.run`` launches host-authored argv, so
a guard conditioned on "this one looks dangerous" would be a guess. The rollout is therefore the
other one the review names -- *"mint the token inside the plan/prepare step so the host receives it
rather than constructing it, which is how ``authorize()`` already works"* -- and the refusal stage is
selected by ``ETALON_METHOD_AUTHORITY``. See :mod:`etalon.authority.method` for which stage is on by
default and why.

**What is deliberately not minted.** A node whose arguments still carry a ``{"$ref": ...}`` is a
declaration that is not final: its inputs are an earlier node's output and nobody can digest them
yet. Minting there would bind a token to a declaration that is guaranteed to differ from the one
dispatched, so every such node would refuse at dispatch for a reason that is the planner's doing and
not the host's. Those nodes are reported as not taken, with the reason, rather than given a token
that cannot hold -- hard constraint 7.
"""

from __future__ import annotations

import json
from typing import Any

#: The tool argument's name, which is also what ``tools/count_unguarded_spends.py`` recognises as an
#: authorization object in a SPENDS tool's signature.
PARAMETER = "authorization_json"

#: Where the token rides inside a node. Not a separate node field, because the node definition is
#: what ``runtime/operations.preflight`` receives at dispatch and ``arguments`` is the only part of
#: it that reaches there.
FIELD = "authorization"


def is_method_node(node: dict[str, Any]) -> bool:
    return node.get("operation") == "method.run"


def _deferred(arguments: dict[str, Any]) -> bool:
    from etalon.runtime.schema import references

    return bool(references(arguments))


def authorize_arguments(arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mint over one ``method.run`` argument object and return it carrying the token.

    Returns the (possibly unchanged) arguments and a record for the response. The arguments are
    returned rather than mutated so that a caller holding the host's original object still has it.
    """

    from etalon.authority.method import authorize_method, token_from_mapping

    if _deferred(arguments):
        return arguments, {
            "state": "not_taken",
            "reason": (
                "this node's arguments still contain a {$ref: ...} to another node's output, so "
                "the declaration a token would be minted on does not exist yet. At dispatch the "
                "resolved declaration is what runs, and a token minted on the unresolved one could "
                "never cover it."
            ),
        }
    existing = token_from_mapping(arguments.get(FIELD))
    if existing is not None:
        return arguments, {"state": "already_supplied", "authorization": existing.as_dict()}
    token = authorize_method(arguments)
    return {**arguments, FIELD: token.as_dict()}, {
        "state": "minted",
        "authorization": token.as_dict(),
        "unchecked": list(token.unchecked),
    }


def authorize_request(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mint for a single ``etalon-action/1`` request, or return it unchanged."""

    if request.get("operation") != "method.run":
        return request, {"state": "not_applicable", "operation": request.get("operation")}
    arguments, record = authorize_arguments(request["arguments"])
    if arguments is request["arguments"]:
        return request, record
    return {**request, "arguments": arguments}, record


def authorize_spec(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Mint for every ``method.run`` node of a workflow spec.

    Also rewrites ``action_request`` when the spec carries one: ``runtime/schema.workflow`` refuses
    a spec whose action metadata disagrees with its single executable node, so the two have to move
    together or neither moves.
    """

    records: dict[str, dict[str, Any]] = {}
    nodes = []
    changed = False
    for node in spec["nodes"]:
        if not is_method_node(node):
            nodes.append(node)
            continue
        arguments, record = authorize_arguments(node["arguments"])
        records[node["id"]] = record
        if arguments is not node["arguments"]:
            changed = True
            nodes.append({**node, "arguments": arguments})
        else:
            nodes.append(node)
    if not changed:
        return spec, records
    updated = {**spec, "nodes": nodes}
    if "action_request" in updated:
        action = dict(updated["action_request"])
        action["arguments"] = nodes[0]["arguments"]
        updated["action_request"] = action
    return updated, records


def tokens_from_json(authorization_json: str) -> dict[str, Any]:
    """Parse the tool argument into ``{node_id: token}``.

    Accepts the single token object the single-action tools return (bound to the one node a prepared
    action has, ``"action"``) or an explicit ``{node_id: token}`` map for a workflow.
    """

    if not authorization_json or not authorization_json.strip():
        return {}
    payload = json.loads(authorization_json)
    if not isinstance(payload, dict):
        raise ValueError(
            f"{PARAMETER} must be the authorization object the plan step returned, or a map of "
            "node id to that object, passed verbatim"
        )
    if "signature" in payload:
        return {"action": payload}
    return {str(key): value for key, value in payload.items()}


def merge(spec_or_request: dict[str, Any], tokens: dict[str, Any], *, node_id: str = "action") -> dict[str, Any]:
    """Put host-supplied tokens into the declarations they belong to.

    A token supplied for a node that already carries a different one is refused here rather than
    silently preferred, because which of the two the host meant is not a question this layer can
    answer and guessing it would decide an authorization by coin toss.
    """

    from etalon.authority.method import token_from_mapping

    if not tokens:
        return spec_or_request

    def place(arguments: dict[str, Any], key: str) -> dict[str, Any]:
        supplied = tokens.get(key)
        if supplied is None:
            return arguments
        present = token_from_mapping(arguments.get(FIELD))
        incoming = token_from_mapping(supplied)
        if present is not None and incoming is not None and present.as_dict() != incoming.as_dict():
            raise ValueError(
                f"node {key!r} already carries a method authorization and {PARAMETER} supplies a "
                "different one. Submit the request the plan step returned, or omit "
                f"{PARAMETER} -- an authorization chosen between two candidates is not one."
            )
        return {**arguments, FIELD: incoming.as_dict()} if incoming is not None else arguments

    if "nodes" in spec_or_request:
        nodes = [
            {**node, "arguments": place(node["arguments"], node["id"])} if is_method_node(node) else node
            for node in spec_or_request["nodes"]
        ]
        updated = {**spec_or_request, "nodes": nodes}
        if "action_request" in updated and is_method_node(nodes[0]):
            updated["action_request"] = {**updated["action_request"], "arguments": nodes[0]["arguments"]}
        return updated
    if spec_or_request.get("operation") != "method.run":
        return spec_or_request
    return {**spec_or_request, "arguments": place(spec_or_request["arguments"], node_id)}


def state(spec_or_request: dict[str, Any], *, node_id: str = "action") -> dict[str, Any]:
    """What a response should say about the authorization of every ``method.run`` it is about.

    Reports rather than rules: the ruling is ``runtime/operations.preflight``'s, at dispatch. A
    report here that disagreed with the dispatch would be the almost-guard ADR 0006 is about.
    """

    from etalon.authority.method import MINTING_ROUTE, stage, token_from_mapping

    declarations: list[tuple[str, dict[str, Any]]] = []
    if "nodes" in spec_or_request:
        declarations = [(n["id"], n["arguments"]) for n in spec_or_request["nodes"] if is_method_node(n)]
    elif spec_or_request.get("operation") == "method.run":
        declarations = [(node_id, spec_or_request["arguments"])]
    if not declarations:
        return {"method_run_nodes": 0, "ruled_at": "etalon.runtime.operations.preflight, at dispatch"}

    carried = {}
    for key, arguments in declarations:
        token = token_from_mapping(arguments.get(FIELD))
        carried[key] = (
            {"authorization": token.as_dict(), "unchecked": list(token.unchecked)}
            if token is not None
            else {"authorization": None, "deferred": _deferred(arguments)}
        )
    without = sorted(key for key, row in carried.items() if row["authorization"] is None)
    return {
        "method_run_nodes": len(declarations),
        "nodes_carrying_an_authorization": len(declarations) - len(without),
        "nodes_without_one": without,
        "stage": stage(),
        "ruled_at": "etalon.runtime.operations.preflight, at dispatch",
        "establishes": (
            "that the declaration dispatched is the declaration the token was minted on -- the "
            "method id, the argv, the content of every declared file, the inputs and the outputs "
            "map. Not that the program is safe and not that its result is admissible."
        ),
        **({"remedy": MINTING_ROUTE} if without else {}),
    }


__all__ = [
    "FIELD",
    "PARAMETER",
    "authorize_arguments",
    "authorize_request",
    "authorize_spec",
    "is_method_node",
    "merge",
    "state",
    "tokens_from_json",
]
