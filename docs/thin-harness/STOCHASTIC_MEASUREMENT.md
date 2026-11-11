# A single draw is not a measurement: specification, not implementation

Status: **specification only.** Nothing described here is implemented, and the files it names are
owned by nobody in the current round. It is written so that the decision can be taken with the
shape in hand rather than discovered during the change.

Terminology follows `CLAUDE.md` verbatim: **completion** / **verification** / **admission**;
**relied_on** (admission propagates) vs **used** (does not); Evidence provenance `measured_here` /
`measured_in_an_asset` / `literature` / `convention`. Where a claim is about repeatability this says
**precision**; where it is about agreement with a measured quantity, **validity**.

## 1. The claim

A value drawn once from a stochastic oracle is a draw. A measurement is a draw plus a declared
**aggregation policy** (how many draws, how they combine, what counts as present) and a
**dispersion figure** over those draws. Absent either, the honest record is `evaluable=False` — the
observable could not be evaluated — and not a number with a caveat attached.

The distinction ETALON already draws correctly is that this is a **precision** defect and not a
**validity** defect. `Consequence.UNVERIFIABLE` blocks a claim and never a spend, and
`judgment/waiver.py` refuses a waiver for `F_RUN_NOT_REPRODUCIBLE` outright because *"it does not
block a spend — it invalidates a claim about the run — so there is nothing for a waiver to
release."* Nothing in this specification proposes that a single draw block a spend. ADR 0002 found
that band and consequence are different questions, and this change must not re-conflate them.

## 2. The evidence, and why one run cannot carry it

An external grader pinned its stochastic model's seed, which made its scores bit-reproducible.
Across five seeds the same metric's spread was **0.0000 on one task and 0.1364 on another**.

Two things follow and both are load-bearing.

A seeded run is reproducible and is not therefore robust. Determinism is a property of the
pipeline; dispersion is a property of the question. Pinning the seed removes the evidence of
dispersion without removing the dispersion, which is strictly worse than leaving it unpinned,
because an unseeded run at least announces that it cannot be reproduced.

**Dispersion is a per-task property and is invisible from one run.** A pooled figure over those two
tasks describes neither. So a dispersion figure is reported per task and never pooled, and a task
whose dispersion cannot be computed because it has one draw is reported as **not taken**, never as
zero dispersion — hard constraint 7, and the trap that makes this specification necessary rather
than obvious: zero is the value a missing spread most resembles.

## 3. Where the general form belongs

ETALON already has the right instinct in exactly one place, and the general form is that place's
argument moved up one level.

`runtime/executors.py` registers the replicated MM-PBSA executor and **refuses to dispatch it**:

> Refused explicitly, because the alternative is worse than an error. … a three-replica endpoint
> would quietly run as one unseeded trajectory per action and report the result under a protocol id
> that claims recorded seeds and a known energy author. Registration is complete and the frozen
> inputs stay valid; only dispatch is unwired.

That is the whole specification in one branch, for one executor kind. Shipping an error instead of a
plausible number is the correct decision and it was taken at cost. The general form is: **the same
refusal, keyed on a declared aggregation policy rather than on an executor kind.**

Four candidate homes, in descending order of fit. The recommendation is the first; the others are
recorded because each was considered and each is wrong for a stated reason.

### 3.1 Recommended: the endpoint's protocol declaration, with the refusal at dispatch

The aggregation policy belongs beside the protocol that produced the readout, because that is where
the rest of the readout's identity already lives. `active/cascade.py` digests a `Readout` into a
`protocol_id`, and `active/store.py` refuses *"protocol changed under an existing id; register a new
endpoint id"*. An aggregation policy folded into that digest therefore inherits three properties
for free: changing it is a new protocol rather than a silent reinterpretation; two campaigns that
aggregated differently cannot be compared under one id; and an alias is already refused — *"this
protocol is already registered; a new alias is not a new experiment."*

