# Live Visum acceptance — V2.4.8.7

## Gate A — run root

Nový run musí být:

```text
...\VISUM\v45\2022\R1_15A2_V2487_RUNS\RUN_...
```

`RUN_ROOT_AUTHORITY.json` musí mít `postcondition_new_run_outside_all_detected_prior_run_roots=true`.

## Gate B — cache

`PERSISTENT_PATH_CACHE_RESTORE.json` musí buď potvrdit autorizovaný restore, nebo transparentně zdokumentovat fresh enumeration. Cache V2486 je explicitně povolený read-only predecessor.

## Gate C — živá autorita koeficientů

V `GENERATION_DESIGN.json`:

```text
summary.generation_coefficient_authority.mode = LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP
summary.generation_coefficient_authority.current_live_values_are_authority = true
summary.generation_coefficient_authority.legacy_absolute_upper_bounds_enforced = false
```

Pro každý násobný coefficient candidate:

```text
proposed / current = exp(requested_attr_log_effect)
```

v rámci numerické tolerance. Hodnota nad 3 nebo 10 není sama o sobě chyba.

## Gate D — V2484 failure shape

U zóny 619 nesmí vzniknout `CLAMPED_TO_NO_IMPLEMENTED_EFFECT` pouze proto, že počáteční hodnota je 10. Očekává se návrh nad 10, pokud guidance žádá kladný krok.

## Gate E — skutečný trial

Musí vzniknout `DEMAND_CYCLE_01_GENERATION/TRY_01` a proběhnout:

```text
candidate write
-> native TG/TD/assignment podle bloku
-> live 12D/11D
-> acceptance nebo ověřený rollback
```

## Gate F — ochrany

Musí zůstat aktivní:

- finite/nonnegative multiplicative domain;
- preserved-zero politika;
- salary formula factor floor;
- effect log error;
- P/A relative gap;
- solver/projection convergence;
- GEH/protected/IDP gates;
- source .ver immutable;
- rollback verification.

## PASS hranice

V2.4.8.7 lze označit za live-accepted až po skutečném průchodu alespoň prvním Generation trialem a ověřeném acceptance/rollback výsledku. Offline testy samy nestačí.
