# PROFILE488 A0004 recovery / telemetry fail-open hotfix

## Failure reconstructed

The source run failed during cycle-3 FineCDF TD rollback after Generation had already been accepted. The immediate exception was a Windows `PermissionError` in performance-only telemetry publication:

`PERFORMANCE/SUMMARY.json.tmp -> PERFORMANCE/SUMMARY.json`

The failure was not an acceptance, assignment, TG, TD, or rollback-state failure. The source evidence reports exact TD rollback parity (`passes=true`, `snapshot_equal=true`, `diagnostic_equal=true`).

## Recovery boundary

The authoritative restart point is `ACCEPTED_B_0004_d26d01d6f9a5.ver`.

Recovery semantics:

- accepted_count = 4
- inherited outer cycles = 2
- next outer cycle = 3
- resume substep = `TD_FINECDF_V17`
- cycle-3 Generation completed = true
- cycle-3 Generation changed = true
- cycle-3 TD completed = false
- original Generation fixed-reference authority retained
- max lineage outer cycle = 100

## Telemetry repair

The hash-locked parent `r1_15a2_perf_v246.py` is not modified on disk.

`r1_15a2_perf_telemetry_failopen_hotfix_profile488.py` replaces only the private telemetry `_atomic_json` function at runtime. Publication uses unique temporary files, bounded retry on `OSError`, best-effort fallback snapshots, and never raises a telemetry I/O error into calibration logic.

## Path cache policy

Recovery deliberately keeps the current PROFILE488 fresh-cache policy. No cache from the failed run is trusted across the new run boundary. The resumed run enumerates a new run-isolated path epoch, then may reuse it within that recovery run according to the existing path-epoch policy.

## Validation

- recovery authority hash lock: PASS
- exact semantic resolver contract: PASS
- partial cycle-3 resume skips Generation: PASS
- persistent `SUMMARY.json` PermissionError does not escape: PASS
- transient `SUMMARY.json` lock retries and publishes: PASS
- parent performance telemetry regression: PASS
- compile/import/config preflight: PASS
- full pytest suite: 910 passed, 4 skipped

No live Visum run was executed in this environment.
