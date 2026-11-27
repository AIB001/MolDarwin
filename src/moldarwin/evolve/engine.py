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
from typing import Any

EVOLUTION_GENERATION_SCHEMA = "moldarwin-evolution-generation/1"
PROTOCOL_TOURNAMENT_SCHEMA = "moldarwin-protocol-tournament/1"

#: Default z-multiplier for branch confidence-interval overlap protection (~95% CI, Evidence: convention).
DEFAULT_UNCERTAINTY_Z: float = 1.96

#: Clean neutral medicinal-chemistry bioisostere & R-group mutation SMIRKS (Evidence: literature).
#: All preserve formal neutrality so analogs remain directly eligible for neutral RBFE networks.
BIOISOSTERE_MUTATIONS: tuple[dict[str, str], ...] = (
    {
        "name": "nitro_to_cyano",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]C#N",
        "rationale": "Replace nitroaromatic liability with polar, metabolically stable nitrile.",
    },
    {
        "name": "nitro_to_cf3",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]C(F)(F)F",
        "rationale": "Replace nitroaromatic with electron-withdrawing -CF3 bioisostere.",
    },
    {
        "name": "nitro_to_methylsulfone",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]S(=O)(=O)C",
        "rationale": "Replace nitroaromatic with H-bond-accepting sulfone while lowering cLogP.",
    },
    {
        "name": "nitro_to_carboxamide",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]C(=O)N",
        "rationale": "Replace nitroaromatic with polar H-bond donor/acceptor carboxamide.",
    },
    {
        "name": "nitro_to_fluoro",
        "smirks": "[c:1][$([NX3](=O)=O),$([NX3+](=O)[O-])]>>[c:1]F",
        "rationale": "Compact electron-withdrawing fluoro replacement.",
    },
    {
        "name": "chloro_to_fluoro",
        "smirks": "[c:1]Cl>>[c:1]F",
        "rationale": "Trim lipophilicity and steric bulk on chloroaryl ring.",
    },
    {
        "name": "chloro_to_methyl",
        "smirks": "[c:1]Cl>>[c:1]C",
        "rationale": "Classic Cl -> Me steric/electronic probe for hydrophobic subpockets.",
    },
    {
        "name": "chloro_to_cyano",
        "smirks": "[c:1]Cl>>[c:1]C#N",
        "rationale": "Polar nitrile substitution probing directional H-bond acceptors.",
    },
    {
        "name": "methyl_to_ethyl",
        "smirks": "[c:1][CH3]>>[c:1]CC",
        "rationale": "Small hydrophobic growth probing subpocket depth.",
    },
    {
        "name": "methyl_to_methoxy",
        "smirks": "[c:1][CH3]>>[c:1]OC",
        "rationale": "Introduce polar H-bond acceptor oxygen on aryl substituent.",
    },
    {
        "name": "methyl_to_fluoro",
        "smirks": "[c:1][CH3]>>[c:1]F",
        "rationale": "Block benzylic metabolic oxidation with fluorine.",
    },
    {
        "name": "aryl_ch_to_fluoro",
        "smirks": "[cH1:1]>>[c:1]F",
        "rationale": "Single aromatic fluorine scan for metabolic blocking and dipole tuning.",
    },
)


def generate_bioisostere_analogs(
    parent_smiles: str,
    *,
    parent_id: str = "parent",
    max_analogs: int = 24,
    include_ch_scan: bool = False,
    target_class: str = "general",
    sar_mutation_weights: Mapping[str, float] | None = None,
    custom_mutations: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Generate deduplicated, neutral, synthesizable R-group/bioisostere analogs of a parent lead.

    Optional target-adaptive inputs:
      - ``sar_mutation_weights``: mapping of ``mutation_name -> priority_weight`` learned from
        empirical target MMP/SAR data (higher weights are expanded first under ``max_analogs``).
      - ``custom_mutations``: additional target-specific neutral SMIRKS rules
        (``{"name", "smirks", "rationale"}``) evaluated alongside built-ins.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    from moldarwin.physics.preflight import annotate_medchem_liabilities

    parent = Chem.MolFromSmiles(parent_smiles)
    if parent is None:
        raise ValueError(f"invalid parent SMILES: {parent_smiles!r}")
    parent_can = Chem.MolToSmiles(parent, canonical=True)
    parent_charge = Chem.GetFormalCharge(parent)

    weights = {str(k): float(v) for k, v in (sar_mutation_weights or {}).items()}
    rule_pool: list[tuple[int, dict[str, str], str]] = []
    idx = 0
    for rule in custom_mutations:
        rule_pool.append((idx, {
            "name": str(rule["name"]),
            "smirks": str(rule["smirks"]),
            "rationale": str(rule.get("rationale") or "target-specific SAR transform"),
        }, "target_custom"))
        idx += 1
    for rule in BIOISOSTERE_MUTATIONS:
        if rule["name"] == "aryl_ch_to_fluoro" and not include_ch_scan:
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
        "sar_weighted": bool(weights),
        "custom_rule_count": len(custom_mutations),
        "analog_count": len(analogs),
        "analogs": analogs,
    }


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
    "PROTOCOL_TOURNAMENT_SCHEMA",
    "generate_bioisostere_analogs",
    "prune_protocol_branches",
    "rank_evolution_generation",
]
