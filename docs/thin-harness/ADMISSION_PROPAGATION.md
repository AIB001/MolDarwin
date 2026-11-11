# Admission propagation: a node-level derived view

Status: design v4, 2026-11-10. §10 supersedes parts of §1–§8 per
`ADMISSION_PROPAGATION_DECISIONS.md`, and §11 amends §3, §4 and §7 for the
assessment-regime membrane per `ASSESSMENT_REGIMES.md`; superseded sections are marked in place and kept. Normative source: `RSI_REWARD.md`. Binding conventions:
`CLAUDE.md` (the epistemic-layer upgrade section).

`RSI_REWARD.md` defines a warranted decision as one where every premise it relied on was
admissible. Today admission exists only per measurement (`learn.admissible.rule`), and
the research graph has no node-level admission at all. This document specifies a
read-only view that derives one, states what it must never do, and states which
existing records it cannot compute.

## 0. Measured before designing

All counts below were taken on 2026-11-05 from the working tree at `origin/main`
(no local commits). Evidence class for each is given.

### 0.1 Reward bandwidth: `exactness` × `consequence`

Counted by parsing `FAULTS` in `src/etalon/faults/taxonomy.py` (AST, not import).
Evidence: `measured_here`. Denominator: 20 faults.

|             | wrong_subject | wrong_size | unverifiable | total |
|-------------|--------------:|-----------:|-------------:|------:|
| `EXACT`     | **11**        | 2          | 3            | 16    |
| `THRESHOLD` | 3             | 0          | 1            | 4     |
| `DERIVED`   | 0             | 0          | 0            | 0     |

The same parse reproduces the marginals already on record (consequence 14/2/4, phase
10/10, evidence convention 10 / measured_here 8 / measured_in_an_asset 1 / literature 1,
unbounded 18).

`rule()` (`src/etalon/learn/admissible.py:151`) withholds only on an unwaived
`WRONG_SUBJECT` fault; `WRONG_SIZE` lands in `bounded` and `UNVERIFIABLE` in
`unverifiable`, and neither withholds. So the faults that both block admission and
cannot be moved by a threshold are the 11 `EXACT ∧ WRONG_SUBJECT` entries:

- preflight (7): `F_HANDOFF_ABSENT`, `F_STRUCTURE_UNREADABLE`,
  `F_COORDINATES_ARE_A_DEPICTION`, `F_HYDROGENS_IMPLICIT`, `F_POSE_WITHOUT_RECEPTOR`,
  `F_RECEPTOR_NOT_THE_ONE_SCORED`, `F_PROTONATION_UNDECIDED`
- postflight (4): `F_BUILD_INCOMPLETE`, `F_STAGE_NEVER_RAN`,
  `F_RESULT_PREDATES_THE_SYSTEM`, `F_TOPOLOGY_CHARGE_NOT_INTEGER`

Each of the 11 codes is referenced by at least one module outside `taxonomy.py`
(`faults/preflight.py`, `faults/postflight.py` or `campaign/expensive.py`), i.e. none is
a catalogue entry that nothing emits. That is a reference check, not a firing check.

**Not taken: firing incidence.** How often each of the 11 actually fires on recorded
campaigns needs `CampaignStore.observations.ruling` rows. No campaign store, journal or
published workspace exists on this machine (`/runs/` and `/findings/` are gitignored and
absent; a home-directory search found no ETALON sqlite store). The catalogue count is a
ceiling on the reward's width, not its width.

Bandwidth judgement: 11 of 20 is not the "two or three" case, so the catalogue does not
make the signal sparse by construction. Whether the signal is wide enough *on real
campaigns* depends on incidence, which is not taken.

### 0.2 Decisions this exposes (recorded, not made; decided since, see `ADMISSION_PROPAGATION_DECISIONS.md`)

