# TB-Science Style Autonomy Benchmarks for MolDarwin

Inspired by **Terminal-Bench Science (TB-Science / Harbor)**, every task here separates:
1. **Minimal Scientist Prompt (`instruction.md`)**: 3–5 sentences stating only the scientific objective, budget charter, and deliverable paths — *no PDB IDs, no engine names, no phase checklists, no GPU indices*.
2. **Machine Charter (`charter.json`)**: explicit wall-clock and GPU etiquette limits (`idle_only`), injected once at `SessionStart` via `[moldarwin-env]` (~80–110 tokens) or read via `moldarwin_capabilities(include_environment=True)`.
3. **Isolated Objective Verifier (`verify_delivery.py`)**: never shown to the agent; audits deliverables, raw-file consistency, epistemic honesty (no uncalibrated screening), charter compliance, and Codex vs Claude Code token/turn efficiency after the run exits.

## Tasks
- `tasks/hsp90_open_discovery/`: Human HSP90α N-terminal ATP-binding domain — tests autonomous target grounding, control calibration, micro-pilot budget sizing, multi-GPU screening, and explicit-solvent physical stability verification.
- `tasks/keap1_ppi_open_discovery/`: Human KEAP1 Kelch-domain–Nrf2 PPI interface — tests cross-target RSI skill transfer onto a challenging polar PPI groove (diagnosing pose sampling vs score ranking, orthogonal rescoring rescue, or honest no-go + physics escalation).

## Grading a Completed Run
```bash
python3 benchmarks/tb_science/verify_delivery.py \
  --run-dir /path/to/run \
  --charter benchmarks/tb_science/tasks/keap1_ppi_open_discovery/charter.json
```
