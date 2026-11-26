"""Dispatch-time join from committed CampaignStore rulings to ResearchJournal records.

``docs/thin-harness/ADMISSION_PROPAGATION.md`` §0.4 recorded that ``Ruling`` rows live in
``CampaignStore.observations`` while the research graph projects ``ResearchJournal`` records,
leaving no recorded join between them. This module supplies the write-at-dispatch record
(``moldarwin-admission-binding/1``) and the read-only extractor/view composer that feeds
``learn.admission_view.admission_view`` without backfilling historical records.

Hard constraints preserved here:

- **C1**: ``learn.admissible.rule`` is never called or modified; bindings carry the verbatim
  ``Ruling`` already committed in ``CampaignStore.observations``.
- **C2**: Recording a binding or deriving an admission view never mutates the target leaf
  record; bindings are separate content-addressed ``Artifact`` records pointing at the leaf's
  immutable ``(target_record_id, target_record_digest)``.
- **C3**: An admission state change on an already-bound record requires an explicit
  ``supersedes`` link (pointing at the prior binding artifact or its ``ruling_digest``),
  recording a new ``Artifact`` whose ``parents`` pin the prior binding so both the old
  admission and its ``claim_scope`` stay permanently readable and un-erased.
- **C4**: ``record_admission_binding`` refuses any ``action_id`` absent from
  ``CampaignStore.observations``, and ``extract_admission_bindings`` never fabricates or
  backfills bindings for historical nodes that were never bound at dispatch.
- **C6**: Writes go exclusively through ``ResearchJournal.record(Artifact(...))`` inside the
  ``research:`` namespace; ``CampaignStore`` is only read to fetch the committed observation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from moldarwin.active.schema import canonical, digest
from moldarwin.active.store import StateError
from moldarwin.boundary.prism_v1 import file_identity
from moldarwin.learn.admission_view import _check_ruling, admission_view

from .entry import resolve_entry
from .evidence import _collect
from .evidence_refs import EvidenceError, _sha, _text
from .graph_memory import GRAPH, build_research_graph, restrict_workspace
from .journal import PREFIX, ResearchJournal
from .schema import Artifact

SCHEMA = "moldarwin-admission-binding/1"
_STORE_STATUSES = frozenset({"ok", "failed", "invalid", "blocked"})
_REQUIRED_KEYS = frozenset({
    "schema",
    "target_record_id",
    "target_record_digest",
    "ruling",
    "ruling_digest",
    "dispatch_ref",
    "claim_scope",
    "store_status",
    "store_admitted",
})
_OPTIONAL_KEYS = frozenset({"supersedes_ruling_digest", "prior_binding_id"})


def validate_content(payload: Any) -> dict[str, Any]:
    """Validate one ``moldarwin-admission-binding/1`` payload without mutating it."""

    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise EvidenceError("unsupported admission binding schema")
    unknown = sorted(set(payload) - _REQUIRED_KEYS - _OPTIONAL_KEYS)
    if unknown:
        raise EvidenceError(f"admission binding has unknown fields: {unknown}")
    missing = sorted(_REQUIRED_KEYS - set(payload))
    if missing:
        raise EvidenceError(f"admission binding lacks required fields: {missing}")

    target_record_id = _text(payload["target_record_id"])
    _sha(payload["target_record_digest"])

    ruling = payload["ruling"]
    try:
        _check_ruling(target_record_id, ruling)
    except ValueError as exc:
        raise EvidenceError(str(exc)) from exc

    ruling_digest = payload["ruling_digest"]
    _sha(ruling_digest)
    if ruling_digest != digest(ruling):
        raise EvidenceError("admission binding ruling_digest does not match its ruling")

    store_status = payload["store_status"]
    store_admitted = payload["store_admitted"]
    if store_status not in _STORE_STATUSES or not isinstance(store_admitted, bool):
        raise EvidenceError("admission binding store_status or store_admitted is invalid")
    if store_admitted != (store_status == "ok" and ruling["teaches"]):
        raise EvidenceError(
            "admission binding store_admitted disagrees with (store_status == 'ok' and teaches)"
        )
    if ruling["teaches"] != store_admitted:
        raise EvidenceError("admission binding ruling teaches != store_admitted")

    dispatch = payload["dispatch_ref"]
    if (
        not isinstance(dispatch, dict)
        or set(dispatch) != {"store", "action_id"}
        or dispatch["store"] != "campaign"
        or not isinstance(dispatch["action_id"], str)
        or not dispatch["action_id"].strip()
    ):
        raise EvidenceError(
            "admission binding dispatch_ref must name store='campaign' and a nonempty action_id"
        )

    claim_scope = payload["claim_scope"]
    if not isinstance(claim_scope, dict):
        raise EvidenceError("admission binding claim_scope must be an object")
    if claim_scope.get("parent_id") != ruling["parent_id"]:
        raise EvidenceError("admission binding claim_scope parent_id disagrees with ruling parent_id")

    if "supersedes_ruling_digest" in payload:
        prior_digest = payload["supersedes_ruling_digest"]
        _sha(prior_digest)
        if prior_digest == ruling_digest:
            raise EvidenceError("admission binding cannot supersede its own ruling_digest")
    if "prior_binding_id" in payload:
        prior_id = _text(payload["prior_binding_id"])
        if not prior_id.startswith("artifact-"):
            raise EvidenceError("admission binding prior_binding_id must be an artifact record id")
        if "supersedes_ruling_digest" not in payload:
            raise EvidenceError(
                "admission binding prior_binding_id requires supersedes_ruling_digest"
            )

    return json.loads(canonical(payload))


def _existing_target_bindings(
    journal: ResearchJournal, target_record_id: str
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Return ``[(artifact_id, artifact_record, verified_payload), ...]`` for one target."""

    rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    with journal.store.connection() as db:
        entries = db.execute(
            "SELECT key, body FROM metadata WHERE key LIKE ? ORDER BY rowid",
            (PREFIX + "artifact-%",),
        ).fetchall()
    for key, raw_body in entries:
        record = json.loads(raw_body)
        bindings = record.get("bindings", {})
        if (
            not isinstance(bindings, dict)
            or bindings.get("schema") != SCHEMA
            or bindings.get("target_record_id") != target_record_id
        ):
            continue
        artifact_id = key.removeprefix(PREFIX)
        path = journal.artifact_path(Artifact(**record))
        payload = validate_content(json.loads(path.read_text(encoding="utf-8-sig")))
        if payload["target_record_id"] != target_record_id:
            raise StateError(
                f"admission binding artifact {artifact_id!r} target_record_id disagrees with metadata"
            )
        rows.append((artifact_id, record, payload))
    return rows


