---
name: etalon-assessment-regime
description: Name the assessment regime before recording an evaluation, keep the diagnostic lane cheap and the validation lane predeclared, and run the promotion from one to the other as the redo it is.
---

# Choose the regime you are working in, and say so

Every `MethodEvaluation` carries an `assessment_role`, either `diagnostic` or
`independent_validation`. The two are different kinds of claim, not two
strictnesses of the same claim, and the choice is yours to make before the work
rather than a label applied after it. State it explicitly. A regime you enter by
omitting a value is not a regime, and no later reader can tell a chosen
`diagnostic` from a forgotten one.

Work in `diagnostic` whenever you are finding out. It needs no predeclared
policy, no frozen chronology, no unseen bytes, no comparator pairing, and no
threshold declared in advance. You may reuse results you have already looked at,
use a proxy nothing has validated, change the question halfway, and stop when you
have learned enough. Spend this lane freely; it is where the method gets chosen.
Keeping an exploratory pass out of the record because it was exploratory is worse
evidence than a `diagnostic` record, not better.

What `diagnostic` cannot do is be relied on. That is a consequence and not a
policy: every check the lane skips is a check about provenance, so the record
cannot distinguish a result you predicted from one you had already seen. A
`diagnostic` evaluation therefore does not propagate admission. It is classified
`used` with the basis `regime_cannot_settle`, and a conclusion whose only
premises are `diagnostic` derives `not_recorded` rather than `admitted`. Its own
admission is still reported, honestly, from its own measurements; it simply stops
being somebody else's premise. Recording everything as `diagnostic` is permitted
and earns nothing, so there is no reason to do it.

A record whose regime is absent or unreadable is treated the same way: it may be
`used` and is never `relied_on`. Withholding one good premise costs the
information in one record; admitting one bad premise costs every conclusion built
on it afterwards.

Promotion to `independent_validation` is a redo, and the harness enforces that
with data rather than asking you to agree. Inputs must have been recorded before
the policy freeze, evidence after it, and bytes an earlier artifact row already
holds cannot be relabelled — `'already seen artifact bytes cannot be relabelled
as independent validation'`. There is no conversion and no flag. The diagnostic
pass produced a hypothesis worth paying for; promotion is paying for it.

Run the promotion in this order, because the order is the content. Decide what
the diagnostic pass actually established, and stop here if there is nothing you
would now predict in advance. Declare the evaluation contract first, with a
finite numeric threshold and a fixed comparator per metric and a `missing_policy`
of `insufficient`, and keep its rules digest. Record every input — subjects,
comparators, protocol, split, initial conditions — and only then freeze the
policy, binding those exact references into its `search_configuration`. Acquire
fresh bytes on the held-out task from the frozen initial state, with evidence
whose artifact role is `independent_validation` or `sealed_holdout`. Have the
admission binding written at dispatch, not afterwards, because a missing binding
leaves the node `not_recorded` and that counts as a loss. Then record the
evaluation with actual results and actual accounting references.

Leave the diagnostic record alone. It is not superseded, amended or withdrawn:
the two records are about different bytes, so they have different claim scopes
and neither replaces the other. Cite the diagnostic record as a `used` input to
the promoted work, which is where the hypothesis came from and is exactly the
classification it gets.

Promotion does not make the conclusion right. It makes it a conclusion you
committed to before seeing the answer. It does not make the metric meaningful, it
does not establish that the gain transfers to another task, and an admission
granted under waiver is reported separately and charged to cost rather than
counted as a win.

The design, with the refusals quoted and their line citations, is
`docs/thin-harness/ASSESSMENT_REGIMES.md`. Read
`docs/thin-harness/HARDENING_CRITERION.md` when deciding whether a new rule of
your own belongs in code, in a document, in a hook or in guidance.
`skill-dependencies.json` lists skills that help when the question calls for
them; retrieve a named member through `etalon_skill_read` rather than searching
for an absent directory.
