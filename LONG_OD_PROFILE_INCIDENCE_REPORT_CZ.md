# LONG OD → profil a zonální Generation ve společném řetězci

Stav k 2026-10-29: LONG Generation je zapojená jako lokální návrhový model podle principu WORK/SERVICE. Živý Visum ve vývojovém prostředí nebyl spuštěn. Nejde o analytickou derivaci TG→TD→20A→20B ani o živou certifikaci; přijetí určuje nativní přepočet a stávající ochrany.

## Běžné spuštění

Používá se dosavadní launcher `01_SPUSTIT_V24917_TDJOINT1.py` nebo jeho varianta 60/40 z kompletního GitHub balíčku. Není potřeba samostatný auditní launcher ani ruční zavolání nového API. Baseline a každá Generation automaticky obslouží potřebné podklady a případné odložení LONG zapíše do výsledků běhu. Načtený model musí stejně jako pro W/S poskytovat uložené assignmentové trasy; požadavek není nahrazen syntetickým routováním.

## Společná cache a inline kontroly

`r1_15a2_long_cache_generation_v24917.py` čte již existující SQLite úložiště two-mode cest. Objemy bere samostatně pro `NATIVE_CL`; násobnosti průchodů profily a jejich směry přebírá ze společné geometrie po módech C/C_NOT. Zachovává její označení `PROVISIONAL_SAME_MODE_GEOMETRY_NOT_FULLY_VERIFIED`. Není to dodatečný kompletní export LONG tras.

Pro každé OD spočítá profilový podíl z uložených CL objemů a přepočte jej aktuálním finálním vozidlovým OD z M9305. Stejný princip zmrazené incidence používají W/S pro návrh změny. Zachovávají se opakované průchody linkou a schválené směry profilů BOTH. Současné M9291–M9295 se musí po buňkách sečíst na M9305; podle jejich OD podílů vznikne i komponentový rozklad LONG profilových toků. Nepoužívá se globální CL konverze ani generační dělitel 2,8.

Kontroly probíhají přímo při Generation:

- aktuální assignment/skim/mutation vazba adapteru, přesná zónová osa a kompatibilní kontext sdílené cache;
- schválená CAL sestava a směry profilů, CL zdroj M9305 a dokončená cache incidence;
- kladné OD se skutečným nenulovým podílem tras; kladné mezizónové trasy mají geometrii;
- rekonstruovaný CL profilový tok odpovídá přímému `VOLVEH_DSEG(NATIVE_CL,AP)` v mezích stávající W/S profilové parity; její toleranci LONG neuvolňuje;
- neměnnost šesti LONG matic, profilových toků, parametrů, epochy a OSRM zdroje během čtení;
- podpora OSRM M9697 / `R1_OSRM_DIST_KM` **≥80 km bez horní meze**. Při načítání incidence se žádná matice nepřepisuje.

Chybějící nový kladný OD/podíl nebo nevyhovující profilová parita vyvolá nejvýše jednu běžnou obnovu společné cache ze současného modelu. Současně se znovu sestaví W/S kontext, aby obě větve použily stejný obnovený základ. Při přetrvávající chybě se odloží LONG, W/S/SCHOOL mohou pokračovat; hledání není označeno za úplné.

## Návrh a meze

Po W/S a SCHOOL se na zbývajícím profilovém reziduu řeší LONG zónové log kroky:

`Δq_od/q_od ≈ u_origin + v_destination − g_LONG`.

Proměnné jsou `ADD_PROD_L` a `ADD_ATT_L` v jednotlivých domácích zónách. Normování, ridge a omezený solver vycházejí z W/S. LONG používá tvrdou P/A bilanci a opravu exponenciálních kroků. Zóny bez přímé expozice, strukturální nuly a nepodporované externí zóny se nemění.

- krok nejvýše **+10 % / −10 %** na kandidáta, případně méně podle aktivního LS/stage nastavení;
- produkce: pevná reference **0,3**, pásmo **0,15–0,45**, dále mobilitní ochrany každé zóny;
- atrakce: nakonfigurovaný násobek **0,5–1,5 neměnné počáteční hodnoty běhu**, bez posunu reference po přijatém kroku;
- již existující hodnoty mimo pásmo mohou držet nebo se vracet dovnitř, nemohou se vzdálit více;
- existující LS ridge 0,05; žádné nové survey cíle komponent.

## Apply, accept, reject, rollback

LONG řádky procházejí stejným zapisovacím mechanismem Generation jako W/S. Tím funguje i LONG-only kandidát při nulovém W/S kroku. Před zápisem se ověřuje úplný plán, živá mobilitní autorita a zdroj návrhu; LONG P/A odhad v právě použité škále vstupuje do stávající předaplikační brány. Rozsah kontroly změněných matic Generation je explicitně rozšířen pouze o NATIVE_CL a 9111–9115; FOREIGN ani ostatní bloky se nepovolují.

Každý skutečný pokus dál proběhne přes nativní TG→jednotnou TD→20A/20B→masky LONG→assignment→čerstvé DIS→12D/11D. Zůstávají ochrany count profilů, OSRM podpory, LONG FineCDF, mobility a přijetí kandidáta. Hodnoty nad 200 km jsou podporou povolené; podmíněná FineCDF 100–200 km nadále používá čerstvou NATIVE_CL/DIS.

Snapshot/restore zahrnuje oba LONG koeficienty. Backtracking může znovu použít svůj zmrazený návrh po přesném obnovení rodičovských parametrů; změněný nepříslušný rodič nebo cache je odmítnut. Ověřený rollback a nativní přepočet vlastní stávající controller. Nový kód nevolá LoadVersion, nepíše OD matice a neprovádí vlastní routing. Již schválené násobení LONG matic maskou se nemění.

## Rozsah a důkazy

Tento port zapojuje **LONG Generation**. Společné LONG TD ladění b/c zůstává blokované do svého vlastního count-response modelu; nepoužívá se zde neprokázaný převod finálních vozidel na změnu person TD matice.

Původní `r1_15a2_long_profile_incidence_v24917.py` a explicitní `long_profile_incidence()` zůstávají k dispozici pro samostatnou vývojovou diagnostiku. Běžný Generation řetězec je nepotřebuje volat; používá společnou cache.

Výsledky a přesné příkazy jsou v `LONG_GENERATION_SHARED_CACHE_20261029.json` a `evidence_long_generation_shared_cache_20261029/`. Kompletní patch je v `artifacts_long_generation_shared_cache_20261029/`. Vše je součástí GitHub větve. Offline testy zahrnují SQL incidenci a její přepočet, komponenty, směry/násobnosti, chyby podkladů, omezený fit, nulový W/S krok, obnovu společné cache, skutečný koeficientový setter, rollback parametrů, vlastnictví backtrackingu a controller freeze proof. Neprokazují živý COM běh ve Visumu.
