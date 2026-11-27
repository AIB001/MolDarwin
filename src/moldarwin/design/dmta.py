"""First-principles DMTA drug-design scoring and decision theory:
LLE/MPO profiling, metabolic soft-spot triage, uncertainty-aware multi-objective EHVI,
and Graph-Laplacian A-optimal batch & bridge selection.

Designed to work hand-in-hand with MolCat's 53 plugins (ADMET-AI, OpenADMET, Lilly rules,
AiZynthFinder, Boltz2, specificity panel): seamlessly ingests MolCat plugin readouts when
present and honestly marks unexecuted plugins as ``not_run`` (Hard Constraint 7).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

MPO_PROFILE_SCHEMA = "moldarwin-drug-design-mpo/1"
EHVI_RANKING_SCHEMA = "moldarwin-multi-objective-ehvi/1"
A_OPTIMAL_DMTA_SCHEMA = "moldarwin-a-optimal-dmta/1"
DESIGN_DOSSIER_SCHEMA = "moldarwin-design-dossier/1"

#: RT * ln(10) at 298.15 K in kcal/mol (Evidence: literature).
RT_LN10_298K_KCAL: float = 1.3642

#: Actionable metabolic soft-spot & hERG risk SMARTS with targeted medchem fixes (Evidence: literature).
_METABOLIC_SOFT_SPOTS: tuple[tuple[str, str, str], ...] = (
    (
        "benzylic_ch",
        "[c][CH3,CH2][!#7;!#8;!F;!Cl;!Br]",
        "CYP benzylic oxidation soft-spot: block with -CF3, -F, gem-difluoro, or cyclopropyl.",
    ),
    (
        "aryl_methyl_benzylic",
        "[c][CH3]",
        "Aryl methyl CYP oxidation soft-spot: consider -CF3, -F, -Cl, or -cPr bioisostere.",
    ),
    (
        "aryl_methoxy_odealkylation",
        "[c]O[CH3]",
        "CYP O-dealkylation soft-spot: consider -OCF3, -OCHF2, or -F/-CN replacement.",
    ),
    (
        "unsubstituted_para_phenyl",
        "[cH1]1[cH1][cH1]c([!#1])[cH1][cH1]1",
        "Para-hydroxylation soft-spot on monosubstituted phenyl: block para position with -F or pyridyl N.",
    ),
    (
        "electron_rich_aniline",
        "[NX3H2,NX3H1][c]1[c][c][c][c][c]1",
        "Aniline oxidation/reactive-metabolite alert: consider 2-aminopyridine or amide/urea attenuation.",
    ),
    (
        "thioether_sulfoxidation",
        "[#6][SX2][#6]",
        "Thioether S-oxidation soft-spot: evaluate sulfone (-SO2-) or ether (-O-) bioisostere.",
    ),
    (
        "basic_aliphatic_amine",
        "[NX3;H2,H1,H0;!$(NC=O);!$(NS=O);!$(N=*)][CX4]",
        "Basic amine center: monitor hERG risk when cLogP > 3.0; attenuate pKa with beta-F or morpholine.",
    ),
)

_HARD_INSTABILITY_SMARTS: tuple[tuple[str, str], ...] = (
    ("acyl_halide", "[CX3](=[OX1])[F,Cl,Br,I]"),
    ("sulfonyl_halide", "[SX4](=[OX1])(=[OX1])[F,Cl,Br,I]"),
    ("peroxide", "[OX2][OX2]"),
    ("isocyanate_isothiocyanate", "[NX2]=[CX2]=[OX1,SX1]"),
)


def _desirability_trapezoid(
    x: float, low_zero: float, low_one: float, high_one: float, high_zero: float
) -> float:
    """Smooth piecewise-linear desirability function in [0, 1]."""
    if x <= low_zero or x >= high_zero:
        return 0.0
    if low_one <= x <= high_one:
        return 1.0
    if x < low_one:
        return (x - low_zero) / max(low_one - low_zero, 1e-9)
    return (high_zero - x) / max(high_zero - high_one, 1e-9)


def _desirability_upper(x: float, ideal_max: float, zero_at: float) -> float:
    """Desirability = 1 for x <= ideal_max, decaying linearly to 0 at zero_at."""
    if x <= ideal_max:
        return 1.0
    if x >= zero_at:
        return 0.0
    return (zero_at - x) / max(zero_at - ideal_max, 1e-9)


def _desirability_lower(x: float, zero_at: float, ideal_min: float) -> float:
    """Desirability = 0 for x <= zero_at, rising linearly to 1 at ideal_min."""
    if x >= ideal_min:
        return 1.0
    if x <= zero_at:
        return 0.0
    return (x - zero_at) / max(ideal_min - zero_at, 1e-9)


def score_drug_design_mpo(
    smiles: str,
    *,
    target_dg_kcal: float | None = None,
    offtarget_dg_kcal: float | None = None,
    profile: str = "oral",
    molcat_annotations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute medicinal-chemistry efficiency (LE/LLE/LELP), continuous MPO, ESOL, hERG, and soft spots.

    Profiles (Evidence: literature / convention):
      - ``"oral"``: smooth oral small-molecule MPO (MW, cLogP, TPSA, HBD, RotBonds, Fsp3).
      - ``"cns"``: Wager et al. (2016) CNS MPO desirability normalized to [0, 1].
      - ``"ppi_bro5"``: non-destructive beyond-Ro5 PPI profile tolerating MW up to 750.
    """
    from rdkit import Chem
    from rdkit.Chem import QED, Descriptors, FilterCatalog, Lipinski, rdMolDescriptors

    if profile not in {"oral", "cns", "ppi_bro5"}:
        raise ValueError(f"unknown MPO profile {profile!r}; expected 'oral', 'cns', or 'ppi_bro5'")

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"invalid SMILES: {smiles!r}")
    can_smiles = Chem.MolToSmiles(mol, canonical=True)

    mw = float(Descriptors.MolWt(mol))
    clogp = float(Descriptors.MolLogP(mol))
    tpsa = float(Descriptors.TPSA(mol))
    hbd = int(Lipinski.NumHDonors(mol))
    hba = int(Lipinski.NumHAcceptors(mol))
    rotb = int(Lipinski.NumRotatableBonds(mol))
    heavy = int(mol.GetNumHeavyAtoms())
    fsp3 = float(rdMolDescriptors.CalcFractionCSP3(mol))
    qed_val = float(QED.qed(mol))
    arom_rings = int(rdMolDescriptors.CalcNumAromaticRings(mol))
    arom_atoms = sum(1 for a in mol.GetAtoms() if a.GetIsAromatic())
    arom_prop = arom_atoms / max(heavy, 1)
    formal_charge = int(Chem.GetFormalCharge(mol))

    # Delaney (2004) ESOL logS (mol/L) aqueous solubility estimator (Evidence: literature).
    esol_log_s = 0.16 - 0.63 * clogp - 0.0062 * mw + 0.066 * rotb - 0.74 * arom_prop

    # Hard instabilities + PAINS + metabolic soft-spots
    hard_flags = [
        name for name, sm in _HARD_INSTABILITY_SMARTS
        if (pat := Chem.MolFromSmarts(sm)) is not None and mol.HasSubstructMatch(pat)
    ]
    params = FilterCatalog.FilterCatalogParams()
    params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    has_pains = FilterCatalog.FilterCatalog(params).HasMatch(mol)

    soft_spots: list[dict[str, str]] = []
    has_basic_amine = False
    for name, sm, remedy in _METABOLIC_SOFT_SPOTS:
        pat = Chem.MolFromSmarts(sm)
        if pat is not None and mol.HasSubstructMatch(pat):
            if name == "basic_aliphatic_amine":
                has_basic_amine = True
            soft_spots.append({"motif": name, "remedy": remedy})

    # hERG risk heuristic (basic amine + elevated lipophilicity, Evidence: literature)
    herg_risk = (
        "high" if (has_basic_amine and clogp > 3.5)
        else ("moderate" if (has_basic_amine and clogp > 2.5) or clogp > 5.0 else "low")
    )

    # Profile-specific continuous MPO desirability components in [0, 1]
    if profile == "cns":
        # Wager et al. (ACS Chem. Neurosci. 2016) 6-component CNS MPO normalized to [0, 1]
        comps = {
            "clogp": _desirability_upper(clogp, 3.0, 5.0),
            "mw": _desirability_upper(mw, 360.0, 500.0),
            "tpsa": _desirability_trapezoid(tpsa, 20.0, 40.0, 90.0, 120.0),
            "hbd": _desirability_upper(float(hbd), 0.5, 3.5),
            "basic_pka_proxy": 0.4 if (has_basic_amine and clogp > 3.0) else (0.75 if has_basic_amine else 1.0),
            "esol_solubility": _desirability_lower(esol_log_s, -6.0, -3.5),
        }
    elif profile == "ppi_bro5":
        comps = {
            "mw": _desirability_upper(mw, 650.0, 850.0),
            "clogp": _desirability_trapezoid(clogp, -0.5, 1.0, 4.5, 6.5),
            "tpsa": _desirability_trapezoid(tpsa, 30.0, 60.0, 150.0, 200.0),
            "hbd": _desirability_upper(float(hbd), 4.0, 7.0),
            "rotb": _desirability_upper(float(rotb), 10.0, 16.0),
            "esol_solubility": _desirability_lower(esol_log_s, -7.0, -4.0),
        }
    else:  # oral
        comps = {
            "mw": _desirability_upper(mw, 420.0, 560.0),
            "clogp": _desirability_trapezoid(clogp, -0.5, 1.0, 3.5, 5.2),
            "tpsa": _desirability_trapezoid(tpsa, 20.0, 45.0, 110.0, 145.0),
            "hbd": _desirability_upper(float(hbd), 2.0, 5.0),
            "rotb": _desirability_upper(float(rotb), 7.0, 12.0),
            "fsp3": _desirability_lower(fsp3, 0.05, 0.35),
            "esol_solubility": _desirability_lower(esol_log_s, -6.0, -3.0),
        }

    mpo_raw = sum(comps.values()) / len(comps)
    if has_pains:
        mpo_raw *= 0.85
    if herg_risk == "high":
        mpo_raw *= 0.85

    # Potency & selectivity efficiency metrics when binding energies are supplied
    efficiency: dict[str, float | None] = {
        "pki": None,
        "le_kcal_per_ha": None,
        "lle_lipe": None,
        "lelp": None,
        "selectivity_dddg_kcal": None,
        "selectivity_fold": None,
    }
    if target_dg_kcal is not None and math.isfinite(float(target_dg_kcal)):
        dg_t = float(target_dg_kcal)
        pki = -dg_t / RT_LN10_298K_KCAL
        le = -dg_t / max(heavy, 1)
        lle = pki - clogp
        lelp = (clogp / le) if le > 1e-6 else None
        efficiency["pki"] = round(pki, 3)
        efficiency["le_kcal_per_ha"] = round(le, 4)
        efficiency["lle_lipe"] = round(lle, 3)
        efficiency["lelp"] = round(lelp, 3) if lelp is not None else None
        if offtarget_dg_kcal is not None and math.isfinite(float(offtarget_dg_kcal)):
            dddg = dg_t - float(offtarget_dg_kcal)
            efficiency["selectivity_dddg_kcal"] = round(dddg, 4)
            efficiency["selectivity_fold"] = round(10.0 ** (-dddg / RT_LN10_298K_KCAL), 2)

    # Honest MolCat plugin integration (never fabricate unexecuted ADMET/retrosynthesis!)
    if molcat_annotations:
        molcat_summary: dict[str, Any] = {
            "status": "supplied",
            "annotations": dict(molcat_annotations),
        }
        # Derive normalized synthesis score in [0, 1] when MolCat supplied SA/SC/AiZynth
        synth_score: float | None = None
        if "aizynth_solved" in molcat_annotations:
            solved = bool(molcat_annotations["aizynth_solved"])
            steps = float(molcat_annotations.get("aizynth_steps") or 4.0)
            synth_score = (0.95 - 0.1 * max(0.0, steps - 1.0)) if solved else 0.15
        elif "sa_score" in molcat_annotations:
            sa = float(molcat_annotations["sa_score"])
            synth_score = _desirability_upper(sa, 3.0, 7.0)
        elif "scscore" in molcat_annotations:
            sc = float(molcat_annotations["scscore"])
            synth_score = _desirability_upper(sc, 2.5, 4.8)
        molcat_summary["synthesis_score"] = (
            round(max(0.0, min(1.0, synth_score)), 4) if synth_score is not None else None
        )
    else:
        molcat_summary = {
            "status": "not_run",
            "note": (
                "Run MolCat plugins (ADMETAIV2 / OpenADMET / LillyMedchem / AiZynthFinder / "
                "RDKitSAScore / ScScore) for full ADMET and retrosynthesis verification."
            ),
            "synthesis_score": None,
        }

    return {
        "schema": MPO_PROFILE_SCHEMA,
        "smiles": can_smiles,
        "profile": profile,
        "mpo_score": round(max(0.0, min(1.0, mpo_raw)), 4),
        "mpo_components": {k: round(v, 4) for k, v in comps.items()},
        "descriptors": {
            "mw": round(mw, 2),
            "clogp": round(clogp, 3),
            "tpsa": round(tpsa, 2),
            "hbd": hbd,
            "hba": hba,
            "rotatable_bonds": rotb,
            "heavy_atoms": heavy,
            "aromatic_rings": arom_rings,
            "fsp3": round(fsp3, 3),
            "qed": round(qed_val, 4),
            "esol_log_s": round(esol_log_s, 3),
            "formal_charge": formal_charge,
        },
        "efficiency": efficiency,
        "hard_red_flags": hard_flags,
        "has_pains": has_pains,
        "herg_risk": herg_risk,
        "metabolic_soft_spots": soft_spots,
        "molcat_plugins": molcat_summary,
    }


