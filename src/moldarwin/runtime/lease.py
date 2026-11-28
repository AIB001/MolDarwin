"""Code-enforced multi-tenant GPU/CPU compute lease, single-dispatcher lock, and retry backoff.

Replaces prompt-only hardware discipline with OS-level single-instance locking and
deterministic pre-launch validation so autonomous campaigns can never:
  1. Spawn duplicate supervisor dispatchers in the same run root (preventing CPU cap breaches).
  2. Touch forbidden or unleased GPUs on shared multi-tenant servers.
  3. Exceed their leased CPU thread budget across concurrent workers.
  4. Silently abort long campaigns on transient API ``429`` / ``503`` rate limits.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from moldarwin.runtime.concurrency import plan_gpu_packing

COMPUTE_LEASE_SCHEMA = "moldarwin-compute-lease/1"
LEASE_AUDIT_SCHEMA = "moldarwin-lease-audit/1"
RETRY_BACKOFF_SCHEMA = "moldarwin-retry-backoff/1"

#: Default under-utilization warning cutoffs (Evidence: measured_here on 96 GB RTX PRO 6000
#: Blackwell where k=2 RBFE windows sat at ~40% SM / <2% VRAM before packing k=6 reached 77-88%).
DEFAULT_UNDERUTIL_SM_PCT: float = 50.0
DEFAULT_UNDERUTIL_VRAM_FRAC: float = 0.40

_TRANSIENT_ERROR_RE = re.compile(
    r"(429|too many requests|rate.?limit|502|503|504|service unavailable|overloaded|"
    r"temporarily unavailable|connection reset|timed out)",
    re.IGNORECASE,
)

T = TypeVar("T")


class LeaseConflictError(RuntimeError):
    """Raised when a second dispatcher attempts to acquire an active campaign compute lease."""


class LeaseViolationError(RuntimeError):
    """Raised when a worker launch requests forbidden GPUs, unleased GPUs, or excess CPUs."""


class ComputeLease:
    """Exclusive POSIX-locked GPU/CPU resource lease for one autonomous campaign run root."""

    def __init__(
        self,
        run_dir: str | Path,
        *,
        campaign_id: str,
        allowed_gpus: Sequence[int],
        forbidden_gpus: Sequence[int] = (),
        max_cpu_threads: int,
        cpu_offset_base: int = 0,
    ) -> None:
        self.run_dir = Path(run_dir).resolve()
        self.campaign_id = str(campaign_id).strip() or "campaign"
        self.allowed_gpus = tuple(sorted({int(g) for g in allowed_gpus}))
        self.forbidden_gpus = tuple(sorted({int(g) for g in forbidden_gpus}))
        self.max_cpu_threads = int(max_cpu_threads)
        self.cpu_offset_base = int(cpu_offset_base)

        if not self.allowed_gpus:
            raise LeaseViolationError("allowed_gpus must be non-empty")
        overlap = sorted(set(self.allowed_gpus) & set(self.forbidden_gpus))
        if overlap:
            raise LeaseViolationError(
                f"allowed_gpus intersects forbidden_gpus: {overlap}"
            )
        if self.max_cpu_threads < 1:
            raise LeaseViolationError("max_cpu_threads must be >= 1")
        if self.cpu_offset_base < 0:
            raise LeaseViolationError("cpu_offset_base must be >= 0")

        self.lock_path = self.run_dir / ".compute_lease.lock"
        self.manifest_path = self.run_dir / ".compute_lease.json"
        self._fd: int | None = None
        self._acquired_at: str | None = None
        self._active_workers: dict[str, dict[str, Any]] = {}

    @property
    def active_cpu_threads(self) -> int:
        return sum(int(w["cpu_threads"]) for w in self._active_workers.values())

    @property
    def is_acquired(self) -> bool:
        return self._fd is not None

    def acquire(self) -> ComputeLease:
        """Acquire exclusive non-blocking POSIX flock preventing duplicate dispatchers."""
        if self._fd is not None:
            return self
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise LeaseConflictError("ComputeLease requires POSIX fcntl.flock")
        import fcntl

        self.run_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise LeaseConflictError(f"lease lock is not a regular file: {self.lock_path}")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                holder = self._read_manifest_safe()
                holder_pid = holder.get("pid") if isinstance(holder, dict) else None
                raise LeaseConflictError(
                    f"duplicate dispatcher refused for {self.run_dir}: active lease held by "
                    f"pid={holder_pid!r} (lock={self.lock_path})"
                ) from exc
        except Exception:
            os.close(fd)
            raise

        self._fd = fd
        self._acquired_at = datetime.now(UTC).isoformat()
        self._write_manifest()
        return self

    def release(self) -> None:
        """Release the exclusive lock and clear active worker registrations."""
        if self._fd is None:
            return
        self._active_workers.clear()
        self._write_manifest(released=True)
        try:
            os.close(self._fd)
        finally:
            self._fd = None

    def __enter__(self) -> ComputeLease:
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()

    def _read_manifest_safe(self) -> dict[str, Any]:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_manifest(self, *, released: bool = False) -> None:
        payload = self.snapshot(released=released)
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.manifest_path)

    def snapshot(self, *, released: bool = False) -> dict[str, Any]:
        return {
            "schema": COMPUTE_LEASE_SCHEMA,
            "campaign_id": self.campaign_id,
            "run_dir": str(self.run_dir),
            "pid": os.getpid(),
            "acquired_at": self._acquired_at,
            "released": released,
            "allowed_gpus": list(self.allowed_gpus),
            "forbidden_gpus": list(self.forbidden_gpus),
            "max_cpu_threads": self.max_cpu_threads,
            "cpu_offset_base": self.cpu_offset_base,
            "active_cpu_threads": self.active_cpu_threads,
            "active_workers": dict(self._active_workers),
        }

    def validate_worker_launch(
        self,
        *,
        gpu_ids: Sequence[int],
        cpu_threads: int,
        worker_id: str | None = None,
    ) -> dict[str, str]:
        """Validate a worker launch against GPU allowlist, forbidden GPUs, and CPU thread cap.

        Returns the exact sanitized environment overrides (``CUDA_VISIBLE_DEVICES``,
        ``OMP_NUM_THREADS``) to inject into the subprocess.
        """
        if not self.is_acquired:
            raise LeaseConflictError("ComputeLease must be acquired before launching workers")
        req_gpus = [int(g) for g in gpu_ids]
        threads = int(cpu_threads)
        if threads < 1:
            raise LeaseViolationError(f"cpu_threads must be >= 1, got {threads}")

        bad_forbidden = sorted(set(req_gpus) & set(self.forbidden_gpus))
        if bad_forbidden:
            raise LeaseViolationError(
                f"worker {worker_id or '?'} requested forbidden GPU(s): {bad_forbidden}"
            )
        unleased = sorted(set(req_gpus) - set(self.allowed_gpus))
        if unleased:
            raise LeaseViolationError(
                f"worker {worker_id or '?'} requested unleased GPU(s): {unleased} "
                f"(allowed={list(self.allowed_gpus)})"
            )

        existing = self._active_workers.get(worker_id, {}).get("cpu_threads", 0) if worker_id else 0
        projected = self.active_cpu_threads - int(existing) + threads
        if projected > self.max_cpu_threads:
            raise LeaseViolationError(
                f"CPU thread cap breach prevented for worker {worker_id or '?'}: "
                f"projected {projected} > lease max {self.max_cpu_threads}"
            )

        env = {"OMP_NUM_THREADS": str(threads)}
        if req_gpus:
            env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in req_gpus)
        else:
            env["CUDA_VISIBLE_DEVICES"] = ""
        return env

    def register_worker(
        self,
        worker_id: str,
        *,
        gpu_ids: Sequence[int],
        cpu_threads: int,
        pid: int | None = None,
    ) -> dict[str, str]:
        """Validate and register an active worker slot under the lease."""
        env = self.validate_worker_launch(
            gpu_ids=gpu_ids,
            cpu_threads=cpu_threads,
            worker_id=worker_id,
        )
        self._active_workers[worker_id] = {
            "gpu_ids": [int(g) for g in gpu_ids],
            "cpu_threads": int(cpu_threads),
            "pid": int(pid) if pid is not None else None,
            "registered_at": datetime.now(UTC).isoformat(),
        }
        self._write_manifest()
        return env

    def release_worker(self, worker_id: str) -> None:
        if worker_id in self._active_workers:
            del self._active_workers[worker_id]
            self._write_manifest()

    def plan_packed_slots(
        self,
        *,
        mem_per_job_mb: float = 1024.0,
        gpu_vram_mb: float = 98304.0,
        jobs_per_gpu: int | None = None,
        single_job_sm_util_pct: float | None = None,
        min_omp_per_job: int = 2,
        max_omp_per_job: int = 12,
        max_jobs_per_gpu: int = 8,
        reserve_os_cores: int = 0,
    ) -> dict[str, Any]:
        """Compute disjoint CPU-pinned packing slots guaranteed to fit strictly inside this lease."""
        return plan_gpu_packing(
            idle_gpus=self.allowed_gpus,
            cpu_cores=self.max_cpu_threads,
            jobs_per_gpu=jobs_per_gpu,
            mem_per_job_mb=mem_per_job_mb,
            gpu_vram_mb=gpu_vram_mb,
            min_omp_per_job=min_omp_per_job,
            max_omp_per_job=max_omp_per_job,
            single_job_sm_util_pct=single_job_sm_util_pct,
            reserve_os_cores=reserve_os_cores,
            max_jobs_per_gpu=max_jobs_per_gpu,
            forbidden_gpus=self.forbidden_gpus,
            cpu_offset_base=self.cpu_offset_base,
        )

    def audit_telemetry(
        self,
        *,
        campaign_gpu_pids: Mapping[int, Sequence[int]],
        configured_cpu_threads: int,
        active_dispatchers: int = 1,
        gpu_util_by_id: Mapping[int, float] | None = None,
        gpu_vram_frac_by_id: Mapping[int, float] | None = None,
    ) -> dict[str, Any]:
        """Audit live telemetry against this lease; flags blocking breaches and packing waste."""
        violations: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if int(active_dispatchers) > 1:
            violations.append({
                "code": "duplicate_dispatcher",
                "severity": "block",
                "detail": f"observed {active_dispatchers} active dispatchers (max 1 permitted)",
            })

        if int(configured_cpu_threads) > self.max_cpu_threads:
            violations.append({
                "code": "cpu_cap_breach",
                "severity": "block",
                "detail": (
                    f"configured_cpu_threads={configured_cpu_threads} exceeds "
                    f"lease max_cpu_threads={self.max_cpu_threads}"
                ),
            })

        for raw_gpu, pids in sorted(campaign_gpu_pids.items()):
            gid = int(raw_gpu)
            pid_list = [int(p) for p in pids]
            if not pid_list:
                continue
            if gid in self.forbidden_gpus:
                violations.append({
                    "code": "forbidden_gpu_occupied",
                    "severity": "block",
                    "gpu_id": gid,
                    "pids": pid_list,
                    "detail": f"campaign PID(s) {pid_list} observed on forbidden GPU {gid}",
                })
            elif gid not in self.allowed_gpus:
                violations.append({
                    "code": "unleased_gpu_occupied",
                    "severity": "block",
                    "gpu_id": gid,
                    "pids": pid_list,
                    "detail": f"campaign PID(s) {pid_list} observed on unleased GPU {gid}",
                })

        if gpu_util_by_id:
            for gid in self.allowed_gpus:
                if gid not in gpu_util_by_id:
                    continue
                if not campaign_gpu_pids.get(gid):
                    continue
                util = float(gpu_util_by_id[gid])
                vram_frac = (
                    float(gpu_vram_frac_by_id[gid])
                    if gpu_vram_frac_by_id and gid in gpu_vram_frac_by_id
                    else 0.0
                )
                if util < DEFAULT_UNDERUTIL_SM_PCT and vram_frac < DEFAULT_UNDERUTIL_VRAM_FRAC:
                    warnings.append({
                        "code": "gpu_under_utilized",
                        "severity": "warn",
                        "gpu_id": gid,
                        "gpu_util_pct": round(util, 1),
                        "vram_fraction": round(vram_frac, 4),
                        "detail": (
                            f"active leased GPU {gid} at {util:.1f}% SM / {vram_frac * 100:.1f}% VRAM; "
                            "consider increasing jobs_per_gpu via plan_packed_slots."
                        ),
                    })

        return {
            "schema": LEASE_AUDIT_SCHEMA,
            "campaign_id": self.campaign_id,
            "compliant": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "thresholds": {
                "underutil_sm_pct": DEFAULT_UNDERUTIL_SM_PCT,
                "underutil_vram_frac": DEFAULT_UNDERUTIL_VRAM_FRAC,
                "evidence": "measured_here_and_convention",
            },
        }


@dataclass(frozen=True, slots=True)
class RetryBackoffPolicy:
    """Explicit, auditable exponential backoff for transient API rate-limit failures."""

    max_attempts: int = 5
    initial_delay_s: float = 60.0
    backoff_factor: float = 2.0
    max_delay_s: float = 600.0

    def delay_for_attempt(self, attempt_number: int) -> float:
        """Compute bounded delay (seconds) after failed 1-indexed ``attempt_number``."""
        exp = max(0, int(attempt_number) - 1)
        return float(min(self.max_delay_s, self.initial_delay_s * (self.backoff_factor**exp)))


def is_transient_rate_limit_error(error: BaseException | str) -> bool:
    """Return True if an exception or stderr snippet reflects transient 429/5xx throttling."""
    return bool(_TRANSIENT_ERROR_RE.search(str(error)))


def run_with_backoff(
    fn: Callable[[], T],
    *,
    policy: RetryBackoffPolicy | None = None,
    is_retryable: Callable[[BaseException], bool] = is_transient_rate_limit_error,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[T, dict[str, Any]]:
    """Run ``fn`` with visible retry accounting (retries are counted, never hidden)."""
    cfg = policy or RetryBackoffPolicy()
    if cfg.max_attempts < 1:
        raise ValueError("policy.max_attempts must be >= 1")

    attempts_log: list[dict[str, Any]] = []
    for attempt in range(1, cfg.max_attempts + 1):
        try:
            result = fn()
            return result, {
                "schema": RETRY_BACKOFF_SCHEMA,
                "succeeded": True,
                "attempts_used": attempt,
                "retries": attempt - 1,
                "history": attempts_log,
            }
        except BaseException as exc:  # noqa: BLE001
            retryable = bool(is_retryable(exc))
            entry: dict[str, Any] = {
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
                "retryable": retryable,
            }
            if not retryable or attempt >= cfg.max_attempts:
                entry["sleep_s"] = 0.0
                attempts_log.append(entry)
                raise
            delay = cfg.delay_for_attempt(attempt)
            entry["sleep_s"] = delay
            attempts_log.append(entry)
            sleep_fn(delay)

    raise AssertionError("unreachable")  # pragma: no cover


__all__ = [
    "COMPUTE_LEASE_SCHEMA",
    "DEFAULT_UNDERUTIL_SM_PCT",
    "DEFAULT_UNDERUTIL_VRAM_FRAC",
    "LEASE_AUDIT_SCHEMA",
    "RETRY_BACKOFF_SCHEMA",
    "ComputeLease",
    "LeaseConflictError",
    "LeaseViolationError",
    "RetryBackoffPolicy",
    "is_transient_rate_limit_error",
    "run_with_backoff",
]
