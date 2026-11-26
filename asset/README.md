# Vendored assets

Three packages, copied in rather than depended on, plus one reference panel lifted out of a
place it could not be found.

> The commits below are checked against `MANIFEST.json` by `tools/verify_assets.py`. They drifted
> once -- this table named two commits the manifest had long since superseded, in the prose that
> introduces the mechanism for preventing exactly that -- so the check now exists and this table is
> no longer maintained by hand alone.

The "Files" column is what `MANIFEST.json` recorded when the asset was vendored. Counted on disk
today, `molcat/` holds 177 and `prism/` 499; `molorigin/`'s 64 still agrees. Those three
differences are the drift `tools/verify_assets.py` reports, and they predate the 2026-11-25
rename described below -- the rename changed file contents and directory names, not which files
are present.

| Asset | Source commit | Files (manifest) | Size | What it is |
| --- | --- | --- | --- | --- |
| `molcat/` | `06f15d7e8274` | 168 | 4.0 MB | Ligand triage, docking and independent redock consistency. Content-addressed artifacts, enforced contracts, per-molecule gates. |
| `prism/` | `f0492d964795` | 504 | 24.7 MB | GROMACS system building, MD, FEP, MM/PBSA, PMF, REST2, and a large trajectory-analysis layer. |
| `molorigin/` | `82f4f34e54cb` | 64 | 0.5 MB | Database access, target evidence dossiers, local catalogs and compound sourcing; six discoverable search skills. |
| `reference/approved_drugs.py` | from `molcat` | 1 | 8 KB | 77 approved oral drugs with an in-window / out-of-window split. |

`MANIFEST.json` carries the exact commit, subject and commit date of each source, the file
and byte counts, a digest over the whole copied tree, and what was excluded. Verify an asset
against it before trusting a number that came out of it.

## Why vendored rather than depended on

Because a version is part of a measurement. A free-energy number is a statement about a
force field, a water model, a lambda schedule and an estimator, and a screening verdict is a
statement about a threshold and a rule revision. An asset pinned by commit and verified by
tree digest means a result recorded last month can be reproduced today, and means a changed
asset is a visibly different asset rather than a silently different answer.

The packages are not independently installed by default. MolDarwin puts `molcat/src`, `prism` and `molorigin/src`
on the path explicitly, so which copy is in use is a fact about the process rather than a
fact about the environment. Verified: importing with those paths first yields
`asset/molcat/src/molcat/__init__.py`, `asset/prism/prism/__init__.py` and
`asset/molorigin/src/molorigin/__init__.py`, a registry
of 59 plugins, PRISM 1.2.0 and MolOrigin 0.5.0. Wheels include the same trees under
`moldarwin/_assets`; optional dependencies remain explicit installation extras.

## What was excluded, and why

`tests/` from all three, with one exception noted below. 103 files from MolCat, 194 files and 19.7 MB from PRISM --
the latter dominated by full CHARMM36 force-field copies duplicated into FEP test fixtures.
MolOrigin's 16 test files are also excluded; upstream suites can be run from their source repositories.
Every other tracked file was
copied, including PRISM's `prism/configs/forcefield/` (170 files), which is runtime data a
build needs rather than test material.

Nothing untracked was copied, so whatever each repository's `.gitignore` excludes is excluded
here too. For MolCat that is most of its 196 MB working tree: run workspaces, artifact
stores, caches.

## The one file lifted deliberately

`reference/approved_drugs.py` comes out of MolCat's excluded test tree. It is a panel of
77 approved oral drugs, and every threshold in MolCat's shipped defaults was calibrated
against it -- the ring ceilings, the alert actions, the Rule-of-Five bound, the Lilly demerit
actions. That makes it reference data rather than a fixture, and a calibration layer that
cannot find it would re-derive a worse version of it.

It is copied rather than imported because importing it would mean depending on a test tree
that is not here.

One further file survives the exclusion: `molcat/tests/test_aizynth_evidence.py`. It is present
on disk and not in the manifest's count, which is part of the drift named above. Either it was
added after vendoring or the exclusion missed it; `tools/verify_assets.py --deep` is what says
which, and re-vendoring is what settles it.

## Renamed after vendoring

`molcat/` and `molorigin/` are copies of the upstream projects MolCascade and MolQuarry. The
commits in the table are commits of `github.com/AIB001/MolCascade` and
`github.com/AIB001/MolQuarry`; checked on 2026-11-25, those repositories still carried those
names and no `AIB001/MolCat` or `AIB001/MolOrigin` existed.

On that date the names were replaced inside the two copies -- directories, packages,
identifiers and environment variables (`molcascade` -> `molcat`, `MOLCASCADE_*` -> `MOLCAT_*`,
`molquarry` -> `molorigin`, `MOLQUARRY_*` -> `MOLORIGIN_*`) -- and nothing else was edited; the
clone address in `molcat/README.md` was left pointing at the repository that exists. Undoing
the replacement gives back the bytes that were here before it. The copies are therefore not
byte-identical to the pinned commits, and `MANIFEST.json` still records the trees as they were
vendored: `tools/verify_assets.py` reports a mismatch, as it already did for all three assets
before the rename.

`tools/vendor_assets.py` copies a source as it is. Until an upstream project is renamed the
same way, refreshing its asset would bring the old package name back and MolDarwin would not
import it.

## Refreshing an asset

```bash
python tools/vendor_assets.py          # inspect proposed refresh; no mutation
python tools/vendor_assets.py --asset molorigin --write  # refresh only this asset
git -C . diff asset/MANIFEST.json      # read what changed before accepting it
```

A refresh changes the tree digest, which is the point: it makes the change reviewable. Read
the diff before accepting it, because an asset update is a change to every measurement taken
afterwards.

## Properties of these assets that MolDarwin is built around

**MolCat enforces its contracts.** `validate_table` checks the declared schema, non-null
columns, primary-key uniqueness and declared string enums before a stage commits, so a
contract column is a field a producer cannot leave empty rather than a field it ought to
fill. Its artifacts are content-addressed, its stage cache keys hash the full plugin
descriptor, and a checkpoint whose configuration differs is refused rather than reused.

**MolDarwin owns PRISM process execution.** PRISM's four `build_*` tools emit a GROMACS tree and a bash
driver -- `localrun.sh`, `smd_run.sh`, `mmpbsa_run.sh` -- and the caller executes it. The
hours-to-days part of the work is not in its tool surface at all. Anything driving PRISM must
therefore own process execution, which is why MolDarwin has a job layer rather than a tool call.
PRISM also has simulator APIs; the statement above describes MolDarwin's builder/driver integration.

**MolOrigin acquisition is evidence, not a measurement ruling.** MolDarwin bounds HTTP requests,
seals raw responses and workflow outputs, and registers structures with MolCat's identity
policy. Exact assays enter the active loop only through an explicit review, on historical-only
endpoints. Mutable database results are never fetched inside a cached screening stage.
