# A0001 native Generation reconstruction + fresh route enumeration

**Status:** offline-tested workflow; live PTV Visum COM confirmation required.
**Entrypoint:** `01_SPUSTIT_V24917_REBUILD_GENERATION_FRESH_PATHS_SILENT.py`

## Why this replaces the previous resume attempt

The original accepted A0001 checkpoint claims matrix hash
`d3d41a7b64f06e94d3c0001e120176ce1c2141c0de71753cba8e2559992d8d5c`.
After the failed TD rollback, 37 matrix fingerprints and overall state hash
match the re-opened model with matrix hash
`22dc5ab9027dbb753b38b09f6842a3572e474b12a2e8d264415c9f2c4f63565e`.
A second full baseline recompute did not restore the original matrix hash.
The past source checkpoint was therefore not a reliable direct matrix authority.

**This branch retains A0001 accepted Generation coefficients** (hash
`b10e94aef55e4943f326fc05217e0d8e9ebe6ef5a4742ee57dabcdcbd35c2d49`)
and the frozen CSD/TD reference. But it does **not** claim the old 37 OD
matrix fingerprints remain identical. It establishes a new native matrix
authority from the approved coefficient state and then makes a completely
new path epoch by re-enumerating routes from that native state.

## Windows PTV Visum procedure

1. Keep the original A0001 .ver and its adjacent `.semantic.json`, original
   `CALIBRATION/RUN_STATUS.json`, and
   `CALIBRATION/GENERATION_COUNTS_REFERENCE.json`. The old large
   `TWO_MODE_PATH_STORE.sqlite` is *not* needed or touched.
2. Save unrelated unsaved work. This dedicated launcher calls
   **Visum.IO.LoadVersion** on the original accepted .ver.
3. In Visum select/open
   `.../RUN_20261030_143622_183126/CALIBRATION/CHECKPOINTS/ACCEPTED_A_0001_8dcf6dca8fa2.ver`.
4. From the new package run
   `01_SPUSTIT_V24917_REBUILD_GENERATION_FRESH_PATHS_SILENT.py`.
5. A NEW sibling `R1_15A2_V16_RUNS/RUN_*` is created, never a child
   of the original `CHECKPOINTS` directory. The outer project
   `R1_15A2_SILENT_DEBUG` directory contains the trace and compact ZIP.
6. In the new run's `CALIBRATION`, inspect
   `A0001_REBUILT_GENERATION_AND_FRESH_PATH_AUTHORITY.json` and
   `REBUILT_GENERATION_FRESH_PATH_EPOCH/PATH_EPOCH.json`. Both must exist
   and be verified before cycle-1 TD is allowed to start.

## Exact operations and control gates

- Verify original .ver SHA256 and the original A0001 seven-field sidecar as
  metadata. Force **real disk reload**; verify A0001 six non-matrix semantic
  hashes in the live Visum preflight. No original matrix hash is adopted.
- The V24917 parent creates its usual isolated working .ver, validates
  profile authority, and performs original `adapter.assign(supply_only=False)`.
- Verify `LONG_MASK_EXECUTION_PLAN.json` contains native
  `THROUGH_TD` ops 1/5/6, realization ops 8/10/11/12/14, and
  assignment ops 17/18/19/20. Verify the source Generation and TD parameter
  hashes were preserved by the full native recompute.
- Verify exactly 37 live 681×681 OD matrices and 248 count profiles.
- Call the existing `adapter._build_cache(...,
  build_sequence_evidence=False, allow_persistent_restore=False)`, requiring
  a newly completed path store. Check that this export did **not** mutate
  live Visum state. The original sqlite is not consulted.
- Publish the newly measured per-matrix SHA256 and new composite matrix and
  semantic state hashes, plus the NEW route basis. The old A0001 hash is
  included for **contrast only**, not as a parity requirement.
- Resume cycle-1 `TD_FINECDF_V17` on the independently recomputed matrix/path
  state, with the accepted A0001 Generation *coefficient* step and original
  frozen objective reference. Do not rerun Generation optimization in that
  one already-accepted substep. Subsequent coupled cycles proceed under
  unchanged V24917 rules and may refresh path epochs normally.
- Fail closed if the native phase plan is missing, the source coefficients
  changed, profile inventory changed, full path enumeration fails, or a
  newly built SQLite is missing/overlaps the old run.
- **Methodology:** inherited accepted count 1 refers solely to the accepted
  A0001 Generation coefficient change. The reconstructed demand matrix state
  is a NEW native authority, not the accepted A0001 OD state. This distinction
  is persisted in the report. Original source .ver and original SQLite
  remain untouched. No direct OD matrix writes are performed.

This script does not bypass native IPF convergence, count/profile gates,
or protected-profile acceptance. If a TD failure causes a genuine state drift,
the original controller still stops. The only intended concession is the
explicit user-authorized *new matrix and path epoch* (no false old hash equality).

## Validation

Run `pytest -q tests/test_v24917_rebuild_generation_fresh_paths.py` and
the full original regression suite. These are offline Python tests, not
Windows Visum COM execution. The first live result decides whether the
reconstructed A0001 coefficient start and new path basis can continue into TD.
