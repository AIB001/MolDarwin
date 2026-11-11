# Two assessment regimes, and the membrane between them

Status: design v1, 2026-11-09. Decision record in ADR form. The `docs/adr/` series
referenced at `README.md:898-905` is absent from this checkout, so this record takes no
number from it and is named after its subject, following the convention of every other
file in `docs/thin-harness/`.

Normative sources: `RSI_REWARD.md` (why the reward must be internal),
`ADMISSION_PROPAGATION.md` §3–§5 and §10.3–§10.4 (edge classification and propagation),
`ADMISSION_PROPAGATION_DECISIONS.md` (D4, D5, D6). Binding conventions: `CLAUDE.md`.
Companion: `HARDENING_CRITERION.md` (which layer a future change belongs in).

Terminology follows `CLAUDE.md` verbatim: `completion` / `verification` / `admission`;
`relied_on` (admission propagates along this edge) vs `used` (does not). Where a claim is
about repeatability it says **precision**; where it is about agreement with a measured
quantity, **validity**.

Citations were read on 2026-11-09 against the working tree. Two other sessions were
editing `src/` concurrently, so each citation quotes the text it relies on; if a line
number has moved, the quoted text is the claim.

---

## 0. The decision this record exists to stop being ambiguous

`research/journal.py:230` reads:

```python
if value.assessment_role == 'diagnostic':
    return
```

A previous review read all 244 source files under `src/etalon` and could not determine
whether that early return was a deliberate two-regime design or an accretion
(`etalon-architecture-review.md:623-629`). It made the answer the question that most
changed its own top-ranked proposal, and asked a human.

The split is deliberate and wanted. The repo owner confirmed it. **That confirmation is
the fact this document records**, because the defect was never in the early return: it was
that a reader with the whole source in front of them could not tell design from accident.
A two-regime system whose second regime is invisible in its own documentation has one
regime and a bug.

Three parts a working two-regime system needs were missing. §2–§4 decide them.

## 1. The two regimes

`MethodEvaluation.assessment_role` ∈ {`diagnostic`, `independent_validation`}
(`research/schema.py:285`, validated at `:297`: `raise ValueError('unknown method
assessment role')`). It is the only regime field in the research schema: a repository-wide
search for `assessment_role` outside `asset/` returns six sites, all of them this field's
definition, its default, its propagation into the journal validator, and its projection
into the graph (`schema.py:285,297`; `composition.py:245,271`; `journal.py:230`;
`graph_memory.py:243`). Evidence: `measured_here`.

### 1.1 What `diagnostic` buys

Everything after the early return is skipped, and each skipped check is a cost that
`diagnostic` does not pay:

| `independent_validation` must | `journal.py` | `diagnostic` instead |
|---|---|---|
| carry actual results and `accounting_refs` | `:232-233` | may carry neither |
| bind subjects, comparators, protocol, split and initial conditions into a frozen `phi-` policy's `search_configuration['method_evaluation']` before release | `:234-246` | needs no predeclaration |
| hold `validation-` receipts from that frozen policy, on a held-out task, from the frozen initial state | `:240-251` | may use any result |
| carry evidence whose `Artifact.role` is `independent_validation` or `sealed_holdout` | `:252-254` | may use `diagnostic` bytes |
| have recorded every input **before** the freeze | `:259-261` | no chronology |
| have recorded every evidence artifact **after** the freeze | `:262-263` | no chronology |
| present bytes no earlier artifact row already holds | `:264-269` | may reuse seen bytes |

Citation freshness: these numbers were re-derived at the end of this round, after
concurrent edits to `research/journal.py` by another session. The architecture review cites
the same two quoted refusals as `:258-260` and `:263-269`
(`etalon-architecture-review.md:46-49`); they are the same text at `:259-261` and `:264-269`
here. Where the two disagree, the quoted text is the claim.

