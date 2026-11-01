# Přijaté TD02 a dnešní pracovní dodávka

Audit 2026-11-01, pouze čtení. Běh `RUN_20261101_113344_232959`. Čtyři nové vstupy jsou archivované přesně v gzip/base64, jejich ID, velikosti a SHA jsou v `INPUTS.json`. Navazují na předchozí audit v `artifacts_new_run_after_td2_20261101`. Produkční kód ani manifesty nejsou změněny; GitHub základ tohoto auditu je `39489064bf58b68af1d391afdace658a7c359aeb`.

## Výsledek

**TD02 bylo přijato v plném kroku 1,0**, `ACCEPTED_FINECDF_TD`, `td_realization_complete=true`, assignment gap **0,00080873**, bez uvolnění IPF tolerance. Samostatný TD výsledek je přesnou kopií položky `td` z výsledku celého cyklu. Stavový hash na obou místech: `3b7afe0b9ced0c93a679dcffe9a088c8a3107f95acf59cab182b928ffbe3c58e`. Diagnostický hash: `ea61aade0301ba74c650d64389e648facabfdfefe630e5f684001546559b0e38`.

| Stav | Vážený GEH CAL |
| --- | ---: |
| Nový baseline | 19,3203 |
| Po Generation C1 | 19,6305 |
| Po Generation C2 | 19,0872 |
| Po SupplyMix C2 | 18,8375 |
| Po aktualizaci impedance před TD | 18,9551 |
| Po přijatém TD C2 | **19,0273** |

Zhoršení samotného TD vůči jeho rodiči je **0,38085 %**. Celý navazující krok od konce SupplyMix zahrnuje také samostatnou aktualizaci impedance; nelze celý rozdíl 18,8375→19,0273 připsat změnám b/c. Konec cyklu je proti startu nového běhu lepší o **1,5167 %**.

TD blend má váhy 0,60 GEH / 0,40 IDP. Jeho IDP kleslo **0,4651259632→0,4471850190**, tj. o **3,8572 %**. F = **0,9868561943**, pod limitem 0,999, a IDP poměr 0,96143 je pod 1,25. Tato IDP hodnota není prostý průměr komponentových `mean_primary_error` ani cílová metrika pouze vybraných komponent. Vybrané komponenty zlepšily svou vlastní váženou metodu 0,5574664→0,4745434, tj. 14,8750 %; tyto různé metriky se nesmějí zaměňovat.

Konec cyklu má 247 CAL profilů, model/obs **0,891879**, GEH <5: **65**, GEH <10: **95**, GEH ≥20: **85**, GEH ≥30: **61**. Součty profilových průjezdů nejsou počtem unikátních cest. Pokles poměru model/obs sám nedokládá úbytek celkové poptávky.

## Přijaté parametry a rozsah hledání

| Komponenta | Přijatá změna |
| --- | --- |
| WORK_noE_noC | b: 2,7529631705→2,7029631705; c beze změny |
| SERV_E_C | c: −0,2324374229→−0,2611666884; b beze změny |
| SCHOOL | c: −0,3618489367→−0,3220442655; b zůstává 0 |

SCHOOL TD je tedy skutečně aktivní a v tomto kroku má přijatou změnu. LONG_COMPOSITE byl aktivní s `READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE`, assignment epoch 67. Žádná LONG změna b/c nebyla přijata. Ve vložené obecné specifikaci je ještě historický stav `READY_FOR_LIVE_PROOF_NOT_YET_CERTIFIED`; pro tuto realizaci je rozhodující novější vnořený měřený readiness záznam. Úspěšný TD02 prokazuje průchod touto kontrolou v tomto kroku, nikoli opravu všech příčin historické chyby assignment bindingu.

Blok trval **3972,283 s = 66 min 12 s**. Má 56 TD vyhodnocení, 3 iterace a 2 dokončené polls. Časy v TIMING jsou vnořené a nesmějí se sčítat. `search_complete=false`, `stationarity_confirmed=false`, důvod obálky `LONG_SCHOOL_DESIGN_UNVERIFIED`; TDJOINT ukončilo hledání na `TD_EVALUATION_BUDGET`. Jde o přijatý dílčí pracovní stav, nikoli dokončenou kalibraci. `completed=false` celého cyklu zde neznamená, že selhala realizace TD.

## Volba souboru pro dnešní scénáře

Zafixovat **přijatý checkpoint po tomto TD02**, nikoli libovolné aktuální uložení Visumu, pokud už pokračuje cyklus 3. Příslušný ukazatel je v:

`RUN_20261101_113344_232959/CALIBRATION/LATEST_ACCEPTED_CHECKPOINT.json`

