# Three-Pillar CADD Architecture & PRISM Boundary Contract

Date: 2026-11-27. Status: **Normative architectural boundary for MolDarwin v2.1 (`cadd_drug_design`).**

## 1. First-Principles Division of Labor

MolDarwin is an **epistemic CADD harness and cross-pillar drug-design reasoning brain**, not a monolithic GROMACS wrapper and not a replacement for its three vendored CADD engines.

| Layer | Owns | Must NOT Drift Into |
| --- | --- | --- |
| **MolOrigin** (`asset/molorigin`, MCP `data` pack) | Target evidence, literature assays, PDB templates, selectivity dossiers, analogue search, purchasable sourcing | Admission verdicts or mutable unsealed HTTP fetches |
| **MolCat** (`asset/molcat`, MCP `screening` pack, 53 plugins) | Standardization, docking (`UniDock`/`Gnina`/`KarmaDock`/`Redock`), Boltz2, OpenADMET/ADMET-AI, Lilly/medchem rules & alerts, AiZynthFinder retrosynthesis, SA/SCScore, pose strain, specificity panels, diversity, MD handoff | Re-implementing ad-hoc SMARTS/ADMET clones outside MolCat when MolCat plugins exist |
| **PRISM** (`asset/prism`, MCP `prism` pack) | 3D SBDD generation (`prism/generation`, 6 models), grounded local editing & LLM graph planning (upstream `AIB001/PRISM@84b5dfa` `prism/design/`), explicit-solvent MD/FEP/MM-PBSA/PMF/REST2, trajectory analysis (`prism/analysis`) | Becoming the sole active domain pack or absorbing MolDarwin's epistemic kernel |
| **MolDarwin Core + Design Brain** (`src/moldarwin/`) | (a) Domain-agnostic Epistemic & RSI Kernel (`ResearchJournal`, `authority` `0/7` unguarded SPENDS, `FaultRSIRegistry` Tier-1 admission, thin 16-tool MCP, 3-tier lazy skills); (b) Cross-pillar Drug-Design Intelligence (`moldarwin.design.{pocket,sar,dmta}` + `moldarwin.evolve`) connecting all three engines into one closed DMTA loop | Accumulating engine-specific GROMACS/MDP/CPU hacks inside MolDarwin core |

## 2. Explicit Containment of `src/moldarwin/physics/`

Because `asset/prism` is frozen at commit `f0492d9` (`2026-09-12`) under Hard Constraint 6 (*never edit `asset/`*), several GROMACS 2026 and FEP sampling compatibility shims were developed inside `src/moldarwin/physics/` during live multi-GPU campaigns. To prevent permanent architectural drift, `moldarwin.physics.PHYSICS_MODULE_BOUNDARIES` enforces a strict split:

### A. MolDarwin Scientific Verification Boundary (`active_boundary`)
Belong permanently in MolDarwin because they verify invariants **across** engines (LLM, co-fold, MolCat, PRISM):
- `moldarwin.physics.preflight` — Any-Origin 3D clash/geometry/element preflight, conserved crystal bridge waters, soft non-destructive medchem triage.
- `moldarwin.physics.rescoring` — Tie-aware ROC-AUC/EF calibration, paired RSI rescorer comparison, property-shortcut check.
- `moldarwin.physics.prism_gen` — Honest PRISM SBDD adapter discovery and Any-Origin pose qualification.

### B. PRISM Runtime Compatibility Shims (`bugfix_only_until_upstreamed_to_prism`)
Retained strictly for live GROMACS 2026 execution against frozen `asset/prism@f0492d9`, **frozen to bugfixes only**, and earmarked for upstream migration to `AIB001/PRISM`:
- `moldarwin.physics.prism_bridge` → upstream to `AIB001/PRISM:prism/builder` & `prism/analysis`
- `moldarwin.physics.prism_fep` → upstream to `AIB001/PRISM:prism/fep`
- `moldarwin.physics.adaptive` → upstream to `AIB001/PRISM:prism/fep` & `prism/sim`
- `moldarwin.physics.enhanced_sampling` → upstream to `AIB001/PRISM:prism/fep` & `prism/sim`

## 3. Upstream PRISM Refresh Path (`prism/design` @ `84b5dfa`)

Upstream `AIB001/PRISM` added `prism/design/` in commit `84b5dfa` (`2026-10-15`: `DesignSpec`, constrained FLOWR local inpainting/growth, peptide curation, M1 training, and evidence-bound LLM graph editing). Note that `prism/design/README.md` explicitly leaves retrosynthesis evaluation, case retrieval, and multi-round DMTA feedback to downstream orchestration — which matches MolCat + MolDarwin's `moldarwin.design` boundary cleanly.

When ready to adopt upstream `prism/design` (and once the GROMACS 2026 shims above are merged into `AIB001/PRISM`), refresh the vendored tree cleanly through the auditable refresh script:

```bash
python tools/vendor_assets.py --asset prism --write
git diff asset/MANIFEST.json
```

Until that explicit vendor refresh, `CaddDomainPack.probe_pillars()` reports `prism_design_present_in_pinned_asset: false` honestly (Hard Constraint 7).
