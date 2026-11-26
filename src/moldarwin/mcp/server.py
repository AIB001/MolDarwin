"""Serve domain tools and optional capability resources over stdio.

The host owns research decisions. Tool registration and cost discovery share a
single path; skills, references and short host guidance are loaded on demand.
"""

from __future__ import annotations

import json
import inspect
from pathlib import Path
from typing import Any

from moldarwin.mcp._common import Cost, require_mcp, stdio_input
from moldarwin.skills import ROLE_PATH, bundle_root, catalog, read_member
from moldarwin.skills import WORKFLOWS as WORKFLOWS  # Preserve the public catalog import.

#: Stable entrypoint URI. Full capability bundles also ship in installed wheels.
SKILL_RESOURCE = "moldarwin://skills/campaign"
RUNTIME_RESOURCE = "moldarwin://runtime"


def _skill_path(slug: str = "campaign") -> Path:
    """Compatibility accessor for the entrypoint of a complete capability bundle."""
    return bundle_root(slug) / "SKILL.md"


def tool_modules() -> tuple[Any, ...]:
    """One module source for registration, cost discovery and compatibility clients."""
    from moldarwin.mcp import (
        active,
        data,
        evidence,
        execution,
        governance,
        host,
        methods,
        physics,
        planning,
        runtime,
        sweep,
    )

    return (planning, governance, active, execution, data, runtime, sweep, host, methods, evidence, physics)


def register_tools(
    server: Any, *, profile: str = "full", packs: list[str] | tuple[str, ...] | str | None = None
) -> None:
    """One registration path for the actual server, thin profiles, and its cost index."""
    from moldarwin.mcp.profiles import FilteredServer, allowed_tools, resolve_packs, resolve_profile

    selected_profile = resolve_profile(profile)
    selected_packs = resolve_packs(packs) if packs is not None else ()
    allowlist = allowed_tools(selected_profile, selected_packs)
    target = server if allowlist is None else FilteredServer(server, allowlist)
    for module in tool_modules():
        module.register(target)


