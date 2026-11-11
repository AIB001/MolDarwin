"""The specification half of an evaluation contract, for the host to read before working.

Why this exists. Measured on an external benchmark (SMDD-Bench, 2026-11-09): an agent
computed exactly the right quantity, saw that its candidate matched 3 of the reference's 6
features, saw that number twice across turns, and submitted -- because the threshold was
never stated anywhere it could read. Two further submissions were already *mathematically*
unable to pass at hand-in, because the metric was a Jaccard over sets and therefore
punished features the reference lacked, and nothing told the agent that extras cost
anything. Those are not chemistry failures. They are a harness that knew the acceptance
criterion and did not say it.

The line this module holds: **publish the specification, never the oracle.**

Published here (the specification): which quantities are judged, each one's operator and
threshold, the Evidence provenance of that threshold, what direction the metric punishes,
the status vocabulary, how statuses aggregate, and the rules digest that identifies the
rule set. A host can rebuild this criterion from its own legal inputs and check itself
against it while it works.

NOT published here (the oracle): the published originals' bytes, any recorded result, and
any verdict. `evaluate_contract` is the only thing that reaches those, and this module does
not call it -- the absence of that call is the enforcement, not a promise in this docstring.
A host that could ask for the verdict would be tuning against one fixed draw of it, which
`RSI_REWARD.md` argues no split of a benchmark protects against; a host that knows the
written criterion is in the position of a scientist who read the acceptance criteria, which
is the position we want it in.
"""
from __future__ import annotations

from typing import Any

from etalon.research.evaluation_contract import (
    FAMILIES,
    PROVENANCE,
    STATUSES,
    THRESHOLD_EVIDENCE_NOT_RECORDED,
    evaluation_rules_digest,
    validate_evaluation_contract,
)
from etalon.research.read_scope import bounded_read
from etalon.runtime.files import EvidenceError

#: Which direction each operator punishes, in the words a host needs to act on. A Jaccard
#: threshold with `gt` punishes BOTH a missing feature and an extra one, because the extra
#: enters the union -- the clause whose absence cost two SMDD submissions their run.
_PUNISHES = {
    "le": "a value above the threshold",
    "lt": "a value at or above the threshold",
    "ge": "a value below the threshold",
    "gt": "a value at or below the threshold",
    "eq": "any value other than the threshold, in either direction",
}

#: What each threshold provenance tag licenses a host to do about the bar. This is the half
#: of the criterion that is not the number: a host that knows only `> 0.75` cannot tell a
#: physical constant from a figure somebody picked, and the two call for different work.
#: Deciding how hard to argue with a bar is design judgement, which is on the measured
#: good-at side; the harness's job is to hand over the input, not to make the call.
#: `not_recorded` is listed because a host may meet it on an unvalidated contract, and it is
#: separated from the four tags rather than appended to them.
_THRESHOLD_PROVENANCE = {
    "vocabulary": list(PROVENANCE),
    "measured_here": ("measured in this project; the run, probe or ADR is nameable. Arguing "
                      "with the bar means arguing with that measurement."),
    "measured_in_an_asset": ("measured inside a vendored asset at its pinned commit, not by "
                             "ETALON and not published. Re-derivable by re-running the "
                             "pinned tree, which is a weaker claim than having run it here."),
    "literature": "published and citable, with a year. Contestable only on the literature.",
    "convention": ("somebody chose this number. No measurement stands behind it, and it may "
                   "not be presented as one (CLAUDE.md constraint 5). A result that misses a "
                   "convention bar is not thereby established as wrong -- but the bar is the "
                   "declared criterion and missing it is still criteria_failed."),
    THRESHOLD_EVIDENCE_NOT_RECORDED: ("not a provenance value: nobody recorded where this "
                                      "number came from. Only reachable on a contract that "
                                      "did not go through validation."),
    "in_the_rules_digest": ("yes. Relabelling a threshold's provenance changes rules_digest, "
                            "so it is a new rule identity rather than an edit to this one."),
}

#: Worst status wins, which is why a cost success never erases a quality failure. Mirrors
#: `evaluation_contract._aggregate`'s precedence exactly; `test_contract_spec` pins the
#: agreement against that function so this listing cannot drift into folklore. Note that a
#: genuine failure outranks `insufficient`: an answer known to be wrong is worse news than
#: one that could not be judged.
_PRECEDENCE = ("incomparable", "criteria_failed", "insufficient", "criteria_passed")

#: `_aggregate` returns this when there are no statuses at all, and it is deliberately NOT
#: in `STATUSES`: a contract that judged nothing has not passed.
_NO_STATUSES = "not_declared"


