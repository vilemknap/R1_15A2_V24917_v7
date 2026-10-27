# V24916 DYNAMICSKIM1 FASTCAL1 — implementation and test report

## Result

FASTCAL1 is an auditable runtime child overlay on top of the existing V24916 DYNAMICSKIM1 release.
It intentionally changes calibration search aggressiveness / materiality only. The parent files and sealed
scientific authorities are not rewritten on disk.

The goal is to move Generation substantially faster and prevent later calibration from stalling on overly
large materiality thresholds, while retaining the existing fail-closed network, protected-profile, severity,
IPF, dynamic-skim and assignment guards.

## Effective parameter changes

| Parameter | Parent DYNAMICSKIM1 | FASTCAL1 |
|---|---:|---:|
| TG common family log cap — initial | 3% | 10% |
| TG common family log cap — middle | 1.5% | 6% |
| TG common family log cap — late | 0.5% | 3% |
| TG per-zone coefficient log cap — initial/middle/late | 6% / 4% / 2% | 10% / 6% / 3% |
| TG max zonal OD change — initial/middle/late | 8% / 6% / 4% | 20% / 14% / 8% |
| TG tested backtracking scales | 3: `1, .5, .25` | 6: `1, .5, .25, .125, .0625, .03125` |
| TG maximum trials | 3 | 6 |
| CAL GEH minimum relative improvement after early-exploration horizon | 0.1% | 0.001% |
| TD normal selected-objective minimum relative improvement | 0.5% | 0.05% |
| TD realization backtracking attempts | 5 | 7 |
| TD realization scales | `1 ... .0625` | `1 ... .015625` |

The middle zonal OD cap was not explicitly specified by the user beyond the requested new 8–20% range.
FASTCAL1 uses 14%, the monotone midpoint between 20% and 8%, yielding a clear 20% / 14% / 8% stage taper.

## Important implementation detail — why max_add_log also changed

The signed Generation algorithm constructs a family-global log movement plus a centered zonal pattern,
but every final zone coefficient movement is bounded by `max_add_log_up/down`. Therefore simply changing
the family-global caps to 10% / 6% / 3% while retaining the old 6% / 4% / 2% per-zone log caps would clip
the requested aggressive TG move and make the headline setting partly ineffective.

FASTCAL1 consequently aligns the per-zone coefficient log caps with the requested family-global values:
10% / 6% / 3%. The existing absolute coefficient envelopes remain unchanged.

## GEH materiality semantics

`min_cal_objective_relative_improvement` is changed from `0.001` to `0.00001`.
That is 0.1% -> 0.001%.

The existing early-exploration acceptance policy remains unchanged through outer cycle 12. During that
horizon Generation still uses its existing any-positive / Pareto-severity policy. FASTCAL1's 0.001% wall is
the fallback CAL materiality after that early-exploration horizon.

The separate `performance.first_sufficient.generation_min_relative_improvement` remains unchanged at
0.1%. It is only an early-stop policy for the TG candidate list, not the hard post-exploration acceptance wall.
Thus the six TG step sizes are available when larger candidates fail, without forcing all six expensive live
assignments when a sufficiently good early candidate already passes.

## TD tolerance semantics

The normal selected TD objective threshold is changed from 0.5% to 0.05% in both effective fields:

- `td.min_selected_component_relative_improvement = 0.0005`
- `td_soft_reference_policy.aggregate_selected_min_relative_improvement = 0.0005`

The existing early-exploration TD policy through cycle 12 is intentionally unchanged; its separate 0.25%
threshold remains in force during that phase. Native IPF convergence tolerance is also unchanged.

## TD realization backtracking

The realization sequence is extended geometrically from five to seven attempts:

`1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125, 0.015625`

The coordinate system remains the existing `B_LINEAR_LOG_NEG_C`. This does not relax native TD/IPF
convergence. It only gives a FineCDF target two additional smaller downstream realization attempts before
the accepted parent is declared a bounded plateau.

## Unchanged hard/scientific contracts

- V24916 DYNAMICSKIM1 fresh assignment + six native `DIS` skims per FineCDF evaluation
- assignment method and assignment gap
- VDF / impedance definitions
- P/A authority and Generation formulas
- dynamic skim family construction
- FineCDF target mathematics / CDF / mean-distance definitions
- native IPF tolerance
- early-exploration acceptance policy through cycle 12
- protected-profile guards
- severity transition guards
- IDP degradation guards
- absolute Generation coefficient envelopes
- no direct OD matrix writes
- persistent cross-run path cache remains disabled

## Changed runtime files

- `00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py`
- `r1_15a2_fastcal_runtime_v24916p2c.py` (new)
- `V24916_PERF2C_RUNTIME_MANIFEST.json`
- `tests/test_v24916_fastcal1_policy.py` (new)

Additional audit artifacts:

- `V24916_FASTCAL1_MACHINE_STATUS.json`
- `V24916_FASTCAL1_SOURCE_PATCH.diff`
- this report

## Verification

Focused FASTCAL1 + dynamic/bootstrap tests:

`29 passed, 0 failed`

Full suite:

`1011 passed, 4 skipped, 0 failed`

Compileall:

`PASS`

Runtime manifest:

`47 / 47 PASS`

## Live status

Offline implementation: **PASS**.

Production/live numerical behavior still requires the normal Visum canary because the changes intentionally
make TG materially more aggressive and TD acceptance more tolerant. All existing rollback and hard guards
remain active for that live run.
