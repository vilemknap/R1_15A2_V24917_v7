# Živý acceptance checklist V2.4.8.6

## 1. Zdrojový stav

Otevřít poslední bezpečný accepted checkpoint. Zdrojový `.ver` se nesmí změnit; kalibrátor musí nejprve uložit vlastní `WORKING_START.ver`.

## 2. Umístění runu

Nový adresář musí vzniknout přímo pod:

```text
C:\Users\vilem_knap\Documents\VISUM\v45\2022\R1_15A2_V2486_RUNS\RUN_...
```

V `RUN_ROOT_AUTHORITY.json` ověřit:

- `project_base = ...\VISUM\v45\2022`;
- `project_base_mode = OUTERMOST_PRIOR_RUN_TREE_NORMALIZED` při startu ze starého checkpointu;
- `postcondition_new_run_outside_all_detected_prior_run_roots = true`.

## 3. Path cache

`PERSISTENT_PATH_CACHE_RESTORE.json` musí uvést autorizovaný restore. Nesmí se provést nová počáteční enumerace, pokud exact-state cache projde. Fresh enumeration je přípustná jen podle existujících support/plateau pravidel.

## 4. Generation design

V `GENERATION_DESIGN.json` ověřit:

- `summary.bound_constrained_projection.enabled = true`;
- `clipped_count >= 2` pro známý stav se saturovanými `ZAHR_PROD_WORK` a `ZAHR_PROD_SERV` v zóně 619;
- `role_rebalance.WORK.status = BALANCED_BY_ROLE_ATTENUATION`;
- `role_rebalance.SERVICE.status = BALANCED_BY_ROLE_ATTENUATION`;
- žádný candidate row nesmí navrhovat hodnotu vyšší než hard bound 10;
- `unresolved_families` musí být prázdné, jinak má gate zůstat fail-closed.

## 5. První trial

Musí vzniknout `DEMAND_CYCLE_01_GENERATION\TRY_01`. Fresh Visum výpočet a 12D/11D rozhodnou o přijetí nebo odmítnutí. Samotný proposal replay není acceptance.

## 6. Rollback

Při odmítnutí musí `ROLLBACK_SUMMARY.json` obsahovat:

```text
snapshot_equal = true
diagnostic_equal = true
passes = true
load_version_called = false
direct_od_matrix_writes = false
```

## 7. Další gate

Po úspěšném Generation kroku musí běh pokračovat do FineCDF TD. Supply se nesmí spustit před dvěma úplnými stacionárními demand cykly.
