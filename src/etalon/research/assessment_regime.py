"""Which assessment regime a record was produced under, and what reliance it permits.

`MethodEvaluation.assessment_role` has two values and they are a deliberate
two-regime split, not an accretion. `diagnostic` is the freely explorable regime:
no predeclaration, already-seen bytes, cheap proxies, no comparator pairing.
`research/journal.py::_validate_method_evaluation` returns before its chronology
gate for exactly that reason. `independent_validation` is the other regime, and
everything after that early return is what makes it one: results must be
`validation-` receipts bound to a `phi-` frozen policy, inputs must be recorded
before the freeze, evidence after it, and a content-addressed loop refuses
already-seen bytes relabelled as unseen.

What the architecture did not express is the consequence. `RSI_REWARD.md` argues
that no split of an external benchmark protects against learning the verifier,
because splitting by instance leaves the verifier shared. The two regimes are
that argument localised to the record: `diagnostic` is where the verifier may be
learned freely *because nothing propagates*, and `independent_validation` is
where it may not, enforced by freeze chronology and unseen bytes. So a diagnostic
record cannot settle a premise, and admission must not propagate through it.
This module is that rule as data; `learn/admission_view.py` applies it at edge
classification time, inside the derived read-only view only.

A third state is not a regime but the absence of one. A record written before
`assessment_role` became a required argument of `composition.record_evaluation`
carries no `assessment_role_basis`, so the record cannot say whether its role was
chosen or arrived at by omission. Such a record is `regime_unknown`: it may be
`used` and it may never be `relied_on`. That is not a backfill of admission
(`CLAUDE.md` constraint 4) - nothing is written to the old record and no
admission is granted. The view declines to grant one, which is the conservative
direction `learn/admissible.py` already argues for: withholding a good
measurement loses one molecule's information, admitting a bad one shifts the
threshold applied to every later molecule.

Nothing here reads or writes a store, a journal or a leaf record.
"""
from __future__ import annotations

from typing import Any

#: The two regimes `research/schema.py::MethodEvaluation` validates.
ROLES = ("diagnostic", "independent_validation")

#: How a record came by its role. Absent on every record written before
#: `composition.record_evaluation` required the argument.
EXPLICITLY_DECLARED = "explicitly_declared"
DEFAULTED_DEPRECATED = "defaulted_deprecated"
ROLE_BASES = (EXPLICITLY_DECLARED, DEFAULTED_DEPRECATED)

DIAGNOSTIC = "diagnostic"
INDEPENDENT_VALIDATION = "independent_validation"
#: Not a regime: the record cannot say which regime it was produced under.
REGIME_UNKNOWN = "regime_unknown"
#: Not a regime either: this record's schema carries no assessment role at all.
NOT_APPLICABLE = "not_applicable"

#: `class_basis` strings the membrane writes on an edge it degrades. Both follow
#: the shape of `visible_at_selection`'s existing `record_cannot_settle`: the
#: record is intact and says something true, and what it says is not reliance.
CANNOT_SETTLE = "regime_cannot_settle"
NOT_DECLARED = "regime_not_declared"

#: Not a regime, and distinct from `NOT_APPLICABLE` in the one way that matters: the
#: membrane **acts**. `NOT_APPLICABLE` says the membrane has no business with this node (an
#: artifact, a receipt) and leaves every derived value alone. `NOT_AN_ASSESSMENT` says the
#: node is a record type that cannot settle a premise *at all*, so a declared reliance on it
#: degrades. The two were one state before 2026-11-10 and a lesson got the first, which is
#: why a lesson could be relied on.
NOT_AN_ASSESSMENT = "not_an_assessment"

#: Why a reliance on an `etalon-method-experience/1` degrades. A lesson is an
#: interpretation: `graph_memory._project_node` gives it `kind = "J"` and never `"R"`, with
#: the comment *"Moving an observation into Judge must not turn a measured result into an
#: interpretation (or vice versa)"*. It has no freeze, no comparator and no predeclaration,
#: so there is no standard it was held to that could carry a premise.
LESSON_CANNOT_SETTLE = "lesson_cannot_settle"


