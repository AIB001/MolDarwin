# Self-improvement architecture: what may self-tune, what holds it, what verifies each level

Status: design, 2026-11-11.

**What this document owns.** The boundary of self-modification: which artifacts a
self-tuning host may change, what must stay outside its reach for the loop to have a
direction at all, and what verifies a change at each level of the loop.

**What it does not own.** One revision cycle's mechanics — propose, measure, adopt / retain
/ rollback — belongs to [BOUNDED_RSI](BOUNDED_RSI.md). The improvement reward and its
accounting belong to [RSI_REWARD](RSI_REWARD.md). Where hardening belongs at all is
[HARDENING_CRITERION](HARDENING_CRITERION.md). The two assessment regimes, including where
a loose internal benchmark lives, are [ASSESSMENT_REGIMES](ASSESSMENT_REGIMES.md) §7.

Every number below carries its Evidence class per `CLAUDE.md` constraint 5, and a quantity
that could not be obtained says so rather than being estimated (constraint 7).

---

## 1. Three principles, and why the first two are not enough

**P1 — admission.** A record must not claim more than what was actually established.
Corollary, and it is the operational half: **an inconsistency must never resolve in the
direction that makes a record look better founded than it is.** It adjudicates
determinately for doc-vs-code drift, for stricter-vs-looser schema conflicts, and for a
vocabulary that exists only as prose.

**P2 — the hardening criterion.** Harden in code where a mistake becomes *indistinguishable
from a correct record later*; leave free where a mistake is *visible and recoverable in the
same session*. Corollary: the hardened set stays small and concerns provenance and
propagation, never method choice.

**P3 — the AI-native rule.** The harness supplies exactly what the host is *measurably* bad
at and gets out of the way of what it is good at.

P3 exists because P1 and P2 are both **restraints**. They say what to refuse, and no
quantity of refusal raises capability. Without a third principle, every design question
resolves toward more constraint, and the record layer — where additions are provably correct
and cheap to verify — absorbs all the effort. §8 is about that failure mode.

The two lists P3 names, measured on an external benchmark (Evidence: `measured_here` for our
own figures, `literature` where cited):

- **Bad at:** knowing an unstated threshold; knowing that a set-valued metric punishes
  extras; aggregation over stochastic draws; climbing out of a repeated error; using its
  budget; not over-claiming.
- **Good at:** design judgement, writing analysis code, reading heterogeneous context.

**The sorting test this yields, applied to every proposal:**

> Does this change what the host *optimizes*, or only what the record *says*?
> If only the record: is the mistake it prevents indistinguishable-later (harden), or
> visible in-session (report only)?
> And does it cost the host a turn it was otherwise spending well?

Speed comes from deleting steps that should not happen, never from making steps cheaper.
Measured: on an external benchmark the tasks that **passed** used fewer turns (mean 12.0 vs
18.3) and fewer oracle calls; an external survey reports tool-call count uncorrelated with
success (3.41 calls → 41.3%; 16.55 calls → 23.4%, Evidence: `literature`). So any proposal
amounting to "iterate more" is contraindicated by measurement, not by taste.

---

## 2. What is fixed, and why exactly these

A self-improvement loop needs a small number of points it cannot move, or improvement has no
direction. Four, of which three exist and the fourth is proposed.

### 2.1 An append-only raw log

Already here, and stronger than "do not modify": records are content-addressed, so a
modification *is* a different record. `ResearchJournal._put` refuses a second, different
body under a recorded identity (*"research identity cannot be rewritten"*), and hard
constraint 3 requires a state change to keep the old value and its claim scope. The host
reads it and cannot rewrite it.

This is the fixed point every other one depends on: it is the only thing against which a
claim can be checked after the session that made it.

### 2.2 Evaluation outside the agent's write reach — stated precisely

The obvious statement is "keep the scorer and the held-out set away from the agent", and it
is **wrong in a way we measured**. On an external benchmark, 8 of 9 failures were on a
single metric the agent could not read, and two submissions were already mathematically
unable to pass at the moment of hand-in (Evidence: `measured_here`). Locking the criterion
away was not safety; it was the defect.

The precise line is the one `research/contract_spec.py` holds: **publish the specification,
never the oracle.** Unreachable: the **verdict**. Readable: the **rule** — which quantities
are judged, each one's operator and threshold, the provenance of that threshold, what
direction the metric punishes, and how statuses aggregate. Enforced structurally: that
module has no code path to `evaluate_contract`, and a test pins the absence by AST.

### 2.3 A gate on irreversible actions — closed on the MCP spending surface (`0/7` unguarded)

Sending work to a wet lab, spending, relaxing a check: these cannot be self-approved.

