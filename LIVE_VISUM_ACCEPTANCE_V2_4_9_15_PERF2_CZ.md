# Live PTV Visum acceptance — V24915 PERF2 CandidateReadbackBundle

## Starting authority

Use the same immutable source checkpoint for both branches:

`ACCEPTED_A_0009_cebb9c7a9349.ver`

- accepted count: 9;
- next outer cycle: 6;
- PERF1 and PERF2 must start from byte-identical or semantically identical approved authority;
- do not overwrite the source `.ver`.

## A/B procedure

1. Run PERF1 as control and record its candidate sequence, effective write signatures, assignment gaps, 12D/11D hashes, ledger decisions, rollback results and final accepted state.
2. Restart from the same A0009 authority.
3. Run PERF2 with `shadow_parity_mode=true` and legacy fallback enabled.
4. Record bundle capture/hit/miss/invalidation/fallback telemetry and all COM read counters.
5. Compare both runs before any production declaration.

## Mandatory exact gates

- candidate order: exact;
- effective write signatures: exact;
- assignment count: not higher;
- 12D payload hash: exact;
- 11D payload hash: exact;
- signals hash: exact;
- accept/reject decision: exact;
- rollback result: exact;
- accepted sequence: exact;
- final accepted `state_hash`: exact;
- no new COM write introduced by PERF2;
- stale bundle reuse count: zero.

## Timing to record

- total candidate wall time;
- assignment wall time;
- Procedure Sequence wall time;
- legacy snapshot/readback wall time;
- `Matrix.GetValues` count and time;
- bulk link-read count and time;
- generation/TD/operation inventory reads;
- 12D/11D time;
- rollback time;
- COM retry count.

## Failure policy

Any hash, decision, epoch, diagnostics or acceptance mismatch is `BUNDLE_PARITY_FAIL`. Disable reuse for that state, preserve the legacy path, store both payloads and the structural diff, and do not mark the release production-ready.

## Current boundary

`real_visum_tested = false`

`calibration_complete = false`

`production_ready = false`
