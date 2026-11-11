"""Which test holds which invariant the normative documents declare.

`docs/thin-harness` declares invariants I1..I20 in prose, each with the sentence "Each
must be held by a test" above it (`ADMISSION_PROPAGATION.md` §7, `ASSESSMENT_REGIMES.md`
§3.6). A declared invariant with no test is an unverified claim about the code -- which is
the thing `admission` exists to refuse, since `CLAUDE.md` defines it as "whether a result
may serve as the basis of a scientific conclusion". This module is the binding from
invariant to test; `tests/test_normative_consistency.py` is the check that the binding is
total and that every entry resolves to a test pytest actually collects.

Three structures, because three states are different and flattening them would hide a gap:

``BOUND``
    invariant id -> the pytest node ids that establish it.
``PARTIAL``
    a *bound* invariant one of whose declared clauses the bound tests do not establish,
    with that clause named. The invariant is bound, not verified whole. Naming the clause
    makes the remainder visible data instead of a silent gap, per `CLAUDE.md` hard
    constraint 7 (a quantity that cannot be obtained is reported as not obtained).
``UNBOUND``
    invariant id -> one line saying why no existing test establishes it.

Node ids are function-level: a parametrised test is named without its ``[param]`` suffix,
and the check strips that suffix from collected ids before comparing. Basis for "is
collected": ``pytest --collect-only -q`` over the files named below.

Evidence for every binding: each listed test was read at HEAD ``5764928`` and its
assertions compared with the invariant's declared text. Evidence class ``measured_here``.
No binding was inferred from a test's name alone; where a name says ``i5`` and the body
establishes something narrower, the narrower reading is what the entry records.

Adding an invariant to a document is therefore a two-file change: declare it there, bind
it here. That is the point -- the registry is the place where "no test holds this" has to
be written down rather than noticed later.
"""
from __future__ import annotations

#: Files that carry the bound tests. Collection is run over exactly these.
AV = "tests/test_admission_view.py"
RG = "tests/test_regime_and_decision_rule.py"

#: Documents scanned for invariant declarations. The declaration form in this repository
#: is a bold id at the head of a list item: ``- **I9 — completeness.** ...``. Plain
#: mentions (``invariant I7``, ``I8: the truncated-graph refusal is replaced by I9``) are
#: references, not declarations, and are deliberately not matched.
DECLARING_DOCS = ("docs/thin-harness/ADMISSION_PROPAGATION.md",
                  "docs/thin-harness/ASSESSMENT_REGIMES.md")

