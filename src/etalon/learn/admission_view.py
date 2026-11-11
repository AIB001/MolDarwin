"""A node-level, read-only view of admission over a research graph.

Specified in ``docs/thin-harness/ADMISSION_PROPAGATION.md`` (v2: section 10 wins where it
disagrees with sections 1-8); this module follows that document section by section. It never calls ``learn.admissible.rule``: it reads the
``admission`` a caller-declared binding carries, and propagates it along ``relied_on``
edges. Nothing here writes to a graph, a binding, a label, a file or a store.

v3 adds **the regime membrane**, which the design corpus argues for and no section
of it had yet specified. ``MethodEvaluation`` has two assessment regimes and the
split is deliberate: ``diagnostic`` is freely explorable and
``research/journal.py::_validate_method_evaluation`` returns before its whole
chronology gate on that value, while ``independent_validation`` is held to a
frozen policy, inputs recorded before the freeze, evidence after it, and a
content-addressed refusal of already-seen bytes. ``RSI_REWARD.md``'s argument that
no split of an external benchmark protects against learning the verifier is the
same argument localised to the record: ``diagnostic`` is where the verifier may be
learned freely **because nothing propagates**. Until v3 nothing expressed the
second half -- ``assessment_role`` never reached edge classification, so a premise
produced under ``diagnostic`` propagated admission exactly as a fully predeclared
one did. It now degrades from ``relied_on`` to ``used`` with ``class_basis``
``regime_cannot_settle``, following the shape ``visible_at_selection`` already
uses for ``record_cannot_settle``: the record is intact and says something true,
and what it says is not reliance. A record that cannot say which regime it was
produced under degrades likewise, with ``regime_not_declared``.

The membrane lives entirely inside this derived view. ``rule(Measurement) ->
Ruling`` is untouched (constraint 1) and nothing is written back to a leaf record
(constraint 2). Declining reliance to a regime-unknown record is not a backfill
of admission (constraint 4): no old record is modified and no admission is
granted -- one is withheld.
"""

from __future__ import annotations

import copy
from typing import Any

from etalon.active.schema import digest
from etalon.faults.taxonomy import BY_CODE, FAULTS, Consequence, Exactness
from etalon.research.assessment_regime import (
    CANNOT_SETTLE, LESSON_CANNOT_SETTLE, NOT_AN_ASSESSMENT, NOT_APPLICABLE, NOT_DECLARED,
    regime_of_node,
)
from etalon.research.graph_memory import validate_research_graph

#: Moved for v3: the membrane changes derived values and the output carries new
#: fields, so every stored view digest is invalidated and ``compare_views``
#: refuses a v2 side rather than silently mixing two propagation rules.
VIEW_VERSION = "etalon-admission-view/4"

#: Worst first (section 4). ``not_recorded`` exists only in this view.
_ORDER = ("withheld", "not_recorded", "admitted_under_waiver", "admitted")
_RANK = {name: index for index, name in enumerate(_ORDER)}
_LEAF_VALUES = frozenset({"withheld", "admitted_under_waiver", "admitted"})

# Section 3 table.
_RELIED_BY_RELATION = frozenset({"measured_result", "evaluation_result", "selection_basis"})
_USED_BY_RELATION = frozenset({
    "declared_selected_workset", "declared_selection_checkpoint", "declared_resource_method",
    "declared_attributed_use", "declared_associated_node", "declared_associated_evaluation",
    "declared_subsequent_selection", "selected_method", "prior_use", "selection_method",
    "evaluated_candidate", "evaluated_baseline", "evaluation_cost", "evaluation_conditions",
    "applied_use", "execution_receipt", "workflow_instance", "evaluated_use",
    "planned_candidate", "planned_baseline", "evaluation_plan",
})
_STRUCTURAL_KINDS = frozenset({"derived_from", "supersedes", "tests", "refutes", "flow"})
_LABEL_VALUES = frozenset({"relied_on", "used"})
#: The two ``class_basis`` values only the membrane writes. An edge carrying one
#: was a relied-class edge by the table (or by a label) and is ``used`` now.
_MEMBRANE_BASES = frozenset({CANNOT_SETTLE, NOT_DECLARED, LESSON_CANNOT_SETTLE})

