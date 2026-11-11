"""Replay the declared decision rule against the artifact about to be submitted.

**The measurement.** Two submissions were already mathematically unable to pass at submission time
and nobody noticed. Not nearly-failing and not failing after review: already failed against the
rule the work itself had declared, at the moment it was handed in.

**Why that is cheap to catch here.** The rule is already first-class data.
``research/evaluation_contract.py`` metrics carry an ``operator`` in ``{le, lt, ge, gt, eq}`` and a
finite numeric ``threshold``, refuse anything else -- *"finite numeric threshold and fixed
comparator required"* -- and pin ``missing_policy`` to the single value ``"insufficient"`` so that
*"missing values cannot be dropped, imputed or passed"*. ``evaluate_contract`` replays the rule
against observed inputs and returns a per-metric ``observed`` value with a status, and ``_aggregate``
orders precedence so that *a missing input can never aggregate into a pass*. The replay exists, it
is read-only, and it is classified FREE on the tool surface as ``etalon_method_evaluate``. What was
missing is anybody calling it **before** the hand-in.

**Why a hook and not a refusal, with one exception.** A failing rule is visible and recoverable in
the same session: the numbers are in hand, the rule is in hand, and either the work or the claim can
change before anything is recorded. That is the recoverable half of the criterion. The exception is
narrow and is the only ``block`` in this package: when the caller supplies a **declared outcome in
the contract's own vocabulary** and the replay contradicts it, the hook blocks, because a declared
``criteria_passed`` recorded against a replayed ``criteria_failed`` is not a judgement anybody can
recover later -- it is the two submissions above, written down. ``research_decision.py`` already
refuses exactly this shape for a decision record (*"unsupported judgment conflicts with verified
evaluation status"*); this extends the same refusal to the surface where the claim is still prose.

A free-text conclusion is never blocked. Classifying prose as a positive finding is a judgement, and
a judgement that blocks is a judgement nobody can argue with at the point it acts. The hook shows
the difference and leaves the decision where it belongs.

**Two sources for the rule, and the second one has just arrived.** Until this round the comparator
and threshold lived only in an ``etalon-evaluation-contract/1`` and were *unrepresentable* in the
journal's ``evaluation_plan`` step: ``research/continuation.py``'s ``_fields`` is an exact-field
check in both directions, ``research/composition.py`` validated plan metrics against exactly
``("name", "family", "unit", "denominator", "missing_policy")`` with no optional tuple, and the
contract/plan cross-check projected only those same five keys. So the rule had to be handed in.

``research/decision_rule.py`` now makes it representable: ``RULE_FIELDS`` is
``("operator", "threshold", "threshold_evidence")``, all three or none, with the third satisfying
hard constraint 5 -- a threshold without a provenance tag is a number of unstated origin.
:func:`plan_declared_rules` reads the rule through that module's own ``plan_rules`` and
:func:`replay_plan_rule` replays it through its own ``replay``, both **lazily imported and both
degrading to a stated absence**. That is deliberate rather than timid: the module is owned by
another workstream, this hook must not hard-depend on a signature still settling, and a hook that
crashes because a field moved is worse than a hook that says the rule was not declared.

One integration point remains genuinely open, and it is a different proposal:

* :data:`PLAN_RULES_DIGEST_FIELD` and :func:`rule_identity_from_plan` -- the architecture review's
  P1(a), which binds the *contract's* identity into the plan via
  ``evaluation_contract.evaluation_rules_digest``, deliberately stable under a change of observed
  inputs. That did **not** land; the representation that landed carries the rule itself rather than
  a reference to one. Until a plan can name a contract, this hook cannot check that the contract it
  was handed is the contract the plan declared, and it reports that as ``not_declared`` rather than
  assuming they match.
"""

from __future__ import annotations

from typing import Any

from etalon.hooks.session import Interruption, bounded_text, quiet

HOOK = "rule_replay"

#: The optional ``evaluation_plan`` metric field that would carry the declared rule's identity. The
#: value is ``evaluation_contract.evaluation_rules_digest(contract)``, which is deliberately stable
#: under a change of observed inputs, so one declared rule can be replayed against new evidence
#: without its identity moving. **Not representable today**: see the module docstring.
PLAN_RULES_DIGEST_FIELD = "rules_digest"