Previously this document recorded three open holes (`moldarwin_screen_submit` bypassing the gate,
`method.run`/`screen.run` spending without an authority object, and zero MCP tools accepting a
spend token). All three have now been closed mechanically, verifiable via
`tools/count_unguarded_spends.py --max-unguarded 0` and `tools/falsify_optional_guard.py`:

- `moldarwin_screen_submit` and runtime `screen.run` enforce `GateAuthorization` (`gate_json`)
  via `mcp/screen_gate.py` and `runtime/operations.py::preflight`.
- `moldarwin_action_submit`, `moldarwin_workflow_submit`, `moldarwin_workflow_advance`, and
  `moldarwin_method_call` enforce `MethodAuthorization` (`authorization_json`) via
  `authority/method.py` and `mcp/method_authority.py`.
- `moldarwin_active_submit` and `moldarwin_workflow_reconcile(resume=True)` enforce
  `WorkflowAuthorization` (`authorization_json`) minted by `moldarwin_active_execution_plan` and
  `moldarwin_workflow_status`/`moldarwin_workflow_reconcile(resume=False)` via
  `authority/workflow.py`.

**Current count: `0 of 7` SPENDS tools accept no authorization object** (Evidence: `measured_here`
from `tools/count_unguarded_spends.py`). Present tokens are always verified; strict refusal on
absent tokens is selectable via `MOLDARWIN_METHOD_AUTHORITY=required` /
`MOLDARWIN_WORKFLOW_AUTHORITY=required`.

An external result makes the cost concrete: memory accumulated over ordinary low-risk chores
moved one model's unsafe-action rate from under 1% to 66–81% (Evidence: `literature`, single
source). Keeping this boundary at `0/7` and enabling `required` stage for autonomous long-horizon
campaigns remains higher priority than every record-layer refinement.

### 2.4 Proposed: every mutable artifact records which generation produced it

Not yet implemented. The argument, because it is cheap now and expensive later:

If the host may freely change its own note schema, its conventions, and its skills — and
§3 says it may — then artifacts written before and after a change are **indistinguishable**
unless each records the generation that wrote it. Git rolls back *files*; it does not roll
back *interpretation*. `git log` would show the history and a reader still could not tell
under which convention a given note was once true. So "revert if it got worse" works at the
file level and fails at the semantic level.

This is not a new mechanism. It is the pattern already applied three times in this
repository — `assessment_role_basis` recording an omission, `threshold_evidence` required on
the number that decides a verdict, `capability_attribution` recording which verb wrote a
record — turned on the memory directory itself. It costs one declared field, and the honest
value today is always "host, in session", **which is exactly when it is cheap to add**.

---

## 3. Everything else is mutable memory

Notes, representations, indexes, which fields a note carries, when consolidation runs and
what its instructions say, workflows and skills: all of it is the host's to change. The
interface constraints this round arrived at — provenance fields, conditional push, splitting
beliefs from policies — are **conventions the host may adopt or abandon**, not harness
structure.

One exception, and §2.4 is its reason: the generation stamp is not a convention the host may
drop, because it is the thing that makes dropping the other conventions recoverable.

**Why the constraints go on the interface and not on the content.** Three independent lines
point the same way, which is why this is stated as settled rather than as a hypothesis:

1. An external ablation: prescribing *what* to record ("record only failures") cost the
   strongest model tested 0.234 reward and the next 0.150, while a weaker one lost 0.020 —
   so the cost of legislating content **rises with model strength** (Evidence: `literature`,
   single paper, single benchmark, read through a summarising fetch).
2. This repository's own decision, reached independently: do not refuse the write, degrade
   the reliance (`ASSESSMENT_REGIMES.md` §2).
3. Our own turn counts: passes used fewer turns than failures (Evidence: `measured_here`).

---

## 4. Zoning, and the sharpening that makes it usable

- **Zone A — freely tunable.** Changes how the host *searches*: skill prose, prompts,
  ordering, candidate counts. Safe by construction, and by the same argument as the
  `diagnostic` regime: nothing propagates.
- **Zone B — tunable as a declaration.** Changes what is *computed*: aggregation, replicate
  counts, oracle choice. Must enter the identity digest, so two campaigns that computed
  differently cannot be compared under one id.
- **Zone C — out of reach.** Defines what *counts* as a result: `rule(Measurement) ->
  Ruling`, the fault catalogue, admission propagation, a declared decision rule, freeze
  chronology, contract thresholds.

**The sharpening, and it is the part worth carrying:** zone is a property of a change's
**write target**, not of the process that makes it. Reading old records and finding patterns
is zone-free; reading is not an act the zoning governs. So a question of the form "is this
mechanism Zone A or Zone C?" has no answer and will not acquire one, while "what does it
write?" always does.

Applied: a consolidation pass that writes only Zone A artifacts is safe by construction; one
that writes `moldarwin-method-experience/1` records is Zone B and needs §2.4's field first; one
that rewrites an existing record, a derived view, the fault catalogue or a decision rule is
Zone C and is already refused without a new rule.

