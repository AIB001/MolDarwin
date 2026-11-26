# MolDarwin Host Guidance

You own the science: choose hypotheses, representations, proxies, code, and tools freely.
Explore in native Python/SDK or `diagnostic` runs with zero paperwork—skip workflow DAGs,
opportunity/patch forms, and routine audits. Passing runs take fewer turns; spend each turn
on an intervention that can change the next decision.

## Token & Turn Efficiency
- **Lazy-load skills in 3 tiers:** Never dump the full catalog. Call `moldarwin_skill_find`
  (query, domain, tags, or `list_domains=True`) to inspect top-K `applicable_when` /
  `invalid_when` cards, then `moldarwin_skill_read` only for the 1–2 matches (`references/`
  only if needed).
- **Prefer compact views:** Start with `moldarwin_research_context(view="summary")`,
  `moldarwin_admission_view(detail="summary")`, and `moldarwin_revision_compare(detail="summary")`.
  Batch routine analysis in one Python script rather than serial tool calls; trust receipts.

## Before Iterating
- **Read the rule first:** If an evaluation contract exists, call `moldarwin_method_criterion`
  to read exact operators, penalties, and threshold provenance (`measured_here`/`literature`/`convention`).
- **Recall before rewriting:** Check `moldarwin_research_context(view="resources")` and
  `moldarwin_skill_find` for pinned callables and prior negative/scoped limits.
- **Carry code, never target thresholds:** Transfer cascades and scripts across targets,
  never docking cutoffs. Calibrate on the new target's own controls before authorizing spend.

## Hard Boundaries & Compounding RSI
- Separate `completion` (ran), `verification` (checks passed), and `admission` (warranted
  premise). `diagnostic` runs and experience notes are `used`, never `relied_on`.
- Never claim improvement from an unvalidated proxy, dropped failed tasks, or inflated
  waivers (`admitted_under_waiver` is cost, not a win). Respect pauses and spend tokens.
- **Capture & promote:** Package proven code via `moldarwin_method_publish` (with explicit
  `applicable_when` + `invalid_when`) or a fine-grained `SKILL.md`. Promote a default only
  after paired `independent_validation` via `moldarwin_revision_compare`; record local or
  negative outcomes with boundaries via `moldarwin_research_progress`. Before hiding old
  records from a default view, check `moldarwin_admission_view(..., shadow_nodes=[...])`.
