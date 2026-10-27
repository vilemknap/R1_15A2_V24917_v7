# R1 15A2 – bezpečný první návrhový běh (V2.3.7)

**Účel:** dokončit první živý end-to-end test 15A2 (12D, 11D, export uložených tras, návrh všech bloků) nad již spočteným assignmentem, **bez kalibračního APPLY**.

## Co spustit

1. Rozbal ZIP jako celek (ponechat kompletní podadresáře `helpers/` a `authorities/`).
2. V PTV Visum otevři **kopii** posledního správně přiřazeného `.ver` se současnou sítí a poptávkou. Pokud mezitím samostatná B/C kalibrace změnila TD, nejdříve dokonči navazující kroky vehicle realization + assignment na nové verzi.
3. Přes **Scripts > Execute script file** (nikoli z Procedure Sequence) spusť `R1_15A2_DESIGN_ONLY_FIRST_RUN_V2_3_7.py`.
4. Ve složce otevřeného `.ver` najdi `R1_15A2_V2_3_7_RUNS/RUN_.../00_RESULT.json` a podsložku `CALIBRATION/`. Pošli `00_RESULT.json`, `CALIBRATION/00_PREFLIGHT.json`, případně `CALIBRATION/BASELINE/` výstupy a celou podsložku `DESIGN_SUPPLY_ADDVAL1/` zabalenou do ZIPu (nebo celý RUN bez objemných .ver).

## Záruky a omezení

* Entrypoint pevně nastavuje `apply=False` a IGNORUJE i `R1_15A2_V237_APPLY=1`; proto nespustí žádný kalibrační zápis do `ADDVAL1`, zónových aktuátorů ani parametrů TD.
* Diagnostika 12D má v této **kopii** helperu `WRITE_DIAGNOSTIC_UDAS=False`. Čte 498 schválených CountLocations, ale nezapisuje do nich pomocné atributy `R1_12D_*`. Toto je **jediná** změna v helperu; měření a výpočty GEH se nemění.
* Master ukládá do RUN složky ochrannou kopii `.ver` (SaveVersion) a vytváří soubory/SQLite auditů. Tyto souborové výstupy jsou očekávané. Samotné `SaveVersion` je akce hostitelské aplikace – spusť v kopii otevřeného `.ver`.
* `run_procseq=True` v konfiguraci neznamená, že design-only spustí assignment. Větve `adapter.assign()` jsou pouze pod `if cfg['apply']`, které tato verze trvale vypíná.
* Pokud jsou uložené trasy po změnách poptávky/sítě neaktuální, návrhy 15A2 nebudou autoritativní. Nesnižuj prahy coverage/parity jen kvůli PASS.
* Produkční master `R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_7.py` **není** tímto testem nahrazen ani povolen. `assignment_operations=[]`, `csd408_mapping_review_acknowledged=false`, `city90_bidirectional_qa_acknowledged=false`; ostré APPLY je stále blokované.
* `MARGINAL_GUARD` ze samostatné B/C kalibrace **není součástí 15A2**.

## Jak interpretovat výsledek

* `DESIGN_ONLY_READY_FOR_LIVE_APPLY_GATE`: všechny navržené bloky mají návrh; stále NENÍ povolení APPLY.
* `DESIGN_ONLY_BLOCKERS`: alespoň jedna fáze návrhu neprošla. Použij její `status/error` pro opravu.
* `LIVE_API_REVIEW_REQUIRED`: povinné COM kontroly nepřešly, nebo byl zapnutý audit-only.
* Jakákoli COM exception: vrať se k outputům RUN a tracebacku. Bez skutečného Visum testu tento běh nelze garantovat.

## Co bude před ostrým APPLY nutné

Schválit seznam a pořadí assignment operací (17–20 vs. pouze finální op. 20 podle závislostí), ověřit po čerstvém assignmentu GAP op.20 <= 0.005, projít živou paritu/coverage uložených cest, uzavřít schvalovací QA u 408 CSD a 90 městských profilů a potvrdit skutečné návrhy bloků.