**MolDarwin cannot make a Zone C edit impossible for a host with shell access.** The aim is
*detectable and non-propagating*, via a Zone C digest folded into every result's identity.
Under P1 that is sufficient: the harm is a record claiming more than was established, and a
changed judge carrying a changed digest cannot silently carry anything across.

---

## 5. The ladder, and the two rungs still short of an instrument

| Level | What changes | Instrument it needs | Status here |
| --- | --- | --- | --- |
| 1 | note content | the append-only raw log | **have it** (§2.1) |
| 2 | how memory is organised | replay over an episodic trace | **partial** (§5.1) |
| 3 | its own conventions and instructions | before/after on held-out tasks | **instrument is contested** |
| 4 | harness code and tools | human review | **have it** |

### 5.1 Level 2: an instrument for one change, not for the rung

**The general case still has no instrument, measured.** A replay test needs an episodic trace.
The real journals contain **0 `observations` rows** and no reasoning log; they record what was
produced, not what was deliberated (Evidence: `measured_here`, read-only over five journals,
2026-11-10). Half of the adjacent gap was closed in that round — every record written inside
a dispatched MCP verb now carries which verb wrote it — but the trace itself does not exist.
So for "is this a better way to organise memory", **the first work is still building the
instrument, not climbing to it.**

**One level-2 change does now have one.** The change is *shadowing*: leaving a stretch of
memory out of a default view because reading is bounded and memory is not. For that one
question the instrument is exact and needs no trace, because the thing at risk is already
computable — `learn/memory_shadow.check_shadow` runs `admission_view` on the graph and on the
graph without the proposed records, and reports every surviving node whose verdict moved
(Evidence: `measured_here`, `tests/test_memory_shadow.py`, 2026-11-25).

It recomputes rather than reasoning over `relied_on` edges, although that reasoning is
available and correct, because the propagation has corners a walk misses: a cyclic component
takes `not_recorded` whatever its premises hold, so does a node with neither premise nor
ruling, and the membrane degrades a relied-class edge on the *premise's* regime rather than on
the edge. Recomputation cannot drift from the rules it describes; an argument about edges can.

What this does not do, and the distinction matters for the rung as a whole: it answers *what
does this shadow cost*, never *is this shadow a good idea*. Whether the host will want a record
next week is a claim about the future and is exactly what the missing episodic trace would be
evidence for. Nothing is deleted either way — `ResearchJournal` has no delete method, and a
shadowed record stays readable by reference, as a superseded one does.

**Level 3's instrument is the one `RSI_REWARD.md` argues against.** Its position is that no
split of an external benchmark protects against learning the verifier. A held-out
before/after comparison is exactly such a split. This is not resolved here, and it should
not be resolved by pretending the instrument is sound: a level-3 change validated on a
held-out set has been validated against a verifier the host may have learned.

**Consequence for sequencing.** Levels 1 and 4 are usable today. Level 2 needs an instrument
built first. Level 3 needs the verifier question answered first. A loop that claims level 3
without that answer is self-scoring with extra steps.

---

## 6. The internal benchmark is optional, and belongs in the diagnostic lane

Recorded in full at [ASSESSMENT_REGIMES](ASSESSMENT_REGIMES.md) §7. In short: a deliberately
loose internal benchmark, up to and including an LLM judge, **is** a `diagnostic`-regime
instrument and needs no new record type, no new regime value and no new refusal. The lane
buys what such a judge needs — no predeclaration, reuse of seen bytes, cheap proxies — and
costs what one must be made to cost: it structurally cannot be relied on.

The fit is exact rather than convenient. An LLM judge is *easier* to learn than a fixed
scorer, because it is reachable by persuasion rather than by being right, and `diagnostic` is
where a verifier may be learned freely **because nothing propagates**.

And it is optional. Admission is not a score: it is whether a result may serve as the basis
of a conclusion, computed from faults, provenance and propagation, none of which asks how
well the work went. An architecture that came to depend on an internal benchmark would have
substituted a measure for a judgement.

---

## 7. What is refused, and on what evidence

**Offline consolidation ("dreaming") as a mechanism.** Refused, and the reason is not
caution. In the domains where it is demonstrated, the transcript *is* the ground truth — it
genuinely settles what a document says or where a cave exit is. **In science the transcript
settles nothing that matters**: a replay shows that the host computed a number, not that the
number was about the right molecule under the right protocol. Consolidation therefore repairs
**errors of recall**, while our measured failures are **errors of warrant** (8 of 9 on a
metric the agent could not read). A transcript-validated pass over a session that optimised
the wrong quantity will faithfully confirm that it did, and write a well-sourced note
recommending it again — so the mechanism is not neutral on our failure mode, it is mildly
adverse, because its validation step confers the appearance of checking on exactly the class
of claim it cannot check. Its published outputs also carry **no provenance at all**, which
under P1 is not a missing feature but the specific failure this architecture exists to
prevent.

