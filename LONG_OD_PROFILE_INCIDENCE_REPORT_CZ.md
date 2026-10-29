# LONG OD → profil: současná čtecí implementace

Stav k 2026-10-29: `OBSERVED_LONG_OD_PROFILE_ONLY`. Živý Visum v tomto vývojovém prostředí nebyl spuštěn. Výstup popisuje vozidlový tok přiřazený profilům; není derivací `ADD_PROD_L`.

## Výpočet a zdroje

`r1_15a2_long_profile_incidence_v24917.py` používá oficiální uložené trasy `NATIVE_CL`, jejich směrované průchody linkami, výslednou M9305 a pět vozidlových komponent M9291–M9295. Pro každý profil a OD pár sčítá objemy tras krát počet průchodů profilem. Skutečný opakovaný průchod linkou se započte opakovaně; duplicitní export stejné profilové pozice se odmítne. Profily BOTH sčítají oba autorizované fyzické směry.

Komponentový příspěvek vzniká podle aktuálního OD podílu M929k/M9305. Součet pěti složek musí odpovídat M9305 v každé buňce a součet uložených tras musí rekonstruovat všechny kladné mezizónové OD vztahy. Kladné vztahy pod numerickou tolerancí se nezahazují. Intrazonální objem je vykázán odděleně. Neodvozuje se žádná globální obsazenost ani převodní koeficient CL.

## Nová cesta z aktuálního adapteru

`r1_15a2_long_incidence_read_v24917.py` doplňuje čtení z aktuálního modelu. V24917 adapter po svém dokončeném assignmentu a zachycení DIS zaznamená assignment/mutation epochu, token, hash skim epochy a pořadí zón. Samotný záznam neexportuje trasy ani nečte další OD matice.

Explicitní diagnostické API na již používaném adapteru:

```python
# Po běžném assignmentu a diagnostice V24917; žádný nový adapter ani attach.
observed = adapter.long_profile_incidence(diag, audit_folder)
```

`audit_folder` musí být nový nebo prázdný. `diag['d12']['rows']` musí obsahovat právě schválenou CAL sestavu; ověřují se identity i směry vůči `api_approved_observations`. Pořadí řádků se zachová pro návazný W/S fit. Volání není automaticky přidáno do každého kalibračního kroku: čtení velkého `NATIVE_CL` exportu proběhne jen na explicitní diagnostický požadavek.

Čtecí cesta:

1. Vyžádá aktuální, adapterem navázanou assignment/skim epochu. Odmítne probíhající výpočet, chybějící vazbu nebo pozdější mutaci.
2. Načte zónovou osu, M9291–M9295 a M9305 a ověří zdroj OSRM M9697 / `R1_OSRM_DIST_KM`. Vyžaduje již aplikovanou podporu **OSRM ≥80 km bez horní meze**. Při nesplnění sama nic neořezává ani nepřepočítává.
3. Přes stávající `export_actual_paths_and_build_incidence()` exportuje pouze `NATIVE_CL`, s ověřeným bounded COM podpisem a průběžnou redukcí path-link řádků. Nepoužívá persistentní W/S cache a nemění původní `path_export_dsegs` ani `mutable_dsegs`.
4. Ověří OD a komponentovou paritu a porovná rekonstruovaný LONG tok s přímým `VOLVEH_DSEG(NATIVE_CL,AP)` na schválených profilových linkách. Tolerance parity: absolutně 1e-6, relativně 1e-8.
5. Znovu načte všech šest matic a profilové toky; vyžaduje přesnou nezměněnost. Znovu ověří zdroj OSRM, parametrový snapshot, pořadí zón a epochu. Změna znamená chybu, nikoli fallback na staré podklady.

Úspěch zapisuje `LONG_INCIDENCE.npz` bez pickle a `LONG_INCIDENCE_REPORT.json` s SHA archivu, matic a zón, identitou epochy a chybami parity. Archiv obsahuje řídké řádky/sloupce/hodnoty, OD identitu, aktuální objemy, pět komponent, zónové P/A a profilové toky. Zůstávají také CSV důkazy původního exportéru. Při selhání se úspěšný výstup odstraní a vznikne `LONG_INCIDENCE_FAILURE.json`; předchozí neprázdný adresář se nepřepisuje.

## Hranice použití

Čtení nevolá Procedures.Execute, SetValues, LoadVersion ani aktivaci LONG. Zdrojový `source_status` rozlišuje pouze caller-supplied offline vstupy od čtení navázaného adapteru s ověřenou paritou. Testovací COM rozhraní neprokazuje běh ve skutečném Visumu.

`r1_15a2_long_zonal_fit_v24917.py` může dál vytvořit čistý lokální návrh podle principu W/S: `Δq/q ≈ u_origin + v_destination − g_LONG`. Skutečná změna produkčního koeficientu však prochází TG → nativní TD → komponentově a pásmově specifický převod 20A → návratový 20B → současné maskování výsledných LONG matic → assignment. Pozorovaná M929x incidence sama tuto citlivost nedokládá. `long_generation_permitted=False`, `tg_sensitivity_verified=False` zůstávají zachovány.

LONG Generation tedy zůstává zmrazená; kanonická reference je nyní **0,3**, nikoli historických 0,2. Společné LONG TD b/c také zůstává blokované do ověření count-response modelu. Nativní OD filtr už není požadavkem: uživatel zvolil následné násobení LONG matic maskou a přijetí úbytku objemu. FineCDF dál používá čerstvou NATIVE_CL/DIS a podmíněnou cílovou křivku 100–200 km, což není horní mez OSRM podpory.

## Ověření a další hranice

Přesné příkazy, návratové kódy, testové součty a manifestové důkazy jsou v `LONG_INCIDENCE_CURRENT_20261029.json` a `evidence_long_incidence_current_20261029/`. Kompletní diff je v `artifacts_long_incidence_current_20261029/`. Vše je součástí GitHub zálohy této větve.

Dalším samostatným krokem je spustit toto čtení na cílovém PC bezprostředně nad platnou epochou V24917 a posoudit skutečnou paritu. Pro odmrazení zonálního LONG TG bude navíc potřeba samostatně ověřená odezva celé realizační sekvence a její rollback.