So `diagnostic` buys: no predeclaration, reuse of already-seen bytes, cheap proxies, and no
comparator pairing. Those are the four things a cheap exploratory pass needs, and refusing
them would not make the record more honest — it would make the exploratory pass
unrecordable, and an unrecorded pass is worse evidence than a `diagnostic` one.

### 1.2 What `diagnostic` structurally cannot do

It cannot **be relied on**. Not as a policy, as a consequence: every check in §1.1 is a
check about provenance, and a record that skipped all of them cannot distinguish a result
the host predicted from a result the host had already seen. The host may have seen the
answer; the record cannot say it did not.

This is the same shape `learn/admission_view.py:96` already names elsewhere. The
`visible_at_selection` relation is classified `used` with `class_basis
"record_cannot_settle"` because the record states visibility and `method_links` forbids
inferring actual use. `diagnostic` is that case one level up: the record states a regime
in which the question of prior sight was never asked.

### 1.3 Why the membrane is native, not an addition

`RSI_REWARD.md:91-95` argues that **no split of an external benchmark protects against
learning the verifier**, because splitting by instance leaves the verifier shared across
both halves, so a revision that learned the verifier also scores better on the held-out
half. Its conclusion is that the protection has to be that the reward is internal.

The two regimes are that argument localised to the record. `diagnostic` is where the
verifier may be learned freely **because nothing propagates**. `independent_validation` is
where it may not, and there the protection is not a claim: it is freeze chronology
enforced on a durable event sequence (`journal.py:259-261`) plus content-addressed
anti-laundering over unseen bytes (`journal.py:264-269`).

**The membrane is the RSI reward restriction expressed at edge-classification time rather
than at reward time.** That is the unifying idea, and it is why the membrane belongs in
`admission_view.py` and not in a new module: the restriction already had a home, and the
home is where admission stops travelling.

## 2. Decision 1 — entry is explicit

**A regime you can enter by forgetting is not a regime.**
`research/composition.py:245` defaults `assessment_role="diagnostic"`, so the weak regime
is today entered by omission.

Decided: `assessment_role` is a required argument. The host names the regime it is working
in, every time. Omission is a refusal, not a default.

Design decision, not a fact about the code. The implementing session owns the call-site
shape; this record owns only the requirement that no value be supplied on the host's
behalf. It is the cheapest possible instance of the hardening criterion
(`HARDENING_CRITERION.md` §2): an omitted regime is indistinguishable from a chosen
`diagnostic` the moment the record is written, and no later reader recovers the
difference.

Not a backfill. Existing records keep the regime they were recorded with, and records that
carry none are treated by §4.

**As implemented, in two stages.** Read 2026-11-09 after the implementing session landed
`research/composition.py::record_evaluation`: an omitted `assessment_role` raises a
`DeprecationWarning` naming the consequence, then records `assessment_role` of
`"diagnostic"` with a new field `assessment_role_basis` of `"defaulted_deprecated"`; an
explicit value records `assessment_role_basis` of `"explicitly_declared"`. That is a
staging of this decision, not a departure from it, and it is the better first move: the
omission is now **recorded as an omission**, so the two populations are countable and the
later refusal can be made against a measured count instead of a guess. The decision this
record holds is that omission must never be silently defaulted.

**Decision, 2026-11-10: the warning does not become a refusal, and this item is closed.**

The hardening criterion answers it determinately once the question is asked in its terms:
after the session, is an omitted regime distinguishable from a chosen `diagnostic`? **With
`assessment_role_basis` recorded, yes — exactly.** `defaulted_deprecated` against
`explicitly_declared` *is* that distinction, and `learn/admission_view.py` already acts on
it (`regime_not_declared` degrades the edge). The indistinguishability that would justify
hardening was removed by the basis field itself, so by `HARDENING_CRITERION.md` §2 the
refusal is not warranted, and by its corollary the hardened set stays small.

