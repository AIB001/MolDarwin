---
name: etalon-recomputability-audit
description: Count how much recorded history survives a change that invalidates admission verdicts, before that change is made, and decide whether the change is still worth its cost.
---

# Count what survives a change to the admission rules

A change to the fault catalogue, to a band, or to the rule that derives a claim's
admission invalidates verdicts already written. Some records can be recomputed
under the new rule and some cannot. Which is which is a count, not an estimate,
and taking it before the change is what makes the change reversible.

Count four classes separately, because they fail for different reasons and only
one of them is recoverable by work.

Records whose observations are absent entirely cannot be recomputed. The fault
layer includes non-firing observations so that a reader knows the checks ran; a
record created before that convention cannot distinguish a clean check from an
absent one. These are marked unchecked and leave the corpus. No later work
recovers them.

Nodes whose `kind_basis` is `legacy_record_semantics_inferred` carry an E/J/X/R
classification that was inferred at projection rather than declared at emission.
Propagation over them produces labels whose provenance is the inference, not the
record. They remain readable and stay out of training material.

Measurements holding only a cheap or only an expensive value have a ruling and no
comparator. `rule` takes `require_comparator` and the default is strict, so these
are visible rather than silent. They can be propagated and are reported apart.

Edges that do not distinguish a premise from an input are the expensive class.
Propagation follows `relied_on` and ignores `used`; an older edge recorded as a
plain dependency states neither. Report the three quantities separately: edges
where the distinction is automatically decidable, edges needing a human judgement,
and edges where the record cannot settle it at all. The middle quantity is the
real price of the change and the one worth knowing before paying it.

Give every count as an absolute number with its denominator, and name how it was
counted: the directory read, the field inspected, the query run. A proportion
without its denominator cannot be checked by anyone else. A count that could not
be taken is reported as not taken; it is not replaced by a plausible figure, and
the audit is more useful with a gap in it than with a number nobody measured.

Close with one sentence giving the proportion of recorded history that can enter
training material, and a judgement on whether the proposed change still earns its
cost at that proportion. A low proportion is not an argument against the change.
It is an argument for applying it to new records and leaving the old ones in a
marked partition, which keeps the earlier results reproducible under the rules
that produced them.

An audit is about one catalogue and one rule version. Carry the catalogue digest
and the rule version in the result so a later reader can see which change it was
taken for. A later change needs its own audit; this one does not transfer.
