# V24917 A0001 resume: TD cycle 1 without route re-enumeration

## Start

1. Keep the **original** `RUN_20261030_143622_183126/CALIBRATION` folder and its path-store SQLite file intact.
2. In PTV Visum select the original `CALIBRATION/CHECKPOINTS/ACCEPTED_A_0001_8dcf6dca8fa2.ver` (not B0000 or the post-crash in-memory state).
3. **Warning: the launcher intentionally calls Visum.LoadVersion and discards any unsaved model changes in the active Visum session.** Only use it after saving your other work. Use **Scripts > Run script file** and choose `01_SPUSTIT_V24917_RESUME_A0001_TD_NO_ENUM_SILENT.py` from the updated repository directory. The new launcher uses the existing V24917 PREFLIGHTIOFIX1 installation, but has an explicit A0001 continuation and read-only path-store rehydration.

The launcher requires these unchanged original run artifacts:

- `CALIBRATION/CHECKPOINTS/ACCEPTED_A_0001_8dcf6dca8fa2.ver.semantic.json`
- `CALIBRATION/GENERATION_COUNTS_REFERENCE.json`
- `CALIBRATION/RUN_STATUS.json`
- `CALIBRATION/DEMAND_CYCLE_01_GENERATION/DESIGN/GENERATION_CACHE/TWO_MODE_PATH_STORE.sqlite`

The launcher now calls `Visum.IO.LoadVersion` (fallback `Visum.LoadVersion`) even if the current filename already matches the accepted checkpoint. The source `.ver` bytes must match SHA-256 `9f209ce288cb8693c4ef22649b229e6f404d52c0451bd0bbdc15827b55300f63`; its **semantic state**, before and after baseline realization, must match the seven approved field hashes in `A0001_TD_RESUME_AUTHORITY.json`.

## Checkpoint inside an older RUN_* tree (fixed)

The source checkpoint remains at:
`...\2022\R1_15A2_V16_RUNS\RUN_20261030_143622_183126\CALIBRATION\CHECKPOINTS\ACCEPTED_A_0001_8dcf6dca8fa2.ver`.

The **new** run must be created at the SAME `R1_15A2_V16_RUNS` level:
`...\2022\R1_15A2_V16_RUNS\RUN_<new_unique_timestamp>`.
Never create it below the old `RUN_20261030_143622_183126`, its
`CALIBRATION` or `CHECKPOINTS`. Neither the checkpoint nor its large
`TWO_MODE_PATH_STORE.sqlite` should be moved.

The V24916 frozen project-root resolver correctly normalizes the source to
`...\2022`, but its original postcondition incorrectly rejects even a new
direct RUN_* sibling because both share the same `R1_15A2_V16_RUNS` ancestor.
This A0001-only launcher installs a stricter sibling-only postcondition:
the frozen original resolver's project base and source RUNS root must match;
new output must be a direct, unique RUN_* child; actual nesting, changed
prior roots and source-run collisions remain fatal. The previous run and
its SQLite remain read-only evidence.

## SILENT logs and finding the new run

For this nested checkpoint only, SILENT logs and the final compact debug ZIP
are written to the project-level `...\\2022\\R1_15A2_SILENT_DEBUG` folder.
The SILENT wrapper scans `...\\2022\\R1_15A2_V16_RUNS` for the new direct
sibling `RUN_*`. It records the real source checkpoint path unchanged.
It never creates `R1_15A2_SILENT_DEBUG` or `R1_15A2_V16_RUNS` under the
source `CHECKPOINTS` directory.

## What the launcher preserves

