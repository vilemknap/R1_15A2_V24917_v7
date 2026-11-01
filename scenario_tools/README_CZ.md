# Import, přepočet a export scénářů 2025 / 2040 / 2050 / 2060 / 2070

Balík připraven 1. 11. 2026 z přiložených vstupů. Používá **MC_MEAN, po OD buňkách zaokrouhlené na celá vozidla**. Otevřenou verzí musí být samostatná kopie kalibrovaného modelu 2022 pro příslušný rok. Do této kopie se již znovu nepřenášejí kalibrační koeficienty: skripty je zachovají.

## Co spustit ve Visumu

Stáhnout a rozbalit **celý GitHub ZIP**. Zachovat strukturu: složka `scenario_tools` musí zůstat vedle původních `r1_15a2_*.py`. Importér a exportér jsou vlastní nové nástroje; přepočet potřebuje původní knihovny v7 z kořene tohoto balíčku. Ve Visumu se používá stávající objekt `Visum`/`COM`; skripty nevytvářejí další instanci a nevolají `LoadVersion` ani `SaveVersion`.

Jestli ve stejné relaci Visumu zůstaly Python moduly z jiné složky kalibrátoru, přepočet je odmítne jako `PRELOADED_MODULE_FROM_OTHER_PACKAGE`. V takovém případě uložit scénář po importu, znovu spustit Visum a otevřít tuto uloženou scénářovou kopii. Staré moduly se za běhu automaticky nemažou ani nenahrazují. Launchery kontrolují vlastní balík přes SHA; přepočet navíc ověřuje původní runtime manifest.

Pro každý rok:

1. Z přijatého kalibrovaného modelu 2022 vytvořit přes **Save as** samostatnou `.ver` s daným rokem v názvu, například `R1_2040_PRACOVNI.ver`. Každý rok vytvořit zvlášť z 2022, ne postupně přepisováním 2025→2040→2050; jinak by fallback již nebyl referencí 2022. Nespouštět souběžně s kalibrací.
2. **Scripts → Run script file**: `scenario_tools/2040/01_IMPORT_ZONES_AND_FREIGHT_2040.py` (pro jiný rok zvolit jeho složku). Import proběhne ihned po úspěšném preflightu. Výsledek `PASS_IMPORTED` bude v logu a `IMPORT_CURRENT.json`. Uložit vlastní `.ver`, aby existovala kopie před přepočtem.
3. Spustit `02_RECOMPUTE_TG_TD_AND_ASSIGNMENT_2040.py`. Provede původní aktivní TG, jednotné TD, LONG masku osobních matic, 20A/20B, LONG masku vozidlových komponent a existující assignment/skimy. Nepouští další optimalizaci, nemění b/c, ADD_* ani ADDVAL1. Vyžaduje aktivní TG a TD a finální assignment 20; ověří jeho GAP ≤0,005. Průběžné ACTIVE příznaky původní mechanismus vrací zpět. Po `PASS_RECOMPUTED` uložit vlastní `.ver`.
4. Spustit `03_EXPORT_MATRICES_2040.py`. Nový výstup je v téže roční složce pod `EXPORT_<datum_čas>`. Předchozí exporty se nepřepisují. Vyexportují se tři denní matice a `EXPORT_MANIFEST.json`.

| Rok | Importér | Přepočet | Exportér |
| --- | --- | --- | --- |
| 2025 | `2025/01_IMPORT_ZONES_AND_FREIGHT_2025.py` | `2025/02_RECOMPUTE_TG_TD_AND_ASSIGNMENT_2025.py` | `2025/03_EXPORT_MATRICES_2025.py` |
| 2040 | `2040/01_IMPORT_ZONES_AND_FREIGHT_2040.py` | `2040/02_RECOMPUTE_TG_TD_AND_ASSIGNMENT_2040.py` | `2040/03_EXPORT_MATRICES_2040.py` |
| 2050 | `2050/01_IMPORT_ZONES_AND_FREIGHT_2050.py` | `2050/02_RECOMPUTE_TG_TD_AND_ASSIGNMENT_2050.py` | `2050/03_EXPORT_MATRICES_2050.py` |
| 2060 | `2060/01_IMPORT_ZONES_AND_FREIGHT_2060.py` | `2060/02_RECOMPUTE_TG_TD_AND_ASSIGNMENT_2060.py` | `2060/03_EXPORT_MATRICES_2060.py` |
| 2070 | `2070/01_IMPORT_ZONES_AND_FREIGHT_2070.py` | `2070/02_RECOMPUTE_TG_TD_AND_ASSIGNMENT_2070.py` | `2070/03_EXPORT_MATRICES_2070.py` |

