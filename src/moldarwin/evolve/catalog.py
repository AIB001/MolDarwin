"""Streaming local building-block catalog indexer for catalog-constrained reaction design.

Solves the "0/2 purchasable coupling partners" failure mode observed on unconstrained
virtual enumeration (e.g., SND1 lead A0200 having 0/2 partners in a 7.07M Mcule snapshot)
by bucketing local ``.smi`` / ``.smi.gz`` / ``.tsv`` supplier catalogs into a fast,
dependency-free SQLite index keyed by canonical SMILES and medicinal-chemistry reactive
handles.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CATALOG_INDEX_SCHEMA = "moldarwin-building-block-catalog/1"

#: Organic medicinal-chemistry elements permitted for building blocks (Evidence: convention).
#: Boron is admitted specifically for the ``boronic_acid`` bucket (consumed in Suzuki coupling).
DEFAULT_BUILDING_BLOCK_ELEMENTS: frozenset[str] = frozenset(
    {"C", "H", "N", "O", "S", "F", "Cl", "Br", "I", "P"}
)

#: Functional-group SMARTS aligned with ``moldarwin.evolve.engine.MEDCHEM_REACTIONS``
#: (Evidence: literature / standard parallel medchem library synthesis handles).
REACTIVE_BUCKET_SMARTS: dict[str, str] = {
    "primary_secondary_amine": "[N;H2,H1;!$(NC=O);!$(NS=O);!$(N=*);!$(N#*);+0]",
    "carboxylic_acid": "[CX3](=O)[OX2H1]",
    "sulfonyl_chloride": "[SX4](=O)(=O)Cl",
    "boronic_acid": "[c]B(O)O",
    "aryl_halide": "[c][Br,I,Cl]",
    "aryl_bromide_iodide": "[c][Br,I]",
    "heteroaryl_halide": "[c]([F,Cl])[n]",
}

#: Complementary reactant bucket pairs for each reaction in ``MEDCHEM_REACTIONS``.
REACTION_PARTNER_BUCKETS: dict[str, tuple[str, str]] = {
    "amide_coupling": ("carboxylic_acid", "primary_secondary_amine"),
    "suzuki_miyaura": ("aryl_halide", "boronic_acid"),
    "buchwald_hartwig": ("aryl_bromide_iodide", "primary_secondary_amine"),
    "sulfonamidation": ("sulfonyl_chloride", "primary_secondary_amine"),
    "snar_heteroaryl_amine": ("heteroaryl_halide", "primary_secondary_amine"),
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_smiles_rows(path: Path) -> Iterator[tuple[str, str]]:
    """Stream (smiles, supplier_id) tuples from .smi/.tsv (plain or .gz)."""
    opener = gzip.open if path.suffix.lower() == ".gz" else Path.open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            smi = parts[0]
            if line_no == 1 and smi.lower() in {"smiles", "canonical_smiles", "smi"}:
                continue
            sid = parts[1] if len(parts) > 1 else f"{path.stem}:{line_no}"
            yield smi, sid


def build_building_block_index(
    source_paths: str | Path | Sequence[str | Path],
    db_path: str | Path,
    *,
    max_mw: float = 350.0,
    max_clogp: float = 4.0,
    require_neutral: bool = True,
    max_rows: int | None = None,
    allowed_elements: Sequence[str] = tuple(sorted(DEFAULT_BUILDING_BLOCK_ELEMENTS)),
) -> dict[str, Any]:
    """Stream supplier SMILES catalog(s) into an indexed SQLite building-block store.

    Preserves exact source SHA-256 provenance, deduplicates canonical SMILES, skips
    multi-fragment salts, and indexes reactive handles matching ``MEDCHEM_REACTIONS``.
    """
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    paths = (
        [Path(source_paths).resolve()]
        if isinstance(source_paths, (str, Path))
        else [Path(p).resolve() for p in source_paths]
    )
    if not paths:
        raise ValueError("source_paths must be non-empty")
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(f"catalog source not found: {p}")

    compiled_buckets = {
        name: Chem.MolFromSmarts(smarts) for name, smarts in REACTIVE_BUCKET_SMARTS.items()
    }
    allowed_set = {str(el) for el in allowed_elements}
    dest = Path(db_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    conn = sqlite3.connect(str(dest))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE compounds (
                canonical_smiles TEXT PRIMARY KEY,
                supplier_id TEXT NOT NULL,
                mw REAL NOT NULL,
                clogp REAL NOT NULL,
                tpsa REAL NOT NULL,
                heavy_atoms INTEGER NOT NULL,
                fsp3 REAL NOT NULL
            );
            CREATE TABLE bucket_members (
                bucket TEXT NOT NULL,
                canonical_smiles TEXT NOT NULL,
                supplier_id TEXT NOT NULL,
                mw REAL NOT NULL,
                clogp REAL NOT NULL,
                PRIMARY KEY (bucket, canonical_smiles)
            );
            CREATE INDEX idx_bucket_filter ON bucket_members (bucket, mw, clogp, supplier_id);
            """
        )

        source_digests: dict[str, str] = {}
        rows_scanned = 0
        rows_invalid = 0
        rows_filtered_out = 0
        compounds_inserted = 0
        bucket_counts: dict[str, int] = dict.fromkeys(REACTIVE_BUCKET_SMARTS, 0)

        compound_batch: list[tuple[Any, ...]] = []
        bucket_batch: list[tuple[Any, ...]] = []
        seen_can: set[str] = set()

        def _flush() -> None:
            if compound_batch:
                conn.executemany(
                    "INSERT OR IGNORE INTO compounds VALUES (?, ?, ?, ?, ?, ?, ?)",
                    compound_batch,
                )
                compound_batch.clear()
            if bucket_batch:
                conn.executemany(
                    "INSERT OR IGNORE INTO bucket_members VALUES (?, ?, ?, ?, ?)",
                    bucket_batch,
                )
                bucket_batch.clear()

        for src_path in paths:
            source_digests[str(src_path)] = _sha256_file(src_path)
            for raw_smi, sid in _iter_smiles_rows(src_path):
                if max_rows is not None and rows_scanned >= int(max_rows):
                    break
                rows_scanned += 1
                if "." in raw_smi:
                    rows_filtered_out += 1
                    continue
                mol = Chem.MolFromSmiles(raw_smi)
                if mol is None:
                    rows_invalid += 1
                    continue
                if require_neutral and Chem.GetFormalCharge(mol) != 0:
                    rows_filtered_out += 1
                    continue

                mw = float(Descriptors.MolWt(mol))
                clogp = float(Descriptors.MolLogP(mol))
                if mw > float(max_mw) or clogp > float(max_clogp):
                    rows_filtered_out += 1
                    continue

                elems = {atom.GetSymbol() for atom in mol.GetAtoms()}
                boron_only_extra = elems - allowed_set == {"B"}
                if not elems.issubset(allowed_set) and not boron_only_extra:
                    rows_filtered_out += 1
                    continue

                matched_buckets = [
                    bname
                    for bname, pat in compiled_buckets.items()
                    if pat is not None and mol.HasSubstructMatch(pat)
                ]
                if boron_only_extra and "boronic_acid" not in matched_buckets:
                    rows_filtered_out += 1
                    continue

                can = Chem.MolToSmiles(mol, canonical=True)
                if can in seen_can:
                    continue
                seen_can.add(can)

                tpsa = float(Descriptors.TPSA(mol))
                heavy = int(mol.GetNumHeavyAtoms())
                fsp3 = float(rdMolDescriptors.CalcFractionCSP3(mol))
                compound_batch.append(
                    (can, sid, round(mw, 3), round(clogp, 3), round(tpsa, 3), heavy, round(fsp3, 4))
                )
                compounds_inserted += 1

                for bname in matched_buckets:
                    if boron_only_extra and bname != "boronic_acid":
                        continue
                    bucket_batch.append((bname, can, sid, round(mw, 3), round(clogp, 3)))
                    bucket_counts[bname] += 1

                if len(compound_batch) >= 2000:
                    _flush()
            if max_rows is not None and rows_scanned >= int(max_rows):
                break

        _flush()

        meta = {
            "schema": CATALOG_INDEX_SCHEMA,
            "built_at": datetime.now(UTC).isoformat(),
            "sources": source_digests,
            "max_mw": float(max_mw),
            "max_clogp": float(max_clogp),
            "require_neutral": bool(require_neutral),
            "rows_scanned": rows_scanned,
            "rows_invalid": rows_invalid,
            "rows_filtered_out": rows_filtered_out,
            "compounds_indexed": compounds_inserted,
            "bucket_counts": bucket_counts,
        }
        conn.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [(k, json.dumps(v, sort_keys=True)) for k, v in meta.items()],
        )
        conn.commit()
    finally:
        conn.close()

    return {**meta, "db_path": str(dest)}


