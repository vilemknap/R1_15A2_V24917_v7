# R1 15A2 V2.2 — Actual-path ADDVAL1 Supply / Demand

## Výchozí autorita

Navazuje na skutečný `R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_V2_1_AUDITED.zip`, SHA256 `8bb9b461424ea6d1780791bbc949d70ba4e61ae2c613298cd5071f2170a9bcbf`. Původní generation/TD numerika a helpery 11D/12D jsou zachovány. Runtime exportér má skutečně změněné rozhraní pro zpracování každého DSegu novým supply kolektorem.

## Co V2.2 provádí

Jeden controller střídá `SUPPLY_ADDVAL1`, `GENERATION`, `TD_COMPONENT_WORK`, `TD_COMPONENT_SERVICE`, `TD_COMPONENT_SCHOOL`, `TD_COMPONENT_LONG`. Každý kandidát vzniká ze stejného přijatého checkpointu svého bloku. Všechny omezené alternativy se vyhodnotí, vrátí do PRE a z přípustných kandidátů se přijme nejnižší společný objective. Vybraný uložený stav se znovu načte a ověří; neregeneruje se jiným během.

Supply mění pouze směrový `Link.ADDVAL1`, při nezměněných OD, generation a b,c. Generation/TD drží ADDVAL1 pevné. Assignment-only výběr dočasně vypne ostatní operace a v `finally` obnoví původní ACTIVE flagy. Neexistuje přímý zápis OD buněk ani vlastní routing/Dijkstra.

Zápis ADDVAL1 používá přesné klíče `(LinkNo, FromNodeNo, ToNodeNo)`, očekávanou starou hodnotu a parent/path identitu. +1 ADDVAL1 znamená +10 sekund zobecněné impedance; není přičítán k fyzickému jízdnímu času. Freight nemá přímý ADDVAL1 člen, ale musí být znovu přiřazen společně.

## Skutečné cesty

Supply exportuje šest NATIVE a šest EXOG_EE osobních DSegů, včetně CL a CF. Zpracovává explicitní uložené PrT paths a seřazené path-link záznamy po jednotlivých DSegech. Kandidát srovnává trasy přes profil a mimo profil v rámci stejného DSeg/OD. Společné hrany alternativ se v kontrastu odečítají; jiná OD nesmí vytvořit falešný bypass.

U profilů se ověřuje shoda vůči skutečnému celkovému osobnímu modelovému toku, ne pouze vůči rekonstruované podmnožině. Není-li uložená alternativa, návrh je výslovně jen actual-path probe vyžadující nový assignment; není vydáván za prokázanou citlivost. Prázdná intrazonální cesta nevytváří fyzické linkové zatížení. Opakovaný průjezd stejnou hranou se započítává i do konzervativního rozpočtu změny trasy.

## Nastavení a živý vstup

Spouštět ručně přes Visum Scripts, nikdy nevkládat master do aktivní Procedure Sequence. Nastavení je v `R1_15A2_CONFIG_V2_2.json`. Výchozí `apply=false`, `max_accepted_blocks=1`, `max_cycles=2`. Proměnná `R1_15A2_V22_APPLY=1` dovolí APPLY jen po úspěšném preflightu.

`assignment_operations` je záměrně prázdné a `gap_readback.attribute` není vyplněn. Je nutné z živého modelu určit přesná čísla a typy assignment operací, jejich skutečný atribut DSeg scope a skutečně čitelný údaj o konvergenci. Testové `operation_type=900` a `Net.GAP` jsou pouze mock fixture, nikoli doporučené Visum API. Bez schválených údajů APPLY korektně skončí blokací.

Design-only běh vypíše `00_DSEG_INVENTORY.json`, `00_SUPPLY_ASSIGNMENT_PLAN.json`, `00_PREFLIGHT.json` a návrhy bloků. Může vytvořit souborový checkpoint `.ver` a diagnostické exporty; nespouští assignment ani kalibrační změny parametrů. Při neočekávané změně modelem/diagnostikou provede ověřený návrat.

Aktivní assignment musí zahrnout všechny deklarované osobní a freight DSegy; neodsouhlasený další agregovaný DSeg je odmítnut, aby nebyla doprava přiřazena dvakrát. Názvy LNV/NV a všech osobních DSegů jsou explicitní konfigurační autorita, nikoli fuzzy odhad.

## Omezení a objective

Výchozí supply krok je 1 jednotka, kumulativní odchylka 4 proti původnímu vektoru, nejvýše 6 hran / 60 ekvivalentních sekund a 8 kandidátů. Jsou to konzervativní vývojové hodnoty odvozené z dodaného G08 presetu, nikoli produkčně optimalizované parametry pro R1. Absolutní limity a kladná minimální impedance se kontrolují současně. Desetinná importovaná baseline se nezaokrouhluje, celočíselné jsou přírůstky.

Společný objective má pevnou počáteční normalizaci CSD CAL, pevné počáteční komponentní váhy IDP a prior ADDVAL1 vůči původní baseline. Původní block-specific generation/TD ochrany zůstávají další podmínkou. VALID nevstupuje do návrhu ani výběru. Nedostupné reportovací metriky se zapisují jako null, nikoli jako falešné nuly nebo důvod zamítnutí CAL kandidáta.

LONG komponentní kalibrace nepřebírá agregovanou CL křivku jako pět targetů: bez vlastní schválené autority zůstává bez kandidáta. SCHOOL politika V2.1 není tímto rozšířením svévolně změněna. V/C není objective ani samostatný supply driver.

## Přijatý stav a obnovení

`ACCEPTED_STATE.json` je jediný publikovaný přijatý stav. Obsahuje snapshot, checkpoint hash, společnou referenci, původní ADDVAL1 kotvu a identitu vědecké konfigurace/implementace. Zápis je atomický. `IN_FLIGHT.json` dokumentuje rozpracovanou změnu. Odmítnuté a chybové kandidáty vrací controller do PRE a ověřuje matice i parametry.

`R1_15A2_V22_RESUME_FROM` ukazuje na předchozí RUN adresář. Semantika je **restart cyklu z posledního přijatého stavu se zachovanými původními kotvami a referencemi**, nikoli pokračování přesně od následující fáze. Změna vědecké konfigurace/implementace starý resume odmítne. Soubor `STOP_REQUESTED` v novém RUN adresáři zastavuje na hranici bloku. Nezlepšení jednoho bloku není konvergence celého modelu.

## Hranice ověření

Offline testy zahrnují numeriku, skutečné produkční funkce s COM-shaped objekty a syntetický controller. Deterministický testovací adapter není assignment engine, Visum ani Dial-B a jeho čísla nejsou výsledkem kalibrace reálné sítě. Skutečný Visum 2026 COM běh dosud není proveden.

Síťový snapshot kontroluje deklarované směrové linkové atributy, všechny načtené DSeg matice a komponentní matice, devět generation atributů, 16 komponentních b,c a operace. Dodané exporty VDF/impedance se hashují, nejsou však automaticky znovu exportovány z živých nastavení. Nejde o úplný generický důkaz všech live node/turn/connector/VDF parametrů. Před APPLY je nutné potvrdit aktuálnost přiložené síťové autority a provést živý checklist.