What does transfer is narrower and is already built: the useful shadow of an offline pass in
this domain is **precomputing the acceptance criterion and handing it over**, which is
`moldarwin_method_criterion`, and it is synchronous.

**A replicate floor (`min_replicates`).** Refused, with four measurements against it, in
[STOCHASTIC_MEASUREMENT](STOCHASTIC_MEASUREMENT.md) §5, and a named reopening trigger.

**Prose as a discipline.** Refused as a mechanism, by its own instance. A withdrawn field was
first guarded by a regular expression hunting imperatives across 28 skill files — prose
policing prose. It silently matched nothing twice while the hazard stood. The repair was to
ask the question one layer down — *why can a field that does not exist be written at all?* —
and refuse the write (`research/reserved_bindings.py`). **The general rule: when the work has
become tuning a pattern over prose, the instrument is wrong.** Find the seam where the
mistake becomes indistinguishable later and refuse it there. A document-level test can
honestly hold doc-versus-source *agreement*, never behaviour.

**A refusal that does not name the legal route.** Not refused as a mechanism but as a
quality: a refusal a host cannot act on is a wall. Both refusals added in that round name
where the fact actually lives and what a legal alternative is.

---

## 8. The stopping rule, and the asymmetry it corrects

> A record-layer addition must name a subject it would have caught within one real campaign.
> If it cannot, it waits.

The asymmetry this exists to correct is structural, not a lapse of discipline. **Additions to
the record layer are provably correct and cheap to verify, so they always feel like progress
and never fail. Experiments can fail.** That difference pulls effort toward the layer where
it is least likely to change an outcome.

The measured instance, from the round that produced this document: roughly 830 lines of
record-layer diff plus thirty tests produced one live wrong number fixed, one real schema
inconsistency closed, and a quantity of correct prophylaxis with zero incidence — while **one
substituted function argument**, costing GPU time and no API quota, produced the finding that
an external benchmark's pass line sits above what its own ground truth achieves on 2 of 8
measured tasks (Evidence: `measured_here`).

The rule works in both directions, which is the test of whether it is a rule or a mood. It
gated the lesson-membrane fix while the self-improvement loop was unspecified, and opened it
once a stated design named the subject (`ADMISSION_PROPAGATION.md` §12).

---

## 9. Empirical Verb Census (2026-11-26) and what remains unestablished

- **Empirical Verb Census taken across 6 live multi-GPU campaigns (`tools/verb_census.py`,
  Evidence: `measured_here`).** Across 6 full autonomous campaigns (`snd1-10k-codex-thin`,
  `snd1-mtdh-10k-prism-rsi`, `snd1-mtdh-rescore-10k-prism-rsi`, `tb-science-keap1-open`,
  `flagship-6h-physics-rbfe-closed-loop`, `flagship-6h-tyk2-rbfe-converged`), **134 MCP tool
  calls touched only 12 distinct verbs out of ~98 registered (~12.2% surface utilization)**:
  - Top 4 verbs (`moldarwin_research_context`: 30, `moldarwin_skill_find`: 30,
    `moldarwin_skill_read`: 22, `moldarwin_admission_view`: 20) accounted for **76.1% (102/134)**
    of all calls.
  - `THIN_CORE_TOOLS` (16 verbs) accounted for **95.5% (128/134)** of all calls; adding the
    optional `prism` pack (6 physics verbs) raised coverage to **98.5% (132/134)**.
  - Seven optional packs (`screening`, `sweep`, `governance`, `active`, `workflow`, `planning`,
    `research-extended`) had **0 calls** across all 6 live campaigns.
  - **Falsifiable prediction confirmed:** real campaign usage is heavily concentrated in a small
    core, directly justifying progressive disclosure (`profile="thin"` + on-demand `packs`) and
    eventual retirement/folding of zero-use legacy verbs.
- **Threshold provenance ablation: still untested.** Whether a host given a `convention`-tagged
  bar behaves differently from one given a `literature`-tagged bar on the same task has not yet
  been ablated.
- **External experimental $\Delta G$ RBFE benchmark:** multi-target live campaigns have verified
  docking/CNN rescoring transfer (SND1 AUC 0.35 -> 0.958, KEAP1 honest No-Go `reward=1.0`) and
  multi-replica MD control gates (TYK2 1.07 Å pass vs. SND1 7.86 Å fail), while the full
  8-edge closed-cycle TYK2 experimental $\Delta G_{\text{MLE}}$ vs. $\Delta G_{\text{exp}}$
  scorecard is the gating external validation milestone.
