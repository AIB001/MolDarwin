# Where a change belongs: the hardening criterion

Status: design v1, 2026-11-09. Companion to `ASSESSMENT_REGIMES.md`. Binding conventions:
`CLAUDE.md`. This document decides one thing: given a mistake worth preventing, which of
four layers should prevent it. It is short on purpose.

Citations were read on 2026-11-09 against the working tree; each quotes the text it relies
on.

---

## 1. The rule

> **Harden in code where a mistake becomes indistinguishable from a correct record later.
> Leave free where a mistake is visible and recoverable in the same session.**

This is not a new principle. It is the repository's own sentence promoted from a skill to a
design rule. `.claude/skills/etalon-step-corpus/SKILL.md:30-35`, on `soundness` and
`progress`:

> Fill them from rules over the fault codes and the operation outcomes on the first pass.
> Where a rule does not reach, leave the field empty; **an inferred value here is
> indistinguishable from a measured one later**, which is the failure this project has a
> vocabulary to avoid.

The same test decides every hardening question, because every hardening question is the
same question: after this session ends, can anyone tell the mistake from the correct thing?
If the record is the only witness and the record reads the same either way, the record must
not be allowed to be written. If the mistake announces itself while the host is still
looking at it, forbidding it buys nothing and costs the host a decision that was theirs.

### Corollary

**The hardened set is small and concerns only provenance and propagation, never method
choice.** Provenance and propagation are exactly the facts whose falsification is invisible
later: which bytes, in what order, relied on by whom. A wrong method produces a wrong
number that stays wrong and visible; a wrong provenance produces a right-looking number
that cannot be unmade. If a proposed refusal is about *what* to compute rather than about
*what the record claims*, the criterion has been misapplied.

## 2. The four layers, and the test that assigns work to them

Ask the questions in order and stop at the first yes.

**1. Does the mistake become indistinguishable from a correct record later?**
→ **Harness code that refuses.** Raise at the write, not at a review. The precedent to copy
is `authority.authorize()`, which refuses to take a verdict as an argument and says why at
`authority/grant.py:232-235`: *"it does not take a verdict from the caller — it calls
`etalon.faults.preflight.check_record` itself. A function that accepted 'this one passed'
as an argument would be a guard on the path nobody takes with extra steps."* A refusal
reachable only from an optional path is in layer 4, whatever it looks like — that is the
bug class `docs/adr/0006` is named for (`README.md:446`).

**2. Is the mistake distinguishable from the record, but only by a reader who already knows
what the design was?**
→ **Markdown.** Write the design down. This is the layer whose absence was itself the
defect behind `ASSESSMENT_REGIMES.md`: a previous agent read all 244 source files and could
not determine whether the `diagnostic` early return at `research/journal.py:230` was a
deliberate two-regime design or an accretion (`etalon-architecture-review.md:623-629`). The
code was correct and the ambiguity was total. Code cannot carry intent; a document can, and
it is the cheapest of the four layers by a wide margin.

**3. Is it visible in-session, but at a moment the host will walk past — because the right
action is one step away and nothing is in the way?**
→ **A hook that interrupts.** Interruption at the moment of the action, not refusal: the
host may proceed. Use this layer only when the timing is the whole problem. A hook that
fires on something the host would have noticed anyway is noise, and noise trains hosts to
dismiss hooks.

**4. Is it visible and recoverable in the same session, and does the right choice depend on
the science?**
→ **A skill that teaches.** Say what good practice is and why, and leave the choice. This
is where everything in §3 lives, and it is the largest layer. `README.md:49` already says
the skill directory is a discovery entry point and not a whitelist of permitted research
(F04).

A change belongs to exactly one layer. Two layers for one mistake means one of them is
unreachable, which returns it to the ADR 0006 class.

### Worked assignments

| mistake | layer | why |
|---|---|---|
| regime entered by omission | 1, refuse | an omitted `assessment_role` is indistinguishable from a chosen `diagnostic` the moment the record exists (`ASSESSMENT_REGIMES.md` §2) |
| a `diagnostic` record used as a premise | 1, refuse (by classification) | after the fact, a derived `admitted` carries no trace of which lane fed it (`ASSESSMENT_REGIMES.md` §3) |
| whether the two regimes were deliberate | 2, markdown | the question a full source read could not answer |
| deciding from a single stochastic draw | 4, teach | the draw count is in the record; the host can draw again in the same session |
| declaring an aggregation policy after seeing the draws | 1 if the policy is recorded, else 4 | a policy recorded after the fact reads identically to one recorded before it — this is a chronology fact, and chronology is provenance |
| submitting without finding the acceptance threshold | 4, teach | recomputable at any time, by the host, from the contract |
| spending fewer turns than the allowance | none — report it | `etalon-architecture-review.md:447-451`: under-use earns visibility, not pressure |

## 3. What stays free

These are the host's, and no layer-1 or layer-2 change may take them:

- **method choice** — which algorithm, which representation, which tool;
- **hypothesis** — what is being claimed and what would refute it;
- **which proxy to use** — including a proxy nothing has validated;
- **how many candidates to explore**;
- **when to stop exploring**;
- **how to spend the `diagnostic` regime** — all of it, including reusing seen bytes and
  skipping comparator pairing, which is what the regime is for
  (`ASSESSMENT_REGIMES.md` §1.1).

This list restates `README.md:46-54` F01–F04 and F09 rather than adding to it: the host
leads, a legal action may use no skill at all, skills may be partially used or combined or
modified, the skill directory is not a whitelist, and exploration is not promotion.

### The reason, measured

Forcing more iteration would be worse than useless. On an external benchmark, **the tasks
that passed used fewer turns (mean 12.0) than the tasks that failed (mean 18.3)**, and
fewer oracle calls (`etalon-architecture-review.md:447-451`). Evidence class: an external
measurement quoted into this repository's review, not `measured_here`.

A harness that reacted to under-use by pushing the host to iterate would be optimising the
quantity the data says is not the problem — and it would be doing so by spending the
host's attention, which is the resource the passing runs had more of. The number does not
say iteration is bad. It says iteration is not the lever, and a layer-1 refusal aimed at a
non-lever costs capability and buys nothing.

What under-use earns is visibility: slack reported beside its reason, so that a deliberate
reserve and a failure to use the allowance are distinguishable
(`etalon-architecture-review.md:428-451`). That is a report, which is no layer at all.

## 4. How to tell the criterion was applied rather than cited

Two checks, both cheap:

- **For a layer-1 change:** name the two records — the correct one and the mistaken one —
  and show that they are byte-identical. If you can write down a field that differs, the
  change is layer 2, 3 or 4, and the refusal is costing freedom for a distinction a reader
  could already make.
- **For a layer-4 change:** name the moment in the same session at which the host would
  see the mistake, and the action that recovers it. If you cannot, it is layer 1 and
  teaching it will not hold.

Per hard constraint 7, a layer assignment that cannot be justified by either check is
reported as undecided rather than defaulted to the stronger layer. Defaulting to refusal is
how a small hardened set stops being small.
