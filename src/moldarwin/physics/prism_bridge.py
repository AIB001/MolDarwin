"""Thin, composable PRISM + GROMACS 2026 bridge and PRISM -> RSI readout layer.

Hardens only the fragile execution/analysis seams uncovered in live GPU runs without
forcing a rigid MD workflow and without modifying ``asset/prism`` (Hard Constraint 6):
1. Pre-sanitizes blank ligand SDF titles before calling pinned ``PRISMBuilder``
   via :func:`moldarwin.boundary.infra.load`.
2. Validates generated GRO/ITP coordinates immediately after build to catch any
   column corruption (e.g. ``'IG  L'``) before burning GPU hours.
3. Stages ligand position-restraint includes and emits a hackable GROMACS 2026
   script using CPU PME for steepest-descent EM and full GPU PME/NB/bonded/update
   for NVT/NPT/production MD.
4. Analyzes completed trajectories with automatic GROMACS 2026 ``TPR v138`` ->
   ``gmx trjconv`` whole-molecule ``GRO+XTC`` fallback, returning a compact
   ``moldarwin-md-readout/1`` record directly consumable by MolDarwin's RSI loop.
"""

from __future__ import annotations

import hashlib
import math
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from moldarwin.physics.preflight import sanitize_ligand_sdf

MD_READOUT_SCHEMA = "moldarwin-md-readout/1"

#: Standard explicit-solvent physical diagnostics thresholds (Evidence: convention).
DEFAULT_POCKET_CUTOFF_A: float = 4.5
DEFAULT_HBOND_DIST_A: float = 3.5
DEFAULT_HBOND_ANGLE_DEG: float = 135.0
DEFAULT_STABLE_RMSD_A: float = 3.0


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_gro_integrity(gro_path: str | Path) -> dict[str, Any]:
    """Verify fixed-column GROMACS ``.gro`` integrity and atom counts.

    Explicitly catches PRISM blank-SDF-title corruption (such as ``'IG  L'`` inside
    integer/coordinate fields) before GROMACS ``grompp``/``mdrun`` is invoked.
    """
    path = Path(gro_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"GRO file not found: {path}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        raise ValueError(f"GRO file is truncated: {path}")
    try:
        declared_atoms = int(lines[1].strip())
    except ValueError as exc:
        raise ValueError(f"GRO atom count line is corrupted ({lines[1]!r}): {path}") from exc

    body = lines[2:-1]
    if len(body) != declared_atoms:
        raise ValueError(
            f"GRO atom count mismatch in {path}: header declares {declared_atoms}, found {len(body)}"
        )

    bad_lines: list[dict[str, Any]] = []
    for idx, line in enumerate(body, start=3):
        if len(line) < 44:
            bad_lines.append({"line": idx, "reason": "short_line", "text": line[:60]})
            continue
        try:
            int(line[0:5].strip())
            int(line[15:20].strip())
            float(line[20:28].strip())
            float(line[28:36].strip())
            float(line[36:44].strip())
        except ValueError:
            bad_lines.append({"line": idx, "reason": "corrupted_columns", "text": line[:60]})
            if len(bad_lines) >= 10:
                break

    box_parts = lines[-1].split()
    box_ok = len(box_parts) in {3, 9} and all(_is_finite_float(tok) for tok in box_parts)
    if not box_ok:
        bad_lines.append({"line": len(lines), "reason": "corrupted_box_vector", "text": lines[-1][:60]})

    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "declared_atoms": declared_atoms,
        "valid": not bad_lines,
        "errors": bad_lines,
    }


def _is_finite_float(token: str) -> bool:
    try:
        return math.isfinite(float(token))
    except ValueError:
        return False


