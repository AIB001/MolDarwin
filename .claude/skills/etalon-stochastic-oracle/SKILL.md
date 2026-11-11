---
name: etalon-stochastic-oracle
description: Declare the aggregation policy before drawing from a stochastic oracle, report dispersion per task rather than pooled, and never settle a decision from a single draw.
---

# Measure a stochastic oracle, do not sample it once

A stochastic oracle returns a draw, not a measurement. The measurement is a
statistic over draws, and which statistic it is must be chosen before the draws
exist. Declare it first: how many draws, what is computed from them, what counts
as present or absent in a single draw, and what the resulting number must reach.
A policy chosen after the draws are visible reads identically in the record to
one chosen before them, which is the one mistake here that no later reader can
undo.

Declaring it first is also the cheaper order. Choosing the statistic afterwards
means the draws you have are the draws that shaped the choice, so the only honest
thing left to report is that they did, and the work is spent.

Reproducibility is not dispersion, and confusing the two is the specific failure
to avoid. An external grader pinned its stochastic model's seed so that scores
came out bit-identical across three days of re-runs; the same metric, recomputed
across five seeds, had a spread of 0.0000 on one task and 0.1364 on another.
Nothing about the pinned run was wrong, and nothing about it was informative
about spread. Bit-reproducibility is **precision** of the pipeline. Dispersion
across draws is a property of the task, and a single run cannot see it however
reproducible that run is.

So dispersion is reported per task and never pooled. A pooled figure over those
two tasks describes neither of them, and the task whose spread is 0.1364 is the
one a decision rule would get wrong. Where a task has one draw, report its
dispersion as not taken. Zero is a measurement and absence is not; replacing a
quantity you could not count with a plausible figure is the one move the
conventions forbid outright.

A repeated seed is not a second draw. The runtime says so and refuses it — *"a
repeated seed is a retry, not a replica"* — and reuse of a terminal result,
duplicate action identities, and a fixed-seed cascade are each refused as
replica sources elsewhere for the same reason. Independent draws come from
distinct authorised seeds, and the count that matters is the count of those, not
the count you declared.

Treat a declared replica count as a declaration. `F_SINGLE_REPLICA_ESTIMATE`
fires below two replicas, carries a band of 1.5 to 12.0 kcal/mol under
`Evidence.LITERATURE`, and its consequence is `WRONG_SIZE`, so it lands in
`bounded` and annotates rather than withholds. The count it reads is a
caller-supplied integer whose default is one. Nothing checks it against the
authorised replicate actions. If you clear that fault by declaring a number,
you have cleared it by declaring a number, and the record cannot tell the
difference later — so declare the count you actually dispatched and say where it
came from.

Five replicas is the ESMACS and TIES convention and the remedy field says plainly
that no theory establishes it. Use it as a convention, labelled as one, and do
not let a `convention` number be reported as a measurement. The same applies to
any presence threshold you set over draws: the one aggregation rule the
repository hard-codes, a contact persistence of 0.5 over a presence cutoff of
0.3, is self-labelled a convention in its own module constants, and it is not
declarable per protocol. Yours should be declared, with its basis.

Report the statistic beside its dispersion and beside the number of draws it rests
on, the way the benchmark layer already does by reporting an `sd_` field as `None`
at one draw. A central value with no spread and no denominator is not a result
anyone else can check, and it is the shape in which a single draw passes for a
measurement.

A decision from a single draw is a decision you cannot defend and should not
record as one. If a second draw is unaffordable, say the quantity was not
measured and decide on that basis openly; that is a weaker claim honestly made,
and it stays correctable. Nothing here requires more draws than the question
needs — a settled question needs no replicates, and a draw spent on a question
you have already answered is a draw not spent on the one you have not.

`docs/thin-harness/ASSESSMENT_REGIMES.md` covers which lane a result can be
relied on in; a declared aggregation policy belongs in the evaluation contract,
for which see `skill-dependencies.json` and retrieve a named member through
`etalon_skill_read` rather than searching for an absent directory.
