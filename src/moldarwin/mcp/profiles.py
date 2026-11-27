"""Selective MCP tool-surface profiles and composable domain packs.

Exposing all 90+ tools simultaneously inflates every turn's tool-definition context.
The ``thin`` profile registers only 15 high-leverage core primitives (lazy skill
discovery/reading, bounded research context/progress/admission view, callable method
reuse, and guarded action execution) — an ~83% reduction in model-facing tool schemas —
while optional domain ``packs`` opt in to screening, sweep, data, governance, active,
workflow, planning, or extended research verbs without hiding ``SPENDS`` tools behind
an opaque meta-dispatcher.

Every tool retains its exact typed schema, ``Cost`` classification, and authorization
parameters across profiles. ``profile="full"`` preserves the complete legacy surface.
"""

from __future__ import annotations

import os
from typing import Any

ENV_PROFILE = "MOLDARWIN_MCP_PROFILE"
ENV_PACKS = "MOLDARWIN_MCP_PACKS"
PROFILES = ("full", "thin")

#: 16 core primitives for the thin default surface.
THIN_CORE_TOOLS: frozenset[str] = frozenset({
    # Lazy discovery & on-demand skill loading (3)
    "moldarwin_skill_find",
    "moldarwin_skill_read",
    "moldarwin_capabilities",
    # Research context, progress, evidence & live admission view (4)
    "moldarwin_research_context",
    "moldarwin_research_progress",
    "moldarwin_evidence_read",
    "moldarwin_admission_view",
    # Reusable callable method library & paired RSI comparison (5)
    "moldarwin_method_publish",
    "moldarwin_method_resolve",
    "moldarwin_method_call",
    "moldarwin_method_collect",
    "moldarwin_revision_compare",
    # Guarded runtime execution & native hook (4)
    "moldarwin_action_prepare",
    "moldarwin_action_submit",
    "moldarwin_action_result",
    "moldarwin_research_hook",
})

#: Composable domain packs for selective exposure on top of ``thin``.
TOOL_PACKS: dict[str, frozenset[str]] = {
    "screening": frozenset({
        "moldarwin_screen_configure",
        "moldarwin_screen_plan",
        "moldarwin_screen_submit",
        "moldarwin_screen_status",
        "moldarwin_screen_export",
        "moldarwin_screen_prepare_continuation",
        "moldarwin_doctor",
    }),
    "sweep": frozenset({
        "moldarwin_calibrate_gates",
        "moldarwin_authorize_gates",
        "moldarwin_sweep_admit",
        "moldarwin_sweep_emit",
        "moldarwin_sweep_claim",
        "moldarwin_sweep_record",
        "moldarwin_sweep_recover",
        "moldarwin_sweep_status",
        "moldarwin_sweep_progress",
        "moldarwin_generation_productivity",
        "moldarwin_devices",
        "moldarwin_campaign_plan",
    }),
    "data": frozenset({
        "moldarwin_data_sources",
        "moldarwin_data_plan",
        "moldarwin_data_run",
        "moldarwin_data_status",
        "moldarwin_data_prepare",
        "moldarwin_data_import_candidates",
        "moldarwin_data_review_template",
        "moldarwin_data_import_assays",
        "moldarwin_data_attach_handoffs",
    }),
    "governance": frozenset({
        "moldarwin_check_handoff",
        "moldarwin_check_stability",
        "moldarwin_rule_admissible",
        "moldarwin_design_fep_network",
        "moldarwin_authorize_spend",
        "moldarwin_council_reliability",
        "moldarwin_council_adjudicate",
        "moldarwin_recommend_waiver",
    }),
    "active": frozenset({
        "moldarwin_active_create",
        "moldarwin_active_status",
        "moldarwin_active_plan",
        "moldarwin_active_replay",
        "moldarwin_active_execution_plan",
        "moldarwin_active_submit",
    }),
    "workflow": frozenset({
        "moldarwin_wait_register",
        "moldarwin_events_read",
        "moldarwin_workflow_capabilities",
        "moldarwin_executor_prepare",
        "moldarwin_executor_register",
        "moldarwin_executor_list",
        "moldarwin_workflow_plan",
        "moldarwin_workflow_submit",
        "moldarwin_workflow_status",
        "moldarwin_workflow_observe",
        "moldarwin_workflow_advance",
        "moldarwin_workflow_cancel",
        "moldarwin_workflow_reconcile",
        "moldarwin_workflow_artifact",
    }),
    "planning": frozenset({
        "moldarwin_generation_runtime",
        "moldarwin_generation_feedback",
        "moldarwin_generation_handoff",
        "moldarwin_plan_campaign",
        "moldarwin_tune_screen",
        "moldarwin_stages",
        "moldarwin_infrastructure",
    }),
    "research-extended": frozenset({
        "moldarwin_research_advice",
        "moldarwin_research_fork_memory",
        "moldarwin_research_handoff",
        "moldarwin_research_handoff_verify",
        "moldarwin_resource_usage_read",
        "moldarwin_research_graph",
        "moldarwin_evidence_query",
        "moldarwin_resource_feedback",
        "moldarwin_method_criterion",
        "moldarwin_method_evaluate",
        "moldarwin_resource_usage_record",
        "moldarwin_method_record",
        "moldarwin_method_read",
    }),
    "prism": frozenset({
        "moldarwin_physics_preflight",
        "moldarwin_prism_prepare",
        "moldarwin_prism_analyze",
        "moldarwin_prism_fep_prepare",
        "moldarwin_prism_fep_analyze",
        "moldarwin_rescore_evaluate",
    }),
}