def _ensure_ligand_posre_include(md_dir: Path, ligand_resname: str = "LIG") -> dict[str, Any]:
    """Ensure ligand position-restraint ITP is included under ``#ifdef POSRES``.

    Searches both ``md_dir`` (``GMX_PROLIG_MD/``) and PRISM's sibling ACPYPE/Amber
    parameterization directories (e.g. ``../LIG.amb2gmx/``).
    """
    search_dirs = [md_dir]
    for sibling in (
        md_dir.parent / f"{ligand_resname}.amb2gmx",
        md_dir.parent / f"{ligand_resname.lower()}.amb2gmx",
        *sorted(md_dir.parent.glob("*.amb2gmx")),
        *sorted(md_dir.glob("*.amb2gmx")),
    ):
        if sibling.is_dir() and sibling not in search_dirs:
            search_dirs.append(sibling)

    posre_names = (
        f"posre_{ligand_resname}.itp",
        f"posre_{ligand_resname.lower()}.itp",
        "posre_LIG.itp",
        "posre_lig.itp",
    )
    posre_file: Path | None = None
    for directory in search_dirs:
        existing = {p.name: p for p in directory.iterdir() if p.is_file()}
        posre_file = next((existing[name] for name in posre_names if name in existing), None)
        if posre_file is not None:
            break
    if posre_file is None:
        return {"status": "no_posre_file_found", "patched": False}

    itp_names = (f"{ligand_resname}.itp", f"{ligand_resname.lower()}.itp", "LIG.itp", "topol.top")
    itp_candidates: list[Path] = []
    # Check the posre's own directory first (e.g. LIG.amb2gmx/LIG.itp), then other dirs.
    ordered_dirs = [posre_file.parent, *(d for d in search_dirs if d != posre_file.parent)]
    for directory in ordered_dirs:
        for name in itp_names:
            candidate = directory / name
            if candidate.is_file() and candidate not in itp_candidates:
                itp_candidates.append(candidate)

    for target in itp_candidates:
        text = target.read_text(encoding="utf-8", errors="replace")
        if posre_file.name in text:
            return {"status": "already_included", "target": str(target), "posre": str(posre_file), "patched": False}
    for target in itp_candidates:
        if target.suffix == ".itp":
            text = target.read_text(encoding="utf-8", errors="replace")
            block = (
                "\n; Staged by MolDarwin GROMACS 2026 guard\n"
                "#ifdef POSRES\n"
                f'#include "{posre_file.name}"\n'
                "#endif\n"
            )
            target.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
            return {"status": "patched_ligand_itp", "target": str(target), "posre": str(posre_file), "patched": True}

    return {"status": "no_ligand_itp_found", "posre": str(posre_file), "patched": False}


def _stage_sibling_mdps(md_dir: Path) -> list[str]:
    """Copy PRISM sibling ``../mdps/*.mdp`` files into ``md_dir`` when absent locally."""
    staged: list[str] = []
    sibling_mdps = md_dir.parent / "mdps"
    if not sibling_mdps.is_dir():
        return staged
    for src in sorted(sibling_mdps.glob("*.mdp")):
        dest = md_dir / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
            staged.append(src.name)
    return staged


