"""Synthesizable R-group/bioisostere molecular evolution and uncertainty-aware protocol tournaments.

Implements the dual-track Darwinian loop:
  1. **Molecular evolution** (``generate_bioisostere_analogs``, ``rank_evolution_generation``):
     applies clean, medicinal-chemistry-grounded bioisosteric and R-group transformations
     (avoiding strained, non-synthesizable unconstrained 3D diffusion outputs), supports
     target-adaptive SAR mutation prioritization and custom neutral SMIRKS rules, and selects
     Pareto-optimal winners jointly over primary potency, off-target selectivity
     (``dddG = ddG_target - ddG_offtarget``), and soft liability tiers.
  2. **Protocol tournament** (``prune_protocol_branches``): evaluates competing parallel
     hypothesis branches (e.g., forcefield/hydration/rescorer/sampling subagents) on hard
     physical gates, protects branches whose confidence intervals still overlap the cutoff
     survivor (LCB/UCB protection against premature small-sample pruning), kills failed or
     statistically dominated branches early, and reallocates GPU leases to survivors.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EVOLUTION_GENERATION_SCHEMA = "moldarwin-evolution-generation/1"
PROTOCOL_TOURNAMENT_SCHEMA = "moldarwin-protocol-tournament/1"
REACTION_ENUMERATION_SCHEMA = "moldarwin-reaction-analogs/1"

#: Default z-multiplier for branch confidence-interval overlap protection (~95% CI, Evidence: convention).
DEFAULT_UNCERTAINTY_Z: float = 1.96

#: Clean neutral medicinal-chemistry bioisostere, soft-spot blocking, and heterocycle-hop SMIRKS
#: (Evidence: literature). All preserve formal neutrality so analogs remain directly eligible
#: for neutral RBFE networks.
BIOISOSTERE_MUTATIONS: tuple[dict[str, str], ...] = (
    # --- Liability rescue ---
    {
        "name": "nitro_to_cyano",
        "category": "liability_rescue",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]C#N",
        "rationale": "Replace nitroaromatic liability with polar, metabolically stable nitrile.",
    },
    {
        "name": "nitro_to_cf3",
        "category": "liability_rescue",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]C(F)(F)F",
        "rationale": "Replace nitroaromatic with electron-withdrawing -CF3 bioisostere.",
    },
    {
        "name": "nitro_to_methylsulfone",
        "category": "liability_rescue",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]S(=O)(=O)C",
        "rationale": "Replace nitroaromatic with H-bond-accepting sulfone while lowering cLogP.",
    },
    {
        "name": "nitro_to_carboxamide",
        "category": "liability_rescue",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]C(=O)N",
        "rationale": "Replace nitroaromatic with polar H-bond donor/acceptor carboxamide.",
    },
    {
        "name": "nitro_to_fluoro",
        "category": "liability_rescue",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]F",
        "rationale": "Compact electron-withdrawing fluoro replacement.",
    },
    # --- Halogen / steric / polarity probes ---
    {
        "name": "chloro_to_fluoro",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]Cl>>[c:1]F",
        "rationale": "Trim lipophilicity and steric bulk on chloroaryl ring.",
    },
    {
        "name": "chloro_to_methyl",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]Cl>>[c:1]C",
        "rationale": "Classic Cl -> Me steric/electronic probe for hydrophobic subpockets.",
    },
    {
        "name": "chloro_to_cyano",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]Cl>>[c:1]C#N",
        "rationale": "Polar nitrile substitution probing directional H-bond acceptors.",
    },
    {
        "name": "chloro_to_cf3",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]Cl>>[c:1]C(F)(F)F",
        "rationale": "Expand hydrophobic halogen vector with metabolically robust -CF3.",
    },
    {
        "name": "fluoro_to_chloro",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]F>>[c:1]Cl",
        "rationale": "Probe hydrophobic/halogen-bond subpocket depth from aryl-F.",
    },
    {
        "name": "fluoro_to_cyano",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]F>>[c:1]C#N",
        "rationale": "Convert aryl-F into directional polar nitrile acceptor while lowering cLogP.",
    },
    {
        "name": "fluoro_to_methyl",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]F>>[c:1]C",
        "rationale": "Probe steric complementarity at fluoroaryl vector.",
    },
    {
        "name": "bromo_to_cyclopropyl",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]Br>>[c:1]C1CC1",
        "rationale": "Replace heavy bromo with compact 3D cyclopropyl increasing Fsp3.",
    },
    {
        "name": "bromo_to_cyano",
        "category": "steric_polarity_probe",
        "smirks": "[c:1]Br>>[c:1]C#N",
        "rationale": "Replace bromo with polar nitrile boosting LLE.",
    },
    # --- Metabolic soft-spot blocking ---
    {
        "name": "methyl_to_ethyl",
        "category": "steric_polarity_probe",
        "smirks": "[c:1][CH3]>>[c:1]CC",
        "rationale": "Small hydrophobic growth probing subpocket depth.",
    },
    {
        "name": "methyl_to_methoxy",
        "category": "steric_polarity_probe",
        "smirks": "[c:1][CH3]>>[c:1]OC",
        "rationale": "Introduce polar H-bond acceptor oxygen on aryl substituent.",
    },
    {
        "name": "methyl_to_fluoro",
        "category": "metabolic_blocking",
        "smirks": "[c:1][CH3]>>[c:1]F",
        "rationale": "Block benzylic metabolic oxidation with fluorine.",
    },
    {
        "name": "methyl_to_cf3",
        "category": "metabolic_blocking",
        "smirks": "[c:1][CH3]>>[c:1]C(F)(F)F",
        "rationale": "Block benzylic CYP oxidation while preserving hydrophobic steric volume.",
    },
    {
        "name": "methyl_to_cyclopropyl",
        "category": "metabolic_blocking",
        "smirks": "[c:1][CH3]>>[c:1]C1CC1",
        "rationale": "Replace benzylic methyl with rigid 3D cyclopropyl to raise Fsp3 and stability.",
    },
    {
        "name": "methoxy_to_ocf3",
        "category": "metabolic_blocking",
        "smirks": "[c:1]O[CH3]>>[c:1]OC(F)(F)F",
        "rationale": "Block CYP O-dealkylation soft-spot via metabolically stable -OCF3.",
    },
    {
        "name": "methoxy_to_fluoro",
        "category": "metabolic_blocking",
        "smirks": "[c:1]O[CH3]>>[c:1]F",
        "rationale": "Remove O-dealkylation soft-spot and reduce MW/TPSA.",
    },
    {
        "name": "methoxy_to_cyano",
        "category": "metabolic_blocking",
        "smirks": "[c:1]O[CH3]>>[c:1]C#N",
        "rationale": "Replace O-methyl soft-spot with polar nitrile acceptor to boost LLE.",
    },
    # --- C-H exit-vector scan & heterocycle hop (enabled via include_ch_scan=True) ---
    {
        "name": "aryl_ch_to_fluoro",
        "category": "ch_scan",
        "smirks": "[cH1:1]>>[c:1]F",
        "rationale": "Single aromatic fluorine scan for metabolic blocking and dipole tuning.",
    },
    {
        "name": "aryl_ch_to_methyl",
        "category": "ch_scan",
        "smirks": "[cH1:1]>>[c:1]C",
        "rationale": "Magic-methyl aromatic scan probing hydrophobic subpockets and conformational lock.",
    },
    {
        "name": "aryl_ch_to_cyano",
        "category": "ch_scan",
        "smirks": "[cH1:1]>>[c:1]C#N",
        "rationale": "Aromatic nitrile scan probing directional H-bond acceptors and water displacement.",
    },
    {
        "name": "aryl_ch_to_pyridyl_n",
        "category": "ch_scan",
        "smirks": "[cH1:1]1[c:2][c:3][c:4][c:5][c:6]1>>[n:1]1[c:2][c:3][c:4][c:5][c:6]1",
        "rationale": "Nitrogen-walk phenyl -> pyridyl heterocycle hop to lower cLogP and improve LLE/solubility.",
    },
)

#: Classic high-reliability medicinal-chemistry coupling reactions for building-block enumeration
#: (Evidence: literature, standard parallel medchem library synthesis reactions).
MEDCHEM_REACTIONS: dict[str, dict[str, str]] = {
    "amide_coupling": {
        "smirks": "[C:1](=[O:2])[OH].[N;H2,H1;!$(NC=O);!$(NS=O):3]>>[C:1](=[O:2])[N:3]",
        "rationale": "Carboxylic acid + primary/secondary amine amide bond formation (HATU/EDC).",
    },
    "suzuki_miyaura": {
        "smirks": "[c:1][Br,I,Cl].[c:2]B(O)O>>[c:1][c:2]",
        "rationale": "Aryl halide + aryl boronic acid Pd-catalyzed biaryl coupling.",
    },
    "buchwald_hartwig": {
        "smirks": "[c:1][Br,I].[N;H2,H1;!$(NC=O);!$(NS=O):2]>>[c:1][N:2]",
        "rationale": "Aryl bromide/iodide + amine Pd-catalyzed C-N cross-coupling.",
    },
    "sulfonamidation": {
        "smirks": "[S:1](=[O:2])(=[O:3])Cl.[N;H2,H1;!$(NC=O);!$(NS=O):4]>>[S:1](=[O:2])(=[O:3])[N:4]",
        "rationale": "Sulfonyl chloride + amine sulfonamide formation.",
    },
    "snar_heteroaryl_amine": {
        "smirks": "[c:1]([F,Cl])[n:2].[N;H2,H1;!$(NC=O);!$(NS=O):3]>>[c:1]([N:3])[n:2]",
        "rationale": "2-Halo-azaarene + amine nucleophilic aromatic substitution (SNAr).",
    },
}


def generate_bioisostere_analogs(
    parent_smiles: str,
    *,
    parent_id: str = "parent",
    max_analogs: int = 24,
    include_ch_scan: bool = False,
    target_class: str = "general",
    sar_mutation_weights: Mapping[str, float] | None = None,
    custom_mutations: Sequence[Mapping[str, str]] = (),
    protected_atom_indices: Sequence[int] = (),
) -> dict[str, Any]:
    """Generate deduplicated, neutral, synthesizable R-group/bioisostere analogs of a parent lead.

    Optional structure- & SAR-adaptive inputs:
      - ``sar_mutation_weights``: mapping of ``mutation_name -> priority_weight`` learned from
        empirical target MMP/SAR data (higher weights are expanded first under ``max_analogs``).
      - ``custom_mutations``: additional target-specific neutral SMIRKS rules
        (``{"name", "smirks", "rationale"}``) evaluated alongside built-ins.
      - ``protected_atom_indices``: 0-based heavy-atom indices (e.g. ``anchor_atom_indices`` from
        ``moldarwin.design.pocket.profile_3d_pocket_and_vectors``) that must NOT be altered,
        preventing mutations from breaking critical 3D H-bond/hinge pharmacophore anchors.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    from moldarwin.physics.preflight import annotate_medchem_liabilities

    parent = Chem.MolFromSmiles(parent_smiles)
    if parent is None:
        raise ValueError(f"invalid parent SMILES: {parent_smiles!r}")
    parent_can = Chem.MolToSmiles(parent, canonical=True)
    parent_charge = Chem.GetFormalCharge(parent)

    protected_set = sorted({int(i) for i in protected_atom_indices if 0 <= int(i) < parent.GetNumAtoms()})
    for idx_p in protected_set:
        parent.GetAtomWithIdx(idx_p).SetProp("_protected", "1")

    weights = {str(k): float(v) for k, v in (sar_mutation_weights or {}).items()}
    rule_pool: list[tuple[int, dict[str, str], str]] = []
    idx = 0
    for rule in custom_mutations:
        rule_pool.append((idx, {
            "name": str(rule["name"]),
            "category": str(rule.get("category") or "target_custom"),
            "smirks": str(rule["smirks"]),
            "rationale": str(rule.get("rationale") or "target-specific SAR transform"),
        }, "target_custom"))
        idx += 1
    for rule in BIOISOSTERE_MUTATIONS:
        if rule.get("category") == "ch_scan" and not include_ch_scan:
            continue
        rule_pool.append((idx, dict(rule), "builtin"))
        idx += 1

    # Prioritize mutations with higher target-validated SAR weights; preserve deterministic tie order.
    rule_pool.sort(key=lambda item: (-weights.get(item[1]["name"], 0.0), item[0]))

    seen: set[str] = {parent_can}
    analogs: list[dict[str, Any]] = []

    for _, rule, source in rule_pool:
        rxn = AllChem.ReactionFromSmarts(rule["smirks"])
        if rxn is None:
            continue
        products = rxn.RunReactants((parent,))
        for prod_tuple in products:
            if not prod_tuple:
                continue
            mol = prod_tuple[0]
            try:
                Chem.SanitizeMol(mol)
            except Exception:
                continue
            if Chem.GetFormalCharge(mol) != parent_charge:
                continue
            can = Chem.MolToSmiles(mol, canonical=True)
            if can in seen:
                continue
            seen.add(can)
            analogs.append({
                "analog_id": f"{parent_id}_{rule['name']}_{len(analogs) + 1}",
                "parent_id": parent_id,
                "smiles": can,
                "mutation": rule["name"],
                "category": rule.get("category", "builtin"),
                "mutation_source": source,
                "mutation_priority_weight": round(weights.get(rule["name"], 0.0), 4),
                "rationale": rule["rationale"],
                "formal_charge": parent_charge,
            })
            if len(analogs) >= max_analogs:
                break
        if len(analogs) >= max_analogs:
            break

    if analogs:
        ann = annotate_medchem_liabilities([a["smiles"] for a in analogs], target_class=target_class)
        for a, rec in zip(analogs, ann["records"], strict=True):
            a["medchem_tier"] = rec.get("tier")
            a["soft_flags"] = rec.get("soft_flags", [])
            a["mw"] = rec.get("mw")
            a["clogp"] = rec.get("clogp")
            a["tpsa"] = rec.get("tpsa")

    return {
        "schema": "moldarwin-bioisostere-analogs/1",
        "parent_id": parent_id,
        "parent_smiles": parent_can,
        "parent_formal_charge": parent_charge,
        "protected_atom_indices": protected_set,
        "sar_weighted": bool(weights),
        "custom_rule_count": len(custom_mutations),
        "analog_count": len(analogs),
        "analogs": analogs,
    }


