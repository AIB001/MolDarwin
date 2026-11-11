---
name: etalon-step-corpus
description: Build step-level training material from the existing research graph and admission rulings, reporting the selection it rests on, without new computation or new experiments.
---

# Build step material from records that already exist

The research graph and the admission rulings together already carry what a step
label needs. This produces that material and reports what it is a sample of. It
runs no calculation, requests no measurement and adds no record.

Walk the judgement nodes. For each, collect its premises along `relied_on` and
`support`, and keep the operation identities it rests on. A premise reached only
by `used` is an input to the work and not something the claim relied on; it is
recorded and does not propagate.

A node's admission comes from the ruling already written for it. `teaches` is the
label; `reproducible` is a separate fact about whether a claim can be rechecked
and not a statement about the molecule. A judgement cannot be better admitted
than the weakest premise it relied on, and the premise that set the limit is
named, because that name is what makes blame attributable later.

Read the refutation edges, including the ones whose target is another edge. A
refutation of a node says the claim was overturned. A refutation of a support
edge says the claim was not entitled to that support, which leaves open whether
the claim itself was wrong. These are different labels and collapsing them loses
the more common case, since a later high-fidelity observation usually invalidates
a premise rather than the conclusion.

Soundness is in the ruling, computed, and is not yours to supply. `Ruling`
separates `blocking` (fired, unwaived, about the wrong subject), `waived`,
`bounded` (about the right thing, off by the band), `unverifiable` (no claim
about the run can be checked) and `unchecked` (could not be evaluated), and each
fault carries a `Consequence` of `WRONG_SUBJECT`, `WRONG_SIZE` or
`UNVERIFIABLE`. That is finer than any three-value summary, which is why no such
field exists. Whether a particular fault is repairable is in its `remedy`, as
prose, deliberately: several of those are decisions with scientific content.

For whether the work moved, compare against the retained baseline — that is a
comparison between two evaluations, and no step-level verdict stands in for it.

Both names are refused if you put them in a record's `bindings`
(`research/reserved_bindings.py`), so you will find this out in the same session
rather than leaving a value a later reader cannot tell from a computed one. Any
judgement of your own is welcome under a name of your own.

Report the admission rate for each step type, not for the campaign as a whole. A
rate near one for some types and near zero for others is a fact about where the
material comes from, and a single campaign-level figure hides it. Where a rate is
low, say what the surviving set is a selection of: the work that passes preflight
is not a random draw, and on a congeneric series it is systematically the work
whose geometry was easy, which is not the work the screen is getting wrong. The
bias runs toward the uninformative cases, so material fitted on this set is
provisional and the withholding reasons are read before it is accepted.

Carry the rule version and the catalogue digest with the material. Material built
under one version does not mix with material built under another; a version
mismatch is an error and not a reason to proceed with the older labels.

Report the counts before using the material for anything. Fewer than five hundred
usable steps, or fewer than fifty in any class that a later comparison depends on,
is a quantity to state rather than a quantity to train on. Saying so costs one
report; training on it costs a conclusion nobody can locate afterwards.