def record_admission_binding(
    journal: ResearchJournal,
    *,
    target_record_id: str,
    action_id: str,
    claim_scope: dict[str, Any],
    directory: str | Path,
    source_kind: str = "new_execution",
    role: str = "diagnostic",
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Bind one committed ``CampaignStore.observations`` ruling to an existing journal record.

    Reads the verbatim ``Ruling``, ``admitted`` flag, and evaluation ``status`` directly from
    ``CampaignStore.observations`` (never trusting caller-supplied verdicts and never backfilling
    an action that was not committed). Leaves the target record untouched (C2), writes only an
    immutable ``Artifact`` inside ``research:`` (C6), and requires an explicit ``supersedes``
    chain whenever a target's admission changes so old values and claim scopes survive (C3).
    """

    if not isinstance(journal, ResearchJournal):
        raise TypeError("journal must be a ResearchJournal")
    _text(target_record_id)
    _text(action_id)
    if not isinstance(claim_scope, dict):
        raise ValueError("claim_scope must be an object")
    if role == "sealed_holdout":
        raise ValueError("admission binding artifacts cannot have role='sealed_holdout'")

    target_body = journal.get(target_record_id)
    if (
        isinstance(target_body.get("bindings"), dict)
        and target_body["bindings"].get("schema") == SCHEMA
    ):
        raise EvidenceError("cannot bind admission onto another admission binding artifact")
    target_record_digest = digest(target_body)

    with journal.store.connection() as db:
        obs_row = db.execute(
            "SELECT admitted, body, ruling FROM observations WHERE action_id=?",
            (action_id,),
        ).fetchone()
    if obs_row is None:
        raise StateError(
            f"cannot bind admission without a committed CampaignStore observation for "
            f"action_id={action_id!r}"
        )

    store_admitted = bool(obs_row["admitted"])
    result_body = json.loads(obs_row["body"])
    store_status = result_body.get("status")
    ruling = json.loads(obs_row["ruling"])
    ruling_digest = digest(ruling)

    scope_copy = json.loads(canonical(claim_scope))
    if scope_copy.get("parent_id") != ruling["parent_id"]:
        raise ValueError(
            f"claim_scope.parent_id ({scope_copy.get('parent_id')!r}) must match the committed "
            f"ruling parent_id ({ruling['parent_id']!r})"
        )

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "target_record_id": target_record_id,
        "target_record_digest": target_record_digest,
        "ruling": ruling,
        "ruling_digest": ruling_digest,
        "dispatch_ref": {"store": "campaign", "action_id": action_id},
        "claim_scope": scope_copy,
        "store_status": store_status,
        "store_admitted": store_admitted,
    }

    existing = _existing_target_bindings(journal, target_record_id)
    parents: tuple[str, ...] = ()
    if supersedes is not None:
        _text(supersedes)
        matches = [
            item
            for item in existing
            if item[0] == supersedes or item[2]["ruling_digest"] == supersedes
        ]
        if len(matches) != 1:
            raise StateError(
                f"supersedes {supersedes!r} does not name a prior admission binding for "
                f"{target_record_id!r}"
            )
        prior_id, _, prior_payload = matches[0]
        if prior_payload["target_record_digest"] != target_record_digest:
            raise StateError("prior admission binding references a different target_record_digest")
        if prior_payload["ruling_digest"] == ruling_digest:
            raise ValueError("cannot supersede an admission binding with the same ruling_digest")
        if prior_payload["claim_scope"]["parent_id"] != scope_copy["parent_id"]:
            raise ValueError("supersedes chain cannot change claim_scope parent_id")
        payload["supersedes_ruling_digest"] = prior_payload["ruling_digest"]
        payload["prior_binding_id"] = prior_id
        parents = (prior_id,)

    payload = validate_content(payload)

    # Idempotent retry check against verified existing bindings for this target.
    for existing_id, existing_record, existing_payload in existing:
        if existing_payload == payload:
            return {
                "record_id": existing_id,
                "path": existing_record["path"],
                "target_record_id": target_record_id,
                "target_record_digest": target_record_digest,
                "ruling_digest": ruling_digest,
                "action_id": action_id,
                "admission": ruling["admission"],
                "supersedes_ruling_digest": payload.get("supersedes_ruling_digest"),
                "prior_binding_id": payload.get("prior_binding_id"),
            }

    if supersedes is None:
        if existing:
            raise StateError(
                f"target {target_record_id!r} already has a recorded admission binding; supply "
                "supersedes to record a state change without erasing or forking"
            )
    else:
        prior_digest = payload["supersedes_ruling_digest"]
        for _, _, existing_payload in existing:
            if existing_payload.get("supersedes_ruling_digest") == prior_digest:
                raise StateError(
                    f"prior ruling_digest {prior_digest!r} already has a successor binding for "
                    f"{target_record_id!r}; cannot fork admission history"
                )

    data = (canonical(payload) + "\n").encode("utf-8")
    target_dir = Path(directory).absolute()
    path = target_dir / (digest(payload) + ".json")
    artifact = Artifact(
        str(path),
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        source_kind=source_kind,
        role=role,
        parents=parents,
        bindings={
            "schema": SCHEMA,
            "target_record_id": target_record_id,
            "target_record_digest": target_record_digest,
            "action_id": action_id,
            "ruling_digest": ruling_digest,
        },
    )

    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target_dir, prefix=".admission-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise EvidenceError("immutable admission binding content conflicts") from None
    finally:
        temporary.unlink()

    if file_identity(path) != {"sha256": artifact.sha256, "bytes": artifact.bytes}:
        raise EvidenceError("published admission binding content changed")

    record_id = journal.record(artifact)
    return {
        "record_id": record_id,
        "path": str(path),
        "target_record_id": target_record_id,
        "target_record_digest": target_record_digest,
        "ruling_digest": ruling_digest,
        "action_id": action_id,
        "admission": ruling["admission"],
        "supersedes_ruling_digest": payload.get("supersedes_ruling_digest"),
        "prior_binding_id": payload.get("prior_binding_id"),
    }


def extract_admission_bindings(
    workspace: Any,
    graph: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    purpose: str = "research",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read-only extraction of recorded ``moldarwin-admission-binding/1`` artifacts for a graph.

    Never fabricates or backfills bindings for unbound historical nodes (C4). Fails closed if any
    published admission binding artifact in the permitted workspace fails byte or schema
    verification (an unavailable ``withheld`` binding must never silently revert a node to
    ``not_recorded``).
    """

    ws, _ = restrict_workspace(workspace, policy=policy, purpose=purpose)
    records, _, _ = _collect(ws)
    universe = {(sid, rid): row for sid, rows in records.items() for rid, row in rows.items()}

    node_by_record = {
        (node["ref"]["source_id"], node["ref"]["record_id"], node["ref"]["record_digest"]): node[
            "node_id"
        ]
        for node in graph["nodes"]
        if "member" not in node["ref"]
    }

    bindings: list[dict[str, Any]] = []
    verified_count = 0
    unmatched_count = 0

    for (sid, rid), row in sorted(universe.items()):
        projection = row.get("projection", {})
        if projection.get("schema") != SCHEMA:
            continue
        if projection.get("status") != "verified" or "projected_content" not in row:
            reason = projection.get("reason", "unavailable")
            raise EvidenceError(
                f"admission binding artifact {sid}:{rid} unavailable or identity changed ({reason})"
            )
        verified_count += 1
        payload = row["projected_content"]
        key = (sid, payload["target_record_id"], payload["target_record_digest"])
        nid = node_by_record.get(key)
        if nid is None:
            unmatched_count += 1
            continue
        entry: dict[str, Any] = {
            "node_id": nid,
            "ruling": payload["ruling"],
            "ruling_digest": payload["ruling_digest"],
            "dispatch_ref": payload["dispatch_ref"],
            "claim_scope": payload["claim_scope"],
            "store_status": payload["store_status"],
            "store_admitted": payload["store_admitted"],
        }
        if "supersedes_ruling_digest" in payload:
            entry["supersedes"] = [payload["supersedes_ruling_digest"]]
        bindings.append(entry)

    summary = {
        "schema": SCHEMA,
        "binding_records_verified": verified_count,
        "matched_bindings": len(bindings),
        "unmatched_bindings": unmatched_count,
        "bound_nodes": len({b["node_id"] for b in bindings}),
        "graph_nodes": len(graph["nodes"]),
        "source": "recorded_dispatch_bindings",
    }
    return bindings, summary


def summarize_admission_view(view: dict[str, Any]) -> dict[str, Any]:
    """Token-efficient summary of an admission view keeping 100% of actionable signals.

    Omits clean, undisputed ``admitted`` nodes from the node list (while reporting their
    exact count) and retains every ``withheld``, ``not_recorded``, ``admitted_under_waiver``,
    membrane-degraded, or superseded node.
    """

    counts_admission: dict[str, int] = {}
    counts_exact: dict[str, int] = {}
    noteworthy: list[dict[str, Any]] = []
    clean_omitted = 0

    for node in view["nodes"]:
        adm = node["admission"]
        ex = node["exact_admission"]
        counts_admission[adm] = counts_admission.get(adm, 0) + 1
        counts_exact[ex] = counts_exact.get(ex, 0) + 1
        interesting = (
            adm != "admitted"
            or ex != "admitted"
            or bool(node.get("regime_refused_premises"))
            or bool(node.get("rests_on_superseded_premise"))
            or bool(node.get("history"))
        )
        if interesting:
            noteworthy.append({
                "node_id": node["node_id"],
                "kind": node["kind"],
                "admission": adm,
                "exact_admission": ex,
                "leaf": node["leaf"],
                "limiting_leaves": node["limiting_leaves"],
                "regime_refused_premises": node["regime_refused_premises"],
                "rests_on_superseded_premise": node["rests_on_superseded_premise"],
                "reasons": node["reasons"],
            })
        else:
            clean_omitted += 1

    return {
        "schema": "moldarwin-admission-view-summary/1",
        "view_id": view["view_id"],
        "view_version": view["view_version"],
        "graph_view_id": view["graph_view_id"],
        "catalogue_digest": view["catalogue_digest"],
        "graph_completeness": view["graph_completeness"],
        "membrane": view["membrane"],
        "total_nodes": len(view["nodes"]),
        "total_edges": len(view["edges"]),
        "counts_by_admission": dict(sorted(counts_admission.items())),
        "counts_by_exact_admission": dict(sorted(counts_exact.items())),
        "noteworthy_nodes": noteworthy,
        "omitted_clean_admitted_nodes": clean_omitted,
    }


def build_admission_view(
    workspace: Any = None,
    *,
    checkpoint_ref: dict[str, Any] | None = None,
    entry: Any = None,
    read_context: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    purpose: str | None = None,
    labels: dict[str, str] | None = None,
    extra_bindings: list[dict[str, Any]] | None = None,
    shadow_nodes: list[str] | tuple[str, ...] | None = None,
    detail: str = "full",
    max_nodes: int = 64,
    max_bytes: int = 65536,
    as_of: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only derived admission view from a published workspace and recorded bindings.

    With ``detail="full"`` (default), returns ``view`` verbatim from
    :func:`moldarwin.learn.admission_view.admission_view` (directly comparable via
    ``compare_views``). With ``detail="summary"``, returns a token-compact ``summary`` card
    retaining all non-clean/membrane/superseded nodes and exact denominators. When
    ``shadow_nodes`` is supplied, runs :func:`moldarwin.learn.memory_shadow.check_shadow`
    read-only and returns ``shadow_report``. Never mutates any leaf record or store.
    """

    if detail not in {"full", "summary"}:
        raise ValueError("detail must be 'full' or 'summary'")

    selectors = sum(
        x is not None for x in (workspace if checkpoint_ref is not None else None, entry, read_context)
    )
    if (workspace is not None) != (checkpoint_ref is not None):
        raise EvidenceError("workspace and checkpoint_ref must be supplied together")
    if selectors != 1:
        raise EvidenceError("supply exactly one of (workspace + checkpoint_ref), entry, or read_context")

    effective_policy = policy
    effective_purpose = "research" if purpose is None else purpose

    if entry is not None or read_context is not None:
        ws, ckpt_ref, _, ctx = resolve_entry(entry if entry is not None else read_context)
        if ctx is not None:
            if policy is not None:
                raise EvidenceError("read_context already pins policy; omit policy or resolve entry again")
            if purpose is not None and purpose != ctx["purpose"]:
                raise EvidenceError("read_context already pins purpose; omit purpose or resolve entry again")
            effective_policy = None
            effective_purpose = ctx["purpose"]
    else:
        ws = workspace
        ckpt_ref = checkpoint_ref

    graph = build_research_graph(
        ws,
        checkpoint_ref=ckpt_ref,
        policy=effective_policy,
        purpose=effective_purpose,
        max_nodes=max_nodes,
        max_bytes=max_bytes,
        as_of=as_of,
        scope=scope,
    )
    if graph.get("schema") != GRAPH:
        raise EvidenceError(
            "scoped graph exceeded max_bytes and returned paged rows; increase max_bytes or "
            "narrow scope to compute an admission view"
        )

    recorded, extraction = extract_admission_bindings(
        ws, graph, policy=effective_policy, purpose=effective_purpose
    )
    extras = list(extra_bindings) if extra_bindings is not None else []
    all_bindings = [*recorded, *extras]
    view = admission_view(graph, all_bindings, labels=labels)

    mode = (
        "recorded_dispatch_bindings"
        if not extras
        else ("mixed" if recorded else "caller_declared")
    )
    result: dict[str, Any] = {
        "graph_view_id": graph["view_id"],
        "checkpoint_ref": graph["checkpoint_ref"],
        "binding_extraction": {
            **extraction,
            "caller_extra_bindings": len(extras),
            "binding_source_mode": mode,
        },
        "execution_permission": "not_granted",
        "automatic_retry": False,
    }
    if detail == "summary":
        result["summary"] = summarize_admission_view(view)
    else:
        result["view"] = view

    if shadow_nodes is not None:
        from moldarwin.learn.memory_shadow import check_shadow

        report = check_shadow(graph, all_bindings, shadow=shadow_nodes, labels=labels)
        result["shadow_report"] = report.as_dict()

    return result


def record_artifact_with_admission(
    journal: ResearchJournal,
    artifact: Artifact,
    *,
    action_id: str,
    claim_scope: dict[str, Any],
    bindings_directory: str | Path,
    source_kind: str = "new_execution",
    role: str = "diagnostic",
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Stealth dispatch seam: record one leaf Artifact and immediately bind its committed Ruling.

    Removes manual two-step ceremony at execution settlement while preserving every hard
    constraint: the leaf Artifact stays byte-identical (C2), the Ruling is read verbatim
    from ``CampaignStore.observations`` (C1/C4), and the binding lands in ``research:`` (C6).
    """
    if not isinstance(artifact, Artifact):
        raise TypeError("artifact must be a ResearchJournal Artifact")
    leaf_id = journal.record(artifact)
    binding = record_admission_binding(
        journal,
        target_record_id=leaf_id,
        action_id=action_id,
        claim_scope=claim_scope,
        directory=bindings_directory,
        source_kind=source_kind,
        role=role,
        supersedes=supersedes,
    )
    return {"leaf_record_id": leaf_id, "binding": binding}


__all__ = [
    "SCHEMA",
    "build_admission_view",
    "extract_admission_bindings",
    "record_admission_binding",
    "record_artifact_with_admission",
    "summarize_admission_view",
    "validate_content",
]
