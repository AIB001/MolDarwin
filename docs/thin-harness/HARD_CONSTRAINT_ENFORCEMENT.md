# Hard-constraint enforcement index

`CLAUDE.md`'s seven hard constraints are promises until something refuses a change that
breaks them. This file records, per constraint, what refuses today and what does not.

The reason to keep this index rather than trust the prose is already recorded in this
repository, by a test that found the same failure one scale smaller
(`tests/test_vendoring.py:137-145`): *"prose is the part of a provenance chain with no
reader that checks it, so it needs one."* That sentence is about a README naming two
superseded commits for months while every tool read the manifest. The seven hard
constraints are in exactly that position.

## Why this matters more under RSI than under human development

Today the constraints work, and this session is the evidence: five agents editing this
repository honored all seven, verified afterwards by hand. That works because a human or a
host reads `CLAUDE.md` before editing and chooses to comply.

The RSI goal is that ETALON self-tunes its skills and parts of its harness while doing
research. A host doing that is not stopped by prose. So each constraint has to move from
*stated* to *refused*, and the test for whether it has moved is blunt:

> **If deleting `CLAUDE.md` would let a change through, the constraint it stated is not
> enforced.**

The target state is that `CLAUDE.md` becomes an index of enforcements rather than a set of
promises. This file is the migration ledger.

## Status per constraint

Status values: **executable** (a check in the suite refuses the violation) · **partial**
(some clause refused, a named clause not) · **promise** (nothing refuses it).

| # | Constraint (abbreviated) | Status | What refuses it today |
|---|---|---|---|
| 1 | Do not change `rule(Measurement) -> Ruling`; node-level admission is a read-only derived view | **executable** | `tests/test_hard_constraint_enforcement.py::test_c1_*` (added here, mirroring `tools/falsify_optional_guard.py` probe C) and `tests/test_admission_view.py::test_membrane_is_read_only_and_the_graph_is_unchanged` |
| 2 | The export view never writes back to leaf records | **executable** (was `partial`) | the read-only test above pins the *input graph*; the leaf clause is now held by `test_c2_taking_the_view_leaves_the_leaf_records_and_their_bindings_byte_identical` (deep equality **and** canonical bytes over graph and bindings) and by `test_c2_taking_the_view_twice_over_the_same_inputs_derives_the_same_view_id`, which holds the constraint by its consequence and so fails for any write-back, including one nobody thought to pin |
| 3 | An admission state change keeps the old value and claim scope, per `supersedes`, without erasing | **promise** | `test_i8_dangling_supersedes_refused`, `test_i8_supersedes_cycle_refused` and `test_s10_1_supersedes_with_two_entries_is_refused` refuse malformed `supersedes`; **nothing checks that the old value and its claim scope survive** |
| 4 | `admission` is written at dispatch, never backfilled | **partial** | I20 via `test_a_record_predating_the_argument_parses_with_no_basis_and_is_refused_reliance`; adjacent checks exist in other subsystems (`test_method_feedback_delivery.py:191`, `test_parallel_harness_mcp.py:56`); no check that admission specifically is never backfilled |
| 5 | Every new number carries an Evidence provenance; `convention` is never presented as a measurement | **partial** (was `promise`) | per-site instances (`test_faults.py:380`, `ENSEMBLE_REPLICAS_EVIDENCE`), plus — new on 2026-11-10 — the clause now holds for the number that decides a verdict: an evaluation contract's `threshold_evidence` is **required** and validated against one shared `PROVENANCE`, held by `test_contract_spec.py::test_the_contract_schema_requires_a_provenance_tag_from_the_one_vocabulary`. Still **no check that a new number in general carries one**; §"cheapest next check" item 1 is unchanged |
| 6 | Do not touch `asset/`'s MolCascade / MolQuarry / PRISM; do not merge RuntimeStore / CampaignStore / ResearchJournal | **executable** (was `partial, second half not well-formed`) | first half: `tests/test_vendoring.py` has the tree digest, the dirt detector and `test_the_asset_readme_names_the_commits_the_manifest_pins`; second half: **restated 2026-11-10 as one record namespace** and held by `test_c6_the_research_journal_writes_only_inside_its_own_key_namespace`, `test_c6_the_namespaces_the_shared_table_carries_are_pairwise_disjoint` and `test_c6_a_recorded_research_identity_still_cannot_be_rewritten`, alongside the two type checks. See below |
| 7 | A quantity that cannot be counted is reported as not obtained, never estimated | **partial** | per-site: `test_a_value_that_was_not_obtained_is_insufficient_and_never_estimated`, `test_an_uncountable_reserve_is_not_obtained_rather_than_zero`, two in `test_sweep.py`; a global check is probably impossible — no test can assert nobody estimated anywhere |