#: Section 10.5. Blocking codes ``rule()`` or ``CampaignStore`` can emit that are not
#: ``Fault`` entries. Cataloguing them would change ``rule()``'s notes (decisions file, part 2).
UNCATALOGUED_BLOCKING_CODES = (
    "NONFINITE_CHEAP_VALUE", "NONFINITE_EXPENSIVE_VALUE", "NO_EXPENSIVE_VALUE",
    "NO_CHEAP_VALUE", "PROTOCOL_EVIDENCE_MISMATCH",
)

_RULING_KEYS = frozenset({
    "parent_id", "admission", "teaches", "reproducible", "blocking", "waived", "bounded",
    "unverifiable", "unchecked", "notes",
})
_BINDING_KEYS = frozenset({
    "node_id", "ruling", "ruling_digest", "dispatch_ref", "claim_scope", "store_status",
    "store_admitted", "supersedes",
})
_BINDING_REQUIRED = _BINDING_KEYS - {"supersedes"}
_STORE_STATUSES = frozenset({"ok", "failed", "invalid", "blocked"})
_COMPLETENESS_SCHEMA = "etalon-research-graph-scope/1"


class AdmissionViewMismatch(ValueError):
    """Two views were built under different versions or fault catalogues."""


def catalogue_digest() -> str:
    """Digest over the semantic fields of every fault, in ``FAULTS`` order (section 6).

    It does NOT cover the blocking codes in ``UNCATALOGUED_BLOCKING_CODES`` (section 10.5):
    they are not faults, so a change to how they block is invisible to this digest. The
    view's ``catalogue_coverage`` says so on every output.
    """

    return digest([
        {
            "code": fault.code,
            "phase": fault.phase.value,
            "exactness": fault.exactness.value,
            "consequence": fault.consequence.value,
            "lower_kcal_mol": fault.lower_kcal_mol,
            "upper_kcal_mol": fault.upper_kcal_mol,
            "evidence": fault.evidence.value,
        }
        for fault in FAULTS
    ])


def _classify(edge: dict[str, Any], premise_regime: dict[str, Any] | None = None,
              label: str | None = None) -> tuple[str, str, bool]:
    """Return ``(premise_class, class_basis, human_labelable)`` for one graph edge.

    Three stages, in this order, and the order is the point.

    1. The section 3 / 10.3 table over ``(kind, relation)``. Unknown pairs are
       refused rather than defaulted, for the reason ``rule()`` refuses an unknown
       fault code: the caller and the view would disagree about what an edge means.
    2. A human label, where the table left the edge in the human-label class.
    3. **The membrane.** If the edge would be ``relied_on`` and the premise's own
       record was produced under a regime that cannot settle a premise, it becomes
       ``used``. This runs last on purpose: a human label may promote a
       corroborating support edge to a premise, and it may not pierce the
       membrane. A label says a person read the edge as reliance; the membrane
       says the record on the far end was never held to a standard that could
       carry it, and no label can make it have been.

    ``premise_regime`` is ``None`` for a premise whose record schema has no
    assessment role at all, and such an edge is left exactly as the table and the
    label leave it. See ``research/assessment_regime.regime_of_node`` for why the
    membrane is scoped to records that declare a regime.
    """

    premise_class, basis, labelable = _declared_class(edge)
    if labelable and label is not None:
        premise_class, basis = label, "human_label"
    if premise_class == "relied_on" and premise_regime is not None \
            and not premise_regime["permits_reliance"]:
        return "used", premise_regime["degrade_basis"], labelable
    return premise_class, basis, labelable