Všechny cesty v tabulce jsou relativní ke `scenario_tools`. Pro 2040 například vzniknou `R1_2040_OA_CAL_WORK.mtx`, `R1_2040_LNV.mtx`, `R1_2040_NV.mtx`. Formát je Visum `$O`, směrované OD a jednotka **vozidla/den**. Soubory lze použít pro otevření matic ve Scenario Manageru. Nepřidává se nový DSeg ani pracovní matice do modelu; OA se pro export sčítá v NumPy ze stávajících 12 unikátních komponentních DSeg matic. Název `OA_CAL_WORK` zachovává původní exportní konvenci.

## Zónová data a ochrana kalibrace

Číslo zóny se v Excelu bere z **OSRM_MATRIX_ID**, nikoli z pořadí ani z textového `id`. Je vyžadováno přesně 681 zón NO 1..681. Zápis používá skutečný COM klíč získaný spolu s NO; pořadí matic se bere přímo z kolekce zón. Žádná OD matice se nepřiřazuje podle řádku CSV.

Allowlist surových atributů:

`NUM_VS, NUM_PUP, POP_ZP, E_C, E_NC, NE_C, NE_NC, PRENOC_SVK, AV_INCOME, NUM_PM, NUM_PM_SMEAR, NUM_PUP_PLACES, NUM_STUD_VS_PLACES, POP_CENTRALITY_TERM`.

Kalibrační `ADD_PROD_*`, `ADD_ATT_*`, `ADD_SALARY`, `ZAHR_*`, TD a/b/c, ADDVAL1 i definice operací zůstávají zachované. Koeficienty přítomné v pracovních Excelech se neimportují. Snímek kalibrovaného kontextu brání použití starého přepočtu po ruční změně b/c, nabídky nebo operací.

| Rok | Autorita raw atributů | Fallback buněk |
| --- | --- | ---: |
| 2025 | `2025_zonalni_atributy.xlsx/List1`; AV_INCOME doplněno z pracovního Excelu `vstupy_prod_att` | 3898 |
| 2040 | `vstupy_prod_att_R1`; prvních 9 atributů numericky souhlasí s dodaným připraveným CSV | 1 |
| 2050 | `vstupy_prod_att_R1` pracovního Excelu 2050 | 53 |
| 2060 | `vstupy_prod_att_R1` pracovního Excelu 2060 | 52 |
| 2070 | `2070_zonalni_atributy.xlsx/List1`; shodné numerické vstupy s pracovním Excelem, prázdné buňky mají fallback | 52 |

**Fallback znamená ponechat hodnotu z právě otevřené výchozí kopie 2022, nikoli dosadit nulu.** Pro 2025 zvolený samostatný zonální výpis neobsahuje posledních pět atributů allowlistu: `NUM_PM`, `NUM_PM_SMEAR`, `NUM_PUP_PLACES`, `NUM_STUD_VS_PLACES`, `POP_CENTRALITY_TERM`. Proto zůstává 5×681 = 3405 těchto buněk v referenci 2022; dalších 493 buněk obsahuje chybu, prázdno nebo zápornou/neplatnou hodnotu. Z širšího historického Excelu pro 2025 se těchto pět polí automaticky nepřebírá: například NUM_PM má jiné měřítko než pozdější zpracované R1 tabulky. Je to záměrně omezená pracovní varianta, výslovně zaznamenaná v provenienci.

Každá zachovaná buňka je dohledatelná v `ZONE_SOURCE_FALLBACKS.csv`; konkrétní živá ponechaná hodnota se při importu zapíše do `logs/.../FALLBACKS_KEPT_2022.json`. Živý import nevyžaduje Excel ani openpyxl, používá připravené CSV ověřené SHA. Chybějící atribut v samotném modelu je chyba preflightu; nevytváří se automaticky nový UDA ani se nepřepisuje jeho vzorec.

## Nákladní matice

| Rok | LNV po zaokrouhlení | NV po zaokrouhlení |
| --- | ---: | ---: |
| 2025 | 25 769 | 35 769 |
| 2040 | 30 922 | 43 560 |
| 2050 | 32 951 | 46 530 |
| 2060 | 35 996 | 50 848 |
| 2070 | 40 046 | 56 498 |

