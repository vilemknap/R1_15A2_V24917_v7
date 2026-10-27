# V24916 PROFILE488FIX1 — implementation and test report

## Live failure reconstructed

The 2026-10-23 live FASTCAL1 run reached the calibration controller and failed in BASELINE_DIAGNOSTICS before outer cycle 1. The active 12D helper returned the intended current authority: 488 rows, all 488 CALIBRATION and 0 VALIDATION. The inherited PERF2 effective config still required the historical 498/462/36 authority tuple, so `r1_15a2_runtime_v1.run_12d()` raised `12D authority row gate failed`.

A second latent mismatch existed in `r1_15a2_runtime_v1.assess_11d_idp_gate()`, where the historical 498/462/36 tuple was hard-coded. Fixing only the config would therefore have moved the failure into the subsequent 11D-to-12D cross-gate.

## Fix

`PROFILE488FIX1` is additive. The sealed parent runtime source remains byte-identical.

1. New `r1_15a2_profile488_gatefix_v24916p2c.py` overlays the active config with:
   - expected_12d_rows = 488
   - expected_calibration_rows = 488
   - expected_validation_rows = 0
2. The same module installs a runtime wrapper over `r1_15a2_runtime_v1.assess_11d_idp_gate` before `parent.main("FULL")`.
3. The wrapper independently validates the real 488/488/0 `d12.row_gate`, then delegates all remaining sealed parent 11D checks unchanged. A mismatch remains fail-closed.
4. No 12D/11D metric formula, FlowBundle targeting, dynamic skim method, assignment method, TG/TD step policy, native IPF tolerance, or acceptance guard is relaxed.

## Verification

- effective runtime gate: 488 / 488 / 0
- focused regression: 79 passed
- full regression: 1015 passed, 4 skipped
- compileall: PASS
- runtime manifest: 48/48 PASS
- explicit wrong-gate test (487/487/0): FAIL-CLOSED as required
