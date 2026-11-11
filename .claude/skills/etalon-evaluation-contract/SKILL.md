---
name: etalon-evaluation-contract
description: Find the acceptance threshold and the direction of the metric before starting work, then recompute the pass or fail yourself on every iteration instead of inferring progress from a quantity.
---

# Read the contract before measuring anything

Find the rule that decides acceptance before you do the work. Not the quantity to
report — the comparator and the number it must reach. A metric name, a unit and a
denominator are not a decision rule, and work aimed at a quantity whose threshold
you never found is work whose stopping point you chose by feel.

This is a measured failure and not a precaution. On an external benchmark an agent
measured the right quantity, saw that its candidate matched three of the
reference's six features, saw that same three twice across separate turns, and
submitted. Nothing in the record was wrong. The number was never compared to
anything, because no threshold had been stated, so three looked like three rather
than like a fail. A quantity you have seen twice and cannot compare is not
evidence of progress; it is the same unanswered question, reported twice.

Find the direction too, and find what the metric punishes. In the same benchmark,
two further submissions were mathematically unable to pass at the moment they were
submitted: the metric penalised extra features, so adding candidates had been
moving the score away from acceptance the whole time, and nothing in the loop said
so. A metric with a penalty term has a worst move that looks like effort. Work out
which move that is before the first iteration, because afterwards it is indistinguishable
from bad luck.

Declare the rule as a contract, not as prose. Each metric carries a comparator and
a finite numeric threshold — the contract refuses anything else with *"finite
numeric threshold and fixed comparator required"* — and a missing value is neither
dropped nor imputed: *"missing values cannot be dropped, imputed or passed"*, so
`missing_policy` is `insufficient` and a gap can never aggregate into a pass.
Aggregation orders `incomparable` above `criteria_failed` above `insufficient`
above passing, and where nothing was declared the status is `not_declared` rather
than anything resembling success. Cost is one metric family beside regression,
retention and funnel, and the aggregation takes the worst status over all of them,
so a passing cost criterion cannot overturn a failing quality one. They are
separate criteria rather than one blended score.

Note one real limit before you try to put the threshold in the wrong place. An
`evaluation_plan` step validates its metrics against an exact field set of name,
family, unit, denominator and missing policy, so a comparator and a threshold are
**not representable in the plan**. Declare them in an evaluation contract, keep
its rules digest, and reference the returned artifact from the evaluation's
result references. Nothing is promoted or adopted automatically by doing so.

Recompute the status yourself on every iteration. The rules digest is deliberately
stable under a change of observed inputs, which is what makes one declared rule
replayable against new evidence without its identity moving — so replaying costs
you a recomputation and no new measurement. The quantity drifting is not news; the
status changing is. An iteration that leaves the status at `criteria_failed` has
told you the loop is not converging, and that is worth more than the fourth decimal
place of a number that cannot pass.

Do not let the conclusion outrun the rule. A judgment of supported against a
replayed status of `criteria_failed` is refused — *"unsupported judgment conflicts
with verified evaluation status"* — and so is a report whose rules digest differs
from the frozen rules the decision was made under. Write the conclusion the replay
supports, and when it is a fail, that is the conclusion.

When the acceptance criterion lives outside the system and cannot be expressed,
record that it was not covered rather than substituting the criterion you can
compute. `missing_policy` of `insufficient` and a status of `not_declared` already
say exactly this, and saying it is a result. An unobtainable threshold is a reason
to stop and report, never a reason to submit and hope: both failures above were
submissions made in place of that report.

None of this fixes how many iterations to spend, which candidates to try, or when
to stop. It fixes only that you know what passing means before you spend the
first one. See `docs/thin-harness/EVALUATION_CONTRACT.md` for the contract itself
and `docs/thin-harness/ASSESSMENT_REGIMES.md` for declaring the rule ahead of a
promotion to independent validation. `skill-dependencies.json` lists skills that
help when the question calls for them; retrieve a named member through
`etalon_skill_read` rather than searching for an absent directory.
