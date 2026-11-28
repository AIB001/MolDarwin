---
name: moldarwin-drug-design
description: First-principles three-pillar DMTA drug design orchestrating MolOrigin evidence, 3D pocket/selectivity & Bayesian Free-Wilson SAR reasoning, PRISM generation/physics, MolCat 53-plugin ADMET/retrosynthesis, and multi-objective EHVI + A-optimal selection.
domain: drug-design
tags: [drug-design, medchem, sar, mmp, free-wilson, selectivity, pocket, mpo, lle, ehvi, dmta, molcat, molorigin, prism]
applicable_when: Running structure-guided hit-to-lead, lead optimization, isoform selectivity design, quantitative SAR/activity-cliff analysis, or multi-parameter DMTA synthesis selection.
invalid_when: Do not treat 2D Free-Wilson or MPO scores as wet-lab binding affinity, never mutate locked 3D anchor pharmacophores blindly, and never fabricate MolCat ADMET/retrosynthesis results that were not executed.
maturity: validated
tools: [moldarwin_capabilities, moldarwin_skill_find, moldarwin_skill_read, moldarwin_research_context]
---

# Three-Pillar Drug Design & DMTA Reasoning (`moldarwin.design`)

MolDarwin empowers drug design by coordinating **three equal vendored engines** through one first-principles medicinal-chemistry reasoning brain—never reinventing what MolCat, MolOrigin, or PRISM already do well:

1. **MolOrigin (`data` pack)** — target/assay/literature evidence, crystal structure templates, isoform selectivity records, analogue search, and purchasable building blocks.
2. **MolCat (`screening` pack, 53 plugins)** — standardization, Uni-Dock/Gnina/KarmaDock/Redock, Boltz2 co-folding, OpenADMET/ADMET-AI, Lilly & medchem alerts, AiZynthFinder retrosynthesis, SA/SCScore, pose strain, specificity panels, diversity.
3. **PRISM (`prism` pack)** — 6 SBDD 3D generators (`prism.generation`), grounded local editing (upstream `prism.design`), explicit-solvent MD/MM-PBSA/RBFE/REST2, and trajectory interaction analysis.
4. **MolDarwin Design Brain (`moldarwin.design` + `moldarwin.evolve`)** — the cross-pillar mathematical reasoning layer:

## 1. Understand the 3D Pocket & Isoform Selectivity First (`moldarwin.design.pocket`)
- Call `profile_3d_pocket_and_vectors(receptor_pdb, ligand_sdf)` before modifying a lead.
  - Identifies **locked anchor atoms** (`anchor_atom_indices`, e.g., kinase hinge H-bonds) that must be protected during analog generation.
  - Measures radial 3D clearance (Å) and local subpocket polarity at every editable growth vector (`editable_atom_indices`), plus solvent-exposed ADMET handles and adjacent crystal waters.
- For isoform selectivity (e.g., TYK2 vs JAK2), call `map_isoform_selectivity_vectors(target_pdb, offtarget_pdb, ligand_sdf)` to Kabsch-align the pockets, compute sidechain volume/polarity differences, and map divergent residues directly onto the closest editable ligand exit vectors.

## 2. Extract Quantitative SAR, Activity Cliffs & Remove 2D Shortcuts (`moldarwin.design.sar`)
- Call `deconfound_sar_signal(records)` to project out MW, cLogP, TPSA, and heavy-atom count (Frisch–Waugh–Lovell partial correlation) so you never chase greasy lipophilicity shortcuts.
- Call `fit_bayesian_free_wilson(records)` to perform ring-preserving MCS R-group decomposition, exact single-site MMP extraction ($\Delta\Delta G$, $\Delta\text{LLE}$), heteroscedastic Bayesian Ridge Free–Wilson + pairwise epistasis (Activity Cliffs), exact hat-matrix LOO CV, and **untested R-group Cartesian recombination** with valid SMILES, predicted $\Delta G \pm \sigma$, $P(\text{improve})$, and expected LLE.

## 3. Generate Protected, Catalog-Verified Synthesizable Candidates (`moldarwin.evolve` + `PRISM` + `MolCat`)
- Index local supplier catalogs (`.smi` / `.smi.gz`) once with `build_building_block_index` and call `enumerate_reaction_analogs(..., catalog_db=...)` so generated reaction products carry exact `catalog_verified_partners` (`0/2`, `1/2`, or `2/2`) and supplier IDs from birth—never burning MD/FEP GPU-hours exclusively on unverified 0/2 virtual partners.
- Pass `protected_atom_indices` from pocket profiling into `generate_bioisostere_analogs` (bioisostere/liability rescue, metabolic soft-spot blocking, steric/polar probes, heterocycle hops) or run `enumerate_reaction_analogs` (amide coupling, Suzuki, Buchwald-Hartwig, sulfonamidation, $S_N\text{Ar}$).
- For 3D de novo / local fragment design, invoke PRISM's 6 SBDD models (`prism.generation`) and qualify every pose with `qualify_generated_poses`.
- Qualify candidates with MolCat's 59-plugin screening, ADMET, medchem rules, PoseBusters, and retrosynthesis pipelines before spending GPU-hours on RBFE (reporting unavailable plugins honestly as `unavailable`).

## 4. Multi-Parameter DMTA Selection & 4-Checkpoint Sidecar Audit (`moldarwin.design.dmta` + `moldarwin.judgment.sidecar`)
- Profile every candidate with `score_drug_design_mpo` (LE, LLE/LipE, LELP, Fsp³, QED, ESOL solubility, hERG risk, CYP soft-spots, continuous Oral/CNS/PPI MPO) and attach any executed MolCat plugin evidence (reporting unexecuted plugins honestly as `not_run`).
- Rank with `rank_candidates_ehvi` (uncertainty-aware multi-objective Expected Hypervolume Improvement over Potency × Selectivity $\Delta\Delta\Delta G$ × MPO × Synthesizability).
- Select the next synthesis/FEP batch with `select_a_optimal_dmta_batch` (Sherman–Morrison Graph-Laplacian A-optimal information gain + EHVI utility + congeneric component/singleton awareness) and emit a complete `build_design_dossier` report.
- Run the read-only Sidecar Auditor (`moldarwin_sidecar_audit` / `run_sidecar_review`) at `CP1_TARGET_DATA`, `CP2_PRE_PHYSICS`, `CP3_RUNTIME_TELEMETRY`, and `CP4_PRE_DELIVERY` (optionally with an independent clean-context `CodexCli` / `ClaudeCli` critic), recording every advisory resolution via `record_advisory_resolution`.
