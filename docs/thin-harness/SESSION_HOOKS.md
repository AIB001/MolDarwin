# Session hooks: the recoverable half of the hardening criterion

Status: **implemented**, in `src/etalon/hooks/`. Not installed by any export; a host adds them
deliberately. This document is the contract and the installation note.

Terminology follows `CLAUDE.md` verbatim.

## 1. The criterion that divides this from hardened code

One rule decides whether a measured failure becomes a refusal in code or a hook that interrupts, and
it is the repository's own. `.claude/skills/etalon-step-corpus/SKILL.md` says of `soundness` and
`progress`:

> Where a rule does not reach, leave the field empty; an inferred value here is indistinguishable
> from a measured one later, which is the failure this project has a vocabulary to avoid.

So:

**Harden in code where a mistake becomes indistinguishable from a correct record later.** An absent
observation recorded as a clean `Ruling`; an untested threshold that produced an empty shortlist; a
verdict accepted as an argument instead of computed. A year on, none of these is distinguishable
from the correct record, so the record must not be able to say it.

**Leave free, as a hook that interrupts rather than refuses, where a mistake is visible and
recoverable in the same session.** An unspent allowance; a rule that already refuses the artifact
about to be submitted; the same tool error twice; a diagnostic lane whose prose has started to rely.
Each of these is in the transcript, nothing has been recorded, and the fix costs a sentence.

Two corollaries, honoured throughout:

- Hardened code concerns only **provenance and propagation**. It never constrains method choice. The
  gate check asks whether a threshold was calibrated, never whether the threshold is good; the
  coverage block asks who computed an observation, never which checks a campaign should run.
- A hook constrains nothing at all. Exactly one hook can object, in exactly one case, and that case
  is a declared outcome contradicting a replayed numeric rule — stated in its own module docstring
  and nowhere else.

## 2. The four hooks

Each is a plain function, independently importable, independently installable. Every number a hook
reports carries its basis, because hard constraint 5 applies to a hook's own figures exactly as it
applies to a fault's band.

| hook | fires on | reads | can block |
|---|---|---|---|
| `rule_replay` | before a submission | an `etalon-evaluation-contract/1`, replayed by `evaluate_contract` | **yes**, one case |
| `budget_floor` | at `ready` | `CampaignStore(..., read_only=True).snapshot()` | no |
| `tool_error_loop` | `PostToolUse` / `PostToolUseFailure` | the event, plus its own session memory | no |
| `regime_drift` | periodically, or at `Stop` | `research_recorded` events, read-only | no |

### 2.1 `rule_replay` — the declared rule, replayed before the hand-in

Measured: two submissions were already mathematically unable to pass at submission time and nobody
noticed. The rule is already first-class data — `evaluation_contract` metrics carry an `operator` in
`{le, lt, ge, gt, eq}` and a finite numeric `threshold`, refuse anything else, and pin
`missing_policy` to `"insufficient"` — and `evaluate_contract` already replays it, read-only, FREE
on the tool surface as `etalon_method_evaluate`. Nobody was calling it before the hand-in.