BOUND: dict[str, tuple[str, ...]] = {
    # I1 -- rule() unchanged: two pinned digests over Measurement fixtures covering every
    # consequence, a waiver, an unchecked observation, non-finite and missing values, on
    # both require_comparator paths.
    "I1": (
        f"{AV}::test_i1_rule_unchanged_pinned_digest",
        f"{AV}::test_i1_second_pin_require_comparator_false_path",
    ),
    # I2 -- no write-back: deep-equality of graph/bindings/labels, no file written, no
    # sqlite connection opened.
    "I2": (
        f"{AV}::test_i2_no_mutation_no_file_written_and_no_sqlite",
        f"{AV}::test_i2_binding_without_supersedes_key_is_accepted_and_unchanged",
        f"{AV}::test_i2_rulings_are_not_mutated_by_derivation",
        f"{AV}::test_membrane_is_read_only_and_the_graph_is_unchanged",
    ),
    # I3 -- history retained, with the §10.7 closure form of the mark.
    "I3": (
        f"{AV}::test_history_retained_after_supersede",
        f"{AV}::test_i3_s10_7_superseded_premise_two_hops_below_marks_the_top",
        f"{AV}::test_i3_s10_7_mark_holds_when_the_superseded_premise_does_not_attain_the_minimum",
        f"{AV}::test_i3_s10_7_bound_node_with_own_history_is_marked_though_its_leaf_is_above_the_floor",
        f"{AV}::test_i3_unsuperseded_graph_marks_nothing",
    ),
    # I4 -- versioned comparison: the view carries both fields and compare_views refuses a
    # mismatch on either. The digest-composition tests are what make "catalogue_digest"
    # mean something, so they are bound here too.
    "I4": (
        f"{AV}::test_i4_view_carries_version_and_catalogue_digest",
        f"{AV}::test_i4_catalogue_digest_ignores_prose_fields",
        f"{AV}::test_i4_catalogue_digest_covers_semantic_fields",
        f"{AV}::test_i4_catalogue_digest_changes_when_a_fault_is_added_or_removed",
        f"{AV}::test_i4_catalogue_digest_unpatched_value_is_restored_after_monkeypatch",
        f"{AV}::test_s10_6_compare_refuses_view_version_mismatch",
        f"{AV}::test_s10_6_compare_refuses_catalogue_digest_mismatch",
    ),
    # I5 -- weakest premise bounds, including the node's own leaf.
    "I5": (
        f"{AV}::test_i5_unbound_premise_bounds_owner_below_waiver",
        f"{AV}::test_own_leaf_bounds_owner",
        f"{AV}::test_limiting_leaves_names_the_bottom_leaf_not_the_intermediate_node_two_hops",
        f"{AV}::test_limiting_leaves_three_hops_and_unbound_bottom",
        f"{AV}::test_limiting_leaves_two_branches_both_reported",
    ),
    # I6 -- no vacuous admission, on both facets.
    "I6": (
        f"{AV}::test_i6_unbound_node_without_premises_is_not_recorded",
        f"{AV}::test_i6_all_nodes_not_recorded_when_nothing_bound",
        f"{AV}::test_s10_2_exact_facet_is_vacuous_not_admitted_without_bindings_or_premises",
    ),
    # I7 -- `used` does not propagate: nine (kind, relation) pairs, each with the side
    # node's admission flipped and the owner's two facets unchanged.
    "I7": (f"{AV}::test_i7_used_and_not_premise_edges_do_not_propagate",),
    # I8 -- refusals. The truncated-graph clause of §7's I8 was replaced by I9 in §10.8,
    # so it is bound under I9, not here.
    "I8": (
        f"{AV}::test_i8_binding_for_unknown_node_refused",
        f"{AV}::test_i8_forked_chain_refused",
        f"{AV}::test_i8_two_unrelated_heads_refused",
        f"{AV}::test_i8_dangling_supersedes_refused",
        f"{AV}::test_i8_supersedes_cycle_refused",
        f"{AV}::test_i8_unknown_kind_relation_refused",
        f"{AV}::test_i8_label_on_non_labelable_edge_refused",
        f"{AV}::test_i8_label_with_bad_value_refused",
        f"{AV}::test_i8_label_with_wrong_kind_in_key_refused",
        f"{AV}::test_s10_1_ruling_digest_mismatch_refused",
    ),
    # I9 -- completeness caps both facets at not_recorded; a truncated graph is capped
    # rather than refused (the §10.4 replacement of §1's refusal).
    "I9": (
        f"{AV}::test_i9_each_failed_completeness_condition_caps_both_facets_and_is_named",
        f"{AV}::test_i9_complete_graph_is_not_capped_control",
        f"{AV}::test_i9_truncated_graph_is_capped_not_refused",
        f"{AV}::test_i9_cap_lowers_only_and_a_withheld_node_stays_withheld_on_both_facets",
        f"{AV}::test_i9_several_failed_conditions_are_all_named_in_order",
        f"{AV}::test_i9_unscoped_graph_without_a_scope_receipt_never_asserts",
    ),
    # I10 -- both clauses: threshold-only withholding has exact leaf `admitted`, and an
    # EXACT & WRONG_SUBJECT code in `unchecked` has exact leaf `not_recorded`.
    "I10": (
        f"{AV}::test_i10_threshold_only_withheld_has_exact_leaf_admitted",
        f"{AV}::test_s10_2_threshold_codes_are_ignored_in_every_list",
        f"{AV}::test_s10_2_row_exact_wrong_subject_in_unchecked_is_not_recorded",
    ),
    # I11 -- "every refusal in §10.1 raises". One entry per refusal clause of §10.1,
    # plus the chain clauses §10.1 inherits from v1.
    "I11": (
        f"{AV}::test_s10_1_inconsistent_ruling_admitted_with_blocking_is_refused",
        f"{AV}::test_s10_1_inconsistent_ruling_other_admission_blocking_waived_pairs",
        f"{AV}::test_s10_1_inconsistent_ruling_teaches_not_equal_to_admission",
        f"{AV}::test_s10_1_inconsistent_ruling_reproducible_not_equal_to_unverifiable_empty",
        f"{AV}::test_s10_1_ruling_keys_must_be_exactly_those_of_as_dict",
        f"{AV}::test_s10_1_ruling_digest_mismatch_refused",
        f"{AV}::test_s10_1_not_recorded_as_a_ruling_admission_is_refused",
        f"{AV}::test_s10_1_store_admitted_disagreeing_with_store_formula_is_refused",
        f"{AV}::test_s10_1_ruling_teaches_not_equal_store_admitted_is_refused",
        f"{AV}::test_s10_1_bad_store_status_or_non_bool_store_admitted_is_refused",
        f"{AV}::test_s10_1_missing_required_key_is_refused",
        f"{AV}::test_s10_1_unknown_binding_key_is_refused",
        f"{AV}::test_s10_1_bad_dispatch_ref_is_refused",
        f"{AV}::test_s10_1_non_object_claim_scope_is_refused",
        f"{AV}::test_s10_1_claim_scope_parent_id_disagreeing_with_ruling_is_refused",
        f"{AV}::test_s10_1_same_ruling_digest_bound_to_two_nodes_is_refused",
        f"{AV}::test_s10_1_chain_whose_claim_scope_parent_id_changes_is_refused",
        f"{AV}::test_s10_1_supersedes_with_two_entries_is_refused",
        f"{AV}::test_i8_forked_chain_refused",
        f"{AV}::test_i8_dangling_supersedes_refused",
        f"{AV}::test_i8_supersedes_cycle_refused",
    ),
    # I12 -- declared coverage of the blocking surface over the I1 fixtures, both
    # require_comparator settings.
    "I12": (
        f"{AV}::test_i12_every_i1_blocking_code_is_catalogued_or_declared_uncatalogued",
        f"{AV}::test_s10_5_uncatalogued_blocking_codes_are_those_five_and_not_faults",
    ),
    # I13 -- the membrane demotes: the pair carries class_basis regime_cannot_settle and
    # neither facet is better than it would be with the edge absent. The last entry is the
    # same mechanism over a graph a journal actually wrote.
    "I13": (
        f"{AV}::test_membrane_diagnostic_premise_degrades_relied_on_to_used",
        f"{AV}::test_membrane_degrades_the_exact_facet_by_the_same_rule",
        f"{AV}::test_membrane_never_lifts_a_derived_value_above_not_recorded",
        f"{RG}::test_the_membrane_refuses_a_real_diagnostic_evaluation_as_a_premise",
    ),
    # I14 -- independent_validation is untouched. See PARTIAL: the "byte-identical to the
    # pre-change view" half of the clause has no fixture to compare against.
    "I14": (
        f"{AV}::test_membrane_independent_validation_premise_still_propagates",
        f"{AV}::test_membrane_covers_every_declared_relied_class_relation",
        f"{AV}::test_membrane_label_to_an_independent_validation_premise_still_promotes",
    ),
    # I15 -- the diagnostic node keeps its own derived value: asserted on p1 inside the
    # same fixture that demotes the edge.
    "I15": (f"{AV}::test_membrane_diagnostic_premise_degrades_relied_on_to_used",),
    # I16 -- scope: no schema other than etalon-method-evaluation/1 is demoted by regime.
    # See PARTIAL for the byte-identity half.
    # I17 was UNBOUND until the two-edge fixture was added: `_membrane_graph` carries
    # exactly one edge, so §11.2's ordering was held only by reading `relied_pairs`.
    # Both directions are bound -- degraded with a diagnostic premise, carried with a
    # permitting one -- because an ordering claim needs the case that must NOT degrade.
    "I17": (f"{AV}::test_i17_two_relied_edges_on_one_pair_still_resolve_to_used",
            f"{AV}::test_i17_two_relied_edges_on_one_pair_still_propagate_when_the_regime_permits"),
    "I16": (
        f"{AV}::test_membrane_leaves_a_premise_whose_schema_has_no_regime_alone",
        f"{AV}::test_membrane_ignores_a_block_that_is_not_an_evaluation_projection",
        f"{AV}::test_membrane_does_not_count_a_used_edge_in_its_denominator",
        f"{RG}::test_regime_of_a_node_whose_schema_has_no_role_is_none",
    ),
    # I18 -- unknown is weak and separable. See PARTIAL: every bound test reaches
    # regime_unknown through the *basis*, not through the three `assessment_role` triggers
    # the declaration names.
    "I18": (
        f"{AV}::test_membrane_regime_unknown_premise_is_used_never_relied_on",
        f"{AV}::test_membrane_an_explicitly_null_basis_is_also_regime_unknown",
        f"{AV}::test_membrane_defaulted_diagnostic_is_the_same_regime_as_a_chosen_one",
        f"{RG}::test_regime_table_is_total_and_only_one_cell_permits_reliance",
        f"{RG}::test_a_legacy_evaluation_node_without_a_basis_is_regime_unknown_on_a_real_graph",
    ),
    # I19 -- read-only, and rule(Measurement) -> Ruling keeps its semantics.
    "I19": (
        f"{AV}::test_membrane_is_read_only_and_the_graph_is_unchanged",
        f"{AV}::test_i2_no_mutation_no_file_written_and_no_sqlite",
        f"{AV}::test_i1_rule_unchanged_pinned_digest",
        f"{AV}::test_membrane_classify_is_pure_in_the_regime_argument",
    ),
    # I20 -- reliance is declined, never revoked: a record written before the regime
    # argument existed parses with no basis, is read regime-unknown, is refused reliance,
    # and nothing is written to it.
    "I20": (
        f"{RG}::test_a_record_predating_the_argument_parses_with_no_basis_and_is_refused_reliance",
        f"{RG}::test_a_legacy_evaluation_node_without_a_basis_is_regime_unknown_on_a_real_graph",
        f"{AV}::test_membrane_regime_unknown_premise_is_used_never_relied_on",
    ),
    # I21/I22 -- v4 (ADMISSION_PROPAGATION.md s12). A lesson is not an assessment. The
    # label clause of I21 is the one that was false before v4: the membrane's own prose
    # claimed no label could pierce it, while `etalon-method-experience/1` sat outside its
    # scope entirely, so both routes are bound here and the label route is bound explicitly.
    "I21": (
        f"{AV}::test_i21_a_lesson_cannot_be_a_premise_and_no_label_restores_it",
        f"{AV}::test_i21_a_lesson_declares_not_an_assessment_rather_than_an_unknown_regime",
    ),
    "I22": (
        f"{AV}::test_i22_a_lesson_stays_out_of_the_assessment_role_census",
    ),
}

