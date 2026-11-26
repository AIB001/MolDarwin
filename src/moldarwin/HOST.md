# Research with MolDarwin

The host owns the scientific question, code, proxies, and next action. Work freely with
native Python, SDK calls, and known tools within the user's scope and budget. Skills,
discovery, method registration, and hooks are optional; no complete workflow DAG,
opportunity/patch chain, or routine review phase is required.

## Core Operating Rhythm
- **Optimize for decisive turns:** Passing runs use fewer turns. Focus on the limiting
  uncertainty and batch routine computation in Python rather than issuing serial tool loops.
- **Lazy-load context and skills:** Resume with `moldarwin_research_context(view="summary")`,
  inspect derived state with `moldarwin_admission_view(detail="summary")`, and locate
  built-in or live generated skills via `moldarwin_skill_find` before calling
  `moldarwin_skill_read`. Load deep `references/` only when needed.
- **Recall before rewriting:** Check the entry's resource catalog (`view="resources"`) and
  domain skills first. Call saved executables through `moldarwin_method_resolve` →
  `moldarwin_method_call` → `moldarwin_method_collect` rather than rewriting them.
- **Carry methods, never target-specific cutoffs:** Transfer cascades and code across
  targets, never scalar docking thresholds; calibrate against each target's own controls.
- **Autonomous planning & compute hygiene:** For open-ended goals without a step-by-step
  plan, inspect idle GPUs/engines once via `moldarwin_capabilities(detail="summary", skills=[], tools=[], operations=[], include_environment=True)`
  (or `SessionStart` `[moldarwin-env]`), size runs from a `<=5%` micro-pilot + control gate,
  never use `busy_gpus`, and load `moldarwin-autonomous-planning` on demand.

## Epistemic & Execution Boundaries
- Keep `completion`, `verification`, and `admission` distinct. `diagnostic` runs and
  experience notes are `used`, never `relied_on`; tool success never implies scientific validity.
- Retain original evidence hashes, failures, unknowns, and real costs. Respect project pauses,
  budget limits, and authorization tokens (`GateAuthorization`, `MethodAuthorization`,
  `SpendAuthorization`). Duplicate requests are retries, not independent replicates.
- Package proven reusable code with `moldarwin_method_publish` (stating `conditions`,
  `applicable_when`, and `invalid_when`) or a fine-grained `SKILL.md`. Promote a default only
  after paired `independent_validation` in `moldarwin_revision_compare` showing no warrant or
  quality regression and no hidden waiver inflation; check `shadow_nodes` before hiding old
  records from default views.

Optional references (load individually on demand):
- [Research and evidence](host-guides/research.md)
- [Method modification and attribution](host-guides/method-improvement.md)
- [Engineering and installation](host-guides/engineering.md)
- [Short project entry for a new chat](host-guides/project-entry.md)
- [Research graph, selective memory and lifecycle hooks](host-guides/research-graph.md)
- [Host setup and compatibility details](HOST_SETUP.md)
