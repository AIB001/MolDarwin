"""Frozen-view counterexamples and scoped revision decisions, no science runs."""
import json
import sqlite3
import pytest

from moldarwin.research import MethodEvaluation, TaskSplit
from moldarwin.research import continuation, evidence
from moldarwin.research.components import record_json
from moldarwin.research.evidence_refs import EvidenceError
from moldarwin.research.evidence_refs import file_identity, make_ref
from moldarwin.research.method_revision import resolve_method_revision
# ruff: noqa: F401, F811 -- these are pytest fixtures, resolved by name in test signatures
# rather than referenced, so every static check reads them as unused or redefined.
from test_method_revision import case as revision_case, save as save_revision
from test_research_continuation import case, save, step, checkpoint, publish


def test_frozen_view_reduces_actual_source_reads_with_identical_context(case, monkeypatch):
    cp = save(case, checkpoint(case, save(case, step(case[1]))))
    ws = publish(case)
    original, calls = evidence._source, []
    def traced(*args):
        calls.append(args[1]["source_id"])
        return original(*args)
    monkeypatch.setattr(evidence, "_source", traced)
    old = continuation.resume_research(ws, cp)
    assert len(calls) == 2
    calls.clear()
    assert continuation.resume_research(ws, cp, read_mode="frozen_view") == old
    assert len(calls) == 1
    case[2].write_text("Changed pause authority")
    assert continuation.resume_research(ws, cp, read_mode="frozen_view")["authority"]["state"] == "review_required"


@pytest.mark.parametrize("damage", ["source", "projected", "wal"])
def test_mid_read_change_cannot_return_clean_frozen_context(case, monkeypatch, damage):
    cp = save(case, checkpoint(case, save(case, step(case[1]))))
    ws = publish(case)
    original = continuation._check_frozen_view
    def changed(*args):
        if damage == "source":
            with sqlite3.connect(case[0].store.path) as db:
                db.execute("CREATE TABLE counterexample (n INTEGER)")
        elif damage == "projected":
            record = case[0].get(cp["record_id"])
            from pathlib import Path
            path = Path(record["path"])
            path.write_bytes(path.read_bytes() + b" ")
        else:
            from pathlib import Path
            Path(str(case[0].store.path) + "-wal").write_bytes(b"nonempty-wal")
        return original(*args)
    monkeypatch.setattr(continuation, "_check_frozen_view", changed)
    ctx = continuation.resume_research(ws, cp, read_mode="frozen_view")
    assert ctx["review_required"] and {"reason": "frozen_view_changed_during_read"} in ctx["issues"]


def test_live_source_uses_original_path_and_no_cross_call_cache(case, monkeypatch):
    cp = save(case, checkpoint(case, save(case, step(case[1]))))
    ws = publish(case)
    with sqlite3.connect(case[0].store.path) as db:
        key, value = db.execute("SELECT key,body FROM metadata ORDER BY key LIMIT 1").fetchone()
    document = json.loads(ws.read_text())
    document["sources"][0]["identity"] = {"kind": "journal_identity", "key": key, "value": json.loads(value)}
    ws.write_text(json.dumps(document))
    monkeypatch.setattr(continuation, "_check_frozen_view", lambda *a: pytest.fail("live view reused"))
    assert continuation.resume_research(ws, cp, read_mode="frozen_view") == continuation.resume_research(ws, cp)


@pytest.mark.parametrize("closed", [True, False])
def test_published_member_hash_and_unclosed_scope_fallback(case, monkeypatch, closed):
    root = case[3]
    payload = root / "member.txt"
    payload.write_text("released member")
    body = {"members": [{"member": "payload", "path": str(payload), **file_identity(payload), "visibility": "released"}]}
    foreign = {**make_ref("data", "bundle-1", body), "member": "payload"}
    manifest = root / "data.json"
    manifest.write_text(json.dumps({"schema": "moldarwin-artifact-manifest/1", "records": [
        {"record_id": "bundle-1", "record_type": "data_snapshot", "record": body, "visibility": "released"}]}))
    source = {"source_id": "data", "kind": "artifact_manifest", "location": str(manifest),
              "identity": {"kind": "snapshot_sha256", "value": file_identity(manifest)["sha256"]}}
    def workspace():
        ws = publish(case)
        config = json.loads(ws.read_text())
        config["sources"].append(source)
        ws.write_text(json.dumps(config))
        return ws
    s = save(case, step(foreign))
    marks = continuation.capture_watermarks(workspace(), source_ids=["data"]) if closed else []
    cp = save(case, checkpoint(case, s, source_watermarks=marks))
    ws = workspace()
    if not closed:
        monkeypatch.setattr(continuation, "_check_frozen_view", lambda *a: pytest.fail("unclosed source set reused"))
    assert continuation.resume_research(ws, cp, read_mode="frozen_view") == continuation.resume_research(ws, cp)
    payload.write_text("damaged member")
    ctx = continuation.resume_research(ws, cp, read_mode="frozen_view")
    assert ctx["review_required"] and any(i["reason"] == "member_identity_mismatch" for i in ctx["issues"])


