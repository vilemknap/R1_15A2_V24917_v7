# R1 15A2 V2.4.9.15 PERF1 exact-safe acceleration

Spouštěcí soubor:

`R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF1.py`

Konfigurace:

`R1_15A2_CONFIG_V2_4_9_15_PERF1.json`

Zdrojová autorita zůstává `ACCEPTED_A_0009_cebb9c7a9349.ver`. Větev pokračuje outer cycle 6 a nemění žádný kalibrační práh ani matematiku.

Před live spuštěním:

1. otevřít čistý A0009 checkpoint;
2. ponechat V6 interlock v procedure operation 21;
3. spustit PERF1 launcher přes `Scripts -> Execute script file`, nikdy jako procedure operation;
4. ověřit oba PERF1 preflight JSONy;
5. sledovat `PROCEDURE_EXECUTION_PLAN.json`, `PROCEDURE_EXECUTION_PLAN_ACTIVE.json` a rollback reuse proof;
6. pro první běh použít kontrolovaný A/B benchmark proti parent V24915.

Neprokázaná optimalizační podmínka vždy přechází na původní plný výpočet.