Waiting for the `defaulted_deprecated` count is also a deadlock dressed as diligence. The
real population is four records, none of which carries a basis at all because they predate
the field (measured read-only on `2xpro6000`, 2026-11-10; Evidence `measured_here`), and new
omissions will arrive a handful per campaign. A count that will never be decisive is not
evidence a decision is waiting on.

**And the refusal that matters already exists, at the reliance boundary rather than the
write.** Three things now hold the line in the right places:

- the impossible pair is refused outright — `schema.py:312` rejects `defaulted_deprecated`
  on a non-`diagnostic` role;
- the undeclared regime cannot be relied on — the membrane degrades the edge;
- the over-claim is refused — `research/decision_rule.py` refuses a `claim` of `supported`
  against a replayed `criteria_failed`, `insufficient` or `not_declared`.

An omission alone is harmless because nothing propagates from it. Omission *plus* an
over-claim is the `snd1-gradient-20261023-03` shape — *"adopt: predeclared equivalence…"*
recorded in the regime that skips predeclaration — and that is the case the third refusal
covers. So the pattern is: **refuse the impossible, degrade the unestablished, and refuse
the claim that outruns its own rule.** Refusing the write would instead cost the host a turn
every time it records an evaluation before settling the regime, and settling the regime is
method judgement, which `HARDENING_CRITERION.md` §3 keeps free.

**What this decision owes, and it is now paid.** "Never refuse" is honest only while the
population is *visible*: a set nothing reports grows unwatched, and "it is countable" is not
a count. An earlier revision of this section claimed the share was already reported in a
coverage block. It was not — the membrane reported `by_class_basis` over **edges** and
nothing counted the **records**. That claim is the exact failure this document exists to
refuse, so it was removed and the count implemented:
`learn/admission_view.py::_role_basis_census` reports, inside the `membrane` block,
`explicitly_declared` / `defaulted_deprecated` / `not_recorded` over the stated denominator
of records carrying an assessment role. Three answers rather than two, because a record
predating the field is a different fact from an omission its writer was warned about — and
`not_recorded` is every real record measured so far (4 of 4). Held by
`test_admission_view.py::test_an_omission_that_was_recorded_is_counted_apart_from_a_record_that_predates_the_field`.

## 3. Decision 2 — the membrane

### 3.1 What it does

`ADMISSION_PROPAGATION.md` §3 classifies each graph edge into `premise_class` ∈
{`relied_on`, `used`, `not_premise`} with a `class_basis`. The membrane adds one rule to
that classification:

> **An edge whose premise side is a method-evaluation node that is not
> `independent_validation` is classified `used`, with a `class_basis` of
> `regime_cannot_settle` — or, where the regime is absent rather than declared weak,
> `regime_not_declared` (§4).**

The basis strings mirror the existing `record_cannot_settle`
(`learn/admission_view.py:96`) deliberately: same reason, one level of abstraction up. The
record cannot settle it, because the regime it was recorded in never asked.

Nothing else changes. `used` already does not propagate (`ADMISSION_PROPAGATION.md` §4,
invariant I7), so the membrane needs no new propagation rule, no new `Admission` value and
no new output field beyond the basis string.

### 3.2 Scope — read this before implementing

The regime is **already in the graph**. `research/graph_memory.py:241-243` projects, for
`schema == "etalon-method-evaluation/1"`, a node field
`node["evaluation"]` carrying the keys `("subjects", "comparators", "assessment_role",
"conclusion", "scope")`. The membrane therefore reads an existing projected field. No
schema change, no emission-point change, no write of any kind. Evidence: `measured_here`.

Only `etalon-method-evaluation/1` nodes carry a regime. Four cases, and the fourth is the
one that matters:

| premise node | regime | classification |
|---|---|---|
| `etalon-method-evaluation/1`, `assessment_role == "independent_validation"` | declared strong | unchanged (§3 table applies) |
| `etalon-method-evaluation/1`, `assessment_role == "diagnostic"` | declared weak | `used`, basis `regime_cannot_settle` |
| `etalon-method-evaluation/1`, regime absent or unreadable | unknown | `used`, basis `regime_not_declared` (§4) |
| any other node schema | **not applicable** | unchanged (§3 table applies) |

**`not_applicable` is not `unknown`.** A measurement, an action receipt, a research step or
a decision has no `assessment_role` and was never meant to; demoting those edges would cap
every node in the view at `not_recorded` and the membrane would have destroyed the view
instead of sealing it. The membrane constrains *evaluation* reliance only. Stated as a
limit in §6.

### 3.3 Which edges this actually bites on

The membrane is defined on the premise node's regime, not on the relation, so it needs no
list of relations to stay correct. Two concrete routes exist today:

- `method_links.py:75` — an `etalon-research-step/1` record with `operation ==
  "evaluation"` emits `add([detail["evaluation_ref"]], "evaluation_result")`, and
  `evaluation_result` is `relied_on` with basis `declared_relation`
  (`admission_view.py:26`; `ADMISSION_PROPAGATION.md` §3). This is the edge from an
  evaluation step to the `MethodEvaluation` it is a step of, and it is the membrane's main
  case.
- `method_links.py:79` — a `decision` step emits `add(detail["basis_refs"],
  "selection_basis")`, also `relied_on`. Whenever a decision's `basis_refs` names a
  method-evaluation record, the membrane applies there too. Which schemas permit that was
  not enumerated; the relation-agnostic rule covers it without the enumeration.

The other two `relied_on` relations are unaffected in practice: `measured_result` targets
`result_refs` (`method_links.py:58`), which are action and artifact references, not
evaluations. `supports` and `evaluated_node` already default to `used`
(`ADMISSION_PROPAGATION.md` §10.3).

### 3.4 What the membrane does *not* do

It does not lower a `diagnostic` node's own derived admission. A diagnostic evaluation
whose own `measured_result` premises were admitted reads `admitted` **for itself**, and
that is the honest answer: the measurement was admitted. The membrane stops it being
somebody else's premise. This is what "the verifier may be learned freely because nothing
propagates" means operationally — the diagnostic lane keeps its full value as a lane and
loses it only as a foundation.

It writes nothing, reads `rule()`'s output as written, and calls `rule()` never
(`ADMISSION_PROPAGATION.md` §2, invariants I1 and I2).

### 3.5 Ordering against pair resolution

`ADMISSION_PROPAGATION.md` §3 resolves classification per `(owner, premise)` pair, with
`relied_on` winning if any edge between them is `relied_on`. **The membrane applies after
that resolution, to the resolved pair.** Applied before it, a second `relied_on` edge
between the same pair would silently undo the demotion, and the membrane would hold
everywhere except where two edges happen to exist — the exact shape of guard that
`docs/adr/0006` is named for (`README.md:446`).

### 3.6 Invariants

Each must be held by a test. Numbering continues `ADMISSION_PROPAGATION.md` §7 / §10.8.

- **I13 — the membrane demotes.** For a graph where an evaluation step relies on a
  `diagnostic` `MethodEvaluation` with an `admitted` leaf, the step's derived `admission`
  and `exact_admission` are no better than they would be with that edge absent, and the
  resolved pair carries `class_basis "regime_cannot_settle"`.
- **I14 — `independent_validation` is untouched.** The same fixture with
  `assessment_role == "independent_validation"` propagates exactly as before the change;
  every other node's row is byte-identical to the pre-change view at the same
  `view_version`.
- **I15 — the diagnostic node keeps its own value.** In I13's fixture, the
  `MethodEvaluation` node's own derived `admission` is unchanged by the membrane.
- **I16 — scope.** A graph containing no `etalon-method-evaluation/1` node produces a view
  byte-identical (modulo `view_version`) to the pre-change one. No node schema other than
  `etalon-method-evaluation/1` is demoted by regime.
