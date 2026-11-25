---
name: moldarwin-target-parameters
description: Choose the receptor, binding site and starting screening parameters for a target that has not been screened here before, and say which of them are transferable defaults and which cannot be set until this target's own controls have been measured.
---

# Start a new target without inheriting another target's numbers

Use this capability at the point where a campaign moves to a protein nothing
here has screened, and a cascade configuration has to be written. It covers
receptor selection, site definition, receptor preparation and the starting
values for engine and gate settings. It does not run a screen and does not
mint a gate authorisation.

## The one number that must not be transferred

A docking score threshold is not a property of a scoring function. It is a
property of a scoring function **on a target**. Measured here, on two targets
with the same engine: a Uni-Dock cutoff of `-8.0` sits above every known SND1
binder -- the best was `-7.78`, and the gate kept 2 molecules out of 5,822 --
while on ALK2 the same `-8.0` sits below the weakest of eight known actives at
`-8.497` and keeps 69% of the library. One number, a factor of about two
thousand in what it does. On ALK2 the eight actives spread from the 1.7th to
the 81st percentile of the population.

So: **carry the cascade, do not carry the threshold.** The shipped defaults
(`-9.5` in the backend catalogue, `-8.5` in the starter cascade, and they
differ for a recorded reason) are starting points for a target like the one
they were calibrated on, and a guess otherwise. Treat a transferred threshold
as an unmeasured parameter until this target's controls say otherwise, and
record it as `convention`, not as a measurement.

Where percentiles are wanted instead of absolute scores,
`moldarwin.campaign.calibrate.percentile_threshold(population, keep, direction)`
converts one into the scalar a gate takes. There is no percentile gate backend:
`GateConfig.settings` holds `{"maximum": ...}` or `{"minimum": ...}`, so the
conversion is done once against a screened population and the resulting number
is written into the configuration, with the population it came from recorded
beside it.

## Choosing the receptor

`molorigin-structure-templates` finds experimental structures, cognate ligands
and templates. Bring back, and record: the entry, the chain, the resolution,
what the co-crystallised ligand actually is, and whether the construct covers
the site. A CCD component may be buffer, ion or cofactor -- not every
non-polymer is a reference ligand, and a predicted model's ligand pose is not
an experimental reference at all.

Nothing in this project selects a receptor, a chain, a protonation state, a
tautomer or a His flip. Those are decisions, they are recorded as decisions,
and `moldarwin_screen_prepare_continuation` is how a campaign branches when
more than one receptor is worth carrying.

## Defining the site, which the code will not guess for you

The site can be given three ways, and the rules differ depending on where you
supply it.

`TargetConfig` itself requires **at least one** and refuses two site *files*
(`reference_ligand_path` and `pocket_path` together) with a plain `ValueError`.
A box **alongside** one file is the ordinary resolved state, not a
contradiction: `resolve_target` derives the box from the file so that engines
reading six numbers and an engine reading a ligand search the same volume.

At the CLI and `merge_target` boundary the rule is stricter and the errors are
coded: naming the site more than once across `--reference-ligand`, `--pocket`
and `--box` raises `DOCKING_TARGET_SITE_AMBIGUOUS`, and a receptor with no site
at all raises `DOCKING_TARGET_SITE_REQUIRED`. Those codes come from
`merge_target`, not from `TargetConfig`'s own validator.

The three forms:

- `reference_ligand_path` -- a co-crystal ligand used purely as a ruler.
  `box_from_structure` takes the smallest axis-aligned box over its atoms and
  adds 4 Å per side. Nothing about its chemistry is read, so a file that could
  not be parsed as a molecule still works as a ruler.
- `pocket_path` -- a pocket PDB.
- an explicit box: exactly six numbers. Three plus an invented edge length is
  refused on purpose, because that is guessing at the size of someone else's
  binding site.

If both a box and a site file are given, the site's centroid must fall inside
the box on every axis or `DOCKING_SITE_DISAGREEMENT` is raised. Containment,
not equality: the box may be deliberately larger.

There is **no pocket detection** here. No fpocket, no SiteMap, no cavity
search. A target with no co-crystal ligand and no pocket file needs the site
established outside this project and brought in. The published guidance that a
box should be about 2.9 times the ligand's radius of gyration is recorded in
the knob catalogue as literature; it is not implemented, so applying it is a
manual calculation whose result is typed in as six numbers.

