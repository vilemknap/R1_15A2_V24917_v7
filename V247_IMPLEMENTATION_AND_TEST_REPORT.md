# R1 15A2 V2.4.7 — implementační a testovací report

## Výchozí základ

- runtime základ: R1 15A2 V2.4.6 / CP05;
- CP03 Windows path-length a rollback-diagnostic hotfixy zachovány;
- V2.4.6 adaptivní TG, progresivní FineCDF v1.8, ADDVAL1 4/2/1, bulk COM čtení a adaptivní paging zachovány;
- produkční autorita stále vyžaduje živý Visum assignment a 12D/11D diagnostiku.

## Implementovaný problém

V2.4.6 po přijatém stavu invalidovala path cache. Následující Generation nebo Supply design proto mohl znovu exportovat miliony path/path-link řádků, i když se změnily jen demand nebo ADDVAL1 parametry a předchozí path báze ještě nabízela další kalibrační kroky.

V2.4.7 zavádí explicitní path epochs:

- počáteční úplná enumerace;
- reuse přes accepted TG, TD a ADDVAL1 stavy;
- live OD reweight na frozen path shares;
- live profile/driver rebind nad stejnou geometrií;
- refresh až po úplném lokálním plateau;
- pokračování při změně path báze;
- stationarity pouze po čerstvé ekvivalentní enumeraci.

## Změněné runtime oblasti

- `r1_15a2_two_mode_v238.py`
  - epochová identita;
  - index-invariant route/volume comparison hash;
  - live OD reweight;
  - detekce nových kladných OD bez supportu;
  - live profile rebind a rebuild sequence evidence.
- `r1_15a2_trial_adapter_v240.py`
  - lifecycle path epoch;
  - retain po accepted state;
  - plateau refresh gate;
  - refresh budget;
  - bezpečná retence pouze aktuálního SQLite store.
- `r1_15a2_overnight_controller_v240.py`
  - Supply refresh pouze po úplném zero-accept cyklu.
- `r1_15a2_overnight_controller_v242.py`
  - demand refresh pouze po úplném TG+TD plateau;
  - refresh s novou bází resetuje stationarity streak.
- `r1_15a2_safety_v247.py`
  - hard-lock všech epochových pravidel.
- `R1_15A2_CONFIG_V2_4_7.json`
  - explicitní metodika, limity, tolerance a disková politika.
- `R1_15A2_FULL_OVERNIGHT_PATH_EPOCH_V2_4_7.py`
  - nový launcher a oddělený `R1_15A2_V247_RUNS` root.

## Bezpečnostní vlastnosti

- frozen paths jsou pouze proposal authority;
- candidate acceptance zůstává čerstvý Visum assignment + live diagnostics;
- immutable network/DSEG/procedure context drift je hard failure;
- nově kladná OD bez epochového supportu vynutí refresh;
- neúplný search, STOP, timeout nebo chyba není plateau;
- fresh path basis je povinná před stationarity;
- přesný hash zůstává pro audit, tolerantní hash pouze pro plateau comparison;
- starý SQLite store se maže až po úspěšném ověření nové epochy;
- mazat lze pouze přesný superseded `TWO_MODE_PATH_STORE.sqlite`;
- accepted `.ver` checkpointy se nemění.

## Testování

Finální lokální sada:

```text
569 passed
0 failed
0 skipped
```

Pokryto mimo jiné:

- všechny zděděné V2.4.5/V2.4.6 testy;
- live OD reweight bez geometry re-exportu;
- nově kladná OD s nulovým i úplně chybějícím supportem;
- profile identity a immutable observation contract;
- accepted-state cache retention;
- demand i Supply plateau refresh controller flow;
- refresh budget fail-closed;
- PathIndex renumbering invariance;
- podmikro volume noise tolerance se zachováním exact SHA;
- bezpečné odstranění superseded SQLite store;
- nový V2.4.7 launcher a oddělený run root;
- zdrojový `.ver` beze změny v syntetickém end-to-end průchodu.

## Benchmark

Syntetický kompletní malý fixture má 3 enumerace u obou politik, protože V2.4.7 záměrně přidává čerstvé plateau certifikace.

Stress fixture s 12 po sobě přijatými demand stavy:

```text
V2.4.6 invalidace: 12 enumeration requests
V2.4.7 frozen epoch: 1 enumeration request
redukce: 11 / 91,67 %
```

Oba stress běhy měly stejný status, accepted count a assignment/recompute count. Nejde o reálné Visum wall-time měření.

## Hranice tvrzení

- offline implementace a testy: dokončeno;
- nezávislý unpack/tamper gate: musí být součástí finálního balení;
- skutečný PTV Visum 2026 COM bounded run: neproveden v tomto prostředí;
- production ready: ne, dokud neprojde živý checklist.