- **I17 — pair resolution order.** Two `relied_on` edges between the same owner and the
  same `diagnostic` premise resolve to `used` with basis `regime_cannot_settle`, not to
  `relied_on`.
- **I18 — unknown is weak.** A method-evaluation node whose projected `assessment_role` is
  `None`, or any string outside {`diagnostic`, `independent_validation`}, demotes
  as `diagnostic` does — to `used`, never refused (§4) — and is distinguishable in the
  output from a declared `diagnostic`. An **absent** key is a fourth case and is
  unreachable rather than unimplemented: `MethodEvaluation.assessment_role` is required
  with no default, so a block lacking the key is not a real projection and reads as
  `not_applicable`, preserving the §3.2 distinction. The field requirement is what makes
  this safe, so a test holds the requirement itself; see
  `ADMISSION_PROPAGATION.md` §11.6 I18 for the amendment and the test name.

`view_version` must move: the view carries per-edge `class_basis` and the output's
`view_id` is a digest of its own content, so a new basis string changes stored digests and
`compare_views` must refuse to compare across the change rather than mix
(`ADMISSION_PROPAGATION.md` §10.6). Views are rebuilt, not migrated.

## 4. Decision 3 — the regime-unknown treatment

Records predating this change, and any record whose projected regime cannot be read, may
be `used` and are **never** `relied_on`.

Three properties of that choice:

- **It is conservative in the direction `admissible.py` already argues for.** Withholding
  one good premise costs the information in one record; admitting one bad premise costs
  every conclusion built on it afterwards. This is D5's own reasoning
  (`ADMISSION_PROPAGATION_DECISIONS.md:70-78`), applied to a regime instead of an edge
  type.
- **It is not a backfill.** Nothing is written, no stored record changes, and no admission
  is assigned to a historical node. The regime is read from the record as it stands, or
  from its absence, at view time. Hard constraint 4 holds because the view is a read-only
  derived export (hard constraints 1 and 2).
- **It is not a refusal.** An unreadable regime produces a weaker classification, not an
  exception. Refusing would make the view uncomputable over existing records, and
  `RSI_REWARD.md:28` already concedes that historical nodes are permanently
  `not_recorded`. The membrane does not need to re-announce that.

Both cases demote for the same reason — the record cannot settle whether anything was
predeclared, in one case because it says `diagnostic` and in the other because it says
nothing — and the two must stay **countable apart**, because the populations call for
different responses: a declared `diagnostic` is a lane working as designed, an absent
regime is a records problem. Nothing is computed from the distinction; it exists so the
two can be reported separately.

