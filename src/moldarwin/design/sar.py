"""First-principles quantitative SAR: MCS/MMP decomposition, Bayesian Free-Wilson + epistasis,
untested R-group recombination, and Frisch-Waugh-Lovell physicochemical deconfounding.

Turns any congeneric series (from MolOrigin assays, MolCat scoring, or PRISM RBFE/ABFE) into
actionable, uncertainty-calibrated medicinal-chemistry hypotheses without chasing 2D cLogP/MW
shortcuts.
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

MMP_DECOMPOSITION_SCHEMA = "moldarwin-sar-mmp-decomposition/1"
FREE_WILSON_SCHEMA = "moldarwin-bayesian-free-wilson/1"
DECONFOUND_SCHEMA = "moldarwin-sar-deconfound/1"

#: RT * ln(10) at 298.15 K in kcal/mol for dG <-> pKi conversion (Evidence: literature).
RT_LN10_298K_KCAL: float = 1.3642

#: Default hierarchical Gaussian priors for Bayesian Free-Wilson (Evidence: convention).
DEFAULT_INTERCEPT_PRIOR_SD_KCAL: float = 10.0
DEFAULT_MAIN_PRIOR_SD_KCAL: float = 1.5
DEFAULT_EPISTASIS_PRIOR_SD_KCAL: float = 0.75
DEFAULT_OBS_NOISE_SD_KCAL: float = 0.5
DEFAULT_ACTIVITY_CLIFF_KCAL: float = 1.5

_ATTACH_RE = re.compile(r"\[\*:(\d+)\]")


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _normal_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def _rank_array(vals: np.ndarray) -> np.ndarray:
    """Midrank array for Spearman correlation (handles ties accurately)."""
    order = np.argsort(vals, kind="mergesort")
    ranks = np.empty(len(vals), dtype=float)
    i = 0
    n = len(vals)
    while i < n:
        j = i + 1
        while j < n and vals[order[j]] == vals[order[i]]:
            j += 1
        avg = 0.5 * (i + j - 1) + 1.0
        ranks[order[i:j]] = avg
        i = j
    return ranks


def _pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3:
        return None
    dx = x - np.mean(x)
    dy = y - np.mean(y)
    denom = float(np.sqrt(np.sum(dx * dx) * np.sum(dy * dy)))
    if denom <= 1e-12:
        return None
    return float(np.sum(dx * dy) / denom)


def _spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3:
        return None
    return _pearson(_rank_array(x), _rank_array(y))


def _mol_2d_descriptors(mol: Any) -> dict[str, float]:
    from rdkit.Chem import Descriptors, rdMolDescriptors

    return {
        "mw": float(Descriptors.MolWt(mol)),
        "clogp": float(Descriptors.MolLogP(mol)),
        "tpsa": float(Descriptors.TPSA(mol)),
        "heavy_atoms": float(mol.GetNumHeavyAtoms()),
        "fsp3": float(rdMolDescriptors.CalcFractionCSP3(mol)),
    }


def _normalize_rgroup_smiles(r_smi: str) -> str:
    """Canonicalize an R-group fragment while stripping attachment map index differences."""
    from rdkit import Chem

    cleaned = _ATTACH_RE.sub("[*]", r_smi)
    mol = Chem.MolFromSmiles(cleaned)
    if mol is None:
        return cleaned
    return Chem.MolToSmiles(mol, canonical=True)


def _reassemble_from_rgroups(core_with_dummies_smi: str, r_by_site: Mapping[str, str]) -> str | None:
    """Assemble a valid canonical SMILES from a decomposed core SMILES and R-group map."""
    from rdkit import Chem

    core_mol = Chem.MolFromSmiles(core_with_dummies_smi)
    if core_mol is None:
        return None

    # Map site name ("R1", "R2", ...) -> integer label (1, 2, ...)
    combined = Chem.RWMol(core_mol)
    for site, raw_r_smi in sorted(r_by_site.items()):
        m = re.fullmatch(r"R(\d+)", site)
        if not m:
            continue
        label = int(m.group(1))
        r_mol = Chem.MolFromSmiles(raw_r_smi)
        if r_mol is None:
            return None
        # Ensure R-group dummy carries the matching map label
        r_rw = Chem.RWMol(r_mol)
        for atom in r_rw.GetAtoms():
            if atom.GetAtomicNum() == 0:
                atom.SetAtomMapNum(label)
                atom.SetIsotope(0)
        offset = combined.GetNumAtoms()
        combined = Chem.RWMol(Chem.CombineMols(combined, r_rw))

        # Find the core dummy with map == label (in < offset) and R dummy (>= offset)
        core_dummy = None
        r_dummy = None
        for atom in combined.GetAtoms():
            if atom.GetAtomicNum() == 0 and (
                atom.GetAtomMapNum() == label or atom.GetIsotope() == label
            ):
                if atom.GetIdx() < offset and core_dummy is None:
                    core_dummy = atom.GetIdx()
                elif atom.GetIdx() >= offset and r_dummy is None:
                    r_dummy = atom.GetIdx()
        if core_dummy is None or r_dummy is None:
            return None

        core_nbrs = list(combined.GetAtomWithIdx(core_dummy).GetNeighbors())
        r_nbrs = list(combined.GetAtomWithIdx(r_dummy).GetNeighbors())
        if len(core_nbrs) != 1 or len(r_nbrs) != 1:
            return None

        c_nbr_idx = core_nbrs[0].GetIdx()
        r_nbr_idx = r_nbrs[0].GetIdx()
        bond = combined.GetBondBetweenAtoms(r_dummy, r_nbr_idx)
        bond_type = bond.GetBondType() if bond is not None else Chem.BondType.SINGLE

        # If the R-group is just hydrogen ([H][*:1]), simply delete both dummy + H so valence fills
        if combined.GetAtomWithIdx(r_nbr_idx).GetAtomicNum() == 1:
            to_drop = sorted([core_dummy, r_dummy, r_nbr_idx], reverse=True)
            for idx in to_drop:
                combined.RemoveAtom(idx)
        else:
            combined.AddBond(c_nbr_idx, r_nbr_idx, bond_type)
            for idx in sorted([core_dummy, r_dummy], reverse=True):
                combined.RemoveAtom(idx)

    # Remove any leftover unmapped hydrogens/dummies and sanitize strictly
    try:
        mol_out = combined.GetMol()
        if any(atom.GetAtomicNum() == 0 for atom in mol_out.GetAtoms()):
            return None
        Chem.SanitizeMol(mol_out)
        mol_out = Chem.RemoveHs(mol_out)
        return Chem.MolToSmiles(mol_out, canonical=True)
    except Exception:  # noqa: BLE001
        return None


def decompose_congeneric_series(
    records: Sequence[Mapping[str, Any]],
    *,
    core_smarts: str | None = None,
    mcs_timeout_s: int = 2,
    activity_cliff_kcal: float = DEFAULT_ACTIVITY_CLIFF_KCAL,
) -> dict[str, Any]:
    """Decompose a congeneric series on its ring-preserving MCS and extract single-site MMPs.

    Each record requires ``id`` (str), ``smiles`` (str), and ``target_dg_kcal`` (float; lower
    is stronger binding). Optional: ``uncertainty_kcal`` (float).
    """
    from rdkit import Chem, RDLogger, rdBase
    from rdkit.Chem import rdFMCS, rdRGroupDecomposition

    RDLogger.DisableLog("rdApp.*")

    parsed: list[dict[str, Any]] = []
    invalid: list[str] = []
    for row in records:
        cid = str(row["id"])
        smi = str(row["smiles"])
        dg = row.get("target_dg_kcal")
        mol = Chem.MolFromSmiles(smi)
        if mol is None or dg is None or not math.isfinite(float(dg)):
            invalid.append(cid)
            continue
        desc = _mol_2d_descriptors(mol)
        dg_f = float(dg)
        pki = -dg_f / RT_LN10_298K_KCAL
        lle = pki - desc["clogp"]
        parsed.append({
            "id": cid,
            "smiles": Chem.MolToSmiles(mol, canonical=True),
            "mol": mol,
            "target_dg_kcal": dg_f,
            "uncertainty_kcal": (
                float(row["uncertainty_kcal"])
                if row.get("uncertainty_kcal") is not None and math.isfinite(float(row["uncertainty_kcal"]))
                else None
            ),
            "pki": pki,
            "lle": lle,
            **desc,
        })

    if len(parsed) < 2:
        raise ValueError("need at least 2 valid molecules with finite target_dg_kcal")

    with rdBase.BlockLogs():
        if core_smarts is None:
            mcs = rdFMCS.FindMCS(
                [p["mol"] for p in parsed],
                timeout=mcs_timeout_s,
                ringMatchesRingOnly=True,
                completeRingsOnly=True,
                atomCompare=rdFMCS.AtomCompare.CompareElements,
                bondCompare=rdFMCS.BondCompare.CompareOrderExact,
            )
            if mcs.numAtoms < 3:
                raise ValueError("series does not share a common core (>= 3 heavy atoms)")
            core_smarts = mcs.smartsString

        core_mol = Chem.MolFromSmarts(core_smarts)
        if core_mol is None:
            raise ValueError(f"invalid core SMARTS: {core_smarts!r}")

        rg_params = rdRGroupDecomposition.RGroupDecompositionParameters()
        rg_params.onlyMatchAtRGroups = False
        rg_params.removeHydrogensPostMatch = False
        rgd = rdRGroupDecomposition.RGroupDecomposition(core_mol, rg_params)

        matched_indices: list[int] = []
        unmatched_ids: list[str] = []
        for idx, rec in enumerate(parsed):
            ok_idx = rgd.Add(rec["mol"])
            if ok_idx >= 0:
                matched_indices.append(idx)
            else:
                unmatched_ids.append(rec["id"])
        rgd.Process()
        rows_smi = rgd.GetRGroupsAsRows(asSmiles=True)

    r_sites = sorted(
        {k for row in rows_smi for k in row if re.fullmatch(r"R\d+", k)},
        key=lambda s: int(s[1:]),
    )
    decomposed: list[dict[str, Any]] = []
    canonical_core_smi: str | None = None

    for idx, rg_row in zip(matched_indices, rows_smi, strict=True):
        rec = parsed[idx]
        if canonical_core_smi is None and "Core" in rg_row:
            canonical_core_smi = str(rg_row["Core"])
        r_raw = {site: str(rg_row.get(site, f"[H][*:{site[1:]}]")) for site in r_sites}
        r_norm = {site: _normalize_rgroup_smiles(smi) for site, smi in r_raw.items()}
        decomposed.append({
            "id": rec["id"],
            "smiles": rec["smiles"],
            "target_dg_kcal": round(rec["target_dg_kcal"], 4),
            "uncertainty_kcal": rec["uncertainty_kcal"],
            "pki": round(rec["pki"], 3),
            "lle": round(rec["lle"], 3),
            "mw": round(rec["mw"], 2),
            "clogp": round(rec["clogp"], 3),
            "tpsa": round(rec["tpsa"], 2),
            "fsp3": round(rec["fsp3"], 3),
            "rgroups": r_norm,
            "rgroups_raw": r_raw,
            "core_smiles": str(rg_row.get("Core", "")),
        })

    # Extract exact single-site Matched Molecular Pairs (differing at exactly 1 R-group site)
    mmps: list[dict[str, Any]] = []
    for i in range(len(decomposed)):
        for j in range(i + 1, len(decomposed)):
            a, b = decomposed[i], decomposed[j]
            diff_sites = [s for s in r_sites if a["rgroups"][s] != b["rgroups"][s]]
            if len(diff_sites) != 1:
                continue
            site = diff_sites[0]
            ddg = b["target_dg_kcal"] - a["target_dg_kcal"]
            dpki = b["pki"] - a["pki"]
            dclogp = b["clogp"] - a["clogp"]
            dlle = b["lle"] - a["lle"]
            dmw = b["mw"] - a["mw"]

            if abs(ddg) >= activity_cliff_kcal:
                eff_class = "activity_cliff"
            elif ddg <= -0.3 and dlle >= 0.25:
                eff_class = "true_recognition_gain"
            elif ddg <= -0.3 and dlle <= -0.25:
                eff_class = "greasy_potency_warning"
            elif ddg >= 0.3 and dlle <= -0.25:
                eff_class = "potency_and_efficiency_loss"
            else:
                eff_class = "neutral_or_tradeoff"

            mmps.append({
                "from_id": a["id"],
                "to_id": b["id"],
                "site": site,
                "from_rgroup": a["rgroups"][site],
                "to_rgroup": b["rgroups"][site],
                "delta_dg_kcal": round(ddg, 4),
                "delta_pki": round(dpki, 3),
                "delta_clogp": round(dclogp, 3),
                "delta_lle": round(dlle, 3),
                "delta_mw": round(dmw, 2),
                "classification": eff_class,
            })

    mmps.sort(key=lambda r: -abs(r["delta_dg_kcal"]))
    site_vocab = {
        site: sorted({d["rgroups"][site] for d in decomposed})
        for site in r_sites
    }
    return {
        "schema": MMP_DECOMPOSITION_SCHEMA,
        "core_smarts": core_smarts,
        "core_smiles": canonical_core_smi,
        "r_sites": r_sites,
        "site_vocab": site_vocab,
        "decomposed_count": len(decomposed),
        "unmatched_ids": unmatched_ids,
        "invalid_ids": invalid,
        "decomposed": decomposed,
        "mmp_count": len(mmps),
        "mmps": mmps,
    }


def fit_bayesian_free_wilson(
    records: Sequence[Mapping[str, Any]],
    *,
    core_smarts: str | None = None,
    prior_main_sd_kcal: float = DEFAULT_MAIN_PRIOR_SD_KCAL,
    prior_epistasis_sd_kcal: float = DEFAULT_EPISTASIS_PRIOR_SD_KCAL,
    obs_noise_sd_kcal: float = DEFAULT_OBS_NOISE_SD_KCAL,
    include_epistasis: bool = True,
    max_enumerated: int = 64,
) -> dict[str, Any]:
    """Fit exact heteroscedastic Bayesian Ridge Free-Wilson + pairwise epistasis (Activity Cliffs).

    Computes closed-form Gaussian posterior R-group contributions, exact hat-matrix LOO CV,
    non-additive activity cliff flags, and novel untested R-group Cartesian combinations with
    RDKit-validated SMILES, predicted dG +/- SD, Probability of Improvement, Expected
    Improvement (EI), and predicted LLE.
    """
    from rdkit import Chem

    decomp = decompose_congeneric_series(records, core_smarts=core_smarts)
    rows = decomp["decomposed"]
    r_sites = decomp["r_sites"]
    if len(rows) < 3:
        raise ValueError("Bayesian Free-Wilson requires at least 3 decomposed congeneric compounds")

    varying_sites = [s for s in r_sites if len(decomp["site_vocab"][s]) >= 2]
    if not varying_sites:
        raise ValueError("series has no varying R-group sites")

    # Build feature index: [intercept] + main effects + optional pairwise epistasis
    feat_names: list[str] = ["intercept"]
    prior_vars: list[float] = [DEFAULT_INTERCEPT_PRIOR_SD_KCAL ** 2]
    main_index: dict[tuple[str, str], int] = {}
    for site in varying_sites:
        for r_smi in decomp["site_vocab"][site]:
            main_index[(site, r_smi)] = len(feat_names)
            feat_names.append(f"main:{site}={r_smi}")
            prior_vars.append(prior_main_sd_kcal ** 2)

    n_additive_feats = len(feat_names)
    epi_index: dict[tuple[str, str, str, str], int] = {}
    if include_epistasis and len(varying_sites) >= 2:
        for i, s1 in enumerate(varying_sites):
            for s2 in varying_sites[i + 1 :]:
                seen_pairs = sorted({(r["rgroups"][s1], r["rgroups"][s2]) for r in rows})
                for r1, r2 in seen_pairs:
                    epi_index[(s1, r1, s2, r2)] = len(feat_names)
                    feat_names.append(f"epi:{s1}={r1}&{s2}={r2}")
                    prior_vars.append(prior_epistasis_sd_kcal ** 2)

    n = len(rows)
    p = len(feat_names)

    def _encode(r_map: Mapping[str, str], *, with_epi: bool) -> np.ndarray:
        x = np.zeros(p if with_epi else n_additive_feats, dtype=float)
        x[0] = 1.0
        for site in varying_sites:
            idx = main_index.get((site, r_map[site]))
            if idx is not None:
                x[idx] = 1.0
        if with_epi and epi_index:
            for i, s1 in enumerate(varying_sites):
                for s2 in varying_sites[i + 1 :]:
                    idx = epi_index.get((s1, r_map[s1], s2, r_map[s2]))
                    if idx is not None:
                        x[idx] = 1.0
        return x

    x_full = np.vstack([_encode(r["rgroups"], with_epi=True) for r in rows])
    x_add = x_full[:, :n_additive_feats]
    y = np.array([r["target_dg_kcal"] for r in rows], dtype=float)
    sigmas = np.array(
        [max(r["uncertainty_kcal"] or obs_noise_sd_kcal, 0.1) for r in rows],
        dtype=float,
    )
    w_vec = 1.0 / (sigmas ** 2)
    w_mat = np.diag(w_vec)

    def _solve_ridge(x_mat: np.ndarray, p_vars: list[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        lam = np.diag([1.0 / v for v in p_vars])
        prec = x_mat.T @ w_mat @ x_mat + lam
        cov = np.linalg.inv(prec)
        theta = cov @ (x_mat.T @ (w_vec * y))
        hat_diag = np.einsum("ij,jk,ik->i", x_mat, cov, x_mat) * w_vec
        return theta, cov, hat_diag

    theta_add, cov_add, hat_add = _solve_ridge(x_add, prior_vars[:n_additive_feats])
    theta_full, cov_full, hat_full = _solve_ridge(x_full, prior_vars)

    y_hat_add = x_add @ theta_add
    y_hat_full = x_full @ theta_full

    # Exact analytical hat-matrix Leave-One-Out CV (zero refitting!)
    denom_loo = np.maximum(1.0 - hat_full, 1e-4)
    loo_err = (y - y_hat_full) / denom_loo
    loo_pred = y - loo_err
    loo_rmse = float(np.sqrt(np.mean(loo_err ** 2)))
    loo_mae = float(np.mean(np.abs(loo_err)))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    loo_r2 = round(1.0 - float(np.sum(loo_err ** 2)) / ss_tot, 4) if ss_tot > 1e-12 else None
    loo_rho = _spearman(y, loo_pred)

    # Per-site R-group main effect summary
    main_effects: dict[str, list[dict[str, Any]]] = {}
    for site in varying_sites:
        entries = []
        for r_smi in decomp["site_vocab"][site]:
            idx = main_index[(site, r_smi)]
            members = [r for r in rows if r["rgroups"][site] == r_smi]
            entries.append({
                "rgroup": r_smi,
                "effect_dg_kcal": round(float(theta_full[idx]), 4),
                "effect_se_kcal": round(float(math.sqrt(max(cov_full[idx, idx], 0.0))), 4),
                "n_observed": len(members),
                "mean_observed_dg_kcal": round(float(np.mean([m["target_dg_kcal"] for m in members])), 4),
                "mean_observed_lle": round(float(np.mean([m["lle"] for m in members])), 3),
            })
        entries.sort(key=lambda r: r["effect_dg_kcal"])
        main_effects[site] = entries

    # Non-additive Activity Cliffs / Epistasis alerts
    activity_cliffs: list[dict[str, Any]] = []
    for (s1, r1, s2, r2), idx in epi_index.items():
        val = float(theta_full[idx])
        se = float(math.sqrt(max(cov_full[idx, idx], 1e-12)))
        z = abs(val) / se
        if abs(val) >= 0.5 or z >= 1.5:
            activity_cliffs.append({
                "kind": "pairwise_epistasis",
                "sites": [s1, s2],
                "rgroups": {s1: r1, s2: r2},
                "epistasis_dg_kcal": round(val, 4),
                "epistasis_se_kcal": round(se, 4),
                "z_score": round(z, 2),
                "direction": "synergistic_gain" if val < 0 else "antagonistic_clash",
            })

    # Also detect compounds with large residual against the purely additive model
    add_res = y - y_hat_add
    for idx_i, rec in enumerate(rows):
        res_i = float(add_res[idx_i])
        if abs(res_i) >= max(0.8, 1.8 * float(sigmas[idx_i])):
            activity_cliffs.append({
                "kind": "additive_model_outlier",
                "compound_id": rec["id"],
                "observed_dg_kcal": rec["target_dg_kcal"],
                "additive_pred_dg_kcal": round(float(y_hat_add[idx_i]), 4),
                "residual_dg_kcal": round(res_i, 4),
                "rgroups": {s: rec["rgroups"][s] for s in varying_sites},
                "note": "Non-additive binding-mode shift, water displacement, or cooperative SAR.",
            })
    activity_cliffs.sort(
        key=lambda r: -abs(r.get("epistasis_dg_kcal", r.get("residual_dg_kcal", 0.0)))
    )

    # Enumerate novel untested R-group Cartesian combinations and reconstruct valid SMILES!
    observed_smiles = {r["smiles"] for r in rows}
    observed_combos = {tuple(r["rgroups"][s] for s in r_sites) for r in rows}
    raw_lookup: dict[tuple[str, str], str] = {}
    for r in rows:
        for s in r_sites:
            raw_lookup.setdefault((s, r["rgroups"][s]), r["rgroups_raw"][s])

    core_template = rows[0]["core_smiles"]
    best_obs_dg = float(np.min(y))
    proposals: list[dict[str, Any]] = []

    if len(varying_sites) >= 2 and core_template:
        vocab_lists = [decomp["site_vocab"][s] for s in r_sites]
        for combo in itertools.product(*vocab_lists):
            if combo in observed_combos:
                continue
            r_norm_map = dict(zip(r_sites, combo, strict=True))
            r_raw_map = {s: raw_lookup[(s, r_norm_map[s])] for s in r_sites}
            smi = _reassemble_from_rgroups(core_template, r_raw_map)
            if smi is None or smi in observed_smiles:
                continue
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                continue
            observed_smiles.add(smi)

            x_star = _encode(r_norm_map, with_epi=True)
            mu = float(x_star @ theta_full)
            var_epi = float(max(0.0, x_star @ cov_full @ x_star))
            sd_epi = math.sqrt(var_epi)
            sd_pred = math.sqrt(var_epi + obs_noise_sd_kcal ** 2)
            z_imp = (best_obs_dg - mu) / max(sd_pred, 1e-6)
            p_imp = _normal_cdf(z_imp)
            ei = max(0.0, (best_obs_dg - mu) * p_imp + sd_pred * _normal_pdf(z_imp))

            desc = _mol_2d_descriptors(mol)
            pred_pki = -mu / RT_LN10_298K_KCAL
            pred_lle = pred_pki - desc["clogp"]
            proposals.append({
                "proposal_id": f"fw_combo_{len(proposals) + 1}",
                "smiles": smi,
                "rgroups": {s: r_norm_map[s] for s in varying_sites},
                "predicted_dg_kcal": round(mu, 4),
                "epistemic_se_kcal": round(sd_epi, 4),
                "predictive_sd_kcal": round(sd_pred, 4),
                "prob_improve_over_best": round(p_imp, 4),
                "expected_improvement_kcal": round(ei, 4),
                "predicted_pki": round(pred_pki, 3),
                "predicted_lle": round(pred_lle, 3),
                "mw": round(desc["mw"], 2),
                "clogp": round(desc["clogp"], 3),
                "tpsa": round(desc["tpsa"], 2),
                "fsp3": round(desc["fsp3"], 3),
            })
            if len(proposals) >= max_enumerated:
                break

    proposals.sort(key=lambda r: (-r["expected_improvement_kcal"], r["predicted_dg_kcal"]))
    return {
        "schema": FREE_WILSON_SCHEMA,
        "core_smarts": decomp["core_smarts"],
        "varying_sites": varying_sites,
        "n_compounds": n,
        "best_observed_dg_kcal": round(best_obs_dg, 4),
        "intercept_dg_kcal": round(float(theta_full[0]), 4),
        "loo_cv": {
            "rmse_kcal": round(loo_rmse, 4),
            "mae_kcal": round(loo_mae, 4),
            "r2": loo_r2,
            "spearman_rho": round(loo_rho, 4) if loo_rho is not None else None,
        },
        "main_effects": main_effects,
        "mmp_count": decomp["mmp_count"],
        "top_mmps": decomp["mmps"][:12],
        "activity_cliffs": activity_cliffs,
        "novel_combinations_count": len(proposals),
        "novel_combinations": proposals,
        "priors": {
            "main_sd_kcal": prior_main_sd_kcal,
            "epistasis_sd_kcal": prior_epistasis_sd_kcal,
            "obs_noise_sd_kcal": obs_noise_sd_kcal,
            "evidence": "convention",
        },
    }


def deconfound_sar_signal(
    records: Sequence[Mapping[str, Any]],
    *,
    score_key: str = "score",
    target_key: str = "target_dg_kcal",
    higher_score_better: bool = False,
    confounders: Sequence[str] = ("mw", "clogp", "tpsa", "heavy_atoms"),
) -> dict[str, Any]:
    """Frisch-Waugh-Lovell partial-correlation deconfounding against 2D physicochemical shortcuts.

    Projects out 2D confounders (MW, cLogP, TPSA, heavy-atom count) from both the model score
    and the measured target affinity so medicinal chemists immediately see whether an apparent
    correlation reflects true 3D molecular recognition or mere size/lipophilicity inflation.
    """
    from rdkit import Chem

    xs: list[float] = []
    ys: list[float] = []
    z_rows: list[list[float]] = []

    for row in records:
        sv = row.get(score_key)
        yv = row.get(target_key)
        if sv is None or yv is None:
            continue
        sf, yf = float(sv), float(yv)
        if not (math.isfinite(sf) and math.isfinite(yf)):
            continue

        desc: dict[str, float] = {}
        if row.get("smiles"):
            mol = Chem.MolFromSmiles(str(row["smiles"]))
            if mol is not None:
                desc = _mol_2d_descriptors(mol)
        z_vec: list[float] = []
        valid_z = True
        for cname in confounders:
            val = row.get(cname, desc.get(cname))
            if val is None or not math.isfinite(float(val)):
                valid_z = False
                break
            z_vec.append(float(val))
        if not valid_z:
            continue

        # Sign-align score so lower is better (matching dG kcal/mol)
        xs.append(-sf if higher_score_better else sf)
        ys.append(yf)
        z_rows.append(z_vec)

    n = len(xs)
    if n < 5:
        raise ValueError(f"deconfounding requires at least 5 complete records; got {n}")

    x_arr = np.array(xs, dtype=float)
    y_arr = np.array(ys, dtype=float)
    z_raw = np.array(z_rows, dtype=float)

    # Keep non-constant confounder columns + intercept
    active_cols: list[int] = []
    active_names: list[str] = []
    for idx, cname in enumerate(confounders):
        if float(np.std(z_raw[:, idx])) > 1e-8:
            active_cols.append(idx)
            active_names.append(cname)

    if active_cols:
        z_std = z_raw[:, active_cols]
        z_std = (z_std - np.mean(z_std, axis=0)) / np.std(z_std, axis=0)
        z_mat = np.column_stack([np.ones(n), z_std])
    else:
        z_mat = np.ones((n, 1))

    coef_x, _, _, _ = np.linalg.lstsq(z_mat, x_arr, rcond=None)
    coef_y, _, _, _ = np.linalg.lstsq(z_mat, y_arr, rcond=None)
    x_res = x_arr - z_mat @ coef_x
    y_res = y_arr - z_mat @ coef_y

    def _r2(orig: np.ndarray, resid: np.ndarray) -> float:
        tot = float(np.sum((orig - np.mean(orig)) ** 2))
        if tot <= 1e-12:
            return 0.0
        return max(0.0, 1.0 - float(np.sum(resid ** 2)) / tot)

    raw_r = _pearson(x_arr, y_arr)
    raw_rho = _spearman(x_arr, y_arr)
    partial_r = _pearson(x_res, y_res)
    partial_rho = _spearman(x_res, y_res)
    r2_conf_score = _r2(x_arr, x_res)
    r2_conf_target = _r2(y_arr, y_res)

    # Flag shortcut if raw skill looks meaningful (>= 0.40) yet collapses after removing 2D props
    raw_best = max(raw_r or 0.0, raw_rho or 0.0)
    partial_best = max(partial_r or 0.0, partial_rho or 0.0)
    shortcut_warning = bool(
        (raw_best >= 0.40 and partial_best < 0.25)
        or (raw_best - partial_best >= 0.30)
    )

    return {
        "schema": DECONFOUND_SCHEMA,
        "n_records": n,
        "confounders_removed": active_names,
        "raw_pearson_r": round(raw_r, 4) if raw_r is not None else None,
        "raw_spearman_rho": round(raw_rho, 4) if raw_rho is not None else None,
        "partial_pearson_r": round(partial_r, 4) if partial_r is not None else None,
        "partial_spearman_rho": round(partial_rho, 4) if partial_rho is not None else None,
        "confounder_r2_on_score": round(r2_conf_score, 4),
        "confounder_r2_on_target": round(r2_conf_target, 4),
        "shortcut_warning": shortcut_warning,
        "verdict": (
            "physicochemical_shortcut_suspected"
            if shortcut_warning
            else ("genuine_3d_recognition_signal" if partial_best >= 0.35 else "weak_signal")
        ),
    }


__all__ = [
    "DECONFOUND_SCHEMA",
    "FREE_WILSON_SCHEMA",
    "MMP_DECOMPOSITION_SCHEMA",
    "RT_LN10_298K_KCAL",
    "deconfound_sar_signal",
    "decompose_congeneric_series",
    "fit_bayesian_free_wilson",
]