The refusal belongs at dispatch, beside the one that already exists, because that is the point at
which a policy declaring five independent draws either has five authorised seeds or does not.
`active/prism.py` already authorises one distinct seed per replicate and refuses *"independent
repetitions need distinct integer seeds"* and *"no authorized seed for this action; next-round plan
is not dispatch permission"*; `runtime/executors.py` already refuses a repeated seed with *"a
repeated seed is a retry, not a replica"*; `active/model.py` refuses duplicate action identities as
replicates; `active/cascade.py` refuses a fixed-seed cascade as a replica source; and
`active/adapters.py` refuses `PrismStage` as a certifier of independent replicas. **Every refusal
this change needs already exists.** What is missing is the declaration they would be refusing
against.

### 3.2 Rejected: a new `Fault` code

A fault is a cause of a *wrong number*. "Nobody declared how these draws combine" is not a cause of
a wrong number; it is the absence of a measurement definition. Adding it would also move
`catalogue_digest()`, invalidating every cross-version comparison, and `RSI_REWARD.md` is explicit
that a comparison whose two sides do not share the catalogue digest is refused. The existing
`F_SINGLE_REPLICA_ESTIMATE` stays exactly as it is: band 1.5–12.0 kcal/mol, `Evidence.LITERATURE`,
consequence `WRONG_SIZE`, routed to `bounded`, annotating and not withholding.

### 3.3 Rejected as the primary home: `economics/stage.py`

`reproducible_from_one_run` returns `run_to_run_kcal_mol <= 1.42` — RT·ln 10 at 310 K, one log unit
of affinity, so a spread above it means two molecules a factor of ten apart can swap places between
runs — and `replicas_for_a_measurement()` returns 1 or 5, honestly labelled a convention because
*"the literature is explicit that no theoretical means exists to establish the number."* These
predicates are correct and well-sourced. They are the right **input** to the policy and the wrong
home for it: they are binding on cost, they surface as a note rather than a refusal, and nothing in
`active/` consults them. A specification that put the policy here would add a fifth correct
predicate nothing reads.

It should, however, be the **default source** of a declared policy's replica count, so that a
protocol which declares nothing inherits a number with a provenance rather than a number somebody
typed.

### 3.4 Rejected: `faults/stability.py`'s module constants

`CONTACT_PERSISTENCE = 0.5` and `CONTACT_PRESENT = 0.3` are the repository's one real aggregation
rule — a contact counts if present in 30% of frames; a pose is the scored one if half its contacts
persist — and they are module constants self-labelled a convention. They are structurally identical
to the external grader's rule (a feature counts in ≥60% of draws, then enough features count), which
is the strongest argument that the shape generalises. But they are an aggregation over *frames of
one trajectory*, not over *independent draws*, and merging the two axes would produce a policy that
cannot say which of them it is about. They should become declarable fields of the protocol that
produced the readout, each carrying its own Evidence tag — following `economics/stage.py`'s
per-quantity provenance exactly, and for the reason that module gives: one label over several
numbers laundered three of them.

## 4. The data shape

A declared aggregation policy, carried by the protocol and folded into its digest.

| field | meaning | required | Evidence |
|---|---|---|---|
| `draws` | independent draws the policy declares | yes, integer ≥ 1 | the declaration's own |
| `independence_basis` | what makes them independent: `distinct_authorised_seeds`, `distinct_initial_conditions`, `declared_not_established` | yes | — |
| `combine` | `mean`, `median`, `best_of`, `fraction_present` | yes | — |
| `dispersion` | `sd`, `range`, `none_declared` | yes | — |
| `present_threshold` | for `fraction_present`, the per-draw cutoff | only for that combiner | per-quantity, e.g. `convention` for today's 0.3 |
| `pass_threshold` | for `fraction_present`, the share of draws needed | only for that combiner | per-quantity |

Three rules on the policy itself.

`draws` is **declared** and the authorised count is **measured**. Where they disagree, the
observation is emitted `evaluable=False` rather than letting the larger number clear the fault.
`Trajectory.replicas` is today a caller-supplied integer defaulting to 1, and
`from_prism(..., replicas: int = 1)` passes it straight through, so the clearing of
`F_SINGLE_REPLICA_ESTIMATE` currently rests on an unverified declaration. Deriving the count from
the authorised replicate actions — which already exist as records with distinct authorised seeds —
is the cheapest valuable half of this whole specification and could ship alone.

