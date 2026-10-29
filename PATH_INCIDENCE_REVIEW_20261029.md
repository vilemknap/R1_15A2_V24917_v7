# Kontrola a optimalizace path incidence — 2026-10-29

Výchozí GitHub commit `2912556cd12e9eb229d4731d92701e913cc628a8`, lokálně totožný strom `d84f8a9ece8337087e0ac37ce48b0051edc291fa`. Rozsah: W/S řídká incidence, LONG společná cache a zonální efektový model, čtecí snapshoty a přesně kompatibilní hashování. Živý Visum nebyl spuštěn.

## Opravy

- W/S už nesmí odříznout přebytek při různých délkách row/col/value ani ignorovat neplatné indexy. Nový společný validátor ověřuje délky, rozměry, rozsah, celočíselnost a konečné nezáporné hodnoty. Existující numerický test nyní pracuje s platnými vstupy; oddělené regresní testy vyžadují odmítnutí poškozených dat.
- LONG už nezaokrouhluje zlomkové sparse/profile/link indexy. Odmítá také duplicitní OD katalog, necelou či nekladnou násobnost v SQL a nepřípustný intrazonální profilový průchod. Na původním commitu byly nezávislým skriptem reprodukovány tři případy přijetí vadných dat.
- Velký platný OD katalog mohl selhat kvůli chybě postupného součtu `+=`. Používá se `math.fsum` a stejná relativní/absolutní numerická smlouva jako u kontroly marginálních součtů. Materiálně chybný objem je stále odmítnut.
- Změna SQLite dat nebo profilu během čtení a mezi návrhem a aplikací je detekována. Zůstává zachované vlastnictví backtrackingu a přesná obnova parametrů rodiče.
- Snapshot ověřuje, že ItemByKey vrátil skutečně požadované číslo matice. Převzatá pole se nepoužijí z částečného neúspěšného pokusu; retry začíná s prázdným lokálním sběrem.

## Implementované optimalizace

1. LONG SQL OD/profile podíly se zpracují do jediné kompaktní neměnné báze na aktivní cache. Další čtení přepočte pouze aktuální OD objemy v NumPy. Rozhoduje identita spojení, `total_changes`, `data_version`, `schema_version`, zdrojový rodič, zóny a profilový katalog. Změny jiné SQL connection i vlastní connection invalidují bázi; živé matice ani toky se mezi voláními nesdílejí. Ve vzorku zabírá báze 5 510 088 bajtů, nenarůstá seznam starých verzí.
2. LONG sestavení husté efektové matice G používá NumPy scatter `add.at`, který správně sečte opakované položky a zachová pořadí sčítání. Nová matice G se v testech i benchmarku přesně rovná původní skalární implementaci.
3. Hashování běží po blocích 4 096 buněk. Protokol zůstává přesně stejný: rozměry a text `float.hex` každé buňky se středníkem v pořadí C. Testy zahrnují podepsanou nulu, subnormální/extrémní hodnoty, F layout a řezy. Nejde o změnu hash autority.
4. Pole právě načtená striktním snapshotem lze použít uvnitř stejné fáze LONG čtení. Používají se vlastní kopie; chybějící pole se načtou běžnou čtecí cestou. Nezávislé čtení PŘED/PO zůstává. V obvyklé konfiguraci se tak neopakuje GetValues M9305 dvakrát v jedné fázi; pokud snapshot zahrnuje i 9291–9295, sdílejí se i ty. Testy prokazují dvě živá čtení každé matice za celé před/po ověření.

## Naměřený offline přínos

Syntetický vzorek: 681 zón, 248 profilů, 75 000 OD, 300 000 řídkých položek pro G. Medián ze tří měření:

| Operace | Před | Po | Poměr |
| --- | ---: | ---: | ---: |
| Sestavení LONG G | 0,4520 s | 0,1753 s | 2,58× |
| Hash jedné matice 681×681 | 0,2229 s | 0,1284 s | 1,74× |

Opakovaná SQL agregace 75 000 profilových OD položek trvala 0,3538 s; při platné připravené bázi se obě GROUP BY vůbec nespouštějí. První kompilace báze stála 0,4534 s. Čas rychlého přístupu k bázi není časem celého LONG capture. Hodnoty nejsou zrychlením assignmentu, skutečného COM ani celého kalibračního cyklu.

## Důkazy a hranice

121 cílených testů; celá hlavní sada 1884 prošlo, 4 přeskočené; DIAGFAST 138 a audit 18. Použita pevná krátká dočasná cesta pytestu, stejně jako v předchozím ověření kvůli syntetickým Windows MAX_PATH testům. Beze změny zůstalo 1059 chráněných původních souborů. Runtime manifest má 72 položek, DIAGFAST release manifest 133.

Podrobné příkazy, návratové kódy, SHA a měření: `PATH_INCIDENCE_REVIEW_20261029.json`, `evidence_path_incidence_review_20261029/`. Kompletní source patch a reprodukční/benchmarkové skripty v textové podobě: `artifacts_path_incidence_review_20261029/`.

Zůstává běžný launcher, meze koeficientů, OSRM ≥80 km bez horní meze, živá akceptace, FineCDF a in-memory rollback. Nový kód neprovádí žádné zápisy do modelu. Společné LONG TD b/c se touto kontrolou neodemyká. Skutečné COM a rychlost modelu zůstávají k ověření při běžném živém běhu.
