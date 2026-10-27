# V2.4.6 — živý akceptační postup ve Visumu 2026

Tento checklist je povinný před označením V2.4.6 jako production-ready.

## 1. Příprava

- zavřít předchozí skripty a ověřit, že nezůstal aktivní lock;
- otevřít čistý autoritativní zdrojový `.ver`;
- rozbalit celý V2.4.6 balík do krátké lokální cesty, nikoli do hluboce zanořeného OneDrive stromu;
- spustit pouze `R1_15A2_FULL_OVERNIGHT_ADAPTIVE_V2_4_6.py`.

## 2. Povinný bounded gate

První běh musí reálně projít alespoň:

1. preflight TG/TD/assignment a kontrolu chráněných autorit;
2. baseline full Procedure Sequence;
3. vytvoření TG incidence cache s adaptivním stránkováním;
4. Generation `TRY_01`;
5. rollback kandidáta a nové 12D/11D diagnostiky;
6. opakované aplikování přijatého kandidáta, pokud existuje;
7. vstup do FineCDF `EXPLORE` a alespoň jeden nativní TD call;
8. bezpečný STOP nebo pokračování do dalšího demand cyklu.

## 3. Kontroly po bounded běhu

Musí platit:

- `source_file_unchanged = true`;
- žádný stav `MANUAL_REOPEN_REQUIRED`;
- poslední checkpoint existuje, je neprázdný a jeho SHA sedí;
- `live_matches_last_accepted = true`;
- při `PROGRESS_CONTINUE_DEMAND` je:
  - `demand_converged = false`,
  - `supply_started = false`,
  - `stationary_cycle_streak = 0`;
- v `PERFORMANCE/SUMMARY.json` nejsou telemetry errors;
- bulk link read je buď `BULK_GET_MULTI_ATT_VALUES`, nebo doložený `SCALAR_FALLBACK`;
- page-size fallback nevytvořil duplicity, ztrátu řádků ani unbounded call;
- CP03 path-length chyba se neopakovala.

## 4. Úplný běh

Supply se smí spustit pouze po dvou po sobě jdoucích úplných `FULL_VERIFY` TG→TD cyklech bez přijaté změny. Konečný model je autorizován jen pokud:

- `final_state_verified = true`;
- `calibration_complete = true`;
- status je `COMPLETED_CONFIGURED_DEMAND_AND_SUPPLY_SEARCH`;
- finální SaveVersion nezměnil ověřený state hash;
- zdrojový `.ver` zůstal byte-for-byte nezměněný.

## 5. Co poslat pro audit

Zabal celý nejnovější `RUN_*`, minimálně však:

- `00_RESULT.json`, `00_PROGRESS.json`, `METHODOLOGY_STATUS.json`;
- `CALIBRATION/RUN_STATUS.json`;
- všechny `DEMAND_CYCLE_*_RESULT.json`;
- `PERFORMANCE/`;
- `CHECKPOINTS/*.json` a SHA evidence;
- první Generation `TRY_01` včetně `ROLLBACK/`;
- první FineCDF `V242_FINECDF_INNER_RESULT.json` a iteration history;
- Supply výsledky, pokud byl Supply odemčen.
