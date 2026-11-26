---
name: moldarwin-prism-physics
description: Empirical PRISM MD, MM-PBSA, FEP, 3D pose preflight, and multi-mode rescoring practices for GROMACS 2026 and RSI loops.
domain: simulation
tags: [prism, md, fep, mmpbsa, gromacs, rescoring, preflight, unidock]
applicable_when: Preparing Any-Origin 3D complexes (LLM, co-fold, generative, docked, crystal) for Uni-Dock rescoring or PRISM explicit-solvent MD/MM-PBSA/FEP on GROMACS 2026.
invalid_when: Do not transfer target-specific score cutoffs, treat short MD pair energies as binding free energy, or skip explicit-H protonation before AmberTools AM1-BCC.
maturity: validated
tools: [moldarwin_physics_preflight, moldarwin_prism_prepare, moldarwin_prism_analyze, moldarwin_prism_fep_prepare, moldarwin_prism_fep_analyze, moldarwin_rescore_evaluate]
---

# PRISM Physics, Multi-Mode Rescoring & RSI Loop

Keep workflows fluid—adapt protocols freely in Python—while respecting these empirically verified physical/ABI boundaries (all measured on live GROMACS 2026 / Uni-Dock v1.2.0 runs):

## 1. Preflight Before Any Spend (Any-Origin Complex Ingress)
- **Scorer element guard:** Screen libraries with `preflight_scorer_elements(..., scorer="unidock")` before Meeko/Uni-Dock. Meeko emits PDBQTs for `B`, `Si`, `Se`, and metals that Uni-Dock v1.2.0 later rejects during parsing.
- **PRISM SDF sanitization & explicit hydrogens:** Always run `sanitize_ligand_sdf` (prevents PRISM's blank-title word-boundary substitution from corrupting GRO/ITP columns into `'IG  L'`) and verify explicit pH-appropriate 3D hydrogens before calling `PRISMBuilder` / AmberTools AM1-BCC.
- **Any-Origin 3D ingress:** Pass LLM, co-fold (Boltz/AF3), `prism.generation`, docked, or crystal complexes through `validate_complex_handoff` to catch 2D depictions, severe clashes (<1.5 Å), and detached poses.

## 2. Diagnose Sampling vs Ranking Before Production Screening
- Shallow PPI grooves (e.g. SND1–MTDH `7KNW`/`7KNX`) frequently pass **pose sampling** (best-of-modes RMSD ~1.1 Å) while failing **Vina top-1 ranking** (AUC ~0.33, EF5% = 0).
- Use `evaluate_rescorer_panel` and `compare_rescorers_for_rsi` to test orthogonal multi-mode rescorers (Gnina 3D-CNN, Vinardo/AD4, 3D shape+pharmacophore, AMBER `MMPBSA.py`) on the exact same control panel. Never launch a 10k screen on an uncalibrated ranking function.

## 3. Upgraded Explicit-Solvent MD & GROMACS 2026 Discipline
- **pH 7.4 PROPKA + conserved bridging crystal waters:** Use `protonation="propka", ph=7.4` (now default in `prepare_prism_md_system` / `prepare_prism_fep_edge`) so receptor HIS/ASP/GLU protonation matches ligand microstates; evaluate `select_conserved_pocket_waters` before stripping bridging crystal waters.
- **Sibling layout & staged equilibration:** `PRISMBuilder` writes `mdps/*.mdp` (default 500 ns!) and `LIG.amb2gmx/posre_LIG.itp` as siblings of `GMX_PROLIG_MD/`. Use `prepare_prism_md_system(..., prod_ns=..., staged_equilibration=True)` so `run_md_gmx2026.sh` runs CPU PME for EM, GPU PME/NB/bonded/update for NVT/NPT/MD, and supports multi-replica random seeds (`GMX_GEN_SEED` / `GMX_OUT_PREFIX`).
- **Multi-replica crystal MD control gate:** Run at least 2–3 independent replicas on the crystal positive control and verify `evaluate_md_control_gate` (median tail RMSD <= 2.5 Å) before relying on MD to triage novel hits.
- **TPR v138 & PBC unwrapping:** Use `analyze_md_trajectory` (automatic `gmx trjconv -pbc whole` GRO+XTC fallback + minimum-image ligand-to-protein unwrapping).

## 4. Converged RBFE/FEP, Soft MedChem Annotation & RSI Reality Loop
- **PRISM RBFE/FEP:** `prepare_prism_fep_edge` enforces the SDF→GRO coordinate guard, sets finite `prod_ns` (replacing PRISM's 500 ns/window default), enables `calc-lambda-neighbors = -1` for exact full-matrix MBAR, and disables uncompressed `.trr` output. Execute legs via PRISM's 8-GPU `run_fep.sh`, extract MBAR $\Delta\Delta G$ & `overlap_min` via `evaluate_prism_fep_edge`, and audit 3/4-node thermodynamic cycle closure hysteresis (<= 1.0 kcal/mol) via `analyze_fep_network` / `moldarwin_prism_fep_analyze`.
- **Non-destructive MedChem annotations:** Use `annotate_medchem_liabilities` to separate narrow chemical instabilities from soft bioisosteric flags (e.g., nitroaromatics, lipophilicity) without blindly killing beyond-Ro5 PPI chemotypes.
- Record MD & FEP readouts via `record_md_readout` / `record_fep_readout` and compare docking vs MD stability via `compare_docking_vs_md`.