The reward as stated in `RSI_REWARD.md` ("restricted to faults whose exactness is
`EXACT`") does not coincide with `rule()`'s admission. Three gaps, each a decision for
the project owner:

- **D1 — threshold faults inside admission.** `rule()` also withholds on the 3
  `THRESHOLD ∧ WRONG_SUBJECT` faults (`F_FEP_MAPPING_DEGENERATE`, `F_POSE_LEFT_THE_SITE`,
  `F_POSE_NOT_EQUILIBRATED`). Rewarding `rule()`'s admission directly therefore leaves a
  knob: moving those thresholds moves the reward. Options: (a) the reward reads an
  exact-only facet computed from a stored `Ruling.blocking` filtered by `exactness`
  (no change to `rule()`); (b) reward `rule()`'s admission and accept that the 3
  threshold faults are gameable.
- **D2 — blocking codes outside the catalogue.** `rule()` and `CampaignStore` also
  withhold on 5 codes that are not `Fault`s and carry no `exactness`:
  `NONFINITE_CHEAP_VALUE`, `NONFINITE_EXPENSIVE_VALUE`, `NO_EXPENSIVE_VALUE`,
  `NO_CHEAP_VALUE` (`admissible.py`), `PROTOCOL_EVIDENCE_MISMATCH`
  (`active/store.py:_protocol_ruling`). They are exact comparisons in character, but the
  catalogue digest does not cover them, so a change to them is invisible to the
  comparison guard. Include them in the reward, exclude them, or catalogue them.
- **D3 — waivers are a knob.** `ADMITTED_UNDER_WAIVER` turns a fired `WRONG_SUBJECT`
  into an admission. A revision loop that can add waivers can raise warrant without
  changing any observable. Count under-waiver premises as warranted or not.

This view does not resolve D1–D3. It propagates `rule()`'s admission faithfully and
carries, per leaf, the blocking codes split by exactness and by catalogue membership,
so any of the options can be computed later without re-running `rule()`.

### 0.3 Can existing edges distinguish `relied_on` from `used`?

The graph vocabulary (`graph_memory.EDGES`) has no `relied_on` or `used`. Every
emitted edge comes from one of a fixed set of emission sites in
`research/graph_memory.py::_build_research_graph` (mirrored one-for-one in
`research/graph_scope.py`). Counted over **emission sites**, not edges:

Denominator: 37 sites = 28 `method_links` call sites (27 distinct labels;
`evaluated_use` is emitted from two operations) + 6 generic field sites
(`input_refs`, `output_refs`, `support_refs`, `supersedes`, `detail.hypothesis_refs`,
decision `basis_refs`) + 1 counter-relation site + 2 workflow-template sites.
`skipped_because` is in `EDGES` and has 0 emission sites.

| class | sites | which |
|---|---:|---|
| automatically decidable | **28** | 3 → `relied_on`; 25 → `used` (table in §3; the relation-less duplicate decision `basis_refs` site is `used` by `field_convention`. An earlier draft said 4/24, which contradicted §3) |
| needs a human label | **2** | `support_refs` (`supports`); step evaluation `evaluated_node` |
| record cannot settle | **1** | method-use `visible_at_selection` |
| not a premise/input edge | 6 | `derived_from`, `selection_output`, `supersedes`, `tests`, `refutes`, `flow` |

Evidence class of the classification: `convention` — it is this document's reading of
field names and module docstrings, not a measurement. The counts of sites are
`measured_here`.

**Not taken: the same three numbers over edges.** That is the quantity the brief asks
for ("the real price"), and it needs real journals; none are present (see 0.1). The site
count bounds the *kinds* of work, not its amount. It is already enough to say where the
price sits: `support_refs` is the generic premise field of claims, research decisions,
candidate briefs and opportunity states, so the human-label class is probably dominated
by it in edge count — "probably" because that count was not taken.

Two further facts make "automatically decidable" weaker than it sounds:

- **`kind` is inferred.** Every non-trace node carries
  `kind_basis = "legacy_record_semantics_inferred"`. The view therefore does not key
  propagation on `kind`; it propagates to any node with outgoing `relied_on` edges.
- **The edge kind alone does not decide.** `depends_on` is emitted both for premises
  (`measured_result`, `evaluation_result`, `selection_basis`) and for inputs
  (`input_refs`, workflow data links, most `method_links`). The view must classify on
  `(kind, relation)`. Relation-less `depends_on` comes from `input_refs`, workflow data
  links and the duplicate decision `basis_refs` edge. For `etalon-research-step/1`
  decision records the last is emitted alongside a `selection_basis`-labelled edge
  between the same pair (both read `detail.basis_refs`), so classifying relation-less
  `depends_on` as `used` loses nothing for those records provided classification is
  resolved per `(from, to)` pair with `relied_on` winning. Whether any other schema
  carries `operation: "decision"` with `detail.basis_refs` was not checked exhaustively.

### 0.4 There is no recorded join from a graph node to a `Ruling`

`Ruling`s are written at dispatch into `CampaignStore.observations.ruling`
(`active/store.py:resolve`, `_import_evaluation`). The research graph reads sources of
kind `journal`, `data_snapshot` and `artifact_manifest`; `CampaignStore` is not among
them, and no research record schema carries a reference to an observation row or a
ruling digest. `research_trace` has an `admission` phase, but its states
(`accepted` / `rejected` / `partial` / `awaiting`, `origin` may be `declared`) are a
different vocabulary from `Admission` and are not produced by `rule()`; mapping one onto
the other would conflate two terms the conventions keep fixed.

Consequence, stated once because it governs §5: **for every existing record, the
node-level admission is not computable.** Writing the join now would be a backfill,
which `CLAUDE.md` constraint 4 forbids. The view is therefore specified over an explicit
binding input, and becomes populated only when a binding is written at dispatch — an
emission-point change that is out of scope for this round.

## 1. What the view is (truncated-graph refusal superseded by §10.4; output schema version superseded by §11)

A pure function

```
admission_view(graph, bindings, *, labels=None) -> dict
compare_views(a, b) -> dict           # raises on mismatch
catalogue_digest() -> str
```

in a new module `src/etalon/learn/admission_view.py`.

- `graph`: a research graph dict as returned by `build_research_graph` (schema
  `etalon-research-graph/1`). Validated with `validate_research_graph` before use. A
  graph with `truncated: true` is **refused**: missing premises would make a derived
  admission look better than it is.
- `bindings`: list of leaf admission bindings (§2).
- `labels`: optional human labels for edges in the human-label class (§3).

Output schema `etalon-admission-view/1`, carrying `view_version`
(`"etalon-admission-view/1"`), `catalogue_digest`, `graph_view_id` (the graph's
`view_id`), and per-node and per-edge results. The output carries its own `view_id`
(`"admission-view-" + digest(rest)`), following the graph's convention.

## 2. Leaf bindings (extended by §10.1)

A binding attaches one `Ruling` to one graph node:

```
{
  "node_id":        <graph node_id>,
  "ruling":         <Ruling.as_dict() output, verbatim>,
  "ruling_digest":  digest(ruling),          # checked; mismatch is refused
  "dispatch_ref":   {"store": "campaign", "action_id": <str>},
  "claim_scope":    <object: what the ruling is about, e.g. parent_id/endpoint/units>,
  "supersedes":     [<ruling_digest of an earlier binding for the same node>]   # 0 or 1
}
```

- The view never calls `rule()`. It reads `ruling["admission"]` as written.
- `binding_provenance` in the output is `"caller_declared"`: the view cannot verify that
  the binding was written at dispatch, and says so instead of implying it.
- A `node_id` absent from the graph is refused.
- Two bindings for one node must form a single `supersedes` chain. A fork (two heads),
  a dangling `supersedes` digest, or a cycle is refused.

Per leaf the output also carries, descriptively, `ruling["blocking"]` split into
`exact_blocking`, `threshold_blocking`, `derived_blocking` (catalogue codes by
`exactness`) and `uncatalogued_blocking` (codes not in `BY_CODE`). No admission is
computed from these splits; they exist so D1/D2 can be evaluated later.

## 3. Edge classification (`supports`/`evaluated_node` default and label keys superseded by §10.3)

Each graph edge is classified into `premise_class` ∈ {`relied_on`, `used`,
`not_premise`} with a `class_basis`.

Direction convention in the view: a `relied_on` edge is stored as
`owner → premise`. Graph edges for `supports` are emitted `premise → owner` and are
reversed when classified. All other classified graph edges are already `owner → target`.

| graph edge | relation | premise_class | class_basis |
|---|---|---|---|
| `depends_on` | `measured_result`, `evaluation_result`, `selection_basis` | `relied_on` | `declared_relation` |
| `depends_on` | `declared_selected_workset`, `declared_selection_checkpoint`, `declared_resource_method`, `declared_attributed_use`, `declared_associated_node`, `declared_associated_evaluation`, `declared_subsequent_selection`, `selected_method`, `prior_use`, `selection_method`, `evaluated_candidate`, `evaluated_baseline`, `evaluation_cost`, `evaluation_conditions`, `applied_use`, `execution_receipt`, `workflow_instance`, `evaluated_use`, `planned_candidate`, `planned_baseline`, `evaluation_plan` | `used` | `declared_relation` |
| `depends_on` | absent (`input_refs`, workflow data link, duplicate `basis_refs`) | `used` | `field_convention` |
| `depends_on` | `visible_at_selection` | `used` | `record_cannot_settle` |
| `depends_on` | `evaluated_node` | `relied_on` unless labelled | `unlabelled_default` / `human_label` |
| `supports` | — | `relied_on` unless labelled | `unlabelled_default` / `human_label` |
| `derived_from`, `supersedes`, `tests`, `refutes`, `flow`, and `depends_on` with `selection_output` | — | `not_premise` | `structural` |
| any other `(kind, relation)` | — | **refused** | — |

Rules:

- Unknown `(kind, relation)` is refused, not defaulted, for the same reason `rule()`
  refuses an unknown fault code: the caller and the view would disagree about what an
  edge means.
- The two human-label sites default to `relied_on`. That default is a **convention**,
  chosen in the conservative direction of `admissible.py`'s asymmetry: treating a
  corroborating support as a premise can only lower a derived admission, never raise
  it. `etalon-step-corpus` already collects premises "along `relied_on` and `support`",
  which this default matches. Every node whose value depended on an unlabelled default
  carries `premise_basis: "includes_convention"`.
  **Refuted in review (2026-11-05):** the "can only lower" claim is false under §4's
  no-vacuous-admission rule. A node whose only edge is an admitted `supports` gets
  `admitted` under the default and `not_recorded` if the edge is labelled `used`, so the
  default *raises* exactly the sole-corroboration case. Whether to keep the default is
  open; it is not changed here.
- `labels` maps `"<from>|<to>"` (graph node ids, graph direction) to `relied_on` or
  `used`. A label may only target an edge in the human-label class; labelling any other
  edge is refused. Labels are view input; they are never written anywhere.
- `visible_at_selection` is `used`: the record states visibility, and
  `method_links` forbids inferring actual use. Propagating it would infer reliance.
- Classification is resolved per `(owner, premise)` pair: if any edge between them is
  `relied_on`, the pair is `relied_on`.

## 4. Propagation rule

Order on `Admission`, worst first:

```
withheld  <  not_recorded  <  admitted_under_waiver  <  admitted
```

`not_recorded` is new and exists only in the view: nothing bound and nothing to derive
from. It sits below `admitted_under_waiver` because an unknown premise may be a withheld
one.

For each node `n`:

```
leaf(n)     = head-of-chain binding's ruling["admission"]   if n has a binding
premises(n) = { p : (n, p) is relied_on }
derived(n)  = min( [leaf(n)] if bound else [],
                   [derived(p) for p in premises(n)] )
            = not_recorded   if both lists are empty
```

- **No vacuous admission.** A node with no binding and no `relied_on` premise is
  `not_recorded`, never `admitted`. A claim that relies on nothing recorded is not
  warranted.
- **Cycles.** Nodes in a strongly connected component of the `relied_on` subgraph with
  more than one node, or with a self-loop, get `min(…, not_recorded)` and reason
  `circular_reliance`: circular reliance cannot ground a premise.
- **Attribution.** Each derived node names `limited_by` (the direct premises attaining
  the minimum, sorted) and `limiting_leaves` (the bound or `not_recorded` nodes at the
  bottom of those chains, sorted). If the node's own leaf attains the minimum it appears
  in `limiting_leaves`.
- `used` and `not_premise` edges have no effect on any derived value.
- Refutation is not admission. `refutes` edges are `not_premise` here; whether a refuted
  premise should lower warrant is a separate decision, not made in this view.

Per node output: `node_id`, `kind` (copied, with `kind_basis`), `admission` (derived),
`leaf` (the bound value or `null`), `limited_by`, `limiting_leaves`, `premise_basis`,
`reasons`, `claim_scope` (copied from the graph node when present), and `history`
(§5, bound nodes only).

## 5. State change and history

A premise's admission changes only through a new binding whose `supersedes` names the
earlier binding's `ruling_digest`. The view:

- uses the chain head for `leaf(n)`;
- emits `history`: every earlier binding in chain order, each with `admission`,
  `ruling_digest`, `claim_scope` and `superseded_by` (the next digest). Nothing in the
  chain is dropped. This follows `supersedes` as `RESEARCH_GRAPH.md` defines it:
  "preserves the earlier record and claim scope; it does not erase it";
- marks every derived node whose `limiting_leaves` or premises include a node with
  non-empty history with `rests_on_superseded_premise: true`.

The previous derived value of a J node is the value in the earlier view object, which
is immutable and identified by its `view_id`. The view does not recompute past states.

## 6. Comparison (superseded by §10.6)

`compare_views(a, b)`:

- raises `AdmissionViewMismatch` if `view_version` differs, or if `catalogue_digest`
  differs. It never returns a partial or "best-effort" comparison in that case;
- otherwise returns, per node present in both, the pair of admissions and whether it
  moved, plus the node ids present in only one side.

`catalogue_digest()` is `digest(...)` (from `etalon.active.schema`) over the list, in
`FAULTS` order, of each fault's semantic fields: `code`, `phase`, `exactness`,
`consequence`, `lower_kcal_mol`, `upper_kcal_mol`, `evidence`. Prose fields (`summary`,
`observable`, `source`, `remedy`) are excluded so a wording fix does not refuse a
comparison; adding, retiring or re-classifying a fault changes the digest.

## 7. Invariants (amended by §10.8)

Each must be held by a test.

- **I1 — `rule()` unchanged.** For a fixed set of `Measurement`s covering every
  consequence, a waived fault, an unchecked observation, non-finite values and missing
  cheap/expensive values, `canonical(rule(m, …).as_dict())` is byte-identical to a value
  pinned from the code before this change. `learn/admissible.py` is not edited.
- **I2 — no write-back.** `admission_view` does not mutate `graph`, `bindings` or
  `labels` (deep-equal before and after), writes no file and opens no store.
- **I3 — history retained.** After a superseding binding, the earlier admission,
  ruling digest and claim scope are present in `history`, and the derived nodes above it
  are marked `rests_on_superseded_premise`.
- **I4 — versioned comparison.** The view carries `view_version` and
  `catalogue_digest`; `compare_views` refuses a mismatch on either.
- **I5 — weakest premise bounds.** No node's derived admission is better than any of its
  `relied_on` premises' derived admissions, or than its own leaf.
- **I6 — no vacuous admission.** A node with neither binding nor `relied_on` premise is
  `not_recorded`.
- **I7 — `used` does not propagate.** Changing the admission of a node reached only by
  `used` or `not_premise` edges does not change the derived value of its owner.
- **I8 — refusals.** Truncated graph, unknown `(kind, relation)`, label on a
  non-labelable edge, binding digest mismatch, binding for an unknown node, forked or
  dangling `supersedes` chain: each raises.

## 8. What existing records cannot compute

- **Every existing node's admission.** No record joins a graph node to a `Ruling`
  (§0.4). Over existing records the view returns `not_recorded` for every node. This is
  the expected output, not a defect.
- **Instance-level edge classification counts** — not taken; no journals present.
- **Nodes whose `kind` matters to a reader.** `kind` is inferred for all non-trace
  records; the view copies it with its basis and does not rely on it.
- **Paged graphs.** A page of a scoped graph is truncated by construction and is
  refused. Propagation needs the whole reliance closure of the nodes it reports.

## 9. Not in this change

- No change to `rule()`, `Ruling`, `Measurement`, `CampaignStore`, `ResearchJournal`,
  `RuntimeStore` or any record schema. No store merge.
- No emission-point change: nothing starts writing bindings at dispatch. That is the
  change that would make the view non-empty on real data, and it needs its own design.
- No exact-only admission facet, no waiver policy, no reward figure: D1–D3 are open.
- Nothing under `asset/`.

## 10. v2: decisions of 2026-11-05

Source: `ADMISSION_PROPAGATION_DECISIONS.md` (decisions D1–D8, U1–U3, and the
implementation notes in its second part). Where this section and §1–§8 disagree, this
section wins. `view_version` becomes `"etalon-admission-view/2"`.

### 10.1 Bindings (extends §2; D7)

Required binding keys: `node_id`, `ruling`, `ruling_digest`, `dispatch_ref`,
`claim_scope`, `store_status`, `store_admitted`; optional `supersedes`. Unknown keys are
refused. Refuse a binding when any of these holds:

- `ruling` does not have exactly the keys of `Ruling.as_dict()` (`parent_id`,
  `admission`, `teaches`, `reproducible`, `blocking`, `waived`, `bounded`,
  `unverifiable`, `unchecked`, `notes`).
- `ruling` is internally inconsistent:
  - `admission == "withheld"` must hold ⇔ `blocking` is non-empty;
  - `admission == "admitted_under_waiver"` must hold ⇔ `blocking` is empty and `waived`
    is non-empty;
  - `teaches` must equal `admission != "withheld"`;
  - `reproducible` must equal `unverifiable == []`.

  This re-checks the final step of `rule()` from its own lists; it does not call `rule()`.
- `ruling_digest != digest(ruling)`.
- `store_status` is not one of `ok`, `failed`, `invalid`, `blocked`, or `store_admitted`
  is not a bool.
- `store_admitted != (store_status == "ok" and ruling["teaches"])`, which disagrees with
  the store's own formula (`active/store.py:564`, `648`).
- `ruling["teaches"] != store_admitted`, i.e. two "admitted" answers that disagree.
  Neither side is silently preferred.
- `dispatch_ref` is not exactly `{"store": "campaign", "action_id": <non-empty str>}`.
- `claim_scope` is not an object, or `claim_scope.get("parent_id") != ruling["parent_id"]`.
- the same `ruling_digest` is bound to more than one node;
- within one node's chain, a binding's `claim_scope["parent_id"]` differs from its
  predecessor's;
- `supersedes` has more than one entry, or the chain forks, dangles or cycles (as v1).

### 10.2 Exact facet (D1)

Each node carries two derived values: `admission` (v1 semantics: `rule()`'s admission,
propagated) and `exact_admission`. The exact leaf of a bound node is the worst of:

| condition on the head binding | exact leaf |
|---|---|
| `store_status != "ok"` | `withheld` |
| any code in `blocking` is a catalogue fault with `EXACT` ∧ `WRONG_SUBJECT` | `withheld` |
| any code in `blocking` is not in `BY_CODE` | `not_recorded` |
| any code in `unchecked` is `EXACT` ∧ `WRONG_SUBJECT` | `not_recorded` |
| any code in `waived` is `EXACT` ∧ `WRONG_SUBJECT` | `admitted_under_waiver` |
| otherwise | `admitted` |

Catalogue codes with `THRESHOLD` or `DERIVED` exactness are ignored in every list.
`exact_admission` propagates by exactly the §4 rule over the same `relied_on` edges, with
the same caps (§4 vacuity and cycles, §10.4 completeness). Each node also carries
`exact_limited_by` and `exact_limiting_leaves`, defined as in §4.

Per-leaf output gains `exact_reasons`: the codes that set the exact leaf, sorted.

This module computes no reward figure, rate or tally (decisions file, part 2: the unit of
"a decision" is undefined, and no reward number is reported before the dispatch link
exists).

### 10.3 Classification changes (D5; review 2.10, interpretation 2)

- `supports` and `depends_on` with relation `evaluated_node` default to `used`, with
  `class_basis: "unlabelled_default"`. A label may set either to `relied_on`
  (`class_basis: "human_label"`) or `used` (`human_label`).
- Label keys are `"<from>|<to>|<kind>"` (graph node ids and graph direction, graph edge
  kind). A key matching no human-label-class edge is refused. A value other than
  `relied_on` or `used` is refused.
- The kinds `supports`, `derived_from`, `supersedes`, `tests`, `refutes` and `flow` with a
  non-null `relation` are refused, following §3's "any other (kind, relation) → refused".
- `premise_basis` is removed. Each node carries `unlabelled_candidate_premises`: the sorted
  premise-side node ids of its human-label-class edges that are still at the default.

### 10.4 Completeness (D6; supersedes the truncated refusal in §1 and §8)

`graph_completeness.asserted` is `true` only when all of these hold:
- `graph["truncated"] is False` and `graph["issues"] == []`;
- `graph["scope_receipt"]` exists, with:
  - `schema == "etalon-research-graph-scope/1"`;
  - `traversal_complete is True` and `reference_coverage_complete is True`;
  - `deliberate_boundary_refs == []` and `boundary_relations == []`;
  - `issues == []`.

Otherwise `asserted` is `false`, and `graph_completeness.missing` lists the failed
conditions by name. When `asserted` is false, every node's `admission` and
`exact_admission` are capped at `not_recorded` (`min(value, not_recorded)`) with the
reason `graph_completeness_not_asserted`. Leaf values are still reported. A truncated
graph is no longer refused. Consequence (intended): an unscoped graph from
`build_research_graph` never asserts completeness, because that builder emits no positive
completeness field.

### 10.5 Catalogue coverage (D2, interim)

The module defines
`UNCATALOGUED_BLOCKING_CODES = ("NONFINITE_CHEAP_VALUE", "NONFINITE_EXPENSIVE_VALUE",
"NO_EXPENSIVE_VALUE", "NO_CHEAP_VALUE", "PROTOCOL_EVIDENCE_MISMATCH")`. The view's
top-level output carries `catalogue_coverage: {"blocking_surface_complete": false,
"uncatalogued_blocking_codes": [...those five, sorted...]}`. The `catalogue_digest()`
docstring states that the digest does not cover these five codes. Cataloguing them is
blocked; see the decisions file, part 2 (it conflicts with constraint 1).

### 10.6 Comparison (D8; supersedes §6's compare rules; the digest rule is unchanged)

`compare_views(a, b)` raises `AdmissionViewMismatch` when any of these holds:
- `view_version` differs;
- `catalogue_digest` differs;
- `catalogue_coverage` differs;
- `graph_view_id` is missing or `None` on either side, or differs;
- either side's `view_id` is not `"admission-view-" + digest(rest)`, i.e. the view was
  edited after it was computed.

Otherwise it returns, per node present on both sides and for each facet (`admission`,
`exact_admission`), `{"a", "b", "moved", "direction"}`. `direction` ∈ `raised`, `lowered`,
`unchanged`, by the §4 order. It also returns `only_in_a` and `only_in_b`. A comparison
is therefore across bindings on one graph. Comparing revisions that produce different
graphs is the job of the reward tally (not built), and is not a node diff.

### 10.7 History mark (review 1.4 quirk; interpretation 8)

`rests_on_superseded_premise` is true when any node in the node's transitive `relied_on`
closure has non-empty `history`, or when the node itself does. This holds whether or not
that node attains the minimum.

### 10.8 Invariants, amended

- I8: the truncated-graph refusal is replaced by I9.
- **I9 — completeness.** When completeness is not asserted, no node's `admission` or
  `exact_admission` is above `not_recorded`.
- **I10 — exact facet ignores thresholds.** A ruling withheld only by `THRESHOLD` codes
  has exact leaf `admitted` (given `store_status == "ok"`). A ruling with an
  `EXACT ∧ WRONG_SUBJECT` code in `unchecked` has exact leaf `not_recorded`.
- **I11 — store consistency.** Every refusal in §10.1 raises.
- **I12 — declared coverage.** Every blocking code `rule()` emits for the I1 fixtures
  (both `require_comparator` settings) is in `BY_CODE` ∪ `UNCATALOGUED_BLOCKING_CODES`.
- Recorded as accepted from round 1:
  - refusals raise `ValueError` (`EvidenceError` subclasses it);
  - a cycle's `limiting_leaves` is its members plus external limiting leaves;
  - a vacuous `not_recorded` node lists itself;
  - per-edge output fields are `owner`, `premise`, `premise_class`, `class_basis`;
  - the extra binding validations of round 1 are kept.

## 11. v3: the assessment-regime membrane

`view_version` becomes `"etalon-admission-view/3"`. The basis strings below are new
`class_basis` values and the output's `view_id` is a digest of its own content, so the
version must move or stored digests collide across two different classifications.

Design record: `ASSESSMENT_REGIMES.md`, which is normative on the semantics; the code
owns the identifiers. Where this section and that one disagree, that one is the design
and this one is the amendment to §3/§4/§7.

### 11.1 Classification (amends §3 and §10.3)

`_classify` takes a third input, the regime of the **premise** record
(`research/assessment_regime.regime_of_node`). After the §3/§10.3 table and after the
human label have had their say, one rule applies: a `relied_on`-class edge whose premise
record does not permit reliance becomes `used`. The degrading basis is the premise's own
`degrade_basis`, and there are two:

- `regime_cannot_settle` — the premise declared `diagnostic`. It skipped the
  predeclaration checks §11.3 lists, so it was never held to a standard that could carry
  a premise.
- `regime_not_declared` — the premise is a method-evaluation record carrying no regime,
  `None`, or a string outside the enum. Treated as `diagnostic` is treated, and kept
  separable in the output from a declared `diagnostic` (I18).

Exactly one cell of the regime table permits reliance: `independent_validation` ∧
`explicitly_declared`. A `diagnostic` role is answered before its basis is consulted,
because a deliberately chosen diagnostic and one entered by omission are the same regime.

A human label cannot pierce the membrane. A label records that a person read an edge as
reliance; the membrane records that the far end was never held to a standard that could
carry it. The second is a fact about the record and outranks a reading of the edge.

### 11.2 Order (amends §4)

The membrane applies **after** the per-pair resolution in which `relied_on` wins. Applied
before, a second `relied_on` edge between the same owner and the same premise silently
restores what the membrane removed — the optional-guard shape ADR 0006 names. I17.

### 11.3 Scope: `not_applicable` is not `unknown`

Only `etalon-method-evaluation/1` records carry an assessment role, projected into
`node["evaluation"]` by `research/graph_memory._project_node`. `regime_of_node` returns
`None` for every other node — an artifact, a receipt, a step — and those edges are
untouched, reported as `NOT_APPLICABLE`.

This is a scope decision, not an omission. Demoting every premise that lacks a regime
would cap every derived value in the repository at `not_recorded`, distinguish nothing
from §10.4's completeness cap, and assert a category error: `assessment_role` is a
property of an assessment, not of every record. The broader reading is one line in
`regime_of_node` and it collapses every real graph.

The checks a `diagnostic` record skips are the ones `research/journal.py` applies after
its role test: results and accounting references must exist; inputs must be recorded
before the frozen policy and evidence after it; and content-addressed bytes already seen
cannot be relabelled as independent validation.

### 11.4 The membrane is not a one-way lowering (amends §4)

Where a refused premise was itself `withheld`, the owner moves **up** to `not_recorded`,
because §4 ranks `not_recorded` above `withheld`. The view cannot honestly keep
`withheld`: that would assert a withholding on the strength of a premise it has just
declined to rely on. Under D4 both values are losses, so no reward is available from the
direction of the move. This refutes the tempting invariant "the membrane never raises a
derived value"; what holds is that it never raises one **above** `not_recorded`.

### 11.5 Output

- per node: `assessment_regime` (the declared regime, else `NOT_APPLICABLE`) and
  `regime_refused_premises` (the premises this node was refused);
- per edge: `premise_regime`;
- per node reason: `premise_regime_cannot_carry_reliance`;
- top level: a `membrane` block carrying `basis`, `relied_class_edges`, `degraded_edges`
  and `by_class_basis`. Two counts and their split, never a rate: a falling admission
  rate is consistent both with the intended mechanism and with a bug that drops edges.

### 11.6 Invariants (amends §7 and §10.8)

- **I16 — scope.** A graph with no `etalon-method-evaluation/1` node produces a view
  byte-identical to the pre-change one modulo `view_version`. No other node schema is
  demoted by regime.
- **I17 — pair resolution order.** Two `relied_on` edges between the same owner and the
  same `diagnostic` premise resolve to `used` with basis `regime_cannot_settle`.
- **I18 — unknown is weak and separable.** A method-evaluation node whose projected
  `assessment_role` is `None` or outside the enum demotes as `diagnostic` does, is never
  refused outright, and is distinguishable in the output from a declared `diagnostic`.
  The third trigger an earlier draft of this clause named — the key being **absent** — is
  unreachable, not unimplemented: `MethodEvaluation.assessment_role` is a required field
  with no default, so a parsed record always carries one and a block without the key is
  not a real projection. `regime_of_node` therefore reads a key-less block as
  `not_applicable`, which keeps §11.3's distinction rather than collapsing it. What makes
  that safe is the field requirement, so the requirement is what a test holds
  (`test_i18_absent_is_unreachable_because_the_field_is_required`); if the field ever
  acquires a default, that test fails and the missing-key branch must move to
  `REGIME_UNKNOWN`.
- **I19 — read-only.** The input graph is unchanged by taking the view, and
  `learn/admissible.py` is untouched: `rule(Measurement) -> Ruling` keeps its semantics
  (hard constraints 1 and 2).
- **I20 — reliance is declined, never revoked.** A record written before the regime
  argument existed is read as regime-unknown and refused reliance. Nothing is written to
  it and no admission is backfilled (hard constraint 4).

---

## 12. v4: a lesson is not an assessment

`view_version` becomes `"etalon-admission-view/4"`. One new `class_basis`, so the version
must move or stored digests collide across two different classifications; views are rebuilt,
not migrated (§11.3).

Design record: `ASSESSMENT_REGIMES.md` §7, which is normative on the semantics.

### 12.1 What changed (amends §11.1 and §11.2)

`regime_of_node` now answers for a second node shape. A projected node carrying an
`experience` block — written by `graph_memory._project_node` for exactly
`etalon-method-experience/1` — returns a regime of `not_an_assessment` with
`permits_reliance = False` and `degrade_basis = "lesson_cannot_settle"`. The membrane rule
of §11.1 is unchanged; it simply now has a premise regime to read where it previously had
`None`.

**Why `not_an_assessment` is a new value and not `NOT_APPLICABLE`.** The two differ in the
one way that matters: whether the membrane acts. `not_applicable` means this node is none of
the membrane's business — an artifact, a receipt — and every derived value is left alone.
`not_an_assessment` means the node is a record type that cannot settle a premise at all, so
a declared reliance on it degrades. Before this version the two were one state and a lesson
got the first.

### 12.2 The two routes this closes, and why one of them contradicted §11

`etalon-method-experience/1` is a full `CONTENT_SCHEMAS` member (`evidence_refs.py:23`), so
an experience ref is legal wherever a ref is legal. Two edges reached `relied_on`:

1. a decision **step** whose `detail["basis_refs"]` is emitted with relation
   `selection_basis` (`method_links.py:79`), which `_declared_class` returns as
   `("relied_on", "declared_relation")` because `selection_basis` is in
   `_RELIED_BY_RELATION`;
2. a `supports`-kind edge, which `_declared_class` returns as
   `("used", "unlabelled_default", labelable=True)` — so a human label promotes it.

`_classify` applies the label **before** consulting the regime, so one branch closes both.
That ordering is also why the second route mattered: §11's own prose claimed *"a label says
a person read the edge as reliance; the membrane says the record on the far end was never
held to a standard that could carry it, and no label can make it have been."* **That claim
was false for a lesson**, because a lesson was outside the membrane's scope. The claim is
now true.

(The decision **record** route was already safe and is unchanged: `graph_memory.py` emits a
research decision's `basis_refs` as kind `depends_on` with no relation, which
`_declared_class` returns as `("used", "field_convention")`.)

### 12.3 Why now, and the honest statement of what was at risk

Harmless until now **by absence, not by declaration**: a lesson carries no `Ruling`, so no
binding, so propagation's floor capped any conclusion relying on it at `not_recorded`.
Protection by absence is the shape this project refuses — the same shape as a count that
"could be taken" and was not (§11's `defaulted_deprecated` census, added in the same round).

The subject that made it worth fixing rather than recording: an RSI loop driven by a **loose
internal benchmark, including an LLM judge**, writes verdicts that are consolidated into
lessons. The lesson route is how those verdicts would have become premises. A loose judge is
a legitimate instrument and belongs in the `diagnostic` lane; what it must not do is settle
anything, and until v4 one path let it.

**Incidence: not obtained.** No journal was opened for this. The reachable emission sites
are the two named above (`measured_here`, by reading `method_links.py` and
`admission_view._declared_class`); how many real edges carry them is not counted here, and
hard constraint 7 forbids an estimate in its place.

- **I21 — a lesson cannot be a premise.** A `relied_on`-class edge whose premise node
  carries an `experience` block is reported `used` with `class_basis`
  `"lesson_cannot_settle"`, **and a human label on that edge does not restore `relied_on`**.
  The second clause is the one that was false before v4.
- **I22 — a lesson is outside the assessment-role census.** `records_by_role_basis` counts
  records carrying an assessment role; a lesson carries none, and counting its absent
  `role_basis` as `not_recorded` would pad the one figure that census exists to keep honest.
