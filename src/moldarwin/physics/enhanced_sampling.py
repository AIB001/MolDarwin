"""First-principles thermodynamic-length geodesic scheduling, Metropolized-Gibbs expanded
ensemble (Chodera & Shirts 2011), and outlier-aware robust FEP network inference.

Addresses the fundamental statistical-physics bottlenecks uncovered in live TYK2 RBFE runs:
  1. **Thermodynamic-Length Geodesic Scheduling** (``optimize_lambda_geodesic``):
     Replaces heuristic window patching with Cauchy-Schwarz variance-optimal arc-length
     inversion ``lambda_k = L^{-1}(k / (K-1) * L_tot)`` over the Riemannian thermodynamic
     metric ``dL_i = sqrt(-ln(max(O_i, eps)))``, 4-decimal rounded to match GROMACS ``.xvg``.
  2. **MBAR-Warm-Started Bidirectional Metropolized-Gibbs Expanded Ensemble**
     (``interpolate_lambda_weights``, ``build_expanded_ensemble_mdp``,
     ``analyze_expanded_ensemble_convergence``):
     Runs natively on stock ``thread_mpi`` GROMACS 2026 (zero OpenMPI compilation needed)
     using ``integrator = md-vv``, ``free-energy = expanded``, and
     ``lmc-move = metropolized-gibbs`` — which Chodera & Shirts (2011) proved achieves
     strictly faster spectral mixing than nearest-neighbor Metropolis HREX. Warm-starts
     ``init-lambda-weights`` directly from prior MBAR free energies ``f_k`` (in ``k_B T``)
     and seeds half the walkers from state A (``lambda=0``) and half from state B
     (``lambda=1``) to measure exact bidirectional initial-condition memory erasure.
  3. **All-Information Robust Graph Inference** (``solve_robust_fep_network``):
     Combines MBAR asymptotic SE, temporal half-block drift, low-overlap deficit, and
     minimum uncorrelated sample count into honest effective edge variances and runs IRLS
     Huber robust MLE to prevent a single kinetically trapped edge from corrupting the
     entire network while explicitly flagging outlier edges for enhanced-sampling escalation.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

GEODESIC_SCHEDULE_SCHEMA = "moldarwin-geodesic-lambda/1"
EE_CONVERGENCE_SCHEMA = "moldarwin-expanded-ensemble-convergence/1"
ROBUST_NETWORK_SCHEMA = "moldarwin-robust-fep-network/1"
ESCALATION_PLAN_SCHEMA = "moldarwin-sampling-escalation/1"


def optimize_lambda_geodesic(
    lambdas: Sequence[float],
    adjacent_overlaps: Sequence[float],
    *,
    n_windows: int = 24,
    floor_overlap: float = 1e-6,
    min_spacing: float = 0.001,
) -> dict[str, Any]:
    """Compute the Riemannian thermodynamic-length equidistant (geodesic) lambda schedule.

    Given an existing schedule ``lambdas`` and observed bidirectional adjacent MBAR
    overlaps ``O_i`` on each interval ``[lambda_i, lambda_{i+1}]``, estimates the interval
    thermodynamic length ``dL_i = sqrt(max(-ln(max(O_i, floor_overlap)), 1e-6))`` and
    analytically inverts the cumulative arc-length ``L(lambda)`` so all ``n_windows - 1``
    new intervals carry equal thermodynamic length (minimizing total MBAR variance by
    Cauchy-Schwarz). All returned points are strictly increasing and rounded to 4 decimals
    to match GROMACS ``.xvg`` column headers identically.
    """
    lams = [float(x) for x in lambdas]
    ovs = [float(x) for x in adjacent_overlaps]
    if len(lams) < 2 or len(ovs) != len(lams) - 1:
        raise ValueError("adjacent_overlaps must have length len(lambdas) - 1")
    if any(lams[i] >= lams[i + 1] for i in range(len(lams) - 1)):
        raise ValueError("lambdas must be strictly increasing")
    if n_windows < 2:
        raise ValueError("n_windows must be >= 2")

    dl: list[float] = []
    cum_l: list[float] = [0.0]
    for ov in ovs:
        clamped = min(max(ov, floor_overlap), 1.0 - 1e-9)
        seg = math.sqrt(max(-math.log(clamped), 1e-6))
        dl.append(seg)
        cum_l.append(cum_l[-1] + seg)

    total_l = cum_l[-1]
    targets = [total_l * k / (n_windows - 1) for k in range(n_windows)]

    raw_new: list[float] = [lams[0]]
    seg_idx = 0
    for t in targets[1:-1]:
        while seg_idx < len(dl) - 1 and cum_l[seg_idx + 1] < t:
            seg_idx += 1
        span = max(cum_l[seg_idx + 1] - cum_l[seg_idx], 1e-12)
        frac = min(max((t - cum_l[seg_idx]) / span, 0.0), 1.0)
        val = lams[seg_idx] + frac * (lams[seg_idx + 1] - lams[seg_idx])
        raw_new.append(val)
    raw_new.append(lams[-1])

    # Round to 4 decimals matching GROMACS .xvg while preserving strict monotonicity
    rounded: list[float] = [round(raw_new[0], 4)]
    for idx in range(1, len(raw_new) - 1):
        v = round(raw_new[idx], 4)
        lo_bound = round(rounded[-1] + min_spacing, 4)
        hi_bound = round(raw_new[-1] - min_spacing * (len(raw_new) - 1 - idx), 4)
        v = min(max(v, lo_bound), hi_bound)
        rounded.append(round(v, 4))
    rounded.append(round(raw_new[-1], 4))

    # Predicted uniform adjacent overlap after equidistant re-parameterization: exp(-(L_tot/(K-1))^2)
    step_l = total_l / (n_windows - 1)
    predicted_uniform_overlap = math.exp(-(step_l ** 2))

    return {
        "schema": GEODESIC_SCHEDULE_SCHEMA,
        "original_windows": len(lams),
        "new_windows": len(rounded),
        "total_thermodynamic_length": round(total_l, 4),
        "target_segment_length": round(step_l, 4),
        "original_worst_overlap": round(min(ovs), 6),
        "predicted_uniform_overlap": round(predicted_uniform_overlap, 4),
        "geodesic_lambdas": rounded,
        "interval_lengths": [round(x, 4) for x in dl],
    }


def interpolate_lambda_weights(
    old_lambdas: Sequence[float],
    old_free_energies_kt: Sequence[float],
    new_lambdas: Sequence[float],
) -> list[float]:
    """Interpolate MBAR free-energy profile ``f_k`` (in ``k_B T``) onto ``new_lambdas``.

    In GROMACS expanded ensemble, ``P(k) ~ exp(-f_k + w_k)``; setting ``w_k = +f_k``
    (anchored with ``w_0 = 0.0``) warm-starts Metropolized-Gibbs near flat-histogram
    equilibrium at ``t = 0``, eliminating slow Wang-Landau burn-in.
    """
    if len(old_lambdas) != len(old_free_energies_kt) or len(old_lambdas) < 2:
        raise ValueError("old_lambdas and old_free_energies_kt must match and have length >= 2")
    ox = [float(x) for x in old_lambdas]
    oy = [float(y) - float(old_free_energies_kt[0]) for y in old_free_energies_kt]

    weights: list[float] = []
    for x in new_lambdas:
        xf = float(x)
        if xf <= ox[0]:
            w = oy[0]
        elif xf >= ox[-1]:
            w = oy[-1]
        else:
            idx = 0
            while idx < len(ox) - 2 and ox[idx + 1] < xf:
                idx += 1
            frac = (xf - ox[idx]) / max(ox[idx + 1] - ox[idx], 1e-12)
            w = oy[idx] + frac * (oy[idx + 1] - oy[idx])
        weights.append(round(w, 4))
    base = weights[0]
    return [round(w - base, 4) for w in weights]


def build_expanded_ensemble_mdp(
    base_mdp_text: str,
    *,
    lambdas: Sequence[float],
    init_lambda_state: int,
    init_weights_kt: Sequence[float] | None = None,
    nsteps: int,
    mode: str = "prod_fixed",
    lmc_seed: int = 20261127,
    nstexpanded: int = 100,
    init_wl_delta: float = 0.25,
    weight_equil_wl_delta: float = 0.02,
    nstxout_compressed: int = 0,
) -> str:
    """Build a GROMACS 2026 ``md-vv`` Metropolized-Gibbs expanded-ensemble MDP.

    Supports two clean modes:
      - ``"equil_wl"``: short Wang-Landau polish starting from MBAR warm-start weights
        (``init-wl-delta = 0.25``, freezing when ``wl-delta <= weight_equil_wl_delta``).
      - ``"prod_fixed"``: strictly stationary fixed-weight (``lmc-stats = no``)
        Metropolized-Gibbs production guaranteeing exact Boltzmann detailed balance for MBAR.
    """
    if mode not in {"equil_wl", "prod_fixed"}:
        raise ValueError(f"mode must be 'equil_wl' or 'prod_fixed', got {mode!r}")
    n_win = len(lambdas)
    if not (0 <= init_lambda_state < n_win):
        raise ValueError(f"init_lambda_state={init_lambda_state} out of range [0, {n_win - 1}]")
    if init_weights_kt is not None and len(init_weights_kt) != n_win:
        raise ValueError("init_weights_kt must have same length as lambdas")

    lam_str = " ".join(f"{float(v):.4f}" for v in lambdas)
    w_list = [float(w) for w in init_weights_kt] if init_weights_kt is not None else [0.0] * n_win
    w_str = " ".join(f"{w:.4f}" for w in w_list)

    # Strip any prior expanded-ensemble directives so regeneration is idempotent
    drop_keys = {
        "nstexpanded", "lmc-stats", "lmc-move", "lmc-seed", "init-wl-delta",
        "wl-scale", "wl-ratio", "lmc-weights-equil", "weight-equil-wl-delta",
        "init-lambda-weights", "ns_type",
    }
    kept_lines: list[str] = []
    for line in base_mdp_text.splitlines():
        key = line.split("=", 1)[0].strip().lower() if "=" in line and not line.strip().startswith(";") else ""
        if key in drop_keys:
            continue
        kept_lines.append(line)
    txt = "\n".join(kept_lines)

    replacements = {
        "integrator": "md-vv",
        "tcoupl": "v-rescale",
        "pcoupl": "C-rescale",
        "free-energy": "expanded",
        "nsteps": str(int(nsteps)),
        "init-lambda-state": str(int(init_lambda_state)),
        "calc-lambda-neighbors": "-1",
        "nstcalcenergy": str(int(nstexpanded)),
        "nstxout": "0",
        "nstvout": "0",
        "nstfout": "0",
        "nstxout-compressed": str(int(nstxout_compressed)),
        "coul-lambdas": lam_str,
        "vdw-lambdas": lam_str,
        "bonded-lambdas": lam_str,
        "mass-lambdas": lam_str,
    }
    for key, val in replacements.items():
        pat = rf"(?im)^(\s*{re.escape(key)}\s*=\s*).*$"
        if re.search(pat, txt):
            txt = re.sub(pat, rf"\g<1>{val}", txt)
        else:
            txt += f"\n{key:24s} = {val}"

    ee_block = [
        "",
        "; MolDarwin Metropolized-Gibbs Expanded Ensemble (Chodera & Shirts 2011)",
        f"nstexpanded              = {int(nstexpanded)}",
        "lmc-move                 = metropolized-gibbs",
        f"lmc-seed                 = {int(lmc_seed)}",
        f"init-lambda-weights      = {w_str}",
    ]
    if mode == "equil_wl":
        ee_block.extend([
            "lmc-stats                = wang-landau",
            f"init-wl-delta            = {float(init_wl_delta):.4f}",
            "wl-scale                 = 0.8",
            "wl-ratio                 = 0.8",
            "lmc-weights-equil        = wl-delta",
            f"weight-equil-wl-delta    = {float(weight_equil_wl_delta):.4f}",
        ])
    else:
        ee_block.append("lmc-stats                = no")

    return txt.rstrip() + "\n" + "\n".join(ee_block) + "\n"


def parse_final_mc_lambda_weights(log_text: str, n_states: int) -> list[float]:
    """Extract the final Wang-Landau ``Wang-Landau`` / ``MC-lambda`` weight vector from a GROMACS log."""
    blocks = log_text.split("MC-lambda information")
    if len(blocks) < 2:
        raise ValueError("no MC-lambda information block found in GROMACS log")
    for block in reversed(blocks[1:]):
        weights: dict[int, float] = {}
        for line in block.splitlines():
            # GROMACS table rows: "    1   0.0000  0.0000  0.0000  0.0000    123    0.00000  <<"
            m = re.match(r"^\s*(\d+)\s+(?:[-0-9.]+\s+){1,6}?(\d+)\s+([-0-9.]+)\s*(?:<<)?\s*$", line)
            if m:
                idx = int(m.group(1)) - 1  # GROMACS prints 1-based state index in MC-lambda table
                if 0 <= idx < n_states:
                    weights[idx] = float(m.group(3))
        if len(weights) == n_states:
            base = weights[0]
            return [round(weights[i] - base, 4) for i in range(n_states)]
    raise ValueError(f"could not parse complete {n_states}-state MC-lambda weights from log")


def analyze_expanded_ensemble_convergence(
    state_trajectories: Sequence[Sequence[int]],
    n_states: int,
    *,
    dg_a_seeded_kcal: float | None = None,
    dg_b_seeded_kcal: float | None = None,
    max_bidirectional_gap_kcal: float = 0.50,
) -> dict[str, Any]:
    """Audit end-to-end round-trips, visitation flatness, and A-vs-B memory erasure."""
    if n_states < 2:
        raise ValueError("n_states must be >= 2")
    counts = [0] * n_states
    total_round_trips = 0
    per_walker_rt: list[int] = []

    for traj in state_trajectories:
        last_end: int | None = None
        half_trips = 0
        for st in traj:
            idx = int(st)
            if 0 <= idx < n_states:
                counts[idx] += 1
            if idx == 0:
                if last_end == n_states - 1:
                    half_trips += 1
                last_end = 0
            elif idx == n_states - 1:
                if last_end == 0:
                    half_trips += 1
                last_end = n_states - 1
        rt = half_trips // 2
        per_walker_rt.append(rt)
        total_round_trips += rt

    sorted_c = sorted(counts)
    med = sorted_c[n_states // 2]
    min_c = sorted_c[0]
    flatness = round(min_c / max(med, 1), 4)
    all_states_visited = min_c > 0

    bidir_gap: float | None = None
    memory_erased: bool | None = None
    if dg_a_seeded_kcal is not None and dg_b_seeded_kcal is not None:
        bidir_gap = round(abs(float(dg_a_seeded_kcal) - float(dg_b_seeded_kcal)), 4)
        memory_erased = bidir_gap <= max_bidirectional_gap_kcal

    return {
        "schema": EE_CONVERGENCE_SCHEMA,
        "n_walkers": len(state_trajectories),
        "n_states": n_states,
        "total_round_trips": total_round_trips,
        "per_walker_round_trips": per_walker_rt,
        "min_state_count": min_c,
        "median_state_count": med,
        "flatness_min_over_median": flatness,
        "all_states_visited": all_states_visited,
        "bidirectional_gap_kcal": bidir_gap,
        "memory_erased": memory_erased,
        "max_bidirectional_gap_kcal": max_bidirectional_gap_kcal,
    }


def solve_robust_fep_network(
    edges: Sequence[Mapping[str, Any]],
    *,
    anchor_ligand: str,
    huber_delta_kcal: float = 0.80,
    outlier_residual_kcal: float = 1.00,
    max_iters: int = 30,
) -> dict[str, Any]:
    """All-information IRLS Huber robust MLE over an RBFE perturbation graph.

    Inflates each edge's asymptotic MBAR variance honestly using temporal half-block drift,
    low-overlap deficit, and minimum uncorrelated sample count, then solves Huber-weighted
    least squares so a kinetically trapped edge cannot silently corrupt the network and is
    explicitly flagged as an outlier for enhanced-sampling escalation.
    """
    import numpy as np

    valid = [
        e for e in edges
        if e.get("status", "ok") == "ok"
        and e.get("ddg_kcal_mol") is not None
        and math.isfinite(float(e["ddg_kcal_mol"]))
    ]
    if not valid:
        raise ValueError("no valid edges supplied")

    all_nodes = sorted({str(e["from_id"]) for e in valid} | {str(e["to_id"]) for e in valid})
    if anchor_ligand not in all_nodes:
        raise ValueError(f"anchor_ligand {anchor_ligand!r} not found in edges")
    free_nodes = [n for n in all_nodes if n != anchor_ligand]

    a_mat = np.array(
        [[int(str(e["to_id"]) == n) - int(str(e["from_id"]) == n) for n in free_nodes] for e in valid],
        dtype=float,
    )
    y_vec = np.array([float(e["ddg_kcal_mol"]) for e in valid], dtype=float)

    sig_eff = []
    for e in valid:
        se = max(float(e.get("uncertainty_kcal_mol") or 0.15), 0.05)
        hd = abs(float(e.get("temporal_half_delta_kcal_mol") or 0.0))
        ov = e.get("overlap_min")
        ov_pen = (
            0.4 * max(0.0, math.log(0.03 / max(float(ov), 1e-4)))
            if (ov is not None and float(ov) < 0.03)
            else 0.0
        )
        cmin = e.get("min_uncorrelated_samples")
        c_pen = (
            max(0.0, 0.5 * math.sqrt(300.0 / max(float(cmin), 10.0)) - 0.5)
            if cmin is not None
            else 0.0
        )
        sig_eff.append(math.hypot(se, 0.5 * hd, ov_pen + c_pen))
    sig_arr = np.array(sig_eff, dtype=float)

    weights = 1.0 / (sig_arr ** 2)
    theta = np.zeros(len(free_nodes), dtype=float)
    for _ in range(max_iters):
        w_mat = np.diag(weights)
        lhs = a_mat.T @ w_mat @ a_mat
        rhs = a_mat.T @ w_mat @ y_vec
        theta = np.linalg.solve(lhs, rhs)
        residuals = y_vec - a_mat @ theta
        huber_factor = np.where(
            np.abs(residuals) <= huber_delta_kcal,
            1.0,
            huber_delta_kcal / np.maximum(np.abs(residuals), 1e-9),
        )
        weights = huber_factor / (sig_arr ** 2)

    residuals = y_vec - a_mat @ theta
    cov = np.linalg.inv(a_mat.T @ np.diag(weights) @ a_mat)
    node_se = np.sqrt(np.maximum(np.diag(cov), 0.0))

    rel_dg = {anchor_ligand: 0.0, **{n: round(float(v), 4) for n, v in zip(free_nodes, theta, strict=True)}}
    rel_se = {anchor_ligand: 0.0, **{n: round(float(s), 4) for n, s in zip(free_nodes, node_se, strict=True)}}

    edge_diagnostics: list[dict[str, Any]] = []
    outliers: list[str] = []
    for e, sig, res in zip(valid, sig_arr, residuals, strict=True):
        eid = str(e.get("edge_id") or f"{e['from_id']}->{e['to_id']}")
        is_outlier = abs(float(res)) > outlier_residual_kcal
        if is_outlier:
            outliers.append(eid)
        edge_diagnostics.append({
            "edge_id": eid,
            "ddg_kcal_mol": round(float(e["ddg_kcal_mol"]), 4),
            "effective_sigma_kcal": round(float(sig), 4),
            "robust_residual_kcal": round(float(res), 4),
            "outlier_flagged": is_outlier,
        })

    return {
        "schema": ROBUST_NETWORK_SCHEMA,
        "anchor_ligand": anchor_ligand,
        "huber_delta_kcal": huber_delta_kcal,
        "relative_dg_kcal_mol": rel_dg,
        "relative_se_kcal_mol": rel_se,
        "outlier_edges": outliers,
        "edge_diagnostics": edge_diagnostics,
    }


def plan_sampling_escalation(
    edge_reports: Sequence[Mapping[str, Any]],
    *,
    mpi_hrex_available: bool = False,
    min_overlap: float = 0.03,
    max_half_delta_kcal: float = 1.0,
    min_uncorr_samples: int = 100,
    outlier_edges: Sequence[str] = (),
) -> dict[str, Any]:
    """Decide per-edge sampling tier cleanly: keep converged edges, escalate only stubborn ones."""
    outlier_set = set(outlier_edges)
    converged: list[str] = []
    escalate_geodesic: list[dict[str, Any]] = []
    escalate_enhanced: list[dict[str, Any]] = []
    enhanced_tier = "tier2_gmx_mpi_hrex" if mpi_hrex_available else "tier1_metropolized_gibbs_expanded_ensemble"

    for row in edge_reports:
        eid = str(row.get("edge_id") or f"{row.get('from_id')}->{row.get('to_id')}")
        status = str(row.get("status") or "ok")
        ov = row.get("overlap_min")
        hd = row.get("temporal_half_delta_kcal_mol")
        cmin = row.get("min_uncorrelated_samples")

        kinetic_reasons: list[str] = []
        if eid in outlier_set:
            kinetic_reasons.append("robust_graph_cycle_outlier")
        if hd is not None and abs(float(hd)) > max_half_delta_kcal:
            kinetic_reasons.append(f"temporal_half_delta={float(hd):.2f}>{max_half_delta_kcal}")
        if cmin is not None and int(cmin) < min_uncorr_samples:
            kinetic_reasons.append(f"low_uncorrelated_samples={int(cmin)}<{min_uncorr_samples}")

        overlap_fail = status != "ok" or (ov is not None and float(ov) < min_overlap)

        if kinetic_reasons:
            escalate_enhanced.append({
                "edge_id": eid,
                "target_tier": enhanced_tier,
                "also_reparameterize_geodesic": overlap_fail,
                "reasons": kinetic_reasons + (["low_overlap"] if overlap_fail else []),
            })
        elif overlap_fail:
            escalate_geodesic.append({
                "edge_id": eid,
                "target_tier": "tier0_geodesic_lambda_cpu_update",
                "reasons": [f"status={status}" if status != "ok" else f"overlap_min={ov}<{min_overlap}"],
            })
        else:
            converged.append(eid)

    return {
        "schema": ESCALATION_PLAN_SCHEMA,
        "mpi_hrex_available": mpi_hrex_available,
        "enhanced_tier": enhanced_tier,
        "converged_edges": converged,
        "escalate_geodesic_only": escalate_geodesic,
        "escalate_enhanced_sampling": escalate_enhanced,
    }


__all__ = [
    "EE_CONVERGENCE_SCHEMA",
    "ESCALATION_PLAN_SCHEMA",
    "GEODESIC_SCHEDULE_SCHEMA",
    "ROBUST_NETWORK_SCHEMA",
    "analyze_expanded_ensemble_convergence",
    "build_expanded_ensemble_mdp",
    "interpolate_lambda_weights",
    "optimize_lambda_geodesic",
    "parse_final_mc_lambda_weights",
    "plan_sampling_escalation",
    "solve_robust_fep_network",
]