def read_catalog_metadata(db_path: str | Path) -> dict[str, Any]:
    """Read provenance and bucket counts from a built SQLite building-block catalog."""
    p = Path(db_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"catalog index not found: {p}")
    conn = sqlite3.connect(str(p))
    try:
        rows = conn.execute("SELECT key, value FROM metadata").fetchall()
    finally:
        conn.close()
    return {k: json.loads(v) for k, v in rows}


def query_building_blocks(
    db_path: str | Path,
    bucket: str,
    *,
    max_mw: float = 300.0,
    max_clogp: float = 3.5,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query verified purchasable building blocks for a reactive functional-group bucket."""
    if bucket not in REACTIVE_BUCKET_SMARTS:
        raise ValueError(
            f"unknown bucket {bucket!r}; expected one of {sorted(REACTIVE_BUCKET_SMARTS)}"
        )
    p = Path(db_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"catalog index not found: {p}")
    conn = sqlite3.connect(str(p))
    try:
        rows = conn.execute(
            """
            SELECT supplier_id, canonical_smiles, mw, clogp
            FROM bucket_members
            WHERE bucket = ? AND mw <= ? AND clogp <= ?
            ORDER BY mw ASC, clogp ASC, supplier_id ASC
            LIMIT ?
            """,
            (bucket, float(max_mw), float(max_clogp), max(1, int(limit))),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "id": str(sid),
            "smiles": str(can),
            "mw": float(mw),
            "clogp": float(clogp),
            "bucket": bucket,
            "catalog_verified": True,
        }
        for sid, can, mw, clogp in rows
    ]


def lookup_exact_smiles(
    db_path: str | Path,
    smiles_list: Sequence[str],
) -> dict[str, list[str]]:
    """Canonicalize and look up exact graph matches in a local building-block catalog."""
    from rdkit import Chem

    p = Path(db_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"catalog index not found: {p}")

    can_map: dict[str, str] = {}
    for smi in smiles_list:
        mol = Chem.MolFromSmiles(smi)
        if mol is not None:
            can_map[smi] = Chem.MolToSmiles(mol, canonical=True)

    unique_cans = sorted(set(can_map.values()))
    found: dict[str, list[str]] = {c: [] for c in unique_cans}
    if not unique_cans:
        return {}

    conn = sqlite3.connect(str(p))
    try:
        for i in range(0, len(unique_cans), 500):
            chunk = unique_cans[i : i + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT canonical_smiles, supplier_id FROM compounds WHERE canonical_smiles IN ({placeholders})",
                chunk,
            ).fetchall()
            for can, sid in rows:
                found[str(can)].append(str(sid))
    finally:
        conn.close()

    return {can: sorted(sids) for can, sids in found.items()}


def infer_complementary_buckets(core_smiles: str, reaction_name: str) -> list[str]:
    """Detect reactive handle(s) on ``core_smiles`` and return complementary partner bucket(s)."""
    from rdkit import Chem

    if reaction_name not in REACTION_PARTNER_BUCKETS:
        raise ValueError(
            f"unknown reaction {reaction_name!r}; expected one of {sorted(REACTION_PARTNER_BUCKETS)}"
        )
    mol = Chem.MolFromSmiles(core_smiles)
    if mol is None:
        raise ValueError(f"invalid core SMILES: {core_smiles!r}")

    b_left, b_right = REACTION_PARTNER_BUCKETS[reaction_name]
    pat_left = Chem.MolFromSmarts(REACTIVE_BUCKET_SMARTS[b_left])
    pat_right = Chem.MolFromSmarts(REACTIVE_BUCKET_SMARTS[b_right])

    complements: list[str] = []
    if pat_left is not None and mol.HasSubstructMatch(pat_left):
        complements.append(b_right)
    if pat_right is not None and mol.HasSubstructMatch(pat_right) and b_left not in complements:
        complements.append(b_left)
    return complements


__all__ = [
    "CATALOG_INDEX_SCHEMA",
    "DEFAULT_BUILDING_BLOCK_ELEMENTS",
    "REACTION_PARTNER_BUCKETS",
    "REACTIVE_BUCKET_SMARTS",
    "build_building_block_index",
    "infer_complementary_buckets",
    "lookup_exact_smiles",
    "query_building_blocks",
    "read_catalog_metadata",
]