`combine: best_of` is legal and is **not** an estimate of a mean. `research/panel.py` takes best-of
across replicate slots and closes with `'uncertainty': None, 'uncertainty_reason': 'correlated
poses; no calibrated assay-error model'`, which is the honest form. A policy declaring `best_of`
declares that it is selecting and not averaging, and its dispersion figure is about the selection.

`dispersion: none_declared` is legal, because a protocol may genuinely have no dispersion model. It
is also the value that makes a readout carry `evaluable=False` where a decision would rely on it.
Legal and consequential is the right combination; illegal would push callers to declare `sd` over
one draw.

## 5. The refusal, staged

**Stage 1 — report, non-breaking.** A readout whose protocol declares no aggregation policy, or
declares one with `draws > 1` while fewer draws are authorised, is reported in a coverage block
beside the value: declared draws, authorised draws, combiner, dispersion figure or `not_taken`, per
task. Nothing is refused and no `Ruling` moves. Default every existing protocol to
`draws: 1, combine: "mean", dispersion: "none_declared", independence_basis:
"declared_not_established"`, so that nothing changes behaviour and every protocol becomes legible.

**Stage 2 — `evaluable=False`, deliberate.** Where the declared and authorised counts disagree, the
stability observation is emitted `evaluable=False`. Where a policy declares a dispersion figure that
was not computed, the dispersion-bearing observable is emitted `evaluable=False`.

Stage 2 must land **after** the admission-propagation recomputability audit, for the same reason the
admission-coverage change must: `learn/admission_view.py` maps an `unchecked` code that is exact and
`WRONG_SUBJECT` to `not_recorded`, and `RSI_REWARD.md` (D4) counts `not_recorded` as a loss — in the
denominator and not in the numerator. Turning declared replicas into unevaluable observations moves
nodes in a derived view. That is a decision to be taken with the audit's four counts in hand, and
`.claude/skills/etalon-recomputability-audit/SKILL.md` prescribes them.

**Decision, 2026-11-10: stage 2 is held, and the gate is restated because the one above is a
deadlock.** Two things changed what this paragraph could claim.

First, the argument for holding is stronger than "we lack the counts", and it should be the one on
the record: stage 2 **mechanically lowers the measured reward** — `not_recorded` enters D4's
denominator and not its numerator — while nothing about what was actually established changes. Under
RSI that is a self-measurement hazard, not a cost: a host tuning against that reward would remove
this change for a reason that has nothing to do with whether it is right. Hold it on that ground,
which does not expire.

Second, the gate as written cannot open. Stage 2 waits on the audit; the audit needs the four counts;
the counts come from observations — and the real journals have **none**. Measured read-only on
`2xpro6000:/home/zx/etalon/runs/*/research.sqlite`, 2026-11-10: 5 journals, `observations` rows **0**,
and no tool-identifying key anywhere in 2001 events. Evidence: `measured_here`. So the gate is
restated: **stage 2 lands after a campaign exists whose journal carries non-zero `observations`**, and
until then the blocking work is the recording gap, not the refusal. `research/capability_attribution.py`
closed the adjacent half of that gap in this round — every record written inside a dispatched MCP
verb now carries which verb wrote it (`mcp/_common.py::tool`, basis `mcp_tool`) — which is the same
recording gap one axis over, and the reason to fix the recording before tightening the judgement.

What ships instead, and it is the spec's own words: the **cheapest valuable half**, deriving the
replica count from the authorised replicate actions, is implemented in `active/aggregation.py`, and
`coverage` reports the declared count beside the authorised one without substituting either. That is
the stage-1 half that gives the audit its counts when observations exist.

**Stage 3 — a floor, optional and per protocol.** `min_replicates` beside `Endpoint.max_replicates`,
defaulting to 1 so no existing endpoint changes behaviour. Hard constraint 5 applies: five is a new
number and its provenance is `literature` (ESMACS/TIES, cited in `F_SINGLE_REPLICA_ESTIMATE`'s own
source), **not** `measured_here`. A candidate below the floor is *not yet measured* rather than
measured once. This changes selection for any endpoint that raises the floor — more spend per
candidate, fewer candidates covered — which is a trade to be approved rather than discovered.

