---
name: moldarwin-autonomous-planning
description: Token-efficient autonomous experiment design, micro-pilot throughput scaling, multi-GPU hygiene, and honest failure pivoting for open-ended scientific goals.
domain: planning
tags: [planning, budget, gpu, resources, autonomy, tb-science, benchmark, pivot]
applicable_when: Given an open-ended scientific discovery goal without a step-by-step recipe, where the host must inventory compute/engines, size experiments to a wall-clock/GPU budget, and decide when to scale or pivot.
invalid_when: Do not override an explicit user-mandated protocol, ignore busy GPUs owned by other users, or extrapolate uncalibrated proxy scores into affinity claims.
maturity: validated
tools: [moldarwin_capabilities, moldarwin_skill_find, moldarwin_physics_preflight, moldarwin_rescore_evaluate]
---

# Autonomous Scientific Planning & Compute Governance

When given a concise goal rather than a scripted multi-phase prompt, keep overhead near zero and let measured physics govern every spend decision:

## 1. Single-Shot Environment & Prior-Skill Grounding (Turn 1)
- Read `[moldarwin-env]` from `SessionStart` or call `moldarwin_capabilities(detail="summary", skills=[], tools=[], operations=[], include_environment=True)` once. Never waste 5–8 bash turns probing `nvidia-smi`, `which`, `df`, or package imports manually.
- Respect `busy_gpus` strictly (`DO_NOT_USE`). When single-job GPU utilization sits below ~50% on high-VRAM GPUs (common in GROMACS free-energy windows due to CPU perturbed-force sync), micro-benchmark `jobs_per_gpu = 1 vs 2 vs 3` with disjoint `-pinoffset` CPU pinning via `moldarwin.runtime.concurrency.{plan_gpu_packing,select_optimal_concurrency}` before scaling!
- Run one `moldarwin_skill_find` query for target/method lessons before writing bespoke scripts, and close every multi-stage run through `moldarwin.research.rsi_loop.{summarize_rsi_cycle,evaluate_rsi_promotion}` so compute, oracle, MD, FEP, and active-learning gains compound across campaigns without promoting single-target flukes.

## 2. Micro-Pilot First, Then Solve Budget-to-Scale
- Never guess library size or MD length blindly. Spend **≤5% of the time/GPU budget** on a micro-pilot (e.g., control panel docking/rescoring or short MD equilibration) to measure real throughput on this exact hardware.
- Use `moldarwin.runtime.environment.estimate_experiment_budget(pilot_items, pilot_wall_s, remaining_wall_min=..., available_gpus=...)` to size production screening $N$, parallel MD count, and production nanoseconds to fit safely inside the charter.
- Default information-value split across a finite wall-clock budget:
  - **~10%** Control calibration + micro-pilot (must pass before scaling);
  - **~45%** Scaled production across all `idle_gpus` (batched single-process GPU calls per shard, never per-ligand process spawning);
  - **~35%** Orthogonal higher-fidelity physics verification (parallel explicit-solvent PRISM MD / MM-GBSA / congeneric RBFE on crystal control + top diverse hits);
  - **~10%** Independent recomputation audit, RSI closeout, and deliverable writing.

## 3. Adaptive Pivot Ladder When Controls Fail
- Diagnose failure before spending more compute: separate **pose sampling** (`best_mode_rmsd_A <= 2.0 Å`) from **score ranking** (`top1_rmsd_A`, `ROC-AUC`, `EF5%`) via `moldarwin_rescore_evaluate`.
- **Sampling OK, ranking failed** (common on shallow PPI grooves): benchmark orthogonal engines already present in `engines_cli` (e.g., Gnina 3D-CNN, Vinardo/AD4, 3D pharmacophore/shape, MM-GBSA) on identical multi-mode poses using `<15%` of budget.
- **All cheap oracles fail calibration**: do **not** lower the gate to fake a pass. Halt scaled screening honestly and pivot remaining budget to explicit-solvent MD/MM-GBSA control rescue, receptor-ensemble diagnosis, or an explicit No-Go report with exact denominators.

## 4. Purposeful Subagent Delegation & Self-Healing Evolution
- **Keep the Coordinator lean (50–70% lower token churn):** When your host supports subagents, partition resources cleanly via `moldarwin.runtime.subagents.partition_resources_for_subagents(env, ...)` and `build_subagent_brief(...)` so every subagent receives a disjoint GPU slice, disjoint `-pinoffset` CPU cores, and an isolated `work/subagents/<name>/` directory, returning only a `<=3 KB` JSON handoff (`validate_subagent_handoff`).
- **Four high-ROI subagent roles:**
  1. `intake-scout` (CPU-only, fast/cheap model): fetch RCSB/ChEMBL/PubChem structures & assays, verify SHA-256, return compact manifest.
  2. `gpu-branch` (2–4 parallel competing branches on disjoint GPU slices): run competing protocol hypotheses (e.g. hydration/forcefield/rescorer/selectivity targets) simultaneously, then kill losing branches early via `moldarwin.evolve.prune_protocol_branches` and reclaim freed GPUs.
  3. `physics-debugger` (disposable context): first match tracebacks against `moldarwin.research.fault_rsi.match_known_faults(...)`; isolate multi-step crash debugging away from the main thread.
  4. `verifier-writer` (fresh unbiased context): recompute final metrics directly from raw disk outputs and generate plots/reports.
- **Self-healing RBFE & synthesizable evolution:** Never stop passively on coarse FEP overlap — auto-insert windows with `moldarwin.physics.refine_lambda_schedule_from_overlap`, pack `k=2–3` windows/GPU via `render_packed_fep_runner`, extend only unconverged windows via `plan_selective_window_extensions`, and evolve neutral synthesizable analogs with `moldarwin.evolve.{generate_bioisostere_analogs,rank_evolution_generation}`.