def evaluation(case, *, measured=True, assessment_role="diagnostic"):
    j, p, directory, ref, _ = case
    data = record_json(j, {"actual_fixture_comparison": True}, directory, source_kind="fixture", bindings={"kind": "accounting"})
    split = j.record(TaskSplit(("fixture",), ("unrun-validation",), ("unrun-transfer",),
        {"fixture": "fixed", "unrun-validation": "not-released", "unrun-transfer": "not-released"}, "test decisions only"))
    subjects = tuple(r["record_id"] for r in p["candidate_version_refs"])
    comparators = (p["base_method_ref"]["record_id"],)
    if assessment_role == "independent_validation":
        from moldarwin.active.schema import canonical as _canonical
        binding = {
            "subjects": list(subjects),
            "comparators": list(comparators),
            "protocol_ref": data,
            "task_split_ref": split,
            "initial_conditions_ref": data,
        }
        policy = j.policy_version(
            TaskSplit(**j.get(split)),
            {"method_evaluation": json.loads(_canonical(binding))},
        )
        from moldarwin.research.schema import Artifact as _Artifact
        measured_path = directory / f"iv-measured-{policy[:12]}.json"
        measured_path.write_text(
            json.dumps({"independent_fixture_result": True, "policy": policy}),
            encoding="utf-8",
        )
        measured_obj = _Artifact(
            str(measured_path), **file_identity(measured_path),
            source_kind="fixture", role="independent_validation",
            bindings={"policy_id": policy, "task_id": "unrun-validation"},
        )
        measured_art = j.record(measured_obj)
        receipt = j.record_validation(
            policy, "unrun-validation", initial_configuration_sha256="not-released",
            evidence=(measured_art,), comparison={"warrant_delta": 12},
        )
        cost_unit = j.store.configuration()[0].cost_unit
        j.store.reserve_resource_execution("fixture-iv-acct", "e" * 64, 1, unit=cost_unit, provenance={"fixture": True})
        j.store.settle_resource_execution("fixture-iv-acct", measured_cost=1, receipt={"status": "ok", "value": 1})
        return ref(j.record(MethodEvaluation(
            subjects, comparators, data, split, data,
            (receipt,) if measured else (), ("fixture-iv-acct",) if measured else (),
            "independent_validation", "Fixture independent validation", "fixture scope",
        )))
    return ref(j.record(MethodEvaluation(subjects, comparators, data, split, data,
        (data,) if measured else (), (data,) if measured else (),
        assessment_role, "Fixture measured success", "fixture only")))


def resolve(case, **kw):
    j, p, directory, ref, _ = case
    checked = kw.pop("evaluation_ref") if "evaluation_ref" in kw else evaluation(case)
    return resolve_method_revision(j, ref(save_revision(case)), checked,
        directory=directory, source_id="fixture", source_kind="fixture", task_id="next-use",
        question="Which exact method should the next call use?", scope="fixture/local-next-use", reason="Fixture evidence", **kw)


def test_adopt_retain_and_rollback_append_uses_without_changing_prior(revision_case):
    j, p, _, _, _ = revision_case
    candidate = p["candidate_version_refs"][0]
    adopted = resolve(revision_case, outcome="adopt", candidate_ref=candidate)
    before = j.store.events()
    assert resolve(revision_case, outcome="adopt", candidate_ref=candidate) == adopted
    assert j.store.events() == before
    retained = resolve(revision_case, outcome="retain")
    rolled = resolve(revision_case, outcome="rollback", prior_use_ref=adopted["use_ref"], counterevidence_refs=p["problem_refs"])
    assert retained["selected_method_ref"] == rolled["selected_method_ref"] == p["base_method_ref"]
    assert j.get(adopted["use_ref"]["record_id"])["selected_methods"][0]["method_version_ref"] == candidate["record_id"]
    assert rolled["default_changed"] is False and j.store.actions() == []