#: The three fields that make a plan metric carry its own numeric rule, as
#: ``research/decision_rule.RULE_FIELDS`` declares them. Restated here, rather than imported at
#: module scope, so this hook reads them without importing a module another workstream owns; the
#: names are compared against that tuple at call time in :func:`plan_declared_rules`, so a drift
#: between the two is reported instead of being silently honoured.
PLAN_OPERATOR_FIELD = "operator"
PLAN_THRESHOLD_FIELD = "threshold"
PLAN_THRESHOLD_EVIDENCE_FIELD = "threshold_evidence"
PLAN_RULE_FIELDS = (PLAN_OPERATOR_FIELD, PLAN_THRESHOLD_FIELD, PLAN_THRESHOLD_EVIDENCE_FIELD)

#: Replayed statuses that mean the rule has spoken against the work. ``insufficient`` is
#: deliberately absent: it means no tool reported the quantity, which is a different claim from a
#: rule that was applied and failed, and ``missing_policy: "insufficient"`` exists precisely to keep
#: the two apart.
RULE_SAYS_NO = ("criteria_failed", "incomparable")

#: A declared outcome in the contract's own vocabulary. Supplying one is what makes a contradiction
#: comparable, and therefore blockable.
DECLARED_STATUSES = ("criteria_passed", "criteria_failed", "insufficient", "incomparable")

#: Claim vocabulary, as ``research/decision_rule.CLAIMS`` declares it -- ``supported`` /
#: ``not_supported`` / ``not_claimed`` -- plus ``research_decision.py``'s older ``unsupported`` as an
#: alias, because both spellings appear in the tree and a claim nobody could parse would be read as
#: prose and silently exempted from the one case this hook blocks.
#:
#: ``not_claimed`` maps to nothing on purpose. It is the honest default: a recorded comparison need
#: not claim anything, and a claim of nothing cannot contradict a rule.
DECLARED_JUDGMENTS = {
    "supported": "criteria_passed",
    "not_supported": "criteria_failed",
    "unsupported": "criteria_failed",
}


def rule_identity_from_plan(plan_detail: Any) -> tuple[str | None, str]:
    """The declared rule's identity, read from an ``evaluation_plan`` step's metrics.

    **Integration point for the workstream that owns ``src/etalon/research/``.** Today every plan
    metric is validated against exactly five fields with no optional tuple, so
    :data:`PLAN_RULES_DIGEST_FIELD` cannot appear and this returns ``(None, reason)``. The function
    is written to read the field the moment it is accepted, and to agree with itself in the
    meantime: a plan that does carry the field (because the validator has been extended) is read
    here with no further change.

    Returns:
        ``(digest, basis)``. The digest is ``None`` whenever no single rule identity is declared,
        and the basis says which case that was -- absent, or declared inconsistently across metrics,
        which is a different problem and must not be reported as absence.
    """

    metrics = plan_detail.get("metrics") if isinstance(plan_detail, dict) else None
    if not isinstance(metrics, (list, tuple)) or not metrics:
        return None, "not_declared: the step carries no evaluation_plan metrics"
    declared = {
        metric[PLAN_RULES_DIGEST_FIELD]
        for metric in metrics
        if isinstance(metric, dict) and metric.get(PLAN_RULES_DIGEST_FIELD)
    }
    if not declared:
        return None, (
            f"not_declared: no plan metric carries {PLAN_RULES_DIGEST_FIELD!r}. The "
            "evaluation_plan metric validator now accepts decision_rule.RULE_FIELDS "
            "(operator, threshold, threshold_evidence) as an optional tuple, so the rule "
            "itself is representable in the plan; this field is not among them, so the "
            "rule's identity still lives only in the evaluation contract."
        )
    if len(declared) > 1:
        return None, (
            f"declared_inconsistently: {len(declared)} distinct {PLAN_RULES_DIGEST_FIELD} values "
            "across the plan's metrics. One plan declaring two rules is not one rule with no "
            "identity, and the two must not be reported alike."
        )
    return declared.pop(), f"measured_here: {PLAN_RULES_DIGEST_FIELD} on every plan metric"


