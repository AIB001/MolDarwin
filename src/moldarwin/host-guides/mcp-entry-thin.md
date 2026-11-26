You are connected to MolDarwin in thin profile (core execution, memory, reusable method, and admission primitives). Explore freely with native code and tools within the user's scope and resources; MolDarwin guards only irreversible spend, provenance identity, and admission boundaries.

Skills are lazy-loaded in three tiers — never dump the full catalog into context:
1. Call `moldarwin_skill_find(query=..., domain=..., tags=...)` (or `list_domains=True`) to retrieve top-K compact cards with `applicable_when` and `invalid_when` boundaries across built-in and live generated skills.
2. Call `moldarwin_skill_read(slug, bundle_ref=...)` only for the 1–2 matching skills (`SKILL.md` + `available_members`).
3. Load `references/...` or `scripts/...` members only when needed.

Use `moldarwin_research_context(view="summary")` to resume, `moldarwin_method_resolve` / `moldarwin_method_call` to reuse saved methods, and `moldarwin_admission_view` to inspect derived admission and membrane boundaries. Need domain packs (`screening`, `sweep`, `data`, `governance`, `active`, `workflow`, `planning`, `research-extended`)? Enable via `MOLDARWIN_MCP_PACKS` / `--packs` or call the Python SDK directly.
