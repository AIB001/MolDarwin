Discover and physically validate purchasable non-covalent small-molecule inhibitors targeting the human KEAP1 Kelch-domain–Nrf2 protein-protein interaction pocket.

You own the full scientific workflow within the machine charter (`charter.json`: 45-minute wall-clock budget, idle GPUs only): select high-resolution experimental structures and verified controls, calibrate and diagnose pose sampling versus ranking before any scaled spend, dynamically size compute to fit the remaining time budget, and test top hits alongside a positive control using explicit-solvent physics. If no fast ranking function passes honest calibration, do not fabricate a pass — pivot to higher-fidelity physics or deliver an honest no-go diagnosis.

Write final reproducible deliverables under `delivery/`:
- `delivery/REPORT.md`
- `delivery/summary.json` (including `target`, `gate_passed`, `control_calibration`, `screened_count`, `physics_validation`, and `wall_clock_s`)
- `delivery/top_candidates.csv` (required if `gate_passed` is true)