def plan_declared_rules(plan_detail: Any) -> tuple[list[dict[str, Any]] | None, str]:
    """The numeric rule the plan itself declares, read through ``research/decision_rule.py``.

    Delegates to that module's ``plan_rules`` rather than re-reading the metric fields here, so
    there is one validator for what counts as a declared rule. The field names in
    :data:`PLAN_RULE_FIELDS` are checked against its ``RULE_FIELDS`` on the way through: if the two
    ever disagree, that is reported as a drift rather than resolved in this hook's favour, because a
    hook that quietly read four fields where the validator required three would accept half a rule.

    Returns ``(rules, basis)``. ``rules`` is ``None`` whenever no rule is declared or the module is
    unavailable, and the basis says which -- never one standing in for the other.
    """

    if not isinstance(plan_detail, dict):
        return None, "not_declared: no evaluation_plan step detail was supplied"
    try:
        from etalon.research.decision_rule import RULE_FIELDS, plan_rules
    except Exception as error:  # noqa: BLE001
        return None, (
            f"not_taken: research.decision_rule is unavailable ({type(error).__name__}), so the "
            "plan's own rule could not be read. An evaluation contract can still be replayed."
        )
    if tuple(RULE_FIELDS) != PLAN_RULE_FIELDS:
        return None, (
            f"not_taken: this hook reads {PLAN_RULE_FIELDS} and the validator requires "
            f"{tuple(RULE_FIELDS)}. Reading a rule under the wrong field set would accept a "
            "partial rule, so the rule is reported as not read."
        )
    try:
        rules = plan_rules(plan_detail)
    except Exception as error:  # noqa: BLE001
        return None, f"refused: the plan's declared rule is invalid ({type(error).__name__}: {error})"
    if not rules:
        return None, (
            "not_declared: no plan metric carries operator, threshold and threshold_evidence. The "
            "three are all-or-none, so a metric with none of them declares no rule rather than "
            "half a rule."
        )
    return rules, (
        "measured_here: research.decision_rule.plan_rules over the evaluation_plan metrics; "
        f"{len(rules)} metric(s) declare a rule"
    )


def replay_plan_rule(plan_detail: Any, observed: Any) -> tuple[dict[str, Any] | None, str]:
    """Replay the plan's own declared rule against supplied observations.

    The second of the two sources, and the cheaper one: it needs no contract, no workspace and no
    recorded refs -- only the plan the work was done under and the numbers in hand. Observations are
    ``{"name", "value", "evidence"}`` rows, every number carrying its provenance, and an absent
    value yields ``insufficient`` for that metric rather than a pass or a substituted figure.
    """

    rules, basis = plan_declared_rules(plan_detail)
    if rules is None:
        return None, basis
    if observed is None:
        return None, (
            "not_taken: the plan declares a rule and no observations were supplied, so there is "
            "nothing to replay it against. A rule with no numbers is not a pass."
        )
    try:
        from etalon.research.decision_rule import replay

        return replay(rules, observed), basis
    except Exception as error:  # noqa: BLE001
        return None, f"refused: the replay was rejected ({type(error).__name__}: {error})"


