---
name: moldarwin-method-literature
description: Search the method and protocol literature for a computational choice already made or about to be made, and record what it says as literature evidence that a later revision can cite without it being mistaken for a measurement.
---

# Find what is already known about a method, before measuring it again

Use this capability when a parameter, scoring function, gate threshold, sampling
depth or protocol step is about to be chosen, changed, or defended, and nobody
has checked what has been published about it. Its output is evidence for a
later decision, not the decision.

This is the **method** literature: papers about docking, scoring, sampling,
free-energy protocols, benchmarks and their failure modes. The assay and target
literature has its own capability, `molorigin-assay-literature`, which traces a
compound's activity claims to primary assays. A question about what a molecule
does belongs there; a question about what a procedure is worth belongs here.

## Why this is separate from the target evidence path

MolOrigin's `collect` workflow builds its queries from a pharmacology
vocabulary -- `inhibit*`, `antagonist*`, `agonist*`, `modulat*` -- resolved
against a UniProt accession, and its `bundle` step refuses a snapshot whose
`kind` is not `collect`. A protocol paper has no accession and no activity
claim, so that path cannot carry it and will fail rather than mislead. Query
Europe PMC directly instead, as below.

## What the search can reach

Europe PMC is the only literature source MolOrigin exposes, and it indexes
PubMed. Reach it through MolDarwin's data boundary:

```python
{"kind": "query", "source": "europepmc", "operation": "search",
 "parameters": {"query": "...", "limit": 25}, "max_pages": 3}
```

passed to `moldarwin_data_plan(request, ...)` to validate without network
access, then `moldarwin_data_run(request, workspace, run_id, ...)` to seal the
result into a snapshot. `operation: "article"` takes one `pmid`;
`operation: "fulltext"` takes a `pmcid` and returns JATS passages with their
section titles and locators, which is what lets a later reader find the exact
sentence a number came from.

Limits that change what a search means, and must be reported with it:

- `contains` on `fulltext` is applied **after** the whole article is fetched.
  It is a local substring filter, not a server-side search, so it finds only
  what the retrieved text already contains.
- Supplementary material arrives as links and is **never fetched**. A protocol
  detail that lives only in the SI is out of reach here.
- A PMCID does not guarantee full-text access. A paywalled method paper yields
  its abstract and no more; record that it did.
- There is no Crossref, OpenAlex, Semantic Scholar or preprint-server
  operation. A preprint is reachable only if Europe PMC indexes it. A method
  that exists only as a preprint or a repository README is **not** covered by
  a search here, and a coverage claim must say so.

## Build the query from the decision, not from the topic

A query written from the topic ("docking accuracy") returns a literature. A
query written from the decision returns the few papers that bear on it. State
the decision first, then its terms:

| decision in hand | terms that discriminate |
| --- | --- |
| raise or keep docking exhaustiveness | `exhaustiveness`, `sampling convergence`, `pose reproducibility` |
| adopt a rescoring stage | `rescoring`, `enrichment`, `EF1%`, the named scorer |
| set a score threshold | `enrichment`, `percentile`, `decoy`, `early enrichment` |
| trust a redock RMSD gate | `redocking`, `self-docking`, `symmetry-corrected RMSD`, `PoseBusters` |
| size a docking box | `box size`, `search space`, `binding site volume` |
| choose replica count | `ensemble`, `replica`, `aleatoric uncertainty`, the estimator |

Use Europe PMC's own syntax, quote multi-word terms so they cannot become
operators, and bound the date range when a claim is about current practice:
`(TITLE_ABS:"docking box" OR TITLE_ABS:"search space") AND FIRST_PDATE:[2015-01-01 TO 2026-01-01]`.

Record the query string itself. A result set whose query is unrecorded cannot
be re-run, extended, or shown to have missed something.

## Record the finding as literature, never as a measurement

This is the part that matters and the part that is easy to skip. A number from
a paper and a number from this machine are different kinds of claim, and a
campaign that mixes them cannot later say which of its thresholds it actually
checked.

Write a `moldarwin-research-claim/1` whose `epistemic_status` is
`extracted_report` when the paper reports it, and `interpretation` when the
reading is yours. Give it `subjects`, `conditions` and `limitations`: the
conditions are the ones the paper measured under -- its target class, its
library, its decoy set -- and they are what decides whether the number
transfers to the campaign in hand. A benchmark figure from a kinase panel is
not a figure about a shallow protein-protein interface.

Attach the sealed snapshot path as `evidence` on
`moldarwin_research_progress(entry, ..., evidence=[...])`, so the claim points
at bytes rather than at a recollection.

When the finding then feeds a parameter change, the number enters a `Stage` or
a threshold carrying `Evidence.LITERATURE` and its citation in `source` --
never `measured_here`, which is reserved for what this project ran. A published
value that this project converted or extrapolated is `inferred`, because the
conversion is this project's and can be wrong in a way the citation is not.

A `Knob` records its basis differently and has **no** `Evidence` field: it
carries a free-text `source` for the citation and an `Effect` of `BENCHMARKED`,
`MEASURED_HERE` or `ASSERTED`. Cite in `source` there, and do not go looking
for an evidence field that type does not have.

## What a search here does not establish

A paper is evidence about the conditions it measured. It is not a measurement
of this campaign's target, library or machine, and the reading-across is an
`interpretation` that a later evaluation can contradict. Finding no paper is
not evidence that no work exists: it is evidence about this query, these
sources and this date, and it is reported that way.

Use the result to **propose** a revision with a stated mechanism, then measure
it. `moldarwin-method-configuration` compiles the change,
`moldarwin-gate-calibration` tests a threshold against controls, and the
comparison that decides whether to keep it belongs to
`moldarwin-skill-improvement`.