def _declared_class(edge: dict[str, Any]) -> tuple[str, str, bool]:
    """The section 3 / 10.3 table alone, over ``(kind, relation)``."""

    kind, relation = edge["kind"], edge.get("relation")
    if kind == "depends_on":
        if relation is None:
            return "used", "field_convention", False
        if relation in _RELIED_BY_RELATION:
            return "relied_on", "declared_relation", False
        if relation in _USED_BY_RELATION:
            return "used", "declared_relation", False
        if relation == "visible_at_selection":
            return "used", "record_cannot_settle", False
        if relation == "evaluated_node":  # section 10.3: default used
            return "used", "unlabelled_default", True
        if relation == "selection_output":
            return "not_premise", "structural", False
    elif relation is None:  # section 10.3: a non-null relation on these kinds is refused
        if kind == "supports":
            return "used", "unlabelled_default", True
        if kind in _STRUCTURAL_KINDS:
            return "not_premise", "structural", False
    raise ValueError(
        f"edge {edge['from']}->{edge['to']} has unknown (kind, relation) "
        f"({kind!r}, {relation!r}); refused rather than defaulted"
    )


def _str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _check_ruling(node_id: str, ruling: Any) -> None:
    """Section 10.1: the ruling is a whole, internally consistent ``Ruling.as_dict()``."""

    if not isinstance(ruling, dict) or set(ruling) != _RULING_KEYS:
        raise ValueError(f"binding for {node_id}: ruling must have exactly the keys of Ruling.as_dict()")
    if ruling["admission"] not in _LEAF_VALUES:
        raise ValueError(f"binding for {node_id} carries no valid ruling admission")
    if not isinstance(ruling["parent_id"], str):
        raise ValueError(f"binding for {node_id}: ruling parent_id must be text")
    for name in ("teaches", "reproducible"):
        if not isinstance(ruling[name], bool):
            raise ValueError(f"binding for {node_id}: ruling {name} must be a bool")
    for name in ("blocking", "waived", "bounded", "unverifiable", "unchecked", "notes"):
        if not _str_list(ruling[name]):
            raise ValueError(f"binding for {node_id}: ruling {name} must be a list of text")
    admission, blocking, waived = ruling["admission"], ruling["blocking"], ruling["waived"]
    if (admission == "withheld") != bool(blocking):
        raise ValueError(f"binding for {node_id}: inconsistent ruling, admission withheld iff blocking is non-empty")
    if (admission == "admitted_under_waiver") != (not blocking and bool(waived)):
        raise ValueError(
            f"binding for {node_id}: inconsistent ruling, admitted_under_waiver iff "
            "blocking is empty and waived is non-empty"
        )
    if ruling["teaches"] != (admission != "withheld"):
        raise ValueError(f"binding for {node_id}: inconsistent ruling, teaches must equal admission != withheld")
    if ruling["reproducible"] != (ruling["unverifiable"] == []):
        raise ValueError(f"binding for {node_id}: inconsistent ruling, reproducible must equal unverifiable == []")


