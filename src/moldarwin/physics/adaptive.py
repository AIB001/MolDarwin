"""Self-healing adaptive physics solver helpers for GROMACS 2026 RBFE/FEP.

Closes the manual intervention gap observed between Run 5 (11 windows -> overlap 0.00168)
and Run 6 (20 windows -> overlap 0.0448):
  1. ``refine_lambda_schedule_from_overlap``: allocates new intermediate lambda states
     strictly in low-overlap intervals proportional to thermodynamic-length density
     ``-ln(O_{i,i+1})``.
  2. ``plan_selective_window_extensions``: identifies only unconverged windows (time-block
     drift or high variance) for ``gmx convert-tpr -extend`` + ``-cpi`` continuation.
  3. ``render_packed_fep_runner``: emits a disjoint-``-pinoffset`` multi-window-per-GPU
     (``k=2-3``) GROMACS 2026 launcher saturating high-VRAM GPUs to 75-90% SM utilization.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ADAPTIVE_LAMBDA_SCHEMA = "moldarwin-adaptive-lambda/1"
WINDOW_EXTENSION_SCHEMA = "moldarwin-fep-window-extensions/1"
PACKED_FEP_RUNNER_SCHEMA = "moldarwin-packed-fep-runner/1"

#: Target minimum adjacent MBAR overlap (Evidence: literature / convention, Klimovich et al. 2015).
DEFAULT_TARGET_ADJACENT_OVERLAP: float = 0.05
DEFAULT_MAX_HALF_DELTA_KCAL: float = 0.50


def refine_lambda_schedule_from_overlap(
    lambdas: Sequence[float],
    adjacent_overlaps: Sequence[float],
    *,
    min_overlap: float = DEFAULT_TARGET_ADJACENT_OVERLAP,
    max_new_windows: int = 12,
    min_gap: float = 1e-4,
) -> dict[str, Any]:
    """Insert intermediate lambda windows exactly where adjacent MBAR overlap falls short.

    Uses logarithmic overlap deficit ``w_i = max(0, ln(min_overlap / max(O_i, 1e-12)))``
    so sparse intervals (e.g. endpoints ``0.00 -> 0.05``) receive proportionally more
    intermediate points while well-overlapping intervals are left untouched.
    """
    lams = [float(x) for x in lambdas]
    ovs = [float(x) for x in adjacent_overlaps]
    if len(lams) < 2 or len(ovs) != len(lams) - 1:
        raise ValueError("adjacent_overlaps must have length len(lambdas) - 1")
    if any(lams[i] >= lams[i + 1] for i in range(len(lams) - 1)):
        raise ValueError("lambdas must be strictly increasing")
    if min_overlap <= 0.0 or min_overlap >= 1.0:
        raise ValueError("min_overlap must lie in (0, 1)")

    deficits: list[tuple[int, float]] = []
    for idx, ov in enumerate(ovs):
        if ov < min_overlap and (lams[idx + 1] - lams[idx]) > 2.0 * min_gap:
            clamped = max(ov, 1e-12)
            # Each halving of gap roughly doubles/squares overlap; log ratio estimates needed subdivisions.
            weight = math.log(min_overlap / clamped)
            deficits.append((idx, max(weight, 0.1)))

    if not deficits:
        return {
            "schema": ADAPTIVE_LAMBDA_SCHEMA,
            "converged": True,
            "original_count": len(lams),
            "new_count": len(lams),
            "added_windows": 0,
            "worst_adjacent_overlap": round(min(ovs), 6),
            "target_min_overlap": min_overlap,
            "refined_lambdas": [round(x, 5) for x in lams],
            "insertions_by_interval": {},
        }

    # Allocate at least 1 new point per failing interval (up to max_new_windows),
    # then distribute extra points proportionally to log-overlap deficit.
    deficits.sort(key=lambda pair: pair[1], reverse=True)
    selected = deficits[:max_new_windows]
    alloc: dict[int, int] = {idx: 1 for idx, _ in selected}
    budget_left = max(0, max_new_windows - len(selected))

    if budget_left > 0:
        # Cap extra points so we don't over-insert into a mildly deficient interval.
        desired_extra: dict[int, int] = {}
        for idx, w in selected:
            # Roughly 1 extra window per ~2.3 nats (10x overlap gap), capped at 4 per interval.
            want = min(4, max(0, int(math.floor(w / 2.3))))
            desired_extra[idx] = want
        while budget_left > 0 and any(v > 0 for v in desired_extra.values()):
            for idx, _ in selected:
                if budget_left <= 0:
                    break
                if desired_extra[idx] > 0:
                    alloc[idx] += 1
                    desired_extra[idx] -= 1
                    budget_left -= 1

    refined: list[float] = []
    insertions_report: dict[str, list[float]] = {}
    for idx in range(len(lams) - 1):
        lo, hi = lams[idx], lams[idx + 1]
        refined.append(round(lo, 5))
        n_ins = alloc.get(idx, 0)
        if n_ins > 0:
            step = (hi - lo) / (n_ins + 1)
            pts = [round(lo + step * k, 5) for k in range(1, n_ins + 1)]
            refined.extend(pts)
            insertions_report[f"{idx}->{idx + 1} (ov={ovs[idx]:.5f})"] = pts
    refined.append(round(lams[-1], 5))

    return {
        "schema": ADAPTIVE_LAMBDA_SCHEMA,
        "converged": False,
        "original_count": len(lams),
        "new_count": len(refined),
        "added_windows": len(refined) - len(lams),
        "worst_adjacent_overlap": round(min(ovs), 6),
        "target_min_overlap": min_overlap,
        "refined_lambdas": refined,
        "insertions_by_interval": insertions_report,
    }


def plan_selective_window_extensions(
    window_reports: Sequence[Mapping[str, Any]],
    *,
    max_half_delta_kcal: float = DEFAULT_MAX_HALF_DELTA_KCAL,
    max_uncertainty_kcal: float = 0.25,
    extend_ns: float = 1.0,
    max_total_ns: float = 6.0,
) -> dict[str, Any]:
    """Select ONLY unconverged lambda windows for targeted ``-cpi`` continuation.

    Avoids wasting GPU-hours extending already-converged windows. Each item in
    ``window_reports`` needs ``window_id`` and ``current_ns``, plus optional
    ``half_delta_kcal``, ``uncertainty_kcal``, ``min_neighbor_overlap``.
    """
    to_extend: list[dict[str, Any]] = []
    converged: list[str] = []
    at_cap: list[str] = []

    for row in window_reports:
        wid = str(row["window_id"])
        cur_ns = float(row.get("current_ns") or 0.0)
        reasons: list[str] = []
        hd = row.get("half_delta_kcal")
        unc = row.get("uncertainty_kcal")
        if hd is not None and abs(float(hd)) > max_half_delta_kcal:
            reasons.append(f"|half_delta|={abs(float(hd)):.3f}>{max_half_delta_kcal}")
        if unc is not None and float(unc) > max_uncertainty_kcal:
            reasons.append(f"unc={float(unc):.3f}>{max_uncertainty_kcal}")

        if not reasons:
            converged.append(wid)
            continue
        if cur_ns >= max_total_ns:
            at_cap.append(wid)
            continue

        add_ns = min(extend_ns, round(max_total_ns - cur_ns, 3))
        to_extend.append({
            "window_id": wid,
            "current_ns": cur_ns,
            "extend_by_ns": add_ns,
            "target_ns": round(cur_ns + add_ns, 3),
            "reasons": reasons,
            "gmx_convert_tpr_arg": f"-extend {int(round(add_ns * 1000.0))}",
        })

    return {
        "schema": WINDOW_EXTENSION_SCHEMA,
        "total_windows": len(window_reports),
        "converged_count": len(converged),
        "extend_count": len(to_extend),
        "at_cap_count": len(at_cap),
        "windows_to_extend": to_extend,
        "converged_windows": converged,
        "at_cap_windows": at_cap,
        "thresholds": {
            "max_half_delta_kcal": max_half_delta_kcal,
            "max_uncertainty_kcal": max_uncertainty_kcal,
            "max_total_ns": max_total_ns,
            "evidence": "convention",
        },
    }


def render_packed_fep_runner(
    leg_dir: str | Path,
    packing_plan: Mapping[str, Any],
    *,
    gmx_bin: str = "gmx",
    update_mode: str = "gpu",
    out_script: str | Path | None = None,
) -> dict[str, Any]:
    """Emit a disjoint-``-pinoffset`` multi-window-per-GPU GROMACS 2026 FEP runner script.

    Saturates high-VRAM GPUs (e.g. 2-3 concurrent FEP windows per RTX PRO 6000) using the
    exact slot table from :func:`moldarwin.runtime.concurrency.plan_gpu_packing` so
    packed windows never contend for CPU cores.
    """
    root = Path(leg_dir).resolve()
    slots = list(packing_plan.get("slots") or [])
    if not slots:
        raise ValueError("packing_plan must contain at least one slot")

    gpu_list = " ".join(str(s["gpu_id"]) for s in slots)
    omp_list = " ".join(str(s["ntomp"]) for s in slots)
    pin_list = " ".join(str(s["pinoffset"]) for s in slots)
    upd_flag = f"-update {update_mode}" if update_mode in {"gpu", "cpu"} else ""

    script = f"""#!/usr/bin/env bash
