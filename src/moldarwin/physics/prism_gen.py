"""PRISM 3D structure-based generation discovery and Any-Origin pose qualification.

Connects PRISM's 6 SBDD generative adapters (``diffsbdd``, ``flowr``, ``molcraft``,
``pocket2mol``, ``pocketxmol``, ``targetdiff``) as well as LLM/co-folded 3D structures
directly into MolDarwin's physical qualification preflight without editing ``asset/prism``
(Hard Constraint 6) and without fabricating model readiness (Hard Constraint 7).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from moldarwin.physics.preflight import sanitize_ligand_sdf, validate_complex_handoff


def discover_prism_generators() -> dict[str, Any]:
    """Inspect pinned ``prism.generation`` adapters honestly without claiming weights exist."""
    from moldarwin.boundary.infra import load as load_infra

    prism_infra = load_infra("prism")
    reg = __import__("prism.generation.registry", fromlist=["model_capabilities"])
    caps = reg.model_capabilities()
    return {
        "schema": "moldarwin-prism-generators/1",
        "prism_provenance": prism_infra.provenance(),
        "models": caps,
        "model_count": len(caps),
        "weights_verified": False,
        "note": (
            "Lists code-supported PRISM SBDD adapters only; verify local model weights "
            "and conda/venv environments separately before launching generation."
        ),
    }


def qualify_generated_poses(
    receptor_pdb: str | Path,
    ligand_paths: Sequence[str | Path],
    *,
    origin: str = "prism_gen",
    scorer: str | None = "unidock",
    sanitize_dir: str | Path | None = None,
    clash_cutoff_A: float = 1.5,
    pocket_contact_cutoff_A: float = 5.0,
) -> dict[str, Any]:
    """Qualify a batch of 3D generated/LLM/co-folded poses before rescoring or PRISM MD.

    Runs every pose through :func:`validate_complex_handoff` (3D check, clash check,
    pocket attachment, optional scorer element compatibility, blank SDF title warning),
    deduplicates identical ligand bytes by SHA-256, and optionally writes sanitized SDFs
    into ``sanitize_dir`` for immediate zero-touch PRISM ingestion.
    """
    rec = Path(receptor_pdb).resolve()
    san_root = Path(sanitize_dir).resolve() if sanitize_dir is not None else None
    if san_root is not None:
        san_root.mkdir(parents=True, exist_ok=True)

    ready: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    seen_hashes: set[str] = set()
    duplicates = 0

    for idx, raw_lig in enumerate(ligand_paths):
        lig = Path(raw_lig).resolve()
        try:
            report = validate_complex_handoff(
                rec,
                lig,
                origin=origin,
                scorer=scorer,
                clash_cutoff_A=clash_cutoff_A,
                pocket_contact_cutoff_A=pocket_contact_cutoff_A,
            )
        except Exception as exc:
            code = type(exc).__name__
            reason_counts[code] += 1
            rejected.append({"path": str(lig), "reasons": [f"{code}: {exc}"]})
            continue

        digest_hex = report["ligand"]["sha256"]
        if digest_hex in seen_hashes:
            duplicates += 1
            continue
        seen_hashes.add(digest_hex)

        if not report["ready"]:
            codes = [item["code"] for item in report["blocking_issues"]]
            for c in codes:
                reason_counts[c] += 1
            rejected.append({
                "path": str(lig),
                "sha256": digest_hex,
                "reasons": codes,
            })
            continue

        sanitized_path: str | None = None
        if san_root is not None and lig.suffix.lower() in {".sdf", ".mol"}:
            out_file = san_root / f"pose_{idx:04d}_{digest_hex[:10]}.sdf"
            sanitize_ligand_sdf(lig, out_path=out_file, fallback_name=f"GEN{idx + 1}")
            sanitized_path = str(out_file)

        ready.append({
            "path": str(lig),
            "sanitized_path": sanitized_path,
            "sha256": digest_hex,
            "heavy_atoms": report["ligand"]["heavy_atoms"],
            "min_receptor_dist_A": report["geometry"]["min_receptor_ligand_heavy_dist_A"],
            "clash_pairs": report["geometry"]["clash_pairs_below_cutoff"],
            "warning_codes": [w["code"] for w in report["warnings"]],
        })

    return {
        "schema": "moldarwin-pose-qualification/1",
        "origin": origin,
        "receptor_pdb": str(rec),
        "scorer": scorer,
        "input_count": len(ligand_paths),
        "duplicate_count": duplicates,
        "ready_count": len(ready),
        "rejected_count": len(rejected),
        "rejected_by_code": dict(sorted(reason_counts.items())),
        "ready": ready,
        "rejected": rejected[:200],
        "rejected_truncated": len(rejected) > 200,
    }