def _metric_spec(metric: dict[str, Any]) -> dict[str, Any]:
    operator = metric.get("operator")
    spec = {
        "name": metric.get("name"),
        "family": metric.get("family"),
        "unit": metric.get("unit"),
        # `measure` says WHAT is computed -- {operation: value|difference|abs_difference|
        # ratio, left, right}. Publishing the threshold without it would tell a host the
        # bar and not the quantity, which is half a criterion.
        "measure": metric.get("measure"),
        "denominator": metric.get("denominator"),
        "denominator_selector": metric.get("denominator_selector"),
        # What happens when the value is absent, which a host otherwise discovers at
        # scoring time. 'insufficient' is not a pass.
        "missing_policy": metric.get("missing_policy"),
        "operator": operator,
        "threshold": metric.get("threshold"),
        "threshold_evidence": metric.get("threshold_evidence"),
        "punishes": _PUNISHES.get(operator),
    }
    if operator is None:
        spec["punishes"] = None
        spec["declared"] = False
        spec["note"] = ("This metric declares no operator or threshold, so the contract "
                        "does not say what would pass. Treat it as unspecified rather than "
                        "as satisfied, and ask for the rule before relying on a result.")
    else:
        spec["declared"] = True
    if metric.get("threshold") is not None and metric.get("threshold_evidence") is None:
        # Unreachable for a validated contract: the metric schema now requires the tag, in
        # the same vocabulary the `evaluation_plan` step has required since
        # `research/decision_rule.py` landed. The branch stays because `specification` can be
        # called with `validate=False` on a contract read from elsewhere, and because a host
        # reading a threshold deserves to know whether anyone recorded where the number came
        # from. `not_recorded` is not a fifth provenance value; it is the absence of one.
        spec["threshold_evidence"] = THRESHOLD_EVIDENCE_NOT_RECORDED
        spec["threshold_evidence_note"] = (
            "This contract records no provenance for the threshold, so the number cannot be "
            "told apart from a convention presented as a measurement (CLAUDE.md constraint "
            "5). A contract built through build_evaluation_contract cannot reach this state; "
            "treat this bar as given, not as established, and ask for its origin.")
    return spec


@bounded_read
def specification(contract: dict[str, Any] | None = None, *, contract_ref: dict | None = None,
                  workspace: Any = None, entry: Any = None, read_context: Any = None,
                  validate: bool = True) -> dict[str, Any]:
    """The readable criterion: what will be judged and by what rule. No verdict.

    Supply exactly one of `contract` (the host already holds the declaration) or
    `contract_ref` (it holds only a pointer). The ref path is the one that matters: in the
    case this module exists for, the criterion lived with the grader and the agent never
    held the contract at all, so a tool that could only project a dict the caller already
    had would not have helped it.

    **Only the contract's own ref is resolved.** `contract["inputs"][*]["ref"]` is never
    read -- the contract is the specification, while its inputs and their results are the
    oracle, and `evaluate_contract` is the only function that may reach those.
    `test_contract_spec` pins the single read by counting calls, not by reading this prose.

    A contract is capped at 64 KiB by its own validator while the evidence reader returns
    32 KiB in one page, so a larger one comes back incomplete and is refused rather than
    paged: a specification assembled from fragments is one nobody can check.

    `validate=False` is for a caller that has already validated an inline payload; it never
    relaxes what is published, and it is ignored on the ref path.
    """

    if (contract is None) == (contract_ref is None):
        raise EvidenceError("supply exactly one contract or contract_ref")
    if contract_ref is not None:
        from etalon.research.entry import resolve_read_workspace
        from etalon.research.evidence_refs import validate_ref
        from etalon.research.improvement import read_material

        resolved = resolve_read_workspace(workspace, entry=entry, read_context=read_context)
        material = read_material(resolved, validate_ref(contract_ref))
        if not material["complete"] or not isinstance(material["content"], dict):
            raise EvidenceError("evaluation contract unavailable or incomplete; the "
                                "specification cannot be recovered from a fragment")
        contract, validate = material["content"], True
    payload = validate_evaluation_contract(contract) if validate else contract
    metrics = [_metric_spec(m) for m in (payload.get("metrics") or [])]
    undeclared = [m["name"] for m in metrics if not m["declared"]]
    return {
        "schema": "etalon-evaluation-specification/1",
        "task_id": payload.get("task_id"),
        "scope": payload.get("scope"),
        "rules_digest": evaluation_rules_digest(payload),
        "metrics": metrics,
        "metrics_without_a_declared_rule": undeclared,
        "families": list(FAMILIES),
        "statuses": sorted(STATUSES),
        "threshold_provenance": _THRESHOLD_PROVENANCE,
        "aggregation": {
            "rule": "the worst status over all metrics is the contract's status",
            "precedence_worst_first": list(_PRECEDENCE),
            "consequence": "a passing cost metric never erases a failing quality metric",
            "with_no_metrics_judged": _NO_STATUSES,
        },
        "inputs": [{"name": i.get("name"), "kind": i.get("kind")}
                   for i in (payload.get("inputs") or [])],
        "published": ("the rule set only: quantities, operators, thresholds, the provenance "
                      "of each threshold, what each metric punishes, and how statuses "
                      "aggregate"),
        "not_published": ("the bytes of any input, any recorded result, and any verdict. "
                          "This projection cannot produce a verdict: it does not call "
                          "evaluate_contract. Use etalon_method_evaluate_contract for a "
                          "replay against recorded results."),
        "how_to_use": ("Read this before the first iteration, not after the last. Recompute "
                       "each metric yourself as you work and compare against the threshold "
                       "here; a metric you cannot compute locally is a reason to say so, "
                       "never a reason to submit and hope."),
    }
