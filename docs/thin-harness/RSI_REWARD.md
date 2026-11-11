# What an RSI revision is rewarded for

A revision needs a quantity that says whether it helped. This states which
quantity, derives it from what the system is for rather than from what is
convenient to measure, and says why an external benchmark cannot be that
quantity even when it is the thing we want to score well on.

## The quantity, derived from the purpose

The system exists to produce molecular design decisions that are warranted by
evidence. A decision that happens to be right about a molecule and rests on a
number computed from a different species is not a success of this system; it is
a coincidence it cannot repeat.

So one system is better than another when more of its decisions are warranted,
or when it reaches warranted decisions at lower cost. Both halves are needed.
Warrant without cost rewards a system that checks everything and decides
nothing; cost without warrant rewards the pipeline we already know produces
numbers uncorrelated with measured activity.

Warrant is definable inside the system and does not need a judge. A decision is
warranted when every premise it relied on was admissible. The premises are
recorded and admission is recorded, but the relation connecting the two is not
yet recorded, and it is the first thing to build. (Corrected 2026-11-05, U1 in
`ADMISSION_PROPAGATION_DECISIONS.md`: an earlier version said this relation was an
edge that already exists. No record joins a graph node to a `Ruling`.) Because
admission may not be backfilled, the relation can only be established for new
records from now on; historical nodes are permanently `not_recorded`. Nothing in this quantity asks whether a molecule was good, and
that is deliberate: the screen's own score has been measured against activity on
this project's development assay and the rank correlation was not distinguishable
from zero, so a reward built on it would be rigorous arithmetic over a quantity
that carries no information about the thing we care about.

The secondary half is the cost of reaching a warranted decision, charged through
the existing ledger: spend, wall time, and the number of expensive-tier calls. A
revision that holds warrant constant and halves the spend is an improvement and
should be rewarded as one.

## Why the reward is restricted to exact observables

The catalogue separates how an observable decides its question. An `EXACT`
observable compares two values that either match or do not: a digest against a
digest, a formal charge against an integer, a stereo SMILES against the parent it
came from. A `THRESHOLD` observable has a cutoff somebody chose. A `DERIVED`
observable is inferred and can be wrong in both directions.

A revision can improve a threshold-based rate by moving the threshold. It cannot
improve an exact rate that way, because an exact comparison does not have a knob;
the only way to make a digest match is to hand over the thing the digest was
taken from. Restricting the reward to faults whose exactness is `EXACT` therefore
makes the reward ungameable by construction rather than by vigilance, and the
property follows from a field the catalogue already carries.

Faults whose exactness is `THRESHOLD` or `DERIVED` stay in the catalogue, stay
reported, and stay out of the reward. They are diagnostics. Promoting one into
the reward requires first measuring its band, at which point it is a different
kind of fact and the promotion is a decision with a reason attached.

The argument above covers the *comparison* and not the *admission decision*, and
the admission decision has a knob of its own: a waiver admits a measurement that a
`WRONG_SUBJECT` fault withheld. (Added 2026-11-05, U2 and D3 in
`ADMISSION_PROPAGATION_DECISIONS.md`.) So the reward counts only
`Admission.ADMITTED`. `ADMITTED_UNDER_WAIVER` is a separate value and does not count
as a win; waivers are reported separately and charged to cost. Turning the knob
therefore only removes the decision from the numerator. The reward also does not
read `Ruling.admission` or `teaches`, which include `THRESHOLD` faults; it reads an
exact-only facet recomputed from the stored ruling (D1). A decision whose warrant
cannot be established (`not_recorded`) counts as a loss: it is in the denominator
and not in the numerator (D4).

A comparison holds the catalogue fixed. Adding or retiring a fault changes the
denominator, so a revision compared across a catalogue change is not compared at
all. Carry the catalogue digest with every reward figure, and refuse a comparison
whose two sides do not share it.

## Why a benchmark cannot be the reward

We intend to be measured on an external benchmark, and that is a reason to keep
it out of the reward rather than a reason to put it in.

Recursive self-improvement revises the procedure that produces procedures. A
fixed verifier is a function. An optimiser pointed at a function discovers the
function's properties, and a verifier's properties are not the same as the
properties of good molecular design. This is the failure that has been
demonstrated in language-model reinforcement learning, where randomised and
incorrect reward labels produced most of the gain that correct labels did, and it
is the failure this project's own shuffled-reward controls were built to detect in
a different layer.

The usual protection is a held-out split, and here it does not work. Splitting a
benchmark by instance leaves the verifier shared across both sides, so a revision
that learned the verifier scores better on the held-out half as well, and the
held-out half confirms a gain that is not one. There is no split of an external
benchmark that protects against this, which is why the protection has to be that
the reward is internal.

The benchmark's role is one gated measurement. Freeze the configuration, authorise
the run against that configuration the way a gate is authorised against a
calibration, run it, and report it. A later run under a changed revision is
visibly a different run rather than the same number improved.

A development signal, if one is wanted, comes from a subset declared burnt. That
protects against memorising instances. It does not protect against learning the
verifier, and saying so is part of using it.

## The control that detects a verifier having been learnt

Replace the verifier's signal with a shuffled or constant one on a development
subset and re-run the revision loop. A revision that still appears to improve was
shaped by the verifier rather than by the design problem. The control costs one
additional run and is the only observable here that distinguishes the two.

The same control applies to the internal reward. A revision loop rewarded on
exact-fault incidence should show no improvement when the incidence is shuffled.
If it does, the gain is coming from the revision process touching something else,
and the reward is not measuring what it is meant to.

## What follows

The score on an external benchmark is a consequence of making more warranted
decisions at lower cost, not a target to optimise. A system optimised against a
score is a system that scores well; whether it works is a separate question that
the score can no longer answer.