## Constraint 6's second half cannot be enforced as written

"Do not merge RuntimeStore / CampaignStore / ResearchJournal" reads as three peer stores
to keep apart. The code is not shaped that way:

- `RuntimeStore` (`runtime/store.py:22`) owns `etalon-runtime.sqlite` and creates its own
  tables.
- `CampaignStore` (`active/store.py:44`) owns a caller-supplied path.
- `ResearchJournal` (`research/journal.py:18`) **has no store of its own.** It takes a
  `CampaignStore` and keeps its rows behind a key prefix in that store's `metadata` table.
  Its constructor calls `store.configuration()` with the comment *"Research belongs to a
  configured campaign, not a shadow database."*

So two of the three already share a file, deliberately, and that sharing is the opposite
of a merge — it is a refusal to give research a database of its own. A check asserting
three distinct paths would fail immediately on correct code, and the obvious weaker check,
"no module imports more than one", fails on three legitimate coordinators
(`research/method_execution.py`, `runtime/api.py`, `hooks/budget_floor.py`).

What is checkable is narrower and is what `test_c6_*` pins: the three remain three distinct
types, none an alias or subclass of another, and `ResearchJournal` remains a view over a
`CampaignStore` rather than acquiring its own connection. A future change that gave
research its own database, or that collapsed two of the types into one, fails there.

### The restatement, 2026-11-10: one record namespace

The owner was asked to say what "merge" forbids — one file, one type, one record namespace,
or one transaction boundary. **It forbids the third.**

The reading is taken from what a merge would actually destroy. Each store *is* a set of
refusals: `ResearchJournal._put` refuses a second, different body under an identity already
recorded (*"research identity cannot be rewritten"*), `CampaignStore` refuses a protocol
changed under an existing id, `RuntimeStore` keeps its own. Merge them and a row can be
written through the weakest of those three disciplines and read afterwards as though it
carried the strongest — which is the indistinguishable-later harm in its exact form, and
the reason this is a constraint rather than a preference about files.

The other three readings are refused for reasons in the code, not by taste:

- **One file.** Already shared, deliberately. `metadata` carries `research:`, `design:`,
  `resource:`, `budget:execution:`, `candidate-handoff:`, `execution-cost:`,
  `external-experiment:` and more, written from twelve `INSERT INTO metadata` sites across
  five modules. Forbidding a shared file would forbid the design the repository has.
- **One type.** What the two earlier `test_c6_*` checks pin. It is a proxy for the harm —
  useful, and not the harm itself.
- **One transaction boundary.** The journal shares the campaign's connection by design, so
  forbidding that would forbid `ResearchJournal.__init__`.

So the line is: **sharing a file and a transaction is permitted; sharing a key namespace,
or writing into another owner's namespace, is not.** Three checks hold it, and each was
written to fail on a real merge rather than on a rename:

1. `test_c6_the_research_journal_writes_only_inside_its_own_key_namespace` — configures a
   campaign, snapshots `metadata`, records one artifact, and asserts every key the journal
   added begins with `journal.PREFIX` and that no campaign key was already inside it.
   Measured on a real store rather than read off the source: the namespace is a property of
   the keys that actually land, and a source scan over twelve insert sites would have to
   guess each key expression. Both vacuity cases are asserted away — the fixture must write
   something, and the journal must write something.
2. `test_c6_the_namespaces_the_shared_table_carries_are_pairwise_disjoint` — `data/design.py`
   defines its own `PREFIX` into the same table; if either were changed to the other's
   value, two owners would share a key space with no error anywhere.
3. `test_c6_a_recorded_research_identity_still_cannot_be_rewritten` — the discipline half. A
   namespace without its refusals is only a string prefix, and a merge that kept the prefix
   while dropping the refusal would pass the first two checks.

**Known, and not fixed here:** the `research:` prefix is spelled as a literal at about 40
sites outside `research/journal.py` (`retained_baseline.py`, `evidence_window.py`,
`improvement.py`, and the `LIKE 'research:artifact-%'` queries). Those are **reads**, and a
read is a view over the namespace rather than a breach of it, so none of them violates the
restated constraint. But a namespace boundary spelled forty times is the debt pattern this
round named, and the fix — import `PREFIX` — is forty mechanical edits that would bury the
three checks above in the same change. Recorded here as the next step rather than done.

## The cheapest next check, per unenforced clause

Ranked by payoff over cost, not by constraint number.

