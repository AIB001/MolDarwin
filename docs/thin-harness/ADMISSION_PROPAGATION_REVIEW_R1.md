# Design review, round 1: `admission_view` against ADMISSION_PROPAGATION.md

Reviewer: Opus, acting as `etalon-design-review`. Date: 2026-11-05.
Reviewed: the round-1 implementation (`src/etalon/learn/admission_view.py`,
`tests/test_admission_view.py`) against the round-1 design. Decisions taken in response:
`ADMISSION_PROPAGATION_DECISIONS.md`. Line numbers refer to the round-1 files, so they will
not match later revisions.

**Verdict.** The function does what the design says on the small graphs the tests build by
hand. Five decisions in the design don't hold up against the code:
- The `supports` default can raise a derived admission, not only lower it.
- `truncated` is the wrong signal for a complete graph.
- `ruling.admission` is not the store's admission decision.
- Nothing in a binding is verifiable, so constraint 4 is not protected.
- The §0.3 split of 4 relied_on / 24 used sites contradicts the design's own §3 table.

**What was checked.** The 42 new tests were rerun and passed in `/tmp/etalon-venv`.
`git diff HEAD` was empty, so `learn/admissible.py` was unedited. 27 mutants of a copy of the
module were run (`/tmp/avmut/run_mutants.py`), plus 15 behaviour probes
(`/tmp/avmut/probes.py`, `/tmp/avmut/probe2.py`).

"Verified" means run, or read in the cited code. "Inferred" means reasoned to.

---

## 1. Does the implementation preserve each invariant?

Ranked by severity.

1. **No test passes a real `Ruling` into a binding, and "verbatim" is not enforced.**
   (Verified)
   - The test helper builds a ruling dict without `teaches`, `reproducible`, `bounded`,
     `unverifiable` or `unchecked` (`tests/test_admission_view.py:61-71`). The view accepts it.
   - The view checks only that `admission` is one of three values and that the digest is
     self-consistent (`admission_view.py:102-106`).
   - Probe P1: a ruling that says `admission: "admitted"` while
     `blocking: ["F_HYDROGENS_IMPLICIT"]` is accepted and propagates `admitted`. `rule()` can
     never produce that ruling (`admissible.py:234-235`).
   - I1 computes real rulings (`test_admission_view.py:114-119`) but never feeds them to
     `admission_view`.
2. **I1: the pinned digest is real but blind to the path production dispatch uses.**
   (Verified)
   - The fixture always calls `rule()` with `require_comparator=True`
     (`test_admission_view.py:116`). Both `CampaignStore` callers pass
     `require_comparator=False` (`active/store.py:560-562`, `633-634`). A change to that branch
     is invisible to the pin.
   - Also not covered:
     - `NONFINITE_EXPENSIVE_VALUE` (only the cheap value is made non-finite, `:108`)
     - the unknown-code `KeyError` and fourth-consequence `ValueError` refusals
       (`admissible.py:178`, `213`)
     - `_protocol_ruling` (`store.py:430-439`)
     - the catalogue entries of the 15 codes not in the fixture
   - What actually holds "`rule()` unchanged" this round is `git diff HEAD` being empty. The
     digest guards only the 9 fixture cases from here on.
3. **I2 (no write-back): the code holds it, the test holds part of it.** (Verified)
   - The module does no I/O, and `validate_research_graph` returns a fresh copy
     (`graph_memory.py:57`).
   - The test checks only a binding that already has every optional field, and only the cwd
     listing (`test_admission_view.py:165-173`).
   - Mutant `binding.setdefault("supersedes", [])` survived. Bindings without `supersedes`
     are untested; the original code handles them correctly (probe2).
   - "Opens no store" has no test.
4. **I3: transitive `rests_on_superseded_premise` is untested.** (Verified)
   - The test is one hop deep (`:143-160`). Mutants restricting the mark to direct premises
     survived. The code is transitive (`admission_view.py:368-370`; probe P11 gives True two
     hops up).
   - Quirk (verified from the code): a bound node with history is marked itself only if its
     own leaf attains its floor.