Dodané čtyři soubory neobsahují cestu k checkpointu ani SHA jeho .ver payloadu. Konkrétní název .ver proto nelze poctivě uvést. Název obsahuje náhodný token, který se nesmí odhadovat ze stavového hashe. V kontrolovaném zdrojovém řetězci se přijatý checkpoint publikuje před zápisem výsledku cyklu; samotné payload soubory na uživatelově počítači zde ale nebyly ověřeny. Ukazatel se při dalších přijatých stavech přepisuje a dva sloty rotují, takže zvolenou .ver, její `.semantic.json` a metadata je vhodné zachovat jako samostatnou pracovní kopii pro dodávku.

Pokud už LATEST odkazuje na pozdější krok, musí se podle uložených checkpointů, sémantických metadat a příslušného stavu dohledat právě hranice TD02. NPZ `BEST_STATE` vnitřního solveru není celkový přijatý checkpoint a `BEST_SO_FAR` může odpovídat jinému kroku. V tomto auditu nebylo nic načteno do Visumu ani zastaveno.

## Navazující postup pro pracovní dodávku

1. Vybrat a zálohovat výše uvedený checkpoint TD02; zaznamenat název, SHA, diagnostiku, schéma zón a parametrů. Pro dnešní balík z něj udělat neměnnou výchozí kopii.
2. Do samostatných scénářů **2025, 2040 a 2070** přenést kalibrační parametry, podle skutečných NO zón a jednoznačných identit komponent a směrovaných hran. Zachovat vlastní síť, socioekonomiku a scénářové vstupy každého roku. Zónové koeficienty, nativní TD parametry a aplikovatelné změny ADDVAL1 přenášet s kontrolou zpětným čtením; konflikty/nenalezené objekty vypsat, ne mapovat podle pořadí. Případné kalibrované intrazonální parametry jsou také součástí předávaného stavu. Nekopírovat skimy, uložené cesty ani OD matice 2022 jako hotovou prognózu.
3. V každém roce znovu spočítat jeho vlastní **TG → jednotné TD → LONG maskování osobních matic → 20A/20B → maskování LONG vozidlových složek a agregace → assignment → skimy** v existující schválené proceduře. Pevná OSRM autorita, pořadí zón a LONG ≥80 km podpora musí odpovídat příslušnému modelu. Aktualizovanou síťovou impedanci pro budoucí rok odvodit z jeho sítě a výpočtu, nepřebírat slepě z modelu 2022.
4. Převést **RPDI na den/večer/noc** podle dodané schválené autority a tříd vozidel. Neodhadovat podíly ani délky období. Je nutné určit, zda odevzdáváme objem za celé období, nebo průměrnou hodinovou intenzitu: `Q_období = RPDI × podíl`; `q_hod = Q_období / počet_hodin`. Pro úplné rozdělení se podíly musejí sečíst na 1. Pokud autorita používá přímo hodinové faktory, respektovat jejich jednotky. Rozdělení OD před periodickým assignmentem a přepočet již přiřazených síťových intenzit jsou různé postupy; výběr závisí na požadovaném výstupu.
5. Vyexportovat podle potvrzeného formátu OD/síť/GIS/tabulky, s názvem roku, scénáře, vozidlové třídy, období a jednotky. Ověřit rozměry, pořadí zón, nezápornost, konečné hodnoty, součty, LONG podporu a úspěšný assignment. Je-li rozdělení úplné, ověřit návrat součtu den+večer+noc na RPDI, případně součet hodinově převážených intenzit. Přiložit manifest souborů a stručný popis omezení.
6. Odevzdat jako **dílčí pracovní výsledky založené na přijatém TD02**, s uvedením nedokončené konvergence a dosud nepřijaté LONG změny. Odeslání příjemci teprve podle určeného cíle; tento audit žádné soubory příjemci neposílá.

Pro skutečné zpracování ještě chybí přesný checkpoint, dostupnost modelů tří let, schválené převodní koeficienty a délky období včetně jednotek a požadované formáty exportů. Ve zkoumaném aktivním balíku nebyl identifikován hotový scénářový exportní řetězec pro tuto konkrétní dodávku. Dotaz na tyto podklady již uživatel dostal; žádná metodika nebyla doplněna odhadem.

## Ověření

**30 kontrol PASS**, viz `CHECKS.json`, včetně 7 SHA vstupů (4 nové a 3 navazující), shody celých TD záznamů, state/diagnostic hashů, předchozích Generation a SupplyMix, akceptačního vzorce i bran. Reprodukce: `python analyse.py.txt --package .`. `SUMMARY.json` obsahuje přesná čísla. Kontroly balíčku jsou v `PACKAGE_CHECKS.json`, SHA souborů v `ARTIFACT_SHA256.json`.

Runtime testy a živý Visum: **NOT_RUN_READ_ONLY_AUDIT**. Scénářové matice a finální exporty zde ještě nebyly vyrobeny. Produkční soubory a manifesty zůstaly shodné se základem.
