Discover and physically validate purchasable small-molecule inhibitors targeting the human HSP90-alpha N-terminal ATP-binding pocket.

You have full ownership of experimental design, structure selection, control calibration, engine selection, compute scaling, and verification within the workspace and machine charter (`charter.json`: 45-minute wall-clock budget, idle GPUs only). Measure throughput on a small pilot before scaling, do not run scaled screening on an uncalibrated scorer, and validate top candidates against a positive control with higher-fidelity explicit-solvent physics rather than relying on static scores alone.

Write final reproducible deliverables under `delivery/`:
- `delivery/REPORT.md` (methods, exact control calibration denominators, scaling rationale, physical validation comparison, and explicit limits of claims)
- `delivery/summary.json` (structured summary with `target`, `gate_passed`, `control_calibration`, `screened_count`, `physics_validation`, and `wall_clock_s`)
- `delivery/top_candidates.csv` (ranked diverse shortlist with SMILES and measured metrics, if the calibration gate passes)
