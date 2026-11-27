"""Disjoint resource partitioning and compact handoff contracts for parallel subagents.

Enables a lean Coordinator thread (Codex CLI, Antigravity, or Claude Code) to delegate
noisy, parallel, or specialized work (literature/structure intake, competing GPU protocol
branches, build/crash debugging, independent verification) without polluting its own
context window or colliding on GPUs, CPU cores, or workspace paths.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from moldarwin.runtime.concurrency import plan_gpu_packing

SUBAGENT_PARTITION_SCHEMA = "moldarwin-subagent-partition/1"
SUBAGENT_BRIEF_SCHEMA = "moldarwin-subagent-brief/1"
SUBAGENT_HANDOFF_SCHEMA = "moldarwin-subagent-handoff/1"

#: Default byte cap on a subagent's inline summary returned to the Coordinator
#: (Evidence: convention, keeping Coordinator context compact across 10+ subagent calls).
DEFAULT_MAX_HANDOFF_BYTES: int = 3072


def partition_resources_for_subagents(
    env: Mapping[str, Any],
    subagents: Sequence[Mapping[str, Any]],
    *,
    work_root: str | Path,
    total_wall_clock_min: float | None = None,
) -> dict[str, Any]:
    """Carve disjoint GPU leases, CPU pin ranges, and isolated work dirs for parallel subagents.

    Each item in ``subagents`` requires:
      - ``name`` (str, short unique identifier e.g. ``"intake"``, ``"branch_tyk2"``)
      - ``role`` (str, e.g. ``"intake"``, ``"gpu_branch"``, ``"debugger"``, ``"verifier"``)
    Optional per-subagent fields:
      - ``needs_gpu`` (bool, default True for ``role == "gpu_branch"``, else False)
      - ``gpu_weight`` (float, relative GPU share among GPU subagents, default 1.0)
      - ``jobs_per_gpu`` (int | None, optional packing factor passed to ``plan_gpu_packing``)
      - ``wall_clock_min`` (float | None)
    """
    if not subagents:
        raise ValueError("subagents must be non-empty")

    root = Path(work_root).resolve()
    gpus_block = env.get("gpus") or {}
    idle_gpus = [int(g) for g in gpus_block.get("idle_gpus") or []]
    devices = gpus_block.get("devices") or []
    vram_mb = float(devices[0]["memory_total_mb"]) if devices else 24576.0
    total_cpus = max(1, int(env.get("cpu_cores") or 1))

    seen_names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in subagents:
        name = str(raw["name"]).strip()
        if not name or name in seen_names:
            raise ValueError(f"subagent name must be non-empty and unique (got {name!r})")
        seen_names.add(name)
        role = str(raw.get("role") or "worker").strip()
        needs_gpu = bool(raw["needs_gpu"]) if "needs_gpu" in raw else (role == "gpu_branch")
        weight = float(raw.get("gpu_weight") or 1.0)
        if weight <= 0:
            raise ValueError(f"gpu_weight must be positive for {name!r}")
        normalized.append({
            "name": name,
            "role": role,
            "needs_gpu": needs_gpu,
            "gpu_weight": weight,
            "jobs_per_gpu": raw.get("jobs_per_gpu"),
            "wall_clock_min": raw.get("wall_clock_min"),
        })

    gpu_agents = [s for s in normalized if s["needs_gpu"]]
    cpu_only_agents = [s for s in normalized if not s["needs_gpu"]]

    if gpu_agents and len(gpu_agents) > len(idle_gpus):
        raise ValueError(
            f"cannot assign disjoint GPUs to {len(gpu_agents)} GPU subagents with only "
            f"{len(idle_gpus)} idle GPU(s) available"
        )

    # Reserve a small slice of CPUs for CPU-only subagents (intake/verifier), rest to GPU branches.
    cpu_reserve_each = min(4, max(1, total_cpus // max(8, len(normalized) * 2))) if cpu_only_agents else 0
    cpu_for_gpu_agents = max(len(gpu_agents), total_cpus - cpu_reserve_each * len(cpu_only_agents))

    # Proportional disjoint GPU allocation (guaranteeing >=1 GPU per GPU subagent).
    gpu_slices: dict[str, list[int]] = {}
    if gpu_agents:
        remaining = list(idle_gpus)
        total_w = sum(s["gpu_weight"] for s in gpu_agents)
        counts: list[int] = [1] * len(gpu_agents)
        extra = len(remaining) - len(gpu_agents)
        if extra > 0:
            raw_extras = [extra * (s["gpu_weight"] / total_w) for s in gpu_agents]
            floors = [int(math.floor(x)) for x in raw_extras]
            for i, f in enumerate(floors):
                counts[i] += f
            leftover = extra - sum(floors)
            order = sorted(range(len(gpu_agents)), key=lambda i: raw_extras[i] - floors[i], reverse=True)
            for i in order[:leftover]:
                counts[i] += 1
        cursor = 0
        for s, cnt in zip(gpu_agents, counts, strict=True):
            gpu_slices[s["name"]] = remaining[cursor : cursor + cnt]
            cursor += cnt

    leases: list[dict[str, Any]] = []
    cpu_cursor = 0

    for s in gpu_agents:
        assigned_gpus = gpu_slices[s["name"]]
        share_cpus = max(
            len(assigned_gpus),
            int(math.floor(cpu_for_gpu_agents * (len(assigned_gpus) / max(1, len(idle_gpus))))),
        )
        packing = plan_gpu_packing(
            assigned_gpus,
            share_cpus,
            jobs_per_gpu=s["jobs_per_gpu"],
            gpu_vram_mb=vram_mb,
        )
        # Shift local pinoffsets into this subagent's disjoint global CPU slice.
        shifted_slots = []
        for slot in packing["slots"]:
            shifted_slots.append({**slot, "pinoffset": cpu_cursor + int(slot["pinoffset"])})
        packing["slots"] = shifted_slots

        agent_dir = root / "subagents" / s["name"]
        leases.append({
            "name": s["name"],
            "role": s["role"],
            "work_dir": str(agent_dir),
            "handoff_path": str(agent_dir / "handoff.json"),
            "gpus": assigned_gpus,
            "cuda_visible_devices": ",".join(str(g) for g in assigned_gpus),
            "cpu_core_start": cpu_cursor,
            "cpu_core_count": share_cpus,
            "packing": packing,
            "wall_clock_min": s["wall_clock_min"] or total_wall_clock_min,
        })
        cpu_cursor += share_cpus

    for s in cpu_only_agents:
        agent_dir = root / "subagents" / s["name"]
        leases.append({
            "name": s["name"],
            "role": s["role"],
            "work_dir": str(agent_dir),
            "handoff_path": str(agent_dir / "handoff.json"),
            "gpus": [],
            "cuda_visible_devices": "",
            "cpu_core_start": cpu_cursor,
            "cpu_core_count": cpu_reserve_each,
            "packing": None,
            "wall_clock_min": s["wall_clock_min"] or (min(10.0, total_wall_clock_min) if total_wall_clock_min else None),
        })
        cpu_cursor += cpu_reserve_each

    return {
        "schema": SUBAGENT_PARTITION_SCHEMA,
        "work_root": str(root),
        "total_idle_gpus": len(idle_gpus),
        "total_cpus": total_cpus,
        "leases": leases,
    }


def build_subagent_brief(
    lease: Mapping[str, Any],
    *,
    objective: str,
    done_criteria: Sequence[str],
    inputs: Mapping[str, Any] | None = None,
    max_handoff_bytes: int = DEFAULT_MAX_HANDOFF_BYTES,
) -> dict[str, Any]:
    """Create a tight, token-minimal assignment brief enforcing bounded JSON handoff."""
    return {
        "schema": SUBAGENT_BRIEF_SCHEMA,
        "subagent": lease["name"],
        "role": lease["role"],
        "objective": objective,
        "done_criteria": list(done_criteria),
        "resource_lease": {
            "work_dir": lease["work_dir"],
            "handoff_path": lease["handoff_path"],
            "gpus": lease["gpus"],
            "cuda_visible_devices": lease["cuda_visible_devices"],
            "cpu_core_start": lease["cpu_core_start"],
            "cpu_core_count": lease["cpu_core_count"],
            "wall_clock_min": lease["wall_clock_min"],
            "jobs_per_gpu": (lease["packing"]["jobs_per_gpu"] if lease.get("packing") else 0),
        },
        "inputs": dict(inputs or {}),
        "handoff_contract": {
            "required_keys": ["status", "summary", "metrics", "artifacts", "failures"],
            "max_inline_bytes": int(max_handoff_bytes),
            "rule": (
                "Write full raw outputs inside work_dir; return ONLY a compact JSON handoff "
                "at handoff_path (<= max_inline_bytes) with file pointers and measured numbers."
            ),
        },
    }


def validate_subagent_handoff(
    handoff: Mapping[str, Any],
    *,
    max_bytes: int = DEFAULT_MAX_HANDOFF_BYTES,
) -> dict[str, Any]:
    """Verify a subagent return envelope stays compact, structured, and Coordinator-safe."""
    required = ("status", "summary", "metrics", "artifacts", "failures")
    missing = [k for k in required if k not in handoff]
    serialized = json.dumps(dict(handoff), sort_keys=True, separators=(",", ":"), allow_nan=False)
    n_bytes = len(serialized.encode("utf-8"))
    status = str(handoff.get("status", ""))
    valid_status = status in {"completed", "failed", "blocked", "partial"}

    issues: list[str] = []
    if missing:
        issues.append(f"missing required keys: {missing}")
    if not valid_status:
        issues.append(f"status {status!r} must be one of completed/failed/blocked/partial")
    if n_bytes > max_bytes:
        issues.append(f"handoff size ({n_bytes} bytes) exceeds max_bytes ({max_bytes}); keep raw logs on disk")

    return {
        "schema": SUBAGENT_HANDOFF_SCHEMA,
        "valid": not issues,
        "bytes": n_bytes,
        "max_bytes": max_bytes,
        "status": status,
        "issues": issues,
    }
