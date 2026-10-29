# Pád při ověření první pracovní kopie: diagnostika operací

Uživatelův živý běh z 29. 10. 2026 v 22:41 skončil po 24,491 s chybou `WORKING_COPY_SEMANTIC_IDENTITY_MISMATCH:operations_hash` v `r1_15a2_fresh0_shortroot_parent_v24916.py` při porovnání živého zdroje s pracovní kopií po SaveVersion. Kalibrační cykly ještě nezačaly. Podle výsledku zůstal původní zdrojový `.ver` na disku bajtově nezměněný a nebylo voláno LoadVersion.

Oba plné snapshoty proběhly úspěšně. Obsahovaly 37 matic, 24 DSeg, 33 generovacích atributů a 43 operací; aktuální tabulka autority obsahuje 248 CAL profilů. Varování o jedné lince s nulovým časem označuje vyloučení ze Supply ADDVAL1 páky a není příčinou tohoto pádu. Path-length preflight prošel.

## Co lze a nelze z logů určit

Jediný hlášený nesoulad je `operations_hash`. Do něj vstupují pořadí/pozice, typ, ACTIVE, COMMENT a NAME jednotlivých operací. Z dodaných hashů nelze rekonstruovat, která z těchto hodnot se změnila. Samotná příčina změny operace proto zůstává nevyřešená. Nepovažujeme změnu NAME nebo COMMENT předem za neškodnou a nic z porovnání nevyřazujeme.

Nalezená chyba diagnostiky: rodičovský launcher publikuje podrobnosti o pracovní sémantické autoritě až po `require_authority_match()`. Při jejím selhání tak pracovní důkaz není uložen. Snapshot navíc uchovává pouze hash operací, ne jejich konkrétní řádky.

## Změna

V `r1_15a2_snapshot_reads_v24917.py` se během dvou již existujících startovních fází automaticky publikuje inventář ze stejného čtení, ze kterého se počítá hash. Nevzniká nové COM čtení ani zápis do modelu. V adresáři běhu vzniknou ještě před rodičovskou kontrolou:

- `SOURCE_OPERATIONS_READBACK.json` — přesný inventář zdroje a všech sedm sémantických hashů;
- `WORKING_COPY_OPERATIONS_READBACK.json` — stejný důkaz pracovní kopie;
- **`WORKING_COPY_OPERATIONS_DIFF.json`** — oba důkazy pohromadě, změněná sémantická pole a přesné změny jednotlivých operací před/po. Pro další rozbor stačí tento jeden soubor.

Při zjištěném rozdílu se na konzoli objeví číslo operace, změněná pole a cesta k JSON. Diagnostika nemění veřejné schéma snapshotu, state_hash, operations_hash ani kontrolu sémantické shody. Neprovádí automatické obnovování/normalizování operací a žádný nesoulad nepovoluje. Chyba při zápisu neautoritativní diagnostiky je oznámena; původní kontrola modelu rozhoduje dál beze změny.

Běžné snapshoty během kalibrace tyto soubory nepíší. Nové startovní čtení zdroje nahradí případný předchozí záznam v paměti adaptéru, aby se neporovnávalo s jiným zdrojem.

## Jak získat potřebný důkaz

1. Rozbal celý nový GitHub ZIP; nespouštěj směs různých vydání.
2. Ve Visumu ručně znovu otevři původní **`R1_novy_start.ver`**. První pokus už uložil jinou pracovní kopii; její stav nepoužívej automaticky jako nový zdroj.
3. Spusť běžný **`01_SPUSTIT_V24917_TDJOINT1.py`**. Samostatný auditní launcher ani další reset koeficientů není pro tuto diagnostiku potřeba.
4. Pokud se chyba opakuje, pošli **`WORKING_COPY_OPERATIONS_DIFF.json`** z nového adresáře běhu `R1_15A2_V16_RUNS/RUN_.../`. Bude obsahovat konkrétní operaci a hodnoty nutné pro opravu příčiny.

Toto vydání opravuje ztrátu diagnostického důkazu, nikoli dosud neznámou změnu způsobenou živým SaveVersion. Spuštění celé kalibrace bez původního pádu zatím potvrdit nelze. Živý Visum zde nebyl k dispozici.

`LIVE_FAILURE_FACTS.json` obsahuje ověřená fakta z dodaných logů a jejich SHA-256. Původní vstupní logy jsou uchovány v pracovním prostředí; do veřejné větve se nepřidávají jejich uživatelské absolutní cesty. `CHECKS.json`, `RESULTS.json` a logy obsahují offline ověření. Patch obsahuje všechny změny zdrojů, testů a manifestů.