1. **C5, as a registry rather than a scan.** A global "every number has provenance" check is
   not writable, but the pattern that worked for invariants is:
   `tests/normative_invariant_registry.py` lists each declared invariant against the test
   that holds it, and the check is that the listing is total. The same shape applies —
   every numeric constant that reaches a record, listed with its provenance, and a check
   that a scan finds no unlisted one. Cost is the initial listing; after that a new number
   fails until it is listed, which is the behaviour the constraint asks for.
2. ~~**C2's leaf clause.**~~ **Done, 2026-11-10.** Two checks rather than the one proposed:
   deep equality plus canonical bytes over both inputs, and — the stronger of the two —
   re-deriving the view and requiring the same `view_id`. The second holds the constraint by
   its consequence, so it fails for a write-back nobody enumerated, which is the shape to
   prefer wherever a constraint has one. Both use `test_admission_view`'s own fixture
   builders: a graph literal written in the ledger's test file would pin that file's idea of
   a projection rather than what the view reads.
3. **C3.** Construct an admission state change with a claim scope, apply a `supersedes`,
   and assert the old value and the old scope are both still readable. The refusals for
   malformed `supersedes` already exist; what is missing is the positive case, which is
   the one the constraint is about.
4. **C4.** One check that admission is absent from a record until dispatch writes it, and
   that no later write can add it. The regime half is held by I20; this is the general case.
5. **C7.** Leave global enforcement alone — it is not writable — and instead require, per
   new quantity, that its "not obtained" branch has a test. That is a convention for
   review, not a check, and this file should say so rather than imply more.

## What this file does not claim

The status column is about whether a **check** exists, not about whether the code is
correct. A constraint marked `promise` may be perfectly respected everywhere today; the
claim is only that nothing would refuse a change that stopped respecting it.

Nor does enforcement reach a host with shell access. ETALON cannot make a Zone-C edit
impossible for a host that can write files; what it can do is make the edit **detectable
and non-propagating**, which is the same move the assessment-regime membrane makes one
level down (`ASSESSMENT_REGIMES.md`). Under the first principle that is sufficient: the
harm is a record claiming more than was established, and a changed judge carrying a changed
digest cannot silently carry anything across.

---

## Appendix: how to tell a real failure from an environment one

Added 2026-11-10, because a suite whose failures nobody can classify cannot serve as the
error-correction instrument a self-improving host needs. The count had been reported for
weeks as "the pre-existing missing-dependency population", which was **wrong**: dependencies
were about a quarter of it. The method below replaced that guess and is cheap enough to rerun.

**Three sets, from two runs and one checkout.**

1. Run the suite on the development platform and on the deployment platform, and take the
   **intersection** of failing node ids. Only the intersection is a candidate defect; a
   failure on one platform alone is that platform's. Measured: 34 of 87 intersected. The
   macOS-only set is dominated by two signatures with physical causes — `/var` is a symlink
   to `private/var`, so every pytest `tmp_path` has a symlink ancestor and
   `research/handoff.py:66` refuses it (19 failures), and there is no `/proc`, which
   `runtime/service.py:166` requires (10). Both are **0** on Linux.
2. Extract `HEAD` into a scratch directory (`git archive HEAD | tar -x -C …`, then copy
   `asset/` in, which `git archive` carries but a sparse checkout may not) and run the
   intersection's files there. What fails at `HEAD` too is **pre-existing**; what passes at
   `HEAD` and fails now was **caused by the current work**. Measured: 23 pre-existing, 5
   caused by this round.
3. Fix the caused-by-us set first. It is the only part that is unambiguously debt.

**Two traps, both hit while establishing this.** The comparison platform must match on
*every* axis that is not the one under test: a Python 3.10 interpreter produced 300
collection errors on its own (`StrEnum` needs 3.11+), and a tarball that excluded `asset/`
produced 278 failures that said nothing about the platform. Both times the broken thing was
the comparison, not the subject. Align the comparison before reading it.

**Result of the first pass.** 96 → 74 failures: 9 cleared by installing `scikit-learn`, 6 by
installing CPU `torch`, 7 by repairing the round's own regression (four example contract
metric literals that predated the `threshold_evidence` requirement). The one remaining
round-caused failure is `test_v_original_sources_complete_…`, and it is a product decision
rather than a defect: this round added five skills under `.claude/skills/` that are **not in
`skills.WORKFLOWS`**, so `skills.catalog()` does not list them and `host.install` cannot
deliver them. Either register them — which enlarges the shipped surface at the moment the
round argued for subtracting from it — or distinguish shipped bundles from
development-only ones in the check. That is the owner's call and is recorded, not taken.
