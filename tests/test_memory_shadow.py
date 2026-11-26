"""Shadowing a stretch of memory is checked by recomputing admission, not by arguing about edges.

The fixtures are the admission view's own, so these tests exercise the real propagation rather
than a second implementation of it.
"""

from __future__ import annotations

import pytest
from test_admission_view import binding, make_graph, nid

from moldarwin.learn.memory_shadow import check_shadow, free_to_shadow


def graph_and_bindings(*, relation="measured_result"):
    """``premise`` is relied on by ``owner``; ``aside`` is merely used by it.

    Edge direction follows the admission view: for every kind except ``supports`` the edge runs
    owner -> premise.
    """

    graph = make_graph(
        ["owner", "premise", "aside"],
        [("owner", "premise", "depends_on", relation),
         ("owner", "aside", "depends_on", "selected_method")],
    )
    bindings = [binding("premise", "admitted"), binding("aside", "admitted")]
    return graph, bindings


def test_a_record_nothing_relies_on_can_leave_the_view_for_free():
    graph, bindings = graph_and_bindings()
    report = check_shadow(graph, bindings, shadow=[nid("aside")])
    assert report.safe
    assert report.free == (nid("aside"),)
    assert report.load_bearing == ()
    assert report.losses == ()
    assert "costs no admission" in report.note


def test_shadowing_a_relied_on_premise_costs_the_verdict_that_rested_on_it():
    graph, bindings = graph_and_bindings()
    report = check_shadow(graph, bindings, shadow=[nid("premise")])
    assert not report.safe
    assert report.load_bearing == (nid("premise"),)
    assert [loss.node_id for loss in report.losses] == [nid("owner")]
    loss = report.losses[0]
    assert loss.after == "not_recorded"
    assert loss.lost_premises == (nid("premise"),)


def test_the_difference_is_the_edge_class_and_nothing_else():
    """Same two nodes, same edge kind; only the relation differs, and so does the answer."""

    relied, bindings = graph_and_bindings(relation="measured_result")
    used, _ = graph_and_bindings(relation="selected_method")
    assert not check_shadow(relied, bindings, shadow=[nid("premise")]).safe
    assert check_shadow(used, bindings, shadow=[nid("premise")]).safe


def test_nothing_is_deleted_and_neither_input_is_mutated():
    graph, bindings = graph_and_bindings()
    before_graph, before_bindings = str(graph), str(bindings)
    report = check_shadow(graph, bindings, shadow=[nid("premise")])
    assert str(graph) == before_graph and str(bindings) == before_bindings
    assert report.as_dict()["deleted_anything"] is False


def test_an_empty_shadow_moves_nothing():
    graph, bindings = graph_and_bindings()
    report = check_shadow(graph, bindings, shadow=[])
    assert report.safe and report.shadowed == () and report.losses == ()


def test_a_shadow_naming_a_node_that_is_not_there_is_refused():
    graph, bindings = graph_and_bindings()
    with pytest.raises(ValueError, match="absent from the graph"):
        check_shadow(graph, bindings, shadow=[nid("premise"), "research-node-absent"])


def test_shadowing_the_whole_graph_is_refused():
    graph, bindings = graph_and_bindings()
    every = [node["node_id"] for node in graph["nodes"]]
    with pytest.raises(ValueError, match="no view to check"):
        check_shadow(graph, bindings, shadow=every)


def test_a_duplicate_in_the_proposal_is_not_counted_twice():
    graph, bindings = graph_and_bindings()
    report = check_shadow(graph, bindings, shadow=[nid("aside"), nid("aside")])
    assert report.shadowed == (nid("aside"),)
    assert report.safe


def test_the_reduced_probe_is_a_different_view_and_says_so():
    """It must not carry the original's digest; a reduced graph is not the graph it came from."""

    from moldarwin.learn.memory_shadow import _reduced
    graph, _ = graph_and_bindings()
    reduced = _reduced(graph, {nid("aside")})
    assert reduced["view_id"] != graph["view_id"]
    from moldarwin.research.graph_memory import validate_research_graph
    validate_research_graph(reduced)  # a correct digest, so it validates


