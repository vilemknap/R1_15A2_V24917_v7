# V24916 PROFILE488 A0004 active-targeting rebase – implementation and test report

## Parent

Rebase byl proveden na `R1_15A2_V24915_PERF2C_PROFILE488_A0004_CYCLE3_TD_RESUME_IOFIX1_NO_WALLCLOCK_20261022`. Parent runtime byl zachovan byte-identicky; SHA audit: **940 same, 0 changed, 0 missing**.

## Continuation semantics

- source checkpoint: `ACCEPTED_B_0004_d26d01d6f9a5.ver`
- checkpoint SHA-256: `6347623c247819a9a061adcfdd8176c0af1fd6546b866331114ee5e91049c9bc`
- accepted_count: **4**
- resume outer cycle: **3**
- resume substep: **TD_FINECDF_V17**
- cycle-3 Generation is already accepted and is not replayed
- TD is pending
- no wall-clock calibration limit

## V24916 additions

FlowBundle + DIST_KM targeting remains active. Resumed cycle-3 TD uses TD component targeting. Because the recovery parent forbids cross-run path-cache restore, the active adapter creates a fresh accepted-state path epoch before resumed TD when no in-run cache exists. Generation FlowBundle targeting becomes active at the next Generation substep.

Supply FlowBundle targeting, shortest-IMP invalidation and skim-driven acceptance remain disabled. Numerical acceptance authority remains fresh Visum assignment + live PROFILE488 12D + live 11D.

## PROFILE488 gate correction

The uploaded parent correctly binds the current 362 + 126 PROFILE488 authority and helper, but its inherited top-level gate still carries legacy `498 / 462 / 36` expected counts. This rebase does not modify the parent files. The V24916 runtime delta explicitly corrects only these gates to `488 / 488 / 0`, and the delta audit proves all other parent-reviewed config fields unchanged.

## IOFIX1 / telemetry

Parent IOFIX1 and fail-open performance telemetry hotfix are preserved. Critical calibration-state publication remains fail-closed; performance telemetry remains best-effort and must not abort calibration.

## Offline validation

- focused A0004/V24916/IOFIX suite: **69 passed**
- complete pytest regression: **974 passed, 4 skipped, 0 failed**
- `compileall`: **PASS**
- parent PERF2 deployment preflight: **PASS**
- parent PERF2C overlay preflight: **PASS**
- parent A0004 runtime preflight: **PASS**
- V24916 runtime manifest: **PASS**
- active runtime delta audit: **PASS**
- parent SHA audit: **PASS, 0 modified parent files**

## Truth boundary

`real_visum_tested = false`. The final distribution still requires live execution of step 1 and then step 2 on the exact A0004 checkpoint.


PREFLIGHT_CACHEFIX1 (2026-10-22)
- opravena live chyba PERSISTENT_PATH_CACHE_ROOT_MISSING ve STEP 1;
- read-only preflight nyní persistent path cache neinicializuje;
- kalibrační STEP 2 zachovává persistent cache aktivní a root zakládá až po vytvoření RUN_*;
- A0004 continuation, IOFIX1, PROFILE488, FlowBundle Generation targeting a TD mask jsou beze změny.