## Preparing the receptor

`ReceptorPreparation` defaults to repairing, dropping waters and dropping
heterogens, keeping metals. `prepare_receptor_pdb` rebuilds missing **atoms**
in residues that are present, reports missing **residues** without building
them, and never passes `--allow_bad_res`. Its `PreparationReport` -- waters
removed, heterogens removed, metals kept, atoms rebuilt, gaps not built -- is
the record of what the structure became, and it belongs in the task's evidence
because a later score is a score on the prepared receptor, not the deposited
one.

Protonation and tautomers are not guessed. If they matter for this site, they
are decided and supplied.

## Where the target actually goes

The receptor and box must be in the **cascade configuration**. MolDarwin's
screening path calls `Screen.plan(config_path, library_path)` without a target
argument, so a target passed anywhere else is not read. Write it with
`moldarwin.campaign.design.compose(name, tiers, target={...})`, or through
`moldarwin_screen_configure(workspace, configuration)` with schema
`moldarwin-cascade-design/1`; revise an existing file with
`moldarwin.campaign.configuration.materialize(source, changes)`.

`docking_requirements` derives which target fields this particular cascade
needs by inspecting the backends it uses, so a KarmaDock-only cascade is never
asked for a PDBQT. Let it tell you what is required rather than filling in
every field.

## Engine and sampling settings: what is and is not target-driven

Engine selection today is **availability-driven**: a criterion is included if
its plugin and assets are installed. Nothing reads the target's class. A
kinase ATP site and a shallow interface get the same engines unless somebody
decides otherwise, and that decision, if made, is a recorded one.

Two settings where the measured answer is already known and saves effort:

- GNINA `exhaustiveness` defaults to 8. Raising it to 32 quadruples that
  tier's cost for an effect no benchmark in the knob catalogue separates from
  zero. Do not spend the budget there first.
- Rescoring carries the largest published rank-correlation gain of the
  catalogued knobs. `moldarwin.rescore` has the SDK and no MCP tool, so it is
  reachable from the Python side only. `load_receptor(path, pocket_centre=...,
  radius=...)` truncates the receptor, and the truncation radius changes the
  features: measured here, 18 Å against a 12 Å outer shell changed feature
  counts by up to 17. Use `radius_for(poses, centre)` for the smallest
  lossless radius rather than picking one.

## Establish the starting point, then stop guessing

With a receptor, a site and a cascade, the first real measurement is a control
panel, not a library. Assemble known actives **and** known inactives --
`PanelMember.known_active` must be a literal boolean and is the operator's
assertion, not something this project measures -- screen them with an
`--id-column` so members stay traceable, and call
`moldarwin_calibrate_gates(workspace, run_id, panel_json, required_recall)`.

It answers two independent questions: whether the funnel **retains** the known
actives, and whether the engines **rank** them. A funnel can keep everything
and rank nothing. Both verdicts are reported separately for that reason, and
`moldarwin_authorize_gates` mints a token only against a panel that passed,
bound to the compiled revision -- which includes the library, so a changed
library needs a new token.

Nothing here assembles a panel. There is no DUD-E, LIT-PCBA or decoy
generator, and a panel of binders only cannot distinguish a discriminating
gate from one that keeps everything.

A detail that has caused a false pass: if panel members are declared under
names the screened library does not carry, the join finds nothing and the
calibration reports full recall on a funnel that deleted everything. The
`panel_identity` verdict exists to catch exactly that. Read it.

## What this capability does not establish

The `redock_consistency` tier measures **dock-redock self-consistency** -- the
same engine, a fresh conformer, a different seed -- and not crystal-pose
accuracy. Two runs can agree on a wrong pose. Its 2 Å default is an
engineering threshold borrowed from crystal-redocking evaluation, not proof of
experimental accuracy. There is no cross-docking or co-crystal RMSD harness
here; pose accuracy against a deposited ligand has to be measured elsewhere
and brought in as evidence.

Everything chosen here is a starting point with a stated basis. Record which
values are `convention` (carried from defaults), which are `literature` (read
from a paper, via `moldarwin-method-literature`), and which are
`measured_here` (this target's own panel). Only the third kind may be defended
as a property of this target.