set -euo pipefail
# Generated by MolDarwin physics.adaptive (multi-window GPU-packed GROMACS 2026 FEP runner)
LEG_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
GMX="${{GMX_BIN:-{gmx_bin}}}"
export GMX_MAXBACKUP=-1

SLOT_GPUS=({gpu_list})
SLOT_OMPS=({omp_list})
SLOT_PINS=({pin_list})
NUM_SLOTS=${{#SLOT_GPUS[@]}}
LOCK_DIR="${{LEG_DIR}}/.slot_locks"
mkdir -p "$LOCK_DIR"

acquire_slot() {{
  while true; do
    for ((i=0; i<NUM_SLOTS; i++)); do
      if mkdir "$LOCK_DIR/slot_$i" 2>/dev/null; then
        echo "$i"
        return 0
      fi
    done
    sleep 0.5
  done
}}

run_window_on_slot() {{
  local win_mdp="$1"
  local slot="$2"
  trap 'rmdir "$LOCK_DIR/slot_'"$slot"'" 2>/dev/null || true' EXIT

  local gpu="${{SLOT_GPUS[$slot]}}"
  local ntomp="${{SLOT_OMPS[$slot]}}"
  local pin="${{SLOT_PINS[$slot]}}"
  local wname
  wname="$(basename "$win_mdp" .mdp)"
  local widx="${{wname#prod_}}"
  local wdir="${{LEG_DIR}}/window_${{widx}}"
  mkdir -p "$wdir"

  export CUDA_VISIBLE_DEVICES="$gpu"
  export OMP_NUM_THREADS="$ntomp"

  if [ ! -f "$wdir/em_short.gro" ]; then
    "$GMX" grompp -f "${{LEG_DIR}}/mdps/em_short_${{widx}}.mdp" -c "${{LEG_DIR}}/build/npt.gro" -r "${{LEG_DIR}}/build/npt.gro" -p "${{LEG_DIR}}/topol.top" -o "$wdir/em_short.tpr" -maxwarn 20
    "$GMX" mdrun -deffnm "$wdir/em_short" -ntmpi 1 -ntomp "$ntomp" -nb gpu -pme cpu -pin on -pinoffset "$pin" -pinstride 1
  fi
  if [ ! -f "$wdir/npt_short.gro" ]; then
    "$GMX" grompp -f "${{LEG_DIR}}/mdps/npt_short_${{widx}}.mdp" -c "$wdir/em_short.gro" -r "$wdir/em_short.gro" -p "${{LEG_DIR}}/topol.top" -o "$wdir/npt_short.tpr" -maxwarn 20
    "$GMX" mdrun -deffnm "$wdir/npt_short" -ntmpi 1 -ntomp "$ntomp" -nb gpu -bonded gpu -pme gpu {upd_flag} -pin on -pinoffset "$pin" -pinstride 1
  fi
  if [ ! -f "$wdir/prod.gro" ]; then
    if [ ! -f "$wdir/prod.tpr" ]; then
      "$GMX" grompp -f "$win_mdp" -c "$wdir/npt_short.gro" -p "${{LEG_DIR}}/topol.top" -o "$wdir/prod.tpr" -maxwarn 20
    fi
    if [ -f "$wdir/prod.cpt" ]; then
      "$GMX" mdrun -deffnm "$wdir/prod" -cpi "$wdir/prod.cpt" -ntmpi 1 -ntomp "$ntomp" -nb gpu -bonded gpu -pme gpu {upd_flag} -pin on -pinoffset "$pin" -pinstride 1
    else
      "$GMX" mdrun -deffnm "$wdir/prod" -ntmpi 1 -ntomp "$ntomp" -nb gpu -bonded gpu -pme gpu {upd_flag} -pin on -pinoffset "$pin" -pinstride 1
    fi
  fi
}}

PIDS=()
for win_mdp in "${{LEG_DIR}}"/mdps/prod_*.mdp; do
  slot="$(acquire_slot)"
  run_window_on_slot "$win_mdp" "$slot" &
  PIDS+=($!)
done

FAIL=0
for pid in "${{PIDS[@]}}"; do
  if ! wait "$pid"; then
    FAIL=1
  fi
done
rm -rf "$LOCK_DIR"
exit "$FAIL"
"""
    dest = Path(out_script).resolve() if out_script is not None else (root / "run_prod_packed_gmx2026.sh")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(script, encoding="utf-8")
    dest.chmod(0o755)
    return {
        "schema": PACKED_FEP_RUNNER_SCHEMA,
        "leg_dir": str(root),
        "script_path": str(dest),
        "total_slots": len(slots),
        "jobs_per_gpu": packing_plan.get("jobs_per_gpu"),
        "update_mode": update_mode,
    }
