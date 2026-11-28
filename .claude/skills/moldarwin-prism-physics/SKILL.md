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
- **pH 7.4 PROPKA + falsifiable crystal hydration:** Use `protonation="propka", ph=7.4` (now default in `prepare_prism_md_system` / `prepare_prism_fep_edge`) so receptor HIS/ASP/GLU protonation matches ligand microstates; evaluate `select_conserved_pocket_waters` across deposited structures first. Never treat a short wet-arm pilot as causal rescue—match dry/wet seeds and track specific seeded-water site occupancy across full replicas (empirically, SND1 `7KNW` seeded waters vacated in 2,002/2,002 full frames despite a 1.23 Å pilot).
- **Sibling layout & staged equilibration:** `PRISMBuilder` writes `mdps/*.mdp` (default 500 ns!) and `LIG.amb2gmx/posre_LIG.itp` as siblings of `GMX_PROLIG_MD/`. Use `prepare_prism_md_system(..., prod_ns=..., staged_equilibration=True)` so `run_md_gmx2026.sh` runs CPU PME for EM, GPU PME/NB/bonded/update for NVT/NPT/MD, and supports multi-replica random seeds (`GMX_GEN_SEED` / `GMX_OUT_PREFIX`).
- **Multi-replica crystal MD control gate & real pose metrics:** Run at least 2–3 independent replicas on the crystal positive control and verify `evaluate_md_control_gate` (pocket-backbone aligned symmetry-aware ligand RMSD to the *source* crystal pose plus individual anchor-contact survival—never rely on `any-contact occupancy` or RMSD from production frame 0, which hide equilibration flips). A drifting crystal control invalidates protocol-based assertions of candidate superiority.
- **TPR v138 & PBC unwrapping:** Use `analyze_md_trajectory` (automatic `gmx trjconv -pbc whole` GRO+XTC fallback + minimum-image ligand-to-protein unwrapping).

## 4. Bond-Consistent RBFE/FEP, Shallow-PPI Escalation & Hardware Leases
- **Bond-consistent MCS mapping preflight (MANDATORY before RBFE):** Run `verify_bond_consistent_atom_mapping(mol_a, mol_b, proposed_mapping=...)` before preparing any dual-topology edge. Distance-only 3D maps can silently rewire conserved bonds and break rings (measured_here on SND1 `C26-A2 <-> C26-A6`: 36 heavy connectivity/order mismatches + 7 H mismatches -> 0/0 with ring-preserving MCS).
- **PRISM RBFE/FEP & GROMACS 2026 `-update cpu`:** `prepare_prism_fep_edge` enforces the SDF→GRO coordinate guard, sets finite `prod_ns`, enables `calc-lambda-neighbors = -1` for exact full-matrix MBAR, and disables uncompressed `.trr` output. Keep PRISM's pristine `hybrid.itp` and run FEP with `-nb gpu -pme gpu -bonded gpu -update cpu` via `render_packed_fep_runner`. Do NOT hack dummy masses to force `-update gpu`.
- **Single-dispatcher `ComputeLease` & auto-packing:** Acquire `ComputeLease(run_dir, allowed_gpus=..., forbidden_gpus=..., max_cpu_threads=...)` (OS-level `flock` preventing duplicate dispatchers and forbidden-GPU touches) and size concurrent slots via `lease.plan_packed_slots(single_job_sm_util_pct=..., max_jobs_per_gpu=8)` (packing up to `k=6` small FEP windows on 96 GB GPUs raised SM util from ~40% to 77–88% within CPU limits).
- **Control-gate hold & shallow-PPI escalation:** When crystal control edges fail `overlap_min >= 0.03`, flip ΔΔG sign across grids, or drift in unconstrained MD, hold candidate RBFE immediately and call `plan_shallow_ppi_physics_protocol` (Boresch/flat-bottom restraints + geodesic λ + `gmx_mpi -multidir -replex` HREX or Expanded Ensemble, or orthogonal wet-lab matched-pair calibration before more FEP spend).
- **Non-destructive MedChem annotations:** Use `annotate_medchem_liabilities` to separate narrow chemical instabilities from soft bioisosteric flags (e.g., nitroaromatics, lipophilicity) without blindly killing beyond-Ro5 PPI chemotypes.
- Record MD & FEP readouts via `record_md_readout` / `record_fep_readout` and compare docking vs MD stability via `compare_docking_vs_md`.