def patch_gromacs2026_artifacts(
    md_dir: str | Path,
    *,
    ligand_resname: str = "LIG",
    gmx_bin: str = "gmx",
    em_pme: str = "cpu",
    prod_ns: float | None = None,
) -> dict[str, Any]:
    """Patch generated PRISM MD outputs for GROMACS 2026 GPU compatibility.

    Only edits generated run files inside ``md_dir`` (never ``asset/prism``):
    - Stages PRISM's sibling ``../mdps/*.mdp`` files into ``md_dir`` when missing locally.
    - Verifies/stages ligand position restraints across ``md_dir`` and ``../LIG.amb2gmx/``.
    - Writes a clean, editable ``run_md_gmx2026.sh`` exporting ``OMP_NUM_THREADS=$NTOMP``,
      passing ``-r {start_gro}`` on EM (required when ``em.mdp`` defines ``-DPOSRES``),
      using CPU PME for steepest-descent EM and GPU PME/NB/bonded/update for NVT/NPT/MD.
    - Optionally updates ``nsteps`` in ``md.mdp`` when ``prod_ns`` is explicitly requested.
    """
    root = Path(md_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"MD directory not found: {root}")
    if em_pme not in {"cpu", "gpu"}:
        raise ValueError("em_pme must be 'cpu' or 'gpu'")

    staged_mdps = _stage_sibling_mdps(root)
    posre_info = _ensure_ligand_posre_include(root, ligand_resname=ligand_resname)

    mdp_patched = False
    md_nsteps: int | None = None
    md_mdp = root / "md.mdp"
    if prod_ns is not None and md_mdp.is_file():
        if prod_ns <= 0 or not math.isfinite(prod_ns):
            raise ValueError("prod_ns must be finite and positive")
        text = md_mdp.read_text(encoding="utf-8", errors="replace")
        dt_match = re.search(r"(?im)^\s*dt\s*=\s*([0-9.eE+-]+)", text)
        dt_ps = float(dt_match.group(1)) if dt_match else 0.002
        md_nsteps = max(1, int(round((prod_ns * 1000.0) / dt_ps)))
        if re.search(r"(?im)^\s*nsteps\s*=", text):
            new_text = re.sub(r"(?im)^(\s*nsteps\s*=\s*)[0-9]+", rf"\g<1>{md_nsteps}", text)
        else:
            new_text = text.rstrip() + f"\nnsteps = {md_nsteps}\n"
        md_mdp.write_text(new_text, encoding="utf-8")
        mdp_patched = True

    gro_candidates = ["solv_ions.gro", "complex_solv_ions.gro", "system.gro", "complex.gro"]
    start_gro = next((name for name in gro_candidates if (root / name).is_file()), "solv_ions.gro")
    em_mdp = next((name for name in ("em.mdp", "minim.mdp") if (root / name).is_file()), "em.mdp")
    nvt_mdp = "nvt.mdp"
    npt_mdp = "npt.mdp"

    script_path = root / "run_md_gmx2026.sh"
    script_body = f"""#!/usr/bin/env bash
set -euo pipefail
# Generated by MolDarwin physics.prism_bridge (GROMACS 2026 GPU-safe; freely editable)
GMX="${{GMX_BIN:-{gmx_bin}}}"
NTOMP="${{GMX_NTOMP:-4}}"
export OMP_NUM_THREADS="$NTOMP"
export GMX_MAXBACKUP=-1

# 1. Energy minimization: steepest descent requires CPU PME in GROMACS 2026;
# pass -r so -DPOSRES in em.mdp always has reference coordinates.
"$GMX" grompp -f {em_mdp} -c {start_gro} -r {start_gro} -p topol.top -o em.tpr -maxwarn 2
"$GMX" mdrun -deffnm em -ntmpi 1 -ntomp "$NTOMP" -nb gpu -pme {em_pme}

# 2. NVT equilibration (GPU accelerated)
if [ -f {nvt_mdp} ]; then
  "$GMX" grompp -f {nvt_mdp} -c em.gro -r em.gro -p topol.top -o nvt.tpr -maxwarn 2
  "$GMX" mdrun -deffnm nvt -ntmpi 1 -ntomp "$NTOMP" -nb gpu -pme gpu -bonded gpu -update gpu
  NEXT_GRO=nvt.gro
else
  NEXT_GRO=em.gro
fi

# 3. NPT equilibration (GPU accelerated)
if [ -f {npt_mdp} ]; then
  "$GMX" grompp -f {npt_mdp} -c "$NEXT_GRO" -r "$NEXT_GRO" -p topol.top -o npt.tpr -maxwarn 2
  "$GMX" mdrun -deffnm npt -ntmpi 1 -ntomp "$NTOMP" -nb gpu -pme gpu -bonded gpu -update gpu
  PROD_IN=npt.gro
  PROD_CPT="-t npt.cpt"
else
  PROD_IN="$NEXT_GRO"
  PROD_CPT=""
fi

# 4. Production MD (GPU accelerated)
"$GMX" grompp -f md.mdp -c "$PROD_IN" $PROD_CPT -p topol.top -o md.tpr -maxwarn 2
"$GMX" mdrun -deffnm md -ntmpi 1 -ntomp "$NTOMP" -nb gpu -pme gpu -bonded gpu -update gpu
"""
    script_path.write_text(script_body, encoding="utf-8")
    script_path.chmod(0o755)

    return {
        "md_dir": str(root),
        "staged_mdps": staged_mdps,
        "posre": posre_info,
        "md_mdp_patched": mdp_patched,
        "md_nsteps": md_nsteps,
        "script_path": str(script_path),
        "script_sha256": _sha256_file(script_path),
        "em_pme": em_pme,
        "start_gro": start_gro,
    }


