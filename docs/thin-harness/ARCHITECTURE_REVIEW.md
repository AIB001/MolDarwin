# ETALON architecture review: eight measured failure modes

Scope: `the repository root`, read 2026-11-09. Read in the order required —
`CLAUDE.md`, `README.md`, `src/etalon/HOST_SETUP.md`, `src/etalon/runtime/README.md` — then
`src/etalon` (244 `.py` files), `docs/thin-harness/` (the local design corpus), `.claude/skills/`
and `tools/`. `asset/` was not read or touched. No existing file was modified; this document is
the only file created. Everything load-bearing below was read directly; the four claims the
argument most depends on (`research/journal.py:230`, `active/store.py:561`,
`runtime/executors.py:388`, `mcp/execution.py:109`) were each re-verified against source after
first being found.

Terminology follows `CLAUDE.md` verbatim: **completion** / **verification** / **admission**;
**relied_on** (admission propagates) vs **used** (does not); **soundness** ∈ `sound` |
`unsound_recoverable` | `unsound_terminal`; **progress** ∈ `advanced` | `no_progress` |
`regressed`; Evidence provenance `measured_here` / `measured_in_an_asset` / `literature` /
`convention`. Where a claim is about repeatability I say **precision**; where it is about
agreement with a measured quantity I say **validity**. I do not use "audit" or "validate" in
place of admission.

---

## 1. The finding that organises the other seven

ETALON does not lack primitives for these failure modes. For six of the eight, the correct
primitive already exists, is better argued than the published practice in the survey, and is
then **either reachable only from Python, or bound to one task family, or sitting behind a
default that skips it.** The measured failures are, almost uniformly, failures of an optional
guard — the class `docs/adr/0006` already named for this repository: *a guard on the path nobody
takes is not a guard.*

Three concrete shapes of that, each a separate proposal below.

**(A) Two parallel regimes, and the default is the weak one.** `research/journal.py`
`_validate_method_evaluation` contains, at line 230:

```python
if value.assessment_role == 'diagnostic':
    return
```

Everything after that early return is a formidable chronology gate for
`assessment_role == 'independent_validation'`: results must be `validation-` receipts bound to a
`phi-` frozen policy whose `search_configuration['method_evaluation']` equals the exact
subjects/comparators/protocol/split/initial-conditions binding (`journal.py:244-246`); inputs
must have been recorded *before* the freeze —
`if self._record_sequence(db, ref) >= frozen_at: raise StateError('method evaluation inputs must be recorded before the policy freeze')`
(`:258-260`); evidence must be recorded *after* it (`:261-262`); and a content-addressed
anti-laundering loop walks every prior artifact row and refuses when seen bytes are relabelled —
`'already seen artifact bytes cannot be relabelled as independent validation'` (`:263-269`).
That is predeclaration enforced on a durable event sequence, not asserted. And
`research/composition.py:245` defaults `assessment_role="diagnostic"`, which returns at line
230 before any of it runs.

**(B) The spend path mints its own evidence; the learning path accepts the agent's.**
`authority.authorize()` (`authority/grant.py:221`) refuses to take a verdict as an argument, and
says why at `:232-235`: *"it does not take a verdict from the caller — it calls
`etalon.faults.preflight.check_record` itself. A function that accepted 'this one passed' as an
argument would be a guard on the path nobody takes with extra steps."* It calls `check_record`
at `:261`, HMAC-signs a token over `parent_id` + `record_sha256` + `receptor_sha256` +
`issued_at` + `expires_at` + `proceeded_under_waiver` + `unchecked` (`:143-155`), and `require()`
(`:304`) raises `NotAuthorized` with three distinct messages for a missing, expired/tampered, or
wrong-record token. In `src` overall `require()` has nine call sites
(`runtime/operations.py:177`, `campaign/expensive.py:175,184`, `active/prism.py:80,143`,
`active/runner.py:192`, `active/adapters.py:72,80`, plus `grant.py:363` internally).

Now the same taxonomy on the path `learn/admissible.py`'s own docstring calls the more
consequential one ("admitting a bad one costs a shift in the policy applied to all of them").
`etalon_rule_admissible` (`mcp/governance.py:268`) takes the observations as JSON **from the
model** and constructs them at `:297-317` with `fired=item.get("fired", False)` and
`evaluable=item.get("evaluable", True)`. A host passing `observations: []` receives a `Ruling`
with an empty `blocking` set — `Admission.ADMITTED` — and `AdmissionReport.rate` counts it as
admitted (`learn/admissible.py:291-300`). The code is visibly careful about one adjacent hazard
(a comment at `governance.py:309-311` ensures `evaluable=0` cannot become an unchecked pass) but
an **omitted** observation is not `unchecked`; it is absent, and absence reads as clean.

The same shape appears again inside the campaign. `rule()` defaults `require_comparator=True`
and blocks `NO_CHEAP_VALUE` with the note *"The expensive measurement stands on its own but
cannot tell the screen it was wrong about anything"* (`learn/admissible.py:227-232`) — and the
active loop's resolve path waives it, at `active/store.py:561-563`:

```python
ruling = rule(Measurement(result.candidate_id, None, result.value,
                          result.checks, result.units, result.provenance),
              waivers, require_comparator=False)
```

`cheap_value` is literally `None`. So the one structural pairing of proxy against comparator is
switched off precisely where the campaign actually records its observations.

**(C) Every quantity gate is an upper bound; all the measured failures were lower-bound
failures.** `active/budget.py` is three functions about not exceeding an allowance —
`fits_budget`, `affordable_capacity`, and a deliberately conservative `cost_quote` returning
`max(endpoint.cost, <observed p90>)` — and none about failing to use one.
`Endpoint.max_replicates` is enforced as a ceiling at `active/store.py:461`
(`"replicate limit reached; implicit retries are not permitted"`),
`runtime/operations.py:212-214` and `active/policy.py:89`; there is no `min_replicates`.
`controller.max_calls` and `max_seconds` are caps. The measured failures were: too few oracle
calls, too few stochastic draws, no declared threshold at all.

ETALON demonstrably *can* write floors — but only in its statistical layer:
`learn/calibrate.decide` returns `Verdict.UNDERPOWERED` below `minimum_positives=10`
(`learn/calibrate.py:317-331`); `research/calibration.py:72-79` refuses a fitted model on
`len(rows) < 2` or `len(set(groups)) < 2`; `research/transfer.py:42-43` requires at least two
independent training groups; `rescore/model.Rescorer.fit` refuses below one complex per feature;
`council/reliability` disqualifies a council when one seat's Youden's J is at or below zero;
`learn/admissible.py:69` warns below `_SELECTION_WARNING_BELOW = 2/3`. The floor discipline
exists and has never been applied to resources or to draws.

---

## 2. Per-input verdicts

