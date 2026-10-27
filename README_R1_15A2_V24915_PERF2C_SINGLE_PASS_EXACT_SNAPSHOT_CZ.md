# R1_15A2 V24915 PERF2C — Single-Pass Exact Snapshot

Release: `R1_15A2_V2_4_9_15_PERF2C_SINGLE_PASS_EXACT_SNAPSHOT_20261020`

This additive overlay keeps the complete R6/R5 calibration runtime and changes only the internal read plan of a full semantic `snapshot()`. It creates no cross-call cache, no new mutation epoch, no authority token, and no rollback path.

## Optimization

- TD parameter capture and Procedure Sequence inventory share one `Operations.GetAll` traversal.
- DSeg binding capture reads only `CODE` and `ODMatrix.NO`, the only DSeg fields published by the semantic snapshot.
- Matrix `GetValues()` remains exactly once per matrix and uses the unchanged float64 little-endian SHA.
- The first live snapshot computes both parent and PERF2C payloads and requires exact object-level equality. Any mismatch or optimized-read exception permanently disables PERF2C for that adapter and returns the untouched parent snapshot.

## Unchanged

Candidate design, assignment, IPF, 12D/11D, acceptance, rollback, path cache, B0016 continuation and the 50-cycle/18-hour overnight budget are unchanged.

## Launcher

`R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C.py`