def _check_bindings(bindings: Any, node_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Validate bindings and return, per node, its chain in order, oldest first."""

    if not isinstance(bindings, (list, tuple)):
        raise ValueError("bindings must be a list")
    by_node: dict[str, list[dict[str, Any]]] = {}
    seen_digest: dict[str, str] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError("a binding must be an object")
        unknown = sorted(set(binding) - _BINDING_KEYS)
        if unknown:
            raise ValueError(f"binding has unknown keys: {unknown}")
        node_id = binding.get("node_id")
        missing = sorted(_BINDING_REQUIRED - set(binding))
        if missing:
            raise ValueError(f"binding for {node_id!r} lacks required keys: {missing}")
        if node_id not in node_ids:
            raise ValueError(f"binding names a node not in the graph: {node_id!r}")
        ruling = binding["ruling"]
        _check_ruling(node_id, ruling)
        if binding["ruling_digest"] != digest(ruling):
            raise ValueError(f"binding for {node_id}: ruling_digest does not match its ruling")
        status, admitted = binding["store_status"], binding["store_admitted"]
        if status not in _STORE_STATUSES or not isinstance(admitted, bool):
            raise ValueError(
                f"binding for {node_id}: store_status must be one of {sorted(_STORE_STATUSES)} "
                "and store_admitted a bool"
            )
        if admitted != (status == "ok" and ruling["teaches"]):
            raise ValueError(
                f"binding for {node_id}: store_admitted disagrees with the store's own formula "
                "(store_status == 'ok' and teaches)"
            )
        if ruling["teaches"] != admitted:
            raise ValueError(f"binding for {node_id}: ruling teaches != store_admitted")
        dispatch = binding["dispatch_ref"]
        if (not isinstance(dispatch, dict) or set(dispatch) != {"store", "action_id"}
                or dispatch["store"] != "campaign" or not isinstance(dispatch["action_id"], str)
                or not dispatch["action_id"]):
            raise ValueError(f"binding for {node_id}: dispatch_ref must name the campaign store and an action_id")
        scope = binding["claim_scope"]
        if not isinstance(scope, dict):
            raise ValueError(f"binding for {node_id}: claim_scope must be an object")
        if scope.get("parent_id") != ruling["parent_id"]:
            raise ValueError(f"binding for {node_id}: claim_scope parent_id disagrees with the ruling")
        supersedes = binding.get("supersedes", [])
        if (not isinstance(supersedes, list) or len(supersedes) > 1
                or any(not isinstance(item, str) for item in supersedes)):
            raise ValueError(f"binding for {node_id}: supersedes must hold 0 or 1 digest")
        if seen_digest.setdefault(binding["ruling_digest"], node_id) != node_id:
            raise ValueError(f"ruling_digest {binding['ruling_digest']} is bound to more than one node")
        by_node.setdefault(node_id, []).append(binding)

    chains: dict[str, list[dict[str, Any]]] = {}
    for node_id, group in by_node.items():
        digests = [b["ruling_digest"] for b in group]
        if len(set(digests)) != len(digests):
            raise ValueError(f"node {node_id} has two bindings with the same ruling_digest")
        known = set(digests)
        successor: dict[str, str] = {}
        for binding in group:
            for target in binding.get("supersedes", []):
                if target not in known:
                    raise ValueError(f"node {node_id}: dangling supersedes digest {target!r}")
                if target in successor:
                    raise ValueError(f"node {node_id}: forked supersedes chain")
                successor[target] = binding["ruling_digest"]
        heads = [d for d in digests if d not in successor]
        if len(heads) != 1:
            raise ValueError(
                f"node {node_id}: supersedes chain has {len(heads)} heads "
                "(a fork, or a cycle)"
            )
        by_digest = {b["ruling_digest"]: b for b in group}
        ordered = [by_digest[heads[0]]]
        while ordered[-1].get("supersedes"):
            ordered.append(by_digest[ordered[-1]["supersedes"][0]])
            if len(ordered) > len(group):
                raise ValueError(f"node {node_id}: supersedes cycle")
        if len(ordered) != len(group):
            raise ValueError(f"node {node_id}: bindings do not form a single supersedes chain")
        for later, earlier in zip(ordered, ordered[1:]):
            if later["claim_scope"]["parent_id"] != earlier["claim_scope"]["parent_id"]:
                raise ValueError(f"node {node_id}: supersedes chain changes claim_scope parent_id")
        chains[node_id] = list(reversed(ordered))  # oldest first
    return chains


def _is_exact_wrong_subject(code: str) -> bool:
    fault = BY_CODE.get(code)
    return (fault is not None and fault.exactness is Exactness.EXACT
            and fault.consequence is Consequence.WRONG_SUBJECT)


def _exact_leaf(binding: dict[str, Any]) -> tuple[str, list[str]]:
    """Section 10.2: the exact leaf of the head binding and the codes that set it."""

    ruling = binding["ruling"]
    applied: list[tuple[str, list[str]]] = [("admitted", [])]
    if binding["store_status"] != "ok":
        applied.append(("withheld", []))  # no code: the computation did not complete
    for value, codes in (
        ("withheld", [c for c in ruling["blocking"] if _is_exact_wrong_subject(c)]),
        ("not_recorded", [c for c in ruling["blocking"] if c not in BY_CODE]),
        ("not_recorded", [c for c in ruling["unchecked"] if _is_exact_wrong_subject(c)]),
        ("admitted_under_waiver", [c for c in ruling["waived"] if _is_exact_wrong_subject(c)]),
    ):
        if codes:
            applied.append((value, codes))
    worst = min((value for value, _ in applied), key=_RANK.__getitem__)
    reasons = sorted({c for value, codes in applied if value == worst for c in codes})
    return worst, reasons


def _sccs(nodes: list[str], premises: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan, iterative. Components come out premises-first."""

    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, i = work.pop()
            if i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            recursed = False
            succ = premises[node]
            while i < len(succ):
                nxt = succ[i]
                i += 1
                if nxt not in index:
                    work.append((node, i))
                    work.append((nxt, 0))
                    recursed = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if recursed:
                continue
            if low[node] == index[node]:
                comp = []
                while True:
                    top = stack.pop()
                    on_stack.discard(top)
                    comp.append(top)
                    if top == node:
                        break
                out.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return out


def _completeness(graph: dict[str, Any]) -> dict[str, Any]:
    """Section 10.4: a positive assertion, never inferred from a missing flag."""

    missing: list[str] = []
    if graph.get("truncated") is not False:
        missing.append("truncated")
    if graph.get("issues") != []:
        missing.append("issues")
    receipt = graph.get("scope_receipt")
    if not isinstance(receipt, dict):
        missing.append("scope_receipt")
    else:
        if receipt.get("schema") != _COMPLETENESS_SCHEMA:
            missing.append("scope_receipt.schema")
        if receipt.get("traversal_complete") is not True:
            missing.append("scope_receipt.traversal_complete")
        if receipt.get("reference_coverage_complete") is not True:
            missing.append("scope_receipt.reference_coverage_complete")
        if receipt.get("deliberate_boundary_refs") != []:
            missing.append("scope_receipt.deliberate_boundary_refs")
        if receipt.get("boundary_relations") != []:
            missing.append("scope_receipt.boundary_relations")
        if receipt.get("issues") != []:
            missing.append("scope_receipt.issues")
    return {"asserted": not missing, "missing": missing}


def _propagate(
    components: list[list[str]], premises: dict[str, list[str]],
    leaf: dict[str, str | None], cyclic: set[str],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Section 4 over one facet: derived value and limiting leaves per node."""

    derived: dict[str, str] = {}
    limiting: dict[str, list[str]] = {}
    for comp in components:
        members = set(comp)
        is_cyclic = comp[0] in cyclic
        candidates: list[str] = []
        for n in comp:
            if leaf[n] is not None:
                candidates.append(leaf[n])
            candidates.extend(derived[p] for p in premises[n] if p not in members)
        if is_cyclic or not candidates:
            candidates.append("not_recorded")
        floor = min(candidates, key=_RANK.__getitem__)
        leaves: set[str] = set()
        for n in comp:
            if leaf[n] == floor:
                leaves.add(n)
            for p in premises[n]:
                if p not in members and derived[p] == floor:
                    leaves.update(limiting[p])
        if floor == "not_recorded":
            external_floor = any(
                derived[p] == floor for n in comp for p in premises[n] if p not in members
            )
            if is_cyclic or not external_floor:
                leaves.update(comp)  # the floor itself is the limit: nothing bound, or a cycle
        for n in comp:
            derived[n] = floor
            limiting[n] = sorted(leaves)
    return derived, limiting


def admission_view(graph: dict[str, Any], bindings: list[dict[str, Any]],
                   *, labels: dict[str, str] | None = None) -> dict[str, Any]:
    """Derive node-level admission. Pure: inputs are neither mutated nor written anywhere."""

    graph = validate_research_graph(graph)  # returns a fresh JSON copy
    completeness = _completeness(graph)
    labels = {} if labels is None else labels
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    chains = _check_bindings(bindings, set(nodes))
    chains = copy.deepcopy(chains)

    # --- labels (section 10.3: keys are "<from>|<to>|<kind>") ---
    if not isinstance(labels, dict):
        raise ValueError("labels must be an object")
    for key, value in labels.items():
        if value not in _LABEL_VALUES:
            raise ValueError(f"label {key!r} must be 'relied_on' or 'used'")
    labelled_keys: set[str] = set()

    # --- regimes (the membrane's input; read from the projected record only) ---
    regimes: dict[str, dict[str, Any] | None] = {
        nid: regime_of_node(node) for nid, node in nodes.items()}

    # --- edges ---
    edge_rows: list[dict[str, Any]] = []
    relied_pairs: set[tuple[str, str]] = set()
    candidates_at_default: dict[str, set[str]] = {nid: set() for nid in nodes}
    degraded: dict[str, set[str]] = {nid: set() for nid in nodes}
    membrane_counts: dict[str, int] = {}
    relied_class_edges = 0
    for edge in graph["edges"]:
        key = f"{edge['from']}|{edge['to']}|{edge['kind']}"
        if edge["kind"] == "supports":
            owner, premise = edge["to"], edge["from"]  # graph stores premise -> owner
        else:
            owner, premise = edge["from"], edge["to"]
        premise_class, basis, labelable = _classify(edge, regimes[premise], labels.get(key))
        if labelable and key in labels:
            labelled_keys.add(key)
        if labelable and basis == "unlabelled_default":
            candidates_at_default[owner].add(premise)
        if basis in _MEMBRANE_BASES:
            # Counted with its denominator rather than reported as a rate: the
            # quantity is "how many premises the regime refused", and a rate over
            # a handful of edges would say less than the two numbers.
            relied_class_edges += 1
            membrane_counts[basis] = membrane_counts.get(basis, 0) + 1
            degraded[owner].add(premise)
        elif premise_class == "relied_on":
            relied_class_edges += 1
        edge_rows.append({
            "from": edge["from"], "to": edge["to"], "kind": edge["kind"],
            "relation": edge.get("relation"),
            "owner": owner, "premise": premise,
            "premise_class": premise_class, "class_basis": basis,
            "premise_regime": (regimes[premise] or {}).get("regime", NOT_APPLICABLE),
        })
        if premise_class == "relied_on":
            relied_pairs.add((owner, premise))
    unmatched = sorted(set(labels) - labelled_keys)
    if unmatched:
        raise ValueError(
            f"labels target edges outside the human-label class (or no edge): {unmatched}"
        )
    edge_rows.sort(key=lambda r: (r["from"], r["to"], r["kind"], r["relation"] or ""))

    premises: dict[str, list[str]] = {nid: [] for nid in nodes}
    for (owner, premise) in sorted(relied_pairs):
        premises[owner].append(premise)

    # --- leaves ---
    leaf: dict[str, str | None] = {nid: None for nid in nodes}
    exact_leaf: dict[str, str | None] = {nid: None for nid in nodes}
    exact_reasons: dict[str, list[str]] = {}
    for nid, chain in chains.items():
        leaf[nid] = chain[-1]["ruling"]["admission"]
        exact_leaf[nid], exact_reasons[nid] = _exact_leaf(chain[-1])

    # --- propagation, both facets over the same relied_on edges ---
    components = _sccs(sorted(nodes), premises)
    cyclic = {comp[0] for comp in components if len(comp) > 1 or comp[0] in premises[comp[0]]}
    derived, limiting = _propagate(components, premises, leaf, cyclic)
    exact_derived, exact_limiting = _propagate(components, premises, exact_leaf, cyclic)
    reasons: dict[str, list[str]] = {nid: [] for nid in nodes}
    for comp in components:
        if comp[0] in cyclic:
            for n in comp:
                reasons[n].append("circular_reliance")
    for n in nodes:
        if not premises[n] and leaf[n] is None:
            reasons[n].append("no_binding_and_no_relied_on_premise")
        if degraded[n]:
            # Why this node has fewer premises than its edges suggest. Stated on
            # the node because that is where a reader of a derived value looks.
            reasons[n].append("premise_regime_cannot_carry_reliance")
    admission_out, exact_out = dict(derived), dict(exact_derived)
    if not completeness["asserted"]:  # section 10.4: cap both facets, leaves still reported
        for n in nodes:
            admission_out[n] = min(derived[n], "not_recorded", key=_RANK.__getitem__)
            exact_out[n] = min(exact_derived[n], "not_recorded", key=_RANK.__getitem__)
            reasons[n].append("graph_completeness_not_asserted")

    def closure(start: str) -> set[str]:
        seen: set[str] = set()
        todo = [start]
        while todo:
            cur = todo.pop()
            for p in premises[cur]:
                if p not in seen:
                    seen.add(p)
                    todo.append(p)
        return seen

    with_history = {nid for nid, chain in chains.items() if len(chain) > 1}
    node_rows = []
    for nid in sorted(nodes):
        node = nodes[nid]
        chain = chains.get(nid)
        binding = None
        history: list[dict[str, Any]] | None = None
        if chain:
            head = chain[-1]
            codes = list(head["ruling"]["blocking"])
            exactness = {e: [] for e in Exactness}
            uncatalogued = []
            for code in codes:
                fault = BY_CODE.get(code)
                (uncatalogued if fault is None else exactness[fault.exactness]).append(code)
            binding = {
                "ruling_digest": head["ruling_digest"],
                "dispatch_ref": head["dispatch_ref"],
                "claim_scope": head["claim_scope"],
                "store_status": head["store_status"],
                "store_admitted": head["store_admitted"],
                "exact_blocking": exactness[Exactness.EXACT],
                "threshold_blocking": exactness[Exactness.THRESHOLD],
                "derived_blocking": exactness[Exactness.DERIVED],
                "uncatalogued_blocking": uncatalogued,
                "exact_reasons": exact_reasons[nid],
            }
            history = [
                {
                    "admission": earlier["ruling"]["admission"],
                    "ruling_digest": earlier["ruling_digest"],
                    "claim_scope": earlier["claim_scope"],
                    "superseded_by": chain[i + 1]["ruling_digest"],
                }
                for i, earlier in enumerate(chain[:-1])
            ]
        row = {
            "node_id": nid,
            "kind": node["kind"],
            "kind_basis": node.get("kind_basis"),
            "admission": admission_out[nid],
            "exact_admission": exact_out[nid],
            "leaf": leaf[nid],
            "exact_leaf": exact_leaf[nid],
            "premises": premises[nid],
            "limited_by": sorted(p for p in premises[nid] if derived[p] == derived[nid]),
            "limiting_leaves": limiting[nid],
            "exact_limited_by": sorted(
                p for p in premises[nid] if exact_derived[p] == exact_derived[nid]),
            "exact_limiting_leaves": exact_limiting[nid],
            "unlabelled_candidate_premises": sorted(candidates_at_default[nid]),
            "assessment_regime": (regimes[nid] or {}).get("regime", NOT_APPLICABLE),
            "regime_refused_premises": sorted(degraded[nid]),
            "reasons": reasons[nid],
            "rests_on_superseded_premise": bool(({nid} | closure(nid)) & with_history),
            "binding": binding,
        }
        if "claim_scope" in node:
            row["claim_scope"] = node["claim_scope"]
        if history is not None:
            row["history"] = history
        node_rows.append(row)

    rest = {
        "schema": VIEW_VERSION,
        "view_version": VIEW_VERSION,
        "catalogue_digest": catalogue_digest(),
        "catalogue_coverage": _catalogue_coverage(),
        "graph_view_id": graph.get("view_id"),
        "graph_completeness": completeness,
        "binding_provenance": "caller_declared",
        "membrane": {
            "basis": "assessment_regime_of_the_premise_record",
            "relied_class_edges": relied_class_edges,
            "degraded_edges": sum(membrane_counts.values()),
            "by_class_basis": {b: membrane_counts.get(b, 0) for b in sorted(_MEMBRANE_BASES)},
            "regime_source": "projected_record_only_never_inferred",
            # The record side of the same membrane, and the reason it is here rather than
            # left countable-in-principle. `ASSESSMENT_REGIMES.md` §2 decided that an
            # omitted `assessment_role` is warned about and recorded, never refused, and
            # that decision rests on the omissions being *visible*: a population nothing
            # reports grows unwatched, and "we could count it" is not a count. Computed
            # from the regimes already read above, so this adds a report and not a pass.
            "records_by_role_basis": _role_basis_census(regimes),
        },
        "nodes": node_rows,
        "edges": edge_rows,
    }
    return {**rest, "view_id": "admission-view-" + digest(rest)}


def _role_basis_census(regimes: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    """How each record in this graph came by its assessment role, with the denominator.

    Three answers, and they are three because two would hide the population this census
    exists for. `explicitly_declared` and `defaulted_deprecated` are what
    `composition.record_evaluation` writes; `not_recorded` is a record predating the field,
    which is every real one measured so far (4 of 4 on `2xpro6000`, read-only 2026-11-10,
    Evidence `measured_here`) and is not the same fact as an omission that was recorded.

    Reported as counts over a stated denominator, never as a share of the declared subset: a
    rate over only the records that answered would read as coverage it does not have. Records
    whose schema carries no assessment role are outside the denominator entirely -- the
    membrane is about the regime of an assessment, not about every node in the graph.
    """

    from etalon.research.assessment_regime import ROLE_BASES

    counts = {basis: 0 for basis in (*ROLE_BASES, "not_recorded")}
    for block in regimes.values():
        # `None` is a node the membrane has no business with. `NOT_AN_ASSESSMENT` is a node
        # the membrane acts on that has no assessment role to report -- a lesson carries
        # `role_basis: None` for the same reason it has no freeze, and counting it as
        # `not_recorded` would pad the one number this census exists to keep honest with
        # records that were never supposed to answer.
        if block is None or block.get("regime") == NOT_AN_ASSESSMENT:
            continue
        basis = block.get("role_basis")
        counts["not_recorded" if basis is None else basis] = (
            counts.get("not_recorded" if basis is None else basis, 0) + 1)
    return {
        "records_carrying_an_assessment_role": sum(counts.values()),
        "by_basis": counts,
        "basis": ("the assessment_role_basis each record carries; declared by its writer at "
                  "dispatch and never inferred here"),
        "not_recorded_means": ("the record predates assessment_role_basis, which is a "
                               "different fact from an omission that was recorded as one"),
    }


def _catalogue_coverage() -> dict[str, Any]:
    return {
        "blocking_surface_complete": False,
        "uncatalogued_blocking_codes": sorted(UNCATALOGUED_BLOCKING_CODES),
    }


def _direction(before: str, after: str) -> str:
    if _RANK[after] > _RANK[before]:
        return "raised"
    if _RANK[after] < _RANK[before]:
        return "lowered"
    return "unchanged"


def compare_views(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Compare two views node by node; refuse if they were built under different terms."""

    for name in ("view_version", "catalogue_digest", "catalogue_coverage"):
        if a.get(name) != b.get(name):
            raise AdmissionViewMismatch(
                f"{name} differs ({a.get(name)!r} vs {b.get(name)!r}); "
                "no comparison is returned"
            )
    if a.get("graph_view_id") is None or b.get("graph_view_id") is None:
        raise AdmissionViewMismatch("graph_view_id is missing on a side; the graph version is unknown")
    if a["graph_view_id"] != b["graph_view_id"]:
        raise AdmissionViewMismatch("graph_view_id differs; these views are not over one graph")
    for side in (a, b):
        rest = {k: v for k, v in side.items() if k != "view_id"}
        if side.get("view_id") != "admission-view-" + digest(rest):
            raise AdmissionViewMismatch("view_id does not match the view's content; it was edited")
    left = {n["node_id"]: n for n in a["nodes"]}
    right = {n["node_id"]: n for n in b["nodes"]}
    both = sorted(left.keys() & right.keys())
    return {
        "nodes": {
            nid: {
                facet: {
                    "a": left[nid][facet], "b": right[nid][facet],
                    "moved": left[nid][facet] != right[nid][facet],
                    "direction": _direction(left[nid][facet], right[nid][facet]),
                }
                for facet in ("admission", "exact_admission")
            }
            for nid in both
        },
        "only_in_a": sorted(left.keys() - right.keys()),
        "only_in_b": sorted(right.keys() - left.keys()),
    }


__all__ = [
    "AdmissionViewMismatch", "UNCATALOGUED_BLOCKING_CODES", "admission_view",
    "catalogue_digest", "compare_views",
]
