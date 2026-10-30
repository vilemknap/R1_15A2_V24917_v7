# V24917 A0001 resume: TD cycle 1 without route re-enumeration

## Start

1. Keep the **original** `RUN_20261030_143622_183126/CALIBRATION` folder and its path-store SQLite file intact.
2. In PTV Visum open the original `CALIBRATION/CHECKPOINTS/ACCEPTED_A_0001_8dcf6dca8fa2.ver` (not B0000 or the post-crash in-memory state).
3. Use **Scripts > Run script file** and choose `01_SPUSTIT_V24917_RESUME_A0001_TD_NO_ENUM_SILENT.py` from the updated repository directory. The new launcher uses the existing V24917 PREFLIGHTIOFIX1 installation, but has an explicit A0001 continuation and read-only path-store rehydration.

The launcher requires these unchanged original run artifacts:

- `CALIBRATION/CHECKPOINTS/ACCEPTED_A_0001_8dcf6dca8fa2.ver.semantic.json`
- `CALIBRATION/GENERATION_COUNTS_REFERENCE.json`
- `CALIBRATION/RUN_STATUS.json`
- `CALIBRATION/DEMAND_CYCLE_01_GENERATION/DESIGN/GENERATION_CACHE/TWO_MODE_PATH_STORE.sqlite`

The source `.ver` bytes must match SHA-256 `9f209ce288cb8693c4ef22649b229e6f404d52c0451bd0bbdc15827b55300f63`; its **semantic state**, before and after baseline realization, must match the seven approved field hashes in `A0001_TD_RESUME_AUTHORITY.json`.

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
