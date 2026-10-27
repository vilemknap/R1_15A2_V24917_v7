# V24915 PERF2 R5 - OVERNIGHT50 implementation and test report

Package revision: `V24915_PERF2_R5_OVERNIGHT50_B0016_CONTINUATION`

## Purpose

Extend the safe coupled-demand continuation budget for an overnight run without relaxing calibration acceptance.

## Reviewed changes

- Coupled-demand outer-cycle cap: **12 -> 50**.
- `calibration_phases[COUPLED_DEMAND].max_cycles`: **12 -> 50**.
- Mature Generation `DISTRIBUTION_FOCUS` schedule coverage: **through cycle 12 -> 50**, with identical step bounds.
- FineCDF `FULL_VERIFY` schedule coverage: **through cycle 12 -> 50**, with identical `35 iterations / 180 evaluations / 14400 s` inner budget.
- Global overnight wall-clock lease: **36000 s -> 64800 s (18 h)**.
- B0016 continuation remains `cycle 11 -> TD_FINECDF_V17`, with accepted Generation not replayed.

## Explicit non-changes

- Early-exploration acceptance remains active only through cycle 12.
- Cycles 13-50 use the already-existing post-cycle-12 fallback; no thresholds were relaxed.
- Minimum stationarity remains 2 complete unchanged coupled-demand cycles.
- Supply unlock rule is unchanged.
- Supply cap remains 100 cycles.
- Assignment method and gap are unchanged.
- GEH / IDP / guard policy is unchanged.
- CandidateReadbackBundle semantics are unchanged.
- Sealed 11D IDP authority is unchanged.

## Continuation design

Historical A0009/B0016 restart authorities remain byte-identical. New module `r1_15a2_demand_continuation_v24915r5.py` first resolves the original authority exactly, then overlays only the runtime cycle budget `12 -> 50`. The source cap is retained as `source_max_lineage_outer_cycle=12` for provenance.

## Tests

- R5 focused overnight-budget tests: **5 passed, 0 failed**.
- PERF2 focused/regression subset: **63 passed, 0 failed**.
- Full repository regression: **856 passed, 4 skipped, 0 failed**.
- `compileall`: **PASS**.
- Runtime bundle preflight: **101 files checked, PASS**.

## Runtime boundaries

`real_visum_tested = false`

`production_ready = false`

The next correctness gate is the live Visum overnight continuation from `ACCEPTED_B_0016_d1211a44ac4d.ver`.
