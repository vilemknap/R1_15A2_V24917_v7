# R1 15A2 V2.4.1 — FULL OVERNIGHT HIERARCHICAL CALIBRATION

## Zásadní oprava proti V2.4.0

V2.4.0 měla chybně `SUPPLY_ADDVAL1` jako první kalibrační blok. V2.4.1 zavádí tvrdé metodické pořadí a supply nelze spustit dříve:

1. **TRIP_GENERATION** — pouze `GENERATION`, opakovaně do konvergence.
2. **TRIP_DISTRIBUTION** — `TD_COMPONENT_WORK`, `TD_COMPONENT_SERVICE`, `TD_COMPONENT_SCHOOL`, `TD_COMPONENT_LONG`, opakovaně do konvergence.
3. **SUPPLY_ROUTE_CHOICE** — pouze `SUPPLY_ADDVAL1`, až po konvergenci obou demand fází.

Konvergence fáze znamená celý průchod jejími bloky bez jediného přijatého zlepšení a bez blokující chyby. Pokud TG nebo TD skončí chybou, limitem cyklů, STOPem nebo vypršením časového rozpočtu, ADDVAL1 se nespustí.

## Co skutečně přepočítává Visum

- `GENERATION`: po každém trialu se spouští celý aktivní Procedure Sequence, protože se mění poptávka.
- `TD_COMPONENT_*`: po každém trialu se spouští celý aktivní Procedure Sequence.
- `SUPPLY_ADDVAL1`: po každém trialu se spouští pouze autoritativní PrT assignment operation 20; demand parametry jsou v supply fázi zmrazené.

Každý kandidát je vyhodnocen ze skutečného nového Visum assignmentu a živých 12D/11D diagnostik. Saved-path cache slouží pouze k návrhu supply kandidátů.

## Síť není globálně omezena počtem linků

`trial_calibration.global_link_count_cap = null` a `full_network_link_eligibility = true`.

`max_edges = 12` je pouze maximální velikost jednoho lokálního ADDVAL1 trial bundle. Není to strop počtu linků, které mohou být v průběhu celé kalibrace změněny. Po každém přijatém kroku se znovu vyhodnotí celá síť.

## Bezpečnost

- Zdrojová `.ver` se nekalibruje přímo.
- Runner nejprve vytvoří `WORKING_START.ver` v adresáři běhu.
- Rejected trial se vrací obnovením konkrétních parametrů a skutečným recompute; `LoadVersion` se nepoužívá.
- Po přijatém stavu se ukládají rotační recovery checkpointy.
- Po konvergenci každé fáze vzniká samostatný checkpoint:
  - `PHASE_CHECKPOINTS/TRIP_GENERATION_CONVERGED.ver`
  - `PHASE_CHECKPOINTS/TRIP_DISTRIBUTION_CONVERGED.ver`
  - `PHASE_CHECKPOINTS/SUPPLY_ROUTE_CHOICE_CONVERGED.ver`
- Pokud rollback nelze přesně ověřit, běh končí fail-closed.

## Noční běh

Výchozí časový rozpočet je 10 hodin / 36 000 sekund. Je společný pro všechny tři fáze. Pokud se rozpočet vyčerpá během TG nebo TD, supply se správně vůbec nespustí.

Ruční korektní zastavení: vytvoř soubor bez přípony `STOP_REQUESTED` v aktuálním `RUN_...` nebo v nadřazené složce runs.

## Jak spustit

1. Rozbal **celý** balík do samostatné složky.
2. Ve Visumu otevři baseline `.ver` s aktuálními uloženými assignment výsledky.
3. Nepouštěj paralelně jinou kalibraci ve stejné instanci.
4. Spusť přes **Scripts → Execute script file**, nikoli Procedure Sequence:

   `R1_15A2_FULL_OVERNIGHT_HIERARCHICAL_V2_4_1.py`

Výstupy vzniknou vedle baseline modelu v:

`R1_15A2_V2_4_1_FULL_OVERNIGHT_HIERARCHICAL_RUNS/RUN_.../`

Průběžný stav: `00_PROGRESS.json`.
Finální výsledek: `00_RESULT.json`.

## Očekávaný metodický průběh

`BASELINE FULL PROCSEQ`
→ `TRIP GENERATION until convergence`
→ phase checkpoint
→ `TRIP DISTRIBUTION until convergence`
→ phase checkpoint
→ `ADDVAL1 / route choice until convergence`
→ phase checkpoint
→ `FINAL_CALIBRATED_WORKING_COPY.ver`

V2.4.0 pro nový běh nepoužívej; měla nesprávné pořadí supply před demand kalibrací.

## Offline ověření

Finální zdrojová větev před zabalením: 442/442 testů PASS. Původních 252 ne-cache souborů V2.4.0 zůstalo bitově beze změny; V2.4.1 je aditivní hierarchická oprava. Živý kompletní běh V2.4.1 v PTV Visum zatím proveden nebyl.
