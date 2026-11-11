"""The decision rule travels with the measurement.

`research/evaluation_contract.py` already makes the acceptance criterion
first-class data: each metric carries an `operator` from a fixed comparator set
and a finite numeric `threshold`, `missing_policy` must be `"insufficient"`, and
`evaluation_rules_digest` strips the observed inputs so one declared rule keeps
its identity while the evidence under it changes. That machinery is good and the
`evaluation_plan` step could not reach it: `composition.validate_step_extension`
checks each plan metric against the exact field set
`("name", "family", "unit", "denominator", "missing_policy")`, and
`composition.record_evaluation` takes a prose `conclusion` validated only as
nonempty text. A plan could therefore declare what it measured and never what
would count as passing, and a conclusion could assert a finding against numbers
that were already unable to reach it.

That failure has been observed outside this repository: on an external benchmark
an agent submitted two answers that were mathematically unable to pass at the
moment of submission, and neither the agent nor the harness noticed, because the
acceptance criterion was never represented anywhere the agent or the record could
see it.

This module supplies the two missing halves.

1. `operator`, `threshold` and `threshold_evidence` as *optional* plan-metric
   fields -- optional so that every plan already recorded stays valid, and
   all-or-none so that half a rule is never mistaken for a rule. The evidence tag
   is required with the pair under `CLAUDE.md` constraint 5: a threshold is a new
   number, and a threshold somebody chose (`convention`) must not be presented as
   a measured one. The catalogue already shows why this matters at the point of
   use -- half its fault bands are `convention` and a reader of a ruling sees
   codes, not tags.

2. A replay of those rules against the observations the conclusion rests on.
   `validate_decision_rule` recomputes the verdict from the block's own `rules`
   and `observed` every time a record is constructed, so a stored
   `replayed_status` cannot be forged -- the same discipline
   `evaluation_contract.record_evaluation_artifact` applies to a report, where a
   payload that differs from the verified replay is refused.

Refusal is one-directional on purpose, and the hardening criterion is the reason.
A `claim` of `supported` against a replayed `criteria_failed`, `insufficient` or
`not_declared` is refused: a record asserting a finding its own declared rule
denies is, once the session is over, indistinguishable from a sound one.
Declining to claim support where the rule passed is *not* refused: a host may
have reasons the rule does not cover, and that choice stays visible in the same
record beside the verdict. Nor does this module decide a method, a threshold or a
metric -- the hardened set concerns provenance and propagation only.

Nothing here reads or writes a store, a journal, a file or an existing record.
"""
from __future__ import annotations

import json

from etalon.active.schema import canonical

REPLAY = "etalon-decision-rule-replay/1"

#: The three halves of a declared rule on an `evaluation_plan` metric. All or none.
RULE_FIELDS = ("operator", "threshold", "threshold_evidence")

#: What a conclusion claims. `not_claimed` is the honest default: a recorded
#: comparison need not claim anything.
CLAIMS = ("supported", "not_supported", "not_claimed")

#: `CLAUDE.md` constraint 5. `convention` may never be presented as a measurement.
#:
#: Imported rather than restated. The contract schema now requires the same tag on the
#: threshold it executes against (`evaluation_contract`'s metric validator), so plan and
#: contract read one vocabulary from one definition. A second copy here would be the debt
#: pattern this round named: a feature that enumerates its subjects instead of letting them
#: declare a property, maintained twice and stale on one side the first time it changes.
from etalon.research.evaluation_contract import PROVENANCE  # noqa: E402

BASIS_DECLARED = "replayed_from_evaluation_plan_metrics"
BASIS_NOT_DECLARED = "no_operator_or_threshold_declared_in_the_evaluation_plan"

#: Constraint 7: a quantity that was not obtained is reported as not obtained.
NOT_OBTAINED = "no value obtained; reported as not obtained rather than estimated"