def _pareto_front_indices(points: np.ndarray) -> list[int]:
    """Return indices of Pareto-nondominated rows (all columns minimized)."""
    n = len(points)
    front: list[int] = []
    for i in range(n):
        dominated = False
        for j in range(n):
            if i == j:
                continue
            if np.all(points[j] <= points[i]) and np.any(points[j] < points[i]):
                dominated = True
                break
        if not dominated:
            front.append(i)
    return front


def _monte_carlo_hv(
    front_pts: np.ndarray,
    lower_bound: np.ndarray,
    ref_point: np.ndarray,
    probe_samples: np.ndarray,
) -> float:
    """Estimate dominated hypervolume inside [lower_bound, ref_point] via shared box probes."""
    if len(front_pts) == 0:
        return 0.0
    dominated = np.any(np.all(front_pts[None, :, :] <= probe_samples[:, None, :], axis=2), axis=1)
    box_vol = float(np.prod(ref_point - lower_bound))
    return float(np.mean(dominated)) * box_vol


def rank_candidates_ehvi(
    candidates: Sequence[Mapping[str, Any]],
    *,
    observed_pareto_points: Sequence[Mapping[str, Any]] | None = None,
    n_mc: int = 256,
    n_hv_probes: int = 2048,
    seed: int = 42,
    top_k: int = 6,
) -> dict[str, Any]:
    """Uncertainty-aware Multi-Objective Expected Hypervolume Improvement (EHVI) ranking.

    Jointly optimizes (all minimized after normalization to [0, 1]):
      - ``target_dg_kcal`` (required; uncertainty ``target_dg_se`` / ``uncertainty_kcal``)
      - ``selectivity_dddg_kcal`` (optional; included when present on all eligible candidates)
      - ``mpo_score`` (optional; maximized -> minimized as ``1 - mpo_score``)
      - ``synthesis_score`` (optional; maximized -> minimized as ``1 - synthesis_score``)

    Hard chemical instabilities (non-empty ``hard_red_flags``) are excluded cleanly; soft
    liabilities never cause silent deletion.
    """
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for row in candidates:
        cid = str(row["candidate_id"])
        hard = list(row.get("hard_red_flags") or [])
        dg = row.get("target_dg_kcal")
        if hard or dg is None or not math.isfinite(float(dg)):
            rejected.append({
                "candidate_id": cid,
                "reason": f"hard_red_flags={hard}" if hard else "missing_target_dg",
            })
            continue
        dg_f = float(dg)
        dg_se = max(0.0, float(row.get("target_dg_se") or row.get("uncertainty_kcal") or 0.0))
        dddg = row.get("selectivity_dddg_kcal")
        if dddg is None and row.get("offtarget_dg_kcal") is not None:
            dddg = dg_f - float(row["offtarget_dg_kcal"])
        dddg_f = float(dddg) if (dddg is not None and math.isfinite(float(dddg))) else None
        dddg_se = max(0.0, float(row.get("selectivity_dddg_se") or 0.0))
        mpo = row.get("mpo_score")
        mpo_f = float(mpo) if (mpo is not None and math.isfinite(float(mpo))) else None
        mpo_se = max(0.0, float(row.get("mpo_se") or 0.0))
        synth = row.get("synthesis_score")
        synth_f = float(synth) if (synth is not None and math.isfinite(float(synth))) else None
        synth_se = max(0.0, float(row.get("synthesis_se") or 0.0))

        eligible.append({
            "candidate_id": cid,
            "target_dg_kcal": dg_f,
            "target_dg_se": dg_se,
            "selectivity_dddg_kcal": dddg_f,
            "selectivity_dddg_se": dddg_se,
            "mpo_score": mpo_f,
            "mpo_se": mpo_se,
            "synthesis_score": synth_f,
            "synthesis_se": synth_se,
        })

    if not eligible:
        return {
            "schema": EHVI_RANKING_SCHEMA,
            "eligible_count": 0,
            "rejected_count": len(rejected),
            "objectives": [],
            "pareto_front": [],
            "selected_top_k": [],
            "ranked": [],
            "rejected": rejected,
        }

    use_sel = all(r["selectivity_dddg_kcal"] is not None for r in eligible)
    use_mpo = all(r["mpo_score"] is not None for r in eligible)
    use_synth = all(r["synthesis_score"] is not None for r in eligible)

    objectives = ["target_dg_kcal"]
    if use_sel:
        objectives.append("selectivity_dddg_kcal")
    if use_mpo:
        objectives.append("neg_mpo_score")
    if use_synth:
        objectives.append("neg_synthesis_score")

    def _extract_raw(rows_in: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
        means_l, sds_l = [], []
        for r in rows_in:
            m = [float(r["target_dg_kcal"])]
            s = [max(0.0, float(r.get("target_dg_se") or r.get("uncertainty_kcal") or 0.0))]
            if use_sel:
                val = r.get("selectivity_dddg_kcal")
                if val is None and r.get("offtarget_dg_kcal") is not None:
                    val = float(r["target_dg_kcal"]) - float(r["offtarget_dg_kcal"])
                m.append(float(val))
                s.append(max(0.0, float(r.get("selectivity_dddg_se") or 0.0)))
            if use_mpo:
                m.append(1.0 - float(r["mpo_score"]))
                s.append(max(0.0, float(r.get("mpo_se") or 0.0)))
            if use_synth:
                m.append(1.0 - float(r["synthesis_score"]))
                s.append(max(0.0, float(r.get("synthesis_se") or 0.0)))
            means_l.append(m)
            sds_l.append(s)
        return np.array(means_l, dtype=float), np.array(sds_l, dtype=float)

    cand_mu, cand_sd = _extract_raw(eligible)
    if observed_pareto_points:
        obs_mu, _ = _extract_raw(observed_pareto_points)
        all_pts = np.vstack([cand_mu, obs_mu])
    else:
        obs_mu = None
        all_pts = cand_mu

    mins = np.min(all_pts, axis=0)
    maxs = np.max(all_pts, axis=0)
    spans = np.where((maxs - mins) > 1e-8, maxs - mins, 1.0)

    cand_norm = (cand_mu - mins) / spans
    sd_norm = cand_sd / spans
    ref_pt = np.full(cand_norm.shape[1], 1.15, dtype=float)
    # Extend the lower integration bound below 0 by 3*max(sd_norm) so posterior draws that beat
    # the current best point along any objective yield strictly positive hypervolume improvement.
    lower_bound = np.minimum(-0.15, np.min(cand_norm - 3.0 * sd_norm, axis=0))
    box_vol = float(np.prod(ref_pt - lower_bound))

    rng = np.random.default_rng(seed)
    probes = rng.uniform(lower_bound, ref_pt, size=(n_hv_probes, cand_norm.shape[1]))

    mean_front_idx = set(_pareto_front_indices(cand_norm))

    if obs_mu is not None:
        obs_norm = (obs_mu - mins) / spans
        base_front = obs_norm[_pareto_front_indices(obs_norm)]
        base_hv = _monte_carlo_hv(base_front, lower_bound, ref_pt, probes)
    else:
        base_front = None
        base_hv = None

    ranked_rows: list[dict[str, Any]] = []
    for i, rec in enumerate(eligible):
        # Reference front against which candidate i's incremental HV gain is measured
        if base_front is not None:
            ref_front = base_front
            ref_hv = float(base_hv)
        else:
            others = np.delete(cand_norm, i, axis=0)
            if len(others) > 0:
                ref_front = others[_pareto_front_indices(others)]
                ref_hv = _monte_carlo_hv(ref_front, lower_bound, ref_pt, probes)
            else:
                ref_front = np.zeros((0, cand_norm.shape[1]))
                ref_hv = 0.0

        # Draw posterior samples for candidate i
        if np.any(sd_norm[i] > 1e-9):
            samples = rng.normal(loc=cand_norm[i], scale=sd_norm[i], size=(n_mc, cand_norm.shape[1]))
        else:
            samples = cand_norm[i : i + 1]

        # Precompute probes NOT already dominated by ref_front (huge speedup + exact!)
        if len(ref_front) > 0:
            undom_mask = ~np.any(np.all(ref_front[None, :, :] <= probes[:, None, :], axis=2), axis=1)
            free_probes = probes[undom_mask]
        else:
            free_probes = probes

        if len(free_probes) > 0:
            # For each posterior draw s, fraction of total box newly dominated by sample s
            newly_dom = np.all(samples[:, None, :] <= free_probes[None, :, :], axis=2)  # (S, M_free)
            gains = (np.sum(newly_dom, axis=1) / float(n_hv_probes)) * box_vol
            ehvi = float(np.mean(gains))
        else:
            ehvi = 0.0

        # Probability sample i is non-dominated by ref_front
        if len(ref_front) > 0:
            dom_by_ref = np.any(
                np.all(ref_front[None, :, :] <= samples[:, None, :], axis=2)
                & np.any(ref_front[None, :, :] < samples[:, None, :], axis=2),
                axis=1,
            )
            p_nondom = float(np.mean(~dom_by_ref))
        else:
            p_nondom = 1.0

        ranked_rows.append({
            **rec,
            "on_mean_pareto_front": i in mean_front_idx,
            "ehvi": round(ehvi, 5),
            "pareto_probability": round(p_nondom, 4),
            "baseline_hv": round(ref_hv, 5),
        })

    ranked_rows.sort(
        key=lambda r: (
            -r["ehvi"],
            -r["pareto_probability"],
            r["target_dg_kcal"],
        )
    )
    return {
        "schema": EHVI_RANKING_SCHEMA,
        "eligible_count": len(eligible),
        "rejected_count": len(rejected),
        "objectives_minimized": objectives,
        "pareto_front": sorted(eligible[i]["candidate_id"] for i in mean_front_idx),
        "selected_top_k": [r["candidate_id"] for r in ranked_rows[: max(1, int(top_k))]],
        "ranked": ranked_rows,
        "rejected": rejected,
    }


def select_a_optimal_dmta_batch(
    candidates: Sequence[Mapping[str, Any]],
    *,
    measured_ids: Sequence[str] = (),
    budget: int = 5,
    exploration_weight: float = 0.45,
    similarity_cutoff: float = 0.45,
    ridge: float = 0.05,
    obs_precision: float = 4.0,
) -> dict[str, Any]:
    """Graph-Laplacian A-optimal DMTA batch selection balancing EHVI utility and SAR information.

    Uses exact Sherman-Morrison rank-1 covariance updates on the molecular Morgan-Tanimoto
    Laplacian ``(L_G + W_obs + ridge * I)^{-1}`` to pick the minimal budget-B batch that
    maximizes combined utility + posterior variance reduction across the whole chemical series,
    while explicitly flagging disconnected singletons (ABFE/bridge needed vs RBFE-connected).

    Each candidate requires ``candidate_id`` (str) and ``smiles`` (str). Optional utility
    signals: ``ehvi`` (float), ``target_dg_kcal`` (float), ``mpo_score`` (float).
    """
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator

    if budget < 1:
        raise ValueError("budget must be >= 1")
    if not 0.0 <= exploration_weight <= 1.0:
        raise ValueError("exploration_weight must be in [0, 1]")

    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    valid_rows: list[dict[str, Any]] = []
    fps: list[Any] = []
    for row in candidates:
        cid = str(row["candidate_id"])
        mol = Chem.MolFromSmiles(str(row["smiles"]))
        if mol is None:
            continue
        valid_rows.append(dict(row, candidate_id=cid))
        fps.append(gen.GetFingerprint(mol))

    n = len(valid_rows)
    if n == 0:
        raise ValueError("no valid candidates supplied")

    id_to_idx = {r["candidate_id"]: i for i, r in enumerate(valid_rows)}
    measured_set = {cid for cid in measured_ids if cid in id_to_idx}

    # Build molecular similarity graph & Laplacian L = D - W
    sim_mat = np.zeros((n, n), dtype=float)
    adj: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            s = float(DataStructs.TanimotoSimilarity(fps[i], fps[j]))
            if s >= similarity_cutoff:
                sim_mat[i, j] = sim_mat[j, i] = s
                adj[i].append(j)
                adj[j].append(i)

    # Connected-component analysis (surfaces RBFE-connected clusters vs ABFE singletons!)
    visited = [False] * n
    components: list[list[str]] = []
    comp_id_by_idx: dict[int, int] = {}
    for i in range(n):
        if visited[i]:
            continue
        comp: list[int] = []
        q: deque[int] = deque([i])
        visited[i] = True
        while q:
            u = q.popleft()
            comp.append(u)
            for v in adj[u]:
                if not visited[v]:
                    visited[v] = True
                    q.append(v)
        c_idx = len(components)
        for u in comp:
            comp_id_by_idx[u] = c_idx
        components.append([valid_rows[u]["candidate_id"] for u in comp])

    measured_comps = {comp_id_by_idx[id_to_idx[cid]] for cid in measured_set}

    laplacian = np.diag(np.sum(sim_mat, axis=1)) - sim_mat
    prec = laplacian + ridge * np.eye(n)
    for cid in measured_set:
        idx = id_to_idx[cid]
        prec[idx, idx] += obs_precision
    cov = np.linalg.inv(prec)
    initial_trace = float(np.trace(cov))

    # Build normalized exploitation utility per candidate
    raw_u = np.zeros(n, dtype=float)
    for i, r in enumerate(valid_rows):
        if r.get("ehvi") is not None:
            raw_u[i] = float(r["ehvi"])
        elif r.get("target_dg_kcal") is not None:
            raw_u[i] = -float(r["target_dg_kcal"]) + 2.0 * float(r.get("mpo_score") or 0.0)
        else:
            raw_u[i] = float(r.get("mpo_score") or 0.0)
    u_min, u_max = float(np.min(raw_u)), float(np.max(raw_u))
    u_norm = (raw_u - u_min) / (u_max - u_min) if (u_max - u_min) > 1e-12 else np.ones(n)

    pool = [i for i in range(n) if valid_rows[i]["candidate_id"] not in measured_set]
    selected: list[dict[str, Any]] = []

    for step in range(min(int(budget), len(pool))):
        # Exact Sherman-Morrison A-optimal trace reduction for every remaining candidate
        gains = {}
        for k in pool:
            col = cov[:, k]
            denom = 1.0 + obs_precision * float(cov[k, k])
            gains[k] = float(obs_precision * float(np.dot(col, col)) / max(denom, 1e-12))

        max_g = max(gains.values()) if gains else 1.0
        best_k = max(
            pool,
            key=lambda k: (
                (1.0 - exploration_weight) * float(u_norm[k])
                + exploration_weight * (gains[k] / max(max_g, 1e-12)),
                gains[k],
                -k,
            ),
        )
        col = cov[:, best_k]
        denom = 1.0 + obs_precision * float(cov[best_k, best_k])
        cov = cov - (obs_precision / max(denom, 1e-12)) * np.outer(col, col)
        pool.remove(best_k)

        cid = valid_rows[best_k]["candidate_id"]
        c_idx = comp_id_by_idx[best_k]
        has_measured_anchor = c_idx in measured_comps
        measured_comps.add(c_idx)
        fep_mode = (
            "rbfe_connected_to_anchor"
            if (has_measured_anchor and len(components[c_idx]) >= 2)
            else ("rbfe_new_series_anchor" if len(components[c_idx]) >= 2 else "abfe_or_bridge_needed")
        )
        selected.append({
            "step": step + 1,
            "candidate_id": cid,
            "smiles": valid_rows[best_k]["smiles"],
            "a_optimal_trace_reduction": round(gains[best_k], 5),
            "normalized_utility": round(float(u_norm[best_k]), 4),
            "component_id": c_idx,
            "component_size": len(components[c_idx]),
            "recommended_fep_mode": fep_mode,
        })

    final_trace = float(np.trace(cov))
    singletons = [comp[0] for comp in components if len(comp) == 1]
    return {
        "schema": A_OPTIMAL_DMTA_SCHEMA,
        "pool_size": n,
        "measured_anchor_count": len(measured_set),
        "budget": int(budget),
        "exploration_weight": exploration_weight,
        "similarity_cutoff": similarity_cutoff,
        "initial_posterior_trace": round(initial_trace, 5),
        "final_posterior_trace": round(final_trace, 5),
        "trace_reduction_fraction": round(
            (initial_trace - final_trace) / max(initial_trace, 1e-12), 4
        ),
        "component_count": len(components),
        "singleton_candidates": singletons,
        "selected_batch": selected,
    }


def build_design_dossier(
    selected_candidates: Sequence[Mapping[str, Any]],
    *,
    target_name: str,
    offtarget_name: str | None = None,
    mpo_profile: str = "oral",
    pocket_report: Mapping[str, Any] | None = None,
    selectivity_report: Mapping[str, Any] | None = None,
    sar_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble an evidence-bound medicinal-chemistry Design Dossier (JSON + compact Markdown).

    Never fabricates unexecuted MolCat ADMET/retrosynthesis or wet-lab results (Hard Constraint 7).
    """
    entries: list[dict[str, Any]] = []
    md_lines = [
        f"# MolDarwin Drug-Design Dossier: {target_name}"
        + (f" (vs {offtarget_name})" if offtarget_name else ""),
        "",
        "| Rank | Candidate | Pred dG (kcal/mol) | Sel dddG | LLE | MPO | Soft Spots | Verification Mode |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for rank_idx, cand in enumerate(selected_candidates, start=1):
        cid = str(cand["candidate_id"])
        smi = str(cand["smiles"])
        dg = cand.get("target_dg_kcal", cand.get("predicted_dg_kcal"))
        dg_o = cand.get("offtarget_dg_kcal")
        mpo = score_drug_design_mpo(
            smi,
            target_dg_kcal=float(dg) if dg is not None else None,
            offtarget_dg_kcal=float(dg_o) if dg_o is not None else None,
            profile=mpo_profile,
            molcat_annotations=cand.get("molcat_annotations"),
        )
        dddg = cand.get("selectivity_dddg_kcal", mpo["efficiency"]["selectivity_dddg_kcal"])
        fep_mode = str(cand.get("recommended_fep_mode") or "pending_network_check")
        rationale = str(cand.get("rationale") or "multi_objective_dmta_selected")

        entry = {
            "rank": rank_idx,
            "candidate_id": cid,
            "smiles": mpo["smiles"],
            "rationale": rationale,
            "target_dg_kcal": round(float(dg), 4) if dg is not None else None,
            "selectivity_dddg_kcal": round(float(dddg), 4) if dddg is not None else None,
            "mpo": mpo,
            "recommended_verification": fep_mode,
        }
        entries.append(entry)

        dg_str = f"{float(dg):.2f}" if dg is not None else "n/a"
        sel_str = f"{float(dddg):+.2f}" if dddg is not None else "n/a"
        lle_str = f"{mpo['efficiency']['lle_lipe']:.2f}" if mpo["efficiency"]["lle_lipe"] is not None else "n/a"
        md_lines.append(
            f"| {rank_idx} | `{cid}` | {dg_str} | {sel_str} | {lle_str} | "
            f"{mpo['mpo_score']:.2f} | {len(mpo['metabolic_soft_spots'])} | {fep_mode} |"
        )

    context_summary = {
        "pocket_profile_attached": pocket_report is not None,
        "anchor_atoms_protected": list(pocket_report.get("anchor_atom_indices", [])) if pocket_report else None,
        "selectivity_map_attached": selectivity_report is not None,
        "divergent_pocket_residues": (
            selectivity_report.get("divergent_residue_count") if selectivity_report else None
        ),
        "sar_model_attached": sar_report is not None,
        "sar_loo_rmse_kcal": (
            sar_report.get("loo_cv", {}).get("rmse_kcal") if sar_report else None
        ),
    }
    return {
        "schema": DESIGN_DOSSIER_SCHEMA,
        "target_name": target_name,
        "offtarget_name": offtarget_name,
        "mpo_profile": mpo_profile,
        "candidate_count": len(entries),
        "context": context_summary,
        "candidates": entries,
        "markdown_summary": "\n".join(md_lines),
    }


__all__ = [
    "A_OPTIMAL_DMTA_SCHEMA",
    "DESIGN_DOSSIER_SCHEMA",
    "EHVI_RANKING_SCHEMA",
    "MPO_PROFILE_SCHEMA",
    "RT_LN10_298K_KCAL",
    "build_design_dossier",
    "rank_candidates_ehvi",
    "score_drug_design_mpo",
    "select_a_optimal_dmta_batch",
]