def _failing(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("metrics")
    if not isinstance(rows, (list, tuple)):
        return []
    return [
        {
            "name": row.get("name"),
            "family": row.get("family"),
            "observed": row.get("observed"),
            "operator": row.get("operator"),
            "threshold": row.get("threshold"),
            "unit": row.get("unit"),
            "status": row.get("status"),
            "reason": row.get("reason"),
        }
        for row in rows
        if isinstance(row, dict) and row.get("status") in RULE_SAYS_NO
    ]


def declared_outcome(declared: Any) -> tuple[str | None, str]:
    """Normalise a declared outcome into the contract's vocabulary, or say it is prose.

    Three forms are comparable: a status in :data:`DECLARED_STATUSES`, a judgment in
    :data:`DECLARED_JUDGMENTS`, or nothing. Anything else -- including a sentence that reads like a
    positive finding -- is prose, and prose is surfaced rather than blocked.
    """

    if declared is None or declared == "":
        return None, "not_declared: no outcome was declared in the contract's vocabulary"
    text = str(declared).strip().lower()
    if text in DECLARED_STATUSES:
        return text, "measured_here: declared in the evaluation contract's own status vocabulary"
    if text in DECLARED_JUDGMENTS:
        return DECLARED_JUDGMENTS[text], (
            "measured_here: declared as a research_decision judgment, mapped to the contract "
            "status it asserts"
        )
    return None, (
        "prose: the declared outcome is free text. It is shown beside the replay and never "
        "blocked, because classifying a sentence as a positive finding is a judgement and a "
        "judgement that blocks is one nobody can argue with where it acts."
    )


def assess(
    *,
    contract: dict[str, Any] | None = None,
    contract_ref: dict[str, Any] | None = None,
    workspace: str | None = None,
    declared: Any = None,
    conclusion: str = "",
    plan_detail: Any = None,
    observed: Any = None,
) -> Interruption:
    """Replay the rule and report the difference between it and the claim.

    Args:
        contract: An ``etalon-evaluation-contract/1`` object, inline. Exactly one of this and
            ``contract_ref`` is required by ``evaluate_contract`` itself.
        contract_ref: An evidence ref to a recorded contract.
        workspace: The published-evidence workspace the refs resolve against.
        declared: The outcome being claimed, in the contract's status vocabulary or
            ``research_decision``'s judgment vocabulary. Supplying one makes a contradiction
            comparable and is the only way this hook can block.
        conclusion: The free-text conclusion, shown beside the replay. Never blocked on.
        plan_detail: The ``evaluation_plan`` step detail. When it declares a rule in
            ``research/decision_rule.py``'s fields, that rule is replayed against ``observed`` and
            no contract is needed.
        observed: ``[{"name", "value", "evidence"}, ...]`` for the plan's ruled metrics. Every
            number carries its provenance and an explicit ``None`` means not obtained, which
            replays as ``insufficient`` rather than as a pass.
    """

    source = "evaluation_contract"
    if contract is None and contract_ref is None:
        # The plan's own rule, which is the cheaper source: no contract, no workspace, no refs.
        plan_report, plan_basis = replay_plan_rule(plan_detail, observed)
        if plan_report is None:
            return quiet(
                HOOK,
                "no declared numeric rule could be replayed: no evaluation contract was supplied "
                "and the plan declares none that could be replayed against numbers. A submission "
                "whose rule exists only as prose cannot be replayed by anything, which is the "
                "state two earlier submissions were handed in from.",
                plan_rule=plan_basis,
                plan_rule_identity=rule_identity_from_plan(plan_detail)[1],
            )
        rules = {row["name"]: row for row in (plan_declared_rules(plan_detail)[0] or ())}
        source = "evaluation_plan"
        report = {
            "status": plan_report["status"],
            # Rule fields first, replay outputs second, so a row carries the comparator and
            # threshold it was judged against and not only the verdict.
            "metrics": [{**rules.get(row["name"], {}), **row} for row in plan_report["metrics"]],
            "rules_digest": None,
            "families": None,
            "issues": (),
        }
    else:
        try:
            from etalon.research.evaluation_contract import evaluate_contract

            # Keywords throughout: ``evaluate_contract`` is wrapped by ``bounded_read``, and a
            # positional call is a call against the decorator's signature rather than the
            # function's.
            report = evaluate_contract(
                workspace=workspace, contract=contract, contract_ref=contract_ref
            )
        except Exception as error:  # noqa: BLE001
            return quiet(
                HOOK,
                f"the declared rule could not be replayed, so no comparison was made "
                f"({type(error).__name__}: {error})",
            )

    replayed = report.get("status")
    failing = _failing(report)
    normalised, declared_basis = declared_outcome(declared)
    plan_identity, plan_basis = rule_identity_from_plan(plan_detail)
    rules_digest = report.get("rules_digest")

    finding = {
        "rule_source": source,
        "replayed_status": replayed,
        "rules_digest": rules_digest,
        "families": report.get("families"),
        "metrics_the_rule_refused": failing,
        "metrics_examined": len(report.get("metrics") or ()),
        "issues": list(report.get("issues") or ())[:8],
        "declared_outcome": normalised,
        "declared_outcome_basis": declared_basis,
        "conclusion": bounded_text(conclusion, limit=1024) if conclusion else None,
        "plan_declares_rule_identity": plan_identity,
        "plan_rule_identity_basis": plan_basis,
        "plan_identity_matches_replayed_rule": (
            None if plan_identity is None else plan_identity == rules_digest
        ),
        "freeze_status": report.get("freeze_status"),
        "replay_establishes": {
            "independent_validation": report.get("independent_validation"),
            "scientific_truth": report.get("scientific_truth"),
        },
    }
    evidence = {
        "replay": (
            "measured_here: research.evaluation_contract.evaluate_contract, read-only, over the "
            "contract's declared inputs; denominator is metrics_examined"
            if source == "evaluation_contract"
            else "measured_here: research.decision_rule.replay over the plan's declared rule and "
            "the supplied observations; denominator is metrics_examined"
        ),
        "rule": (
            "declared: operator and threshold come from the contract and are refused unless the "
            "comparator is fixed and the threshold is a finite number"
        ),
        "declared_outcome": declared_basis,
        "plan_rule_identity": plan_basis,
    }

    if replayed not in RULE_SAYS_NO:
        if normalised == "criteria_passed" and replayed == "insufficient":
            return Interruption(
                hook=HOOK,
                status="interrupt",
                headline=(
                    "the declared rule could not be applied -- a quantity it needs was not "
                    "reported -- and the claim is that it passed"
                ),
                finding=finding,
                evidence=evidence,
                alternatives=(
                    "insufficient is not a failure and is not a pass. missing_policy is pinned to "
                    "'insufficient' precisely so a missing input cannot aggregate into either.",
                    "Report the quantity, or restate the claim as not established. Hard constraint "
                    "7: a quantity that cannot be counted is reported as not taken.",
                ),
            )
        return quiet(
            HOOK,
            f"the declared rule replays as {replayed!r}, which does not contradict the claim",
            **finding,
        )

    first = failing[0] if failing else {}
    rule_text = (
        f"{first.get('name')}: observed {first.get('observed')} against the declared rule "
        f"{first.get('operator')} {first.get('threshold')} {first.get('unit') or ''}".strip()
        if first
        else f"the aggregate replays as {replayed!r}"
    )

    if normalised == "criteria_passed":
        return Interruption(
            hook=HOOK,
            status="block",
            headline=(
                f"this submission is already unable to pass its own declared rule, and the "
                f"declared outcome says it passed -- {rule_text}"
            ),
            finding=finding,
            evidence=evidence,
            alternatives=(
                "Change the work, or change the claim. The rule was declared before the evidence "
                "and its identity is stable under new observations, so replaying it against better "
                "numbers does not move it.",
                "research_decision already refuses this shape for a recorded decision: a judgment "
                "of 'supported' against a replayed status of criteria_failed raises. This is the "
                "same refusal one step earlier, where it is still free to fix.",
                "If the rule itself is wrong, say so and declare a new one. That is a decision with "
                "a reason attached and is a different act from submitting against the old one.",
            ),
        )

    return Interruption(
        hook=HOOK,
        status="interrupt",
        headline=(
            f"the declared rule already refuses this artifact at submission time -- {rule_text}"
        ),
        finding=finding,
        evidence=evidence,
        alternatives=(
            "Read metrics_the_rule_refused before submitting. Two earlier submissions were "
            "mathematically unable to pass at the moment they were handed in, which is the "
            "measurement this hook exists for.",
            "A cost criterion passing does not erase a quality criterion failing: the aggregate "
            "orders incomparable > criteria_failed > insufficient > criteria_passed for that "
            "reason, and families[*] says which half spoke.",
            "No outcome was declared in the contract's vocabulary, so nothing is blocked. Declaring "
            "one is what makes a contradiction checkable rather than readable.",
        ),
    )


__all__ = [
    "DECLARED_JUDGMENTS",
    "DECLARED_STATUSES",
    "HOOK",
    "PLAN_OPERATOR_FIELD",
    "PLAN_RULES_DIGEST_FIELD",
    "PLAN_RULE_FIELDS",
    "PLAN_THRESHOLD_EVIDENCE_FIELD",
    "PLAN_THRESHOLD_FIELD",
    "RULE_SAYS_NO",
    "assess",
    "declared_outcome",
    "plan_declared_rules",
    "replay_plan_rule",
    "rule_identity_from_plan",
]
