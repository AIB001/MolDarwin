"""Optional revision Artifact helpers; never an execution gate or a new ledger.

Build accepts source-qualified references without reading them. Record verifies
local method lineage and producer attribution before publishing immutable JSON.
External evidence stays explicitly unresolved here; use evidence.read_evidence
to inspect it, or register a local source-envelope Artifact when appropriate.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from moldarwin.active.schema import canonical, digest
from moldarwin.boundary.prism_v1 import file_identity
from .evidence_refs import make_ref, validate_ref
from .schema import Artifact, nonempty


def journal_ref(journal, record_id: str, *, source_id: str) -> dict:
    """Bind a record to the caller's explicit workspace source ID, not its path.

    The caller owns source-ID/workspace identity binding. This does not infer a
    globally stable ID from a mutable database hash or register a new source.
    """
    return make_ref(source_id, record_id, journal.get(record_id))


def build_method_revision(*, problem_refs, target_kind, base_method_ref,
                          producer_method_ref, producer_use_ref,
                          change_summary, mechanism_hypothesis, scope,
                          candidate_version_refs=(), counterexamples=(),
                          trial_refs=(), accounting_refs=()) -> dict:
    """Build JSON content, including reasoned no-change (empty candidates).

    No journal, files, tools, model, registration or trial is required. Unknown
    costs belong in accounting artifacts, never invented numeric zeroes.
    """
    if target_kind not in {"S", "U", "G"}:
        raise ValueError("target_kind must be S, U or G")
    for value in (change_summary, mechanism_hypothesis, scope):
        nonempty(value)

    def refs(values):
        if not isinstance(values, (list, tuple)):
            raise ValueError("references must be a sequence")
        result = [validate_ref(ref) for ref in values]
        if len({canonical(ref) for ref in result}) != len(result):
            raise ValueError("duplicate reference")
        return result

    problems = refs(problem_refs)
    if not problems:
        raise ValueError("a revision needs a concrete problem reference")
    if not isinstance(counterexamples, (list, tuple)):
        raise ValueError("counterexamples must be a sequence of text")
    for item in counterexamples:
        nonempty(item)
    payload = dict(schema="moldarwin-method-revision/1", problem_refs=problems,
                   target_kind=target_kind, base_method_ref=validate_ref(base_method_ref),
                   producer_method_ref=validate_ref(producer_method_ref),
                   producer_use_ref=validate_ref(producer_use_ref),
                   candidate_version_refs=refs(candidate_version_refs),
                   change_summary=change_summary, mechanism_hypothesis=mechanism_hypothesis,
                   scope=scope, counterexamples=list(counterexamples),
                   trial_refs=refs(trial_refs), accounting_refs=refs(accounting_refs))
    return json.loads(canonical(payload))


def record_method_revision(journal, payload: dict, directory: str | Path, *,
                           source_id: str, source_kind: str,
                           role: str = "diagnostic") -> str:
    """Publish content-addressed JSON, then record an ordinary Artifact.

    Replays in the same directory return the same Artifact ID/event. File and
    DB are separate commits: a failed DB write leaves a verifiable orphan for
    retry; no files or facts are rolled back/deleted. Local reference metadata
    is checked; this does not attest native method application or external files.
    Method references must be local: import an external complete snapshot and
    explicit provenance envelope first, or use build_method_revision alone.
    """
    nonempty(source_id)
    if not isinstance(payload, dict) or payload.get("schema") != "moldarwin-method-revision/1":
        raise ValueError("expected moldarwin-method-revision/1")
    content = build_method_revision(**{k: v for k, v in payload.items() if k != "schema"})

    def local(ref, schema=None):
        if ref["source_id"] != source_id:
            raise ValueError("method references require local snapshots and source envelopes")
        body = journal.get(ref["record_id"])
        if digest(body) != ref["record_digest"]:
            raise ValueError("record digest mismatch")
        if schema and body.get("schema") != schema:
            raise ValueError("wrong referenced method record type")
        return body

    base = local(content["base_method_ref"], "moldarwin-method-version/1")
    producer = local(content["producer_method_ref"], "moldarwin-method-version/1")
    use = local(content["producer_use_ref"], "moldarwin-method-use/1")
    producer_id = content["producer_method_ref"]["record_id"]
    if producer_id not in {r["method_version_ref"] for r in use["selected_methods"]}:
        raise ValueError("producer use must attribute the producer method; read is not applied")
    target_role = {"S": "domain_skill", "U": "usage_method", "G": "improvement_method"}[content["target_kind"]]
    if target_role not in base["roles"] or "improvement_method" not in producer["roles"]:
        raise ValueError("target/producer roles do not match revision kind")
    base_id = content["base_method_ref"]["record_id"]
    for ref in content["candidate_version_refs"]:
        candidate = local(ref, "moldarwin-method-version/1")
        if ref["record_id"] == base_id or base_id not in candidate["parents"]:
            raise ValueError("candidate must descend from the target base")
        if producer_id != base_id and producer_id in candidate["parents"]:
            raise ValueError("producer is not a target parent")
        if target_role not in candidate["roles"]:
            raise ValueError("candidate target role mismatch")
    external = []
    for field in ("problem_refs", "trial_refs", "accounting_refs"):
        for ref in content[field]:
            if ref["source_id"] == source_id:
                body = local(ref)
                if field == "accounting_refs" and body.get("bindings", {}).get("kind") not in {
                    "accounting", "cost_receipt", "resource_accounting"
                }:
                    raise ValueError("accounting ref must identify an accounting artifact")
            else:
                external.append(ref)
    data = (canonical(content) + "\n").encode("utf-8")
    directory = Path(directory).absolute()
    path = directory / (digest(content) + ".json")
    item = Artifact(str(path), sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data), source_kind=source_kind, role=role,
                    bindings={"kind": "method_revision", "schema": content["schema"],
                              "source_id": source_id, "reference_verification":
                              "local_metadata_checked_external_unresolved" if external else "local_metadata_checked"})
    directory.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("immutable revision file conflicts")
    else:
        # Publish a fully written file without replacing an existing destination.
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".revision-", delete=False) as f:
            temporary = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("immutable revision file conflicts")
        finally:
            temporary.unlink()
    if file_identity(path) != {"sha256": item.sha256, "bytes": item.bytes}:
        raise ValueError("published revision changed")
    return journal.record(item)


def _comparison_body(comparison, *, resolve_local=None):
    """Normalise an optional comparison to its recorded mapping, enforcing its own invariants.

    Accepts a ``revision_score.Comparison``, a local ``EvidenceRef`` to a recorded
    ``moldarwin-revision-comparison/1`` Artifact, or the serialized mapping ``as_dict`` returns.
    Every structural and safety invariant of ``revision_score`` is re-checked here so a
    hand-assembled or mutated dict cannot pass a contradictory ``adoption``/``outcome``, smuggle
    a ``diagnostic`` comparison into ``full``/``scoped`` adoption, or hide a quality regression.
    """

    if comparison is None:
        return None, None
    from .continuation import _comparison as _validate_comparison_summary
    from .evidence_refs import EvidenceError
    from .revision_score import Adoption, Family, Verdict, _OUTCOME

    comparison_ref = None
    if isinstance(comparison, dict) and {"source_id", "record_id"} <= comparison.keys():
        if resolve_local is None:
            raise ValueError("a comparison reference requires local journal resolution")
        artifact = resolve_local(comparison)
        body = json.loads(resolve_local.read_artifact(artifact))
        comparison_ref = comparison
    else:
        body = comparison.as_dict() if hasattr(comparison, "as_dict") else comparison

    if not isinstance(body, dict) or body.get("schema") != "moldarwin-revision-comparison/1":
        raise ValueError("comparison must be a moldarwin-revision-comparison/1 result")
    try:
        adoption = Adoption(body.get("adoption"))
    except ValueError as error:
        raise ValueError("comparison carries no recognised adoption level") from error
    if body.get("outcome") not in {"adopt", "retain"}:
        raise ValueError("comparison carries no recognised outcome")
    expected_outcome = _OUTCOME[adoption]
    if body["outcome"] != expected_outcome:
        raise ValueError(
            f"comparison is internally inconsistent: adoption {adoption.value!r} requires "
            f"outcome {expected_outcome!r}, not {body['outcome']!r}"
        )
    role = body.get("assessment_role")
    if role not in {"diagnostic", "independent_validation"}:
        raise ValueError("comparison must declare assessment_role as diagnostic or independent_validation")
    if role == "diagnostic" and adoption in (Adoption.FULL, Adoption.SCOPED):
        raise ValueError(
            f"comparison is internally inconsistent: diagnostic assessment_role cannot yield "
            f"adoption {adoption.value!r}"
        )
    reservations = body.get("reservations", [])
    if not isinstance(reservations, list) or any(not isinstance(item, str) or not item.strip() for item in reservations):
        raise ValueError("comparison reservations must be a list of nonempty strings")
    waiver_change = body.get("waiver_change", 0)
    if isinstance(waiver_change, bool) or not isinstance(waiver_change, int):
        raise ValueError("comparison waiver_change must be an integer")
    try:
        summary = _comparison_summary(body)
        _validate_comparison_summary(summary)
    except (KeyError, TypeError, EvidenceError) as error:
        raise ValueError(f"comparison summary is incomplete or invalid: {error}") from error

    quality_families = {
        Family.WARRANT.value, Family.REFUSAL.value, Family.COVERAGE.value, Family.PROVENANCE.value
    }
    dims = summary["dimensions"]
    quality_gain = any(d["family"] in quality_families and d["verdict"] == Verdict.BETTER.value for d in dims)
    any_gain = any(d["verdict"] == Verdict.BETTER.value for d in dims)
    quality_regression = any(d["family"] in quality_families and d["verdict"] == Verdict.WORSE.value for d in dims)
    any_regression = any(d["verdict"] == Verdict.WORSE.value for d in dims)
    if adoption in (Adoption.FULL, Adoption.SCOPED):
        if quality_regression:
            raise ValueError("comparison is internally inconsistent: cannot adopt with a quality regression")
        if not any_gain:
            raise ValueError("comparison is internally inconsistent: cannot adopt with no improved dimension")
        if any_regression and not quality_gain:
            raise ValueError("comparison is internally inconsistent: cost gain alone cannot pay for a regression")
        if waiver_change > 0 and not quality_gain:
            raise ValueError("comparison is internally inconsistent: extra waivers with no quality gain cannot adopt")
    return body, comparison_ref


def _comparison_summary(verdict):
    """The part of a comparison that fits in a research step, keeping its numbers.

    The step has 16 KiB for the whole record, and a comparison's per-dimension prose is the
    large part of it. Dropped here and not elsewhere: the reservations go into
    ``reconsider_when`` on the same step, so no reason for a bounded adoption is lost.
    """

    if not isinstance(verdict.get("dimensions"), list):
        raise TypeError("comparison dimensions must be a list")
    return {
        "adoption": verdict["adoption"],
        "gain": verdict["gain"],
        "catalogue_digest": verdict["catalogue_digest"],
        "dimensions": [
            {"name": row["name"], "family": row["family"], "verdict": row["verdict"],
             "effect": row["effect"], "p_value": row["p_value"]}
            for row in verdict["dimensions"]
        ],
    }


def resolve_method_revision(journal, revision_ref, evaluation_ref, *, outcome, task_id, question,
                            scope, reason, directory, source_id, source_kind,
                            candidate_ref=None, prior_use_ref=None, counterevidence_refs=(),
                            comparison=None):
    """Record scoped adoption/retention/rollback using MethodUse and a decision step.

    The host supplies the conclusion after examining the evaluation. This helper
    validates attribution, not scientific truth; it changes no shared default and
    executes no candidate. A subsequent caller explicitly uses the chosen version.

    ``comparison`` is an optional ``revision_score.Comparison``, a local ``EvidenceRef`` to a
    persisted ``moldarwin-revision-comparison/1`` Artifact, or the mapping ``as_dict`` returns.
    Supplying one binds the outcome to both the comparison's verdict and the referenced
    ``MethodEvaluation``'s ``assessment_role``: a candidate the comparison refused cannot be
    adopted, a diagnostic evaluation cannot be paired with an independent-validation comparison,
    and the comparison's reservations are carried into the step's ``reconsider_when``. Omitting
    one is allowed and is **recorded as an omission** -- ``adoption_basis`` is ``host_assertion``
    rather than ``measured_comparison`` -- because the hazard this guards is not that an
    unjustified adoption happens, it is that an unjustified adoption looks exactly like a
    justified one afterwards.
    """
    from .schema import MethodUse
    from .continuation import STEP, record_content
    if outcome not in {"adopt", "retain", "rollback"}:
        raise ValueError("outcome must be adopt, retain or rollback")
    for value in (task_id, question, scope, reason):
        nonempty(value)

    def local(ref, schema=None):
        validate_ref(ref)
        if ref["source_id"] != source_id:
            raise ValueError("resolution needs exact local records")
        body = journal.get(ref["record_id"])
        if digest(body) != ref["record_digest"] or (schema and body.get("schema") != schema):
            raise ValueError("resolution reference identity or type mismatch")
        if ref["record_id"].startswith("artifact-"):
            journal.artifact_path(Artifact(**body))
        return body

    local.read_artifact = lambda artifact_body: journal.artifact_path(Artifact(**artifact_body)).read_text("utf-8")

    verdict, comparison_ref = _comparison_body(comparison, resolve_local=local)
    if verdict is not None and outcome != verdict["outcome"]:
        raise ValueError(
            f"the comparison concluded {verdict['adoption']!r}, whose outcome is "
            f"{verdict['outcome']!r}, and this resolution says {outcome!r}. "
            + ("Rollback additionally needs prior use and counterevidence, which a comparison "
               "cannot establish; resolve it without one and record the counterevidence."
               if outcome == "rollback" else
               "Adopting against a measured refusal is the failure the comparison exists to "
               "catch. Narrow the revision, measure more, or record the refusal."))

    artifact = local(revision_ref)
    revision = json.loads(journal.artifact_path(Artifact(**artifact)).read_text("utf-8"))
    if revision.get("schema") != "moldarwin-method-revision/1":
        raise ValueError("resolution requires a MethodRevision")
    revision = build_method_revision(**{k: v for k,v in revision.items() if k != "schema"})
    evaluation = local(evaluation_ref, "moldarwin-method-evaluation/1")
    if verdict is not None and evaluation.get("assessment_role") != verdict["assessment_role"]:
        raise ValueError(
            f"comparison assessment_role {verdict['assessment_role']!r} disagrees with "
            f"referenced MethodEvaluation assessment_role {evaluation.get('assessment_role')!r}; "
            "a diagnostic evaluation cannot be adopted behind an independent_validation comparison"
        )
    base = revision["base_method_ref"]
    local(base, "moldarwin-method-version/1")
    candidates = {canonical(r) for r in revision["candidate_version_refs"]}
    candidate_ids = {r["record_id"] for r in revision["candidate_version_refs"]}
    if evaluation["comparators"] != [base["record_id"]] or not set(evaluation["subjects"]) <= candidate_ids:
        raise ValueError("evaluation does not compare this revision with its base")
    for ref in counterevidence_refs:
        local(ref)
    prior = local(prior_use_ref, "moldarwin-method-use/1") if prior_use_ref else None
    if outcome == "adopt":
        if candidate_ref is None or canonical(candidate_ref) not in candidates:
            raise ValueError("adoption requires an exact revision candidate")
        local(candidate_ref, "moldarwin-method-version/1")
        if candidate_ref["record_id"] not in evaluation["subjects"] or not evaluation["result_refs"] or not evaluation["accounting_refs"]:
            raise ValueError("adoption needs measured results and accounting for the chosen candidate")
        selected = candidate_ref
    else:
        selected = base
    if outcome == "rollback" and (prior is None or not counterevidence_refs or not
            any(m["method_version_ref"] in candidate_ids for m in prior["selected_methods"])):
        raise ValueError("rollback needs prior candidate use and explicit counterevidence")
    refs = [revision_ref, evaluation_ref, *([comparison_ref] if comparison_ref else []), *counterevidence_refs]
    # An adoption with a measured comparison and one without must not read alike later, so the
    # basis is a field rather than an inference from whether some other field happens to be set.
    basis = "measured_comparison" if verdict else "host_assertion"
    # A partial adoption's own reservations are the conditions under which it stops holding.
    # Defaulting them away is how a scoped adoption becomes a full one over a few readings.
    reconsider = "New counterevidence or a change outside the evaluated scope"
    if verdict and verdict.get("reservations"):
        reconsider += ". " + " ".join(
            f"({i + 1}) {reason_}" for i, reason_ in enumerate(verdict["reservations"]))
    use_id = journal.record(MethodUse(
        ({"kind": "task", "id": task_id, "scope": str(journal.store.path)},),
        # Deliberately not MethodUse's own ``adoption: partial``: that field says which *parts*
        # of a method were used, and a scoped comparison says which *conditions* the evidence
        # covers. Two different axes, and writing one into the other would make a method used in
        # full read as a method used in part. The bound lives in the step's comparison and in
        # ``reconsider_when``.
        ({"method_version_ref": selected["record_id"], "scope": scope},),
        visible_evidence_refs=tuple(r["record_id"] for r in refs),
        reason=reason, parents=(prior_use_ref["record_id"],) if prior_use_ref else ()))
    use_ref = journal_ref(journal, use_id, source_id=source_id)
    step = dict(schema=STEP, task_id=task_id, question=question, branch_id="revision-resolution",
        operation="decision", reason=reason, input_refs=refs, output_refs=[use_ref],
        method_refs=[selected], accounting_refs=[], source_watermarks=[], supersedes=[],
        detail={"choice": {"adopt": "proceed", "retain": "reuse", "rollback": "reconsider"}[outcome],
            "alternatives": [{"branch_id": "candidate", "disposition": outcome, "reason": reason}],
            "basis_refs": refs, "adoption_basis": basis,
            **({"comparison": _comparison_summary(verdict)} if verdict else {}),
            "reconsider_when": reconsider})
    rid = record_content(journal, step, directory, source_id=source_id, source_kind=source_kind)
    return {"outcome": outcome, "selected_method_ref": selected, "use_ref": use_ref,
            "step_ref": journal_ref(journal, rid, source_id=source_id), "scope": scope,
            "default_changed": False, "execution": "not_performed",
            "adoption_basis": basis,
            "adoption": verdict["adoption"] if verdict else "not_assessed",
            "reservations": list(verdict["reservations"]) if verdict else []}
