# Dostupnost prognózních hodnot v nových zdrojových sešitech

**Ano, pro část nynějších fallbacků jsou ve zdrojích ročně označené hodnoty. Především pro 2025 bylo nalezeno 1873 kladných hodnot. Pro chybějící položky 2040–2070 v aktuálních hlavních výpočtových sloupcích platné kladné hodnoty chybějí.** Pro 2040 a 2050 jsou k dispozici některé alternativy ve starších vložených sloupcích.

Audit z 1. 11. 2026 porovnává všechny **4493 buněčné fallbacky** z balíčku V2 `0d99b3e419b9584d55ce488c65ce7da670e57834`, tedy i případ, kdy chybějící zdroj nechává referenční nulu. Každý případ je rok × zóna × atribut. Není to tvrzení, že v těchto souborech chybí všechny prognózy pro daný rok; kontrolovány jsou právě současné fallbacky.

Referenční hodnoty pocházejí z dříve dodaného exportu 2022 z 31. 10. a jeho V2 náhledu, nikoli z nového živého odečtu .ver. Importéry, model ani data V2 se v tomto kroku nemění.

## Přímé hodnoty s příslušným ročníkem

| Atribut 2025 | Kladné hodnoty nalezené místo fallbacku | Z nich číselně odlišné od reference 2022 |
| --- | ---: | ---: |
| NUM_PM | 638 | 585 |
| NUM_PM_SMEAR | 638 | 585 |
| POP_CENTRALITY_TERM | 591 | 581 |
| NUM_VS | 4 | 4 |
| NUM_PUP | 1 | 1 |
| PRENOC_SVK | 1 | 1 |
| **Celkem** | **1873** | **1757** |

Tyto hodnoty mají ověřené přiřazení zóny, význam hlavičky a roční horizont. Jde o doložený obsah zdrojů; audit neprovádí novou validaci prognózní metodiky ani výpočet ve Visumu. Úplný seznam s názvem souboru, listu a adresou buňky je v [DIRECT_POSITIVE_FORECASTS.csv](DIRECT_POSITIVE_FORECASTS.csv).

Příklady:

| Zóna | Atribut | Reference 2022 | Zdroj 2025 | Soubor / buňka |
| --- | --- | ---: | ---: | --- |
| 615 Nitra | NUM_PM | 62 866 | 67 721,1104 | Prognozy_pracovni mista / MS655 |
| 615 Nitra | NUM_PM_SMEAR | 81 148 | 73 531,3434 | Prognozy_pracovni mista / ML655 |
| 642 Horný dvor | NUM_PUP | 155,0379 | 167,7229 | Prognozy_počty obyvatel a žáků a studentů / LU152 |
| 574 Blatné | NUM_VS | 56 | 53,1356 | Prognozy_počty obyvatel a žáků a studentů / MB159 |
| 194 Ulica kpt,Rašu | PRENOC_SVK | 1350,1133 | 1331,5330 | Prognoza_PRENOC / MW195 |

NUM_VS je dostupné pro zóny **303, 324, 574, 642**, NUM_PUP pro **642**, PRENOC_SVK pro **194**. Nalezená hodnota POP_CENTRALITY_TERM u Nitry je 156978 a číselně souhlasí s referencí; samotný nález ročního zdroje tedy neznamená změnu výsledného čísla.

Pro dalších **93 buněk roku 2025** zdroje potvrzují platnou nulu při nulové referenci. Tyto případy neobnovují kladnou hodnotu a jsou oddělené od 1873 kladných nálezů.

## Co zůstává nedostupné

| Rok | Prověřených fallback buněk | Přímá kladná hodnota v hlavním ročním sloupci | Buňky s alternativou v jiné větvi |
| --- | ---: | ---: | ---: |
| 2025 | 3904 | 1873 | 0 |
| 2040 | 117 | 0 | 55 |
| 2050 | 158 | 0 | 55 |
| 2060 | 157 | 0 | 0 |
| 2070 | 157 | 0 | 0 |

Pro 2040–2070 jsou právě chybějící položky v aktuálních výpočtových sloupcích převážně `#N/A`, prázdné nebo nemají sloupec pro daný ročník. Například u Nitry obsahují NUM_PM/NUM_PM_SMEAR 2040–2070 ve zdroji pracovních míst `#N/A`; u přenocování je v příslušných ročních sloupcích také `#N/A`. Nové načtení těchto hodnot samo nenahradí stávající fallback.

Pro NUM_PUP_PLACES a NUM_STUD_VS_PLACES existují i nenulová základní pole, ale nebyl nalezen odpovídající explicitní prognózní ročník. Například základní kapacita škol u Nitry není automaticky novou prognózou 2070. Nedatované základní hodnoty jsou zaznamenané v [UNDATED_BASE_VALUES.csv](UNDATED_BASE_VALUES.csv), nepovažují se za přímou náhradu prognózy. Pro chybějící AV_INCOME 2025 nebyl v těchto čtyřech souborech nalezen ročně označený příjmový sloupec.

Celkové rozdělení: **1873 kladných přímých hodnot, 93 potvrzených nul, 999 chybných/prázdných ročních hodnot a 1528 případů bez explicitního ročního sloupce**. Součet je 4493. Úplné pokrytí je v [FALLBACK_SOURCE_COVERAGE.csv](FALLBACK_SOURCE_COVERAGE.csv).

