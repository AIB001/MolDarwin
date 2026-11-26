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

## 3. GROMACS 2026 GPU & Trajectory Analysis Pitfalls
- **Sibling layout:** `PRISMBuilder` writes `mdps/*.mdp` (default `md.mdp` = 500 ns!) and `LIG.amb2gmx/posre_LIG.itp` as siblings of `GMX_PROLIG_MD/`. Use `prepare_prism_md_system` / `patch_gromacs2026_artifacts(..., prod_ns=...)` to stage sibling MDPs, set `nsteps`, verify posre includes, and emit an editable `run_md_gmx2026.sh`.
- **EM vs MD GPU flags:** Steepest-descent EM requires `-pme cpu` (and `-r {start_gro}` when `em.mdp` defines `-DPOSRES`) in GROMACS 2026; NVT/NPT/production MD run `-nb gpu -pme gpu -bonded gpu -update gpu` with `OMP_NUM_THREADS="$NTOMP"`.
- **TPR v138 & PBC unwrapping:** Older `MDAnalysis` rejects GROMACS 2026 `TPR v138`. Use `analyze_md_trajectory`, which automatically falls back via `gmx trjconv -pbc whole` to `GRO+XTC` and applies minimum-image ligand-to-protein PBC unwrapping so periodic box jumps never inflate RMSD.

## 4. Feeding PRISM Reality into MolDarwin RSI
- Record explicit-solvent MD readouts via `record_md_readout` and compare docking vs MD stability via `compare_docking_vs_md` to flag high-docking-score drifters.
- Reserve RBFE/FEP (`prepare_prism_fep_edge` → `analyze_fep_network` → `record_fep_readout`) for confirmed congeneric series with a shared binding pose; require thermodynamic cycle closure hysteresis <= 1.0 kcal/mol before trusting 1–2 kcal/mol SAR claims.
