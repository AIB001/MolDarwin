# Reuse the six MolOrigin methods

The maintained content source is `asset/molorigin/skills/`; do not copy or rewrite
its scientific workflows merely to call them through MolDarwin. All six are methods
that may be read independently, partially used, combined or skipped.

| Existing skill | Relevant question |
| --- | --- |
| `molorigin-analogue-search` | Structure/analogue and identity-based follow-up searches |
| `molorigin-assay-literature` | Assay/publication context, endpoints and evidence interpretation |
| `molorigin-compound-sourcing` | Vendor/catalog evidence and bounded sourcing, not proven stock or synthesis |
| `molorigin-selectivity-evidence` | Target/selectivity context and counter-evidence |
| `molorigin-structure-templates` | Experimental structure, construct and ligand/template provenance |
| `molorigin-target-modulators` | Target-to-compound collection and reviewed dossier delivery |

MolDarwin preserves the legacy resource index `moldarwin://skills/molorigin` and item
URIs `moldarwin://skills/molorigin/<name-without-molorigin-prefix>` (for example
`moldarwin://skills/molorigin/assay-literature`); full bundles include the original
references and agent metadata. Those URIs remain valid alongside main-library
discovery/export. Check the returned bundle version when recording use; the
entrypoint alone does not identify changed references.

Original MolOrigin text names its own CLI/SDK/MCP tools. In a MolDarwin-only MCP
session, map `list_sources/describe_source` to `moldarwin_data_sources`, acquisition
to `moldarwin_data_plan/run`, and snapshot verification to `moldarwin_data_status`.
For `collect_target_evidence`, use a `kind="collect"` request; for bundle building,
use `kind="bundle"` with a collected snapshot and curation path. A source-specific
operation that is not exposed through MolDarwin can use the installed MolOrigin SDK
under the same task's permissions; do not pretend its tool exists in MolDarwin.

Source coverage and a successful export are not scientific validation. Keep raw
evidence, retrieval failures, curation assertions, review limits, identity changes
and overlapping experiments. Download/collection/purchasing/model submission in
an optional method is not automatic authorization to perform those actions.
For MolDarwin candidate or assay admission, use the separate actual SDK/tool contracts
in [data operations](data-operations.md); collected rows are not automatically
training labels. No live collection is needed to discover/read/export these skills.