Použita je uživatelem potvrzená **MC_MEAN ze ZIPu pro všechny roky**. Samostatné MC_MEAN soubory 2070 jsou stejná varianta; starší samostatné `2040_ROUNDED.csv` se nepoužívají. Každá nezáporná buňka se zaokrouhlí na nejbližší celé číslo, při přesné polovině nahoru (`Decimal ROUND_HALF_UP`). Nic se znovu nevybalancovává ani nepřenásobuje kvůli zachování původního součtu. Původní a zaokrouhlené součty, diagonály, odchylky a SHA jsou v `SCENARIO.json` a `INPUT_PREPARATION_REPORT.json`. Chybějící OD řádky jsou strukturální nuly.

Zapisují se pouze existující DATA matice navázané na DSeg `LNV` a `NV`, případně jednoznačná matice se stejným CODE. Nehledají se podle historického součtu a nepřepíná se DSeg na jiný obsah. Před prvním zápisem se prověří obě matice. Původní hodnoty jsou zálohované do `FREIGHT_BEFORE_BACKUP.npz`. Při chybě zápisu se obnoví i částečně zapsaná matice a ověří se její obsah.

## Přepočet, export a chybové stavy

Přepočet používá původní `r1_15a2_long_post_td_mask_v24917.execute_sequence`, takže LONG maska je **OSRM 9697 / R1_OSRM_DIST_KM ≥80 km bez horní meze**, s povoleným úbytkem objemu. Není přidán samostatný distribuční blok LONG. Zůstává původní jednotné TD a existující nativní přiřazení 17/18/19/20. Matice 9305 se kontroluje proti 9291–9295. Před exportem musí být LONG pod 80 km nulový v osobních i vozidlových maticích.

Pokud selže import, log rozlišuje ověřenou obnovu a `FAILED_ROLLBACK_UNVERIFIED_MANUAL_REOPEN`. Selhání nativní procedury při přepočtu se **nevydává za obnovený model**: nevznikne PASS důkaz, export je blokován a je třeba ručně otevřít uloženou scénářovou kopii. Nepoužívá se `LoadVersion` uvnitř aktivního běhu ani se automaticky nepřepíná na jiný výpočetní postup.

Export vyžaduje úspěšný přepočet z tohoto balíku a shodu otevřené `.ver`, raw i kalibrovaných atributů, b/c, ADDVAL1, operací, zón, nákladních matic a otisků komponentních OD matic. Zastaralé důkazy z jiného importu nestačí. Příprava exportu probíhá v staging adresáři; celá sada se zveřejní přejmenováním až po dokončení všech souborů a manifestu.

LNV/NV se exportují celočíselně; OA má 6 desetinných míst, aby se zbytečně neztrácely drobné osobní OD toky. Manifest obsahuje i součet skutečně zapsaných textových hodnot. **RPDI → den/večer/noc není součástí tohoto balíku**, protože dosud nejsou schválené převodní koeficienty a délky období. Exporty jsou denní. Nevyrábí se soubory pro jiný rok ani automatická duplikace do složky 2022.

## Ověření a zdroje

Offline testy a přesné příkazy jsou v `scenario_tools/validation/CHECKS.json`. Prošlo **29 nových cílených testů**, dále 57 testů stávající LONG masky a 21 testů assignment rozhraní. Plná hlavní sada: **2479 PASS, 4 SKIPPED**; DIAGFAST **189 PASS**; audit **18 PASS**. Sady 57 a 21 jsou podmnožiny hlavní sady, nejde o další nezávislé tisíce testů. Testy pokrývají skutečné vstupy všech pěti let, mapování zón, zachování koeficientů, částečné COM zápisy a rollback, blokaci starého přepočtu, LONG support a atomickou publikaci exportů. Reálný Visum/COM zde není dostupný: **LIVE_VISUM_NOT_RUN**. Úspěch offline mocků není potvrzením živého běhu.

`INPUT_SOURCES.json` obsahuje názvy/ID/SHA přiložených podkladů. Velký `R1_2025_CORDON_LIVE04_2_TRANSFER2025_FULL_20261031.zip` nebyl stažen: přesahuje limit 32 MiB. Tento balík na něm nezávisí. Původní duplicitní skripty 2040 jsou shodné, připravené numerické vstupy jsou malé CSV. Původní velké pracovní Excely se do nového balíku nekopírují; jsou doložené SHA a odvozenými raw daty/proveniencí.

Nové nástroje jsou oddělené od kalibračních launcherů. Původní runtime/release SHA manifesty zůstávají beze změny. Nový obsah má vlastní `SCENARIO_TOOLS_SHA256.json`.
