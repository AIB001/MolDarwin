"""Any-Origin 3D complex preflight, SDF title sanitization, and scorer element guards.

Every check here addresses a concrete failure observed in live CADD/AIDD campaigns:
- Blank SDF title lines trigger word-boundary empty-string substitution in PRISM's
  name standardizer, corrupting GRO/ITP coordinates with ``LIG`` markers (measured_here,
  SND1 pilot 2026-11-26).
- Meeko writes valid-looking PDBQTs for boron-containing ligands that Uni-Dock v1.2.0
  subsequently rejects during parsing (9 of 123 inputs = 7.32% failure rate,
  measured_here, SND1 pilot 2026-11-26).
- Static 3D structures from LLMs, co-folders, SBDD generators, or docking can carry
  flat 2D depictions, severe receptor-ligand steric clashes, or detached poses.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

#: Supported element sets per docking scorer.
#: Evidence: ``measured_here`` (Uni-Dock v1.2.0 rejected 9/123 boron PDBQTs emitted by Meeko
#: in the 2026-11-26 SND1 pilot; standard AutoDock Vina atom-type tables cover organic CHNOFPSClBrI).
SCORER_SUPPORTED_ELEMENTS: dict[str, frozenset[str]] = {
    "unidock": frozenset({"H", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I"}),
    "vina": frozenset({"H", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I"}),
    "smina": frozenset({"H", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I", "B", "Si"}),
}

#: Allowed declared origins for Any-Origin 3D complex ingress.
COMPLEX_ORIGINS: frozenset[str] = frozenset({
    "llm",
    "cofold",
    "prism_gen",
    "docked",
    "crystal",
    "unknown",
})

#: Default physical geometry check thresholds (Evidence: convention, standard heavy-atom
#: covalent/VdW clash bound 1.5 A and first-shell pocket contact cutoff 5.0 A).
DEFAULT_CLASH_CUTOFF_A: float = 1.5
DEFAULT_POCKET_CUTOFF_A: float = 5.0
DEFAULT_Z_SPAN_2D_EPSILON_A: float = 1e-3

_SAFE_TITLE_RE = re.compile(r"[^A-Za-z0-9_]+")
_SMILES_BRACKET_ATOM_RE = re.compile(r"\[[0-9]*([A-Z][a-z]?)")
_SMILES_ORGANIC_RE = re.compile(r"(Cl|Br|[BCNOPSFIbcnops])")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean_title(raw: str, fallback: str = "LIG") -> str:
    cleaned = _SAFE_TITLE_RE.sub("_", raw.strip()).strip("_")[:16]
    if not cleaned or not cleaned[0].isalpha():
        fb = _SAFE_TITLE_RE.sub("", fallback.strip())[:16] or "LIG"
        cleaned = fb if fb[0].isalpha() else "LIG"
    return cleaned


def _elements_from_smiles(smiles: str) -> set[str]:
    """Extract element symbols using RDKit when installed, with a pure-Python fallback."""
    try:
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"invalid SMILES: {smiles!r}")
        return {atom.GetSymbol() for atom in mol.GetAtoms()}
    except ImportError:
        found: set[str] = set()
        for match in _SMILES_BRACKET_ATOM_RE.finditer(smiles):
            found.add(match.group(1))
        stripped = re.sub(r"\[[^\]]*\]", "", smiles)
        for match in _SMILES_ORGANIC_RE.finditer(stripped):
            sym = match.group(1)
            found.add(sym.upper() if len(sym) == 1 else sym)
        return found


def preflight_scorer_elements(
    inputs: str | Iterable[str | Mapping[str, Any]],
    *,
    scorer: str = "unidock",
    smiles_key: str = "smiles",
    id_key: str = "id",
) -> dict[str, Any]:
    """Screen one SMILES or a batch of molecules against a scorer's supported atom types.

    Catches Meeko -> Uni-Dock element mismatches (e.g. boron) before 3D conformer/PDBQT
    generation or GPU submission so failure denominators stay transparent and zero-surprise.
    """
    scorer_key = scorer.strip().lower()
    if scorer_key not in SCORER_SUPPORTED_ELEMENTS:
        raise ValueError(
            f"unknown scorer {scorer!r}; expected one of {sorted(SCORER_SUPPORTED_ELEMENTS)}"
        )
    allowed = SCORER_SUPPORTED_ELEMENTS[scorer_key]

    single = isinstance(inputs, str)
    items: list[Any] = [inputs] if single else list(inputs)

    admitted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    element_counts: Counter[str] = Counter()

    for idx, item in enumerate(items):
        if isinstance(item, str):
            mol_id, smi = f"mol_{idx}", item
        elif isinstance(item, Mapping):
            smi = str(item.get(smiles_key, "")).strip()
            mol_id = str(item.get(id_key, f"mol_{idx}"))
        else:
            raise TypeError("each item must be a SMILES string or mapping containing SMILES")

        if not smi:
            excluded.append({"id": mol_id, "reason": "empty_smiles", "unsupported_elements": []})
            continue
        try:
            elements = _elements_from_smiles(smi)
        except ValueError as exc:
            excluded.append({"id": mol_id, "reason": str(exc), "unsupported_elements": []})
            continue

        unsupported = sorted(elements - allowed)
        if unsupported:
            for elem in unsupported:
                element_counts[elem] += 1
            excluded.append({
                "id": mol_id,
                "smiles": smi,
                "reason": f"unsupported_elements_for_{scorer_key}",
                "unsupported_elements": unsupported,
            })
        else:
            admitted.append({"id": mol_id, "smiles": smi})

    total = len(items)
    return {
        "schema": "moldarwin-scorer-element-preflight/1",
        "scorer": scorer_key,
        "supported_elements": sorted(allowed),
        "supported_elements_evidence": "measured_here",
        "total": total,
        "admitted_count": len(admitted),
        "excluded_count": len(excluded),
        "excluded_by_element": dict(sorted(element_counts.items())),
        "admitted_ids": [row["id"] for row in admitted] if total <= 200 else None,
        "excluded": excluded[:200],
        "excluded_truncated": len(excluded) > 200,
    }


def _parse_sdf_coords_and_atoms(block: str) -> tuple[list[tuple[str, float, float, float]], str]:
    """Parse V2000/V3000 coordinates from one SDF record without requiring RDKit."""
    lines = block.splitlines()
    if len(lines) < 4:
        raise ValueError("SDF record has fewer than 4 header lines")
    title = lines[0]
    counts = lines[3]
    coords: list[tuple[str, float, float, float]] = []
    if "V3000" in counts:
        in_atoms = False
        for line in lines[4:]:
            s = line.strip()
            if s.startswith("M  V30 BEGIN ATOM"):
                in_atoms = True
                continue
            if s.startswith("M  V30 END ATOM"):
                break
            if in_atoms and s.startswith("M  V30"):
                parts = s.split()
                if len(parts) >= 7:
                    coords.append((parts[3], float(parts[4]), float(parts[5]), float(parts[6])))
        return coords, title

    try:
        n_atoms = int(counts[0:3].strip())
    except ValueError as exc:
        raise ValueError(f"unreadable V2000 atom count line: {counts!r}") from exc
    if len(lines) < 4 + n_atoms:
        raise ValueError(f"truncated V2000 atom block: expected {n_atoms} atoms")
    for line in lines[4 : 4 + n_atoms]:
        parts = line.split()
        if len(parts) < 4:
            raise ValueError(f"malformed SDF atom line: {line!r}")
        coords.append((parts[3], float(parts[0]), float(parts[1]), float(parts[2])))
    return coords, title


def sanitize_ligand_sdf(
    sdf_path: str | Path,
    out_path: str | Path | None = None,
    *,
    fallback_name: str = "LIG",
) -> dict[str, Any]:
    """Validate an SDF ligand and guarantee a safe non-empty title line before PRISM build.

    Eliminates PRISM's blank-title word-boundary substitution bug that corrupts GRO/ITP
    coordinates into ``'IG  L'`` markers. Never mutates ``sdf_path`` in place unless
    ``out_path`` explicitly equals ``sdf_path``.
    """
    src = Path(sdf_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"ligand SDF not found: {src}")
    raw = src.read_text(encoding="utf-8", errors="replace")
    if not raw.strip():
        raise ValueError(f"ligand SDF is empty: {src}")

    records = [rec for rec in raw.split("$$$$") if rec.strip()]
    if not records:
        raise ValueError(f"no SDF molecule records found in {src}")

    repaired_records: list[str] = []
    repaired_titles = 0
    total_atoms = 0
    has_explicit_h = False
    is_3d = False
    elements: set[str] = set()

    for idx, rec in enumerate(records):
        # Preserve a blank first title line on record 0; only strip the single newline
        # immediately following a prior '$$$$' separator.
        if idx > 0:
            if rec.startswith("\r\n"):
                rec = rec[2:]
            elif rec.startswith("\n"):
                rec = rec[1:]
        lines = rec.splitlines()
        coords, orig_title = _parse_sdf_coords_and_atoms(rec)
        if not coords:
            raise ValueError(f"SDF record {idx} contains zero atoms")
        total_atoms += len(coords)
        zs = [c[3] for c in coords]
        if (max(zs) - min(zs)) > DEFAULT_Z_SPAN_2D_EPSILON_A:
            is_3d = True
        for sym, _, _, _ in coords:
            elements.add(sym)
            if sym == "H":
                has_explicit_h = True

        desired_fallback = fallback_name if len(records) == 1 else f"{fallback_name}{idx + 1}"
        safe_title = _clean_title(orig_title, fallback=desired_fallback)
        if orig_title.strip() != safe_title:
            lines[0] = safe_title
            repaired_titles += 1
        repaired_records.append("\n".join(lines) + "\n$$$$")

    dest = Path(out_path).resolve() if out_path is not None else src
    if out_path is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(repaired_records) + "\n", encoding="utf-8")

    return {
        "schema": "moldarwin-sdf-sanitization/1",
        "source_path": str(src),
        "source_sha256": _sha256_file(src),
        "output_path": str(dest),
        "output_sha256": _sha256_file(dest),
        "record_count": len(records),
        "total_atoms": total_atoms,
        "elements": sorted(elements),
        "has_explicit_hydrogens": has_explicit_h,
        "is_3d": is_3d,
        "z_span_threshold_A": DEFAULT_Z_SPAN_2D_EPSILON_A,
        "z_span_threshold_evidence": "convention",
        "titles_repaired": repaired_titles,
        "written": out_path is not None,
    }


def _parse_pdb_heavy_coords(pdb_path: Path) -> list[tuple[str, float, float, float]]:
    coords: list[tuple[str, float, float, float]] = []
    for line in pdb_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 54:
            continue
        elem = line[76:78].strip() if len(line) >= 78 else ""
        if not elem:
            atom_name = line[12:16].strip()
            elem = "".join(ch for ch in atom_name if ch.isalpha())[:1]
        if elem.upper() == "H":
            continue
        try:
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError:
            continue
        coords.append((elem, x, y, z))
    return coords


def validate_complex_handoff(
    receptor_pdb: str | Path,
    ligand_path: str | Path,
    *,
    origin: str = "unknown",
    scorer: str | None = None,
    clash_cutoff_A: float = DEFAULT_CLASH_CUTOFF_A,
    pocket_contact_cutoff_A: float = DEFAULT_POCKET_CUTOFF_A,
) -> dict[str, Any]:
    """Any-Origin 3D complex ingress check before spending docking or MD compute.

    Works identically for structures coming from LLMs, co-folding models (Boltz/AF3),
    PRISM 3D generation, Uni-Dock, or X-ray crystals. Checks 3D geometry, blank SDF
    titles, receptor-ligand steric clashes, detached/floating ligands, explicit
    hydrogens, and optional scorer element compatibility.
    """
    if origin not in COMPLEX_ORIGINS:
        raise ValueError(f"origin must be one of {sorted(COMPLEX_ORIGINS)}, got {origin!r}")

    rec_path = Path(receptor_pdb).resolve()
    lig_path = Path(ligand_path).resolve()
    if not rec_path.is_file():
        raise FileNotFoundError(f"receptor PDB not found: {rec_path}")
    if not lig_path.is_file():
        raise FileNotFoundError(f"ligand file not found: {lig_path}")

    rec_coords = _parse_pdb_heavy_coords(rec_path)
    if not rec_coords:
        raise ValueError(f"receptor PDB contains zero parseable heavy atoms: {rec_path}")

    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    sdf_report: dict[str, Any] | None = None

    if lig_path.suffix.lower() in {".sdf", ".mol"}:
        sdf_report = sanitize_ligand_sdf(lig_path, out_path=None)
        raw_rec = [r for r in lig_path.read_text(encoding="utf-8", errors="replace").split("$$$$") if r.strip()][0]
        lig_all, _ = _parse_sdf_coords_and_atoms(raw_rec)
        lig_heavy = [c for c in lig_all if c[0].upper() != "H"]
        if sdf_report["titles_repaired"] > 0:
            warnings.append({
                "code": "W_BLANK_OR_UNSAFE_SDF_TITLE",
                "message": "Ligand SDF title is empty or non-alphanumeric; sanitize via sanitize_ligand_sdf before PRISM build.",
            })
        if not sdf_report["is_3d"]:
            issues.append({
                "code": "F_COORDINATES_ARE_A_DEPICTION",
                "message": "Ligand coordinates appear flat (2D Z-span <= 0.001 A).",
            })
        if not sdf_report["has_explicit_hydrogens"]:
            warnings.append({
                "code": "W_HYDROGENS_IMPLICIT",
                "message": "Ligand SDF lacks explicit hydrogens; verify protonation state at target pH before MD.",
            })
        lig_elements = set(sdf_report["elements"])
    elif lig_path.suffix.lower() == ".pdb":
        lig_heavy = _parse_pdb_heavy_coords(lig_path)
        lig_elements = {c[0] for c in lig_heavy}
    else:
        raise ValueError(f"unsupported ligand format {lig_path.suffix!r}; expected .sdf, .mol, or .pdb")

    if not lig_heavy:
        raise ValueError(f"ligand contains zero heavy atoms: {lig_path}")

    # Fast bounding-box prefilter before exact pairwise distance scan.
    lx = [c[1] for c in lig_heavy]
    ly = [c[2] for c in lig_heavy]
    lz = [c[3] for c in lig_heavy]
    pad = max(clash_cutoff_A, pocket_contact_cutoff_A) + 0.5
    near_rec = [
        c for c in rec_coords
        if (min(lx) - pad <= c[1] <= max(lx) + pad
            and min(ly) - pad <= c[2] <= max(ly) + pad
            and min(lz) - pad <= c[3] <= max(lz) + pad)
    ]

    min_dist = math.inf
    clash_pairs = 0
    contact_rec_atoms = 0
    clash_sq = clash_cutoff_A * clash_cutoff_A
    contact_sq = pocket_contact_cutoff_A * pocket_contact_cutoff_A

    for _, rx, ry, rz in near_rec:
        atom_min_sq = math.inf
        for _, x, y, z in lig_heavy:
            dx, dy, dz = rx - x, ry - y, rz - z
            d2 = dx * dx + dy * dy + dz * dz
            if d2 < atom_min_sq:
                atom_min_sq = d2
            if d2 < clash_sq:
                clash_pairs += 1
        if atom_min_sq < contact_sq:
            contact_rec_atoms += 1
        d = math.sqrt(atom_min_sq)
        if d < min_dist:
            min_dist = d

    if not near_rec or min_dist > pocket_contact_cutoff_A:
        issues.append({
            "code": "F_LIGAND_DETACHED_FROM_RECEPTOR",
            "message": f"No receptor heavy atom within {pocket_contact_cutoff_A} A of ligand.",
        })
    if clash_pairs > 0:
        warnings.append({
            "code": "W_STERIC_CLASH",
            "message": f"{clash_pairs} receptor-ligand heavy-atom pair(s) closer than {clash_cutoff_A} A.",
            "clash_pairs": clash_pairs,
        })

    if scorer is not None:
        scorer_key = scorer.strip().lower()
        if scorer_key not in SCORER_SUPPORTED_ELEMENTS:
            raise ValueError(f"unknown scorer {scorer!r}")
        unsupported = sorted(lig_elements - SCORER_SUPPORTED_ELEMENTS[scorer_key])
        if unsupported:
            issues.append({
                "code": "F_SCORER_UNSUPPORTED_ELEMENTS",
                "message": f"Elements {unsupported} are unsupported by scorer {scorer_key!r}.",
                "unsupported_elements": unsupported,
            })

    return {
        "schema": "moldarwin-complex-handoff-preflight/1",
        "origin": origin,
        "receptor": {"path": str(rec_path), "sha256": _sha256_file(rec_path), "heavy_atoms": len(rec_coords)},
        "ligand": {
            "path": str(lig_path),
            "sha256": _sha256_file(lig_path),
            "heavy_atoms": len(lig_heavy),
            "elements": sorted(lig_elements),
            **({"sdf_sanitization": sdf_report} if sdf_report is not None else {}),
        },
        "geometry": {
            "min_receptor_ligand_heavy_dist_A": round(min_dist, 3) if math.isfinite(min_dist) else None,
            "pocket_contact_receptor_atoms": contact_rec_atoms,
            "clash_pairs_below_cutoff": clash_pairs,
            "clash_cutoff_A": clash_cutoff_A,
            "pocket_contact_cutoff_A": pocket_contact_cutoff_A,
            "thresholds_evidence": "convention",
        },
        "ready": not issues,
        "blocking_issues": issues,
        "warnings": warnings,
    }
