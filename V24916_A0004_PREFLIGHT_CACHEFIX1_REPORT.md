# V24916 A0004 PREFLIGHT_CACHEFIX1

## Live failure reproduced

The STEP-1 live preflight failed while constructing `VisumAdapter` with:

`PERSISTENT_PATH_CACHE_ROOT_MISSING`

The preflight ran before a calibration `RUN_*` folder existed. The inherited V2.4.8 `PersistentPathCacheManager` correctly requires `runtime_persistent_path_cache_root` whenever persistent cache is enabled. That root is intentionally assigned only inside the calibration runtime after creation of the new run folder.

## Fix

`r1_15a2_fresh_baseline_live_preflight_v24916p2c.py` now builds a dedicated read-only preflight adapter config. Only for STEP 1 / immediate pre-calibration revalidation it sets `performance.persistent_path_cache.enabled = false`, clears legacy cache roots, and does not invent a cache directory.

STEP 2 is unchanged: persistent path cache stays enabled and the A0004 parent creates its run-isolated cache root after allocating the `RUN_*` folder. The resumed TD still requires a fresh recovery path epoch and cross-run restore remains forbidden.

## Methodological invariants

- A0004 checkpoint/semantic authority unchanged.
- accepted_count=4, outer cycle=3, resume at TD unchanged.
- PROFILE488 12D authority unchanged.
- Generation FlowBundle targeting unchanged.
- TD component mask unchanged.
- fresh Visum assignment + live 12D/11D acceptance unchanged.
- parent source files byte-identical.

## Offline validation

- focused V24916+A0004+IOFIX1+telemetry: 70 passed, 0 failed.
- full regression: 975 passed, 4 skipped, 0 failed.
- compileall: PASS.
- V24916 runtime manifest: PASS.
- parent deployment/runtime preflight: PASS.
- parent SHA audit: PASS.

The live Visum preflight must still be rerun on the target machine.