def test_unevaluated_candidate_and_unattributed_rollback_are_rejected(revision_case):
    p = revision_case[1]
    with pytest.raises(ValueError, match="measured"):
        resolve(revision_case, outcome="adopt", candidate_ref=p["candidate_version_refs"][0], evaluation_ref=evaluation(revision_case, measured=False))
    with pytest.raises(ValueError, match="rollback needs"):
        resolve(revision_case, outcome="rollback")
    with pytest.raises(ValueError, match="exact revision candidate"):
        resolve(revision_case, outcome="adopt", candidate_ref=p["producer_method_ref"])


# -- a measured comparison binds the adoption it was computed for --------------------------


def _comparison(adoption="full"):
    """A comparison whose conclusion is ``adoption``, built from paired fixture observations."""
    from moldarwin.research.revision_score import Dimension, Family, compare_revision
    tasks = [f"fixture-{index}" for index in range(12)]
    better = dict.fromkeys(tasks, "admitted")
    worse = dict.fromkeys(tasks, "withheld")
    base, candidate = (worse, better) if adoption != "refused" else (better, worse)
    return compare_revision(
        dimensions=[(Dimension("warranted", Family.WARRANT), base, candidate)],
        assessment_role="independent_validation" if adoption == "full" else "diagnostic",
        base_catalogue_digest="a" * 64, candidate_catalogue_digest="a" * 64,
        declared_scope=["fixture scope"])


def test_an_adoption_without_a_comparison_is_recorded_as_a_host_assertion(revision_case):
    """The hazard is not an unjustified adoption; it is one that later reads like a justified one."""
    p = revision_case[1]
    result = resolve(revision_case, outcome="adopt", candidate_ref=p["candidate_version_refs"][0])
    assert result["adoption_basis"] == "host_assertion"
    assert result["adoption"] == "not_assessed"
    step_body = revision_case[0].get(result["step_ref"]["record_id"])
    detail = json.loads(revision_case[0].artifact_path(
        __import__("moldarwin.research.schema", fromlist=["Artifact"]).Artifact(**step_body)
    ).read_text("utf-8"))["detail"]
    assert detail["adoption_basis"] == "host_assertion"
    assert "comparison" not in detail


def test_a_measured_comparison_is_carried_into_the_decision_step(revision_case):
    p = revision_case[1]
    comparison = _comparison("full")
    assert comparison.adoption.value == "full"
    iv_eval = evaluation(revision_case, assessment_role="independent_validation")
    result = resolve(revision_case, outcome="adopt", candidate_ref=p["candidate_version_refs"][0],
                     evaluation_ref=iv_eval, comparison=comparison)
    assert result["adoption_basis"] == "measured_comparison"
    assert result["adoption"] == "full"
    step_body = revision_case[0].get(result["step_ref"]["record_id"])
    from moldarwin.research.schema import Artifact
    detail = json.loads(revision_case[0].artifact_path(
        Artifact(**step_body)).read_text("utf-8"))["detail"]
    assert detail["comparison"]["adoption"] == "full"
    assert detail["comparison"]["dimensions"][0]["verdict"] == "better"


def test_a_candidate_the_comparison_refused_cannot_be_adopted(revision_case):
    """The gate the resolution did not have: it checked existence, never the verdict."""
    p = revision_case[1]
    with pytest.raises(ValueError, match="against a measured refusal"):
        resolve(revision_case, outcome="adopt", candidate_ref=p["candidate_version_refs"][0],
                comparison=_comparison("refused"))


def test_a_diagnostic_comparison_cannot_be_turned_into_an_adoption(revision_case):
    p = revision_case[1]
    with pytest.raises(ValueError, match="diagnostic_only"):
        resolve(revision_case, outcome="adopt", candidate_ref=p["candidate_version_refs"][0],
                comparison=_comparison("diagnostic"))


def test_a_diagnostic_evaluation_cannot_hide_behind_an_independent_validation_comparison(revision_case):
    """Cross-record binding: comparison.assessment_role must match MethodEvaluation.assessment_role."""
    p = revision_case[1]
    diag_eval = evaluation(revision_case, assessment_role="diagnostic")
    with pytest.raises(ValueError, match="disagrees with referenced MethodEvaluation"):
        resolve(revision_case, outcome="adopt", candidate_ref=p["candidate_version_refs"][0],
                evaluation_ref=diag_eval, comparison=_comparison("full"))


def test_a_persisted_comparison_artifact_ref_is_verified_and_linked_in_basis_refs(revision_case):
    j, p, directory, ref, _ = revision_case
    comparison = _comparison("full")
    comp_id = record_json(j, comparison.as_dict(), directory, source_kind="fixture")
    comp_ref = ref(comp_id)
    iv_eval = evaluation(revision_case, assessment_role="independent_validation")
    result = resolve(revision_case, outcome="adopt", candidate_ref=p["candidate_version_refs"][0],
                     evaluation_ref=iv_eval, comparison=comp_ref)
    assert result["adoption_basis"] == "measured_comparison"
    from moldarwin.research.schema import Artifact
    step_body = j.get(result["step_ref"]["record_id"])
    step_doc = json.loads(j.artifact_path(Artifact(**step_body)).read_text("utf-8"))
    assert comp_ref in step_doc["detail"]["basis_refs"]


