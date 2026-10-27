# V2.4.8.6 — implementační a testovací report

## Vstupní větve

- stable project-root V2.4.8.5: `9447609bcda09ec2831f3d8ece193a25cf744d8955febed1a2bd5eb74867cf8c`;
- generation-saturation V2.4.8.5: `fdb193abf51bde4d496ed4b8e1ed08aabbd8286210c7b8de451a52a27b342b32`.

Obě větve byly před merge samostatně spuštěny:

- stable project-root: **601 passed**;
- generation-saturation: **595 passed**.

## Merge strategie

Základem je stable project-root větev. Z generation větve byl převzat skutečný numerický modul `r1_15a2_multiblock.py`; konfigurace, launcher, safety contract a package verifier byly ručně sloučeny. Nevzniklo překopírování ZIPu přes ZIP.

V2.4.8.6 současně vyžaduje:

1. outermost prior-run-tree normalizaci a postcondition zákazu vnořeného nového runu;
2. bound-constrained Generation projekci;
3. read-only cache bridge pro V2.4.8.1–V2.4.8.4 a obě divergentní V2.4.8.5 větve;
4. původní fresh assignment + live 12D/11D acceptance.

## Dodatečné odladění při merge

Při cíleném testu byla nalezena identitní nekompatibilita: zděděný validator připouští v `performance.release` pouze `V2.4.7` nebo `V2.4.8`. Hodnota byla správně ponechána na `V2.4.8`; vlastní release identita V2.4.8.6 je samostatně hashově uzamčená.

Dále byla opravena analogická mezera saturation hotfixu: přímý aktuátor s nulovou hodnotou a aktivní `preserve_zero` byl dříve odstraněn až po P/A projekci. Nyní je označen jako nulová implementovatelná kapacita ještě před vyvážením, takže nevytváří stejný deterministický P/A gap jako hard-max saturation.

## Replay skutečného V2484 pádu

Z dodaného `GENERATION_DESIGN(2).json` bylo přehráno 1 374 normalizovaných WORK/SERVICE řádků.

- odstraněné saturované aktuátory: `ZAHR_PROD_WORK`, `ZAHR_PROD_SERV` v zóně 619;
- WORK relativní P/A gap po rebalancování: `1.779270796523963e-14`;
- SERVICE relativní P/A gap po rebalancování: `7.707279611355136e-13`;
- zápis saturovaného aktuátoru nad 10: **ne**;
- unresolved families: **0**.

Toto je proposal replay, nikoli náhrada živého Visum assignmentu.

## Testování

Finální source tree před zabalením:

- `compileall`: PASS;
- úplný pytest: **607 passed, 0 failed, 0 skipped**;
- combined root + saturation cílená sada: PASS;
- obě V2.4.8.5 cache identity: PASS;
- preserved-zero capacity regression: PASS;
- single/double/triple nested run-root derivation: PASS;
- reálným pádem tvarovaný Generation replay: PASS.

## Neměněné autority

`V2486_CRITICAL_PARITY.json` dokládá byte-for-byte shodu obou parent větví u path-store, adapteru, persistent-cache manageru, runtime, assignment controlleru a FineCDF v1.8. Numerická změna je omezena na Generation proposal konstrukci; acceptance autorita se nemění.

## Hranice

Skutečný PTV Visum 2026 COM běh V2.4.8.6 nebyl v tomto prostředí proveden. `production_ready=false` zůstává povinné až do živého checklistu.

## Balíkovací gate

Kandidátní ZIP prošel mechanickou integritou, nezávislým rozbalením, package verifierem a opakovanou sadou 607 testů. Úmyslná změna `r1_15a2_multiblock.py` byla manifestem odmítnuta s nenulovým návratovým kódem. Stejné kontroly se opakují nad finálními bajty.
