# R1 15A2 V2.4.9.14 — pokračování demandu a připravená supply fáze

## Účel release

V2.4.9.14 opravuje jedinou systémovou chybu, která ukončila úspěšný V24912 běh po cycle 5:

```text
DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED:MAX_ITERATIONS
```

Cycle 5 přitom dokončila Generation i TD, přijala oba změněné stavy a vytvořila ověřený accepted checkpoint A0009. Vyčerpání jednoho bounded FineCDF inner budgetu proto nemá ukončit celý coupled-demand outer loop.

V24914 pokračuje výhradně z přesné sémantické autority:

```text
ACCEPTED_A_0009_8f7cac7a950a.ver
accepted_count = 9
next lineage outer cycle = 6
maximum lineage outer cycle = 12
```

Raw SHA celého `.ver` není cross-run restart gate. Rozhoduje sedm sémantických hashů modelu.

## Opravená state-machine logika

Následující FineCDF stop reasons jsou bounded inner-budget boundary:

```text
MAX_ITERATIONS
TD_EVALUATION_BUDGET
TD_INNER_TIME_BUDGET
```

Když při takovém boundary vznikl ověřený accepted změněný stav:

```text
PROGRESS_CONTINUE_DEMAND_ACCEPTED_BUDGET
```

Když změna přijata nebyla, ale inner search nebyl kompletní:

```text
BOUNDED_SEARCH_CONTINUE_DEMAND_NO_ACCEPTED_CHANGE
```

Ani jeden stav:

- není stationarity;
- nepřidává stationary-cycle credit;
- neodemkne supply;
- není vydáván za konvergenci.

Globální user stop, celkový runtime limit, COM chyby, rollback failure a technické chyby zůstávají fail-closed.

## Podmínka odemčení supply se nemění

Supply se smí spustit až po:

```text
2 po sobě jdoucích kompletních a úspěšných TG+TD cycles bez accepted změny
```

V24914 zachovává celou supply-route-choice policy V24913:

- LINK ADDVAL1;
- lattice 0,5 ADDVAL = 5 generalized seconds;
- branch-local ladder 80 → 40 → 20 → 10 → 5 s;
- fresh Visum assignment;
- fresh 12D/11D;
- baseline-relative supply acceptance;
- frozen demand hashes během supply;
- rollback/reapply/commit;
- VDF, capacity, V0, turn/connector ADDVAL zůstávají frozen.

## Jak spustit

1. Vypni všechny jiné R1 15A2 kalibrační běhy.
2. Otevři ve fresh Visum session:

```text
C:\Users\vilem_knap\Documents\VISUM\v45\2022\R1_15A2_V24912_RUNS\
RUN_20261019_002326_649324\CALIBRATION\CHECKPOINTS\
ACCEPTED_A_0009_8f7cac7a950a.ver
```

Je přípustné i ručně znovu uložené `.ver`, pokud má přesně stejné sémantické hashe.

3. Rozbal celý V24914 balík do nové čisté složky.
4. Spusť:

```text
R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_14.py
```

5. Před prvním zápisem musí vzniknout:

```text
V24914_DEPLOYMENT_PREFLIGHT.json
V24914_RUNTIME_BUNDLE_PREFLIGHT.json
V24914_DEMAND_CONTINUATION_HANDOFF.json
```

Handoff musí potvrdit:

```text
enabled = true
accepted_count = 9
inherited_outer_cycles = 5
next_outer_cycle = 6
semantic_state_hash = b599fdc7291e4a1d929db9818740e3f7aa7de53616b55238dcfcb2e8c40134a8
```

## Co release netvrdí

```text
real_visum_tested = false
production_ready = false
```

Offline testy dokazují state-machine, restart authority, config/runtime integritu a zachování supply policy. První live V24914 běh je stále povinný gate.
