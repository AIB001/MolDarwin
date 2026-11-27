"""Read-only host discovery; does not create another planner or scientific journal."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

from moldarwin.mcp._common import Cost, ok, tool


def _registered_tool_catalog(mcp: Any) -> dict[str, dict[str, str]]:
    """Describe this live server; registration-only collectors keep old discovery."""
    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:
        # Lightweight compatibility collectors have no callable-server registry.
        from moldarwin.mcp.server import tool_catalog
        return tool_catalog()
    found = {}
    for registered in manager.list_tools():
        function = registered.fn
        cost = getattr(function, "moldarwin_cost", None)
        description = registered.description or inspect.getdoc(function) or ""
        found[registered.name] = {
            "cost": cost.value if isinstance(cost, Cost) else "not_declared",
            "description": " ".join(description.split("\n\n", 1)[0].split()),
        }
    return found


def register(mcp: Any) -> None:
    def moldarwin_research_hook(event: dict) -> Any:
        """FREE. Native lifecycle adapter; prepares research context and delivery receipts.

        Uses the server's installed MOLDARWIN_RESEARCH_HOOK_BINDING, never caller-supplied
        entry or state paths. Writes host delivery metadata only; no scientific write,
        computation, checkpoint creation or RSI. An event is a supplied observation;
        native provenance is verified separately against the host trace.
        """
        import json

        from mcp.types import CallToolResult, TextContent

        from moldarwin.mcp._common import StdoutToStderr
        from moldarwin.research_hooks import handle_bound_event
        try:
            with StdoutToStderr():
                result = handle_bound_event(event)
            failed = not result["ok"]
            output = result["host_output"] if not failed else {
                "ok": False, "error": result["receipt"]["error"],
                "receipt_path": result["receipt_path"], "automatic_retry": False}
        except (ValueError, KeyError, OSError) as exc:
            failed = True
            output = {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)},
                      "automatic_retry": False}
        # Native hook consumers parse the text as the hook output itself. The
        # ordinary MolDarwin ok envelope would hide hookSpecificOutput. Protocol
        # isError, unlike an ok:false text alone, is recognized by both hosts.
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(
            output, ensure_ascii=False, separators=(",", ":")))], isError=failed)

    moldarwin_research_hook.moldarwin_cost = Cost.FREE
    mcp.tool()(moldarwin_research_hook)

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_capabilities(detail: str = "full", skills: list[str] | None = None,
                            tools: list[str] | None = None,
                            operations: list[str] | None = None,
                            include_environment: bool = False,
                            include_data_sources: bool = False) -> str:
        """FREE. Discover all or selected capabilities; known tools need no discovery call.

        Defaults retain the full catalog. detail='summary' omits file manifests.
        Each selector is exact names: null means all, [] means none. For example,
        skills=['campaign'], tools=[], operations=[] reads just that skill bundle.
        Set include_environment=True for a compact live compute/GPU/engine/charter snapshot
        without exploratory shell turns. Set include_data_sources=True for read-only
        MolOrigin data-source availability without enabling the optional data pack.
        Summary includes entrypoints and complete selected-bundle version digests;
        detail='full' expands their member inventory. This is not a method whitelist.
        tools lists only this server's callable registrations. operations describes the
        general runtime API, not additional callable tools on this instance.
        """
        from moldarwin.skills import _selection, catalog

        report = catalog(detail=detail, skills=skills)
        if tools == []:
            tool_report = {}
        else:
            available = _registered_tool_catalog(mcp)
            tool_report = {name: available[name]["cost"] if detail == "full" else available[name]
                           for name in _selection(tools, available, "tools")}
        if operations == []:
            operation_report = {}
        else:
            from moldarwin.runtime.operations import describe
            available_operations = describe()
            operation_report = {name: available_operations[name]
                                for name in _selection(operations, available_operations, "operations")}
        if detail != "full" or any(value is not None for value in (skills, tools, operations)):
            report.update(detail=detail, scope={"skills": [row["slug"] for row in report["skills"]],
                                               "tools": list(tool_report), "operations": list(operation_report)})
        extra: dict[str, Any] = {}
        if detail == "summary":
            from moldarwin.mcp.profiles import pack_catalog, pack_summary
            extra["available_packs"] = pack_summary()
            extra["pack_tiers"] = pack_catalog(include_legacy=True)
        if include_environment:
            from moldarwin.runtime.environment import format_environment_card, probe_environment
            env = probe_environment()
            extra["environment"] = env
            extra["environment_card"] = format_environment_card(env)
        if include_data_sources:
            try:
                from moldarwin.boundary.molorigin import sources as molorigin_sources
                extra["data_sources"] = molorigin_sources()
            except Exception as exc:  # noqa: BLE001
                extra["data_sources"] = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        return ok(**report, **extra, tools=tool_report, operations=operation_report,
                  runtime={"python": sys.executable, "module": str(Path(__file__).resolve()),
                           "durable_workers": "Linux /proc and POSIX locks required"})

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_skill_find(query: str = "", domain: str | None = None,
                             tags: list[str] | None = None, source: str | None = None,
                             extra_dirs: list[str] | None = None,
                             include_retired: bool = False, include_legacy: bool = False,
                             list_domains: bool = False, limit: int = 5) -> str:
        """FREE. Lazy Tier-1 discovery over active v2 built-in and live generated skill directories.

        Reads only YAML frontmatter headers (never full bodies or references), so context
        stays O(1) even with hundreds of fine-grained target/method skills. Defaults to the
        12 active v2 built-in skills plus all live generated skills (set include_legacy=True
        to include archived/overlapping historical built-in skills). Set list_domains=True
        for a compact domain/tag taxonomy overview, or pass query/domain/tags to get top-K
        cards carrying applicable_when, invalid_when, and ready arguments for
        moldarwin_skill_read. Live directories from extra_dirs or MOLDARWIN_SKILL_DIRS are
        indexed immediately without restarting the server. Never activates or runs a skill.
        """
        from moldarwin.mcp._common import absolute_path
        from moldarwin.skill_index import find_skills

        resolved_dirs = (
            [str(absolute_path(item, label="extra_dirs")) for item in extra_dirs]
            if extra_dirs is not None
            else None
        )
        return ok(**find_skills(
            query=query, domain=domain, tags=tags, source=source,
            extra_dirs=resolved_dirs, include_retired=include_retired,
            include_legacy=include_legacy, list_domains=list_domains, limit=limit,
        ))

    @mcp.tool()
    @tool(Cost.FREE)
    def moldarwin_skill_read(slug: str, member: str = "SKILL.md", bundle_ref: dict | None = None) -> str:
        """FREE. Read one text member of an installed skill, with its file and bundle digests.

        Known slugs/members can be read directly; discovery is optional. References are loaded
        only when relevant; no experiment is dispatched or skill use inferred.
        Installed names (moldarwin-screening-sweep), MCP slugs (sweep), and resource
        URIs (moldarwin://skills/sweep) select the same built-in bytes and version.
        """
        from moldarwin.skills import read_member

        if bundle_ref is not None and not bundle_ref.get("manifest_sha256"):
            raise ValueError("MCP explicit bundle reads require an expected manifest_sha256")
        return ok(**read_member(slug, member, bundle_ref=bundle_ref))
