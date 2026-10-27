# V24915 PERF2 — CandidateReadbackBundle implementation and test report

## Machine-derived status

`PERF2_OFFLINE_VERIFIED_READY_FOR_LIVE_PARITY_BENCHMARK`

- Release: `R1_15A2_V2_4_9_15_PERF2_CANDIDATE_READBACK_BUNDLE_20261019`
- Exact parent: `R1_15A2_V2_4_9_15_PERF1_EXACT_SAFE_ACCELERATION_20261019`
- Parent CP88 SHA-256: `29af8e1bcd45904b101da9988a4a8406db9bd4c74c2bb6e1b0100f5d777b99fa`
- Restart authority: `ACCEPTED_A_0009_cebb9c7a9349.ver`
- Accepted count: `9`
- Next outer cycle: `6`
- `live_visum_tested = false`
- `calibration_complete = false`
- `production_ready = false`

## Implemented architecture

PERF2 adds an ephemeral, read-only `CandidateReadbackBundle` bound to the exact:

- Visum session token;
- run token;
- accepted-parent `state_hash`;
- calibration block;
- effective candidate-write signature;
- mutation epoch;
- assignment epoch;
- payload hash.

A bundle is published atomically only after the complete legacy semantic snapshot, optional 498-profile passenger-flow signature, epoch rechecks, and canonical payload hash have completed. Any model-changing operation invalidates the current bundle **before** its side effect.

The implementation preserves the legacy `VisumAdapter.snapshot()` payload and all component hashes exactly. Matrix fingerprints still come from the original full `GetValues()` path; PERF2 only reuses the already verified fingerprint inside the same immutable state.

## Invalidation coverage

Explicit invalidation is wired before:

- generation candidate writes;
- TD candidate writes;
- ADDVAL1 candidate writes;
- rollback writes for generation, TD and supply;
- `Procedures.Execute()` / PrT assignment;
- `LoadVersion` restore;
- diagnostics that may create or update CountLocation UDAs;
- candidate context changes and adoption/rollback transitions.

Capture failures never publish a partial bundle. A stale or tampered bundle becomes a miss and falls back to the original live readback path or fails closed according to configuration.

## 12D / 11D boundary

The helper readback dependency audit conservatively keeps all live 12D and 11D reads in place. No diagnostic COM read is replaced in PERF2. After a real helper completes, its output hashes may be attached to the current epoch as an immutable reference, but fresh diagnostics are never skipped after a new assignment.

## Source audit

The forensic call-site audit scanned 11 active source/helper files and identified 84 relevant call sites, including 35 semantic snapshots, 5 link reads, 5 DSeg reads, 4 direct `GetValues` call sites, 10 diagnostics calls, 7 `SetAttValue` mutations, 2 `LoadVersion` paths, and one procedure execution site.

Parent source files modified: `0`.

The implementation is additive and retains the complete PERF1 parent tree.

## Exact parity evidence

Offline parity is exact for:

- `GENERATION`;
- `TD_FINECDF`;
- `SUPPLY_ADDVAL1`;
- `state_hash`;
- `addval_hash`;
- `fixed_link_hash`;
- `matrix_hash`;
- `dseg_hash`;
- `generation_hash`;
- `td_hash`;
- `operations_hash`.

The inherited FineCDF counterfactual replay returns the same candidate order, duplicate elimination, assignment count, plateau decision, diagnostics payload and final accepted-parent `state_hash` for PERF1 and PERF2.

## Synthetic performance evidence

For three unchanged snapshot consumers and two synthetic matrices:

- legacy path: `6` matrix `GetValues()` calls;
- PERF2 path: `2` matrix `GetValues()` calls;
- saved calls: `4`;
- exact semantic and state-hash parity: `PASS`.

The general call-count reduction for `K` consumers is `1 - 1/K`. This is a read-count result, **not a claimed live Visum wall-time speed-up**.

## Tests

- Focused PERF1/PERF2 gate: **61 passed, 0 failed**.
- Complete single-process regression: **844 passed, 4 skipped, 0 failed**.
- New PERF2 tests: **51**.
- `compileall`: **PASS**.
- Runtime manifest: **80 hash-pinned files**.
- Runtime manifest SHA-256: `d2962cbcf312f5101de99045aa3d60b8af29df2cf3726283e7fa261449144e4d`.

## What is not claimed

This run had no live PTV Visum COM instance. Therefore it does not claim:

- a measured wall-time speed-up;
- live A/B parity from A0009;
- calibration completion;
- production readiness.

## Next mandatory gate

Run PERF1 and PERF2 from the same immutable `ACCEPTED_A_0009_cebb9c7a9349.ver`, compare candidate decisions and final hashes exactly, and record COM/readback timing. Any parity mismatch must disable bundle reuse and retain the legacy path.
