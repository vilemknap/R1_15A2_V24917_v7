# R1 15A2 V2.3.7 - oprava prvniho design-only behu, 11D compatibility guard (16.10.2026)

## Vysledek prvniho realneho testu

`00_RESULT.json`: `BLOCKED_OR_FAILED` ve fazi 11D, `accepted_count=0`, `apply=false`, `emergency_rollback_verified=true`. Selhani je presne na `r1_15a2_runtime_v1.py:run_11d`: helper vytvoril summary, ale jeho `final_status` nebyl puvodne vynucovany `PASS_11D_BASELINE_DIAGNOSTICS_READ_ONLY`.

V exportu aktivni Procedure Sequence je 43 operaci a **zadna typu 66**. Stary 11D zahrnuje neaktivni TFlowFuzzy scaffold typu 66 jako povinnou kontrolu. Soucasny R1 15A2 nepouziva TFlowFuzzy pro svoji kalibraci. To je predem prokazany konflikt; bez samostatneho 11D summary vsak nelze vedet, zda soucasne nedoslo i k dalsi stare 11D `REVIEW` podmince. Tato verze ponechava originalni summary nedotcene a uklada vlastni `11D_15A2_COMPATIBILITY_GATE.json`.

Druhy nezavisle potvrzeny problem: komponentni CSV stareho 11D maji prefix `r1_step11d_v1_3_component_dist_behavior_`, ale starsi kalibracni nacteni hledalo `component_model_dist_vs_idp_summary.csv` atd. bez prefixu. Opraveno v `R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py`.

## Co se zmenilo

- POUZE `r1_15a2_runtime_v1.py` a `R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py` (plus nove testy, tento navod a auditni report).
- Legacy 11D `REVIEW` z chybějícího neaktivniho TFlowFuzzy, vlastniho stareho selectu CountLocations a fallback vah kompozitu je pro **DESIGN ONLY** pouze auditnim upozornenim, jestlize vsechny dulezite vlastni IDP kontroly vysly.
- Tvrdé brany zustavaji: 12D 498 radku (462 CAL, 36 VALID), 11 atomickych IDP komponent (WORK 5, SERVICE 5, SCHOOL 1) se skutecnymi konecnymi a nenegativnimi ciselnymi metrikami, matice DIST_KM, nulove nevalidni/negativni hodnoty klasifikacni matice, vyhlasene read-only stavy `False`, absence **aktivni** korekce typu 66 a existence vsech tri fyzickych komponentnich CSV. Neocekavany status nebo necitelna data = FAIL.
- Pokud se brana zamitne, `11D_CURRENT.zip` i `11D_15A2_COMPATIBILITY_GATE.json` se zachovaji pro diagnostiku.
- Pro `apply=true` stale plati striktni legacy 11D PASS; navrhovou kompatibilitu tato oprava **nikdy sama o sobe nepovoluje pro produkcni APPLY**.
- Konfigurace `apply=false`, schvalene profily 408+90, zony, OD matice, linky, epsilon 0.005 a vsechny numericke moduly / pomocne skripty zustaly beze zmeny.

## Jak spustit

1. Rozbal **cele** nove ZIP do samostatne slozky pobliz otevreneho `.ver`; nespoustej stary rozbaleny balicek z minuleho testu.
2. Otevri stejny spravny model s aktualnim assignmentem ve Visumu (pro jistotu kopii `.ver`).
3. Spust `R1_15A2_DESIGN_ONLY_FIRST_RUN_V2_3_7.py` pres Visum > Scripts > Execute script file. Nikoli z Procedure Sequence. Tento skript striktne vynucuje `apply=false`.
4. Vysledky vzniknou ve slozce `.ver` pod `R1_15A2_V2_3_7_RUNS/RUN_.../`. Posli `00_RESULT.json`. Pokud to opet skonci v 11D, pridej `CALIBRATION/BASELINE/11D_CURRENT/11D_15A2_COMPATIBILITY_GATE.json` a `CALIBRATION/BASELINE/11D_CURRENT.zip`. Pokud probehne navrh, posli take vystupy `DESIGN_SUPPLY_ADDVAL1`.

Pro presne urceni puvodniho legacy 11D `REVIEW` muzes jiz ted poslat ze **stareho** behu:
`CALIBRATION/BASELINE/11D_CURRENT/r1_step11d_v1_3_component_dist_behavior_summary.json`.

## Stav pripravenosti

322 offline testu PASS; vcetne 21 novych striktnich testu. Live Visum s touto upravou zatim nebezel. `assignment_operations=[]`, dva metodicke QA approval priznaky false, overeni cerstvosti assignmentu/parity tras dale zustavaji podminkou pro pripadny pozdejsi APPLY. Samostatny B/C marginal guard je mimo tento balicek.