def prepare_prism_md_system(
    receptor_pdb: str | Path,
    ligand_sdf: str | Path,
    out_dir: str | Path,
    *,
    ligand_forcefield: str = "gaff2",
    forcefield: str = "amber14sb",
    water_model: str = "tip3p",
    ligand_resname: str = "LIG",
    prod_ns: float | None = 5.0,
    overwrite: bool = False,
    require_explicit_h: bool = True,
    gmx_bin: str = "gmx",
) -> dict[str, Any]:
    """Sanitize inputs, build an explicit-solvent system with pinned PRISM, and validate outputs.

    Stops right before GPU execution and emits a clean, editable ``run_md_gmx2026.sh`` so
    the host agent can schedule GPU shards freely without rigid workflow lock-in.
    """
    from moldarwin.boundary.infra import load as load_infra

    rec_path = Path(receptor_pdb).resolve()
    out_root = Path(out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    sanitized_sdf = out_root / f"{ligand_resname}_sanitized.sdf"
    sdf_report = sanitize_ligand_sdf(ligand_sdf, out_path=sanitized_sdf, fallback_name=ligand_resname)
    if require_explicit_h and not sdf_report["has_explicit_hydrogens"]:
        raise ValueError(
            f"ligand SDF {ligand_sdf} lacks explicit hydrogens required for AmberTools/AM1-BCC "
            "charge assignment; protonate at target pH with explicit 3D hydrogens first "
            "(or pass require_explicit_h=False to bypass)."
        )

    prism_infra = load_infra("prism")
    builder_mod = __import__("prism.builder.core", fromlist=["PRISMBuilder"])
    prism_builder_cls = builder_mod.PRISMBuilder

    builder = prism_builder_cls(
        protein_path=str(rec_path),
        ligand_paths=str(sanitized_sdf),
        output_dir=str(out_root),
        ligand_forcefield=ligand_forcefield,
        forcefield=forcefield,
        water_model=water_model,
        overwrite=overwrite,
    )
    build_result = builder.run()

    md_dir = out_root / "GMX_PROLIG_MD"
    if not md_dir.is_dir():
        md_dir = out_root

    gro_candidates = [md_dir / name for name in ("solv_ions.gro", "complex_solv_ions.gro", "system.gro", "complex.gro")]
    gro_file = next((p for p in gro_candidates if p.is_file()), None)
    gro_report = validate_gro_integrity(gro_file) if gro_file is not None else None
    if gro_report is not None and not gro_report["valid"]:
        raise RuntimeError(
            f"PRISM produced corrupted GRO coordinates at {gro_file}: {gro_report['errors'][:3]}"
        )

    patch_report = patch_gromacs2026_artifacts(
        md_dir, ligand_resname=ligand_resname, gmx_bin=gmx_bin, prod_ns=prod_ns
    )

    return {
        "schema": "moldarwin-prism-prepare/1",
        "prism_provenance": prism_infra.provenance(),
        "receptor_pdb": str(rec_path),
        "receptor_sha256": _sha256_file(rec_path),
        "sdf_sanitization": sdf_report,
        "output_dir": str(out_root),
        "md_dir": str(md_dir),
        "gro_validation": gro_report,
        "gromacs2026_patch": patch_report,
        "build_summary": str(build_result)[:500] if build_result is not None else None,
        "execution_performed": False,
    }


def _export_whole_gro_xtc(md_dir: Path, tpr_path: Path, xtc_path: Path, gmx_bin: str) -> tuple[Path, Path]:
    """Export whole-molecule GRO + XTC via ``gmx trjconv`` when MDAnalysis cannot read TPR v138."""
    whole_gro = md_dir / "md_whole_moldarwin.gro"
    whole_xtc = md_dir / "md_whole_moldarwin.xtc"
    gmx = shutil.which(gmx_bin) or gmx_bin
    if not whole_gro.is_file():
        subprocess.run(
            [gmx, "trjconv", "-s", str(tpr_path), "-f", str(xtc_path), "-o", str(whole_gro), "-dump", "0", "-pbc", "whole"],
            input="System\n",
            text=True,
            capture_output=True,
            check=True,
            timeout=120,
        )
    if not whole_xtc.is_file():
        subprocess.run(
            [gmx, "trjconv", "-s", str(tpr_path), "-f", str(xtc_path), "-o", str(whole_xtc), "-pbc", "whole"],
            input="System\n",
            text=True,
            capture_output=True,
            check=True,
            timeout=300,
        )
    return whole_gro, whole_xtc


def _load_universe(
    md_dir: Path,
    *,
    gro_path: Path | None,
    xtc_path: Path,
    tpr_path: Path | None,
    gmx_bin: str,
) -> tuple[Any, str, Path]:
    import MDAnalysis as mda

    if gro_path is not None and gro_path.is_file():
        return mda.Universe(str(gro_path), str(xtc_path)), "gro_xtc_explicit", gro_path

    if tpr_path is not None and tpr_path.is_file():
        try:
            return mda.Universe(str(tpr_path), str(xtc_path)), "tpr_xtc", tpr_path
        except Exception as exc:
            # GROMACS 2026 emits TPR v138, which older MDAnalysis parsers reject.
            # Fall back transparently to gmx trjconv whole-molecule GRO + XTC.
            fallback_gro = next(
                (p for p in (md_dir / "md_whole.gro", md_dir / "md.gro", md_dir / "npt.gro") if p.is_file()),
                None,
            )
            if shutil.which(gmx_bin) is not None:
                whole_gro, whole_xtc = _export_whole_gro_xtc(md_dir, tpr_path, xtc_path, gmx_bin)
                return mda.Universe(str(whole_gro), str(whole_xtc)), f"gro_xtc_fallback_after_{type(exc).__name__}", whole_gro
            if fallback_gro is not None:
                return mda.Universe(str(fallback_gro), str(xtc_path)), f"gro_xtc_existing_after_{type(exc).__name__}", fallback_gro
            raise

    raise FileNotFoundError(f"neither topology GRO nor TPR found in {md_dir}")


def analyze_md_trajectory(
    md_dir: str | Path,
    *,
    gro_path: str | Path | None = None,
    xtc_path: str | Path | None = None,
    tpr_path: str | Path | None = None,
    ligand_resname: str = "LIG",
    pocket_cutoff_A: float = DEFAULT_POCKET_CUTOFF_A,
    hbond_dist_A: float = DEFAULT_HBOND_DIST_A,
    key_residues: Sequence[int] | None = None,
    stride: int = 1,
    gmx_bin: str = "gmx",
) -> dict[str, Any]:
    """Compute standardized ``moldarwin-md-readout/1`` physical observables from a trajectory.

    Automatically falls back from ``TPR`` to whole-molecule ``GRO + XTC`` when MDAnalysis
    encounters GROMACS 2026 ``TPR v138``. Reports unobtainable quantities explicitly as
    ``None`` / ``"not_taken"`` rather than guessing (Hard Constraint 7).
    """
    import numpy as np
    from MDAnalysis.analysis import align, distances, rms

    root = Path(md_dir).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"MD directory not found: {root}")

    xtc = Path(xtc_path).resolve() if xtc_path else next(
        (p for p in (root / "md_whole.xtc", root / "md.xtc", root / "traj_comp.xtc") if p.is_file()),
        None,
    )
    if xtc is None or not xtc.is_file():
        raise FileNotFoundError(f"no XTC trajectory found in {root}")

    tpr = Path(tpr_path).resolve() if tpr_path else (root / "md.tpr" if (root / "md.tpr").is_file() else None)
    gro = Path(gro_path).resolve() if gro_path else None

    u, backend, topo_used = _load_universe(root, gro_path=gro, xtc_path=xtc, tpr_path=tpr, gmx_bin=gmx_bin)

    protein_bb = u.select_atoms("protein and backbone")
    if len(protein_bb) == 0:
        raise ValueError("trajectory topology contains no protein backbone atoms")

    ligand_heavy = u.select_atoms(f"resname {ligand_resname} and not name H*")
    if len(ligand_heavy) == 0:
        raise ValueError(f"no heavy atoms found for ligand resname {ligand_resname!r}")

    protein_heavy = u.select_atoms("protein and not name H*")
    lig_polar = u.select_atoms(f"resname {ligand_resname} and (name N* O* F* S*)")
    prot_polar = u.select_atoms("protein and (name N* O* S*)")

    # Reference frame 0 coordinates for alignment (with minimum-image wrap of ligand to protein).
    u.trajectory[0]
    ref_bb = protein_bb.positions.copy()
    ref_lig = ligand_heavy.positions.copy()
    ref_box = u.trajectory.ts.dimensions
    if ref_box is not None and len(ref_box) >= 3 and all(float(ref_box[i]) > 0 for i in range(3)):
        box_len = np.asarray(ref_box[:3], dtype=float)
        delta = ref_lig.mean(axis=0) - ref_bb.mean(axis=0)
        ref_lig = ref_lig - np.round(delta / box_len) * box_len
    ref_bb_center = ref_bb.mean(axis=0)
    ref_bb_centered = ref_bb - ref_bb_center
    ref_lig_centered = ref_lig - ref_bb_center

    bb_rmsds: list[float] = []
    lig_rmsds: list[float] = []
    times_ps: list[float] = []
    residue_contact_frames: dict[str, int] = {}
    any_pocket_contact_frames = 0
    polar_contact_frames = 0

    key_set = set(key_residues) if key_residues else None
    prot_res_ids = [f"{a.resname}{a.resid}" for a in protein_heavy]
    prot_res_nums = [int(a.resid) for a in protein_heavy]

    for ts in u.trajectory[:: max(1, int(stride))]:
        times_ps.append(float(ts.time))
        cur_bb = protein_bb.positions.copy()
        cur_lig = ligand_heavy.positions.copy()
        # Minimum-image wrap ligand COM into the protein's periodic image so PBC box jumps
        # never produce spurious ~box-length RMSD spikes.
        if ts.dimensions is not None and len(ts.dimensions) >= 3 and all(float(ts.dimensions[i]) > 0 for i in range(3)):
            box_len = np.asarray(ts.dimensions[:3], dtype=float)
            delta = cur_lig.mean(axis=0) - cur_bb.mean(axis=0)
            cur_lig = cur_lig - np.round(delta / box_len) * box_len
        cur_bb_center = cur_bb.mean(axis=0)
        R, _ = align.rotation_matrix(cur_bb - cur_bb_center, ref_bb_centered)
        aligned_bb = (cur_bb - cur_bb_center) @ R.T
        aligned_lig = (cur_lig - cur_bb_center) @ R.T

        bb_rmsds.append(float(rms.rmsd(aligned_bb, ref_bb_centered, superposition=False)))
        lig_rmsds.append(float(rms.rmsd(aligned_lig, ref_lig_centered, superposition=False)))

        dmat = distances.distance_array(protein_heavy.positions, ligand_heavy.positions, box=ts.dimensions)
        min_per_prot = dmat.min(axis=1)
        hit_indices = np.where(min_per_prot <= pocket_cutoff_A)[0]
        hit_labels: set[str] = set()
        for idx in hit_indices:
            if key_set is None or prot_res_nums[idx] in key_set:
                hit_labels.add(prot_res_ids[idx])
        if hit_labels:
            any_pocket_contact_frames += 1
            for label in hit_labels:
                residue_contact_frames[label] = residue_contact_frames.get(label, 0) + 1

        if len(lig_polar) > 0 and len(prot_polar) > 0:
            pmat = distances.distance_array(prot_polar.positions, lig_polar.positions, box=ts.dimensions)
            if float(pmat.min()) <= hbond_dist_A:
                polar_contact_frames += 1

    n_frames = len(times_ps)
    if n_frames == 0:
        raise ValueError("trajectory yielded zero frames")
    sim_ns = round((times_ps[-1] - times_ps[0]) / 1000.0, 4) if n_frames > 1 else 0.0
    tail_start = max(0, int(math.floor(n_frames * 0.8)))

    per_res_occ = {
        k: round(v / n_frames, 4)
        for k, v in sorted(residue_contact_frames.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    }
    lig_mean = float(np.mean(lig_rmsds))
    lig_final = float(lig_rmsds[-1])
    lig_tail = float(np.mean(lig_rmsds[tail_start:]))
    pocket_occ = round(any_pocket_contact_frames / n_frames, 4)

    return {
        "schema": MD_READOUT_SCHEMA,
        "md_dir": str(root),
        "topology_path": str(topo_used),
        "topology_sha256": _sha256_file(topo_used),
        "trajectory_path": str(xtc),
        "trajectory_sha256": _sha256_file(xtc),
        "analysis_backend": backend,
        "n_atoms": int(len(u.atoms)),
        "ligand_resname": ligand_resname,
        "ligand_heavy_atoms": int(len(ligand_heavy)),
        "n_frames": n_frames,
        "stride": max(1, int(stride)),
        "sim_ns": sim_ns,
        "protein_backbone_rmsd_A": {
            "mean": round(float(np.mean(bb_rmsds)), 3),
            "final": round(float(bb_rmsds[-1]), 3),
            "max": round(float(np.max(bb_rmsds)), 3),
        },
        "ligand_heavy_rmsd_A": {
            "mean": round(lig_mean, 3),
            "final": round(lig_final, 3),
            "max": round(float(np.max(lig_rmsds)), 3),
            "last_20pct_mean": round(lig_tail, 3),
        },
        "pocket_contact_occupancy": pocket_occ,
        "per_residue_contact_occupancy": per_res_occ,
        "polar_hbond_proxy_occupancy": round(polar_contact_frames / n_frames, 4),
        "thresholds": {
            "pocket_cutoff_A": pocket_cutoff_A,
            "hbond_dist_A": hbond_dist_A,
            "evidence": "convention",
        },
        "binding_free_energy_kcal_mol": None,
        "binding_free_energy_status": "not_taken_requires_fep_or_abfe",
    }


def record_md_readout(
    journal: Any,
    readout: dict[str, Any],
    *,
    directory: str | Path,
    candidate_id: str,
    complex_origin: str = "docked",
    docking_score: float | None = None,
    role: str = "diagnostic",
) -> dict[str, Any]:
    """Persist a ``moldarwin-md-readout/1`` artifact into ``ResearchJournal`` for RSI recall."""
    from moldarwin.active.schema import canonical, digest
    from moldarwin.research.schema import Artifact

    if readout.get("schema") != MD_READOUT_SCHEMA:
        raise ValueError(f"readout schema must be {MD_READOUT_SCHEMA!r}")
    out_dir = Path(directory).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        **readout,
        "candidate_id": candidate_id,
        "complex_origin": complex_origin,
        **({"docking_score": float(docking_score)} if docking_score is not None else {}),
    }
    data = (canonical(payload) + "\n").encode("utf-8")
    path = out_dir / f"md-readout-{digest(payload)[:24]}.json"
    path.write_bytes(data)

    bindings: dict[str, Any] = {
        "schema": MD_READOUT_SCHEMA,
        "candidate_id": candidate_id,
        "complex_origin": complex_origin,
        "sim_ns": readout["sim_ns"],
        "ligand_rmsd_mean_A": readout["ligand_heavy_rmsd_A"]["mean"],
        "ligand_rmsd_final_A": readout["ligand_heavy_rmsd_A"]["final"],
        "pocket_contact_occupancy": readout["pocket_contact_occupancy"],
    }
    if docking_score is not None:
        bindings["docking_score"] = float(docking_score)

    record_id = journal.record(
        Artifact(
            str(path),
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
            source_kind="new_execution",
            role=role,
            bindings=bindings,
        )
    )
    return {"record_id": record_id, "path": str(path), "candidate_id": candidate_id}


