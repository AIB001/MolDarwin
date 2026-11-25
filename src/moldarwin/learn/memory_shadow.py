"""Decide whether a stretch of research memory can be dropped from a view without changing a verdict.

Memory grows and reading it is bounded, so eventually something has to be left out of the view a
host reads. The question "which records can be left out" has an exact answer here, and it is not a
matter of age, size or how interesting a record looks.

**Nothing is deleted.** ``ResearchJournal`` has no delete method and that is load-bearing: a
recorded identity cannot be rewritten (``research/journal.py``), admission state changes keep their
old value (CLAUDE.md constraint 3), and a provenance chain with a hole in it is not a provenance
chain. Shadowing is about what a *default view* presents. Every shadowed record stays readable by
reference, exactly as a superseded record does today.

The rule
--------

``learn.admission_view`` already classifies every edge as ``relied_on`` or ``used``: a premise that
is relied on propagates admission to the node that relies on it, and a premise that is merely used
does not. That classification is the instrument this module needed and did not have to invent.

A record reached only along ``used`` edges can leave the view without changing any surviving node's
admission. A record on a ``relied_on`` path cannot: dropping it removes a premise, the node that
relied on it loses its floor, and its verdict falls to ``not_recorded`` -- which the reward counts
as a loss. The difference is not a matter of judgement.

Why this recomputes instead of reasoning
----------------------------------------

The reachability argument above is correct and is not what this module ships. ``check_shadow``
runs ``admission_view`` twice -- once on the graph as it is, once on the graph with the proposed
records removed -- and compares every surviving node's verdict. A claim that a shadow is safe is
then a measurement, not an argument about edges, and it stays true when the propagation rules
change underneath it.

This matters because the propagation has corners an edge-walk misses: a cyclic component takes
``not_recorded`` whatever its premises say, a node with no premises and no ruling takes the same
floor, and the membrane can degrade a relied-class edge to ``used`` on the regime of the premise
rather than on the edge. Reasoning about all three correctly is possible; recomputing is cheaper
and cannot drift from the thing it describes.

``docs/thin-harness/RSI_ARCHITECTURE.md`` lists memory organisation as the level of
self-improvement with **no verification instrument**. This is one: it does not say whether a
shadow is a good idea, which is a question about what a host will need next, but it does say
whether the shadow costs a verdict, which was the part nobody could check.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from moldarwin.active.schema import digest
from moldarwin.learn.admission_view import admission_view
from moldarwin.research.graph_memory import validate_research_graph


@dataclass(frozen=True, slots=True)
class Loss:
    """One node whose verdict the proposed shadow would change."""

    node_id: str
    before: str
    after: str
    #: Shadowed nodes this one had relied on, which is why its verdict moved.
    lost_premises: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "before": self.before, "after": self.after,
                "lost_premises": list(self.lost_premises)}


@dataclass(frozen=True, slots=True)
class ShadowReport:
    """Whether a proposed shadow is free, and what it would cost if not."""

    safe: bool
    shadowed: tuple[str, ...]
    retained: int
    losses: tuple[Loss, ...]
    #: Shadowed nodes that nothing surviving relied on. Safe to drop from the view.
    free: tuple[str, ...]
    #: Shadowed nodes at least one surviving node relied on. These are the cost.
    load_bearing: tuple[str, ...]
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "moldarwin-shadow-safety/1",
            "safe": self.safe,
            "shadowed": list(self.shadowed),
            "retained_nodes": self.retained,
            "free": list(self.free),
            "load_bearing": list(self.load_bearing),
            "losses": [loss.as_dict() for loss in self.losses],
            "note": self.note,
            "deleted_anything": False,
        }


def _reduced(graph: dict[str, Any], drop: set[str]) -> dict[str, Any]:
    """The graph without the dropped nodes and every edge that touched one.

    A probe, built in memory and never recorded. Two details are deliberate.

    It is **re-sealed**: ``validate_research_graph`` checks ``view_id`` against the content, so a
    reduced graph carrying the original's digest would be refused -- rightly, since it is a
    different view. Re-sealing says so rather than hiding it.

    Its ``scope_receipt`` is **inherited unchanged**. The receipt asserts that the traversal which
    produced the original was complete, and this is a controlled comparison: the dropped nodes must
    be the only difference between the two runs, or a verdict that moves cannot be attributed to
    them. The reduced graph is never written anywhere, so the inherited assertion makes no claim
    about a stored record.
    """

    out = copy.deepcopy(graph)
    out["nodes"] = [node for node in out["nodes"] if node["node_id"] not in drop]
    out["edges"] = [edge for edge in out["edges"]
                    if edge["from"] not in drop and edge["to"] not in drop]
    out.pop("view_id", None)
    out["view_id"] = "research-graph-" + digest(out)
    return out


def check_shadow(
    graph: dict[str, Any],
    bindings: Sequence[dict[str, Any]],
    *,
    shadow: Sequence[str],
    labels: dict[str, str] | None = None,
) -> ShadowReport:
    """Recompute admission with and without ``shadow``, and report every verdict that moved.

    ``graph`` and ``bindings`` are what :func:`admission_view` takes. ``shadow`` names the nodes a
    pruning policy proposes to leave out of a default view. Nothing is written and neither input
    is mutated.

    A node named in ``shadow`` that is not in the graph is refused rather than ignored: a policy
    whose targets have already moved is not a policy anybody can check.
    """

    graph = validate_research_graph(graph)
    present = {node["node_id"] for node in graph["nodes"]}
    drop = list(dict.fromkeys(shadow))
    missing = [node_id for node_id in drop if node_id not in present]
    if missing:
        raise ValueError(
            f"shadow names {len(missing)} node(s) absent from the graph ({', '.join(missing[:5])}). "
            "A policy whose targets have moved cannot be checked; rebuild the view and re-propose.")
    if not drop:
        return ShadowReport(True, (), len(present), (), (), (),
                            "Nothing proposed for shadowing; no verdict can move.")
    drop_set = set(drop)
    if drop_set == present:
        raise ValueError("shadowing every node leaves no view to check")

    before = admission_view(graph, list(bindings), labels=labels)
    reduced = _reduced(graph, drop_set)
    kept_bindings = [binding for binding in bindings
                     if binding.get("node_id") not in drop_set]
    # Labels key on an edge triple; one naming a dropped node would be unmatched and refused.
    kept_labels = None if labels is None else {
        key: value for key, value in labels.items()
        if not ({key.split("|")[0], key.split("|")[1]} & drop_set)}
    after = admission_view(reduced, kept_bindings, labels=kept_labels)

    before_nodes = {node["node_id"]: node for node in before["nodes"]}
    after_nodes = {node["node_id"]: node for node in after["nodes"]}

    def _premise_closure(start: str) -> set[str]:
        """All transitive relied_on premises of ``start`` in the original admission view.

        ``admission_view`` stores only direct premises on each node row. Walking only direct
        premises on surviving nodes misses multi-hop reliance (e.g. ``owner -> mid -> leaf``
        when both ``mid`` and ``leaf`` are proposed, or when ``leaf`` alone is shadowed), which
        would falsely classify a grounding leaf as ``free`` or report empty ``lost_premises``.
        """

        seen: set[str] = set()
        stack = list(before_nodes[start].get("premises", ()))
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                if current in before_nodes:
                    stack.extend(before_nodes[current].get("premises", ()))
        return seen

    closures = {node_id: _premise_closure(node_id) for node_id in after_nodes}
    losses: list[Loss] = []
    for node_id, node in after_nodes.items():
        was = before_nodes[node_id]
        if node["admission"] != was["admission"] or \
                node.get("exact_admission") != was.get("exact_admission"):
            lost = tuple(sorted(closures[node_id] & drop_set))
            losses.append(Loss(node_id, was["admission"], node["admission"], lost))

    relied_on_dropped = {
        premise
        for closure in closures.values()
        for premise in closure
        if premise in drop_set
    }
    free = tuple(node_id for node_id in drop if node_id not in relied_on_dropped)
    load_bearing = tuple(node_id for node_id in drop if node_id in relied_on_dropped)
    safe = not losses
    if safe and load_bearing:
        note = (
            f"{len(drop)} node(s) proposed, {len(after_nodes)} retained; no retained verdict moved "
            f"under the current bindings, though {len(load_bearing)} proposed node(s) lie on a "
            "relied_on path (currently masked by a stronger limiting premise)."
        )
    elif safe:
        note = (
            f"{len(drop)} node(s) proposed, {len(after_nodes)} retained; every retained verdict is "
            "unchanged. The shadow costs no admission."
        )
    else:
        note = (
            f"{len(losses)} retained node(s) would change verdict, because {len(load_bearing)} of the "
            f"{len(drop)} proposed node(s) are relied on. Shadow the free ones, or keep the premise."
        )
    return ShadowReport(safe, tuple(drop), len(after_nodes), tuple(losses), free, load_bearing, note)


def free_to_shadow(
    graph: dict[str, Any],
    bindings: Sequence[dict[str, Any]],
    *,
    candidates: Sequence[str],
    labels: dict[str, str] | None = None,
) -> ShadowReport:
    """The largest subset of ``candidates`` that costs no verdict, checked by recomputation.

    Greedy and then verified: the nodes nothing relies on are taken first, and every candidate set
    is put back through :func:`check_shadow`. The verification is not a formality -- dropping a set
    can move a verdict that dropping each member alone does not, because a node with two premises
    keeps its floor until both are gone.

    Returning an empty-but-safe shadow is a legitimate answer, and so is being handed candidates
    that turn out to be every node in the graph. Neither is an error here, whereas
    :func:`check_shadow` refuses the latter outright -- a caller who asks "what may I drop" is
    asking a question, where a caller who says "drop all of this" is making a claim.
    """

    present = {node["node_id"] for node in validate_research_graph(graph)["nodes"]}
    keep = [node_id for node_id in dict.fromkeys(candidates) if node_id in present]
    dropped = [node_id for node_id in dict.fromkeys(candidates) if node_id not in present]
    if dropped:
        raise ValueError(
            f"candidates name {len(dropped)} node(s) absent from the graph "
            f"({', '.join(dropped[:5])}). Rebuild the view and re-propose.")
    # Never the whole graph: a view with nothing in it answers no question, and `check_shadow`
    # refuses it. Drop the last candidate rather than the caller's whole request.
    if keep and set(keep) == present:
        keep = keep[:-1]
    while keep:
        report = check_shadow(graph, bindings, shadow=keep, labels=labels)
        if report.safe:
            return report
        # A verdict still moved, so the nodes those losses relied on come back out of the shadow.
        blocked = {premise for loss in report.losses for premise in loss.lost_premises}
        if not blocked:
            blocked = {keep[-1]}
        keep = [node_id for node_id in keep if node_id not in blocked]
    return check_shadow(graph, bindings, shadow=[], labels=labels)


__all__ = ["Loss", "ShadowReport", "check_shadow", "free_to_shadow"]
