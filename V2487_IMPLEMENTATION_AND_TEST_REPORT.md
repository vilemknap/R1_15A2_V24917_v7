# V2.4.8.7 — Implementation and test report

## Problem

V2.4.8.6 still interpreted historical configuration values as absolute bounds:

- `ADD_* <= 3`;
- `ADD_SALARY <= 3`;
- `ZAHR_* <= 10`.

This was incorrect. These zonal attributes are calibration coefficients. The current live Visum value is the numerical authority; a coefficient already above a historical value must remain valid and may move further by an allowed relative step.

## Implemented contract

### Multiplicative zonal coefficients

```text
proposed = current_live_value * exp(requested_log_step)
```

No global absolute upper bound is applied. Safety is provided by:

- stage-specific `max_add_log_up` / `max_add_log_down`;
- backtracking scales;
- finite-value checks;
- nonnegative multiplicative domain;
- preserved-zero policy;
- active-zone and active-formula eligibility;
- fresh Visum assignment and live diagnostics.

### Salary coefficient

```text
proposed = current_live_value + bounded_delta
```

The old 0–3 clamp is disabled. The retained constraints are:

- `max_abs_delta_per_block`;
- finite-value checks;
- formula-domain `factor_floor`;
- joint salary/`ADD_ATT_W` effect reconstruction.

### Quality gates

No acceptance tolerances were widened. The following remain unchanged:

- generation effect log error;
- family P/A relative gap;
- solver and projection convergence;
- GEH/protected profile limits;
- IDP degradation limits;
- candidate rollback and reproduction;
- fresh assignment plus live 12D/11D acceptance.

## Files changed

The runtime change is limited primarily to:

- `r1_15a2_multiblock.py`;
- `r1_15a2_runtime_v1.py`;
- new V2487 config, safety validator, launcher and verifier;
- V2487 regression tests and documentation.

Path enumeration, path SQLite, FineCDF, assignment authority, ADDVAL1 supply and observation authority are unchanged.

## Source spreadsheet audit

`ZONE-2026-10-16-21-09-22.xlsx` was read with 681 zone rows. Its values are treated as a snapshot, not as bounds. Detailed statistics and source SHA-256 are recorded in:

- `V2487_ZONE_COEFFICIENT_AUTHORITY_AUDIT.json`;
- `V2487_ZONE_COEFFICIENT_AUTHORITY_AUDIT.csv`.

The supplied snapshot currently contains maxima 10 for `ZAHR_PROD_*` and 8 for `ZAHR_ATR_*`. This does not contradict the correction: a live model may already contain larger values, and the code no longer derives bounds from snapshot maxima or historical config constants.

## Real-failure replay

The actual V2484 Generation design evidence was reconstructed into 1,374 proposal rows and replayed with V2487 logic and the supplied zone snapshot.

Results:

```text
candidate rows:                  1712
skipped rows:                    0
legacy-bound clipped rows:       0
ZAHR_PROD_WORK zone 619:          10 -> 10.789216458...
ZAHR_PROD_SERV zone 619:          10 -> 10.393926399...
WORK P/A relative gap:           1.01e-15
SERVICE P/A relative gap:        8.17e-13
maximum effect log error:        1.11e-16
```

This is proposal-layer replay only. Real Visum recomputation remains required.

## Tests

```text
focused V2487 + inherited V2486 tests: 20 passed
full suite:                            615 passed
compileall:                            PASS
```

The V2487 tests cover:

- `ZAHR_*` already above 10 and increasing further;
- domestic `ADD_*` already above 3 and increasing further;
- `ADD_SALARY` already above 3 without clamping;
- preserved-zero behavior;
- old configuration reproducing legacy clamp;
- stable project root;
- V2486 persistent-cache predecessor compatibility;
- launcher initialization under nested accepted checkpoints.

## Verification boundary

Offline implementation and regression testing are complete. A real Windows PTV Visum V2.4.8.7 run has not yet been completed. `production_ready=false` until the live gate passes.
