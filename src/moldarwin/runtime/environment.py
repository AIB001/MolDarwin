"""Lightweight compute, GPU-idle, engine, and charter introspection for autonomous planning.

Designed to replace 5-8 exploratory shell turns with a single ~80-120 token snapshot
without adding any new always-on MCP tool to ``THIN_CORE_TOOLS`` or mutating state.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

ENV_SCHEMA = "moldarwin-environment/1"
BUDGET_ESTIMATE_SCHEMA = "moldarwin-budget-estimate/1"

#: Default thresholds classifying a GPU as safe/idle for autonomous allocation
#: (Evidence: convention, avoiding active multi-tenant jobs while tolerating desktop/driver contexts).
DEFAULT_GPU_IDLE_MEM_MB: int = 1500
DEFAULT_GPU_IDLE_UTIL_PCT: int = 15

CLI_ENGINES: tuple[str, ...] = (
    "unidock",
    "gnina",
    "gmx",
    "MMPBSA.py",
    "antechamber",
    "obabel",
    "smina",
    "vina",
    "boltz",
    "chai",
)

PY_ENGINES: tuple[str, ...] = (
    "rdkit",
    "meeko",
    "openmm",
    "mdtraj",
    "MDAnalysis",
    "pymbar",
    "alchemlyb",
    "torch",
    "scipy",
    "sklearn",
)


def _parse_int_list(raw: str | None) -> list[int] | None:
    if not raw or not raw.strip():
        return None
    out: list[int] = []
    for tok in raw.split(","):
        s = tok.strip()
        if s.isdigit():
            out.append(int(s))
    return out or None


def _probe_gpus(
    *,
    gpu_idle_mem_mb: int = DEFAULT_GPU_IDLE_MEM_MB,
    gpu_idle_util_pct: int = DEFAULT_GPU_IDLE_UTIL_PCT,
    allowed_gpus: list[int] | None = None,
) -> dict[str, Any]:
    """Query live GPU availability via ``nvidia-smi`` without initializing CUDA."""
    visible_filter = _parse_int_list(os.environ.get("CUDA_VISIBLE_DEVICES"))
    explicit_allowed = (
        allowed_gpus
        if allowed_gpus is not None
        else _parse_int_list(os.environ.get("MOLDARWIN_ALLOWED_GPUS"))
    )

    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        return {
            "detected": False,
            "devices": [],
            "idle_gpus": [],
            "busy_gpus": [],
            "gpu_policy": "none_detected",
        }

    try:
        proc = subprocess.run(
            [
                nvsmi,
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "detected": False,
            "devices": [],
            "idle_gpus": [],
            "busy_gpus": [],
            "gpu_policy": "probe_failed",
        }

    if proc.returncode != 0:
        return {
            "detected": False,
            "devices": [],
            "idle_gpus": [],
            "busy_gpus": [],
            "gpu_policy": "probe_failed",
        }

    devices: list[dict[str, Any]] = []
    idle_gpus: list[int] = []
    busy_gpus: list[int] = []

    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            idx = int(parts[0])
            name = parts[1]
            mem_total = int(float(parts[2]))
            mem_used = int(float(parts[3]))
            util = int(float(parts[4]))
        except ValueError:
            continue

        if visible_filter is not None and idx not in visible_filter:
            continue

        is_idle = (mem_used <= gpu_idle_mem_mb) and (util <= gpu_idle_util_pct)
        is_allowed = (explicit_allowed is None) or (idx in explicit_allowed)
        rec = {
            "index": idx,
            "name": name,
            "memory_total_mb": mem_total,
            "memory_used_mb": mem_used,
            "utilization_gpu_pct": util,
            "idle": is_idle,
            "allowed": is_allowed,
        }
        devices.append(rec)
        if is_idle and is_allowed:
            idle_gpus.append(idx)
        else:
            busy_gpus.append(idx)

    policy = "explicit_allowed_and_idle" if explicit_allowed is not None else "idle_only"
    return {
        "detected": bool(devices),
        "devices": devices,
        "idle_gpus": idle_gpus,
        "busy_gpus": busy_gpus,
        "idle_thresholds": {
            "max_memory_used_mb": gpu_idle_mem_mb,
            "max_utilization_pct": gpu_idle_util_pct,
            "evidence": "convention",
        },
        "gpu_policy": policy,
    }


def _host_memory_gb() -> float | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024.0 * 1024.0), 1)
        except (OSError, ValueError, IndexError):
            return None
    return None


def _load_charter(charter_path: str | Path | None = None) -> dict[str, Any] | None:
    raw_path = charter_path or os.environ.get("MOLDARWIN_CHARTER_PATH")
    charter: dict[str, Any] = {}
    if raw_path:
        p = Path(raw_path)
        if p.is_file():
            try:
                loaded = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    charter.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
    if os.environ.get("MOLDARWIN_WALL_CLOCK_MIN"):
        with contextlib.suppress(ValueError):
            charter["wall_clock_min"] = float(os.environ["MOLDARWIN_WALL_CLOCK_MIN"])
    if os.environ.get("MOLDARWIN_GPU_POLICY"):
        charter["gpu_policy"] = os.environ["MOLDARWIN_GPU_POLICY"]
    return charter or None


def probe_environment(
    work_dir: str | Path | None = None,
    *,
    gpu_idle_mem_mb: int = DEFAULT_GPU_IDLE_MEM_MB,
    gpu_idle_util_pct: int = DEFAULT_GPU_IDLE_UTIL_PCT,
    allowed_gpus: list[int] | None = None,
    charter_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a compact, side-effect-free inventory of compute, engines, and charter."""
    root = Path(work_dir).resolve() if work_dir else Path.cwd()
    disk = shutil.disk_usage(root if root.exists() else Path.cwd())
    cpu_cores = os.cpu_count() or 1
    gpu_info = _probe_gpus(
        gpu_idle_mem_mb=gpu_idle_mem_mb,
        gpu_idle_util_pct=gpu_idle_util_pct,
        allowed_gpus=allowed_gpus,
    )

    cli_found = {name: shutil.which(name) for name in CLI_ENGINES if shutil.which(name)}
    py_found = [name for name in PY_ENGINES if importlib.util.find_spec(name) is not None]

    pinned_prism = False
    try:
        from moldarwin.boundary.infra import locate

        pinned_prism = locate("prism") is not None
    except Exception:
        pinned_prism = False

    n_idle = len(gpu_info["idle_gpus"])
    omp_per_gpu = max(1, min(12, cpu_cores // max(1, n_idle))) if n_idle else max(1, min(8, cpu_cores))

    return {
        "schema": ENV_SCHEMA,
        "work_dir": str(root),
        "cpu_cores": cpu_cores,
        "mem_total_gb": _host_memory_gb(),
        "disk_free_gb": round(disk.free / (1024.0**3), 1),
        "gpus": gpu_info,
        "omp_threads_per_gpu_job": omp_per_gpu,
        "engines_cli": sorted(cli_found.keys()),
        "engines_cli_paths": cli_found,
        "engines_py": py_found,
        "pinned_prism_available": pinned_prism,
        "charter": _load_charter(charter_path),
    }


def format_environment_card(env: dict[str, Any]) -> str:
    """Format a compact ~70-110 token environment card for SessionStart or planning."""
    gpus = env.get("gpus") or {}
    idle = gpus.get("idle_gpus", [])
    busy = gpus.get("busy_gpus", [])
    vram_hint = ""
    devices = gpus.get("devices") or []
    if devices:
        vram_gb = round(devices[0].get("memory_total_mb", 0) / 1024.0)
        if vram_gb > 0:
            vram_hint = f"({vram_gb}GB)"

    busy_str = f" busy_gpus={busy}(DO_NOT_USE)" if busy else ""
    mem_str = f" ram={env['mem_total_gb']}GB" if env.get("mem_total_gb") is not None else ""
    lines = [
        (
            f"[moldarwin-env] idle_gpus={idle}{vram_hint}{busy_str} "
            f"cpu={env.get('cpu_cores')} omp_per_gpu={env.get('omp_threads_per_gpu_job')}"
            f"{mem_str} disk_free={env.get('disk_free_gb')}GB"
        ),
        f"engines_cli: {', '.join(env.get('engines_cli') or ['none'])}",
        (
            "engines_py: "
            + ", ".join(
                list(env.get("engines_py") or [])
                + (["prism(pinned)"] if env.get("pinned_prism_available") else [])
            )
        ),
    ]
    charter = env.get("charter")
    if isinstance(charter, dict) and charter:
        parts = [f"{k}={v}" for k, v in sorted(charter.items()) if v is not None]
        if parts:
            lines.append("charter: " + " ".join(parts[:6]))
    return "\n".join(lines)


def estimate_experiment_budget(
    pilot_items: int,
    pilot_wall_s: float,
    *,
    remaining_wall_min: float,
    available_gpus: int,
    pilot_gpus: int = 1,
    safety_fraction: float = 0.5,
    target_items: int | None = None,
) -> dict[str, Any]:
    """Scale an experiment from an empirical micro-pilot measurement without blind guessing."""
    if pilot_items <= 0 or pilot_wall_s <= 0 or remaining_wall_min <= 0 or available_gpus <= 0 or pilot_gpus <= 0:
        raise ValueError("pilot_items, pilot_wall_s, remaining_wall_min, available_gpus, and pilot_gpus must be positive")
    if not (0.0 < safety_fraction <= 1.0):
        raise ValueError("safety_fraction must lie in (0, 1]")

    pilot_gpu_min = (pilot_wall_s / 60.0) * pilot_gpus
    rate_per_gpu_min = pilot_items / pilot_gpu_min
    usable_gpu_min = remaining_wall_min * available_gpus * safety_fraction
    recommended_max_items = max(1, int(math.floor(rate_per_gpu_min * usable_gpu_min)))

    out: dict[str, Any] = {
        "schema": BUDGET_ESTIMATE_SCHEMA,
        "evidence": "measured_here",
        "pilot_items": int(pilot_items),
        "pilot_wall_s": round(float(pilot_wall_s), 2),
        "pilot_gpus": int(pilot_gpus),
        "throughput_items_per_gpu_min": round(rate_per_gpu_min, 3),
        "remaining_wall_min": round(float(remaining_wall_min), 2),
        "available_gpus": int(available_gpus),
        "safety_fraction": float(safety_fraction),
        "recommended_max_items": recommended_max_items,
    }
    if target_items is not None:
        est_wall_min = float(target_items) / (rate_per_gpu_min * available_gpus)
        out["target_items"] = int(target_items)
        out["estimated_target_wall_min"] = round(est_wall_min, 2)
        out["fits_budget"] = est_wall_min <= (remaining_wall_min * safety_fraction)
    return out
