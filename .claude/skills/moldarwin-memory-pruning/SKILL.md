---
name: moldarwin-memory-pruning
description: Decide what to leave out of a default research view when memory has outgrown the read budget, by measuring which records can be shadowed without changing any admission verdict, and recording the policy so a later round can judge it.
---

# Shrink the view, not the record

Use this capability when a research task's history no longer fits the reads that are supposed
to orient a host: a context view that truncates every time, a graph page that returns
`truncated`, a continuation that spends its whole budget before reaching the current question.

The answer is **never deletion**. `ResearchJournal` has no delete method and that is
load-bearing: a recorded identity cannot be rewritten, admission changes keep their old value,
and a provenance chain with a hole in it is not a chain. What this capability changes is which
records a *default view* presents. A shadowed record stays readable by reference, exactly as a
superseded one does.

## The question that has an exact answer

"Which records are worth keeping" is a judgement about the future and this capability does not
make it. "Which records can leave the view without changing a conclusion" is a measurement, and
that one is the gate.

```python
from moldarwin.learn.memory_shadow import check_shadow, free_to_shadow

report = check_shadow(graph, bindings, shadow=[node_id, ...])
report.safe            # no surviving verdict moved
report.free            # proposed nodes nothing relied on
report.load_bearing    # proposed nodes something relied on -- the cost
report.losses          # per node: before, after, which premises were lost
```

`check_shadow` runs `admission_view` twice, once on the graph and once without the proposed
records, and compares every surviving node. `free_to_shadow` takes a candidate list and returns
the largest subset that costs nothing, verified by the same recomputation rather than by the
greedy pass that proposed it -- two premises can each look droppable while dropping both moves
the floor.

Why recomputation and not an argument about edges: the reasoning "only `used` edges point at
it, so it is free" is correct and still not what to rely on. Propagation has corners that
reasoning misses -- a cyclic component takes `not_recorded` whatever its premises hold, so does
a node with neither premise nor ruling, and the membrane degrades a relied-class edge on the
*premise's* regime rather than on the edge. A measurement cannot drift from the rules; an
argument can.

## What to propose, in order

Propose candidates in this order, and let the gate refuse what it refuses:

1. **Superseded records whose successor is in the view.** The supersession is already recorded
   and `build_branch_context` already excludes them from `current_decision_refs`.
2. **Records reached only along `used` edges** -- `selected_method`, `prior_use`,
   `evaluation_cost`, `declared_*`. These are inputs, not premises.
3. **Closed branches** whose disposition is recorded and whose results nothing later relied on.
4. **Superseded notes** that `find_notes(current_only=True)` already folds.

Never propose, and the gate will refuse anyway: anything on a `relied_on` path to a surviving
conclusion -- `measured_result`, `evaluation_result`, `selection_basis`. A shadowed premise
takes its dependant's verdict to `not_recorded`, which the reward counts as a loss. Paying a
loss to save a read is the wrong trade in every case this capability is for.

## Record the policy, not just the act

A shadow applied and not recorded is indistinguishable next round from a record that was never
written. Write what was shadowed, the measured report, and the rule that chose it -- a rule
stated once can be compared with its successor, and a shadow applied by taste cannot.

The rule is itself a method with `usage_method` in its roles, so it is revisable like any
other: propose a successor, measure both with `moldarwin-skill-improvement`, and let
`compare_revision` rule on it. The dimensions that make sense for a pruning rule are **coverage**
(did the host still find what the next decision needed) and **cost** (bytes or records read per
decision) -- and `warrant` must be in the comparison too, as the control: a pruning rule that
improves reading while costing a verdict has not improved anything.

## What this does not establish

That the shadow was a good idea. `check_shadow` answers what it costs in admission, which is
the part that was uncheckable before; whether a host will want a record next week is a claim
about the future, and the episodic trace that would be evidence for it does not exist here
(`docs/thin-harness/RSI_ARCHITECTURE.md` §5.1). Treat a safe shadow as permitted, not as
validated, and reverse it the moment a later read needs what it hid -- which costs nothing,
because nothing was deleted.
