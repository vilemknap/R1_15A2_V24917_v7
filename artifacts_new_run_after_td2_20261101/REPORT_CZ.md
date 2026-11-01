# Nový běh po přerušení TD: audit dodaných výsledků

Pouze čtení, 2026-11-01. Tato větev archivuje důkazy, není novou verzí kalibrátoru. Kód a oba runtime/release manifesty zůstávají beze změn proti `dd140a065c02675ad1b00e96fb917e66954af581`. Tento commit je základ balíčku auditu, nikoli doklad skutečně instalované živé verze. Visum/COM nebyl spuštěn.

## Dva odlišné běhy

- `RUN_20261101_012423_535520`: první z dodaných C1, C2, C3, C4 a RUN_STATUS. RUN_STATUS obsahuje přesné kopie těchto čtyř záznamů. C1→C2→C3→C4 mají spojité stavové hashe. C2 TD bylo přijato. Tento běh skončil v C4 chybou `LONG_INCIDENCE_ASSIGNMENT_BINDING_STALE_OR_MISSING`, po přijaté Generation a SupplyMix. Stav vyžadoval ruční otevření přijatého checkpointu, protože `live_matches_last_accepted=false` a `final_state_verified=false`.
- `RUN_20261101_113344_232959`: druhý dodaný C1 a samostatný GENERATION_BLOCK_RESULT pro C2. SupplyMix C2 je navázán přes přesnou shodu celého `objective_before` s `objective_after` Generation C2, stejný referenční hash a shodný původ path epochy. Plán STEP1 odpovídá prvnímu pokusu Generation C2. V tomto balíku není RUN_STATUS nového běhu ani výsledek jeho TD C2.

Popis uživatele uvádí přerušení TD C2; starý RUN_STATUS ale dokládá chybu C4. Bez dalšího důkazu tyto události nelze ztotožnit. Starý FAILED status nepopisuje stav nového běhu. Samotný název `DEMAND_CYCLE_01_RESULT.json` nestačí k přiřazení běhu.

## Nový běh: poslední doložený stav

| Stav | Vážený GEH CAL | Model/obs | GEH <5 | GEH <10 | GEH ≥20 | GEH ≥30 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Start | 19,3203 | 0,9360 | 59 | 102 | 88 | 59 |
| Po Generation C1 | 19,6305 | 0,9571 | 62 | 101 | 88 | 58 |
| Po Generation C2 | 19,0872 | 0,9391 | 69 | 102 | 91 | 57 |
| Po SupplyMix C2 | **18,8375** | **0,9410** | **68** | **103** | **90** | **56** |

CAL má ve všech čtyřech stavech 247 profilů a stejnou referenci cíle. Součty profilových průjezdů nejsou počtem unikátních cest. Celkový zisk GEH proti startu nového běhu je **2,4988 %**. Nejzávažnější skupiny se počtem nevyvíjejí všechny stejně: proti startu zůstávají dva profily navíc s GEH ≥20, zatímco skupina ≥30 klesla o tři.

Generation C1 první návrh odmítla (GEH 20,6963). Druhý, `MEASURED_ZONAL_REFIT`, přijala přes `EARLY_EXPLORATION_NONMONOTONIC_SEVERITY_TRADEOFF`. Zhoršení GEH bylo **1,6056 %**, v evidovaném rozpočtu do 2 %. Počet GEH ≥30 klesl z 59 na 58, což splnilo jednu větev tradeoff podmínky. Kontinuální `severity20` ale narostla z 245,9534 na 256,2530 (+4,1876 %) a `severity30` z 137,0328 na 143,1332 (+4,4518 %). Počet GEH ≥40 vzrostl 32→35. Výjimka tedy neznamená zlepšení celé severity. `shared_objective_monotonicity_bypassed=true` je v rozhodnutí výslovně zaznamenáno; nejde o srovnání s jiným rodičem nebo o nenápadnou změnu reference.

Generation C2 přijala první návrh, scale 1, 2693 řádků, GEH zlepšení **2,7675 %**, assignment gap **0,00147436**. Predikovala GEH 19,3860, skutečný výsledek byl 19,0872. `rho_measured=0,5110` je projekční poměr vektorů změn toku, nikoli poměr zisků GEH.

## SupplyMix C2