| # | Failure mode | Verdict | Code behind the verdict |
|---|---|---|---|
| 1 | Optimised the visible oracle; failed the unseen acceptance criterion | **partial** | Prevents *misreporting which number was measured*; does not detect *divergence between the measured quantity and the scored one*. The readout is hash-bound: `Readout(stage_id, contract_id, value_column, filters)` (`active/cascade.py:27-32`) is digested into `protocol_id = "molcascade-recipe/1:" + digest(...)` (`:124`), so changing which column you read changes the endpoint's protocol id, and `active/store.py:190` refuses `"protocol changed under an existing id; register a new endpoint id"`. `active/graph.py:92-123` checks the column exists and is numerically typed. Aliasing is refused: `"this protocol is already registered; a new alias is not a new experiment"` (`active/protocols.py:279-280`). Units cannot drift: `"result units do not match the endpoint; no implicit conversion"` (`store.py:558-559`), and `active/schema.py:70-71` refuses a ΔΔG as a scalar molecule label. What the host *could see* is recorded (`MethodUse.visible_evidence_refs`, `research/schema.py:235`; the `visible_at_selection` relation at `learn/admission_view.py:97`, classified `used` with basis `record_cannot_settle`). The real anti-proxy mechanism is budgetary, not epistemic: `active/store.py:475-488` refuses, inside the reservation transaction, a proxy action that would eat the objective's confirmation reserve — `BudgetExhausted("proxy action would consume the objective confirmation budget")` — but only for `policy == "decision_aware"`, and `CampaignSpec.confirmation_reserve` defaults to **1**, so "confirmed" means n=1. Against this sits the comparator waiver at `store.py:561-563`. And the fault catalogue is closed-world — an unknown code raises (`learn/admissible.py:173-180`) — so an externally imposed criterion cannot be *named* in a `Ruling` at all. |
| 2 | Measurement with no decision rule | **partial — strong path exists, default path skips it** | The threshold *is* first-class data, separate from the reported quantity: `research/evaluation_contract.py` metrics carry `operator` ∈ {le,lt,ge,gt,eq} and a finite numeric `threshold`, with `"finite numeric threshold and fixed comparator required"` and `"missing values cannot be dropped, imputed or passed"` (`missing_policy` must be `"insufficient"`); `evaluation_rules_digest` strips inputs and provenance so the rule has an identity independent of the data it was applied to. `_aggregate` returns `"not_declared"` where nothing was declared and orders precedence `incomparable > criteria_failed > insufficient > passed`, so a missing input can never aggregate into a pass, and "cost success never erases quality failure". `research_decision.py:502-503` makes the rule binding on the claim: a judgment of `supported` against a replayed status of `criteria_failed` raises `"unsupported judgment conflicts with verified evaluation status"`, and `:334-335` refuses a report whose rules digest differs from the decision's frozen rules. `evidence_window.py` with `timing_mode="controlled"` enforces real durable ordering (`"durable window must precede decision"`, `"outcome must follow frozen decision"`, `"earlier original bytes cannot become a prospective release"`). **And none of it gates the default path.** `composition.record_evaluation` (`research/composition.py:244`) takes a free-text `conclusion`, validated only by `nonempty`; `MethodEvaluation` (`research/schema.py:275-299`) has no threshold, metric, operator or contract field; the `evaluation_plan` step requires metrics with `("name","family","unit","denominator","missing_policy")` (`composition.py:101-108`) and, because `_fields` is an exact-field check (`research/continuation.py:35-37`), **`operator` and `threshold` are not representable in the plan**; and `assessment_role="diagnostic"` returns at `journal.py:230`. `evaluation_contract.py` states the gap itself: *"Existing composition.record_evaluation can explicitly reference the returned Artifact in its result_refs; no MethodEvaluation/adoption is auto-created."* Where a decision rule *is* mandatory it is hard-coded rather than declared: `learn/calibrate.decide` has exactly one call site, `campaign/propose.py:287`, and scores on `Split.WHOLE_PANEL`, the weakest of its three splits. |
| 3 | A single draw from a stochastic oracle is not a measurement | **partial — detected, priced, annotated; never refused, and the count is unverified** | `F_SINGLE_REPLICA_ESTIMATE` (`faults/taxonomy.py:562`) carries band 1.5–12.0 kcal/mol, `Evidence.LITERATURE`, and a remedy naming five replicas as the ESMACS/TIES count with the honest rider that no theory establishes it. It fires at `faults/stability.py:290` on `trajectory.replicas < 2` — but its `Consequence` is `WRONG_SIZE`, routed to `bounded` (`learn/admissible.py:205-206`), which annotates and does not withhold. The count is a caller-declared integer defaulting to 1 (`faults/stability.py:88`; `from_prism(..., replicas: int = 1)` at `:181`), never derived from the authorised replicate records. `economics/stage.py` has the right predicate in the right place — `reproducible_from_one_run` returns `run_to_run_kcal_mol <= 1.42` (RT·ln 10 at 310 K, i.e. one log unit of affinity) at `:238`, and `replicas_for_a_measurement()` returns 1 or 5 at `:256` — it is binding on **cost** (`economics/allocate.py:222-223`) and surfaces only as a **note**, not a refusal (`allocate.py:478-485`), and **nothing in `active/` consults it.** The one real aggregation rule in the repository is hard-coded and self-labelled a convention: `CONTACT_PERSISTENCE = 0.5` with `CONTACT_PRESENT = 0.3` (`faults/stability.py:65-68`) — structurally identical to the grader's "each feature in ≥60% of 10 draws, then enough features" — and not declarable per protocol. Genuinely strong adjacent work: `runtime/executors.py:138` refuses a repeated seed with *"a repeated seed is a retry, not a replica"*; `active/prism.py:33,59-60` authorises one distinct seed per replicate and refuses dispatch past the authorised set; `active/model.py:69` refuses duplicate action identities as replicates; `active/cascade.py:165-171` refuses a fixed-seed cascade as a replica source; `active/adapters.py:77-78` refuses `PrismStage` as a certifier of independent replicas. And the decisive one, `runtime/executors.py:388-400`: the replicated MM-PBSA executor is registered and **deliberately not dispatchable**, because falling through *"would quietly run as one unseeded trajectory per action and report the result under a protocol id that claims recorded seeds and a known energy author."* Both shipped dispatchable kinds have `max_replicates = 1`. So the replicate machinery is correct, honest, and inert. |
| 4 | Budget systematically under-used | **absent** | `active/store.py:292` `_balance` returns exactly `{"budget", "spent", "reserved", "remaining"}`, and `remaining` is read only to decide whether the next action fits (`runner.py:70`, `policy.py:35`); nothing ever reads a large `remaining` as a problem. The per-round allowance is `spec.batch_size` (`active/schema.py:189`), passed as `slots` at `runner.py:72`; when `policy.choose` returns fewer than `slots` it simply breaks out of its loop (`policy.py:135-136`) and the round runs short. The round summary at `runner.py:174` records a **cumulative** balance and a `stop_reason` of `"ready"` — so a round that used 2 of 8 slots and one that used 8 of 8 are recorded identically. `len(summary["actions"]) < spec.batch_size` is computable by any reader and computed by nothing. `campaign/ledger.py` has no cost field at all; it is a config-change journal (`Entry(kind, round_id, at, body)`, `:61`). The nearest thing that puts allowance beside consumption is the benchmark layer, at whole-campaign granularity (`active/benchmark.py:78,87`), and there under-spend is scored as a **virtue**: `protocol_stopping_benchmark.py:87` reports `"budget_saved": budget - spent`. That is the real obstacle, not the arithmetic: `active/decision_benchmark.py:136-137` states *"Equal budget means equal caps and charged warm starts, not necessarily equal expenditure: a confirmation guard may deliberately leave unusable budget."* A detector must therefore distinguish a deliberate reserve from a failure to use the allowance, and that distinction exists nowhere as data. ETALON's substantive position agrees with the measurement — `findings/0004` as quoted in `README.md` holds that a better cheap tier beats ten times the compute — so this is a missing detector, not a disputed claim. |
| 5 | Error recovery is the bottleneck, not capability | **partial — feedback strong, adaptation absent** | Materially stronger than the harness those numbers were measured on. `method.run` is a whole declared program, not a snippet: explicit absolute argv with no shell (`runtime/method.py:46-49`), declared `files`, `inputs`, `input_files`, `outputs` confined to the step directory (`:65-73`), and `--request`/`--result` paths appended (`:129`). The program runs as its own OS process under a detached supervisor (`runtime/native.py:337-338`, `:397-398`), so "variables did not persist across calls" is not a failure this contract can produce; state crosses steps through `$ref` and the step directory. Failure feedback is typed: `_failure_details` (`runtime/method.py:21-40`) returns a discriminating `kind` ∈ {`process_exit`, `missing_output`, `invalid_result`}, plus `returncode`, a `missing_outputs` list, `reason`, a 2048-byte `stderr_tail` with `stderr_truncated`, a content-addressed `stderr` pin, and `stderr_read_error` kept separate so a log-read failure is not confused with the program's. A malformed result file is itself a typed failure rather than a crash. Exit code 0 is not read as success: `"scientific_status": "not_inferred_from_exit_code"` (`native.py:416`). Retry is structurally forbidden, not merely omitted: `"automatic_retry": False` in both status and receipt (`native.py:281`, `:378`), `return  # Never relaunch even after a worker dies with unknown outcome` (`:390`), and an unknown outcome raises rather than re-running (`method.py:141`). What is absent is the other half. Nothing counts repeated near-identical failing submissions. `runtime/reuse.py` would recognise one — `request_identity()` digests operation+implementation+environment+inputs+parameters and a terminal receipt *including a failed one* is returned as `reused: True` (`reuse.py:20-31`, `:37`) — but **`method.run` does not use it**; no import of `etalon.runtime.reuse` appears in `method.py`, `native.py` or `operations.py`. `research/defect_family.py` can represent a family of related failures with a `mechanism_hypothesis`, and its dedup is deliberately anti-inflationary — `sorted(set(accepted))` with *"repeated bytes add no accepted issue"* — which is right for corroboration and discards the one signal that would support "you have tried this three times". `research/action_learning.py:87` is the nearest thing to forced adaptation: a prediction must predeclare `next_if_match` / `next_if_different` / `next_if_unknown`, all nonempty, and `compare_action_feedback` replays the comparison and hands back the matching branch — explicitly as advice, *"Hints are the host's previously recorded alternatives, never executor commands."* |
| 6 | Determinism is not robustness | **partial** | The distinction ETALON draws is better than the survey's. `F_RUN_NOT_REPRODUCIBLE` (`faults/taxonomy.py:434`) carries `Consequence.UNVERIFIABLE`, which by the taxonomy's own rule blocks a *claim* and never a spend, and `rule()` routes it to `unverifiable` with the note *"Admitted but not reproducible … This qualifies the claim, not the molecule"* (`learn/admissible.py:203-204`, `:259-265`). That is exactly right: an unseeded run is a **precision** defect, not a **validity** defect, and `judgment/waiver.py:115-123` refuses a waiver for it outright because *"it does not block a spend — it invalidates a claim about the run — so there is nothing for a waiver to release."* `docs/adr/0001` measured the problem (two `genion` runs, `7c3e3472…` vs `098089b3…`) and `boundary/toolchain.py` supplies the seed from outside, refusing with exit 64 when none is set, pinning its own bytes by digest and refusing to wrap itself. `boundary/simulate.py:398-399` is honest that `reproducible` is a conjunction of configuration facts, not a verified output property, and `toolchain.py:30-33` names the residual: the shim does not touch MDP files, so velocity generation is not seeded. **What is missing is dispersion.** Nothing runs the same thing under multiple seeds and reports the spread. `tools/falsify_determinism.py` compares two runs bit-for-bit but records `"seed_passed": False` — it probes the *unseeded* case only, so the shim's own claim is never itself falsified by a probe. Cross-seed `sd_*` is computed, but only inside ETALON's own synthetic policy benchmarks and `None` at n = 1 (`active/benchmark.py:86`, `active/protocol_benchmark.py:161`, `active/decision_benchmark.py:99,125`). The one executor that declares multiple distinct seeds is blocked at dispatch (`runtime/executors.py:388-400`). In `research/`, `panel.py` collects replicate slots and protects the denominator (`slots_per_candidate`, every attempted slot including failures represented exactly once) and then takes **best-of** rather than a spread (`panel.py:128`), closing with `'uncertainty': None, 'uncertainty_reason': 'correlated poses; no calibrated assay-error model'` (`:148`); `grep` over `research/` finds no `stdev`, `variance`, `confidence_interval`, `percentile` or `bootstrap`. ETALON also names this gap against itself: `README.md` records two runs of the council probe at one seed moving Youden's J 1.000 → 0.917, kappa 0.371 → 0.442, effective votes 1.46 → 1.39, concluding *"it is the precision that is unestablished."* |
| 7 | The harness dominates the base model; effort is non-monotonic | **partial, trending absent** | The content/usage split is real: skill-content identity S and usage-method identity U carry independent digests (`HOST_SETUP.md`, §Capabilities and versions), the usage method is a byte hash of the guidance file (`skills.py:296-297`), `MethodVersion.verification_basis` ∈ {`host_reported`, `content_verified`} (`research/schema.py:223-224`), `MethodUse.basis` ∈ {`host_reported`, `tool_observed`} (`:268-269`), and `selected_methods` carries `adoption` ∈ {full, partial} with `used_parts` required for partial (`:256-263`). `MethodEvaluation` requires `task_split_ref` *and* `accounting_refs` (`:276-287`), so cost is structurally beside quality. `research_decision.py:101-109` is the richest record, with `attribution` fields `("actor","basis","model_ref","skill_refs","verifier_refs")` and a refusal that predictions stay attributable host judgment — and `model_ref` is explicitly nullable, `skill_refs` and `verifier_refs` may be empty. `capability_profile.py:108-118` does form a joint version group over model + skills + methods + verifiers + rules digest, and reports a null `model_ref` as a **gap** (`:99-107`) — but it is read-only, refuses nothing, and stamps `transferable_benefit="not_established_by_aggregation"` and `uncertainty="no_confidence_interval_or_statistical_noninferiority_inferred"`. `MethodUse.host_conditions` defaults to `{}` and is validated only as *"must be an object with null for unknown fields"* (`research/schema.py:270-271`): **no required key, no type, no enum.** `host.py:120-121` restricts `host` to a vendor name. So prompt/skill version is content-hashed and recordable, model name is a nullable ref, and **reasoning effort is not representable at all** — input 7's non-monotonicity (one system peaking at medium, another lifting 35% → 52% from high to max) has no slot. No mechanism refuses a two-axis change: `Revision` only refuses changing the same field twice, and `panel.propose_joint_revision` *requires* a simultaneous two-axis change, answering confounding by predeclaring the joint arm as a control (`panel.py:198-208`, `:267`) and closing with `'causal_attribution': 'unresolved; factorial differences are descriptive'` (`:153`). `improvement.assess_revision:392` compares a patch's declared `conditions` against observed `host_conditions` and reports mismatches as **missing evidence** (`'awaiting_evidence'`), checking only keys the patch declared — an undeclared axis that changed is invisible. |
| 8 | The field's convergent design discipline | **largely handled; in three places stronger than the surveyed practice; one element consciously rejected** | **Freeze all but the variable — handled, chronology enforced by data rather than claimed.** `research/panel.freeze_selection` (`:236`) requires distinct development and validation tasks and refuses outright once the validation panel holds any observation: `if any(v is not None for v in target_summary['cells'].values()): raise StateError('freeze must precede validation panel observations')` (`:251-253`). It freezes a 2×2 of `P0/E0 … P1/E1` including an explicit `static_P1_E1` "predeclared joint intervention control", records `improvement_policy_learning: 'not_demonstrated'`, `independent_validation_accessed: False` and `policy_equivalence: '… neither is a learned improvement policy'` in the frozen body, digests it, and `execute_frozen_policies` re-verifies that digest (`"frozen decision changed"`) while noting it is *"an off-policy evaluation, not four independent experiments."* `schema.Contrast` (`:136-151`) forces all four factorial cells to be recorded including the missing ones as `None`, and refuses one observation impersonating two arms. **Sealed split, scored once — handled, and one-way.** `Artifact.role` ∈ {`diagnostic`, `independent_validation`, `sealed_holdout`} (`research/schema.py:47-48`), with `sealed_holdout` structurally unreadable at many read sites. `research_decision.py:259-261` refuses evaluation-only or sealed material from conditioning a decision, and `:400-401` refuses the byte-level relabel. `seen.register_seen_labels` releases evidence from independent validation to seen development one way only, refusing a formerly-seen task re-entering an independent test, refusing any label change (*"seen release changes scientific labels; explicit data amendment required"*), and recording `independent_validation_reusable: False`. `journal.py:263-269` adds the content-addressed anti-laundering check. `result_integrity.confirmation_eligibility` (`:270`) requires `decisions_frozen_before_execution is True`, `outcomes_visible_at_freeze is False`, verified freeze-declaration *bytes* rather than *"a newly asserted boolean or a command-line flag"*, and `seen_series_ids` tracking that returns `series_feedback_seen`. `evidence_window.py:522-523` refuses partial scoring — *"release must preserve every frozen outcome, including failures"* — so you cannot score only the slots that came out well. **Sealed oracle in the benchmarks — handled by argument absence.** `active/policy.choose` has no oracle parameter; `replay.py:39-47` returns a cell only for an action already reserved and charged; `replay.py:80-84` requires the table be *complete* over the full cross product so which cells exist leaks nothing; `replay.py:98-104` validates QC across the whole table *"without admitting or exposing any unqueried label to the learner"*; `decision_benchmark.py:71-72` refuses an evidence-backed recommendation the arm never paid to measure. **Fresh re-run — partially handled**, by `boundary/infra.py` refusing a shadowed import, `tools/verify_assets.py --deep`, and the SND1 ablation's reproduction cell (`narrow_on` must reproduce historical T0 within 0.001 Å and 0.0001 kcal/mol); there is no general "re-run the submitted artifact in a fresh environment as the official score". **Cost as a first-class axis — handled**, with units kept separate rather than normalised and the separation enforced: `store.py:334-335` refuses a cross-unit charge, `:558-559` a cross-unit value, `active/adapters.py:45-46` states *"Wall time is NOT silently called GPU time"*, and `economics/stage.py:147-152` gives each quantity its own Evidence tag because `measure.with_enrichment` had published `spearman: 0.35` under `evidence: measured_here`. **Mechanism evidence — the strongest element, and unimplemented.** `faults/attribution.py` eliminates causes by magnitude and returns `UNEXPLAINED` when no candidate survives — a label on a returned `Attribution`, not a refusal, with the note *"Something outside this taxonomy is acting, and naming one of the refused causes anyway would be the wrong answer confidently given"*, and `magnitude_was_available` reporting whether any magnitude reasoning happened at all. `research_decision.py:129-141` requires a testable prediction to bind competing `option_ids` and state in `distinguishes` which rival explanation the observation rules out, and `:492-493` requires a judgment's observations to be exact outputs of the specific executed action with its identity unchanged — arm-level attribution, genuinely enforced. `docs/thin-harness/RSI_REWARD.md` then goes further than anything in the survey: restrict the reward to `Exactness.EXACT` observables so it is *"ungameable by construction rather than by vigilance"*, count only `Admission.ADMITTED` and not `ADMITTED_UNDER_WAIVER`, count `not_recorded` as a loss, refuse a comparison whose sides differ in catalogue digest, argue that **no split of an external benchmark protects against learning the verifier** so the reward must be internal, and specify the shuffled-signal control as *"the only observable here that distinguishes the two."* None of that reward exists in `src` (`grep -rn "warrant"` over `src/etalon` returns two unrelated docstrings), and no module checks a declared mechanism against evidence — every delta module stamps "not causal" instead (`transfer_checks.py:81`, `panel.py:153`, `research_impact.py:137`, `declared_relations.py:103-105`). **Normalisation onto one anchored scale — consciously rejected**, and I think correctly. That rejection should stay a stated position rather than drift into an unstated one. |