**Decision, 2026-11-10: stage 3 is refused. There is no `min_replicates`.** Not deferred —
refused, because every measurement available argues against it and the paragraph above was
already most of the case:

1. **Our own numbers point the other way.** On the external benchmark the tasks that *passed*
   used fewer turns (mean 12.0 vs 18.3) and fewer oracle calls, and the external survey finds
   tool-call count uncorrelated with success (3.41 calls → 41.3%; 16.55 calls → 23.4%). A floor
   spends more per candidate and covers fewer candidates: it buys precision on the axis the
   evidence says is not the binding one.
2. **The seed experiment is the direct test, and it came back empty.** Ten scorings across two
   boundary tasks, spread 0.0000 and 0.1364, and **no verdict flipped**. Replicates would have
   changed neither task's outcome.
3. **A per-protocol floor cannot express a per-task property.** Dispersion was 0.0000 on one task
   and 0.1364 on the other; that is the same reason §6 forbids a pooled dispersion figure, and it
   applies to a pooled floor identically.
4. **It would refuse everything it applied to.** Both shipped dispatchable kinds have
   `max_replicates = 1` (`runtime/executors.py`), so a floor of five refuses at dispatch wherever
   it is set. A floor that refuses every case is not a floor; it is a disablement with a number
   attached.

What carries the same restraint at no cost is already here: `dispersion: none_declared` stays legal
**and consequential** — a readout a decision would rely on comes back `evaluable=False`. That
reports the gap without spending anything, which is the honest version of what the floor was for.

**The measurable trigger that would reopen it**, so this is a decision and not a veto: a replicated
executor ships *and* a task is found whose verdict flips across authorised seeds. The second half is
exactly what the ten scorings looked for and did not find; `tools/` holds the probe shape.

## 6. What must not happen

`prism_mmpbsa_replicated` stays undispatchable. Its refusal is for a different and correct reason —
independent-replica MD and gmx_MMPBSA execution are not wired — and this specification gives no
argument for unwiring it. A declared policy satisfied by an executor that cannot produce
independent draws is worse than no policy, because it moves the lie from the number to the
declaration.

The two shipped dispatchable kinds have `max_replicates = 1`. A policy declaring five draws against
them must refuse at dispatch and not quietly run one.

No pooled dispersion figure, anywhere. 0.0000 and 0.1364 across two tasks is the measurement that
forbids it.

## 7. How to verify by mechanism evidence

Not a score, and not "fewer single-draw results were published".

The directly countable quantity is **the number of stability observations whose declared replica
count disagrees with the count of authorised replicate actions, over the number of stability
observations examined.** That count says how often the clearing of `F_SINGLE_REPLICA_ESTIMATE`
rested on an unverified declaration, and it is computable before anything is implemented. The
fixture is the falsifier: declare `replicas=5` against a campaign holding two authorised replicate
actions, and require the observation to become unevaluable rather than clearing.

For the dispersion half, report `sd_*` the way `active/benchmark.py` already reports it — `None` at
n = 1 — computed across the **authorised** replicate seeds of real readouts, **per task, never
pooled**.

One honest note on the existing instruments: `tools/falsify_determinism.py` compares two runs
bit-for-bit but records `"seed_passed": False`, so it probes the unseeded case only and the seed
shim's own claim is never itself falsified by a probe. A dispersion probe is the missing half of
that pair, not a replacement for it.

## 8. What this specification does not settle

Whether the external benchmark behind this evidence is intended to run through `method.run`, and
whether its grader is to be expressed as an evaluation contract. If the grader stays outside, the
acceptance criterion remains structurally invisible to ETALON and the realistic goal becomes
recording that the criterion was *not* covered — which `missing_policy: "insufficient"` and
`not_declared` already express.

Whether the aggregation fractions in `faults/stability.py` should become per-protocol fields in the
same change as the draw policy, or in a later one. They are the same shape and a different axis, and
doing both at once risks a field that cannot say which axis it is about.