- Resumes accepted count **1**, outer cycle **1**, substep **TD_FINECDF_V17**. It does not replay the accepted Generation step (scale 0.538158).
- Retains the original `GENERATION_COUNTS_REFERENCE.json`, verified by canonical reference hash, not a new baseline.
- Recovers the original epoch-1 SQLite route basis from original B0000 state, verifying its parent snapshot hash, exact path basis hash, canonical comparison hash, full link dictionary, profile-index geometry-to-profile_hits parity, SQLite quick integrity and read-only status.
- Fresh native baseline assignment + skims and live diagnostics remain required. Route enumeration and SQLite path export do not run at restart.
- The intact V24917 TDJOINT dynamic evaluator and rollback/acceptance rules remain in control.
- Any attempt to create a new path epoch (new positive OD support, local plateau or missing store) raises `A0001_RESUME_NO_PATH_ENUMERATION_ALLOWED`, without a new COM route export. This is deliberate: **formal path-epoch stationarity cannot be claimed** without its eventual fresh comparison enumeration.

## Important limitation

`SLOT_A.json` explicitly has `persistent_cache_id=null` and `persistent_cache_dir=null`: original V24916 was configured with the persistent path-cache manager disabled. The SQLite database was therefore stored inside the original run's Generation design folder, **not** in a separate persistent cache root. If that database was deleted, the JSON hashes are not a substitute for geometry/path-volume evidence and a zero-enumeration restart is impossible; the launcher correctly refuses to proceed.

The source `RUN_STATUS.json` must still contain the verified accepted STEP1 record with `search_complete=false` (early accepted by `STEP1_FIRST_ELIGIBLE_KEPT`) and `td_completed=false`. The continuation does not falsely change `search_complete` to true. The next Generation phase remains locked until TD has returned normally.

## Code and tests

- New: `r1_15a2_resume_a0001_v24917.py`, `A0001_TD_RESUME_AUTHORITY.json`, `01_SPUSTIT_V24917_RESUME_A0001_TD_NO_ENUM_SILENT.py`.
- Regression: `tests/test_v24917_resume_a0001_td_no_enum.py`.
- Required host validation: open the original checkpoint and inspect `RESUME_EVIDENCE/A0001_PATH_EPOCH_RESTORE.json`, `RUN_STATUS.json`, unchanged source `.ver` SHA and baseline source/working semantic parity.
- Offline Python tests do **not** constitute a real Windows PTV Visum COM test.

## Methodology

The original source has one accepted Generation step but no completed TD cycle. The restart is a **partial cycle continuation**, not a fresh run or a new accepted optimization. Its active path epoch is geometry/volume evidence for Generation/Supply proposals only; acceptance still requires a fresh native assignment with live 12D/11D.

## 2026-10-30 reopen matrix fingerprint incident

The original A0001 acceptance sidecar records matrix_hash
`d3d41a7b64f06e94d3c0001e120176ce1c2141c0de71753cba8e2559992d8d5c`.
Reopening the exact same .ver (SHA-256
`9f209ce288cb8693c4ef22649b229e6f404d52c0451bd0bbdc15827b55300f63`)
and running the V24916 read-only preflight yields matrix_hash
`22dc5ab9027dbb753b38b09f6842a3572e474b12a2e8d264415c9f2c4f63565e`.
All six other semantic field hashes match.

This branch does NOT treat unchanged .ver file bytes as equivalence of
in-memory matrix values. It allows *only* V24916's differing matrix digest
to be deferred through a stable read-only preflight and then requires the
V24917 **strict uncached** snapshot to match ALL SEVEN checkpoint fields
before any resumed TD or path-store use. If that full comparison fails,
the controller stops and publishes
`RUN_*/CALIBRATION/A0001_MATRIX_REOPEN_FORENSICS.json` (also copied into
the SILENT DEBUG.zip), including the matrix numbers, dimensions, per-matrix
SHA-256 of float64 LE arrays, V24916/V24917 totals, and exact changed
semantic domains. It does not invent the unavailable original per-matrix
fingerprints from the sidecar.

If the strict V24917 matrix hash still equals the reopened V24916 value,
the checkpoint's original in-memory accepted matrix state was NOT proven
to survive serialization/reopening. This is a real safety blocker, not
something to bypass by modifying a manifest, tolerance, or stored authority.
`LIVE_VISUM_NOT_RUN` for this patch.

## Staged native OD rehydration (fix to matrix-state acceptance)

