"""Hardware-aware multi-job GPU concurrency packing and empirical RSI throughput tuner.

Addresses the classic large-VRAM GPU under-saturation seen on high-core GPUs (e.g.,
96 GB RTX PRO 6000 Blackwell running single 46k-atom GROMACS FEP windows at ~30% SM
utilization and <1% VRAM due to CPU/GPU perturbed-force synchronization).

Provides:
  1. Disjoint CPU-pinned multi-slot GPU packing plans (``plan_gpu_packing``) so
     packing 2-3 windows per GPU never causes OpenMP core contention.
  2. Empirical micro-benchmark selection (``select_optimal_concurrency``) returning a
     structured ``moldarwin-concurrency-tuning/1`` RSI record that refuses oversubscription
     whenever failures occur or aggregate throughput gain is below threshold.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

CONCURRENCY_PLAN_SCHEMA = "moldarwin-gpu-packing-plan/1"
CONCURRENCY_TUNING_SCHEMA = "moldarwin-concurrency-tuning/1"

#: Minimum aggregate throughput multiplier over k=1 required to justify packing >1 job/GPU
#: (Evidence: convention, avoiding added scheduling complexity for marginal <10% gains).
DEFAULT_MIN_SPEEDUP_GAIN: float = 1.10
DEFAULT_MAX_VRAM_FRACTION: float = 0.75


def plan_gpu_packing(
    idle_gpus: Sequence[int],
    cpu_cores: int,
    *,
    jobs_per_gpu: int | None = None,
    mem_per_job_mb: float = 1024.0,
    gpu_vram_mb: float = 98304.0,
    max_vram_fraction: float = DEFAULT_MAX_VRAM_FRACTION,
    min_omp_per_job: int = 2,
    max_omp_per_job: int = 12,
    single_job_sm_util_pct: float | None = None,
    reserve_os_cores: int = 0,
    max_jobs_per_gpu: int = 8,
    forbidden_gpus: Sequence[int] = (),
    cpu_offset_base: int = 0,
) -> dict[str, Any]:
    """Build a disjoint CPU-pinned multi-job packing plan across allowed GPUs.

    If ``jobs_per_gpu`` is omitted, recommends a packing factor bounded by VRAM headroom,
    minimum OpenMP threads per job, ``max_jobs_per_gpu`` (default 8 so 96 GB GPUs can
    pack 6+ small FEP windows cleanly), and (when provided) observed single-job SM
    utilization. Refuses immediately if any GPU in ``idle_gpus`` is in ``forbidden_gpus``.
    Set ``reserve_os_cores > 0`` on multi-GPU servers so SSH/kernel/IO threads are never
    starved by 100% pinned compute slots.
    """
    gpus = [int(g) for g in idle_gpus]
    forbidden = {int(g) for g in forbidden_gpus}
    if not gpus:
        raise ValueError("idle_gpus must be non-empty")
    overlap_forbidden = sorted(set(gpus) & forbidden)
    if overlap_forbidden:
        raise ValueError(
            f"refusing to plan compute on forbidden GPU(s): {overlap_forbidden}"
        )
    if cpu_cores < 1 or mem_per_job_mb <= 0 or gpu_vram_mb <= 0:
        raise ValueError("cpu_cores, mem_per_job_mb, and gpu_vram_mb must be positive")
    if reserve_os_cores < 0 or reserve_os_cores >= cpu_cores:
        raise ValueError(f"reserve_os_cores must lie in [0, {cpu_cores - 1}], got {reserve_os_cores}")
    if not (0.1 <= max_vram_fraction <= 0.95):
        raise ValueError("max_vram_fraction must lie in [0.1, 0.95]")
    if max_jobs_per_gpu < 1:
        raise ValueError("max_jobs_per_gpu must be >= 1")
    if cpu_offset_base < 0:
        raise ValueError("cpu_offset_base must be >= 0")

    usable_cores = cpu_cores - reserve_os_cores
    vram_cap = max(1, int(math.floor((gpu_vram_mb * max_vram_fraction) / mem_per_job_mb)))
    cpu_cap = max(1, usable_cores // (len(gpus) * max(1, min_omp_per_job)))
    max_safe_k = max(1, min(vram_cap, cpu_cap, int(max_jobs_per_gpu)))

    if jobs_per_gpu is not None:
        if jobs_per_gpu < 1:
            raise ValueError("jobs_per_gpu must be >= 1")
        k = int(jobs_per_gpu)
        if k > vram_cap:
            raise ValueError(
                f"requested jobs_per_gpu={k} exceeds VRAM safety cap ({vram_cap}) "
                f"for {mem_per_job_mb} MiB/job on {gpu_vram_mb} MiB GPU"
            )
    elif single_job_sm_util_pct is not None and single_job_sm_util_pct > 0:
        target_k = int(round(80.0 / float(single_job_sm_util_pct)))
        k = max(1, min(target_k, max_safe_k))
    else:
        # Default candidate: 2 jobs/GPU when VRAM >= 40 GB and CPU cores allow >=4 threads/job.
        k = 2 if (gpu_vram_mb >= 40000 and usable_cores >= len(gpus) * 8 and max_safe_k >= 2) else 1

    total_slots = len(gpus) * k
    ntomp = max(1, min(max_omp_per_job, usable_cores // total_slots))

    slots: list[dict[str, Any]] = []
    slot_idx = 0
    for gpu_id in gpus:
        for local_rank in range(k):
            cpu_offset = int(cpu_offset_base) + ((slot_idx * ntomp) % usable_cores)
            slots.append({
                "slot_id": slot_idx,
                "gpu_id": gpu_id,
                "gpu_local_rank": local_rank,
                "ntomp": ntomp,
                "pinoffset": cpu_offset,
                "env": {
                    "CUDA_VISIBLE_DEVICES": str(gpu_id),
                    "OMP_NUM_THREADS": str(ntomp),
                },
            })
            slot_idx += 1

    return {
        "schema": CONCURRENCY_PLAN_SCHEMA,
        "gpu_count": len(gpus),
        "idle_gpus": gpus,
        "forbidden_gpus": sorted(forbidden),
        "jobs_per_gpu": k,
        "max_safe_jobs_per_gpu": max_safe_k,
        "total_concurrent_slots": total_slots,
        "omp_threads_per_slot": ntomp,
        "total_cpus_assigned": total_slots * ntomp,
        "cpu_cores_available": cpu_cores,
        "cpu_cores_reserved_for_os": reserve_os_cores,
        "cpu_offset_base": int(cpu_offset_base),
        "estimated_vram_per_gpu_mb": round(k * mem_per_job_mb, 1),
        "vram_limit_per_gpu_mb": round(gpu_vram_mb * max_vram_fraction, 1),
        "slots": slots,
    }


def select_optimal_concurrency(
    benchmarks: Sequence[dict[str, Any]],
    *,
    min_speedup_gain: float = DEFAULT_MIN_SPEEDUP_GAIN,
    max_vram_mb: float | None = None,
) -> dict[str, Any]:
    """Select the highest-throughput verified ``jobs_per_gpu`` from empirical micro-benchmarks.

    Each benchmark record requires:
      - ``jobs_per_gpu`` (int >= 1)
      - ``wall_s`` (float > 0)
      - ``work_completed_per_job`` (float > 0, e.g., simulated ns or scored ligands per slot)
    Optional:
      - ``failed_jobs`` (int, default 0)
      - ``peak_vram_mb`` (float)
      - ``gpu_util_pct`` (float)
      - ``work_unit`` (str, e.g. ``"ns"`` or ``"ligands"``)
    """
    if not benchmarks:
        raise ValueError("benchmarks must contain at least one concurrency measurement")

    evaluated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    unit = str(benchmarks[0].get("work_unit") or "units")

    for raw in benchmarks:
        k = int(raw["jobs_per_gpu"])
        wall_s = float(raw["wall_s"])
        work_per_job = float(raw["work_completed_per_job"])
        failed = int(raw.get("failed_jobs") or 0)
        peak_vram = float(raw["peak_vram_mb"]) if raw.get("peak_vram_mb") is not None else None
        gpu_util = float(raw["gpu_util_pct"]) if raw.get("gpu_util_pct") is not None else None

        if k < 1 or not math.isfinite(wall_s) or wall_s <= 0 or not math.isfinite(work_per_job) or work_per_job <= 0:
            raise ValueError(f"invalid benchmark measurement for jobs_per_gpu={k}")

        reasons: list[str] = []
        if failed > 0:
            reasons.append(f"failed_jobs={failed}")
        if max_vram_mb is not None and peak_vram is not None and peak_vram > max_vram_mb:
            reasons.append(f"peak_vram_mb={peak_vram:.1f}>{max_vram_mb:.1f}")

        agg_per_min = (k * work_per_job) / (wall_s / 60.0)
        rec = {
            "jobs_per_gpu": k,
            "wall_s": round(wall_s, 3),
            "work_completed_per_job": round(work_per_job, 4),
            "aggregate_work_per_gpu_min": round(agg_per_min, 4),
            "aggregate_work_per_gpu_day": round(agg_per_min * 1440.0, 2),
            "peak_vram_mb": round(peak_vram, 1) if peak_vram is not None else None,
            "gpu_util_pct": round(gpu_util, 1) if gpu_util is not None else None,
            "failed_jobs": failed,
        }
        if reasons:
            rejected.append({**rec, "rejection_reasons": reasons})
        else:
            evaluated.append(rec)

    if not evaluated:
        return {
            "schema": CONCURRENCY_TUNING_SCHEMA,
            "evidence": "measured_here",
            "work_unit": unit,
            "selected_jobs_per_gpu": None,
            "verdict": "all_candidates_failed",
            "evaluated": [],
            "rejected": rejected,
        }

    evaluated.sort(key=lambda r: r["jobs_per_gpu"])
    baseline = next((r for r in evaluated if r["jobs_per_gpu"] == 1), evaluated[0])
    base_rate = baseline["aggregate_work_per_gpu_min"]

    for r in evaluated:
        r["speedup_vs_baseline"] = round(r["aggregate_work_per_gpu_min"] / base_rate, 3)

    best = max(evaluated, key=lambda r: (r["aggregate_work_per_gpu_min"], -r["jobs_per_gpu"]))
    if best["jobs_per_gpu"] > baseline["jobs_per_gpu"] and best["speedup_vs_baseline"] < min_speedup_gain:
        selected = baseline
        verdict = "keep_baseline_marginal_gain"
    elif best["jobs_per_gpu"] > baseline["jobs_per_gpu"]:
        selected = best
        verdict = "pack_multiple_jobs_per_gpu"
    else:
        selected = baseline
        verdict = "baseline_optimal"

    return {
        "schema": CONCURRENCY_TUNING_SCHEMA,
        "evidence": "measured_here",
        "work_unit": unit,
        "baseline_jobs_per_gpu": baseline["jobs_per_gpu"],
        "selected_jobs_per_gpu": selected["jobs_per_gpu"],
        "speedup_vs_baseline": selected["speedup_vs_baseline"],
        "min_speedup_gain_threshold": min_speedup_gain,
        "threshold_evidence": "convention",
        "verdict": verdict,
        "evaluated": evaluated,
        "rejected": rejected,
    }
