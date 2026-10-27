# Live Visum acceptance — V2.4.8.8

1. Otevřít poslední bezpečný accepted checkpoint z V2487 B_0000. Nemazat `%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248`.
2. Spustit `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_8.py` přes Scripts → Execute script file.
3. Ověřit, že nový run leží přímo v `...\2022\R1_15A2_V2488_RUNS\RUN_...`, ne uvnitř starého checkpointu.
4. V `...\DEMAND_CYCLE_01_GENERATION\DESIGN\GENERATION_CACHE\PERSISTENT_PATH_CACHE_RESTORE.json` očekávat `PERSISTENT_PATH_EPOCH_RESTORED`. Pro starou cache je očekávaný `contract_validation.mode=EXPLICIT_PREDECESSOR_PATH_SEMANTIC_COMPATIBILITY`; při stejném path kódu a pouze jiném config SHA může být `PATH_SEMANTIC_CONFIG_DIGEST_COMPATIBILITY`.
5. Pokud cache semanticky nesedí, musí vzniknout `PERSISTENT_PATH_CACHE_REJECTED.json` a běh musí pokračovat legacy importem nebo fresh enumeration. Nesmí skončit pouze na `PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH:*`.
6. Integrity/SHA/binding/path-basis chyby musí naopak zůstat hard fail.
7. Po cache gate musí vzniknout Generation `DESIGN` a následně `TRY_01`; acceptance dál vyžaduje fresh Visum assignment a live 12D/11D.
8. Po prvním accepted stavu ověřit checkpoint + path epoch binding a bezpečný restart bez zbytečné enumerace.

Do dokončení tohoto gate je `production_ready=false`.