_RULE_KEYS = ("name", "operator", "threshold", "threshold_evidence", "unit")
_OBSERVED_KEYS = ("name", "value", "evidence")
_BLOCK_KEYS = ("schema", "rules", "observed", "metrics", "replayed_status", "claim", "basis")


def _parts():
    """The comparator table, number check and status precedence, from their one home.

    Imported here rather than copied so that moving the precedence in
    `evaluation_contract._aggregate` moves it here too. Imported inside the
    function, following `composition.py`'s own idiom, so the record schema can
    depend on this module without an import cycle.
    """

    from .evaluation_contract import STATUSES, _OPS, _aggregate, _number
    return _OPS, _number, _aggregate, STATUSES


def _refuse(message):
    from .evidence_refs import EvidenceError
    raise EvidenceError(message)


def validate_plan_metric_rule(metric) -> bool:
    """Validate the optional rule on one `evaluation_plan` metric; True if it declares one.

    All three fields or none. An operator without a threshold declares nothing,
    a threshold without a comparator does not say which side passes, and a
    threshold without a provenance tag is a number of unstated origin.
    """

    operators, number, _, _ = _parts()
    present = [key for key in RULE_FIELDS if key in metric]
    if not present:
        return False
    if len(present) != len(RULE_FIELDS):
        _refuse("a plan metric declares operator, threshold and threshold_evidence"
                " together or none")
    if metric["operator"] not in operators:
        _refuse("plan metric comparator must be one of " + ", ".join(sorted(operators)))
    if not number(metric["threshold"]):
        _refuse("finite numeric threshold required; a decision rule cannot rest on a"
                " missing bound")
    if metric["threshold_evidence"] not in PROVENANCE:
        _refuse("threshold evidence must be one of " + ", ".join(PROVENANCE))
    return True


def plan_rules(detail) -> list[dict]:
    """The rules an `evaluation_plan` step detail declares, in plan order."""

    rules = []
    for metric in detail.get("metrics", []):
        if validate_plan_metric_rule(metric):
            rules.append({"name": metric["name"], "operator": metric["operator"],
                          "threshold": metric["threshold"],
                          "threshold_evidence": metric["threshold_evidence"],
                          "unit": metric["unit"]})
    return rules


def _check_rules(rules):
    operators, number, _, _ = _parts()
    if not isinstance(rules, list) or len(rules) > 64:
        _refuse("decision rules must be a bounded explicit list")
    names = []
    for item in rules:
        if not isinstance(item, dict) or set(item) != set(_RULE_KEYS):
            _refuse("a decision rule names exactly " + ", ".join(_RULE_KEYS))
        for key in ("name", "unit"):
            if not isinstance(item[key], str) or not item[key].strip():
                _refuse("decision rule name and unit must be nonempty text")
        if item["operator"] not in operators or not number(item["threshold"]):
            _refuse("decision rule needs a fixed comparator and a finite numeric threshold")
        if item["threshold_evidence"] not in PROVENANCE:
            _refuse("decision rule threshold needs an Evidence provenance")
        names.append(item["name"])
    if len(set(names)) != len(names):
        _refuse("one decision rule per metric name")
    return names


def _check_observed(observed, names):
    _, number, _, _ = _parts()
    if not isinstance(observed, list) or len(observed) > 64:
        _refuse("observations must be a bounded explicit list")
    values = {}
    for item in observed:
        if not isinstance(item, dict) or set(item) != set(_OBSERVED_KEYS):
            _refuse("an observation names exactly " + ", ".join(_OBSERVED_KEYS))
        if not isinstance(item["name"], str) or not item["name"].strip():
            _refuse("observation name must be nonempty text")
        if item["name"] in values:
            _refuse("one observation per metric name: " + item["name"])
        if item["evidence"] not in PROVENANCE:
            _refuse("every observed number carries an Evidence provenance")
        if item["value"] is not None and not number(item["value"]):
            _refuse("an observation is a finite number or explicit null for not obtained")
        values[item["name"]] = item["value"]
    if sorted(values) != sorted(names):
        missing = sorted(set(names) - set(values))
        extra = sorted(set(values) - set(names))
        _refuse("observations must cover exactly the ruled metrics"
                + (f"; missing {missing}" if missing else "")
                + (f"; not in the plan {extra}" if extra else ""))
    return values