#: Empirical Verb-Census tier classification for every optional pack (Evidence: measured_here,
#: 6 live multi-GPU campaigns / 134 calls via ``tools/verb_census.py``).
#: - ``active_domain``: default v2 domain pack (with THIN_CORE_TOOLS covers 98.5-100% of live calls).
#: - ``l3_governance``: wet-lab spend authorization, waiver, and FEP network design (L2 -> L3 gate).
#: - ``optional_data``: MolOrigin data acquisition and assay import utilities.
#: - ``legacy``: 0 calls across all 6 live campaigns; retained strictly for backward-compat opt-in.
PACK_TIERS: dict[str, str] = {
    "prism": "active_domain",
    "governance": "l3_governance",
    "data": "optional_data",
    "screening": "legacy",
    "sweep": "legacy",
    "active": "legacy",
    "workflow": "legacy",
    "planning": "legacy",
    "research-extended": "legacy",
}

#: Recommended default packs for lean MolDarwin v2 autonomous CADD sessions (16 core + 6 prism = 22 tools).
RECOMMENDED_V2_PACKS: tuple[str, ...] = ("prism",)


def resolve_profile(profile: str | None = None) -> str:
    value = (os.environ.get(ENV_PROFILE, "full") if profile is None else profile).strip().lower()
    if value not in PROFILES:
        raise ValueError(f"unknown MCP profile {value!r}; expected one of {PROFILES}")
    return value


def resolve_packs(packs: list[str] | tuple[str, ...] | str | None = None) -> tuple[str, ...]:
    if packs is None:
        raw = os.environ.get(ENV_PACKS, "").strip()
        items = [part.strip().lower() for part in raw.split(",") if part.strip()] if raw else []
    elif isinstance(packs, str):
        items = [part.strip().lower() for part in packs.split(",") if part.strip()]
    else:
        items = [str(part).strip().lower() for part in packs if str(part).strip()]
    unknown = sorted(set(items) - set(TOOL_PACKS))
    if unknown:
        raise ValueError(f"unknown MCP tool packs: {unknown}; known: {sorted(TOOL_PACKS)}")
    return tuple(dict.fromkeys(items))


def allowed_tools(profile: str, packs: tuple[str, ...] = ()) -> frozenset[str] | None:
    """Return exact allowlist for selective registration, or ``None`` for full surface."""
    if profile == "full":
        return None
    names = set(THIN_CORE_TOOLS)
    for pack in packs:
        names.update(TOOL_PACKS[pack])
    return frozenset(names)


def pack_summary() -> dict[str, int]:
    """Compact pack-name -> tool-count index for on-demand discovery."""
    return {name: len(tools) for name, tools in sorted(TOOL_PACKS.items())}


def pack_catalog(*, include_legacy: bool = True) -> dict[str, dict[str, Any]]:
    """Tiered pack catalog distinguishing active v2 / L3 packs from zero-use legacy packs."""
    out: dict[str, dict[str, Any]] = {}
    for name, tools in sorted(TOOL_PACKS.items()):
        tier = PACK_TIERS.get(name, "legacy")
        if not include_legacy and tier == "legacy":
            continue
        out[name] = {
            "tool_count": len(tools),
            "tier": tier,
            "recommended_default": name in RECOMMENDED_V2_PACKS,
        }
    return out


class FilteredServer:
    """Minimal proxy that forwards only allowlisted ``@mcp.tool()`` registrations."""

    def __init__(self, target: Any, allowlist: frozenset[str]) -> None:
        self._target = target
        self._allowlist = allowlist

    def tool(self, *args: Any, **kwargs: Any) -> Any:
        explicit_name = kwargs.get("name")

        def decorate(function: Any) -> Any:
            tool_name = explicit_name or getattr(function, "__name__", "")
            if tool_name in self._allowlist:
                return self._target.tool(*args, **kwargs)(function)
            return function

        return decorate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


__all__ = [
    "ENV_PACKS",
    "ENV_PROFILE",
    "PACK_TIERS",
    "PROFILES",
    "RECOMMENDED_V2_PACKS",
    "THIN_CORE_TOOLS",
    "TOOL_PACKS",
    "FilteredServer",
    "allowed_tools",
    "pack_catalog",
    "pack_summary",
    "resolve_packs",
    "resolve_profile",
]