5. **I4: refusal is tested; the digest's contents are not.** (Verified)
   - Mutants that dropped `exactness` from `catalogue_digest()`, or added the prose field
     `summary`, both survived.
   - The only digest test checks determinism and length (`:202-204`). §6's rule about which
     fields count is held by nothing.
6. **I5 holds for the value; multi-hop attribution is untested.** (Verified)
   - I5 holds by construction: a single `min` over leaf and premises
     (`admission_view.py:274-283`).
   - Mutant `leaves.add(p)` in place of `leaves.update(limiting[p])` survived.
     `limiting_leaves` beyond one hop is untested; probes P7 and P8 show the original is
     correct.
7. **I6, I7 and I8 are held, and mutants against them were killed.** (Verified)
   - Surviving mutants on the extra binding checks: removing the `dispatch_ref` check,
     removing the `claim_scope` check, accepting `not_recorded` as a leaf value.
   - Overall, 10 of 27 mutants survived, all in the gaps listed above.
8. **The implementer's eleven self-reported interpretations, checked against the code:**
   1. *Consistent.* `EvidenceError` subclasses `ValueError` (`runtime/files.py:12`), so graph
      refusals are `ValueError` too. A malformed edge can still escape as `KeyError` from
      `validate_research_graph`.
   2. *Must be recorded.* Reading "—" as "any relation" is the permissive reading. It
      conflicts with §3's "any other (kind, relation) → refused". No effect today: the builder
      attaches a relation only to `method_links` `depends_on` edges
      (`graph_memory.py:349-350`).
   3. *Consistent* with §3's last row (`admission_view.py:84`).
   4. *Consistent.* `owner`/`premise` follow from §3's direction rule.
   5. *Misdescribed and must be recorded.*
      - The code flags a node if any pair in {self} ∪ closure is `relied_on` only by
        unlabelled defaults (`:256-259`, `325-327`). That is not "the closure rests solely on a
        default".
      - P9: the node is flagged despite a declared sibling. P10: it is flagged even when the
        default edge does not set the value.
      - The design's "whose value depended on" does not say whether it means structurally
        present or value-changing.
   6. *Consistent.* Refusing a label that matches no edge goes beyond the design; record it.
   7. *Consistent.* The shared value is the fixed point of the min recursion. "Members plus
      external" and "self" both fit "the bound or not_recorded nodes at the bottom".
   8. *Must be recorded.* The design's wording is ambiguous; transitive is the inclusive
      reading.
   9. *Consistent with §2's schema but untested* (surviving mutants).
   10. *Consistent.* Record that the per-leaf splits live under `binding`, and that `history`
       is `[]` for a chain of length 1.
   11. *Consistent with §6.* It reports no direction of movement; see 2.5.

---

## 2. Does the design still hold?

Ranked by severity.

1. **The `supports` / `evaluated_node` default can raise a derived admission.**
   (Verified, probe2)
   - §3 says treating a support as a premise "can only lower a derived admission, never raise
     it". Under §4's no-vacuous-admission rule that is false.
   - A claim C whose only edge is `s supports C`, with s admitted: default gives C `admitted`;
     labelling the edge `used` gives `not_recorded`.
   - So the default raises C in exactly the case where it is wrong (s is corroboration, not
     reliance). Measured against RSI_REWARD's "every premise it relied on", it can turn
     "relies on nothing recorded" into "warranted".
   - The wrong decision is calling the default conservative. What would settle it: on real
     journals, the share of judgement nodes whose only `relied_on` premises come from
     `support_refs` or `evaluated_node`. Not available.
