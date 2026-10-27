# V24915 PERF2C R3 — B0018 Demand extension 16–25

## Scope

R3 je uzce ohranicena continuation vetev nad PERF2C R2. Neopakuje Demand od B0016 a nespousti Supply. Vychozim stavem je presne semantic B0018 `ACCEPTED_B_0018_3d57d34487ba.ver` z runu `RUN_20261020_004141_848876`.

## Reviewed delta

- `next_outer_cycle = 16`
- `max_lineage_outer_cycle = 25`
- 10 outer cycles: 16..25
- inherited stationary streak: 2 -> runtime reset 0
- Supply lock: ano, po celou extension
- Generation backtracking scales: `[1.0, 0.5, 0.25]` -> `[1.0, 0.5, 0.25, 0.125, 0.0625]`
- Generation max trials: 3 -> 5

Generation direction/math, GEH/IDP acceptance, guards, TD math, TD realization scales, assignment, rollback, path cache a PERF2C snapshot semantics se nemeni.

Supply lock je realizovan fail-closed: `min_stationary_cycles=11`, zatimco exact continuation muze vykonat maximalne 10 cyklu (16..25) a inherited streak je vynulovan. Proto existujici coupled controller nemuze behem extension Supply odemknout. Wrapper navic explicitne failne, pokud by `supply_started=True` presto nastalo.

## B0018 authority

Semantic state hash:
`cef9b4247114a01e54d45b885f3321a0a22387fe67fc7c1dfdd44f9d1134590e`

Snapshot diagnostic state hash:
`7c5c4ff0b08932cdfde6bd1362f5d32b224cf5ef2ca02938fcfa480789680b9a`

Accepted count at resume: 18.

Raw `.ver` SHA je pouze provenance; restart acceptance je semantic. Presny filename B0018 je ale povinny.

## Tests

- R3 focused: 6 passed
- R3 + R2/PERF2C/R5/continuation/release focused: 42 passed, 1 skipped
- full regression: 893 passed, 4 skipped, 0 failed
- compileall: PASS
- combined deployment preflight: PASS, 111 files checked
- combined runtime preflight: PASS
- exact extension config delta gate: PASS

`real_visum_tested = false` pro tuto R3 extension. Live B0018 evidence pochazi z predchoziho runu, ale samotne cykly 16..25 jeste nebyly spusteny.