def replay(rules, observed) -> dict:
    """Replay declared rules against observations. Nothing is imputed or estimated.

    An absent or non-finite observation yields `insufficient` for that metric,
    never a pass and never a substituted value, matching
    `evaluation_contract`'s `missing_policy: "insufficient"` and `CLAUDE.md`
    constraint 7. With no rules at all the status is `not_declared`, the value
    `_aggregate` already returns for an empty set, so "no rule travelled with
    this measurement" is a recorded status rather than a missing field.
    """

    operators, number, aggregate, _ = _parts()
    names = _check_rules(rules)
    values = _check_observed(observed, names)
    rows = []
    for item in rules:
        value = values[item["name"]]
        if value is None or not number(value):
            rows.append({"name": item["name"], "observed": None,
                         "status": "insufficient", "reason": NOT_OBTAINED})
        elif operators[item["operator"]](value, item["threshold"]):
            rows.append({"name": item["name"], "observed": value,
                         "status": "criteria_passed", "reason": None})
        else:
            rows.append({"name": item["name"], "observed": value,
                         "status": "criteria_failed",
                         "reason": "observed value does not satisfy the declared rule"})
    return {"metrics": rows, "status": aggregate([row["status"] for row in rows])}


def validate_decision_rule(value) -> dict:
    """Validate a `decision_rule` block and recompute its verdict from its own data.

    The recomputation is the point: a block may not carry a `replayed_status` or
    per-metric statuses that its rules and observations do not produce. The claim
    is then checked against the recomputed verdict in the one unsafe direction.
    """

    _, _, _, statuses = _parts()
    if not isinstance(value, dict) or set(value) != set(_BLOCK_KEYS):
        _refuse("a decision rule replay names exactly " + ", ".join(_BLOCK_KEYS))
    if value["schema"] != REPLAY:
        _refuse("wrong decision rule replay schema")
    if value["claim"] not in CLAIMS:
        _refuse("conclusion claim must be one of " + ", ".join(CLAIMS))
    expected_basis = BASIS_DECLARED if value["rules"] else BASIS_NOT_DECLARED
    if value["basis"] != expected_basis:
        _refuse("decision rule basis must be " + expected_basis)
    recomputed = replay(value["rules"], value["observed"])
    if (canonical(recomputed["metrics"]) != canonical(value["metrics"])
            or recomputed["status"] != value["replayed_status"]):
        _refuse("decision rule replay differs from the recorded verdict")
    if value["replayed_status"] not in statuses | {"not_declared"}:
        _refuse("unknown replayed evaluation status")
    if value["claim"] == "supported" and value["replayed_status"] != "criteria_passed":
        _refuse("conclusion claims support against a replayed " + value["replayed_status"]
                + "; the declared decision rule does not reach that conclusion")
    return json.loads(canonical(value))


def build_decision_rule(rules, observed, claim) -> dict:
    """Build the block a `MethodEvaluation` carries, replaying as it builds."""

    out = replay(rules, observed)
    return validate_decision_rule({
        "schema": REPLAY, "rules": list(rules), "observed": list(observed),
        "metrics": out["metrics"], "replayed_status": out["status"], "claim": claim,
        "basis": BASIS_DECLARED if rules else BASIS_NOT_DECLARED,
    })


__all__ = [
    "BASIS_DECLARED", "BASIS_NOT_DECLARED", "CLAIMS", "NOT_OBTAINED", "PROVENANCE",
    "REPLAY", "RULE_FIELDS", "build_decision_rule", "plan_rules", "replay",
    "validate_decision_rule", "validate_plan_metric_rule",
]
