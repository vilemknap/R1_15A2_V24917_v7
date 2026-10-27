# SAFETYFIX2 / TDROLLBACKFIX1 — dokončená oprava (27. 10. 2026)

## Co obsahuje dodávka

Základem je skutečný archiv SAFETYFIX1, nikoli starší MOBILITYFIX1. Zachovány jsou všechny tři opravy SAFETYFIX1: odmítnutí TD kandidáta při nedostupném společném skóre, výslovný globální fallback při nulové FlowBundle evidenci a omezené opakování COM čtení LONG/SCHOOL bez falešné stacionarity.

Nová oprava mění pouze dva existující produkční moduly, přidává jeden testovací modul a aktualizuje tři navazující integritní manifesty. Generation, SupplyMix, váhy, akceptační prahy, R1_RUN_OPTIONS.json, 24 souborů autorit a 1 059 souborů chráněného základu se nemění. Komponentové skimy se nezavádějí.

## Co prokazují nové podklady

GENERATION_BLOCK_RESULT(20261027-143617).json uvádí ACCEPTED. LATEST_ACCEPTED_CHECKPOINT(20261027-143605).json uvádí accepted_count=1 a ACCEPTED_A_0001_f3e10746c18b.ver. Následný TD_FINECDF_BLOCK_RESULT(20261027-143543).json uvádí GENFIX2_TD_ROLLBACK_FULL_PARENT_PROOF_FAILED. Základní ROLLBACK_ALL_TD_RESULT(2).json současně uvádí passes=true, snapshot_equal=true, diagnostic_equal=true a gap=0.00460217. Parametrické freeze audity prošly.

Tyto záznamy nejsou důkazem, že byl model nevratně poškozen; ukazují rozdílné výsledky dvou vrstev ověřování. Původní dodatečný důkaz se neukládal, takže nelze zpětně vyjmenovat všechny položky, které odmítly konkrétní živý rollback. V kódu jsou ale reprodukovány dva nezávislé falešné důvody odmítnutí, odpovídající používanému LONG/dynamickému skimovému schématu.

## 1. Shodná nekalibrovaná LONG komponenta byla odmítnuta

Skutečná funkce build_td_signals nastavuje u pěti atomických LONG komponent bez samostatné průzkumové autority calibratable=false, authority_status=NO_COMPONENT_LONG_AUTHORITY, policy_reason=AGGREGATE_CL_TARGET_IS_GUARD_ONLY a objective=+inf. Je to značka nepoužitelného samostatného objective, nikoli změna modelu. Původní ověření odmítalo tento stav i při porovnání diagnostiky se svou identickou kopií.

Oprava normalizuje pouze tuto přesně rozpoznanou kombinaci komponenty, rodiny, statusu, policy a kladného nekonečna. NaN, záporné nekonečno, nekonečné aktivní objective i neplatné intenzity/11D hodnoty se nadále odmítají. LONG_COMPOSITE se tímto pravidlem nevyjímá.

## 2. Nová identita výpočtu není změna obsahu skimů

DynamicSkimManager po novém assignmentu zvyšuje epoch a assignment_epoch a vytváří nový assignment_token. Tyto položky jsou zahrnuty také v epoch_hash. Proto se jejich hodnoty mohou lišit i při bajtově shodných maticích a shodných diagnostických hodnotách. Původní kontrola je zaměňovala za rozdíl rodičovského modelu.

Nová kontrola nejprve ověřuje schéma a vlastní hash každé epochy, identitu a jednotky šesti DIS matic, pořadí zón, hash rodinných skimů, vazbu komponentových řádků a IDP gate na správnou epochu a shodu nové diagnostiky s aktuálním managerem. Teprve potom při porovnání oddělí výpočetní identifikátory od obsahu.

Obsahové hashe DIS matic a rodinných skimů zůstávají přesně kontrolované. Neznámé epochové položky se globálně neignorují. Skutečná změna obsahu, metrik, autority, pořadí zón nebo neaktuální diagnostika musí kontrolou neprojít.

## 3. Jednoznačný konečný výsledek rollbacku

TDROLLBACKFIX1_PARENT_PROOF.json vzniká při úspěchu i při odmítnutí plného důkazu. Obsahuje rozdíly parametrů, důkaz matic, rozdíly profilů, GEH a konkrétní cesty neshod v 11D/signálech. Závěrečné čtení používá existující nezávislý živý snapshot, pokud jej adaptér poskytuje, nikoli jen kandidátní cache.

ROLLBACK_ALL_TD_RESULT.json nově uvádí konečné passes a uchovává původní výsledek v legacy_result. Nemůže zůstat zelený po odmítnutí navazující kontroly. Výjimka obsahuje konkrétní důvody a cestu k důkazu. Osvědčený rodič se naváže na cache bez zvýšení počtu přijatých změn.

## Pokračování běhu

Odmítnuté kandidáty se zkoušejí podle stávajícího backtrackingu. Po prokázané obnově rodiče se použije dosavadní návrat SOFT_REFERENCE_PLATEAU/FINECDF_TD_PLATEAU a běh může pokračovat. Test skutečného controlleru provedl dva takové cykly za sebou. Další integrační test ověřil společně nový rollback a chybu společného skóre ze SAFETYFIX1: kandidát nebyl přijat, rodič byl ověřen a cyklus dostal progress_continue=true, nikoli falešnou konvergenci.

Při skutečné neshodě, neplatném čtení nebo neprokázané obnově se bezpečné zastavení zachovává. Nezavádí se automatické LoadVersion ani přímý zápis OD matic. Tolerance nebyly rozšířeny.

## Ověření a omezení

Hlavní sada: 1 508 PASS + 4 historické SKIP, DIAGFAST: 138 PASS, audit GENFIX2: 18 PASS. Celkem 1 664 jedinečných PASS, 0 FAIL. Nový modul obsahuje 39 regresních případů. Všech 1 512 položek hlavního sběru je pokryto sedmi dokončenými samostatnými běhy bez duplicit. Jediný hromadný běh se zastavil na limitu nástroje a NENÍ vykázán jako PASS. Syntakticky ověřeno 440 Python souborů. Sedm kontrolovaných aktivních/chráněných manifestů souhlasí.

Testy používají skutečné porovnávače a controller, ale simulují Visum/COM a assignment. Živý Windows/PTV Visum nebyl dostupný. Původní a opravená reprodukce jsou uloženy v TDROLLBACKFIX1_EVIDENCE. Starší vývojové zprávy a distribuční soupisy se vztahují ke svým pojmenovaným verzím; aktuální soupis je SAFETYFIX2_FILES_SHA256.json.

Ostatní nálezy dřívějšího auditu, například pokrytí count incidence, fallback konfigurace SupplyMix a parita DIAGFAST 11D, nejsou tímto patchem označeny za vyřešené.
