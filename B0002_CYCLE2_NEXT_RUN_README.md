# R1 V24917 — B0002 recovery / TD SCHOOL and LONG / new native path epoch

**Prepared:** 2026-10-30. **Source:** actual failed V24917 run `RUN_20261030_163527_853780`, PR #1 (balanced TD proposals + A0001 path-epoch lifecycle), and a new B0002-specific launcher. **Windows PTV Visum live run NOT performed by this release.**

## Why B0002, not A0001

- Cycle 1 accepted Generation and one native FineCDF TD parameter update (`WORK_E_C`), but TD optimization stopped at the 28-evaluation EXPLORE budget; SCHOOL and LONG were in the active pool but no accepted change was recorded for them. This is *progress*, NOT convergence.
- Cycle 2 attempted Generation and encountered `PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:NATIVE_CS_NOT:616:676`; the old A0001 no-enumeration guard then stopped the run.
- The source `RUN_STATUS.json` confirms `accepted_count=2`, `latest_accepted_checkpoint=ACCEPTED_B_0002_e9eb29d6b38d.ver`, raw SHA-256 `c19027ba4b3ce283d54d364b6f023f6990f4ba639870b56c7ba9a25e3fbf61b2` and 534576048 bytes. The independent BEST_SO_FAR semantic witness has semantic state hash `0c19a6443a2f2b794da2e7fd5868aeb2ab39c2eed0a70b384e91a3114fc59f17` and all seven semantic fields.
- Fresh-run baseline native assignment and skim recalculation are still necessary. They are **not** a repeat of already accepted TG/TD optimization.

## Required local source files (nothing needs uploading to GitHub)

Visum must have the original tree on the corporate Windows machine:

```
C:\Users\vilem_knap\Documents\VISUM\v45\2022\R1_15A2_V16_RUNS\RUN_20261030_163527_853780\
  CALIBRATION\CHECKPOINTS\ACCEPTED_B_0002_e9eb29d6b38d.ver
  CALIBRATION\CHECKPOINTS\ACCEPTED_B_0002_e9eb29d6b38d.ver.semantic.json
  CALIBRATION\RUN_STATUS.json
  CALIBRATION\GENERATION_COUNTS_REFERENCE.json
```

The `.ver` should be opened **exactly** in Visum; do not Save / overwrite it. The original A0001 SQLite can remain in its former folder and is not opened or copied by the B0002 launcher. Never move the checkpoint away from its original `RUN_*/CALIBRATION/CHECKPOINTS` path without updating/resealing the authority.

## How to start

1. Download **the entire source branch** that contains the PR #1 fixes plus this B0002 patch. Extract the ZIP to a NEW source directory, keeping all subfolders.
2. Open `ACCEPTED_B_0002_e9eb29d6b38d.ver` in PTV Visum 2026. Verify this file is the **current loaded** version, not a similarly named copy.
3. **First, one-shot live path smoke:** Scripts -> Run script file -> `01_SPUSTIT_V24917_B0002_PATH_EPOCH_SMOKE_SILENT.py`. It stops after a verified baseline and fresh route-support export. Expected: `B0002_NATIVE_PATH_EPOCH_SMOKE_PASSED`; it runs **zero** Generation and FineCDF candidate optimizations. Inspect `B0002_PATH_EPOCH_SMOKE_RESULT.json` and `RESUME_EVIDENCE/B0002_INITIAL_PATH_SUPPORT_SMOKE.json` before proceeding.
4. **Reopen the exact original B0002 .ver from disk in Visum** (the smoke's working model is not the accepted source for another run). Then launch `01_SPUSTIT_V24917_RESUME_B0002_CYCLE2_FRESH_EPOCH_SILENT.py` for the real cycle-2 continuation. The full run enumerates a fresh epoch again; the smoke's temporary cache is not imported, by design.
5. Both launchers verify original file bytes, seven semantic hashes, source RUN_STATUS, BOTH accepted cycle-1 steps, clean non-entered cycle 2 and fixed Generation reference. The V24916 semantic preflight may defer only its matrix hash, and the V24917 post-native baseline must prove all seven fields exactly. The new run is a DIRECT sibling RUN_* under the project `R1_15A2_V16_RUNS`, never nested beneath the old CHECKPOINTS folder.
6. Each launcher enumerates one NEW native path epoch under the new run and immediately calls the same live-DSEG incidence validator as `VisumAdapter.generation_design`. No stored OD share is invented. If `NATIVE_CS_NOT:616:676` is still unsupported after **fresh** export, this early smoke fails before the first Generation trial.
7. After a successful smoke, the separate full launcher continues at **cycle 2 Generation** and then TD; previous accepted cycle-1 changes are inherited. The 12-group TD proposal round-robin from PR #1 is retained to sample SCHOOL and LONG in the limited EXPLORE stage.

## Evidence to look at before leaving unattended

```
NEW_RUN\CALIBRATION\B0002_PATH_EPOCH_SMOKE_RESULT.json (smoke run only)
NEW_RUN\CALIBRATION\RESUME_EVIDENCE\B0002_POST_BASELINE_AUTHORITY.json
NEW_RUN\CALIBRATION\RESUME_EVIDENCE\B0002_INITIAL_EPOCH\B0002_NATIVE_EPOCH_AUTHORITY.json
NEW_RUN\CALIBRATION\RESUME_EVIDENCE\B0002_INITIAL_PATH_SUPPORT_SMOKE.json
NEW_RUN\CALIBRATION\RESUME_EVIDENCE\B0002_INITIAL_EPOCH\PATH_EPOCH.json
NEW_RUN\CALIBRATION\DEMAND_CYCLE_02_TD_FINECDF\FINECDF_INNER\...
NEW_RUN\CALIBRATION\RUN_STATUS.json
```

**Stop / don't use the working model** if source provenance, the seven hashes, support smoke, native assignment or rollback fail. Source B0002 remains the restart authority. A native route exporter failure is NOT solved by restoring the old A0001 SQLite or by inventing fractions.

## Explicit release limitations

- The `.ver` file is about 535 MB and was not uploaded; the new launcher **will** check the full raw SHA and local `.ver.semantic.json` at execution. An offline test is not a proof that those disk files still exist.
- PR #1's round-robin change **guarantees fair opportunity to probe enabled components**, not that SCHOOL or LONG necessarily improve enough for acceptance. Review `polled_components`, `unpolled_components`, native TD per-component result, and outer acceptance separately. No changes to the 60% counts / 40% survey blend, parameter bounds, IPF, native OD writes, rollback, LONG masking or SCHOOL fixed Generation.
- The first fresh native path enumeration will be time-consuming. A separate smoke and full run each require their own new export; this is intentionally paid twice to avoid a long full run that fails on stale support. Subsequent epochs remain controlled by existing path basis/support and plateau logic.
- The DIAGFAST tolerance experiment and separate SupplyMix policy patch are **not automatically incorporated into this B0002 recovery branch** unless explicitly merged and reverified; do not mix package files from independent branches.

## Offline verification

`python -m pytest -q -p no:cacheprovider tests/test_v24917_resume_b0002_cycle2.py`

The GitHub Actions workflow additionally runs the complete V24917 suite, PR #1 fairness tests and other native-control mocks. This is NOT a substitute for a one-epoch live Visum smoke.
