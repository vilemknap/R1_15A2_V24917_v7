R1 2022 - FINE IDP CDF AUTOMATICKA KALIBRACE B/C - v1.7 PATCHED, SILENT
====================================================================

VYCHOZI STAV POTVRZENY UZIVATELEM
--------------------------------
RESULT.json z opravneho skriptu uvadi:
  status: APPLIED_READBACK_VERIFIED
  opraveno 1361 bunek v M9001 a 2041 bunek v M9697 = 3402.
  nezmenene hodnoty mimo patch maji maximalni rozdil 0.
  no_procedures_executed: true
  no_OD_matrices_modified: true

Pouzij pouze ulozeny opraveny model:
  OSRM_AMDY_INPUTS_PATCHED_TD_STALE.ver
ze slozky:
  %LOCALAPPDATA%\R1_OSRM_M9001_M9697_FINAL_PATCH\RUN_20261016_022055_090476

NEOTVIREJ PREDCHOZI PUVDNI .ver jako vstup tohoto kalibratoru.

CO TED PROVEDE v1.7
-------------------
1. V aktualnim modelu PTV Visum kontroluje vsech 3402 opravnych bunek
   M9001/M9697 podle pevne zabudovane autority OSRM/AMDY.
   Pred jakoukoli modifikaci modelu overi, ze diagonaly i mezizonalni
   casy/vzdalenosti jsou kladne. Neprojde-li kontrola, abort BEZ TD.
2. Vykona 1 x native Trip Distribution jako NOVY BASELINE. To je dulezite:
   predesle OD matice ulozene v opravenem .ver jsou STALE (zastarele).
   Zadne rucni spousteni TD pred kalibraci neni potreba.
3. Dale optimalizuje pouze b,c (16 komponent) proti IDP 512bodovym
   CDF pro 11 WORK/SERVICE/SCHOOL komponent a 512bodove prijate
   zamrzle LONG 12b smesi. Prumerna vzdalenost je pomocne kriterium.
   Puvodni 6bin a LONG 10bin histogramy jsou kontrolni diagnostika,
   nejsou primarnim optimalizacnim cilem.
4. Kazdy vyhodnoceny krok je proveden v nativnim TD Visumu.
   Chybne kroky vraci zpet, kontroluje ochranu vstupu a v ramci limitu
   pokracuje. Nejlepsi prijaty stav ulozi do noveho .ver.
5. Srovnani FINAL_VS_INPUT.csv nyn i porovnava pouze novy native
   baseline z opravenych impedanci a konecny kalibrovany stav;
   NIKOLI stare OD matice pred opravou Senice a AMDY diagonaly.

CO SE NEMENI
-------------
  - P/A, a, FOREIGN (M9116), sit, konektory
  - puvodni 512bodove IDP targety, LONG 12b vahy
  - impedance M9001 a vzdalenosti M9697 (jen kontrola, nikdy zapis)
  - dalsi procedury: TG, realization, smart-sym, assignment, 14A/14B

JAK SPUSTIT
-----------
1. Ukonci predchozi kalibrator, over ze zadny script stale nebezi.
2. Otevri OSRM_AMDY_INPUTS_PATCHED_TD_STALE.ver ve Visumu 2026.
3. Scripts > Execute script file:
      R1_BC_AUTO_DIST_ONLY_FINECDF_PATCHED_v1_7.py
4. Pockej na dokonceni. Skript nema vlastni informacni pop-up okna.
   Native zavazne chyby Visumu ale automaticky nepotvrzuje.
5. Pro stav a prubeh otevri v Pruzkumniku:
      %LOCALAPPDATA%\R1_BC_AUTO_DIST_RESULTS
   V nejnovejsim RUN_... jsou:
      00_STATUS.txt
      00_MASTER_SUMMARY.json
      02_PATCHED_INPUT_PREFLIGHT.json
      BASELINE/COMPONENT_FINE_CDF.csv
      FINAL/COMPONENT_FINE_CDF.csv
      FINAL_VS_INPUT.csv
      FINAL_PARAMETERS.csv
      FINAL_DISTRIBUTION_ONLY.ver
   Vedle RUN_... je soubor RUN_..._EVIDENCE.zip pro dalsi audit.
6. Uspesna kontrola opraveneho vstupu:
      02_PATCHED_INPUT_PREFLIGHT.json:
      "status": "VERIFIED_PATCHED_AMDY_OSRM_INPUTS"
   Uspech optimalizacniho behu je v 00_MASTER_SUMMARY.json;
   samotny status COMPLETED neni dukaz absolutni shody s IDP.

RIZENY STOP
-----------
Vloz prazdny STOP.txt do aktivni slozky RUN_... a pockej na bezpecne
ukonceni mezi nativnimi TD vypocty. Nikdy nasilne nezavirej Visum
behem zapisovani TD vystupnich matic. Pokud po padu zustane
R1_BC_AUTO.lock, odstran az po overeni, ze kalibrator nebezi.

OMEZENI VALIDACE
----------------
- 42 lokalnich testu: 7 IDP autorita, 6 tiche logovani/soubory,
  19 regresnich testu automaticke kalibrace (mock Visum COM),
  10 patch authority a fresh-baseline pravidla.
- Z toho zadny nebyl ostrym behum COM ve skutecnem PTV Visum 2026.
- Casove limity: 4 h / max 180 TD vyhodnoceni / max 35 iteraci.
- Skript zachovava bezpecnostni guardy; neodstranuje je.
- Intrazonalni vzdalenosti AMDY zustavaji schvalenym modelovym
  odhadem (polomer ekvivalentniho kruhu), ne pozorovanou delkou cesty.
- Po kalibraci nasleduje samostatne downstream zpracovani. Nova
  TD distribuce jeste neni hotovy vozidlovy/asignacni scenar.