**As implemented** (read 2026-11-09, `research/assessment_regime.py` and
`learn/admission_view.py`): two basis strings rather than one with a discriminator —
`regime_cannot_settle` for a declared `diagnostic`, `regime_not_declared` for an absent
or unreadable regime, alongside a `NOT_APPLICABLE` state for schemas that carry no regime
(§3.2's fourth case). The record side gained `assessment_role_basis`
(`explicitly_declared` / `defaulted_deprecated`, §2). This satisfies the requirement more
directly than the single-string form proposed above and is the shape to follow; the
requirement is that the two populations be separable in the output, not which identifiers
carry it. **The ADR is normative on the semantics; the implementation owns the
identifiers.**

### 4.1 The route-around risk is answered by the membrane, not by a report

A stricter `independent_validation` path invites hosts to record everything as
`diagnostic`. The architecture review judged this should be reported rather than prevented,
because `diagnostic` is a legitimate role and forcing the stronger one would make the
record less honest, not more (`etalon-architecture-review.md:209-213`). That judgement is
correct and this design keeps it: nothing here refuses a `diagnostic` record.

With the membrane, the route around is self-defeating without being blocked. A conclusion
whose only premises are `diagnostic` has no `relied_on` premise, so §4's no-vacuous-admission
rule gives it `not_recorded`, and D4 counts `not_recorded` as a **loss** — in the
denominator, not the numerator (`ADMISSION_PROPAGATION_DECISIONS.md:61-68`). Recording
everything as `diagnostic` therefore earns nothing instead of earning warrant cheaply.

The ratio of `independent_validation` to `diagnostic` records per window is still worth
reporting (`etalon-architecture-review.md:223-226`), now as an observation about how the
lanes are used rather than as the detector of a loophole.

## 5. Decision 4 — the promotion ritual

### 5.1 Promotion is a redo, and that is enforced by data

There is no conversion of a `diagnostic` record into an `independent_validation` one, and
no flag that effects one. The reason is not policy:

- inputs must have been recorded **before** the freeze — `if self._record_sequence(db, ref)
  >= frozen_at: raise StateError('method evaluation inputs must be recorded before the
  policy freeze')` (`journal.py:259-261`);
- evidence must be recorded **after** it (`journal.py:262-263`);
- and bytes an earlier artifact row already holds cannot be relabelled — `'already seen
  artifact bytes cannot be relabelled as independent validation'` (`journal.py:264-269`).

A diagnostic run's bytes exist and are recorded. Any attempt to carry them across is
refused by name. Promotion is therefore a **fresh freeze and unseen bytes**, which is to
say: a new experiment that the diagnostic pass told you was worth running.

### 5.2 The procedure

The host follows this; the harness refuses the steps that are refusable. Chronology is the
whole content, so the order is not a presentation choice.

1. **Decide what the diagnostic pass established.** It established a hypothesis and a
   method worth paying for. It did not establish a result. If there is nothing you would
   now predict in advance, there is nothing to promote.
2. **Declare the evaluation contract first.** Metrics with an `operator` and a finite
   numeric `threshold`, and `missing_policy = "insufficient"` so a missing value cannot
   aggregate into a pass (`research/evaluation_contract.py`; statuses are
   `{criteria_passed, criteria_failed, insufficient, incomparable}` at `:23`). Take its
   `evaluation_rules_digest`, which is stable under a change of observed inputs, so the
   declared rule can be replayed against new evidence without its identity moving.
3. **Record every input, then freeze.** The subjects, comparators, `protocol_ref`,
   `task_split_ref` and `initial_conditions_ref` must all exist as records before the
   freeze (`journal.py:259-261`). Recording them afterwards is refused, and no later work
   repairs it.
4. **Freeze the policy.** A `phi-` policy whose `split_id` equals the `task_split_ref` and
   whose `search_configuration['method_evaluation']` equals the exact binding of subjects,
   comparators, `protocol_ref`, `task_split_ref` and `initial_conditions_ref`
   (`journal.py:234-246`).
5. **Acquire unseen bytes.** Run on the held-out task from the frozen initial
   configuration. Evidence artifacts carry `role` ∈ {`independent_validation`,
   `sealed_holdout`} (`journal.py:252-254`; `research/schema.py:47-48`), are recorded after
   the freeze, and must not match the bytes of any artifact recorded at or before it.
6. **Write the admission binding at dispatch.** Not afterwards: hard constraint 4, and
   `ADMISSION_PROPAGATION.md` §0.4 and §10.1. A record whose binding is missing is
   `not_recorded`, which D4 counts as a loss — so the binding is part of the ritual, not
   bookkeeping after it.
7. **Record the evaluation** with `assessment_role="independent_validation"`, non-empty
   results and non-empty `accounting_refs` (`journal.py:232`). Cost is structurally beside
   quality here, not optional.
8. **Leave the diagnostic record alone.** It is not superseded, amended or withdrawn.

### 5.3 The diagnostic record survives promotion, and stays citable

Step 8 is a decision, not an omission. `supersedes` "preserves the earlier record and claim
scope; it does not erase it" (`ADMISSION_PROPAGATION.md` §5, quoting `RESEARCH_GRAPH.md`),
and hard constraint 3 requires the old value and claim scope to be kept. But the promoted
record is not a superseding version of the diagnostic one: the two are about **different
bytes** by construction (§5.1), so they have different claim scopes and neither replaces
the other. **Design decision:** do not emit `supersedes` between them.

What the diagnostic record remains is a `used` input to the promoted work — where the
hypothesis came from, recorded, visible, and not propagating. That is exactly the
classification §3 gives it, which is the sign the membrane and the ritual are one design
rather than two.

### 5.4 What promotion does not buy

- It does not make the conclusion right. It makes the conclusion one the host predicted
  before seeing the answer.
- It does not make the metric meaningful. A predeclared threshold on a quantity
  uncorrelated with activity is a predeclared threshold on a quantity uncorrelated with
  activity (`RSI_REWARD.md:28-32`).
- It does not establish a transferable gain. One promoted evaluation is one task.
- It does not count as a win under waiver: the reward counts only `Admission.ADMITTED`,
  and `admitted_under_waiver` is reported separately and charged to cost
  (`RSI_REWARD.md:61-65`).

## 6. Limits, and what this record does not decide

- **Reliance that does not pass through an evaluation node is not covered.** The membrane
  is scoped to `etalon-method-evaluation/1` premises (§3.2). A decision relying directly on
  a measurement is unaffected by regime, because a measurement has no regime to declare.
  Whether some reliance paths should be regime-bearing is open and is not decided here.
- **The membrane does not make the view non-empty.** Over existing records every node is
  `not_recorded` for want of a binding (`ADMISSION_PROPAGATION.md` §8), and an unscoped
  graph never asserts completeness (§10.4). The membrane changes what happens once
  bindings exist; it does not create them.
- **Not taken: how many edges the membrane demotes on real records.** It needs journals,
  and none are present on this machine (`ADMISSION_PROPAGATION.md` §0.1). Per hard
  constraint 7 this is reported as not taken, not estimated. What is taken is the count of
  emission sites it can reach: 2 of the 3 `relied_on` relation sites
  (`ADMISSION_PROPAGATION.md` §0.3), by the argument in §3.3.
- **D1–D3 stay open**, and the exact facet (`ADMISSION_PROPAGATION.md` §10.2) is demoted by
  the membrane on exactly the same edges as the base facet. No separate rule.
- **Whether `independent_validation` should become the default is not decided and should
  not be.** The review raised it as the alternative to this design if `diagnostic` had been
  an accretion (`etalon-architecture-review.md:626-629`). It was not. With explicit entry
  (§2) there is no default to argue about.
- **No reward figure.** The decisions file's single critical-path instruction stands: do
  not report any reward number before the dispatch link exists
  (`ADMISSION_PROPAGATION_DECISIONS.md:107-109`).

## 7. Hard-constraint compliance

| constraint | how this holds |
|---|---|
| 1. `rule(Measurement) -> Ruling` semantics unchanged | nothing here reads or edits `learn/admissible.py`; the membrane is a classification rule in the derived view |
| 2. the export view does not write back to leaf records | the membrane reads `node["evaluation"]["assessment_role"]` as projected (`graph_memory.py:243`) and writes nothing |
| 3. admission state changes keep the old value and claim scope | no state change; §5.3 declines to emit `supersedes` between records with different claim scopes |
| 4. `admission` is written at dispatch, never backfilled | §4 derives at view time from the record as it stands; §5.2 step 6 keeps the binding at dispatch |
| 5. every new number carries an Evidence class | the counts in §1 and §6 are marked `measured_here`; the classification itself is `convention`, as `ADMISSION_PROPAGATION.md` §0.3 marks its own |
| 6. no store merge, nothing under `asset/` | no store is opened; `asset/` is untouched and was not read |
| 7. a quantity that cannot be counted is reported as not taken | §6 reports the demotion incidence as not taken rather than estimating it |

## 8. Claims in this record that are decisions rather than facts

Marked here so a later reader need not re-derive the distinction: the requirement in §2
that omission never be silently defaulted; the separability requirement in §4;
the ordering requirement in §3.5; the scoping to evaluation nodes in §3.2; the decision in
§5.3 not to emit `supersedes`. Everything in §1, §3.2's projection claim, §3.3's emission
sites and §5.1's refusals is a fact about the code with the quoted text as its citation.

---

## 7. Decision, 2026-11-10: where a loose internal benchmark lives, and why it needs no new mechanism

The owner's stated design for driving RSI is an **internal benchmark that is deliberately
loose and flexible, possibly an LLM judge**, with the explicit qualification that it exists
to make the loop turn and that doing without it would be acceptable.

**That instrument is already defined by this document. It is a `diagnostic`-regime
instrument, and that is the whole of the answer.** §1's lane buys exactly what such a judge
needs — no predeclaration, reuse of seen bytes, cheap proxies, no comparator pairing — and
costs exactly what such a judge must be made to cost: it structurally cannot be relied on.
So the design requires **no new record type, no new regime value, and no new refusal.** A
judge verdict recorded as an `etalon-method-evaluation/1` with
`assessment_role: "diagnostic"` is handled by the membrane as built.

This is the use case that makes the `diagnostic` lane load-bearing rather than theoretical,
and it is worth saying why the fit is exact rather than convenient. `RSI_REWARD.md`'s
argument is that no split of an external benchmark protects against learning the verifier.
An LLM judge is *easier* to learn than a fixed scorer, because it is reachable by persuasion
rather than by being right. The two regimes are that argument localised to the record:
`diagnostic` is where the verifier may be learned freely **because nothing propagates**. A
loose judge is therefore not a weakening of the design — it is the case the design was
drawn for.

### 7.1 The one thing that had to change, and it was a defect not an addition

A loose judge's verdicts do not stay verdicts. An RSI loop consolidates them into lessons,
and §12 of `ADMISSION_PROPAGATION.md` records what was found when that path was traced: an
`etalon-method-experience/1` was **outside the membrane's scope** while being a legal
premise ref, and a human label on a `supports` edge from one could promote it to
`relied_on` with nothing to stop it. So the lesson route was how a loose judge's verdicts
would have become premises.

That is now closed (`not_an_assessment` / `lesson_cannot_settle`, view version `/4`). Note
what kind of change it was: **a defect with a newly named subject, not a new mechanism.**
Before the owner stated this design, the hole had no subject and the honest thing was to
record it; the design supplied the subject and the fix became owed.

### 7.2 What must stay outside the judge's reach, stated precisely

Not "the scorer", which is the obvious answer and the wrong one. The precise statement is
the line `research/contract_spec.py` already holds: **publish the specification, never the
oracle.** The measured reason is in this repository's own figures — on an external benchmark
8 of 9 failures were on a single metric the agent could not read, so locking the criterion
away is not safety, it is the defect. What must be unreachable is the **verdict**; what must
be readable is the **rule**.

A loose judge changes nothing about that division. It may read any specification; its own
output is a diagnostic; and if a conclusion is to rest on it, the promotion ritual of §5
applies in full — a fresh freeze and unseen bytes, not a relabelling.

### 7.3 And if there is no internal benchmark at all

The owner's qualification — that it would be acceptable to have none — is worth recording as
the stronger position, because it is the one the first principle actually requires. Nothing
in this architecture needs an internal score to function. Admission is not a score; it is
whether a result may serve as the basis of a conclusion, and it is computed from faults,
provenance and propagation, none of which asks how well the work went. A loose benchmark is
a convenience for *driving* a loop. It is never what makes the loop's output admissible, and
an architecture that came to depend on one would have substituted a measure for a judgement.