def compare_docking_vs_md(
    entries: Sequence[dict[str, Any]],
    *,
    stable_rmsd_cutoff_A: float = DEFAULT_STABLE_RMSD_A,
    min_contact_occupancy: float = 0.5,
) -> dict[str, Any]:
    """Compare cheap docking ranks against explicit-solvent PRISM MD stability for RSI calibration.

    Flags high-scoring docking candidates that drifted out of the pocket during MD so
    subsequent rounds and RSI comparisons evaluate physical survival rather than proxy scores.
    """
    rows = []
    for item in entries:
        cid = str(item["candidate_id"])
        dock = float(item["docking_score"])
        rmsd_tail = float(item["ligand_rmsd_last_20pct_A"])
        occ = float(item["pocket_contact_occupancy"])
        stable = rmsd_tail <= stable_rmsd_cutoff_A and occ >= min_contact_occupancy
        rows.append({
            "candidate_id": cid,
            "docking_score": dock,
            "ligand_rmsd_last_20pct_A": rmsd_tail,
            "pocket_contact_occupancy": occ,
            "md_stable": stable,
        })

    if not rows:
        return {
            "schema": "moldarwin-docking-vs-md/1",
            "n_candidates": 0,
            "stable_count": 0,
            "false_positive_drifters": [],
            "spearman_docking_vs_rmsd": None,
            "spearman_status": "not_taken_empty",
        }

    # Lower docking score is better; lower MD RMSD is better.
    by_dock = {r["candidate_id"]: idx + 1 for idx, r in enumerate(sorted(rows, key=lambda x: x["docking_score"]))}
    by_md = {r["candidate_id"]: idx + 1 for idx, r in enumerate(sorted(rows, key=lambda x: x["ligand_rmsd_last_20pct_A"]))}
    for r in rows:
        r["docking_rank"] = by_dock[r["candidate_id"]]
        r["md_rank"] = by_md[r["candidate_id"]]
        r["rank_shift"] = r["docking_rank"] - r["md_rank"]

    spearman: float | None = None
    spearman_status = "not_taken_fewer_than_3_candidates"
    if len(rows) >= 3:
        n = len(rows)
        d2_sum = sum((r["docking_rank"] - r["md_rank"]) ** 2 for r in rows)
        spearman = round(1.0 - (6.0 * d2_sum) / (n * (n * n - 1)), 4)
        spearman_status = "measured_here"

    drifters = [r["candidate_id"] for r in rows if not r["md_stable"]]
    return {
        "schema": "moldarwin-docking-vs-md/1",
        "n_candidates": len(rows),
        "stable_count": sum(1 for r in rows if r["md_stable"]),
        "drifted_count": len(drifters),
        "false_positive_drifters": drifters,
        "spearman_docking_vs_rmsd": spearman,
        "spearman_status": spearman_status,
        "thresholds": {
            "stable_rmsd_cutoff_A": stable_rmsd_cutoff_A,
            "min_contact_occupancy": min_contact_occupancy,
            "evidence": "convention",
        },
        "rows": sorted(rows, key=lambda x: x["md_rank"]),
    }