#: A clause of a bound invariant that the bound tests do not establish. Bound is not the
#: same as verified whole, and the difference is written down rather than rounded off.
PARTIAL: dict[str, str] = {
    "I1": "the clause 'learn/admissible.py is not edited' is held as behavioural "
          "equivalence over the two pinned fixture sets, not as file identity: no test "
          "pins a hash or mtime of that module.",
    "I14": "the clause 'every other node's row is byte-identical to the pre-change view "
           "at the same view_version' is not established -- no pre-membrane view object "
           "is pinned anywhere in the suite, so there is nothing to compare bytes with.",
    "I16": "same byte-identity clause as I14 ('byte-identical modulo view_version to the "
           "pre-change one'); the operative half -- no other node schema is demoted by "
           "regime -- is established by the listed tests.",
    "I18": "the three triggers the declaration names (`assessment_role` absent, `None`, "
           "or a string outside the enum) have no fixture; every bound test reaches "
           "regime_unknown through a missing or null `assessment_role_basis` instead. "
           "The 'absent' trigger also reads differently in the code: "
           "`research/assessment_regime.regime_of_node` returns None (not_applicable, "
           "edge untouched) when the projected block has no `assessment_role` key.",
}

#: An invariant no existing test establishes. One line each, naming what is missing.
#: Empty is the state to aim for, not a sign the structure is unused: I17 sat here until
#: the two-edge fixture below was written, and the entry is what made it a task rather
#: than a code reading nobody had checked.
UNBOUND: dict[str, str] = {}


def all_registered() -> set[str]:
    """Every invariant id this registry accounts for, bound or not."""

    return set(BOUND) | set(UNBOUND)


def node_ids() -> tuple[str, ...]:
    """Every pytest node id the registry points at, deduplicated and sorted."""

    return tuple(sorted({n for ids in BOUND.values() for n in ids}))


def files() -> tuple[str, ...]:
    """The test files collection has to be run over to resolve every entry."""

    return tuple(sorted({n.split("::", 1)[0] for n in node_ids()}))