def regime(role: Any, role_basis: Any) -> dict[str, Any]:
    """Classify one record's regime from its declared role and the basis of that role.

    Order matters. A role of `diagnostic` is answered first and without consulting
    the basis, because the regime is then known whichever way it was reached: a
    deliberately chosen diagnostic and one entered by omission are the same
    regime, and both cannot settle a premise. Only `independent_validation` needs
    the basis, and needs it to be `explicitly_declared`: on a record that predates
    the required argument, the role is a value we cannot attribute to a choice.
    """

    if role == DIAGNOSTIC:
        return {"regime": DIAGNOSTIC, "permits_reliance": False,
                "degrade_basis": CANNOT_SETTLE, "role_basis": role_basis}
    if role == INDEPENDENT_VALIDATION and role_basis == EXPLICITLY_DECLARED:
        return {"regime": INDEPENDENT_VALIDATION, "permits_reliance": True,
                "degrade_basis": None, "role_basis": role_basis}
    return {"regime": REGIME_UNKNOWN, "permits_reliance": False,
            "degrade_basis": NOT_DECLARED, "role_basis": role_basis}


def regime_of_node(node: dict[str, Any]) -> dict[str, Any] | None:
    """The regime a projected graph node declares, or None where its schema has none.

    The only projection carrying a regime today is the `evaluation` block
    `research/graph_memory.py::_project_node` writes for
    `etalon-method-evaluation/1` records, and `evaluation_result` -- a relation
    `learn/admission_view.py` classifies `relied_on` -- is emitted at exactly
    those nodes (`research/method_links.py`). Verified against both modules rather
    than assumed.

    A node whose record schema has no assessment role is left alone. The membrane
    is about the regime of an assessment, not about every record in the graph:
    treating an artifact or a receipt as regime-unknown would collapse every
    derived value and say nothing, and `CLAUDE.md`'s terms reserve
    `assessment_role` for an assessment.
    """

    # A lesson, before the assessment branch, because it is not an assessment and must not be
    # read as one with a missing role. `_project_node` writes this block for exactly
    # `etalon-method-experience/1`, which is a full `CONTENT_SCHEMAS` member and therefore a
    # legal premise ref anywhere a ref is legal. Two routes reached `relied_on` and the
    # membrane was blind to both: a decision step's `basis_refs`, emitted with relation
    # `selection_basis` (`method_links.py:79`), which `_declared_class` returns as
    # `relied_on`; and a `supports`-kind edge, which returns `labelable=True` so a human
    # label promotes it. `_classify` applies the label and *then* consults the regime, so one
    # branch here closes both -- including the case the membrane's own docstring claimed was
    # already closed ("no label can make it have been"), which was false for a lesson.
    #
    # Harmless until now only by absence: a lesson carries no `Ruling`, so no binding, so the
    # floor capped at `not_recorded`. Protection by absence is what the first principle
    # refuses, and the subject is now named: an RSI loop driven by a loose internal judge
    # consolidates verdicts into lessons, and this is the path by which those verdicts would
    # become premises.
    if isinstance(node.get("experience"), dict):
        return {"regime": NOT_AN_ASSESSMENT, "permits_reliance": False,
                "degrade_basis": LESSON_CANNOT_SETTLE, "role_basis": None}
    block = node.get("evaluation")
    if not isinstance(block, dict) or "assessment_role" not in block:
        return None
    # Why the missing key reads as `not_applicable` rather than as a regime-unknown
    # assessment: `MethodEvaluation.assessment_role` is a required field with no default
    # (`schema.py`), so a parsed record always carries one and a projection missing the key
    # is not a real projection. Reading a fabricated block as an undeclared assessment
    # would collapse `not_applicable` into `unknown`, which §11.3 refuses. This is safe
    # ONLY while the field stays required, which
    # `tests/test_regime_and_decision_rule.py::test_i18_absent_is_unreachable_because_the_field_is_required`
    # holds. The reachable weak cases are a `None` or out-of-enum value, and `regime`
    # answers both with `REGIME_UNKNOWN`.
    return regime(block.get("assessment_role"), block.get("assessment_role_basis"))


__all__ = [
    "CANNOT_SETTLE", "DEFAULTED_DEPRECATED", "DIAGNOSTIC", "EXPLICITLY_DECLARED",
    "INDEPENDENT_VALIDATION", "LESSON_CANNOT_SETTLE", "NOT_AN_ASSESSMENT",
    "NOT_APPLICABLE", "NOT_DECLARED", "REGIME_UNKNOWN",
    "ROLES", "ROLE_BASES", "regime", "regime_of_node",
]
