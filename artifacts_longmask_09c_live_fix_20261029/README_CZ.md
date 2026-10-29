# LONGMASK — oprava pádu BASELINE_FULL_RECOMPUTE 29. 10. 2026

**Výchozí větev:** `codex/working-copy-operation-diff-20261029` (SHA `07cdc99f8ccd8a42ef4da970ae1d782c856e7889`).
**Zdrojem závady:** živý `RUN_20261029_224737_496385`, `00_RESULT.json`, `RUN_STATUS.json`,
`00_SUPPLY_ASSIGNMENT_PLAN.json` a `00_V240_ASSIGNMENT_SCOPE.json` poskytnuté uživatelem.
**Status:** `OFFLINE_CODE_PATCHED / LIVE_VISUM_NOT_RUN`. Úplná pytest regrese v tomto prostředí **NEBYLA SPUŠTĚNA**.

## Ověřené symptomy
- `status=FAILED`; `error=LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH`; výjimka na ř. 170 v `r1_15a2_long_post_td_mask_v24917.py`.
- Pád nastal ve `BASELINE_FULL_RECOMPUTE` ještě před prvním cyklem. `accepted_count=0`, `completed_demand_cycles=0`.
- Zdrojová validace `00_SUPPLY_ASSIGNMENT_PLAN` prošla. Ověřuje operaci 20 jako **jedinou** finální autoritu 14 DSeg/GAP.
- Aktivní operace typu 101 v tomto modelu: **17 (LNV,NV)**, **18 (NATIVE_CF,NATIVE_CL)**, **19 (NATIVE_CS/CW včetně noT)**, **20 (finální společná 14 DSeg)**; detail dokládá `00_V240_ASSIGNMENT_SCOPE`.
- Starý LONGMASK obsahoval `if assignments and not set(assignments) <= approved: raise ...`. Rozpor 17/18/19 vs. schválená {20} vyvolal pád.
- Nezávislý jiný start v reportu `artifacts_working_copy_operation_diff_20261029/` dříve vykázal `WORKING_COPY_SEMANTIC_IDENTITY_MISMATCH:operations_hash`; jeho příčina nadále vyžaduje živý `WORKING_COPY_OPERATIONS_DIFF.json`. Tato oprava ho automaticky neřeší.

## Oprava
V `r1_15a2_long_post_td_mask_v24917.py`:
1. Požadujeme existenci všech schválených finálních operací ve skutečně aktivním seznamu, nikoli opačný podmnožinový test.
2. Při výskytu dalších aktivních PrT operací přijímáme pouze přesně známé částečné operace 17/18/19 před schválenou finální 20 a jen s přesnou, normalizovanou shodou `DSEGSET`.
3. Cizí, přidané nebo přeuspořádané operace jsou nadále blokovány. U všech aktivních 101 v 09C jsou ověřeny obě složky: finální i částečné.
4. Rozdělení zůstává `THROUGH_TD` → maska 9111–9115 → `REALIZATION` → maska 9291–9295, přepočet 9305 → `ASSIGNMENT_SKIMS`; odstraněné LONG cesty se nevracejí. Operace 17–20 zůstávají vykonatelné pouze v poslední fázi. Původní ACTIVE hodnoty se po každé fázi obnovují.
5. Do `LONG_MASK_EXECUTION_PLAN.json` přibyla diagnostická pole `final_assignment_authority` a `validated_partial_assignments`.

Přidán `tests/test_v24917_longmask_09c_live_scope_regression.py` pro čtyři skutečné 09C scopes, bezpečné pořadí vykonání, neznámou aktivní operaci, chybějící finální 20, změněný a duplicitní DSEGSET a aliasy `noT`/`NOT`. Testy **nebyly v tomto prostředí spuštěny**.

Aktualizovány SHA256 obsahu `r1_15a2_long_post_td_mask_v24917.py` v obou manifestech `V24917_RUNTIME_MANIFEST.json` a `DIAGFAST_V1_RELEASE_MANIFEST.json`. Nový test uveden v DIAGFAST manifestu. Předchozí historické soubory zůstávají beze změny; po změně obsahu se manifest nesmí vrátit ke starému hashi.

## Bezpečné ověření na vývojovém PC
1. Stáhnout celý ZIP této nové větve, rozbalit do **nové samostatné složky**, bez míchání se starými vydáními.
2. Před Visum zkusit `python -m pytest -q tests/test_v24917_longmask_09c_live_scope_regression.py tests/test_v24917_long_post_td_mask.py` a `python tools/run_genfix2_checks.py --output <mimo_repo>`. Je-li chyba, nespouštět živé Visum.
3. V PTV Visum ručně otevřít původní ověřený model `R1_novy_start.ver`; nenačítat neověřenou pracovní kopii po neúspěšném běhu.
4. Spustit běžný `01_SPUSTIT_V24917_TDJOINT1.py`, neprovádět další dlouhou kalibraci bez ověření BASELINE. Pokud znovu selže změna source/working-copy operací, dodat `WORKING_COPY_OPERATIONS_DIFF.json`.
5. Pokud základní přepočet projde, ověřit `LONG_MASK_EXECUTION_PLAN.json`, `MASK_PERSON_LONG/LONG_MASK_RESULT.json`, `MASK_VEHICLE_LONG/LONG_MASK_RESULT.json`, 9305 a finální GAP 20. Následně jen krátký řízený kandidát s kontrolou rollbacku; teprve pak dlouhý běh.

**Není deklarováno `PASS` pro živý Visum ani plnou testovací sadu.**
