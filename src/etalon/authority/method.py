"""Permission to run one declared method request, bound to the declaration that was prepared.

``grant.py`` guards a GPU-hour spent on a molecule nobody ruled on. ``gate.py`` guards a threshold
applied to a million molecules that no panel tested. Both describe a *scientific* irreversibility.
This module guards the third thing on ETALON's spending surface, and it is not scientific at all:

    ``method.run`` executes host-authored argv.

Of the registered workflow operations only ``active.evaluate`` could reach
:func:`~etalon.authority.grant.require` (``runtime/operations.py``). For ``method.run`` the whole
preflight was::

    if operation == "method.run" and resources.get("wall_second", 0) <= 0:
        raise ValueError("method.run requires an explicit wall_second allowance")

-- a declared budget and nothing else -- and ``verify`` only re-read the native receipt the same run
had just written. So the one operation that launches an arbitrary detached child process was a
SPENDS path with a budget declaration and no gate. ``docs/thin-harness/ARCHITECTURE_REVIEW.md`` §P3
names it as the second of ADR 0006's three live instances.

**Why not a handoff-style token.** ``method.run`` has no handoff row to bind one to, and no
preflight verdict to mint from: there is no ``check_record`` for an argv list, and inventing a
scientific verdict for one would be exactly the fabricated-measurement failure the rest of this
repository is built against. What there *is* is a declaration -- the review's phrase is *"a declared
method request digest"* -- and what a token over it establishes is narrow and stateable:

    **the method request that was prepared is the method request that is dispatched.**

That is all it establishes. It is the same ``WRONG_SUBJECT`` argument ``grant.py`` makes about a row
and ``gate.py`` makes about a compiled revision, applied to a program. It does **not** establish
that the program is safe, that its output is admissible, or that anybody read the argv. Those are
different questions and this module answers none of them; ``scientific_admission`` stays
``not_inferred`` exactly as before.

**What is in the subject, and one addition to the review's list.** The review says *"mint on the
declared ``(method_id, files digests, inputs digest, outputs map)``"*. This mints on those four and
on **the argv itself**, because the sentence the whole proposal turns on is *"the operation that
runs arbitrary host-authored argv"*: a subject that omitted ``command`` would hand out a token for
``method_id="fixture-sum-v1"`` that also covers any other program run with the same inputs and
outputs. ``files`` are digested by **content**, not by path, so a source file edited between the
plan and the dispatch invalidates the token -- the same reason ``SpendAuthorization`` digests the
row rather than trusting ``parent_id``. A sixth field, ``request_sha256``, covers the declaration
whole, so a field added to the ``method.run`` contract later is inside the subject on the day it is
added rather than on the day somebody remembers this module.

**Rollout.** Stage 1, which is what ``authority/gate.py``'s own history suggests and what
``etalon_screen_submit`` did with ``gate_json``: the token is minted by the plan/prepare step so the
host receives it rather than constructing it, and at dispatch a token that is **present** is fully
enforced -- expired, tampered, or minted for a different request are all refusals. A request with
**no** token is not refused; it is recorded as ``absent`` with the stage-2 message attached, because
refusing outright breaks every existing ``method.run`` caller including the saved-method path in
``research/``. Stage 2 -- refuse when absent -- is implemented and selected by
``ETALON_METHOD_AUTHORITY=required``; see :func:`stage`.

A missing token is never minted on the caller's behalf at dispatch. Minting at the point of spending
is a guard on the path nobody takes with extra steps: it would put an authorization object in the
receipt that nothing authorised, which is worse than the gap it papers over. The preflight receipt
says ``absent`` and says what would have minted one.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from etalon.authority.subject import (
    NotAuthorized,
    Signed,
    digest_of,
    require_signed,
    sign,
)

#: How long a method authorization is good for, in hours.
#:
#: Evidence: ``convention``. It is not measured and is not presented as measured. The argument is
#: the one :data:`~etalon.authority.grant.DEFAULT_LIFETIME_HOURS` makes, and the figure is the same
#: for the same reason: a submission follows its plan within minutes in any workflow that is
#: working, so a token still valid tomorrow is one that outlived the declaration it describes. What
#: the clock is *not* doing here is catching drift -- a changed source file, a changed argv, a
#: changed inputs object are each caught by digest the moment they change. The clock catches the
#: resumed run that picked up a plan from last week, which is the failure mode long-horizon agent
#: runs actually produce.
DEFAULT_METHOD_LIFETIME_HOURS = 24.0

#: Environment variable selecting the rollout stage. See :func:`stage`.
STAGE_VARIABLE = "ETALON_METHOD_AUTHORITY"

#: The subject could not be established because the program that will actually run was not
#: digestible: ``command[0]`` is not a readable file on this host. The token still covers the argv
#: string, so substituting a *different* command is caught; what is not established is that the
#: bytes at that path are the bytes that were there when the request was prepared.
EXECUTABLE_NOT_PINNED = "EXECUTABLE_NOT_PINNED"

#: One or more declared ``input_files`` could not be digested, so a change to their contents between
#: the plan and the dispatch is not caught by this token. ``runtime/operations.input_hashes``
#: separately refuses a missing ``input_files`` entry at preflight; this code exists for the mint
#: that runs before preflight does.
INPUT_FILES_NOT_PINNED = "INPUT_FILES_NOT_PINNED"


class NotAuthorizedMethod(NotAuthorized):
    """Raised when ``method.run`` was dispatched without, or past, an authorization for it.

    A subclass of :class:`~etalon.authority.subject.NotAuthorized` so that every existing
    ``except NotAuthorized`` keeps catching it, and so the MCP boundary's non-retryable
    classification applies without a change. The boundary's *message* is a different matter:
    ``mcp/_common.py``'s ``_refusal`` has to match this type **before** the gate branch, or a method
    refusal reaches the model with the gate remedy -- calibrate a panel, call
    ``etalon_authorize_gates`` -- which names a route that cannot fix it. That is the
    ``threshold_evidence`` mistake: a refusal a host cannot act on is a wall.
    """


def stage() -> str:
    """``"optional"`` (the default) or ``"required"``, read from the environment at each dispatch.

    Read per call rather than cached at import so the stage is a property of the dispatch and not of
    whenever the worker happened to start -- hard constraint 4: authorization is decided at dispatch
    and never added afterwards.
    """

    value = os.environ.get(STAGE_VARIABLE, "").strip().lower()
    if value in {"required", "stage2", "2"}:
        return "required"
    if value in {"", "optional", "stage1", "1"}:
        return "optional"
    raise ValueError(
        f"{STAGE_VARIABLE} must be 'optional' (the default) or 'required'; got {value!r}. "
        "An unreadable setting is not treated as either stage: a guard whose stage nobody can "
        "state is a guard nobody can rely on."
    )


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declaration(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """The method request without its own authorization, which cannot be part of its own subject."""

    return {key: value for key, value in parameters.items() if key != "authorization"}


def method_request_subject(parameters: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """The six digests a token is minted on, and what could not be established.

    Raises:
        NotAuthorizedMethod: When a declared source or model file cannot be read. That is not a
            scientific refusal; it is the subject failing to exist. A token minted over files
            nobody could digest would assert a binding it does not have, and ``gate.py``'s rule
            applies -- "we did not look" must not read as "it is the same".
    """

    declaration = _declaration(parameters)
    method_id = str(declaration.get("method_id", ""))
    command = list(declaration.get("command", ()))
    unchecked: list[str] = []

    contents: dict[str, str] = {}
    for name in declaration.get("files", ()):
        path = Path(str(name))
        try:
            contents[str(path)] = _file_digest(path)
        except OSError as error:
            raise NotAuthorizedMethod(
                f"this method request declares a source or model file that cannot be read "
                f"({path}: {type(error).__name__}), so there is nothing to bind an authorization "
                "to. `files` is the declaration of what the method *is*; fix the path or remove "
                "the entry, then prepare the request again."
            ) from error

    if command:
        executable = Path(str(command[0]))
        try:
            executable_sha = _file_digest(executable)
        except OSError:
            executable_sha = ""
            unchecked.append(EXECUTABLE_NOT_PINNED)
    else:
        executable_sha = ""
        unchecked.append(EXECUTABLE_NOT_PINNED)

    dependencies: dict[str, str] = {}
    for logical, name in dict(declaration.get("input_files", {})).items():
        path = Path(str(name))
        try:
            dependencies[str(logical)] = _file_digest(path)
        except OSError:
            if INPUT_FILES_NOT_PINNED not in unchecked:
                unchecked.append(INPUT_FILES_NOT_PINNED)

    subject = {
        "method_id": method_id,
        "command_sha256": digest_of(command),
        "executable_sha256": executable_sha,
        "files_sha256": digest_of(contents),
        "input_files_sha256": digest_of(dependencies),
        "inputs_sha256": digest_of(declaration.get("inputs", {})),
        "outputs_sha256": digest_of(declaration.get("outputs", {})),
        "request_sha256": digest_of(declaration),
    }
    return subject, tuple(unchecked)


@dataclass(frozen=True, slots=True)
class MethodAuthorization(Signed):
    """Permission to dispatch one declared method request.

    Constructed only by :func:`authorize_method`. Every field is in the signature, so editing one
    invalidates the token rather than producing a token for different circumstances.
    """

    #: The declared method identifier, carried in the clear so a reader of a receipt can see which
    #: method a token is about without recomputing a digest.
    method_id: str
    #: Digest of the argv list. The review's four-field subject did not include this and it is the
    #: addition this module argues for in its own docstring.
    command_sha256: str
    #: Digest of ``command[0]``'s bytes, or empty -- in which case :attr:`unchecked` says so.
    executable_sha256: str
    #: Digest of ``{declared path: content digest}`` over ``files``. Content, not paths.
    files_sha256: str
    #: Digest of ``{logical name: content digest}`` over ``input_files``.
    input_files_sha256: str
    inputs_sha256: str
    outputs_sha256: str
    #: Digest of the whole declaration minus the authorization, so a field added to the contract
    #: later is inside the subject without an edit here.
    request_sha256: str
    #: What this token does not establish. A token over an unevaluated check authorises a dispatch;
    #: it does not assert the check passed.
    unchecked: tuple[str, ...]
    issued_at: str
    expires_at: str
    signature: str

    def _signed_fields(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "command_sha256": self.command_sha256,
            "executable_sha256": self.executable_sha256,
            "files_sha256": self.files_sha256,
            "input_files_sha256": self.input_files_sha256,
            "inputs_sha256": self.inputs_sha256,
            "outputs_sha256": self.outputs_sha256,
            "request_sha256": self.request_sha256,
            "unchecked": self.unchecked,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def covers(self, parameters: Mapping[str, Any]) -> bool:
        """Whether this token permits dispatching *this* declaration, not merely one by this name.

        ``method_id`` matching is not evidence: it is a host-chosen string and
        ``saved_methods.resolve_saved_method`` rewrites ``command[0]``, ``inputs`` and
        ``input_files`` of a catalogue entry while keeping the id. The digest comparison is the
        point, and ``executable_sha256`` is compared only when the token recorded one -- a token
        that says ``EXECUTABLE_NOT_PINNED`` must not be refused for the gap it already declares.
        """

        subject, _ = method_request_subject(parameters)
        if self.executable_sha256 and subject["executable_sha256"] != self.executable_sha256:
            return False
        return all(
            subject[field] == getattr(self, field)
            for field in (
                "method_id",
                "command_sha256",
                "files_sha256",
                "input_files_sha256",
                "inputs_sha256",
                "outputs_sha256",
                "request_sha256",
            )
        )


def authorize_method(
    parameters: Mapping[str, Any],
    *,
    lifetime_hours: float = DEFAULT_METHOD_LIFETIME_HOURS,
    now: datetime | None = None,
) -> MethodAuthorization:
    """Mint a token for one declared method request.

    This is the only constructor of :class:`MethodAuthorization` that signs, and it takes no verdict
    from the caller -- it computes the subject itself, for the reason
    :func:`~etalon.authority.grant.authorize` gives: a function that accepted "this one is fine" as
    an argument would be a guard on the path nobody takes with extra steps.

    Called from the plan/prepare step (``etalon_action_prepare``, ``etalon_workflow_plan``) so the
    host receives a token rather than constructing one, which is how ``authorize()`` already works
    and is the mitigation the review names for the rollout risk.
    """

    if lifetime_hours <= 0:
        raise ValueError("a method authorization needs a positive lifetime")
    subject, unchecked = method_request_subject(parameters)
    issued = now or datetime.now(UTC)
    fields = {
        **subject,
        "unchecked": unchecked,
        "issued_at": issued.isoformat(timespec="seconds"),
        "expires_at": (issued + timedelta(hours=float(lifetime_hours))).isoformat(
            timespec="seconds"
        ),
    }
    return MethodAuthorization(**fields, signature=sign(fields))


def token_from_mapping(payload: Any) -> MethodAuthorization | None:
    """Rebuild a token from the ``authorization`` object carried in a node's arguments.

    A parse, not a trust decision: the signature covers every field, so a token whose fields have
    been edited simply does not verify and :func:`require_method` is what rules on it.
    """

    if payload is None or payload == "":
        return None
    if isinstance(payload, MethodAuthorization):
        return payload
    if not isinstance(payload, Mapping):
        raise ValueError(
            "method authorization must be the `authorization` object the plan step returned, "
            "passed verbatim"
        )
    try:
        return MethodAuthorization(
            method_id=str(payload["method_id"]),
            command_sha256=str(payload["command_sha256"]),
            executable_sha256=str(payload.get("executable_sha256", "")),
            files_sha256=str(payload["files_sha256"]),
            input_files_sha256=str(payload.get("input_files_sha256", "")),
            inputs_sha256=str(payload["inputs_sha256"]),
            outputs_sha256=str(payload["outputs_sha256"]),
            request_sha256=str(payload["request_sha256"]),
            unchecked=tuple(payload.get("unchecked", ())),
            issued_at=str(payload["issued_at"]),
            expires_at=str(payload["expires_at"]),
            signature=str(payload["signature"]),
        )
    except KeyError as error:
        raise ValueError(
            f"method authorization is missing the field {error.args[0]!r}; pass the object the "
            "plan step returned unchanged rather than a subset of it"
        ) from error


#: The remedy, in one place, because three refusals and two tool surfaces quote it.
MINTING_ROUTE = (
    "The authorization is minted for you: call etalon_action_prepare (FREE) for a single action, "
    "or etalon_workflow_plan (CHEAP) for a workflow, and submit the request/spec it returns -- it "
    "carries the token at arguments.authorization. It is minted on the declaration itself: "
    "method_id, the argv, the content digests of every declared `files` and `input_files` entry, "
    "the inputs object and the outputs map. Do not construct one by hand; the signature covers "
    "every field. A token does not survive a restart of the process that minted it unless "
    "ETALON_AUTHORITY_KEY is set in both."
)


def require_method(
    parameters: Mapping[str, Any],
    token: MethodAuthorization | None = None,
    *,
    when: datetime | None = None,
    required: bool | None = None,
) -> dict[str, Any]:
    """Rule on the authorization for one ``method.run`` dispatch, and return the record of it.

    Args:
        parameters: The resolved node arguments about to be dispatched -- resolved, because a
            ``{$ref: ...}`` still in them is a different declaration from the one that ran.
        token: The token, or ``None``. Omitted means it is taken from
            ``parameters["authorization"]``.
        required: Overrides :func:`stage`. Pass it explicitly in tests rather than setting the
            environment variable, so a test states the stage it is testing.

    Returns:
        A record for the preflight receipt. ``state`` is ``"authorized"`` or ``"absent"``; the
        latter is reachable only in stage 1 and carries the message stage 2 would have raised.

    Raises:
        NotAuthorizedMethod: Missing (stage 2 only), stale, or minted for a different declaration.
    """

    supplied = token if token is not None else token_from_mapping(parameters.get("authorization"))
    enforced = stage() == "required" if required is None else bool(required)
    method_id = str(parameters.get("method_id", ""))

    absent = (
        f"method.run was dispatched for {method_id!r} with no authorization. This operation "
        "launches host-authored argv as a detached child process; a declared wall_second allowance "
        "says how much it may cost and nothing about whether the program being run is the one that "
        f"was prepared. {MINTING_ROUTE}"
    )
    if supplied is None:
        if enforced:
            raise NotAuthorizedMethod(absent)
        return {
            "state": "absent",
            "stage": "optional",
            "method_id": method_id,
            "established": "nothing. No authorization was supplied and none was minted here.",
            "would_refuse_under": f"{STAGE_VARIABLE}=required",
            "refusal_text": absent,
        }

    require_signed(
        supplied,
        covers=lambda issued: issued.covers(parameters),
        when=when,
        error=NotAuthorizedMethod,
        missing=absent,
        stale=(
            f"the method authorization for {method_id!r} does not verify or has expired (issued "
            f"{supplied.issued_at}, expires {supplied.expires_at}). A token outliving its plan "
            "describes a declaration nobody has re-read; planning again costs nothing. "
            + MINTING_ROUTE
        ),
        mismatch=(
            f"the method authorization presented for {method_id!r} was minted for a different "
            "method request. Something changed between the plan and the dispatch -- the argv, a "
            "declared source file's contents, the inputs object, the outputs map, or the method "
            "id itself -- so what was prepared is not what would run. This is the taxonomy's "
            "WRONG_SUBJECT applied to the authorization itself, and it is the case this guard "
            "exists for: method.run executes whatever argv it is handed. "
            + MINTING_ROUTE
        ),
    )
    return {
        "state": "authorized",
        "stage": "required" if enforced else "optional",
        "method_id": method_id,
        "authorization": supplied.as_dict(),
        "unchecked": list(supplied.unchecked),
        "established": (
            "that the declaration dispatched is the declaration this token was minted on. Not that "
            "the program is safe, not that its result is admissible, and not that anybody read the "
            "argv."
        ),
    }


def unauthorized_method(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Why this request cannot be dispatched, as a record rather than an exception.

    For the caller that wants to report the refusal and continue -- a planning tool, a dry run --
    rather than the one that was about to launch the process.
    """

    try:
        record = require_method(parameters, required=True)
    except NotAuthorizedMethod as error:
        return {
            "method_id": str(parameters.get("method_id", "")),
            "authorized": False,
            "refusal": str(error),
        }
    return {"method_id": record["method_id"], "authorized": True, "unchecked": record.get("unchecked", [])}


__all__ = [
    "DEFAULT_METHOD_LIFETIME_HOURS",
    "EXECUTABLE_NOT_PINNED",
    "INPUT_FILES_NOT_PINNED",
    "MINTING_ROUTE",
    "STAGE_VARIABLE",
    "MethodAuthorization",
    "NotAuthorizedMethod",
    "authorize_method",
    "method_request_subject",
    "require_method",
    "stage",
    "token_from_mapping",
    "unauthorized_method",
]