def test_the_largest_free_subset_is_found_and_verified():
    graph = make_graph(
        ["owner", "premise", "aside", "spare"],
        [("owner", "premise", "depends_on", "measured_result"),
         ("owner", "aside", "depends_on", "selected_method"),
         ("owner", "spare", "depends_on", "prior_use")],
    )
    bindings = [binding("premise", "admitted"), binding("aside", "admitted"),
                binding("spare", "admitted")]
    report = free_to_shadow(graph, bindings,
                            candidates=[nid("aside"), nid("spare"), nid("premise")])
    assert report.safe
    assert set(report.shadowed) == {nid("aside"), nid("spare")}
    assert nid("premise") not in report.shadowed


def test_a_greedy_subset_is_still_recomputed_rather_than_trusted():
    """Two premises can each look droppable while dropping both moves the floor."""

    graph = make_graph(
        ["owner", "first", "second"],
        [("owner", "first", "depends_on", "measured_result"),
         ("owner", "second", "depends_on", "measured_result")],
    )
    bindings = [binding("first", "admitted"), binding("second", "admitted")]
    both = check_shadow(graph, bindings, shadow=[nid("first"), nid("second")])
    assert not both.safe
    assert free_to_shadow(graph, bindings,
                          candidates=[nid("first"), nid("second")]).safe


def test_the_report_records_what_a_reader_needs_to_act_on_it():
    graph, bindings = graph_and_bindings()
    body = check_shadow(graph, bindings, shadow=[nid("premise")]).as_dict()
    assert body["schema"] == "moldarwin-shadow-safety/1"
    assert body["safe"] is False
    assert body["losses"][0]["before"] != body["losses"][0]["after"]
    assert body["load_bearing"] == [nid("premise")]
    assert body["retained_nodes"] == 2


def test_multi_hop_reliance_never_marks_grounding_leaf_free_and_tracks_transitive_losses():
    """``owner -> mid -> leaf``: shadowing both ``mid`` and ``leaf`` must mark both load-bearing,
    and shadowing ``leaf`` alone must still attribute ``owner``'s loss to ``leaf``."""

    graph = make_graph(
        ["owner", "mid", "leaf", "aside"],
        [("owner", "mid", "depends_on", "measured_result"),
         ("mid", "leaf", "depends_on", "measured_result"),
         ("owner", "aside", "depends_on", "selected_method")],
    )
    bindings = [binding("leaf", "admitted"), binding("aside", "admitted")]

    both = check_shadow(graph, bindings, shadow=[nid("mid"), nid("leaf")])
    assert not both.safe
    assert both.free == ()
    assert set(both.load_bearing) == {nid("mid"), nid("leaf")}
    owner_loss = next(loss for loss in both.losses if loss.node_id == nid("owner"))
    assert owner_loss.lost_premises == tuple(sorted([nid("mid"), nid("leaf")]))

    leaf_only = check_shadow(graph, bindings, shadow=[nid("leaf")])
    assert not leaf_only.safe
    assert leaf_only.load_bearing == (nid("leaf"),)
    by_node = {loss.node_id: loss for loss in leaf_only.losses}
    assert set(by_node) == {nid("owner"), nid("mid")}
    assert by_node[nid("owner")].lost_premises == (nid("leaf"),)
    assert by_node[nid("mid")].lost_premises == (nid("leaf"),)

    free_report = free_to_shadow(graph, bindings,
                                 candidates=[nid("mid"), nid("leaf"), nid("aside")])
    assert free_report.safe
    assert free_report.shadowed == (nid("aside"),)


def test_masked_load_bearing_premise_is_reported_honestly():
    """When ``owner`` is already ``withheld`` via ``bad``, dropping ``good`` does not move
    ``owner`` today, yet ``good`` remains on a relied_on path and is reported as load-bearing."""

    graph = make_graph(
        ["owner", "bad", "good"],
        [("owner", "bad", "depends_on", "measured_result"),
         ("owner", "good", "depends_on", "measured_result")],
    )
    bindings = [binding("bad", "withheld"), binding("good", "admitted")]
    report = check_shadow(graph, bindings, shadow=[nid("good")])
    assert report.safe
    assert report.load_bearing == (nid("good"),)
    assert "relied_on path" in report.note
