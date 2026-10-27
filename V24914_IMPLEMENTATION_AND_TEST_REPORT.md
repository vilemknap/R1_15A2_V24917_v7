# V24914 Implementation and Test Report

## Scope

Target release:

```text
R1_15A2_V2_4_9_14_DEMAND_CONTINUATION_SUPPLY_READY_20261019
```

Parent release:

```text
R1_15A2_V2_4_9_13_SUPPLY_ROUTE_CHOICE_READINESS_20261019
```

Live source state:

```text
V24912 A0009
accepted_count = 9
source cycles = 1..5
next cycle = 6
```

## Root cause fixed

V24912 FULL_VERIFY used:

```text
allow_progress_continue = false
```

A FineCDF result with `MAX_ITERATIONS`, `search_complete=false`, but an accepted realized state therefore terminated the entire coupled demand controller. The inner optimization budget had been confused with the outer coupled-demand horizon.

## Implementation

### Exact semantic continuation

`r1_15a2_demand_continuation_v24914.py`:

- pins V24912 terminal status and A0009 semantic state;
- validates all seven semantic restart hashes;
- explicitly does not use whole-file `.ver` SHA as cross-run acceptance authority;
- optionally cross-checks source `RUN_STATUS.json` and `LATEST_ACCEPTED_CHECKPOINT.json`;
- produces a runtime continuation descriptor only after exact semantic validation.

### State-machine correction

`r1_15a2_overnight_controller_v242.py`:

- initializes accepted count at 9;
- starts outer loop at cycle 6;
- preserves cycle horizon 12;
- treats only `MAX_ITERATIONS`, `TD_EVALUATION_BUDGET`, and `TD_INNER_TIME_BUDGET` as bounded inner boundaries;
- continues outer search with supply locked;
- grants no stationarity credit for incomplete inner search;
- retains legacy behavior when no V24914 continuation descriptor is present;
- keeps global stops and technical failures terminal;
- keeps supply unlock criterion unchanged.

### Supply inheritance

V24913 route-choice configuration and code are hash-compared and preserved unchanged. V24914 therefore retains the 5-second ADDVAL lattice and branch-local 80/40/20/10/5-second ladder.

## Tests

Focused continuation tests cover:

1. static A0009 authority;
2. exact live semantic match;
3. semantic mismatch fail-closed;
4. bounded reason whitelist;
5. cycle-6 start and accepted-count-9 inheritance;
6. accepted changed bounded-budget continuation;
7. no-change bounded-budget continuation without stationarity;
8. two complete unchanged cycles before supply;
9. global budget remains terminal;
10. inherited non-continuation behavior remains unchanged;
11. config/runtime manifest and V24913 supply-policy integrity.

Regression result:

```text
focused continuation: 8 passed
focused inherited + continuation: 70 passed, 3 skipped
full suite: 774 passed, 3 skipped
compileall: PASS
```

## Truth boundary

```text
implementation_complete = true
offline_tested = true
real_visum_tested = false
production_ready = false
```