After a .ver is reopened, its OD matrices may not be in the identical
post-Generation native recomputed state captured by the A0001 sidecar. The
already-existing parent controller has an authorized baseline native
assignment/recompute step that intentionally permits matrix_hash to change
while six immutable parameter hashes stay exact.

For A0001, the stage-gated behavior is:
1. Verify source .ver byte hash and sidecar, plus six identical non-matrix
   hashes at V24916 read-only preflight. The matrix mismatch is *not*
   accepted; it is deferred solely to native recompute and V24917 verification.
2. Verify the same six fields again using V24917 uncached snapshot, write
   A0001_MATRIX_REOPEN_FORENSICS.json with phase BEFORE_NATIVE_BASELINE.
3. Allow the *original parent* to create its isolated working .ver and execute
   the existing full baseline native recompute (no added COM path export).
4. At BASELINE diagnostics, before restoring any SQLite path epoch or
   executing TD proposals, take a second V24917 **uncached** snapshot and
   demand exact identity of all seven fields, including the previously
   mismatched matrix_hash and the semantic_state_hash. Then allow the
   read-only original path-store epoch rehydration and cycle-1 TD.
5. If the post-native identity differs, stop: no old SQLite cache is adopted,
   no TD performed, and the new working run's debug ZIP includes the exact
   per-matrix SHA-256 list. The original accepted .ver is unchanged.

**No automatic reference rebasing, no tolerance loosening, no new path
enumeration, and no promotion of an unverified state as accepted.** The
live Windows/Visum result of this staged recovery has not yet been observed.

## 2026-10-30 16:21 forensic result and HARD_DISK_REOPEN

Original aborted TD/rollback evidence `GENFIX2_PARENT_PROOF_RETAINED` has
exactly the **same 37 per-matrix float64 SHA-256 fingerprints and the same
snapshot state hash** as the subsequent 16:21 restart, both with matrix_hash
`22dc5ab9027dbb753b38b09f6842a3572e474b12a2e8d264415c9f2c4f63565e`.
The sidecar attached to accepted A0001 instead claims
`d3d41a7b64f06e94d3c0001e120176ce1c2141c0de71753cba8e2559992d8d5c`.

Importantly, **IO.CurrentVersionFile is a file name, not proof that file
contents were deserialized after failed in-memory transactions**. The previous
launcher explicitly never called LoadVersion, even though the original
`SaveVersion` could make the CURRENT filename look correct while the model
was later modified. This means it remains possible that the accepted .ver
was correct all along but a stale live Visum session was reused.

This dedicated launcher now:
1. validates original .ver file bytes and the sidecar/SQLite/reference metadata;
2. forces `r1_15a2_runtime_v1.load_version(visum, checkpoint)` using the
   verified original .ver **every time**, also if the filename already matches;
3. validates current COM version path and .ver bytes again (no overwrite);
4. uses the existing V24916 live structural preflight but requires *all seven*
   checkpoint semantic hashes to match **before allocating or modifying a new run**;
5. if exactly matched, creates an isolated sibling RUN_* and uses the original
   native baseline recompute with a second strict V24917 all-seven-field gate
   before reattaching the read-only route basis and starting TD_FINECDF_V17;
6. if the forcibly reopened file still yields the old 22dc matrix hash, it
   fails early with `A0001_RESUME_LIVE_SEMANTIC_DIFFERENCE:matrix_hash`.
   This would show the *serialized* checkpoint is not equal to the accepted
   in-memory scientific authority. A different restart mode would then need
   deterministic recovery of those matrices, not a bypass of the hash check.

The launcher **does not** regenerate paths, write directly to OD matrices,
or promote an unverified state. Since it deliberately discards unsaved Visum
model state, this behavior is restricted to the dedicated A0001 restart script.

Separate performance observation: the 11D inline DIAGFAST parity check fell
back to LEGACY (three output artifacts not equal); that was NOT the cause of
the A0001 resume stop. The test result below is still an offline test until
the new hard-disk-reopen launcher runs in PTV Visum on Windows.