def build(
    *, profile: str | None = None, packs: list[str] | tuple[str, ...] | str | None = None
) -> Any:
    """Construct the server with full or thin+packs tool surface and lazy resources."""
    from moldarwin.mcp.profiles import resolve_packs, resolve_profile

    selected_profile = resolve_profile(profile)
    selected_packs = resolve_packs(packs)
    server_class = require_mcp()
    guide_name = "mcp-entry-thin.md" if selected_profile == "thin" else "mcp-entry.md"
    guidance = ROLE_PATH.parent / "host-guides" / guide_name
    if not guidance.is_file():
        guidance = ROLE_PATH
    mcp = server_class("moldarwin", instructions=guidance.read_text(encoding="utf-8"))
    register_tools(mcp, profile=selected_profile, packs=selected_packs)

    @mcp.resource("moldarwin://skills/molorigin")
    def molorigin_workflows() -> str:
        """Discover all pinned acquisition workflows and their reference resource URIs."""
        rows = []
        for entry in catalog(skills=sorted(slug for slug in WORKFLOWS
                                          if slug.startswith("molorigin-")))["skills"]:
            slug = entry["name"].removeprefix("molorigin-")
            uri = "moldarwin://skills/molorigin/" + slug
            resources = [row["path"] for row in entry["files"]]
            rows.append({"name": entry["name"], "description": entry["description"],
                         "entrypoint": entry["entrypoint"], "resources": resources,
                         "uri": uri, "references": [
                uri + "/" + path for path in resources
                if path.startswith("references/")
            ]})
        return json.dumps({"skills": rows, "execution": "Use MolDarwin data tools for sealed acquisition."},
                          ensure_ascii=False)

    @mcp.resource("moldarwin://skills/molorigin/{skill}")
    def molorigin_workflow(skill: str) -> str:
        """Read a pinned workflow; discover names at moldarwin://skills/molorigin.

        Use MolDarwin's data tools for sealed acquisition and campaign ingress. These documents
        also describe advanced MolOrigin SDK workflows, not additional MolDarwin MCP tools.
        """
        return read_member("molorigin-" + skill)["content"]

    @mcp.resource("moldarwin://skills/molorigin/{skill}/references/{reference}")
    def molorigin_reference(skill: str, reference: str) -> str:
        """The reference document linked by each pinned MolOrigin workflow."""
        return read_member("molorigin-" + skill, "references/" + reference)["content"]

    @mcp.resource(SKILL_RESOURCE)
    def campaign_workflow() -> str:
        """Optional capability for expensive execution and scientific evidence admission."""
        return read_member("campaign")["content"]

    @mcp.resource("moldarwin://skills")
    def workflows() -> str:
        """Optional skills, supporting files and independently versioned host guidance."""
        report = catalog()
        # Retain the old index shape for existing readers, without a mandatory route.
        report["workflows"] = [
            {"uri": f"moldarwin://skills/{row['slug']}", "skill": row["name"],
             "regime": row["description"]} for row in report["skills"]]
        return json.dumps(report, ensure_ascii=False)

    @mcp.resource("moldarwin://skill-libraries")
    def skill_libraries() -> str:
        """Discover memory, execution and RSI skills without loading their bodies."""
        from moldarwin.skills import library_catalog
        return json.dumps(library_catalog(), ensure_ascii=False)

    @mcp.resource("moldarwin://skill-index")
    def skill_index() -> str:
        """Tier-1 domain/tag taxonomy over built-in and live generated skills (headers only)."""
        from moldarwin.skill_index import find_skills
        return json.dumps(find_skills(list_domains=True), ensure_ascii=False)

    @mcp.resource("moldarwin://skills/{slug}")
    def workflow(slug: str) -> str:
        """One workflow document; discover the slugs at ``moldarwin://skills``."""

        return read_member(slug)["content"]

    @mcp.resource("moldarwin://skills/{slug}/references/{name}")
    def skill_reference(slug: str, name: str) -> str:
        """Read one supporting reference; exact members are listed in the skill catalog."""
        return read_member(slug, "references/" + name)["content"]

    @mcp.resource("moldarwin://host")
    def host_guidance() -> str:
        """Short research responsibilities and skill usage guidance for the host."""
        return ROLE_PATH.read_bytes().decode("utf-8")

    @mcp.resource(RUNTIME_RESOURCE)
    def runtime_workflow() -> str:
        """Durable workflow and executor protocol, resource budgets and verified completion rules.

        Read before workflow submission or external controller decisions. The same document
        ships with the runtime package and describes how to inspect and recover saved work.
        """

        return (Path(__file__).resolve().parents[1] / "runtime" / "README.md").read_text(encoding="utf-8")

    @mcp.resource("moldarwin://findings")
    def findings() -> str:
        """Every measurement this project has recorded, as one document.

        Each is a JSON file under ``findings/`` carrying what was measured, why it matters, and a
        "how this could be wrong" section. A model justifying a decision to an operator should quote
        from here rather than paraphrase: the numbers are the argument.
        """

        root = Path(__file__).resolve().parents[3] / "findings"
        if not root.is_dir():
            return "No findings directory in this installation."
        parts = [
            f"## {path.name}\n\n```json\n{path.read_text(encoding='utf-8')}\n```"
            for path in sorted(root.glob("*.json"))
        ]
        return "# MolDarwin findings\n\n" + "\n\n".join(parts)

    @mcp.resource("moldarwin://decisions")
    def decisions() -> str:
        """Every architectural decision, with the measurement that forced it.

        Read ``0003`` before acting as an advisor inside a campaign, and ``0005`` before planning one
        that ends in relative FEP.
        """

        root = Path(__file__).resolve().parents[3] / "docs" / "adr"
        if not root.is_dir():
            return "No ADR directory in this installation."
        return "\n\n---\n\n".join(
            path.read_text(encoding="utf-8") for path in sorted(root.glob("*.md"))
        )

    return mcp


def tool_catalog() -> dict[str, dict[str, str]]:
    """Short descriptions and declared costs from the actual registration path."""

    found: dict[str, dict[str, str]] = {}

    class Collector:
        def tool(self) -> Any:
            def decorate(function: Any) -> Any:
                cost = getattr(function, "moldarwin_cost", None)
                if not isinstance(cost, Cost):
                    raise ValueError(f"tool {function.__name__} has no explicit cost classification")
                if function.__name__ in found:
                    raise ValueError(f"duplicate tool name: {function.__name__}")
                description = (inspect.getdoc(function) or "").split("\n\n", 1)[0]
                found[function.__name__] = {
                    "cost": cost.value, "description": " ".join(description.split()),
                }
                return function

            return decorate

    collector = Collector()
    register_tools(collector)
    return found


def costs() -> dict[str, str]:
    """Every tool's declared spend class; preserve the original discovery shape."""
    return {name: item["cost"] for name, item in tool_catalog().items()}


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="moldarwin-mcp", add_help=True)
    parser.add_argument(
        "--profile",
        choices=("full", "thin"),
        default=None,
        help="Tool surface profile: 'thin' exposes 16 core primitives + lazy skill discovery; 'full' exposes all tools.",
    )
    parser.add_argument(
        "--packs",
        default=None,
        help="Comma-separated domain packs to add to thin profile (e.g. screening,data,governance).",
    )
    args = parser.parse_args(argv)
    with stdio_input():
        if args.profile is None and args.packs is None:
            build().run()
        else:
            build(profile=args.profile, packs=args.packs).run()


if __name__ == "__main__":
    main()
