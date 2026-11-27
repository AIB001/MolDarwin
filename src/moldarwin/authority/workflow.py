"""Subject-bound authorization for active campaign submission and workflow resume.

Completes MolDarwin's spending-surface authority boundary alongside :mod:`moldarwin.authority.grant`,
:mod:`moldarwin.authority.gate`, and :mod:`moldarwin.authority.method`, moving the mechanical
``tools/count_unguarded_spends.py`` census from ``2/7`` to ``0/7`` unguarded ``SPENDS`` tools.

Two concrete subjects share this module:
  * ``action="active.submit"`` — minted by ``moldarwin_active_execution_plan`` (CHEAP, read-only)
    over ``(database, plan_id, max_rounds, min_new_admitted, max_seconds)`` and enforced by
    ``moldarwin_active_submit`` before dispatching a persistent active-learning worker.
  * ``action="workflow.resume"`` — minted by ``moldarwin_workflow_status`` or a non-resuming
    ``moldarwin_workflow_reconcile(resume=False)`` over ``(workspace, job_id, plan_id, epoch)``
    and enforced by ``moldarwin_workflow_reconcile(resume=True)`` before relaunching a stopped
    worker.

A spending tool never mints its own authorization. Present tokens are always verified regardless
of rollout stage; absent tokens are refused when ``MOLDARWIN_WORKFLOW_AUTHORITY=required`` or
``MOLDARWIN_METHOD_AUTHORITY=required`` (matching :mod:`moldarwin.authority.method`).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from moldarwin.authority.subject import (
    NotAuthorized,
    Signed,
    digest_of,
    require_signed,
    sign,
)

#: Token lifetime in hours (Evidence: convention; matches DEFAULT_METHOD_LIFETIME_HOURS).
DEFAULT_WORKFLOW_LIFETIME_HOURS: float = 24.0

#: Environment variables controlling strictness when no token is supplied.
STAGE_VARIABLE = "MOLDARWIN_WORKFLOW_AUTHORITY"
FALLBACK_STAGE_VARIABLE = "MOLDARWIN_METHOD_AUTHORITY"

MINTING_ROUTE = (
    "For moldarwin_active_submit, call moldarwin_active_execution_plan (CHEAP, read-only) and pass "
    "its returned authorization object as authorization_json. For moldarwin_workflow_reconcile with "
    "resume=true, call moldarwin_workflow_status or moldarwin_workflow_reconcile(resume=false) and "
    "pass its returned resume_authorization as authorization_json."
)


class NotAuthorizedWorkflow(NotAuthorized):
    """Raised when active submission or workflow resume lacks a valid matching authorization."""


def stage() -> str:
    """Return ``"optional"`` or ``"required"`` from environment configuration."""
    for var in (STAGE_VARIABLE, FALLBACK_STAGE_VARIABLE):
        raw = os.environ.get(var, "").strip().lower()
        if raw:
            if raw not in {"optional", "required"}:
                raise ValueError(f"{var} must be 'optional' or 'required', got {raw!r}")
            return raw
    return "optional"


def active_submit_subject(
    *,
    database: str | Path,
    plan_id: str,
    max_rounds: int,
    min_new_admitted: int,
    max_seconds: float,
) -> dict[str, Any]:
    """Canonical subject binding an active execution plan to its dispatch parameters."""
    return {
        "action": "active.submit",
        "target_id": str(Path(database).resolve()),
        "plan_id": str(plan_id),
        "epoch": None,
        "parameters": {
            "max_rounds": int(max_rounds),
            "min_new_admitted": int(min_new_admitted),
            "max_seconds": float(max_seconds),
        },
    }


def workflow_resume_subject(
    *,
    workspace: str | Path,
    job_id: str,
    plan_id: str,
    epoch: int,
) -> dict[str, Any]:
    """Canonical subject binding a workflow resume to its exact job, plan, and epoch."""
    return {
        "action": "workflow.resume",
        "target_id": f"{Path(workspace).resolve()}:{job_id}",
        "plan_id": str(plan_id),
        "epoch": int(epoch),
        "parameters": {"job_id": str(job_id)},
    }


@dataclass(frozen=True, slots=True)
class WorkflowAuthorization(Signed):
    """Signed permission covering one active submission or workflow resume."""

    action: str
    target_id: str
    plan_id: str
    epoch: int | None
    subject_sha256: str
    issued_at: str
    expires_at: str
    unchecked: tuple[str, ...]
    signature: str

    def _signed_fields(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target_id": self.target_id,
            "plan_id": self.plan_id,
            "epoch": self.epoch,
            "subject_sha256": self.subject_sha256,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "unchecked": list(self.unchecked),
        }

    def covers(self, subject: Mapping[str, Any]) -> bool:
        return (
            self.action == subject.get("action")
            and self.target_id == subject.get("target_id")
            and self.plan_id == subject.get("plan_id")
            and self.epoch == subject.get("epoch")
            and self.subject_sha256 == digest_of(subject)
        )


def authorize_workflow(
    subject: Mapping[str, Any],
    *,
    lifetime_hours: float = DEFAULT_WORKFLOW_LIFETIME_HOURS,
    now: datetime | None = None,
    unchecked: tuple[str, ...] = (),
) -> WorkflowAuthorization:
    """Mint a signed :class:`WorkflowAuthorization` for an active plan or workflow resume."""
    moment = now or datetime.now(UTC)
    issued = moment.isoformat()
    expires = (moment + timedelta(hours=lifetime_hours)).isoformat()
    fields = {
        "action": str(subject["action"]),
        "target_id": str(subject["target_id"]),
        "plan_id": str(subject["plan_id"]),
        "epoch": subject.get("epoch"),
        "subject_sha256": digest_of(subject),
        "issued_at": issued,
        "expires_at": expires,
        "unchecked": list(unchecked),
    }
    return WorkflowAuthorization(
        action=fields["action"],
        target_id=fields["target_id"],
        plan_id=fields["plan_id"],
        epoch=fields["epoch"],
        subject_sha256=fields["subject_sha256"],
        issued_at=issued,
        expires_at=expires,
        unchecked=tuple(unchecked),
        signature=sign(fields),
    )


def token_from_json(authorization_json: str) -> WorkflowAuthorization | None:
    """Parse ``authorization_json`` into a :class:`WorkflowAuthorization`, or ``None`` if empty."""
    if not authorization_json or not authorization_json.strip():
        return None
    payload = json.loads(authorization_json)
    if not isinstance(payload, dict):
        raise ValueError("authorization_json must be a JSON object returned by the plan/status tool")
    for wrapper_key in ("authorization", "resume_authorization", "authorization_token"):
        inner = payload.get(wrapper_key)
        if isinstance(inner, dict) and "signature" in inner:
            payload = inner
            break
    required = {"action", "target_id", "plan_id", "subject_sha256", "issued_at", "expires_at", "signature"}
    missing = sorted(required - set(payload))
    if missing:
        raise NotAuthorizedWorkflow(
            f"workflow authorization object is missing required fields {missing}; {MINTING_ROUTE}"
        )
    return WorkflowAuthorization(
        action=str(payload["action"]),
        target_id=str(payload["target_id"]),
        plan_id=str(payload["plan_id"]),
        epoch=int(payload["epoch"]) if payload.get("epoch") is not None else None,
        subject_sha256=str(payload["subject_sha256"]),
        issued_at=str(payload["issued_at"]),
        expires_at=str(payload["expires_at"]),
        unchecked=tuple(str(x) for x in (payload.get("unchecked") or ())),
        signature=str(payload["signature"]),
    )


def require_workflow_authorization(
    authorization_json: str,
    subject: Mapping[str, Any],
    *,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Enforce workflow authorization according to rollout stage and strict token verification."""
    token = token_from_json(authorization_json)
    current_stage = stage()
    if token is None:
        if current_stage == "required":
            raise NotAuthorizedWorkflow(
                f"{subject['action']} requires an explicit authorization under stage='required'. "
                + MINTING_ROUTE
            )
        return {
            "state": "absent",
            "stage": current_stage,
            "action": subject["action"],
            "note": (
                "No authorization_json supplied (accepted under stage='optional'; set "
                f"{STAGE_VARIABLE}=required or {FALLBACK_STAGE_VARIABLE}=required to refuse)."
            ),
        }

    verified = require_signed(
        token,
        covers=lambda tok: tok.covers(subject),
        missing=f"{subject['action']} requires a workflow authorization. {MINTING_ROUTE}",
        stale=(
            f"workflow authorization for {subject['action']} has an invalid signature or expired "
            f"(also check MOLDARWIN_AUTHORITY_KEY across restarts). {MINTING_ROUTE}"
        ),
        mismatch=(
            f"workflow authorization does not match {subject['action']} for "
            f"plan_id={subject['plan_id']!r}, epoch={subject.get('epoch')!r}, or its parameters. "
            + MINTING_ROUTE
        ),
        when=when,
        error=NotAuthorizedWorkflow,
    )
    return {
        "state": "verified",
        "stage": current_stage,
        "action": verified.action,
        "plan_id": verified.plan_id,
        "epoch": verified.epoch,
        "subject_sha256": verified.subject_sha256,
    }


__all__ = [
    "DEFAULT_WORKFLOW_LIFETIME_HOURS",
    "MINTING_ROUTE",
    "NotAuthorizedWorkflow",
    "STAGE_VARIABLE",
    "WorkflowAuthorization",
    "active_submit_subject",
    "authorize_workflow",
    "require_workflow_authorization",
    "stage",
    "token_from_json",
    "workflow_resume_subject",
]
