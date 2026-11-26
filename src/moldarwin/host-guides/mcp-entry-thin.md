# MolDarwin Host Guidance (Thin Profile — 16 Core Primitives)

You own the science: explore freely in native Python/SDK or `diagnostic` runs with zero
paperwork—no workflow DAGs, opportunity/patch forms, or routine audits. MolDarwin guards
only irreversible spend, provenance identity, and admission boundaries.

## Token & Turn Efficiency
- **3-tier lazy skills:** Call `moldarwin_skill_find(query=..., domain=..., tags=...)` (or
  `list_domains=True`) across built-in and live generated skills; read `applicable_when` /
  `invalid_when` first, then call `moldarwin_skill_read` only for the 1–2 matches.
- **Compact views by default:** Use `moldarwin_research_context(view="summary")`,
  `moldarwin_admission_view(detail="summary")`, and `moldarwin_revision_compare(detail="summary")`.
  Batch calculations in Python rather than serial tool loops.

## Recall, Hard Boundaries & Compounding RSI
- **Recall before rewriting:** Inspect `moldarwin_research_context(view="resources")` and
  `moldarwin_skill_find` first; reuse saved callables via `moldarwin_method_resolve` →
  `moldarwin_method_call` → `moldarwin_method_collect`.
- **Carry code, never target thresholds:** Transfer workflows/scripts across targets, never
  docking cutoffs; calibrate on each target's own controls before authorizing spend.
- Separate `completion`, `verification`, and `admission` (`diagnostic` and lessons are `used`,
  never `relied_on`). Never claim gain from dropped tasks or extra waivers.
- **Promote cleanly:** Publish reusable code via `moldarwin_method_publish` (`applicable_when`,
  `invalid_when`) or write a fine-grained `SKILL.md` into the live skill directory. Promote
  defaults only after paired `independent_validation` in `moldarwin_revision_compare`; test
  pruning via `moldarwin_admission_view(..., shadow_nodes=[...])`.
- Need domain MCP packs (`screening`, `sweep`, `data`, `governance`, `active`, `workflow`,
  `planning`, `research-extended`)? Enable via `MOLDARWIN_MCP_PACKS` / `--packs` or call the
  Python SDK directly.
