# V24915 PERF2C R2 — Supply TEMP SQLite hotfix

## Live failure forensic

The supplied live run reached coupled-demand convergence and then failed at the first Supply design attempt.

Observed terminal path:

- Demand converged at lineage cycle 15.
- accepted_count = 18.
- stationary_cycle_streak = 2.
- Supply started.
- Supply accepted_count remained 0; failure happened before candidate design.
- Exception: `sqlite3.OperationalError: attempt to write a readonly database`.
- Stack: `TwoModeRouteCollector.impact()` -> `CREATE TEMP TABLE current_impact`.

The live artifacts identify the executed release as the parent PERF2 release, not PERF2C R1. Therefore PERF2C single-pass snapshot has not yet been live-validated by this run.

## Root cause

Persistent V248 path cache is reopened through SQLite URI `mode=ro` (correct main-database immutability), and parent V238 additionally executes `PRAGMA query_only=ON`. `query_only` also blocks writes to SQLite TEMP schema. Supply design deliberately creates only a connection-local TEMP table for impact joins, so the additional query-only guard prevented a legitimate scratch-table operation.

A focused reopened-cache test then exposed a second latent persistence-reopen defect that would have appeared immediately after the TEMP fix: V238 `open_existing()` reconstructs the parent collector but omits subclass fields `cal_indices` and `protected`, although fresh `TwoModeRouteCollector.__init__()` initializes them. R2 reconstructs both with the exact parent formulas.

## R2 implementation

R2 is additive; parent V238 source and all 101 parent runtime files remain byte-identical and pass the original manifest.

New overlay `r1_15a2_supply_temp_sqlite_hotfix_v24915p2c2.py` wraps only `TwoModeRouteCollector.open_existing()` after the parent validation has completed:

1. the existing connection remains opened with URI `mode=ro`;
2. `PRAGMA query_only` is switched OFF only on that already-read-only connection;
3. TEMP storage is forced to MEMORY;
4. a connection-local TEMP write/read/drop probe must pass;
5. `cal_indices` and `protected` are reconstructed exactly from the reopened profile authority;
6. persistent main database remains physically non-writable.

No Supply candidate math, route geometry, path-cache contents, assignment, acceptance, demand state, or rollback logic was changed.

## B0018 direct Supply resume

A dedicated launcher was added:

`R1_15A2_SUPPLY_ONLY_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_R2.py`

It invokes the pre-existing verified Supply-only handoff. When started from the accepted B0018 checkpoint, the existing handoff searches the checkpoint ancestry for `DEMAND_CONVERGED.json` and verifies that the live opened snapshot `state_hash` exactly equals the converged Demand authority before any Supply trial write is permitted. Demand is not replayed.

## Tests

- Focused PERF2C/Persistent-cache/R2 tests: 37 passed.
- Full regression: 887 passed, 4 skipped, 0 failed.
- Parent runtime manifest: 101/101 exact, no changed parent runtime file.
- PERF2C R2 overlay manifest: 6/6 PASS.
- Combined deployment preflight: 107 files PASS.
- FULL config/runtime preflight: PASS.
- SUPPLY_ONLY config/runtime preflight: PASS.
- compileall: PASS.
- Real reopened persistent-cache Supply `impact()` test: PASS, including real `TEMP current_impact` join path.
- Main-database write attempt on reopened `mode=ro` connection: rejected as expected.

## Methodology status

- calibration_math_changed = false
- assignment_method_changed = false
- acceptance_changed = false
- demand_convergence_rule_changed = false
- supply_math_changed = false
- path_cache_content_changed = false
- persistent_main_database_writable = false
- real_visum_tested = false for PERF2C R2
- production_ready = false
- calibration_complete = false
