# Live Visum acceptance — V2.4.9.14

## 1. Povinný startovní stav

Otevři latest verified V24912 accepted checkpoint:

```text
ACCEPTED_A_0009_8f7cac7a950a.ver
```

Očekávaná sémantická autorita:

```text
accepted_count = 9
semantic_state_hash = b599fdc7291e4a1d929db9818740e3f7aa7de53616b55238dcfcb2e8c40134a8
matrix_hash = 48d452633ed3ae2d760f618c44e5231f46294678b4f8ff847b9c4f2d56ae26e9
generation_hash = 3785673ab68a47d66949975e35b7fc71ee27dc591297c0df657e5e04e2c02520
td_hash = 28b6569f3417ff4eb7c909a9e3a696a50f6dde2f1bfd5a7bbca35b2ebf427e94
```

Nespouštěj V24914 nad B0000, B0002 nebo libovolným jiným modelem.

## 2. Spuštění

Spusť pouze:

```text
R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_14.py
```

Supply-only launcher v této chvíli nepoužívej, protože demand zatím není joint-converged.

## 3. Povinné preflight artefakty

V novém `R1_15A2_V24914_RUNS\RUN_...` ověř:

```text
V24914_DEPLOYMENT_PREFLIGHT.json          passes = true
V24914_RUNTIME_BUNDLE_PREFLIGHT.json      passes = true
V24914_DEMAND_CONTINUATION_HANDOFF.json   enabled = true
```

Handoff musí obsahovat:

```text
accepted_count = 9
next_outer_cycle = 6
max_lineage_outer_cycle = 12
raw_ver_sha_used_for_restart_acceptance = false
```

## 4. První coupled-demand cycle

První nový cycle musí mít číslo 6, nikoli 1.

`RUN_STATUS.json` musí na začátku uvádět přibližně:

```text
lineage_outer_cycle_start = 6
inherited_outer_cycles = 5
accepted_count = 9
supply_started = false
```

První nově uložený accepted checkpoint musí být číslovaný 0010.

## 5. Bounded inner budget

Pokud FineCDF skončí například:

```text
stop_reason = MAX_ITERATIONS
search_complete = false
```

a realizace je přijatá, cycle se musí uzavřít jako:

```text
PROGRESS_CONTINUE_DEMAND_ACCEPTED_BUDGET
```

a pokračovat do dalšího outer cycle.

Pokud se stav nezmění, ale inner search je stále nekompletní:

```text
BOUNDED_SEARCH_CONTINUE_DEMAND_NO_ACCEPTED_CHANGE
```

V obou případech musí platit:

```text
stationary_cycle_streak = 0
supply_started = false
```

## 6. Co musí zůstat terminální

Následující důvody se nesmí převést na continuation:

```text
GLOBAL_USERSTOPREQUESTED
GLOBAL_TIMEBUDGETREACHED
TD_USER_STOP_FILE
COM_ERROR
ROLLBACK_FAILED
```

## 7. Demand convergence a supply

Supply se smí odemknout až po dvou po sobě jdoucích kompletních cycles, kde:

```text
generation_changed = false
td_changed = false
generation search_complete = true
TD search_complete = true
joint_stationary = true
```

Potom musí vzniknout `DEMAND_CONVERGED.json` se stationary streak 2 a teprve následně `SUPPLY_ROUTE_CHOICE_START`.

## 8. Supply policy

Po odemčení supply zkontroluj, že EFFECTIVE_CONFIG stále obsahuje:

```text
lattice = 0.5
max_step = 8.0
max_cumulative = 15.0
absolute range = -100 .. +100
step ladder seconds = 80, 40, 20, 10, 5
max_candidates = 40
max_trials_per SUPPLY_ADDVAL1 = 40
```

## 9. Live PASS podmínka

Release lze označit jako live-tested až když:

- cycle 6 skutečně začne z A0009;
- bounded FineCDF budget neukončí celý outer loop;
- accepted checkpoint numbering naváže od 0010;
- demand convergence nebo další bezpečný continuation boundary proběhne bez rollback/state identity chyby;
- supply se nespustí před joint convergence;
- final verified state odpovídá latest accepted checkpointu.