### Two terminology findings worth stating separately

**`soundness` and `progress` are not implemented anywhere.** A repository-wide search over `*.py`,
`*.md` and `*.json` outside `asset/` returns only `CLAUDE.md:6-7` itself. Their sole operational
appearance is a prose instruction to the host in
`.claude/skills/etalon-step-corpus/SKILL.md:30-35`:

> Soundness and progress are separate fields. … Fill them from rules over the fault codes and the
> operation outcomes on the first pass. Where a rule does not reach, leave the field empty; an
> inferred value here is indistinguishable from a measured one later, which is the failure this
> project has a vocabulary to avoid.

So two of the five fixed vocabularies are currently enforced at exactly the level ADR 0006 found
insufficient, and the skill's own closing clause names the hazard that follows. `relied_on` /
`used`, by contrast, is implemented and load-bearing (`learn/admission_view.py:26-36`, with
propagation at `:415-425` and `:336-371`). The nearest existing substitutes are worth knowing
before inventing new ones: for a pass/fail axis, `evaluation_contract.STATUSES`
{`criteria_passed`, `criteria_failed`, `insufficient`, `incomparable`} plus `not_declared`; for
disposition, `research_decision.py:169` {`retain`, `revise`, `reject`, `defer`, `no_change`} —
`no_change` being the nearest token to `no_progress`; and for soundness, a pervasive
*negative-assertion field* idiom (`scientific_truth="not_certified"`, `adoption="not_performed"`,
`mechanism_posterior=None`) which at `research_decision.py:86-87` is a validated constant rather
than decoration.

**`regressed` exists in `learn/` and does not mean the enum value.** `learn/acquire.py:10` and
`learn/__init__.py:12` use it for statistical regression toward the conditional mean — *"it
regressed an unseen chemotype to the panel mean"* — which is a different claim from
`progress = regressed`. Whoever implements the vocabulary should expect this collision.

---

## 3. Ranked architecture changes

Ordered by leverage. Each gives the change, the call sites, the cost, what it risks breaking,
and — the part the brief insists on — how to verify the change produced its intended effect
**through mechanism evidence rather than a score delta**. In every case the mechanism evidence is
a count with a named denominator, per hard constraint 7.

### P1. Close the `diagnostic` escape hatch and bind the decision rule to the conclusion

**Why first.** This is a two-line early return standing in front of the best predeclaration
machinery in the repository, with the harness's own default routing around it. Inputs 2 and 8
both land here, and the fix needs almost no new mechanism.

**What changes.** Three edits, each small, in increasing order of commitment.

*(a) Let the plan carry the rule's identity.* Add an optional `rules_digest` to each metric in
the `evaluation_plan` step. `_fields(value, required, optional=())`
(`research/continuation.py:35`) already supports optional fields and `composition.py:112` already
uses the two-tuple form, so this is the validator's own idiom. The value is the existing
`evaluation_contract.evaluation_rules_digest(contract)`, deliberately stable under a change of
observed inputs, so one declared rule can be replayed against new evidence without its identity
moving.

*(b) Make an independent-validation conclusion name the rule it is a conclusion of.* In
`composition.record_evaluation`, when `assessment_role == "independent_validation"`, require
every plan metric to carry a `rules_digest` and a bound `etalon-evaluation-report/1` whose status
is `criteria_passed` or `criteria_failed` — not `insufficient`, not `incomparable`, not absent.
This does not ask the contract to be right and promotes nothing; it asks that a claim of
independent validation name a numeric rule.

*(c) Give `diagnostic` the cheapest of the checks it currently skips.* Not the full chronology
gate — a diagnostic evaluation legitimately has no frozen policy. But the early return at
`journal.py:230` also skips `if not results or not value.accounting_refs: raise StateError(...)`
at `:232`, so a diagnostic evaluation may carry no results and no cost references at all. Require
`accounting_refs` for every role. Cost is already a required field of the dataclass; this makes
it a required *fact*.

