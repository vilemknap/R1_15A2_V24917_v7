# Forenzní audit R1 15A2 V2.0 → V2.1

## Výsledek

V2.0 nebyla samostatně spustitelná distribuce. ZIP obsahoval master, config a dokumentaci, ale chyběly importované numerické/runtime moduly, oba helpery a dvě autority. Dřívější PASS tak dokazoval hlavně izolovanou matematiku, nikoli čisté rozbalení a spuštění dodaného balíku.

V2.1 je zabalena jako samostatný strom a čisté rozbalení je součástí gate.

## Nálezy a opravy

| Závažnost | Nález ve V2.0 | Oprava V2.1 |
|---|---|---|
| Kritická | Chyběly `r1_15a2_core`, runtime, multiblock, Visum adapter, 11D/12D helpery a autority. | Vše je součástí ZIPu; import/compile/clean-extract test. |
| Kritická | Agregovaná LONG/CL 100–200 křivka mohla být používána jako společný target pěti komponent. | Agregovaný CL target je guard-only. Component LONG potřebuje explicitní per-component autoritu. |
| Kritická | TD_LONG change gate používal obecný W/S mutable scope. | Samostatný matrix scope pro každý blok; LONG = 9111–9115 + NATIVE_CL. |
| Vysoká | Backtracking mohl zmenšit `b,c` proposal při návrhu a podruhé při materializaci. | Neškálovaný trust-region krok se počítá jednou, scale se aplikuje právě jednou. |
| Vysoká | `ALL_MUTABLE_RELATIONS` dovoloval guidance pro OD s endpointem bez implementovatelného aktuátoru. | Default `BOTH_ENDPOINTS_ACTUATABLE`; exclusions se použijí už při stavbě incidence. |
| Vysoká | ZAHR větev nekontrolovala přesný formula base. | ZAHR vyžaduje `ZAHR_SUSED > 0` a `POP_ZP_2022 > 0`. |
| Vysoká | Chybějící/nenumerický Zone atribut mohl být zkonvertován na nulu. | Strict numeric read; blank, NaN, missing, duplicate nebo unexpected ZoneNo failnou. |
| Vysoká | P/A consistency se reportovala i z řádků, které byly kvůli zero/bounds přeskočené. | P/A totals se počítají z přesně implementovaného nelineárního efektu po bounds. |
| Vysoká | `ADD_SALARY` a `ADD_ATT_W` byly potenciálně neidentifikovatelné. | Jedna regularizovaná income basis + zónový ADD_ATT residual; exact formula readback. |
| Vysoká | Neúplná shoda target/model distance binů mohla vytvořit kandidát. | Exact bin authority coverage gate. |
| Střední | `b` shape krok byl jednostranný. | Signed short–middle shape signal dovolí `b` zvýšit i snížit. |
| Střední | Aktivita konkrétní TG/TD operation nebyla tvrdě ověřena. | Vybraná operation musí být aktivní; DStratSet a jednotlivá strata se ověří. |
| Střední | Formula token audit byl prostý substring. | Vyžaduje bracketed Visum atribut `[TOKEN]`. |
| Střední | Importovaný runtime neviděl automaticky Visum injected global. | Master explicitně binduje svůj `Visum/COM` objekt do runtime modulu. |
| Střední | Rollback nebyl po reloadu kompletně numericky prokázán. | Hashy block matrices + všech 9 generation parametrů + 16 komponentních `b,c`. |
| Střední | TD acceptance mohla skrýt zhoršení jednotlivé komponenty. | Selected-component a nonselected-component guard, CSD CAL guard a global IDP guard. |
| Terminologie | `TD_SCHOOL` vypadal jako samostatná assignment family. | `TD_COMPONENT_SCHOOL`; SCHOOL je jedna komponentní křivka. |

## Co audit záměrně neudělal

- Nevytvořil chybějící produkční LONG component target z agregované CL křivky.
- Neaktivoval přímý OD write.
- Neměnil supply, `ADDVAL1`, VDF ani kapacity.
- Neprovedl live PTV Visum COM run.

## Závěr

V2.1 je vhodná pro první **design-only live gate**. Za produkčně ověřenou ji lze označit až po živém path exportu, parity, TG/TD parameter readback, jednom bounded apply pokusu a prokázaném ACCEPT nebo exact ROLLBACK.