def enumerate_reaction_analogs(
    core_smiles: str,
    building_blocks: Sequence[str | Mapping[str, Any]] = (),
    *,
    reaction_name: str,
    core_id: str = "core",
    mpo_profile: str = "oral",
    max_products: int = 48,
    require_neutral: bool = True,
    protected_core_atom_indices: Sequence[int] = (),
    catalog_db: str | Path | None = None,
    catalog_limit: int = 32,
    catalog_max_mw: float = 300.0,
    catalog_max_clogp: float = 3.5,
) -> dict[str, Any]:
    """Enumerate wet-lab-synthesizable analogs by coupling a reactive core with building blocks.

    Uses standard medicinal-chemistry coupling templates (``MEDCHEM_REACTIONS``) paired with
    purchasable reagents (either caller-supplied or automatically pulled from a local indexed
    SQLite supplier catalog via ``catalog_db``) and scores each product with continuous
    MPO/soft-spot profiling (``moldarwin.design.dmta``). When ``catalog_db`` is provided,
    both core and partner are checked for exact canonical matches so every product carries
    explicit ``catalog_verified_partners`` (0, 1, or 2) provenance at generation time.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    from moldarwin.design.dmta import score_drug_design_mpo
    from moldarwin.evolve.catalog import (
        infer_complementary_buckets,
        lookup_exact_smiles,
        query_building_blocks,
        read_catalog_metadata,
    )

    if reaction_name not in MEDCHEM_REACTIONS:
        raise ValueError(
            f"unknown reaction {reaction_name!r}; expected one of {sorted(MEDCHEM_REACTIONS)}"
        )
    rxn_meta = MEDCHEM_REACTIONS[reaction_name]
    rxn = AllChem.ReactionFromSmarts(rxn_meta["smirks"])
    if rxn is None:
        raise ValueError(f"failed to compile reaction SMIRKS for {reaction_name!r}")

    core_mol = Chem.MolFromSmiles(core_smiles)
    if core_mol is None:
        raise ValueError(f"invalid core SMILES: {core_smiles!r}")
    core_can = Chem.MolToSmiles(core_mol, canonical=True)
    protected_set = sorted(
        {int(i) for i in protected_core_atom_indices if 0 <= int(i) < core_mol.GetNumAtoms()}
    )
    for idx_p in protected_set:
        core_mol.GetAtomWithIdx(idx_p).SetProp("_protected", "1")

    catalog_path = Path(catalog_db).resolve() if catalog_db is not None else None
    catalog_sources: dict[str, str] | None = None
    core_supplier_ids: list[str] = []
    queried_buckets: list[str] = []

    effective_blocks: list[str | Mapping[str, Any]] = list(building_blocks)
    if catalog_path is not None:
        cat_meta = read_catalog_metadata(catalog_path)
        catalog_sources = dict(cat_meta.get("sources") or {})
        core_lookup = lookup_exact_smiles(catalog_path, [core_can])
        core_supplier_ids = list(core_lookup.get(core_can, []))
        if not effective_blocks:
            queried_buckets = infer_complementary_buckets(core_can, reaction_name)
            for bucket in queried_buckets:
                effective_blocks.extend(
                    query_building_blocks(
                        catalog_path,
                        bucket,
                        max_mw=catalog_max_mw,
                        max_clogp=catalog_max_clogp,
                        limit=catalog_limit,
                    )
                )

    partner_lookup: dict[str, list[str]] = {}
    if catalog_path is not None and effective_blocks:
        raw_bb_smiles = [
            bb if isinstance(bb, str) else str(bb.get("smiles") or "")
            for bb in effective_blocks
        ]
        partner_lookup = lookup_exact_smiles(catalog_path, [s for s in raw_bb_smiles if s])

    seen: set[str] = {core_can}
    products_out: list[dict[str, Any]] = []
    skipped_blocks: list[dict[str, str]] = []

    for b_idx, raw_bb in enumerate(effective_blocks):
        if isinstance(raw_bb, str):
            bb_id, bb_smi = f"bb_{b_idx + 1}", raw_bb
        else:
            bb_id = str(raw_bb.get("id") or f"bb_{b_idx + 1}")
            bb_smi = str(raw_bb.get("smiles") or "")
        bb_mol = Chem.MolFromSmiles(bb_smi)
        if bb_mol is None:
            skipped_blocks.append({"building_block_id": bb_id, "reason": "invalid_smiles"})
            continue
        bb_can = Chem.MolToSmiles(bb_mol, canonical=True)
        partner_sids = list(partner_lookup.get(bb_can, [])) if catalog_path is not None else []
        if catalog_path is not None:
            core_ver = bool(core_supplier_ids)
            partner_ver = bool(partner_sids)
            n_verified: int | None = int(core_ver) + int(partner_ver)
        else:
            core_ver = False
            partner_ver = False
            n_verified = None

        # Try both reactant orderings so core can act as either partner (e.g. acid or amine)
        raw_prods = list(rxn.RunReactants((core_mol, bb_mol))) + list(rxn.RunReactants((bb_mol, core_mol)))
        if not raw_prods:
            skipped_blocks.append({"building_block_id": bb_id, "reason": "no_reactive_match"})
            continue

        for p_tuple in raw_prods:
            if not p_tuple:
                continue
            pmol = p_tuple[0]
            try:
                Chem.SanitizeMol(pmol)
            except Exception:  # noqa: BLE001
                continue
            if require_neutral and Chem.GetFormalCharge(pmol) != 0:
                continue
            can = Chem.MolToSmiles(pmol, canonical=True)
            if can in seen:
                continue
            seen.add(can)
            mpo = score_drug_design_mpo(can, profile=mpo_profile)
            row: dict[str, Any] = {
                "analog_id": f"{core_id}_{reaction_name}_{bb_id}_{len(products_out) + 1}",
                "smiles": can,
                "reaction": reaction_name,
                "reaction_rationale": rxn_meta["rationale"],
                "core_id": core_id,
                "building_block_id": bb_id,
                "building_block_smiles": bb_can,
                "mpo_score": mpo["mpo_score"],
                "mw": mpo["descriptors"]["mw"],
                "clogp": mpo["descriptors"]["clogp"],
                "tpsa": mpo["descriptors"]["tpsa"],
                "fsp3": mpo["descriptors"]["fsp3"],
                "esol_log_s": mpo["descriptors"]["esol_log_s"],
                "herg_risk": mpo["herg_risk"],
                "hard_red_flags": mpo["hard_red_flags"],
                "soft_spot_count": len(mpo["metabolic_soft_spots"]),
            }
            if catalog_path is not None:
                row["core_catalog_verified"] = core_ver
                row["core_supplier_ids"] = core_supplier_ids
                row["partner_catalog_verified"] = partner_ver
                row["partner_supplier_ids"] = partner_sids
                row["catalog_verified_partners"] = n_verified
            products_out.append(row)
            if len(products_out) >= max_products:
                break
        if len(products_out) >= max_products:
            break

    products_out.sort(
        key=lambda r: (
            -(int(r.get("catalog_verified_partners") or 0)),
            -r["mpo_score"],
            r["soft_spot_count"],
            r["mw"],
        )
    )
    out: dict[str, Any] = {
        "schema": REACTION_ENUMERATION_SCHEMA,
        "core_id": core_id,
        "core_smiles": core_can,
        "reaction": reaction_name,
        "mpo_profile": mpo_profile,
        "protected_core_atom_indices": protected_set,
        "product_count": len(products_out),
        "skipped_building_blocks": skipped_blocks,
        "products": products_out,
    }
    if catalog_path is not None:
        out["catalog_db"] = str(catalog_path)
        out["catalog_sources"] = catalog_sources
        out["catalog_queried_buckets"] = queried_buckets
        out["core_catalog_verified"] = bool(core_supplier_ids)
        out["core_supplier_ids"] = core_supplier_ids
    return out


def _pareto_nondominated(rows: list[dict[str, Any]], keys: list[str]) -> set[str]:
    """Identify Pareto-nondominated candidate IDs (all objectives minimized)."""
    front: set[str] = set()
    for i, a in enumerate(rows):
        dominated = False
        for j, b in enumerate(rows):
            if i == j:
                continue
            if all(b[k] <= a[k] for k in keys) and any(b[k] < a[k] for k in keys):
                dominated = True
                break
        if not dominated:
            front.add(str(a["candidate_id"]))
    return front


def rank_evolution_generation(
    candidates: Sequence[Mapping[str, Any]],
    *,
    generation: int = 1,
    top_k: int = 6,
) -> dict[str, Any]:
    """Multi-objective Pareto selection over potency, selectivity (dddG), and soft-liability risk.

    Each candidate requires:
      - ``candidate_id`` (str)
      - ``target_dg_kcal`` (float; lower is stronger primary-target binding)
    Optional:
      - ``offtarget_dg_kcal`` (float; higher is weaker off-target binding -> better selectivity)
      - ``uncertainty_kcal`` (float, default 0.0)
      - ``soft_flag_count`` (int, default 0)
      - ``hard_red_flags`` (list[str], excluded from promotion if non-empty)
    """
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for row in candidates:
        cid = str(row["candidate_id"])
        hard = list(row.get("hard_red_flags") or [])
        dg_t = row.get("target_dg_kcal")
        if hard or dg_t is None or not math.isfinite(float(dg_t)):
            rejected.append({"candidate_id": cid, "reason": f"hard_red_flags={hard}" if hard else "missing_target_dg"})
            continue

        dg_t_f = float(dg_t)
        dg_o = row.get("offtarget_dg_kcal")
        # dddG = dG_target - dG_offtarget: more negative = MORE selective for primary target!
        dddg = round(dg_t_f - float(dg_o), 4) if (dg_o is not None and math.isfinite(float(dg_o))) else None
        unc = float(row.get("uncertainty_kcal") or 0.0)
        flags = int(row.get("soft_flag_count") or 0)
        eligible.append({
            "candidate_id": cid,
            "target_dg_kcal": round(dg_t_f, 4),
            "offtarget_dg_kcal": round(float(dg_o), 4) if dg_o is not None else None,
            "selectivity_dddg_kcal": dddg,
            "conservative_target_dg_kcal": round(dg_t_f + unc, 4),
            "uncertainty_kcal": round(unc, 4),
            "soft_flag_count": flags,
        })

    if not eligible:
        return {
            "schema": EVOLUTION_GENERATION_SCHEMA,
            "generation": int(generation),
            "eligible_count": 0,
            "rejected_count": len(rejected),
            "pareto_front": [],
            "selected_for_next_generation": [],
            "ranked": [],
            "rejected": rejected,
        }

    has_selectivity = all(r["selectivity_dddg_kcal"] is not None for r in eligible)
    pareto_keys = ["conservative_target_dg_kcal", "soft_flag_count"]
    if has_selectivity:
        pareto_keys.insert(1, "selectivity_dddg_kcal")

    front_ids = _pareto_nondominated(eligible, pareto_keys)
    for r in eligible:
        r["on_pareto_front"] = r["candidate_id"] in front_ids

    eligible.sort(
        key=lambda r: (
            0 if r["on_pareto_front"] else 1,
            r["selectivity_dddg_kcal"] if has_selectivity else 0.0,
            r["conservative_target_dg_kcal"],
            r["soft_flag_count"],
        )
    )
    selected = [r["candidate_id"] for r in eligible[: max(1, int(top_k))]]

    return {
        "schema": EVOLUTION_GENERATION_SCHEMA,
        "generation": int(generation),
        "has_selectivity_objective": has_selectivity,
        "pareto_objectives_minimized": pareto_keys,
        "eligible_count": len(eligible),
        "rejected_count": len(rejected),
        "pareto_front": sorted(front_ids),
        "selected_for_next_generation": selected,
        "ranked": eligible,
        "rejected": rejected,
    }


def prune_protocol_branches(
    branches: Sequence[Mapping[str, Any]],
    *,
    max_survivors: int = 2,
    uncertainty_z: float = DEFAULT_UNCERTAINTY_Z,
) -> dict[str, Any]:
    """Select surviving parallel protocol branches with LCB/UCB uncertainty protection.

    Each branch record requires:
      - ``branch_id`` (str)
      - ``gate_passed`` (bool)
      - ``primary_score`` (float, higher is better, e.g. AUC or -median_rmsd)
    Optional:
      - ``score_se`` (float >= 0.0, standard error of ``primary_score``; default 0.0)
      - ``n_evals`` (int, number of samples/replicas backing ``primary_score``)
      - ``gpu_min_spent`` (float, default 1.0)
      - ``gpus_leased`` (list[int])
      - ``failure_reason`` (str)

    Branches failing hard physical gates are always pruned immediately. Among passing branches,
    the top ``max_survivors`` always survive; any lower-ranked branch with ``score_se > 0`` whose
    upper confidence bound ``primary_score + z * score_se`` still meets or exceeds the cutoff
    survivor's lower confidence bound ``cutoff_lcb`` is retained under
    ``survival_reason="uncertainty_overlap_protected"`` rather than prematurely killed on noise.
    """
    if uncertainty_z < 0:
        raise ValueError(f"uncertainty_z must be >= 0, got {uncertainty_z!r}")

    passing: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    freed_gpus: list[int] = []

    for b in branches:
        bid = str(b["branch_id"])
        passed = bool(b.get("gate_passed"))
        score = b.get("primary_score")
        cost = max(float(b.get("gpu_min_spent") or 1.0), 0.01)
        leased = [int(g) for g in (b.get("gpus_leased") or [])]

        if not passed or score is None or not math.isfinite(float(score)):
            pruned.append({
                "branch_id": bid,
                "reason": str(b.get("failure_reason") or "failed_physical_gate"),
                "gpus_freed": leased,
            })
            freed_gpus.extend(leased)
            continue

        score_f = float(score)
        se_raw = b.get("score_se")
        se = max(0.0, float(se_raw)) if (se_raw is not None and math.isfinite(float(se_raw))) else 0.0
        n_evals = int(b["n_evals"]) if b.get("n_evals") is not None else None
        passing.append({
            "branch_id": bid,
            "primary_score": round(score_f, 4),
            "score_se": round(se, 4),
            "score_lcb": round(score_f - uncertainty_z * se, 4),
            "score_ucb": round(score_f + uncertainty_z * se, 4),
            "n_evals": n_evals,
            "gpu_min_spent": round(cost, 2),
            "gpus_leased": leased,
        })

    passing.sort(key=lambda r: (-r["primary_score"], r["score_se"], r["gpu_min_spent"]))
    k = max(1, int(max_survivors))
    kept: list[dict[str, Any]] = []
    uncertain_protected: list[str] = []

    for row in passing[:k]:
        kept.append({**row, "survival_reason": "top_survivor"})

    cutoff_lcb = kept[-1]["score_lcb"] if kept else -math.inf

    for cand in passing[k:]:
        if cand["score_se"] > 0.0 and cand["score_ucb"] >= cutoff_lcb:
            kept.append({**cand, "survival_reason": "uncertainty_overlap_protected"})
            uncertain_protected.append(cand["branch_id"])
        else:
            pruned.append({
                "branch_id": cand["branch_id"],
                "reason": (
                    "statistically_dominated_below_lcb"
                    if cand["score_se"] > 0.0
                    else "dominated_by_higher_scoring_branch"
                ),
                "gpus_freed": cand["gpus_leased"],
            })
            freed_gpus.extend(cand["gpus_leased"])

    return {
        "schema": PROTOCOL_TOURNAMENT_SCHEMA,
        "uncertainty_z": float(uncertainty_z),
        "cutoff_lcb": round(cutoff_lcb, 4) if math.isfinite(cutoff_lcb) else None,
        "total_branches": len(branches),
        "survivor_count": len(kept),
        "uncertain_protected_branches": uncertain_protected,
        "pruned_count": len(pruned),
        "survivors": kept,
        "pruned": pruned,
        "freed_gpus": sorted(set(freed_gpus)),
    }


__all__ = [
    "BIOISOSTERE_MUTATIONS",
    "DEFAULT_UNCERTAINTY_Z",
    "EVOLUTION_GENERATION_SCHEMA",
    "MEDCHEM_REACTIONS",
    "PROTOCOL_TOURNAMENT_SCHEMA",
    "REACTION_ENUMERATION_SCHEMA",
    "enumerate_reaction_analogs",
    "generate_bioisostere_analogs",
    "prune_protocol_branches",
    "rank_evolution_generation",
]
