# R1_15A2 V24917 — LONGMASK FORMULA FIX + SILENT DEBUG (29. 10. 2026)

## Aktuální živý důkaz

Nahraný běh `RUN_20261029_234434_309625` skončil v `BASELINE_FULL_RECOMPUTE`
po ~129 s: `LONGMASK_RESTORE_FAILED_MANUAL_REOPEN_REQUIRED`,
`accepted_count=0`. V tracebacku je přímé `matrix.SetValues(a, False)`
v `r1_15a2_long_post_td_mask_v24917.py`. Změna Python list -> numpy
nepomohla. Preflight/procseq **prošel**, OP17/OP18/OP19/OP20 **jsou aktivní**.

Přiložený `COM_API_PREFLIGHT(20261029-224753).json` potvrzuje:
`MATRIX_VALUES:9301` .. `MATRIX_VALUES:9306` mají
`DATASOURCETYPE='FORMULA'`. `M9111..M9115` mají `'DATA'`.
PTV Visum 2026 nedovoluje přímé přepsání hodnot formula matrix; pouze
přepis její formule nebo převod na data matrix (jiná metodika).

**Pozor:** aktuálně chybí skutečný live `DATASOURCETYPE` pro jednotlivé
`9291..9295`. Není poctivé tvrdit, že jsou datové nebo vzorcové.
Nová implementace to před každou transformací čte přímo z Visumu.

## Opravené LONGMASK chování

- `9111..9115` se násobí OSRM 9697 maskou `>=80 km` (bez horní meze),
  ztracený objem se **nenormalizuje**.
- Po 20A/20B provede `apply_group()` **před prvním zápisem**
  live `DATASOURCETYPE` audit všech `9291..9295,9305`.
- Je-li `929x=DATA`, nezakázaná vozidla se ponechají a short support se
  vymaže v těchto datových maticích. Je-li `9305=FORMULA`, **nikdy se
  do ní nezapisuje**; musí se přepočítat z upravených komponent a
  následně projít přesným readback/parity/support testem.
- Je-li nějaká `929x=FORMULA` a obsahuje nepovolené pod-80km cesty,
  **neprovádí se žádný zápis do 929x ani 9305**, nedochází k poškození
  working copy a vznikne `LONG_MASK_RESULT.json` s číslem matice a
  nevyhovujícím objemem. Stav je
  `FORMULA_COMPONENT_REQUIRES_NATIVE_SUPPORT_NO_WRITES`.
  Je pak nutné rekonstruovat její vzorec / native 20B postup; pouhé
  `SetValues` na vzorcové matici nelze opravovat další konverzí typu
  argumentu. Nesmí se potichu vypnout >=80km maska.
- Při zápisu datové matice se provádí readback, na chybě rollback s
  kontrolou formulového agregátu po návratu komponent. Nedošlo k trvalé
  změně zdrojového `.ver`; nic se nenahrává do produkce.

## SILENT start

Spusť ve Visumu 2026 v otevřeném originálním `R1_novy_start.ver`:
`01_SPUSTIT_V24917_TDJOINT1_SILENT.py`.

Stejný výpočet jako `01_SPUSTIT_V24917_TDJOINT1.py`;
žádná změna 100-cyklové kalibrační matematiky, IPF tolerancí, acceptance
ani ochranných limitů. **Silent znamená:** Python stdout/stderr i traceback
se uloží do průběžně flushovaného logu, exception se zachytí, nestane
se z ní falešný úspěch a nevyskočí hostitelský Python traceback.
Neznamená to, že lze potlačit interní modální dialogy Visumu při samotné
nativní proceduře (tyto programový wrapper neovládá).

V adresáři vedle zdrojového `.ver` vznikne:
`R1_15A2_SILENT_DEBUG/SILENT_LATEST.json`,
a pro každý běh `SILENT_<timestamp>.log`,
`SILENT_<timestamp>_STATUS.json`,
`SILENT_<timestamp>_DEBUG.zip`.

ZIP obsahuje popis chyby, chvost Python logu a jen vybrané relevantní
`RUN_STATUS`, `00_RESULT`, `LONG_MASK_RESULT`, `LONG_MASK_EXECUTION_PLAN`
a související JSON/TXT bez obrovských matic. Poslední balíček stačí
přiložit do další konverzace místo 20 souborů.

**Důležité:** není potvrzen živý PASS ve Windows COM. Před dalším
dlouhým během je třeba ověřit zejména `BASELINE_FULL_RECOMPUTE`.
Pokud vyjde `FORMULA_COMPONENT_REQUIRES_NATIVE_SUPPORT_NO_WRITES`,
je to přesný metodický blocker, nikoli chyba tichého spouštěče.

Oficiální dokumentace (Visum 2026):
https://cgi.ptvgroup.com/vision-help/VISUM_2026_EN-DE/en-us/Content/2_Nachfrage_modellieren/2_3_Formelmatrix%20bearbeiten.htm