## Alternativní hodnoty 2040 a 2050

Ve vložených starších sloupcích NUM_PUP_2040/2050 a E_C/E_NC/NE_C/NE_NC_2040/2050 jsou pro domácí vnější zóny **608–618** číselné hodnoty. V aktuálně používaných připojených výpočtových sloupcích pro stejné veličiny je ovšem chyba. Pět veličin × 11 zón = **55 buněk pro každý z roků 2040 a 2050**.

Příklad Nitra:

| Veličina | Alternativní 2040 | Alternativní 2050 |
| --- | ---: | ---: |
| NUM_PUP | 17 388 | 12 056 |
| E_C | 50 988 | 45 107 |
| E_NC | 11 560 | 8 026 |
| NE_C | 25 207 | 23 663 |
| NE_NC | 21 228 | 25 981 |

Část těchto čísel je opakovaně zkopírovaná ve více sešitech; kopie se nesmějí sčítat ani počítat jako nezávislá pozorování. Úplný seznam v [ALTERNATIVE_YEAR_COLUMNS.csv](ALTERNATIVE_YEAR_COLUMNS.csv) proto obsahuje více zdrojových adres na jednu roční buňku. Shodu této jiné výpočtové větve s aktuální prognózní metodikou tento audit nepotvrdil. Je označená `ALTERNATIVE_YEAR_COLUMN_REQUIRES_METHOD_REVIEW`; import nebyl přepnut na tyto hodnoty.

## Zónová identita a problémy zdrojů

V populačním a pracovním sešitu je zdrojové ID někdy textové (`ZONE 403`), zatímco v opravené tabulce ekonomické aktivity jde většinou o číselné R1 NO (`615`). Textové `ZONE 403` je vnější Nitra, R1 zóna **615**, nikoli číselná R1 zóna 403. Mapování bylo navázáno na opravený sešit 2040 přes OSRM_MATRIX_ID a zdrojové id. Jména slouží ke křížové kontrole, ne jako klíč. Sloupce jsou vybírány podle významu a roku; koeficienty K_* se nepoužívají místo počtů pracovních míst.

Ve výpočtovém listu ekonomické aktivity je ale **ID 624 označeno Burgenland**, zatímco R1 reference 624 je **Neusiedl am See**. Tento nesoulad je zachován jako **FAIL kontroly kvality zdroje**, nikoli vydáván za bezchybný vstup. Řádek je vyloučen z ověřených kandidátů. V pomocném širokém listu `Prognoza EA + EN` se navíc `ZONE 1051` / Burgenland vyskytuje dvakrát (řádky 405 a 678); oba nejednoznačné záznamy pro NO 220 jsou z kandidátů vyřazeny a pro NO 624 v tomto listu není jednoznačné pokrytí. Detaily jsou v [SOURCE_IDENTITY_WARNINGS.json](SOURCE_IDENTITY_WARNINGS.json).

## Evidence a rozsah

Primární listy: populační `Prognoza` (hlavička řádek 1), pracovní `PROGNOZA zde` (řádek 2), `opravaPRENOCOVANI` (řádek 1) a ekonomická `opr_Prog E_C, E_nC, nE_C, nE_nC` (řádek 18). Pro alternativy byly zahrnuty i široký list `Prognoza EA + EN` a starší `xxxPRENOCOVANI`. U opakovaných historických hlaviček v širokých tabulkách byl jako primární určen poslední připojený roční prognózní blok; ostatní adresy zůstávají dohledatelné jako alternativy. Regionální vstupy a regresní parametry nejsou samy přímou hodnotou konkrétní R1 zóny.

Čteny byly uložené hodnoty XLSX. Excel se nespouštěl, externí odkazy ani formule se nepřepočítávaly. Z dostupnosti čísla nelze dovodit, že sešity mají plně aktuální přepočet všech vazeb. Audit nerozšiřoval metodiku a nedopočítával chybějící prognózy z regionálních faktorů.

`INPUTS.json` obsahuje ID a SHA všech zdrojů; `SOURCE_CATALOG.json` vybrané hlavičky a pravidla párování. Relevantní tabulkové hodnoty jsou bezeztrátově archivovány jako `SOURCE_TABLES.json.gz.b64`. `audit.py.txt --package .` provede znovu porovnání z tohoto archivu; volby `--uploads` a `--model-sources` slouží pro prvotní čtení dodaných XLSX.

Kontroly v `CHECKS.json` oddělují **integritu analýzy** od **kvality zdrojových dat**. Zdrojový nesoulad 624 zůstává červený a celkový stav je `COMPLETED_WITH_SOURCE_WARNINGS`. Reprodukovatelnost, SHA a rozsah změn jsou ověřeny v `PACKAGE_CHECKS.json`. Živý Visum/COM a runtime testy: **NOT_RUN**, protože jde o čistě čtecí audit.

Další ohraničený krok je zapojit doložené přímé zdroje 2025 a pro dosud chybějící či neověřené položky zachovat schválenou referenci 2022. V tomto kroku nebyly importéry ani prognózní CSV upraveny.
