# V24916 FRESH0 — BOOTSTRAPFIX1

## Live symptom

The first real Visum launch stopped immediately with:

`ValueError: not enough values to unpack (expected 5, got 4)`

and the user did not see a `RUNS` directory in the unpacked package folder.

## Root-cause audit

Two bootstrap weaknesses were confirmed in the delivered source:

1. The launcher activated IOFIX3 and telemetry **before** allocating the isolated `R1_15A2_V16_RUNS` root. A failure in that interval could therefore leave no run-root evidence.
2. The live bootstrap/preflight call graph reaches `r1_15a2_com_compat.com_call_with_retry`, whose current implementation consumes a five-item retry budget. Historical R1_15A2 retry providers used four items (before `max_elapsed_seconds`). The observed exception signature is exactly the Python failure produced by a 5-target unpack of a 4-item value. The old launcher did not persist a traceback early enough to prove the exact live line, so this identification is recorded as the strongest call-graph diagnosis rather than fabricated certainty.

## Fix

The fix is additive and V24916-local:

- `R1_15A2_V16_RUNS` is allocated immediately after binding the currently opened `.ver`, before IOFIX3/telemetry activation.
- `LATEST_BOOTSTRAP.json` exists before risky runtime activation.
- a launcher-only 4→5 COM retry-budget compatibility overlay maps the historical four-item contract to `(attempts, delay, factor, maximum, None)`; the sealed parent `r1_15a2_com_compat.py` is not modified.
- all stale `r1_15a2_*` and `R1_15A2_*` project modules are purged before importing the release, reducing mixed-runtime contract risk in a reused Visum Python host.
- every bootstrap failure records the exact stage, exception and full traceback in `R1_15A2_V16_RUNS/BOOTSTRAP_FAILED.json` and `LATEST_BOOTSTRAP.json`.
- the unpacked package also receives `V24916_LAST_RUNS_LOCATION.txt` and, on failure, `V24916_LAST_BOOTSTRAP_FAILURE.json`, so the runtime folder is discoverable even when it lives beside the opened `.ver` rather than inside the package directory.
- console output now prints the exact `RUNS root:` path before live preflight starts.

No candidate mathematics, assignment, 12D/11D acceptance, FlowBundle targeting, TD mask, coefficients, tolerances or path-cache policy were changed.

## Protected parent integrity

`r1_15a2_com_compat.py` and the duplicated legacy inline COM preflight remain byte-identical to the uploaded package. V24915 PERF2 deployment preflight and PERF2C overlay preflight both remain PASS.

## Tests

- BOOTSTRAPFIX1/fresh0 focused: **25 passed**
- full package regression: **1000 passed, 4 skipped, 0 failed**
- compileall: **PASS**
- V24916 runtime manifest: **PASS**
- V24915 PERF2 deployment: **PASS**
- PERF2C overlay: **PASS**

A dedicated test reproduces the live contract mismatch by forcing a four-item retry budget during `main()` and verifies that bootstrap continues through live-preflight handoff.

## Live boundary

This corrected package has not yet been rerun inside the user's real Visum instance. Therefore:

- `real_visum_tested = false`
- `production_ready = false`
- next gate = one real fresh0 bootstrap/preflight launch from the same opened `.ver`.

If any further live-only failure occurs, the new package must leave a full traceback in the two failure artifacts above; no more anonymous bootstrap failure is acceptable.
