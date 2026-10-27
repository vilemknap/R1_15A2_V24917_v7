# R1 15A2 V2.4.0 — plná noční trial-assignment kalibrace

## Co tato verze dělá

Toto už není pouze design-only sonda. Skript na **izolované pracovní kopii** skutečně:

1. provede čerstvý celý aktivní Procedure Sequence a stanoví baseline,
2. navrhne kandidáta `SUPPLY_ADDVAL1`, `GENERATION` nebo komponentního TD `b,c`,
3. dočasně zapíše kandidátní parametry,
4. spustí skutečný Visum přepočet,
5. znovu načte živé 12D/11D diagnostiky a společný objective,
6. kandidáta přijme jen pokud projde existujícími GEH/IDP ochrannými gate a zlepší společný objective,
7. zamítnutého kandidáta vrátí **bez LoadVersion**: obnoví pouze kalibrované parametry a znovu provede stejný přepočet,
8. po rollbacku vyžaduje přesně stejný snapshot i diagnostický hash jako před pokusem,
9. po přijatém kroku pokračuje dalším blokem/cyklem až do konvergence, 10hodinového limitu nebo `STOP_REQUESTED`.

## Assignment

- `SUPPLY_ADDVAL1`: pouze autoritativní finální **operation 20 / type 101 / přesný 14-DSeg DSEGSET**. Demand se nemění.
- `GENERATION` a všechny TD bloky: celý aktivní Procedure Sequence, protože je nutné znovu vytvořit poptávku a všechny downstream assignment výsledky.
- GAP op20 musí projít stávající hranicí `<= 0.005`.

## Rozsah linků

Není žádný globální gate typu „kalibruj jen N linků“.

- `editable_link_types = null`
- `excluded_link_keys = []`
- každý link otevřený pro `C` nebo `C_noT` je potenciálně kalibrovatelný,
- `max_edges = 12` je **pouze lokální velikost jednoho trial kandidáta**, nikoli globální počet linků, které smějí být během noci změněny,
- po každém přijatém kroku se znovu vyhodnotí celý eligible network a další kandidát může být na úplně jiných linkách.

Zůstávají fyzikální/numerické ochrany `max_step`, `max_cumulative`, minimum cost a absolutní bounds. Ty chrání velikost změny, nikoli rozsah sítě.

## Dvourežimová geometrie

Úplná identity geometry ještě není 15T-proven. V2.4.0 ji proto používá **jen pro návrh kandidáta**. Nikdy není konečnou autoritou pro accept/reject.

Konečné rozhodnutí je vždy:

`candidate -> skutečný Visum assignment/procseq -> nové živé intenzity/GEH/IDP -> accept/reject`

Proto 15T není blocker tohoto pracovního nočního běhu. Zůstává vhodný jako následná validační kontrola před produkčním release.

## Ochrana zdrojové .ver

Skript nejprve uloží `WORKING_START.ver` do nového run adresáře. Od tohoto okamžiku kalibruje pouze tuto pracovní kopii.

Původní `.ver` se na začátku i na konci hashuje a `00_RESULT.json` obsahuje `source_file_unchanged`.

Rollback **nikdy nepoužívá `LoadVersion`**.

Po každém accepted state se střídavě ukládají dvě recovery kopie:

- `CALIBRATION/CHECKPOINTS/LATEST_ACCEPTED_A.ver`
- `CALIBRATION/CHECKPOINTS/LATEST_ACCEPTED_B.ver`

Na úspěšném konci se uloží:

- `FINAL_CALIBRATED_WORKING_COPY.ver`

Pokud by rollback selhal, běh se fail-closed zastaví a v `00_RESULT.json` ukáže poslední ověřený accepted checkpoint k ručnímu otevření.

## Metodické upozornění

Tento běh je plná **pracovní kalibrace**, ale není automatický production release:

- `production_apply = false`,
- stávající CSD408 mapping-review a CITY90 bidirectional-QA acknowledgement zůstávají nezměněné,
- všech 498 řádků pozorování zůstává zachováno a jejich CAL/VALID role se nemění,
- konfliktní same-source skupiny mohou být podle dosavadní diagnostické politiky vynechány pouze jako *candidate drivers*; nejsou mazány z diagnostiky ani přepisovány.

## Noční rozpočet

- max runtime: **10 hodin**,
- max cycles: 100,
- max accepted states: 100,
- na jeden blok se testuje omezený počet kandidátů, aby první cyklus nevyčerpal celou noc,
- ukončení dříve: celý cyklus bez accepted improvement.

Časový limit je kooperativní; běžící jedno COM/Visum volání se násilně nepřerušuje.

## Jak spustit

1. Rozbal celý ZIP do samostatné složky.
2. Otevři ve Visumu baseline `.ver` s uloženými assignment paths.
3. Nech PC na napájení, vypni uspávání a automatický restart Windows.
4. **Scripts -> Execute script file**.
5. Spusť:

   `R1_15A2_FULL_OVERNIGHT_CALIBRATION_V2_4_0.py`

6. Nespouštěj ho z Procedure Sequence a ve stejné instanci Visumu současně nespouštěj nic dalšího.

Run vznikne vedle původní `.ver` v:

`R1_15A2_V2_4_0_FULL_OVERNIGHT_RUNS/RUN_.../`

Průběh:

`00_PROGRESS.json`

Ruční bezpečné zastavení: vytvoř prázdný soubor `STOP_REQUESTED` v aktuálním `RUN_...` nebo v nadřazené složce `R1_15A2_V2_4_0_FULL_OVERNIGHT_RUNS`.

## Co poslat ráno

Nejdůležitější:

- `00_RESULT.json`
- `CALIBRATION/RUN_STATUS.json`
- `CALIBRATION/ACCEPTED_STATE.json` (pokud vznikl)
- poslední `CYCLE_.../BLOCK_RESULT.json` pro případ, že běh skončil chybou

Celé SQLite path cache zatím neposílej.