def test_a_bounded_adoption_records_its_reservations_where_a_reader_will_meet_them(revision_case):
    from moldarwin.research.revision_score import Dimension, Family, compare_revision
    tasks = [f"fixture-{index}" for index in range(12)]
    comparison = compare_revision(
        dimensions=[(Dimension("warranted", Family.WARRANT),
                     dict.fromkeys(tasks, "withheld"),
                     dict.fromkeys(tasks, "admitted")),
                    (Dimension("wall", Family.COST, minimum_gain=1.0, unit="s",
                               minimum_gain_source="fixture"),
                     dict.fromkeys(tasks, 10.0), dict.fromkeys(tasks, 10.0))],
        assessment_role="independent_validation",
        base_catalogue_digest="a" * 64, candidate_catalogue_digest="a" * 64,
        declared_scope=["fixture scope"])
    assert comparison.adoption.value == "scoped" and comparison.reservations
    iv_eval = evaluation(revision_case, assessment_role="independent_validation")
    result = resolve(revision_case, outcome="adopt",
                     candidate_ref=revision_case[1]["candidate_version_refs"][0],
                     evaluation_ref=iv_eval, comparison=comparison)
    from moldarwin.research.schema import Artifact
    step_body = revision_case[0].get(result["step_ref"]["record_id"])
    detail = json.loads(revision_case[0].artifact_path(
        Artifact(**step_body)).read_text("utf-8"))["detail"]
    assert "not established" in detail["reconsider_when"]
    assert detail["comparison"]["adoption"] == "scoped"
    # The bound is the comparison's, not MethodUse's `adoption: partial`, which means
    # "used some parts of the method" and is a different axis entirely.
    use = revision_case[0].get(result["use_ref"]["record_id"])
    assert "adoption" not in use["selected_methods"][0]


@pytest.mark.parametrize("bad", [
    {"schema": "other/1"},
    {"adoption": "full"},
    "full",
    7,
    {"schema": "moldarwin-revision-comparison/1", "adoption": "x", "outcome": "adopt"},
    # Self-contradictory adoption vs outcome (previously bypassed the gate).
    {
        "schema": "moldarwin-revision-comparison/1",
        "adoption": "refused",
        "outcome": "adopt",
        "gain": "none",
        "assessment_role": "independent_validation",
        "catalogue_digest": "a" * 64,
        "reservations": ["regressed"],
        "dimensions": [{"name": "w", "family": "warrant", "verdict": "worse", "effect": -12.0, "p_value": 0.0005}],
    },
    # Forged diagnostic lane claiming full adoption.
    {
        "schema": "moldarwin-revision-comparison/1",
        "adoption": "full",
        "outcome": "adopt",
        "gain": "quality",
        "assessment_role": "diagnostic",
        "catalogue_digest": "a" * 64,
        "reservations": [],
        "dimensions": [{"name": "w", "family": "warrant", "verdict": "better", "effect": 12.0, "p_value": 0.0005}],
    },
    # Forged full adoption hiding a quality regression.
    {
        "schema": "moldarwin-revision-comparison/1",
        "adoption": "full",
        "outcome": "adopt",
        "gain": "both",
        "assessment_role": "independent_validation",
        "catalogue_digest": "a" * 64,
        "reservations": [],
        "dimensions": [
            {"name": "w", "family": "warrant", "verdict": "worse", "effect": -10.0, "p_value": 0.002},
            {"name": "c", "family": "cost", "verdict": "better", "effect": 5.0, "p_value": 0.002},
        ],
    },
    # Incomplete dict missing dimensions/catalogue_digest (must raise ValueError, not KeyError).
    {
        "schema": "moldarwin-revision-comparison/1",
        "adoption": "full",
        "outcome": "adopt",
        "assessment_role": "independent_validation",
    },
])
def test_a_lookalike_comparison_is_refused_rather_than_read(revision_case, bad):
    p = revision_case[1]
    iv_eval = evaluation(revision_case, assessment_role="independent_validation")
    with pytest.raises(ValueError):
        resolve(revision_case, outcome="adopt", candidate_ref=p["candidate_version_refs"][0],
                evaluation_ref=iv_eval, comparison=bad)
