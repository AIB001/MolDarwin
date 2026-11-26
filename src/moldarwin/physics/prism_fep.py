"""Thin PRISM FEP/RBFE and MM-PBSA preparation, cycle-closure analysis, and RSI bridge.

Hardens input/output invariants (blank SDF titles, explicit hydrogens, GRO integrity,
thermodynamic cycle closure hysteresis) without locking the host into a rigid MD/FEP
workflow and without editing ``asset/prism`` (Hard Constraint 6).
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from moldarwin.physics.preflight import sanitize_ligand_sdf
from moldarwin.physics.prism_bridge import patch_gromacs2026_artifacts, validate_gro_integrity

FEP_NETWORK_SCHEMA = "moldarwin-fep-network/1"

#: Standard RBFE quality guidelines (Evidence: literature / convention, Wang et al. JACS 2015;
#: cycle closure hysteresis <= 1.0 kcal/mol and per-edge statistical error <= 1.0 kcal/mol).
DEFAULT_CYCLE_CLOSURE_LIMIT_KCAL: float = 1.0
DEFAULT_MAX_EDGE_UNCERTAINTY_KCAL: float = 1.0
DEFAULT_MIN_OVERLAP_THRESHOLD: float = 0.03


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_prism_fep_edge(
    receptor_pdb: str | Path,
    ref_ligand_sdf: str | Path,
    mut_ligand_sdf: str | Path,
    out_dir: str | Path,
    *,
    ligand_forcefield: str = "gaff2",
    forcefield: str = "amber14sb",
    water_model: str = "tip3p",
    lambda_windows: int = 11,
    lambda_strategy: str = "decoupled",
    overwrite: bool = False,
    require_explicit_h: bool = True,
) -> dict[str, Any]:
    """Sanitize reference & mutant ligands and build one pinned PRISM RBFE/FEP edge.

    Enforces blank-title repair and explicit-hydrogen checks on both ligands before
    AmberTools parameterization, then validates any generated GRO topologies under
    ``GMX_PROLIG_FEP/``. Never launches GPU lambda windows so the host schedules freely.
    """
    from moldarwin.boundary.infra import load as load_infra

    rec_path = Path(receptor_pdb).resolve()
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    ref_clean = out_root / "REF_sanitized.sdf"
    mut_clean = out_root / "MUT_sanitized.sdf"
    ref_rep = sanitize_ligand_sdf(ref_ligand_sdf, out_path=ref_clean, fallback_name="REF")
    mut_rep = sanitize_ligand_sdf(mut_ligand_sdf, out_path=mut_clean, fallback_name="MUT")

    if require_explicit_h:
        for label, rep, src in (("reference", ref_rep, ref_ligand_sdf), ("mutant", mut_rep, mut_ligand_sdf)):
            if not rep["has_explicit_hydrogens"]:
                raise ValueError(
                    f"{label} ligand SDF {src} lacks explicit hydrogens required for AmberTools/AM1-BCC "
                    "charge assignment; protonate both endpoints at identical pH first."
                )
    if not ref_rep["is_3d"] or not mut_rep["is_3d"]:
        raise ValueError("both reference and mutant ligand SDFs must carry aligned 3D coordinates for FEP")

    prism_infra = load_infra("prism")
    builder_mod = __import__("prism.builder.core", fromlist=["PRISMBuilder"])
    builder = builder_mod.PRISMBuilder(
        protein_path=str(rec_path),
        ligand_paths=str(ref_clean),
        output_dir=str(out_root),
        ligand_forcefield=ligand_forcefield,
        forcefield=forcefield,
        water_model=water_model,
        overwrite=overwrite,
        fep_mode=True,
        mutant_ligand=str(mut_clean),
        lambda_windows=int(lambda_windows),
        lambda_strategy=lambda_strategy,
    )
    build_result = builder.run()

    fep_dir = out_root / "GMX_PROLIG_FEP"
    if not fep_dir.is_dir():
        fep_dir = out_root

    gro_checks: list[dict[str, Any]] = []
    for gro_file in sorted(fep_dir.rglob("*.gro"))[:12]:
        chk = validate_gro_integrity(gro_file)
        gro_checks.append({
            "path": chk["path"],
            "declared_atoms": chk["declared_atoms"],
            "valid": chk["valid"],
            "error_count": len(chk["errors"]),
        })
        if not chk["valid"]:
            raise RuntimeError(f"PRISM-FEP produced corrupted GRO at {gro_file}: {chk['errors'][:3]}")

    return {
        "schema": "moldarwin-prism-fep-prepare/1",
        "prism_provenance": prism_infra.provenance(),
        "receptor_pdb": str(rec_path),
        "receptor_sha256": _sha256_file(rec_path),
        "ref_sanitization": ref_rep,
        "mut_sanitization": mut_rep,
        "output_dir": str(out_root),
        "fep_dir": str(fep_dir),
        "lambda_windows": int(lambda_windows),
        "lambda_strategy": lambda_strategy,
        "gro_validations": gro_checks,
        "build_summary": str(build_result)[:500] if build_result is not None else None,
        "execution_performed": False,
    }


def prepare_prism_mmpbsa_system(
    receptor_pdb: str | Path,
    ligand_sdf: str | Path,
    out_dir: str | Path,
    *,
    ligand_forcefield: str = "gaff2",
    forcefield: str = "amber14sb",
    water_model: str = "tip3p",
    ligand_resname: str = "LIG",
    traj_ns: float | None = None,
    gmx2amber: bool = True,
    overwrite: bool = False,
    require_explicit_h: bool = True,
    gmx_bin: str = "gmx",
) -> dict[str, Any]:
    """Sanitize ligand and build a pinned PRISM MM/PBSA setup (AMBER MMPBSA.py or gmx_MMPBSA)."""
    from moldarwin.boundary.infra import load as load_infra

    rec_path = Path(receptor_pdb).resolve()
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    sanitized_sdf = out_root / f"{ligand_resname}_sanitized.sdf"
    sdf_rep = sanitize_ligand_sdf(ligand_sdf, out_path=sanitized_sdf, fallback_name=ligand_resname)
    if require_explicit_h and not sdf_rep["has_explicit_hydrogens"]:
        raise ValueError(
            f"ligand SDF {ligand_sdf} lacks explicit hydrogens required for AmberTools/AM1-BCC."
        )

    prism_infra = load_infra("prism")
    builder_mod = __import__("prism.builder.core", fromlist=["PRISMBuilder"])
    builder = builder_mod.PRISMBuilder(
        protein_path=str(rec_path),
        ligand_paths=str(sanitized_sdf),
        output_dir=str(out_root),
        ligand_forcefield=ligand_forcefield,
        forcefield=forcefield,
        water_model=water_model,
        overwrite=overwrite,
        mmpbsa_mode=True,
        mmpbsa_traj_ns=traj_ns,
        gmx2amber=gmx2amber,
    )
    build_result = builder.run()

    mmpbsa_dir = out_root / "GMX_PROLIG_MMPBSA"
    md_dir = out_root / "GMX_PROLIG_MD"
    patch_report = (
        patch_gromacs2026_artifacts(md_dir, ligand_resname=ligand_resname, gmx_bin=gmx_bin, prod_ns=traj_ns)
        if md_dir.is_dir()
        else None
    )

    return {
        "schema": "moldarwin-prism-mmpbsa-prepare/1",
        "prism_provenance": prism_infra.provenance(),
        "receptor_pdb": str(rec_path),
        "receptor_sha256": _sha256_file(rec_path),
        "sdf_sanitization": sdf_rep,
        "output_dir": str(out_root),
        "mmpbsa_dir": str(mmpbsa_dir) if mmpbsa_dir.is_dir() else str(out_root),
        "gmx2amber": bool(gmx2amber),
        "traj_ns": traj_ns,
        "gromacs2026_patch": patch_report,
        "build_summary": str(build_result)[:500] if build_result is not None else None,
        "execution_performed": False,
    }


def _solve_weighted_mle(
    nodes: list[str],
    edges: list[dict[str, Any]],
    anchor: str,
) -> dict[str, float]:
    """Weighted least-squares relative free energy estimate anchored at ``anchor = 0.0``.

    Pure-Python Gaussian elimination so FEP network diagnostics have zero numpy requirement.
    """
    unknowns = [n for n in nodes if n != anchor]
    idx = {n: i for i, n in enumerate(unknowns)}
    m = len(unknowns)
    if m == 0:
        return {anchor: 0.0}

    ata = [[0.0] * m for _ in range(m)]
    atb = [0.0] * m

    for e in edges:
        u, v = e["from_id"], e["to_id"]
        ddg = float(e["ddg_kcal_mol"])
        unc = max(float(e["uncertainty_kcal_mol"]), 0.05)
        w = 1.0 / (unc * unc)
        # Model: G(v) - G(u) = ddg
        iu = idx.get(u)
        iv = idx.get(v)
        if iv is not None:
            ata[iv][iv] += w
            atb[iv] += w * ddg
        if iu is not None:
            ata[iu][iu] += w
            atb[iu] -= w * ddg
        if iu is not None and iv is not None:
            ata[iu][iv] -= w
            ata[iv][iu] -= w

    # Small ridge for disconnected components; disconnected nodes are flagged separately.
    for i in range(m):
        if ata[i][i] == 0.0:
            ata[i][i] = 1e-12

    # Gaussian elimination with partial pivoting.
    aug = [ata[i] + [atb[i]] for i in range(m)]
    for col in range(m):
        piv = max(range(col, m), key=lambda r: abs(aug[r][col]))
        aug[col], aug[piv] = aug[piv], aug[col]
        diag = aug[col][col]
        if abs(diag) < 1e-15:
            continue
        for r in range(col + 1, m):
            factor = aug[r][col] / diag
            for c in range(col, m + 1):
                aug[r][c] -= factor * aug[col][c]

    sol = [0.0] * m
    for r in range(m - 1, -1, -1):
        diag = aug[r][r]
        if abs(diag) < 1e-15:
            sol[r] = 0.0
            continue
        rem = aug[r][m] - sum(aug[r][c] * sol[c] for c in range(r + 1, m))
        sol[r] = rem / diag

    out = {anchor: 0.0}
    for n, i in idx.items():
        out[n] = round(sol[i], 4)
    return out


def analyze_fep_network(
    edges: Sequence[dict[str, Any]],
    *,
    anchor_ligand: str | None = None,
    cycle_closure_limit_kcal: float = DEFAULT_CYCLE_CLOSURE_LIMIT_KCAL,
    max_edge_uncertainty_kcal: float = DEFAULT_MAX_EDGE_UNCERTAINTY_KCAL,
    min_overlap_threshold: float = DEFAULT_MIN_OVERLAP_THRESHOLD,
) -> dict[str, Any]:
    """Audit a relative FEP perturbation network: cycle-closure hysteresis, overlap, and MLE dG.

    Each edge dict requires ``from_id``, ``to_id``, ``ddg_kcal_mol``, ``uncertainty_kcal_mol``
    (optional ``edge_id``, ``overlap_min``, ``status``). Failed/non-ok edges are excluded from
    thermodynamic fits and counted transparently rather than silently dropped.
    """
    valid_edges: list[dict[str, Any]] = []
    failed_edges: list[dict[str, Any]] = []
    flagged_edges: list[dict[str, Any]] = []

    for i, raw in enumerate(edges):
        eid = str(raw.get("edge_id") or f"{raw.get('from_id')}->{raw.get('to_id')}_{i}")
        status = str(raw.get("status", "ok")).lower()
        if status != "ok":
            failed_edges.append({"edge_id": eid, "status": status})
            continue
        ddg = float(raw["ddg_kcal_mol"])
        unc = float(raw["uncertainty_kcal_mol"])
        if not (math.isfinite(ddg) and math.isfinite(unc) and unc >= 0.0):
            raise ValueError(f"edge {eid!r} has non-finite ddg or negative uncertainty")
        ov = raw.get("overlap_min")
        ov_val = float(ov) if ov is not None else None
        rec = {
            "edge_id": eid,
            "from_id": str(raw["from_id"]),
            "to_id": str(raw["to_id"]),
            "ddg_kcal_mol": ddg,
            "uncertainty_kcal_mol": unc,
            "overlap_min": ov_val,
        }
        valid_edges.append(rec)
        reasons = []
        if unc > max_edge_uncertainty_kcal:
            reasons.append(f"uncertainty_{unc:.2f}_exceeds_{max_edge_uncertainty_kcal}")
        if ov_val is not None and ov_val < min_overlap_threshold:
            reasons.append(f"overlap_{ov_val:.3f}_below_{min_overlap_threshold}")
        if reasons:
            flagged_edges.append({"edge_id": eid, "reasons": reasons})

    # Directed lookup: signed[(u, v)] = ddg(u -> v), averaging repeated edges if present.
    pair_vals: dict[tuple[str, str], list[float]] = defaultdict(list)
    adj: dict[str, set[str]] = defaultdict(set)
    nodes_set: set[str] = set()
    for e in valid_edges:
        u, v = e["from_id"], e["to_id"]
        nodes_set.add(u)
        nodes_set.add(v)
        adj[u].add(v)
        adj[v].add(u)
        pair_vals[(u, v)].append(e["ddg_kcal_mol"])
        pair_vals[(v, u)].append(-e["ddg_kcal_mol"])

    nodes = sorted(nodes_set)
    signed = {k: sum(vals) / len(vals) for k, vals in pair_vals.items()}

    # Enumerate unique 3-cycles and 4-cycles canonically.
    cycles: list[dict[str, Any]] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def _canon_cycle(seq: tuple[str, ...]) -> tuple[str, ...]:
        rots = [seq[i:] + seq[:i] for i in range(len(seq))]
        rev = tuple(reversed(seq))
        rots += [rev[i:] + rev[:i] for i in range(len(rev))]
        return min(rots)

    for a in nodes:
        for b in sorted(adj[a]):
            if b <= a:
                continue
            for c in sorted(adj[b]):
                if c == a or c <= a:
                    continue
                if a in adj[c]:
                    key = _canon_cycle((a, b, c))
                    if key not in seen_cycles:
                        seen_cycles.add(key)
                        res = signed[(a, b)] + signed[(b, c)] + signed[(c, a)]
                        cycles.append({
                            "nodes": [a, b, c],
                            "length": 3,
                            "closure_residual_kcal_mol": round(res, 4),
                            "within_limit": abs(res) <= cycle_closure_limit_kcal,
                        })
                for d in sorted(adj[c]):
                    if d in {a, b, c} or d <= a:
                        continue
                    if a in adj[d]:
                        key = _canon_cycle((a, b, c, d))
                        if key not in seen_cycles:
                            seen_cycles.add(key)
                            res = signed[(a, b)] + signed[(b, c)] + signed[(c, d)] + signed[(d, a)]
                            cycles.append({
                                "nodes": [a, b, c, d],
                                "length": 4,
                                "closure_residual_kcal_mol": round(res, 4),
                                "within_limit": abs(res) <= cycle_closure_limit_kcal,
                            })

    # Connected component check.
    components = 0
    visited: set[str] = set()
    for n in nodes:
        if n in visited:
            continue
        components += 1
        stack = [n]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            stack.extend(adj[cur] - visited)

    mle: dict[str, float] | None = None
    mle_status = "not_taken_empty_or_disconnected"
    if nodes and components == 1:
        anchor = anchor_ligand if (anchor_ligand in nodes_set) else nodes[0]
        mle = _solve_weighted_mle(nodes, valid_edges, anchor=anchor)
        mle_status = f"weighted_mle_anchored_at_{anchor}"

    max_hyst = max((abs(c["closure_residual_kcal_mol"]) for c in cycles), default=None)
    cycles_failed = [c for c in cycles if not c["within_limit"]]

    return {
        "schema": FEP_NETWORK_SCHEMA,
        "n_ligands": len(nodes),
        "n_edges_total": len(edges),
        "n_edges_valid": len(valid_edges),
        "n_edges_failed": len(failed_edges),
        "failed_edges": failed_edges,
        "flagged_edges": flagged_edges,
        "connected_components": components,
        "cycles_checked": len(cycles),
        "cycles_exceeding_limit": len(cycles_failed),
        "max_cycle_closure_abs_kcal_mol": round(max_hyst, 4) if max_hyst is not None else None,
        "cycles": cycles[:50],
        "relative_dg_kcal_mol": mle,
        "relative_dg_status": mle_status,
        "network_converged": bool(
            valid_edges and not failed_edges and not flagged_edges and not cycles_failed and components == 1
        ),
        "thresholds": {
            "cycle_closure_limit_kcal": cycle_closure_limit_kcal,
            "max_edge_uncertainty_kcal": max_edge_uncertainty_kcal,
            "min_overlap_threshold": min_overlap_threshold,
            "evidence": "literature",
        },
    }


def record_fep_readout(
    journal: Any,
    network_report: dict[str, Any],
    *,
    directory: str | Path,
    target: str,
    series_id: str,
    role: str = "diagnostic",
) -> dict[str, Any]:
    """Persist a ``moldarwin-fep-network/1`` report into ``ResearchJournal`` for RSI."""
    from moldarwin.active.schema import canonical, digest
    from moldarwin.research.schema import Artifact

    if network_report.get("schema") != FEP_NETWORK_SCHEMA:
        raise ValueError(f"network_report schema must be {FEP_NETWORK_SCHEMA!r}")
    out_dir = Path(directory).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {**network_report, "target": target, "series_id": series_id}
    data = (canonical(payload) + "\n").encode("utf-8")
    path = out_dir / f"fep-network-{digest(payload)[:24]}.json"
    path.write_bytes(data)

    record_id = journal.record(
        Artifact(
            str(path),
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
            source_kind="new_execution",
            role=role,
            bindings={
                "schema": FEP_NETWORK_SCHEMA,
                "target": target,
                "series_id": series_id,
                "n_edges_valid": network_report["n_edges_valid"],
                "cycles_checked": network_report["cycles_checked"],
                "network_converged": network_report["network_converged"],
                "max_cycle_closure_abs_kcal_mol": network_report["max_cycle_closure_abs_kcal_mol"],
            },
        )
    )
    return {"record_id": record_id, "path": str(path), "series_id": series_id}