| Pokus | Maximální změna ADDVAL1 | Hrany | Vážený GEH | Výsledek |
| --- | ---: | ---: | ---: | --- |
| 1 | ±4 / ±40 s zobecněného nákladu | 36 | 19,0181 | Zamítnut: severity, chráněné profily, společný cíl |
| 2 | ±3 / ±30 s | 31 | 18,9773 | Zamítnut: severity a chráněné profily |
| 3 | ±2 / ±20 s | 19 | **18,8375** | **Přijat v aktuálním modelu** |

Zlepšení SupplyMix vůči jeho rodiči je **1,3082 %**. Doba bloku **1483 s = 24 min 43 s**; přijatý assignment gap **0,00096275**. V evidenci je skutečně politika 24 skupin / 240 hran / nejvýše 4 pokusy. Limity nejsou povinnost využít všechny skupiny ani hrany. Po přijetí třetího kandidáta se čtvrtý nezkoušel.

## TD, LONG a restart

TD C1 nového běhu má `TD_SKIPPED_BY_RUN_POLICY` / `NOT_DUE`, což odpovídá kalibraci jednou za dva cykly. Native TD v realizaci TG zůstává součástí výpočtu. Doklad dokončení TD C2 chybí; nelze tvrdit jeho přijetí, pád ani právě probíhající činnost podle současného okna Visumu.

Starý traceback vede přes `r1_15a2_td_joint_runtime_v24917.py:realize` → `long_composite_td.require_live_ready` → `long_incidence_read._require_binding`. Tato kontrola porovnává aktuální assignment/mutation epochu, skim hash, assignment token a pořadí zón s vazbou uloženou po assignmentu. Chyba potvrzuje chybějící nebo odlišnou vazbu při kontrole realizace LONG; samotný traceback nedokládá, které pole se změnilo ani proč. Nelze z něj odvodit chybnou masku nebo poškozenou SQLite databázi. Aktuální SupplyMix rovněž mění nabídku před TD, proto je další důležitý výsledek TD C2 a jeho kontrola aktuální vazby LONG. Bez těchto důkazů nelze prohlásit problém za opravený.

LONG guard Generation C2 má `long_generation_permitted=true`, ověřený FineCDF a nulový objem pod 80 km; současně `changed_long=false`. Toto přijetí tudíž opět není důkazem zónové kalibrace LONG. Blok stále hlásí `ls_search_incomplete=true` a nepotvrzuje stationaritu. Zapnutý přepínač sám nezaručuje návrh LONG změny.

Poslední přijatý checkpoint starého běhu je `ACCEPTED_A_0005_87d938018db7.ver`, uložený v jeho `CALIBRATION/CHECKPOINTS`, s váženým GEH 19,2425. Nový start má 19,3203. Dodané soubory neobsahují novou preflight/restart autoritu ani sémantické hashe nového baseline; přesné načtení tohoto checkpointu proto nelze prokázat ani vyvrátit. Rozdíl GEH sám o sobě nedokazuje ztrátu parametrů. Nový C1 začíná vlastní baseline a vlastní referencí; součty normalizovaných cílů z různých běhů se nesmějí přímo porovnávat.

## Ověření a další hranice

`analyse.py.txt` reprodukuje kontrolu přesných archivovaných vstupů, 10 SHA-256, oddělení běhů, návaznost stavů/cílů/epochy, přijetí pokusů a aktivních rozpočtů. Výsledek: **32 kontrol PASS**, viz `CHECKS.json`. Výstupy jsou v `SUMMARY.json`. Vstupy jsou bezeztrátové gzip/base64; jejich původní názvy, ID, velikosti a SHA jsou v `INPUTS.json` a duplicitní názvy mají jednoznačné prefixy.

Příkaz pro zopakování z tohoto adresáře: `python analyse.py.txt --package .`. V projektu nebyl změněn žádný produkční soubor. Runtime testy a živý Visum: **NOT_RUN**, odpovídá čistě čtecímu auditu. SHA a diff balíčku jsou doplněny v `PACKAGE_CHECKS.json` a `ARTIFACT_SHA256.json`.

Další ohraničené ověření: výsledek `DEMAND_CYCLE_02_TD_FINECDF/TD_FINECDF_BLOCK_RESULT.json` a RUN_STATUS **nového** `RUN_20261101_113344_232959`. Do běžícího kódu ani modelu tento audit nezasahuje.
