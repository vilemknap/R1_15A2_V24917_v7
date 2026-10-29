# R1_15A2 V24917: OP17–OP20 a Visum 2026 COM matrix SetValues (29. 10. 2026)

## Podklady a příčina posledního neúspěchu

User log `RUN_20261029_232928_973176`, `00_RESULT(20261029-223321).json`:
- `status=FAILED`, `error=LONGMASK_RESTORE_FAILED_MANUAL_REOPEN_REQUIRED`, `accepted_count=0`, `completed_demand_cycles=0`.
- `PREFLIGHT/00_PREFLIGHT.json: apply_preflight_passes=true`; OP20 `DSEGSET` správných 14 DSeg, `00_PROCSEQ_AUDIT_SUMMARY: passes=true`, pouze OP20 aktivní.
- Zdrojový a pracovní sémantický hash shodně `4c9fefa9e2c8e129b2efa37eae3c34d270253344a44543ec61fb1bfb1d358005`; originální `.ver` nedotčen.
- Skutečná výjimka až uvnitř `BASELINE_FULL_RECOMPUTE` v `r1_15a2_long_post_td_mask_v24917.py:110`, kde se `matrix.SetValues(targets[no].tolist())` pokusilo zapsat LONG výslednou vozidlovou matici (9291–9295, případně 9305). Visum 2026 COM vyvolal `pywintypes.com_error`. Druhý stejný COM zápis při rollbacku potom zakryl původní výjimku jako `LONGMASK_RESTORE_FAILED_MANUAL_REOPEN_REQUIRED`.
- Konkrétní první neúspěšnou matici původní výpis **neuvádí**; příště ji poskytne `MASK_VEHICLE_LONG/LONG_MASK_RESULT.json:failed_matrix_no`.

## Oprava zápisu a rollbacku

`r1_15a2_long_post_td_mask_v24917.py`:
- Zapisovat **dvourozměrné C-contiguous NumPy float64** pole a explicitní `Add=False`: `matrix.SetValues(array, False)`. Toto je doporučený Python/Visum COM kontrakt. Vnořený `.tolist()` už není použit v žádném zápisu ani při rollbacku.
- Po neúspěšné COM operaci nejdříve přečíst matici: pokud je přesně shodná s předchozím stavem, *neprovádět zbytečný další zápis*. Pokud se částečně změnila, obnovit ji a ověřit přesný readback.
- Fail closed při jakékoli neověřené obnově; nezavádět slepé opakování potenciálně částečně úspěšných COM zápisů; zvýšit diagnostiku v `LONG_MASK_RESULT.json`.

**Limity:** Bez běhu na reálném Visumu nelze potvrdit, že konkrétní matice 929x jsou zapisovatelné. Jestliže COM odmítne i pole NumPy, spustit diagnostiku `LONG_MASK_RESULT.json` a dále už nevykonávat dlouhou kalibraci. Pro nezapisovatelnou systémovou matici bude nutná metodicky samostatně auditovaná korekce v nativním post-processingu, nikoli obcházení ochrany proti ztrátě objemu.

## Všechny čtyři operace při kalibračním přepočtu

`execute_sequence()`:
- Když běh přichází z původního source `.ver` s OP17/18/19 INACTIVE a OP20 ACTIVE, vyžaduje přesné definice každé z OP17/18/19: pořadí, typ 101 a DSEGSET LNV/NV, CF/CL, CS/CW (včetně noT). Finální OP20 musí být aktivní, typu 101 a pokrývat přesných 14 DSeg.
- Ve fázi `ASSIGNMENT_SKIMS` aktivuje v **dočasném `activate_operation_plan`** i OP17/OP18/OP19 a vykoná přesně `17→18→19→20`. Všechny fáze vrací `ACTIVE` definice zdrojového modelu na původní hodnoty; nedojde k driftu `operations_hash`.
- `LONG_MASK_EXECUTION_PLAN.json`: `temporarily_activated_partial_assignments=[17,18,19]`, `expected_final_assignment_sequence=[17,18,19,20]`, `final_assignment_authority=[20]`. OP20 zůstává jediná společná autorita GAP a kalibračního souhrnu; dílčí operace nemění schválený objective.
- Předem aktivní OP17–OP19 zůstávají aktivní v téže fázi, při nezměněných správných scopes.

**Rozlišuj:** `ACTIVE` v otevřeném `.ver` a `ACTIVE` během skutečné výpočetní fáze. Model může mít 17–19 trvale vypnuté, ale výpočet v každém kroku používá všechny čtyři. Trvalé zapnutí v source `.ver` by porušilo požadavek na nepozměněný zdrojový model a je záměrně zakázáno.

## Verifikace

Testy jsou doplněny v `tests/test_v24917_long_post_td_mask.py` a `tests/test_v24917_longmask_09c_live_scope_regression.py`: striktní NumPy marshaller a `Add=False`, odmítnuté COM zápisy bez mutace a po částečné mutaci, znovuověřená obnova, všechny čtyři OP ve správném pořadí s dočasně změněnými flagy, nepovolená a porušená `DSEGSET` definice.

GitHub Actions workflow `.github/workflows/previsum-v24917-failure-guards.yml`: testy na Pythonu 3.13 + plná regresní sada + DIAGFAST + GENFIX2 + kontrola SHA256 pečetí.

## Bezpečné spuštění

1. Stáhnout celé ZIP této GitHub větve a rozbalit do **nové složky**, žádné přepisování modulů ve starším vydání.
2. Otevřít v Visumu originální `R1_novy_start.ver`, nikoli již poškozenou pracovní kopii z neúspěšného běhu. Spustit `01_SPUSTIT_V24917_TDJOINT1.py` z opraveného balíčku.
3. Ověřit `LONG_MASK_EXECUTION_PLAN.json` a `MASK_VEHICLE_LONG/LONG_MASK_RESULT.json`, všechny maskované 9111–9115 a 9291–9295, agregát 9305, finální OP20/GAP a následně 12D/11D readback.
4. Teprve po úspěšném kompletním `BASELINE_FULL_RECOMPUTE` a bezchybném rollbacku povolit dlouhý 100-cyklový TG/TD běh.

`LIVE_VISUM_NOT_RUN` — úspěšné offline testy samy o sobě nezaručují úspěch Windows COM API nebo validitu vícenásobného přiřazení.