2. **`truncated` is not a completeness signal.** (Verified by reading; consequence shown on
   hand-built graphs in P5, P6, P12)
   - Unscoped builder: an unavailable premise record becomes an `issues` entry and its edge is
     filtered out, with `truncated` left false (`graph_memory.py:358-363`, `456`, `459`).
   - Scoped builder:
     - hard-codes `"truncated": False` (`graph_scope.py:432`)
     - limits the closure to `ordinary_hops` ∈ {0,1} (`:211-213`)
     - drops edges past that boundary (`:412-414`), recording them only in
       `scope_receipt.deliberate_boundary_refs` and `boundary_relations` (`:394-395`)
   - A bound owner whose withheld premise was dropped comes out `admitted` (P6). P12: the same
     bindings over a graph missing one edge move J from withheld to admitted.
   - The design reason ("missing premises would make a derived admission look better than it
     is") applies just as much to `issues`, the scope boundary and
     `reference_coverage_complete: false`.
   - Small detail: a scoped *page* is refused, but because its schema is `PAGE` and fails
     `validate_research_graph`, not because it is truncated.
3. **`ruling["admission"]` is not what the store admitted.** (Verified)
   - `CampaignStore` records `admitted = result.status == "ok" and ruling.teaches`
     (`store.py:564`, `648`).
   - An `Evaluation` with status `failed`, `blocked` or `invalid` may carry a finite value
     (`active/schema.py:140-148`). `rule()` then returns `admitted` while the store records
     admitted=0 (ran it).
   - A verbatim `Ruling.as_dict()` binding would therefore propagate `admitted` for
     observations the store refused. The quantity the design wants, admission at dispatch, is
     not computable from `ruling` alone.
4. **Constraint 4 cannot be protected by the view, and the binding is a free knob.**
   (Verified)
   - `ruling_digest` is self-certifying: anyone can compute `digest(ruling)`.
   - `dispatch_ref.action_id` is never checked against a store.
   - Store rows are `canonical(ruling.as_dict())` (`store.py:567`, `658`), so a binding built
     today from `observations.ruling` passes every check. That is the backfill §0.4 forbids,
     and the view cannot tell it apart.
   - Other probes:
     - P4: a fabricated superseding `admitted` ruling lifts J and is accepted.
     - P3: leaving out the withheld binding moves J from `withheld` to `not_recorded`.
     - P2: the same ruling bound to two nodes is accepted.
     - P14, P15: a supersede onto a different subject, and a `parent_id` that disagrees with
       `claim_scope`, are both accepted.
   - The design names D3 (waivers) as a knob but not this one: a loop that can write or omit
     bindings moves warrant. It needs recording as a D4.
   - What would settle it: an emission-point design whose binding carries something the store
     can verify, such as the event-log row of `action_resolved`.
5. **Ranking `not_recorded` above `withheld` makes omission an improvement.**
   (Verified P3; the consumer risk is inferred)
   - I5 holds: no derived value exceeds its premises' derived values.
   - But the design's own reason for the rank, "an unknown premise may be a withheld one",
     says the derived value can exceed what the premises truly justify.
   - `compare_views` reports `moved: True` with no direction. Any consumer that reads
     admission the way `Ruling.teaches` does (anything not withheld counts,
     `admissible.py:128`) treats `not_recorded` as teaching (inferred).
   - The reward must decide how it counts `not_recorded`.
6. **`premise_basis` reports one convention out of several.** (Verified)
   - §0.3 calls the whole classification `convention`, but only `unlabelled_default` is
     flagged.
   - Relation-less `depends_on` → `used` (`field_convention`) is the non-conservative
     direction: it can only raise a value, and it carries no flag.
   - For the two research-step decision emitters checked, `input_refs` equals `basis_refs`, so
     `relied_on` wins on the pair (`meta_context.py:604-606`; `method_revision.py:221-225`).
     Verified.
   - Inferred: evidence-window decisions treat `input_refs` as "decision conditioning"
     (`evidence_window.py:321-339`), which reads as premise-like.
7. **`compare_views` does not check `graph_view_id` or `view_id`.** (Verified P12, P13)
   Movement caused by a graph change, or a hand-edited view, is reported as an ordinary move.
8. **One §0 count is wrong. The counts, checked against code:**

   | Count | Result | Evidence |
   |---|---|---|
   | 11 EXACT∧WRONG_SUBJECT of 20 | Correct | Ran over `FAULTS` |
   | Cross-tab 11/2/3, 3/0/1, 0/0/0 | Correct | Ran over `FAULTS` |
   | Marginals 14/2/4, 10/10, 10/8/1/1 | Correct | Ran over `FAULTS` |
   | Unbounded 18 | Correct | Counted as `upper_kcal_mol is None` |
   | All 11 codes referenced outside `taxonomy.py` | Correct | grep |
   | 5 uncatalogued blocking codes | Correct | `admissible.py:171`, `221`, `228`; `store.py:439` |
   | 37 sites = 28 + 6 + 1 + 2; classes 28 / 2 / 1 / 6 | Correct | Read the emitters |
   | 4 → relied_on, 24 → used | **Wrong** | See below |

   - Under §3's own table the relied_on sites are `measured_result`, `evaluation_result` and
     `selection_basis`: 3, giving 3 / 25. Relation-less decision `basis_refs` is classified
     `used`, so it cannot be the fourth.
   - The "28 relation labels" are 28 call sites but 27 distinct labels: `evaluated_use`
     appears twice (`method_links.py:70`, `76`).
   - On `CampaignStore` rows only 2 of the 5 uncatalogued codes can occur: `Evaluation`
     enforces finite values and the store passes `require_comparator=False`.
9. **The normative source is contradicted.** `RSI_REWARD.md:22-23` said "the relation between
   them is an edge that already exists". §0.3 and §0.4 show neither a `relied_on` edge nor a
   node-to-ruling join exists. RSI_REWARD.md needs amending, not only this design.
10. **Low: label keys can collide** (inferred). A `"from|to"` label key can match a
    `supports` edge and an `evaluated_node` edge with opposite owners on the same ordered
    pair.

---

## 3. What can now be claimed, and what cannot

**Can be claimed (verified):**
- A pure function exists that refuses the inputs §7 I8 lists and propagates min-admission
  along §3's classification over hand-built graphs.
- `rule()` was not modified.
- 42 tests pass in one unpinned Python 3.12.14 environment.

**Cannot be claimed:**
- **Any node-level admission on existing records.** No bindings exist; every node is
  `not_recorded`.
- **Any warrant rate or reward figure.** D1–D3 are open, and the binding/omission knob (2.4)
  is unrecorded.
- **That a derived `admitted` means "every premise it relied on was admissible".** Three
  things defeat it: dropped edges with `truncated: false` (2.2), the default raising
  sole-support claims (2.1), and the gap between ruling and store admission (2.3).
- **That bindings were written at dispatch,** or that a binding names the right subject.
- **That the classification is measured, or that the default is conservative.**
- **That the view works on real graphs.** No test runs it on a graph from
  `build_research_graph`. The fixtures carry no `view_id`, so the graph digest check is
  skipped.
- **Edge-class counts over real journals.** Not taken.
- **Anything from the full suite about this change.** 537 failed / 340 errors were dominated
  by missing dependencies; the related suites were not separated out.
  `tests/test_graph_pages.py` errors at collection in that run.

What a passing test here shows is behaviour on synthetic inputs, not a scientific result.

---

## 4. Open items

- The project needs a fixed Python ≥3.11 environment; this round's test results are
  reproducible only against the `/tmp/etalon-venv` freeze and carry lower evidential weight
  than results in a fixed environment.
- Decide whether the `supports` / `evaluated_node` default stays `relied_on`, given that it can
  raise an admission (2.1). Settle it with incidence data from real journals.
- Replace or augment `truncated` as the refusal signal with `issues`, the `scope_receipt`
  boundary fields and `reference_coverage_complete` (2.2).
- Decide whether a binding carries the store's `admitted` / `status`, or whether the view
  refuses or derives it (2.3).
- Record D4: bindings that are caller-written or omitted are a warrant knob. The
  emission-point design must make a binding verifiable against the store, which is what
  protects constraint 4 (2.4).
- Decide how the reward counts `not_recorded`, and whether `compare_views` reports direction
  and checks `graph_view_id` / `view_id` (2.5, 2.7).
- Fix the design's 4/24 split to 3/25, or reclassify relation-less decision `basis_refs`
  (2.8). Amend `RSI_REWARD.md:22-23` (2.9).
- Record decisions on the implementer's interpretations 2, 5, 6, 8, 9 and 10.
- Test gaps that the surviving mutants show:
  - a binding built from real `rule().as_dict()` output, and an inconsistent
    admission/blocking ruling
  - I1 with `require_comparator=False` and a non-finite expensive value
  - I2 with a binding that has no `supersedes`
  - I3 and `limiting_leaves` two or more hops up
  - `catalogue_digest` field membership
  - the extra binding validations