The one block: a **declared outcome in the contract's own vocabulary** that contradicts the replay.
`research_decision.py` already refuses that shape for a recorded decision (*"unsupported judgment
conflicts with verified evaluation status"*); this is the same refusal one step earlier, where it is
still free to fix. A free-text conclusion is **never** blocked: classifying prose as a positive
finding is a judgement, and a judgement that blocks is one nobody can argue with where it acts.

### 2.2 `budget_floor` — granted beside consumed, partitioned by reason

Measured: 2.0–2.9 of 8 structure-oracle calls, 2.4–6.0 of 15 property-oracle calls, then `ready`.
`active/budget.py` is three functions about not exceeding an allowance and none about failing to use
one; `_balance` returns four keys and `remaining` is read only to decide whether the next action
fits.

The hard part is not the arithmetic. Under-spend is sometimes the designed outcome —
`decision_benchmark.py` states that *"a confirmation guard may deliberately leave unusable budget"*
and `protocol_stopping_benchmark.py` scores `budget_saved` as a virtue — so the report is four
states and `deliberately_reserved` has a principled basis: it is recomputed from
`CampaignSpec.confirmation_reserve` and the guard that raises `BudgetExhausted("proxy action would
consume the objective confirmation budget")`. Where the campaign's policy does not arm that guard,
the reserve is **zero with a stated reason**, because "no reserve was represented" and "no reserve
was wanted" are different facts.

The hook does **not** ask for more spend, and says so in its own output. Input 4's measurement is
that more iteration was not the lever: passing tasks used fewer turns (mean 12.0) than failing ones
(18.3). What under-use earns is visibility, so that slack and its reason arrive together.

Second signal, free: per round, slots granted (`spec.batch_size`) against slots used
(`len(actions)`) against the recorded `stop_reason` — because today a round that used 2 of 8 slots
and one that used 8 of 8 are both recorded as `"ready"`.

Two guards on the hook's own honesty. The partition is reconciled against the action rows before it
is reported, and a partition that does not reconcile is reported and **not** interrupted on. An
outstanding reservation is `unresolved`, never `consumed`: hard constraint 7 forbids filling an
unknown charge with an estimate.

### 2.3 `tool_error_loop` — the fact that ends the loop, on the second occurrence

Measured: an agent repeatedly assumed variables persisted across calls to a stateless code tool and
ate `NameError`s without adapting. Independent base rate: of 6617 tool errors, models responded to
**32.9%** and changed a parameter in **6.6%**.

The second occurrence and not the first, because one occurrence cannot distinguish a tool that
failed from an agent that is not adapting. Identity is `(tool, error code, normalised message)`;
only the message is normalised, because `mcp/_common.py` flattens `StateError`'s whole subtree —
`BudgetExhausted` included — into `code == "StateError"`, so the message is what distinguishes a
budget refusal from any other state refusal.

Where no signature matches, the injected fact is **derived**: the repetition count and the argument
names whose values are byte-identical to the previous failing call. That is the fact the 6.6% figure
is about.

### 2.4 `regime_drift` — the lane that propagates nothing, and prose that relies

`research/journal.py`'s two-line early return stands in front of the strongest predeclaration
machinery in the repository, and `research/composition.py` defaults every evaluation to the lane
that skips it. A `diagnostic` evaluation receives none of: the frozen-policy binding, the
before/after-freeze chronology on the durable record sequence, the held-out comparison from the
frozen initial state, the evidence-role requirement, or the content-addressed check that
already-seen bytes are not relabelled.

Nothing is refused and nothing should be. `diagnostic` is legitimate, nothing propagates from it,
and forcing the stronger role would make the record less honest rather than more — a host that must
declare independent validation to record anything will declare it. What the hook reports is the
**ratio** of `independent_validation` to `diagnostic` in the window, which is the failure signature's
only visible form, plus the diagnostic conclusions whose language presumes reliance.

The language check is a **lexical count and is reported as one**: the matched phrases come back
verbatim with their conclusions so the operator reads the sentences, and the lexicon is tagged
`convention` because somebody chose the words. Conclusions already carrying the repository's own
negative-assertion idiom — `not_demonstrated`, `not_certified`, `descriptive`, `unresolved` — are
counted as hedged and subtracted, because that idiom is the honest form and flagging it would punish
the right behaviour.

## 3. Installing them

One entry point, `research_hooks.py`'s transport: event JSON on stdin, host response JSON on stdout,
diagnostics on stderr.

```bash
python -m etalon.hooks --hook tool_error_loop --state-dir /absolute/host-state
python -m etalon.hooks --hook budget_floor     --database /absolute/campaign.sqlite
python -m etalon.hooks --hook regime_drift     --database /absolute/campaign.sqlite --window 200
python -m etalon.hooks --hook rule_replay      --contract /absolute/contract.json \
                       --workspace /absolute/etalon-workspace.json
```

Exit `0` means the hook ran — stdout carries `{}` for a quiet hook and a `hookSpecificOutput`
envelope otherwise. Exit `1` means it could not run, with the reason on stderr; a host reading that
as a failed call is reading it correctly, because nothing was assessed. **A non-zero exit never
means the agent did something wrong.** The one hook that can object does so through
`permissionDecision` in its own output, so that a host without hook-level enforcement still receives
the finding as text; blocking by exit code would hide the objection from exactly the hosts that
cannot act on it.

These install **beside** `research_hooks.py`, not instead of it. They share no state directory and
no receipt identity, so adding one does not invalidate the research hook's receipts and
`etalon-research-hooks/4` does not move.

`tool_error_loop` needs `--state-dir` because it counts repetitions across calls. That directory is
**host session state and never a scientific record**: keyed by session, discarded when the session
ends, never read back as evidence. Hard constraint 6 is not at risk from this package — the campaign
store is opened `read_only=True` and the journal is reached through the read-only event reader; no
hook merges `RuntimeStore`, `CampaignStore` or `ResearchJournal`, and the budget report is per store
with its aggregate marked `additive: false`.

## 4. Two sources for the rule, and the one integration point still open

Until this round the decision rule's comparator and threshold were **unrepresentable** in the
journal's `evaluation_plan` step: `research/continuation.py`'s `_fields` is an exact-field check in
both directions, `research/composition.py` validated plan metrics against exactly
`("name", "family", "unit", "denominator", "missing_policy")` with no optional tuple, and the
contract↔plan cross-check projected only those same five keys. The rule had to be handed in as an
`etalon-evaluation-contract/1`.

`research/decision_rule.py` now makes it representable, and `rule_replay` reads both sources:

| source | read through | needs |
|---|---|---|
| the plan's own rule | `research.decision_rule.plan_rules` and `.replay`, via `rule_replay.plan_declared_rules` / `rule_replay.replay_plan_rule` | the plan detail and `observed` rows |
| an evaluation contract | `research.evaluation_contract.evaluate_contract` | the contract (inline or as a ref) and a workspace |

Both imports are **lazy and degrade to a stated absence**. That is deliberate: the module is owned
by another workstream, this hook must not hard-depend on a signature still settling, and a hook that
crashes because a field moved is worse than one that says the rule was not declared. The field names
`rule_replay.PLAN_RULE_FIELDS` are additionally compared against that module's `RULE_FIELDS` at call
time, so a drift between the two is reported rather than resolved in the hook's favour — reading
four fields where the validator requires three would accept half a rule.

One integration point remains open, and it is a different proposal:

| name | in | becomes useful when |
|---|---|---|
| `rule_replay.PLAN_RULES_DIGEST_FIELD` (`"rules_digest"`) and `rule_replay.rule_identity_from_plan` | `src/etalon/hooks/rule_replay.py` | the `evaluation_plan` metric validator accepts `rules_digest` as an **optional** field |

That is the architecture review's P1(a): bind the *contract's* identity into the plan via
`evaluation_contract.evaluation_rules_digest`, which is deliberately stable under a change of
observed inputs, so one declared rule can be replayed against new evidence without its identity
moving. It did not land — the representation that did carries the rule itself rather than a
reference to one. Until a plan can name a contract, this hook cannot check that the contract it was
handed is the contract the plan declared, and it reports `not_declared` rather than assuming they
match. A plan declaring two different rule identities is reported as `declared_inconsistently`
rather than as absence, because those are different problems.

## 5. What these hooks do not establish

A hook that fires does not establish that the agent was wrong, and a quiet hook does not establish
that it was right: `quiet` covers both "looked and found nothing" and "could not take the
measurement", distinguished by the reason it carries and never by silence.

No hook executes research, writes a scientific record, grants a permission or retries anything.
Those are `research_hooks.py`'s limits and they are repeated here because they are the reason this
package is safe to install: the worst a wrong hook does is interrupt a correct session, which costs
attention and shows up as an interruption nobody acted on.

The thresholds are conventions. `CONSUMPTION_FLOOR = 0.5`, `SLOT_FLOOR = 0.75`,
`SPEAK_ON_OCCURRENCE = 2`, `DIAGNOSTIC_STEP_FLOOR = 8`, `RELIANCE_PHRASE_FLOOR = 3`, and both
lexicons. Each is labelled `convention` in the hook's own `evidence` block, each names the
measurement it was chosen *against* where one exists, and none is presented as a measurement.
Nothing has measured where any of these boundaries is.