**Files and call sites.** `src/etalon/research/composition.py:101-108` (metric validation, add
the optional field), `:244-282` (`record_evaluation`: the refusal, and binding the report ref
into the recorded step's `detail`); `src/etalon/research/journal.py:230-232`
(`_validate_method_evaluation`, the early return and the check immediately after it);
`src/etalon/research/schema.py:296-297` (`assessment_role`, already the discriminator). Reads
only: `src/etalon/research/evaluation_contract.py` (`evaluation_rules_digest`,
`validate_evaluation_contract`), whose `method_contract_ref` binding already demonstrates the
digest-into-a-contract pattern.

**Cost.** Small in code, real in workflow: every future independent-validation conclusion
requires a contract declared beforehand. That is the intended cost.

**What it risks breaking.** Existing `independent_validation` records carry no contract and
would become unrecordable. They must not be retrofitted — hard constraint 4 forbids backfilling
admission, and `RSI_REWARD.md` already concedes historical nodes are permanently `not_recorded`.
Apply to new records and leave the old ones in a marked partition, which is exactly what
`.claude/skills/etalon-recomputability-audit/SKILL.md:46-49` prescribes for this class of change.
Second risk, and the one to watch: hosts route around a stricter path by recording everything as
`diagnostic`. That should be reported rather than prevented — `diagnostic` is a legitimate role
and forcing the stronger one would make the record less honest, not more. Edit (c) is the one
that could break working callers; check it against `research/capability_profile.py`, which reads
`accounting_refs` and already treats their absence as a gap.

**How to verify by mechanism evidence.** Ignore "how many evaluations now pass". The mechanism
quantity is **the disagreement between prose and rule**: for the corpus of existing evaluations,
replay each against a contract written from its own plan metrics and count how many `conclusion`
texts assert a positive finding while the replayed status is `insufficient` or `criteria_failed`,
with the number replayed as the denominator. A non-trivial count is direct evidence that the
pathway being closed is the one that was open — and this replay has already been performed once,
retrospectively, for two SND1 protocols, finding exactly that shape: the PoseBusters case *"fails
the original conditional-policy criteria"* while its cost criterion passes separately
(`docs/thin-harness/EVALUATION_CONTRACT.md:132-145`). For the route-around risk, report the ratio
of `independent_validation` to `diagnostic` records per window before and after: a shift toward
`diagnostic` with unchanged conclusion language is the failure signature, and it is visible only
if the ratio is reported. Both numbers are invisible in any pass rate.

### P2. Make the admission gate mint its own observations, in two stages

**What changes.** Close asymmetry (B) at the only place a host actually reaches the admission
rule.

*Stage 1, non-breaking, ships alone.* Add a `coverage` block to the **MCP response** — not to the
`Ruling` — naming, per measurement, the catalogue codes for which the caller supplied no
observation at all, split by `Phase` and by `Exactness`. The response already carries `report`,
`waivers_in_force`, `waivers_expired` and `next_step`; this is one more key. An empty observation
list then reads as "ten preflight causes unexamined" rather than as a clean ruling.

*Stage 2, deliberate, after an audit.* At the MCP boundary only, synthesise
`Observation(code, fired=False, evaluable=False)` for every `Phase.PREFLIGHT` code the caller did
not mention, before constructing the `Measurement`. `rule()` sorts them into `unchecked` by its
existing branch (`learn/admissible.py:181-183`), and the note it already writes — *"clean only as
far as anyone looked"* (`:266-270`) — becomes true of every host-driven ruling rather than only of
the honest ones.

*Related, and cheaper than either:* reconsider `require_comparator=False` at
`active/store.py:561-563`. I am **not** proposing flipping it — the active loop legitimately has
no cheap comparator at resolve time, and `NO_CHEAP_VALUE` would block every observation. I am
proposing that the waiver be *reported*: the campaign's own summary should state that its rulings
were taken without a comparator, because the whole argument of `learn/admissible.py` is
calibration of a cheap number against an expensive one, and on this path that comparison is
structurally absent.

**Files and call sites.** `src/etalon/mcp/governance.py:268` (signature), `:297-317` (the
`Measurement`/`Observation` construction that is the actual hole), `:318-330` (the `ok(...)`
response). Reads only: `src/etalon/faults/taxonomy.py` (`FAULTS`/`BY_CODE`) and
`src/etalon/faults/preflight.py:388` (`unchecked`) for the existing vocabulary. For the
comparator report: `src/etalon/active/store.py:561-563` and the round summary at
`src/etalon/active/runner.py:174`. **`src/etalon/learn/admissible.py` is not modified** —
`rule(Measurement) -> Ruling` keeps its semantics exactly; what changes is the completeness of
the `Measurement` handed to it, which is the argument `rule()` was designed to receive.

**Cost.** Stage 1 is roughly 30 lines plus a fixture. Stage 2 is smaller; its real cost is the
recomputability audit that must precede it, for which the repository already has a procedure.

**What it risks breaking.** Stage 1: nothing, being additive and read-only. Stage 2 is the
dangerous one and the risk is specific: `learn/admission_view.py:250` maps `unchecked` codes that
are exact `WRONG_SUBJECT` to `not_recorded`, so filling `unchecked` pushes nodes to
`not_recorded` in the export view, and per `RSI_REWARD.md` (D4) `not_recorded` counts as a loss.
The honest reading is that this *reveals* unestablished warrant rather than creating it, but it
is a large visible shift in a derived view and must be taken as a decision with the audit's
counts in hand. Also check the council's jurisdiction, which is defined over
`preflight.unchecked`: a council may move a check from unevaluable to fired and never to cleared,
so a larger `unchecked` set enlarges what a council may be asked about. That direction is safe by
the module's own argument, but the volume changes.

**How to verify by mechanism evidence.** Do not report an admission-rate delta; the rate is
*supposed* to fall, and a falling rate is consistent with both the intended mechanism and with a
bug that drops observations. Report instead **the count of rulings whose `blocking` set was empty
because nothing was checked, with the total number of rulings as the denominator, broken down by
which codes were absent.** Two fixtures are the falsifiers: (a) a measurement with a complete
honest observation set must produce a byte-identical `Ruling` before and after, establishing the
change touches only the incomplete case; (b) a measurement with `observations: []` must move from
`admission=admitted` with empty `unchecked` to `admitted` with a fully populated `unchecked` and
unchanged `cheap_value`/`expensive_value`, establishing the mechanism is coverage and not a new
refusal. Run the recomputability audit first and publish its four counts — absent observations,
`legacy_record_semantics_inferred` nodes, comparator-less measurements, undecidable premise edges
— each as an absolute number with its denominator and with the method of counting named.

### P3. Close the three live ADR-0006 instances on the host-facing surface

**What changes.** ADR 0006 is written in the past tense and its class is still open in three
places, all on the surface a model actually drives. This proposal is to close two of them and
document the third as a bounded, named exception rather than an oversight.

1. **`etalon_screen_submit` is a route around the gate.** `mcp/execution.py:109-117` takes
   `config_path, workspace, run_id, plan_id, library_path, workers, devices, allow_copyleft,
   delivery` — no gate token of any kind. `plan_id` is `expected_plan_id`, a change-detection
   check, not an authorization. Meanwhile `etalon_sweep_emit` does it correctly: it takes
   `gate_json`, refuses without it, and reports which of the three causes fired. A host that
   reads a refusal from `etalon_authorize_gates` — or never calls it — can reach
   `etalon_screen_plan` (CHEAP) then `etalon_screen_submit` (SPENDS) and apply uncalibrated gates
   to a library it supplies directly. `authority/gate.py:31-36` concedes this and calls it *"a
   campaign whose operator chose to skip the check"*, but the actor on the MCP surface is the
   model, which is the party the cost scheme exists for. **Change:** add an optional `gate_json`
   to `etalon_screen_submit` and refuse without it when the config declares gates whose
   calibration is recorded — the same shape `etalon_sweep_emit` already uses.
2. **`method.run` and `screen.run` nodes spend with no authority object.** Of the registered
   workflow operations, only `active.evaluate` can reach `require()`
   (`runtime/operations.py:171-177`). For `method.run` the preflight checks only that an
   allowance was declared — `if operation == "method.run" and resources.get("wall_second", 0) <= 0: raise ValueError("method.run requires an explicit wall_second allowance")`
   (`runtime/operations.py:186-187`) — and `verify` only re-reads the native receipt. So the
   operation that runs arbitrary host-authored argv is a SPENDS path with a budget declaration and
   no gate. **Change:** this one should *not* get a handoff-style token, because `method.run` has
   no handoff row to bind one to. What it should get is the generalisation `authority/` has so far
   avoided: `grant.py` and `gate.py` are the same pattern written twice with no shared base, and a
   third subject — a declared method request digest — is the right third instance. Mint on the
   declared `(method_id, files digests, inputs digest, outputs map)` and require it at dispatch.
3. **No MCP tool accepts a spend token at all**, which `authority/__init__.py:10-12` states
   plainly: *"nothing on the tool surface accepts a spend token, so `require` is reached only from
   Python."* **Change:** none proposed beyond (1) and (2); this is the honest summary of why the
   first two matter, and the docstring that says it should stay.

While there: `authority/__init__.py:8-9` and `mcp/governance.py:410` both still say *"57 tools …
five that spend"*. The current census is 87 `@tool` applications with 7 SPENDS and 1 NEVER. A
stale count in a docstring that *reasons from* the count is worth fixing in the same pass.

**Files and call sites.** `src/etalon/mcp/execution.py:109-131` (`etalon_screen_submit`);
`src/etalon/mcp/sweep.py:246-296` (`etalon_sweep_emit`, the pattern to copy) and `:314-368`
(`etalon_authorize_gates`); `src/etalon/runtime/operations.py:171-190` (the preflight branch
where a `method.run` token would be required) and `:650-652` (`verify`);
`src/etalon/authority/grant.py` and `src/etalon/authority/gate.py` (the two existing copies that
a third instance should finally factor); `src/etalon/authority/__init__.py:8-12` and
`src/etalon/mcp/governance.py:410` (stale counts).

**Cost.** (1) is small. (2) is the largest single change in this document, because doing it
properly means extracting the shared authorization shape rather than writing it a third time.

**What it risks breaking.** (1) breaks any host that submits a screen without calibrating gates —
which is the point, but it is a behaviour change on a SPENDS tool and needs the optional-then-
required rollout that `authority/gate.py`'s own history suggests. (2) risks breaking every
existing `method.run` caller; mitigate by minting the token inside `prepare_action`/`plan` so the
host receives it rather than constructing it, which is how `authorize()` already works. Do not
weaken `_refusal()`'s classification while doing this: `mcp/_common.py:272-314` intercepts
`NotAuthorized` and returns `retryable=False`, because `NotAuthorized` subclasses
`PermissionError` → `OSError` and was previously reaching the model as *"it looks transient …
calling again is reasonable once"*. A new authorization error must be added to that intercept or
it will be retried.

**How to verify by mechanism evidence.** Not "fewer bad screens ran" — that is a score and it is
unobservable. The mechanism evidence is **reachability, demonstrated by construction**: for each
of the two closed holes, write the test that ADR 0006 would have caught, i.e. drive the MCP
surface the way a model would, take the refusal from the guard tool, then attempt the spending
tool and assert it refuses. Before the change that sequence succeeds; after it, it raises. That
pair of transcripts *is* the mechanism claim, and it is the same falsifier
`tools/falsify_determinism.py` and `tools/measure_council.py` already embody — a probe that
exits nonzero when the property fails. Second, countable quantity: the number of SPENDS tools
whose signature accepts no authorization object, with the number of SPENDS tools as the
denominator. Today that is 7 of 7 for spend tokens; the proposal moves it, and the count is
checkable mechanically from the registration index that `mcp/server.py:172-176` already builds.

### P4. Give replicates a floor, a declared aggregation policy, and a verified count

**What changes.** Four separable defects behind inputs 3 and 6, in descending order of value per
unit of work.

*(a) Wire the predicate that already exists.* `economics/stage.reproducible_from_one_run`
(`:238`) and `replicas_for_a_measurement()` (`:256`) are correct, well-sourced, and consulted
only by the planner, where they move cost and emit a note. Nothing in `active/` reads them. Have
the active loop consult `reproducible_from_one_run` for the endpoint's stage and, when it is
false, treat a single admitted observation as not yet a measurement for the purpose of an
objective recommendation. This is the cheapest of the four and the only one that connects two
subsystems that already agree.

*(b) A floor beside the ceiling.* Add `min_replicates` to `Endpoint` alongside `max_replicates`
and have selection treat a candidate below it as not yet measured rather than measured once.
Hard constraint 5 applies: `min_replicates` is a new number and must carry Evidence provenance.
The value the catalogue supports is five and its provenance is `literature` (ESMACS/TIES, cited
in the fault's own `source`), **not** `measured_here`. Default it to 1 so no existing endpoint
changes behaviour, and let a protocol raise it.

*(c) An aggregation policy declared rather than hard-coded.* The two-level rule the grader in
input 3 used — a feature counts if it appears in ≥60% of draws; a candidate passes if enough
features count — exists once in this repository as module constants self-labelled a convention:
`CONTACT_PERSISTENCE = 0.5` and `CONTACT_PRESENT = 0.3` (`faults/stability.py:65-68`). Make that
pair a declared field of the protocol that produced the readout, defaulting to today's constants
so nothing moves, each value carrying its own Evidence tag — following
`economics/stage.py:147-152`'s per-quantity provenance exactly, and for the reason that module
gives: one label over several numbers laundered three of them.

*(d) A count measured rather than declared.* `Trajectory.replicas` is a caller-supplied integer
defaulting to 1. Derive it from the authorised replicate actions, which already exist as records
with distinct authorised seeds, and when the declared and authorised counts disagree, emit the
stability observation as `evaluable=False` rather than letting the larger number clear the fault.

**Files and call sites.** (a) `src/etalon/economics/stage.py:238,256` (read only),
`src/etalon/active/recommendation.py:40-57`, `src/etalon/active/decision.py`. (b)
`src/etalon/active/schema.py` (`Endpoint`, where `max_replicates` and its validation live),
`src/etalon/active/store.py:459-461`, `src/etalon/runtime/operations.py:212-214`,
`src/etalon/active/policy.py:47,89`. (c) `src/etalon/faults/stability.py:65-68,171,275-281`. (d)
`src/etalon/faults/stability.py:72-88,176-211,288-301`. The fault's `Consequence` stays
`WRONG_SIZE` throughout — I am not proposing a single draw block a spend, which would contradict
`docs/adr/0002`'s finding that band and consequence are different questions.

**Cost.** Moderate; it touches four modules. (a) and (d) are the valuable half and the cheap half.

**What it risks breaking.** (b) changes selection for any endpoint that raises the floor — more
spend per candidate, fewer candidates covered, which is the intended trade and should be approved
rather than discovered. (d) turns previously `evaluable=True` observations into `evaluable=False`,
with the same `admission_view` consequence flagged in P2, so it should land after P2's audit.
Note that none of this unblocks `prism_mmpbsa_replicated`: `runtime/executors.py:388-400` is
refused for a different and correct reason, and that refusal should stay until independent-replica
execution is actually wired.

**How to verify by mechanism evidence.** For (d) the mechanism is directly countable and needs no
score: **the number of stability observations whose declared replica count disagrees with the
count of authorised replicate actions, over the number of stability observations examined.** That
count says how often the clearing of `F_SINGLE_REPLICA_ESTIMATE` rested on an unverified
declaration. The fixture: declare `replicas=5` against a campaign holding two authorised replicate
actions and require the observation to become unevaluable rather than clearing. For (a), (b) and
(c), the mechanism evidence is dispersion, reported the way `active/benchmark.py:86` already
reports it — `sd_*` with `None` at n = 1 — computed across the *authorised* replicate seeds of real
readouts and reported **per task, never pooled**. Input 6's measurement is the reason to insist on
per-task: 0.0000 on one task and 0.1364 on another means a pooled figure describes neither. Per
hard constraint 7, a task whose dispersion cannot be computed because it has one replicate is
reported as not taken, never as zero dispersion.

### P5. Report allowance granted against allowance consumed, partitioned by reason

**What changes.** Close asymmetry (C)'s resource half with the smallest possible instrument: a
read-only per-round report pairing granted with consumed, per declared unit separately, in four
states rather than one number — `consumed`, `deliberately_reserved`, `not_attempted`,
`unresolved`. The precedent to copy rather than reinvent is `learn/admissible.py:291-315`, which
reports a rate, and `:353-362`, which warns below a stated convention threshold with an
explanation of what the surviving set is a selection *of*. The warning threshold here is likewise
a `convention` under hard constraint 5 — nothing has measured where the real boundary is — and
must not be dressed as a measurement.

The `deliberately_reserved` state is not decoration; it is the whole difficulty.
`active/decision_benchmark.py:136-137` states that *"a confirmation guard may deliberately leave
unusable budget"*, and `protocol_stopping_benchmark.py:87` scores `budget_saved` as a virtue. A
detector that cannot tell a reserve from a failure would be worse than none. The good news is
that the reserve is already represented: `CampaignSpec.confirmation_reserve` and the guard at
`active/store.py:475-488` are exactly the quantity that belongs in that partition, which gives it
a principled basis rather than a heuristic.

The reason to prefer a report over a mechanism that pushes the agent to spend more: input 4's own
measurement is that **more iteration was not the lever** — passing tasks used fewer turns (mean
12.0) than failing ones (18.3). A harness that reacted to under-use by encouraging spend would be
optimising the quantity the data says is not the problem. What under-use earns is visibility, so
that slack and its reason arrive together.

**Files and call sites.** `src/etalon/active/store.py:292` (`_balance`, the only accounting view,
and the four keys to extend from), `:475-488` (the confirmation guard that defines
`deliberately_reserved`), `:490-492` (where quote and attempt count are written);
`src/etalon/active/runner.py:72` (`slots=spec.batch_size`, the per-round allowance) and `:174`
(the round summary, which today carries a cumulative balance and a `stop_reason` of `"ready"` for
both a 2-of-8 and an 8-of-8 round); `src/etalon/active/schema.py:189` (`batch_size`). Surfaced
through the existing status path (`src/etalon/runtime/api.py` and the status tools in
`src/etalon/mcp/`), not a new tool. **Not** `campaign/ledger.py`, which has no cost field — it is
a config-change journal and should stay one.

**Cost.** Low. It is arithmetic over records that already exist, plus the reason partition.

**What it risks breaking.** Very little, being additive and read-only. Two traps: hard constraint
6 forbids merging `RuntimeStore` / `CampaignStore` / `ResearchJournal`, so the report is per store
with any aggregate marked non-additive — already the runtime's own convention
(`additive=false`). And hard constraint 7 forbids filling an unknown charge with an estimate; an
unresolved action's true cost is reported as not taken, which the runtime's deliberately
conservative reservations already imply.

**How to verify by mechanism evidence.** The ratio alone is not mechanism evidence — a low ratio
is consistent with an agent that stopped early, an agent that was refused, and an agent that
could not afford the next call, and those demand opposite responses. The mechanism is **the
reason partition with its denominator**, verified by exact reconciliation: on a fixture round whose
granted and consumed values are known by construction, the four partitions must sum to
granted-minus-consumed exactly, computed from the ledger alone. That reconciliation is the
mechanism claim — it establishes the report reads the records rather than inferring from them.
Input 4's finding would appear here as a large `not_attempted` share with no refusals, which is a
different architectural problem from a large refused share and is only distinguishable because
the partition exists. Second check: `stop_reason` must stop being `"ready"` for a short round —
and the count of rounds whose recorded `stop_reason` disagrees with their slot utilisation,
against the number of rounds examined, is itself a countable mechanism quantity for the change.

### P6 (smaller, and required by the vocabulary). Type `soundness` and `progress`, or stop asking

Both exist only as prose in `.claude/skills/etalon-step-corpus/SKILL.md:30-35`. Either make them
derived fields or withdraw the request; a field the host fills from its own reading is the
configuration that skill's own last clause warns against.

The compliant form is a **derived, read-only facet of the admission export view**, computed from
codes already in the stored `Ruling`, carrying for each value the identifier of the rule that
derived it, and **absent** rather than empty where no rule reaches (hard constraint 7).
`soundness` maps onto distinctions the `Ruling` already carries — a `WRONG_SUBJECT` code that is
blocking and unwaived is not recoverable within the loop, whereas a `WRONG_SIZE` code in
`bounded` is. `progress` is a property of the operation-outcome sequence rather than of the
`Ruling`, so it will more often be the field with no rule, which is an acceptable and honest
outcome. Neither is a `Fault`, so neither belongs in the taxonomy and neither may touch
`catalogue_digest()`. Expect the `regressed` collision noted in §2.

**Files.** `src/etalon/learn/admission_view.py` — a third derived facet beside `admission` and
`exact_admission` in the node rows at `:503-526`, over the same `relied_on` edges. Then the skill
text changes from "fill them" to "read them", which is the point.

**Risk.** The view's `view_id` is a digest of its own content (`:539`) and `compare_views` refuses
two views built under different `view_version` (`:557-573`). Adding a facet invalidates every
stored view digest and forces `VIEW_VERSION` to move — correct behaviour, meaning views are
rebuilt rather than migrated, and downstream readers refuse rather than silently mix.

**Mechanism evidence.** **The disagreement rate between a host-filled value and the derived one,
over the number of comparable records, broken down by direction.** Agreement near one would mean
the prose instruction was working and the change buys only enforcement; substantial disagreement
is direct evidence the instruction-level field was carrying inferred values. Stronger second
check: the derived value must be a pure function of the stored `Ruling` plus the named rule, so
recomputing twice from the same stored ruling must be byte-identical — testable with no host at
all, and the thing that distinguishes a derivation from a judgement. Per the step-corpus skill's
own counting rule, report absolute counts and state when a class has fewer than fifty members
rather than computing a rate over it.

---

## 4. Hard-constraint compliance

Four moves I considered and am flagging explicitly; three are redesigned above and one is
dropped.

| Tempting move | Constraint it violates | Disposition |
|---|---|---|
| Have the export view write the derived `soundness` / `progress` back onto the leaf `Ruling`, so a reader needs one record instead of a join | **2** — export views do not write back to leaf records | **Redesigned.** P6 keeps the facet derived-only inside the view; readers join on `ruling_digest`, which `admission_view.py:166` already requires to match its ruling. |
| Backfill `admission` on historical nodes so warrant can be computed over existing history | **4** — admission is written at dispatch and may not be filled in afterwards | **Redesigned.** New records only, old ones in a marked partition. `RSI_REWARD.md:28` already concedes historical nodes are permanently `not_recorded`, and the recomputability-audit skill already prescribes the partition. |
| Merge the runtime and campaign cost ledgers to produce one granted-vs-consumed figure | **6** — `RuntimeStore` / `CampaignStore` / `ResearchJournal` are not merged | **Redesigned.** P5 reports per store with any aggregate marked `additive=false`, the runtime's existing convention. |
| Add the externally imposed acceptance criterion as a new `Fault` code so `rule()` can withhold on it | Not a violation of **1** as written — but it moves `catalogue_digest()`, invalidating every cross-version comparison, and it is conceptually wrong: a `Fault` is a cause of a *wrong number*, not an unmet acceptance criterion | **Dropped.** It is the obvious move and it is the wrong one. P1 routes the criterion through the evaluation contract, where `missing_policy: "insufficient"` and `not_declared` already express "no tool reported this" without touching the catalogue. |

Confirmed compliant throughout. **Constraint 1** — no proposal changes
`rule(Measurement) -> Ruling`; P2 changes the completeness of the `Measurement` handed to it and
P6 adds a derived view facet. **Constraint 2** — nothing written above writes back to a leaf
record. **Constraint 3** — no proposal erases a prior admission value or claim scope; the
`supersedes` chain checks at `admission_view.py:199-231` stay intact. **Constraint 4** — no
backfill; P1 and P2 apply forward only. **Constraint 5** — every new number carries a provenance
tag: `min_replicates` = 5 is `literature` (ESMACS/TIES), the aggregation fractions inherit the
`convention` tag their current constants already carry, and P5's warning threshold is
`convention`. **Constraint 6** — `asset/` was not read and no proposal touches it or merges the
three stores. **Constraint 7** — each proposal names the case in which its quantity is reported
as not taken rather than estimated.

One thing worth noting about constraint 5 in the existing catalogue: of the 20 entries in
`FAULTS`, the Evidence tags are 8 `measured_here`, 1 `measured_in_an_asset`, 1 `literature` and
**10 `convention`**. Half the catalogue is a number somebody chose. That is legitimate and
labelled, which is exactly what the constraint asks — but a reader of a `Ruling` sees codes, not
tags, and the per-code provenance is one join away. If a cheap addition were wanted beyond the
proposals above, surfacing each cited code's Evidence tag in the ruling's notes would cost almost
nothing and would make the convention/measurement boundary visible at the point of use rather
than in the catalogue.

---

## 5. Where ETALON is already ahead of the surveyed practice

Stated plainly, because the brief asks for it and because four of these are not small.

1. **`Consequence.UNVERIFIABLE` blocks a claim and never a spend.** The taxonomy separates "this
   number is about the wrong thing" from "this number may be fine and no re-run will confirm it",
   and `judgment/waiver.py:115-123` refuses a waiver for the latter because there is nothing to
   release. Input 6's whole shape — determinism mistaken for robustness — is a conflation of
   **precision** with **validity**, and ETALON already has two words, two consequences and a
   refusal for them. The surveyed benchmarks publish a verdict resting on one draw; ETALON would
   record that verdict as admitted and not reproducible, which is the honest shape of the same
   fact.
2. **Reward restricted to `EXACT` observables.** `RSI_REWARD.md:39-57` makes the improvement
   signal ungameable by construction rather than by vigilance, on the ground that an exact
   comparison has no knob. It also argues — correctly, and against the field's convergent
   practice — that **a held-out split cannot protect against learning the verifier**, because
   splitting by instance leaves the verifier shared. That is sharper than input 8's "sealed split
   scored once", and it is the reason to adopt the sealed-split element as ETALON already has it
   (`seen.py`'s one-way release, `journal.py:263-269`'s byte-level anti-laundering) rather than as
   the benchmarks frame it.
3. **Freeze chronology enforced by data, not asserted.** `panel.freeze_selection` refuses to
   freeze once the validation panel holds any observation (`:251-253`);
   `journal.py:258-262` refuses an input recorded after the freeze and evidence recorded before
   it, on a durable record sequence; `result_integrity.confirmation_eligibility` requires verified
   declaration *bytes* rather than a boolean or a flag. Compare `evaluation_contract`'s own honest
   admission that `predeclared` can only return
   `predeclaration_claim_chronology_not_verified`: the repository contains both the weak and the
   strong form of the same guarantee, knows which is which, and says so.
4. **A refused executor rather than a lying one.** `runtime/executors.py:388-400` registers the
   replicated MM-PBSA executor and refuses to dispatch it, because the fall-through *"would
   quietly run as one unseeded trajectory per action and report the result under a protocol id
   that claims recorded seeds and a known energy author."* Shipping an error instead of a
   plausible number is the decision input 3 is about, taken correctly, at cost.
5. **`method.run`'s failure feedback.** Against the 32.9% / 6.6% respond-and-adapt figures in
   input 5, a typed `kind` discriminator, a `missing_outputs` list, a bounded `stderr_tail`, a
   content-addressed log pin, `stderr_read_error` kept distinct from the program's own failure,
   and `"scientific_status": "not_inferred_from_exit_code"` is a materially better substrate than
   the harness those numbers were measured on — and no auto-retry means a failure cannot be
   silently absorbed.
6. **Honest negative claims written into the records themselves**, not into a caveat section:
   `improvement_policy_learning: 'not_demonstrated'` and `policy_equivalence: '… neither is a
   learned improvement policy'` inside the frozen decision body; `'myopic': {'status':
   'not_fitted', 'reason': 'no calibrated predictive query-value distribution'}`;
   `'causal_attribution': 'unresolved; factorial differences are descriptive'`; and at
   `research_decision.py:86-87` two of these are *validated constants* rather than decoration —
   `if (payload["scientific_truth"], payload["adoption"]) != ("not_certified", "not_performed"): raise`.
   `faults/stability.necessary_not_sufficient()` exists as a function precisely so the sentence
   survives summarisation. Input 8's mechanism-evidence requirement is in part a demand that
   systems stop inferring mechanism from a score delta; a record that states what it has *not*
   demonstrated is the same discipline discharged earlier.

---

## 6. What I could not determine from the code, and would ask a human

1. **Are `soundness` and `progress` meant to become typed fields, or to stay host-filled prose?**
   `CLAUDE.md` fixes them as vocabulary; nothing in `src`, `docs/` or any schema implements them,
   and their only operational appearance instructs the host to fill them. P6 assumes the first
   answer. If the second is intended, P6 should be dropped and the skill text should say the
   fields are host judgements, so a later reader cannot mistake one for a derived value.
2. **`findings/` is absent from this checkout** (excluded from Git by design, per `README.md`).
   Every headline number quoted in `README.md` — 19 heavy atoms with zero explicit hydrogens, 41
   of 41 gaff2 builds, Spearman 0.108 with interval −0.021 to 0.234, the council's J 1.000 → 0.917
   and 1.39 effective votes — was read as a quotation, not verified. Where a number also appears
   in a source docstring I treated the docstring as the citation. Which of these are current, and
   whether any have been superseded, needs a human.
3. **Is the `diagnostic` early return at `journal.py:230` a deliberate two-regime design or an
   accretion?** This is the question that most changes P1. If the two regimes are deliberate — a
   cheap diagnostic lane and an expensive validation lane — then P1(b) and P1(c) are right and
   P1 should stop there. If `diagnostic` became the default by accretion because
   `composition.record_evaluation` needed a value, then the stronger move is to make
   `independent_validation` the default and force the cheap lane to be chosen explicitly, which I
   am not proposing without knowing.
4. **Are `etalon-candidate-confirmation-freeze/1`, `snd1-seen-series-visibility-overlay/1` and
   `freeze_selection`'s `{P0/E0, P0/E1, P1/E0, P1/E1}` vocabulary deliberate single-task
   instruments, or prototypes of a general contract?** If they are meant to generalise, then
   promoting `panel.freeze_selection`'s chronology enforcement into a harness-level primitive
   outranks parts of P4 and P5, because it is one of only two mechanisms in the repository that
   enforce predeclaration from data rather than from a claim.
5. **Does `MethodUse.basis = 'tool_observed'` have any production path today?** The schema accepts
   it and `HOST_SETUP.md:221-223` says the journal accepts `host_reported` and that native traces
   should be preserved separately. If `tool_observed` is never produced, every attribution of a
   gain to the harness rests on self-report — exactly the axis input 7 says carries a 10× effect —
   and harness-attribution work is premature until observation exists.
6. **Is reasoning effort intended to be part of the usage-method identity U?** If so, a change in
   effort should move U's digest; because `host_conditions` is an unvalidated dict I could not
   determine whether it does, and input 7's non-monotonicity is unrepresentable until it does.
   Related: would a required key set for `host_conditions` be welcome, or is its openness
   deliberate?
7. **Is the external benchmark behind these eight inputs intended to run through `method.run`, and
   is its grader to be expressed as an evaluation contract?** This decides P1's scope. If the
   grader stays outside, the acceptance criterion remains structurally invisible to ETALON whatever
   P1 does, and the realistic goal becomes recording that the criterion was *not* covered — which
   `missing_policy: "insufficient"` and `not_declared` already express.
8. **Is the shuffled-signal control of `RSI_REWARD.md:106-116` scheduled?** `grep` finds shuffling
   in `active/protocol_benchmark.py` (where it shuffles public catalogue ids independently of the
   hidden response function, so public ids carry no signal) and in `tools/measure_council.py`, and
   neither is that control. It is the only mechanism-evidence instrument the design corpus
   specifies and the only one of input 8's convergent practices ETALON argues for *more* strongly
   than the field; whether it is scheduled decides whether mechanism evidence is a gap or a pending
   delivery.
9. **Are `controller.max_calls` and `max_seconds` meant to be read as allowances whose under-use
   matters, or purely as ceilings?** P5 assumes the former for campaign cost units and says nothing
   about these two. If model calls are also an allowance, the same report should cover them, and
   input 4's measurement suggests they are where under-use would show up first.

---

## 7. Owner decisions, 2026-11-10

Five items this review left open were decided by the repo owner and are now closed. Each is
recorded where it binds — in the normative document that states the behaviour, with a test
holding it — rather than only here. Listed in the order they were worked, which is the order
of leverage, not the order they were asked.

**§6.1 — `soundness` and `progress`: withdrawn, and deliberately NOT re-delivered as derived
fields.** `FIXED_TERMINOLOGY_STATUS.md` §6. Withdrawal is the answer to the question as posed;
the second half is the part worth noting, because the obvious alternative was to keep the
concepts as ETALON-computed fields and that was refused on the repository's own argument.
`Ruling` already separates `blocking` / `waived` / `bounded` / `unverifiable` / `unchecked`,
each fault carries a `Consequence` of `WRONG_SUBJECT` / `WRONG_SIZE` / `UNVERIFIABLE`, and
`Consequence`'s docstring says *"the band and the consequence are different questions, and one
field cannot answer both"*. A three-value summary over that is lossy re-presentation. For
`progress` the three values do not even share a subject: `advanced` at `research/entry.py:114`
is checkpoint freshness and `regressed` at `learn/acquire.py:10` is statistical regression to
a conditional mean. This review's P6 assumed the first answer and should be dropped.

The live hazard was never `CLAUDE.md` — `host.py:145` installs `src/etalon/HOST.md` as the
target's `CLAUDE.md`, so the conventions never reach a research host. It was
`.claude/skills/etalon-step-corpus/SKILL.md` telling the host to *fill* both fields, in a
paragraph whose own closing clause explained that an inferred value there is indistinguishable
from a measured one later. That instruction is removed, and `test_normative_consistency.py` J4
holds its absence across all 28 skills and `HOST.md`.

Left to the owner, with the argument written down: the one fact neither `Ruling` nor
`Consequence` carries is whether a given fault is **repairable or terminal** — today prose, in
each fault's `remedy`. The right shape is for each fault to declare it, not for a summary field
to enumerate which codes are terminal. It is a **Zone C** edit (the fault catalogue defines what
counts as a result) and so is not folded into a terminology cleanup.

**§6 (regimes) — the `assessment_role` deprecation warning does NOT become a refusal.**
`ASSESSMENT_REGIMES.md` §2. The hardening criterion decides it: with `assessment_role_basis`
recorded, an omitted regime is perfectly distinguishable from a chosen `diagnostic`, so the
indistinguishability that would justify hardening is already gone. Waiting for a
`defaulted_deprecated` count was also a deadlock dressed as diligence — the real population is
four records, none carrying a basis because they predate the field. The refusals that matter
already sit at the right boundaries: the impossible pair at `schema.py:312`, the undeclared
regime degraded by the membrane, and the over-claim refused by `research/decision_rule.py`.
Pattern: refuse the impossible, degrade the unestablished, refuse the claim that outruns its
own rule.

**`threshold_evidence` — resolved toward the stricter side; the contract schema now requires
it.** The inconsistency ran the wrong way: the `evaluation_plan` step required a provenance tag
while the contract schema — the one `evaluate_contract` computes `criteria_passed` from — had no
such field. Measured read-only on the real journals (2026-11-10): **zero** stored records carry
a `metrics` block, so requiring the field outright breaks no existing contract and the migration
question was empty. `PROVENANCE` now has one definition shared by plan and contract; provenance
is inside `evaluation_rules_digest`, so relabelling a threshold is a new rule identity; and the
published specification says what each tag *licenses*, which is the half of a criterion that is
not the number. `not_recorded` is a sentinel outside the vocabulary, mirroring `not_declared`'s
exclusion from `STATUSES`.

**Stage 2 held on a better ground; stage 3 refused.** `STOCHASTIC_MEASUREMENT.md` §5. Stage 2's
reason for waiting is not missing counts but that it mechanically lowers the measured reward
(`not_recorded` enters D4's denominator, not its numerator) while nothing established changes —
a self-measurement hazard under RSI. Its old gate could not open: the audit needs observations
and the real journals have **0**. Restated gate: after a campaign exists whose journal carries
non-zero observations. Stage 3 (`min_replicates`) is **refused**, not deferred: passes used
fewer turns (12.0 vs 18.3), ten seed scorings flipped no verdict, dispersion is per-task while a
floor is per-protocol, and both dispatchable kinds have `max_replicates = 1` so a floor of five
would refuse everything it applied to. Reopening trigger named and measurable.

**Constraint 6's "merge" — one record namespace.** `HARD_CONSTRAINT_ENFORCEMENT.md`. Read off
what a merge would destroy: each store *is* a set of refusals, so merging lets a row be written
through the weakest discipline and read as carrying the strongest. One file and one transaction
are already shared by design and stay permitted; sharing a key namespace, or writing into
another owner's, does not. Three checks hold it, measured on a real store rather than inferred
from twelve `INSERT INTO metadata` sites. Known and not fixed: the `research:` prefix is spelled
as a literal at ~40 **read** sites, which is debt rather than a breach.

### What was not on the list and mattered more

**ETALON recorded what was produced and never which capability produced it.** No MCP tool name
appears anywhere in 2001 real events. That one gap blocked three things at once: stage 2, the
recomputability audit, and the question of which of the 89 verbs are core. It is closed at the
one seam that knows the answer without being told — `mcp/_common.py::tool` wraps every
registered tool and already holds `function.__name__` — so every record written inside a
dispatched verb now carries it with basis `mcp_tool`, a value `capability_attribution.BASES`
had reserved before anything set it. 89 verbs, one change; the census reports the two bases
separately because a dispatched verb and a declared skill slug are not interchangeable evidence
for a routing decision.

**Two live defects found while applying the above**, both instances of the debt pattern named
this round (a feature that enumerates its subjects instead of reading a property they declare):

- `hooks/budget_floor.EXPLAINED_STOPS` had already drifted from `active/rounds.py` — missing
  `selected_action` and all three `ready_short_*` values — so rounds that *recorded* a reason
  were counted in `rounds_short_recorded_without_a_reason`. Now derived from the record layer,
  and the partition is three-way because a reason whose accounting failed is neither explained
  nor absent (hard constraint 7).
- `rounds.partition_reason` gated on `READY_REASONS`, which contains its own outputs, so a
  second pass could rewrite a recorded `ready_short_reserve_represented` into
  `ready_short_no_reserve` from whatever reserve that caller held. Latent, not live — all three
  call sites pass a fresh planning reason — and the function's own docstring already stated the
  narrow reading. The gate is now `!= READY`.

### One method note worth keeping

The J4 probe's first version required the fill verb and the term in the same sentence. The
instruction it was written against read *"Soundness and progress are separate fields. … Fill
them from rules over the fault codes"* — four sentences apart — so the probe matched nothing,
passed, and would have gone on passing with the hazard in place. It was caught only because the
falsifier quotes the removed text verbatim instead of paraphrasing it. The second version failed
too: a paragraph-wide negation check was cancelled by *"one field cannot hold both"* three
sentences earlier. What works is mood — an imperative opening its own sentence — judged per
sentence while the subject is judged per paragraph. A probe that matches nothing is
indistinguishable from a repository with no hazard, which is the same first principle one level
down.

### Correction to the method note above

The "method note worth keeping" in §7 was wrong, and the way it was wrong is the most
reusable finding of the round.

It reported that the J4 fill-directive probe needed its *mood* judged per sentence and its
*subject* per paragraph. That is a lesson about writing a better regular expression. But the
probe was a regex hunting imperatives across 28 skill files — **prose policing prose**,
which is the mechanism §6.1 of `FIXED_TERMINOLOGY_STATUS.md` had just finished arguing does
not work. It matched nothing twice while the hazard stood. A third tuning would have yielded
a better prose detector and no enforcement at all.

The question re-asked one layer down: **why can a field that does not exist be written?**
Measured, not assumed: `Artifact(bindings={"soundness": "sound"})` was written to the
journal and read back intact, while a typed `MethodEvaluation(..., soundness=...)` was
already refused. The hole was the free-form slot that is *also* where ETALON's own
annotations live — `capability_attribution.KEY` calls `bindings` "the reserved bindings
key" — which is exactly what makes a host-supplied value indistinguishable from a computed
one afterwards. `research/reserved_bindings.py` refuses it at `Artifact.__post_init__` and
`Experiment.__post_init__`, with the legal route in the message. The regex probe was
**deleted**, not demoted: a second prose check kept for defence in depth is the same mistake
in a smaller font.

Three things generalise:

1. **Tuning a pattern over prose means the instrument is wrong.** Find the seam where the
   mistake becomes indistinguishable later and refuse it there. A document-level test can
   honestly hold doc↔source *agreement* and never behaviour.
2. **Scope a refusal to what ETALON would be read as having produced.** `bindings` yes;
   arbitrary payload content no, because `progress` in a caller's own document legitimately
   means how far a screen got (`boundary/screen.py:178`). The first structural check
   overreached here too and failed on ten legitimate sites — the same error one level in.
3. **A refusal must name the legal route**, or it is a wall. Verified safe the cheap way:
   the full suite's 96 failures and 9 errors are identical before and after, and none of
   4529 passing tests — many of which write records — hits the new gate.

The same correction surfaced a smaller instance of the round's debt pattern: the running-verb
consultation sat in `components.record_json`, i.e. per write site, so every other caller
assembling bindings would have had to copy it. It moved into `with_attribution`, and the
write seam now holds no branch.

### Finishing the round: three things the correction surfaced

**A false claim I had written into a normative document, found by checking it.** §7's
deprecation entry rested on the omissions being visible, and `ASSESSMENT_REGIMES.md` §2 said
the `defaulted_deprecated` share "is reported in the coverage block". It was not. The
membrane reported `by_class_basis` over **edges**; nothing counted the **records**. That is
precisely the failure the document exists to refuse — a record claiming more than was
established — and it was load-bearing, because "never refuse an omitted regime" is honest
only while someone can see how large the unrefused population is. "It is countable" is not a
count, and a population nothing reports grows unwatched.

Fixed by implementing the count rather than by softening the sentence:
`learn/admission_view.py::_role_basis_census` reports, inside the `membrane` block,
`explicitly_declared` / `defaulted_deprecated` / `not_recorded` over the stated denominator
of records carrying an assessment role. Three answers, not two: a record predating the field
is a different fact from an omission its writer was warned about, and `not_recorded` is
every real record measured so far (4 of 4). Computed from the regimes the view already
reads, so it adds a report and not a pass.

**The restatement had not landed where the constraint is stated.** Constraint 6 in
`CLAUDE.md` still read "do not merge RuntimeStore / CampaignStore / ResearchJournal" with the
ambiguity the ledger had just resolved. A decision recorded only in the ledger is a decision
the conventions still contradict, so the constraint now carries the definition — one record
namespace, file and transaction sharing permitted — and names the test that executes it.

**Prose-as-discipline residue in the skill I had just rewritten.** My replacement paragraph
opened "Do not fill a soundness or progress field", which is the same shape as the
instruction it replaced: a skill paragraph doing enforcement work. The write is refused now,
so the skill's job is to say where the fact lives. It leads with the ruling, then the
retained-baseline comparison, and mentions the refusal as a property of the system with the
legal route beside it — information the host cannot get any other way, which is what a skill
is for.

Also closed, being the ledger's own next-cheapest check: **C2's leaf clause** (constraint 2,
`partial` → `executable`). Two checks instead of the one proposed — deep equality plus
canonical bytes over graph and bindings, and re-deriving the view to require the same
`view_id`. The second holds the constraint *by its consequence*, so it fails for a write-back
nobody enumerated; prefer that form wherever a constraint has one. Both reuse
`test_admission_view`'s fixture builders, because a graph literal in the ledger's own test
file would pin that file's idea of a projection rather than what the view reads.

Housekeeping from the same pass: the two J3 derivations whose premise ended with the
withdrawal were removed, including `_derive_reporting_term`, which by then referenced a
constant already deleted and survived only because nothing called it.

**Enforcement status after the round:** C1 executable, C2 executable, C3 promise, C4 partial,
C5 partial, C6 executable, C7 partial. Three of seven now refuse a violation in the suite,
against one at the round's start.

---

## 8. The loose internal benchmark, and the one defect it made owed

The owner's design for driving RSI is an internal benchmark that is deliberately loose and
flexible, possibly an LLM judge, with the qualification that having none would be
acceptable. The first-principles reading is recorded in `ASSESSMENT_REGIMES.md` §7 and is
short: **that instrument is already defined — it is a `diagnostic`-regime instrument, and
the design needs no new record type, no new regime value and no new refusal.** The lane buys
what a loose judge needs (no predeclaration, reused bytes, cheap proxies) and costs what one
must be made to cost (it structurally cannot be relied on).

The fit is exact rather than convenient. `RSI_REWARD.md`'s argument is that no split of an
external benchmark protects against learning the verifier; an LLM judge is *easier* to learn
than a fixed scorer, because it is reachable by persuasion rather than by being right. The
two regimes are that argument localised to the record: `diagnostic` is where the verifier may
be learned freely because nothing propagates. And the owner's qualification is the stronger
position: admission is not a score, so nothing here needs an internal benchmark to function.

**What had to change was a defect, not an addition.** Tracing where a judge's verdicts would
go — consolidated into lessons — found that `etalon-method-experience/1` was outside the
membrane's scope while being a legal premise ref, and that a human label on a `supports`
edge from a lesson could promote it to `relied_on` with nothing to stop it. Verified in
source before acting: `evidence_refs.py:23` makes it a `CONTENT_SCHEMAS` member,
`method_links.py:79` emits `selection_basis`, `admission_view.py:56` has that relation in
`_RELIED_BY_RELATION`, and `:168-169` returns `labelable=True` for `supports`. The
membrane's own prose — *"no label can make it have been"* — **was false for a lesson**.

Closed as `ADMISSION_PROPAGATION.md` §12 (view version `/4`): a node carrying an
`experience` block declares `not_an_assessment` with `degrade_basis
"lesson_cannot_settle"`. One branch closes both routes, because `_classify` applies the
label and *then* consults the regime. Invariants I21/I22 declared and bound.

Three things about this worth keeping:

1. **It passed the stopping rule this round adopted, and would not have before.** A
   record-layer addition must name a subject it would catch within one real campaign. The
   hole had no subject while the RSI loop was unspecified; the owner's design supplied one,
   and the fix became owed rather than optional. That is the rule working in the direction
   it was meant to — gating, then opening.
2. **`not_an_assessment` is a new state because the old one did nothing.** `not_applicable`
   means the membrane has no business with a node and leaves every derived value alone;
   `not_an_assessment` means the node cannot settle a premise at all, so reliance degrades.
   Before v4 those were one state and a lesson got the first.
3. **The census I had just added would have been quietly corrupted by my own fix.** A lesson
   regime carries `role_basis: None`, which `_role_basis_census` would have counted as
   `not_recorded` — padding the one figure added that same day to keep "never refuse an
   omitted regime" honest. Caught and excluded (I22). A number added for honesty is not
   self-maintaining.

### What must stay outside the judge's reach, stated precisely

Not "the scorer" — that is the obvious answer and the wrong one. The line is the one
`contract_spec.py` already holds: **publish the specification, never the oracle.** Locking
the criterion away is not safety, it is the measured defect: 8 of 9 failures on a single
metric the agent could not read. Unreachable: the **verdict**. Readable: the **rule**.

---

## 9. The method-layer measurement: the ground truth fails its own criterion

This is the result the round was redirected to find, and it is worth more than anything in
§7–§8. Cost: one substituted function argument, GPU only, zero API quota, about one hour.

**Method.** `metrics/interaction.py::assess_boltz_all` builds its reference consensus
fingerprint entirely from the task's stored `gt_results/boltz_results_gt_dock` predictions,
so the reference side is recoverable from disk with no Boltz run. The candidate side is a
fresh 10-sample Boltz run. Feeding the **reference molecule** as the candidate therefore
returns Jaccard(fresh prediction of the reference, scorer's stored reference) — the same
molecule, predicted twice, under the stock metric with every other argument read from each
task's own `task.yaml`. Evidence: `measured_here`, 2026-11-10.

**Result, 8 of 10 obtained** (two returned `FileNotFoundError` on Boltz's affinity output
with eight successes under identical setup, so the failure is molecule-dependent; reported
as not obtained rather than estimated, per hard constraint 7):

| self-similarity | tasks |
|---|---|
| 1.0000 | 1JVP_1, 3QAR_2, 3QX5_0, 7OKM_1 |
| 0.9091 | 3GHW_0 |
| 0.8889 | 3KWZ_1 |
| **0.7500** | **2VQM_0, 3FFG_0** |

Range 0.7500–1.0000, median 0.9545. The condition is `gt: 0.75`, so **0.75 fails**:

> **On 2 of 8 tasks the ground-truth molecule does not pass its own criterion.**

Two further free findings from the recovered reference sets (sizes 3, 4, 6, 7, 7, 8, 9, 10,
10, 17):

- **Where the reference set is small the bar is an exact-match requirement.** With no extra
  interactions J = I/|R|, and `> 0.75` needs |R|=3 → 3 of 3 and |R|=4 → 4 of 4, since
  3/4 = 0.75 fails. `7OKM_1` and `2VQM_0` are those tasks. Neither failure is "far off";
  each is on a task admitting one answer — and `2VQM_0`'s reference molecule reproduces only
  3 of its own 4 interactions.
- **Where the fraction pins the decomposition, the gap is one interaction.** `3KWZ_1`
  passed with 7 of 8 plus one extra; `3QAR_2` and `3GHW_0` each reproduced 7 where 8 was
  needed. The other tasks' decompositions are ambiguous and the candidate fingerprints are
  unrecoverable — the evaluator runs Boltz in a `--rm` container under a temp dir.

**What this does to the scaffold fix.** The proposal was to have the agent rebuild the
reference side from `reference.sdf` and gate submission on the scorer's own quantity. The
replica reproduces the hidden reference **exactly on 4 of 8** tasks and is off by up to 0.25
Jaccard on others — and **the agent cannot tell which case it is in**, because telling would
require the hidden reference. So the fix is not built on sand; it is built on ground whose
elevation varies and is unobservable from above. Any A/B must report per-task replica
fidelity beside the pass rate, or it will attribute to the scaffold what belongs to the
metric.

**And the methodological point.** No amount of consolidating session notes would have
produced this. It came from asking what would falsify the premise and then measuring —
level 3 of the scientific-dreaming ladder, not level 1 or 2. It is also exactly the class of
fact the salience heuristic says to record: the environment will never volunteer that a
benchmark's pass line sits above what its own ground truth achieves.
