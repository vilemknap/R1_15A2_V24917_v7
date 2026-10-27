# LIVE VISUM ACCEPTANCE - V2.4.8.1

Pro první bounded rerun po V2.4.7:

1. Neodstraňovat složku `R1_15A2_V247_RUNS/RUN_20261016_162053_068586`.
2. Otevřít `ACCEPTED_B_0000_61129884aaf7.ver` z tohoto runu.
3. Spustit `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_1.py`.
4. V novém runu zkontrolovat `PERSISTENT_PATH_CACHE_RESTORE.json`.
5. Preferovaný výsledek: `matched_by=LEGACY_EXACT_STATE_IMPORT` a žádný nový úvodní path export.
6. Potvrdit, že `NATIVE_CW:7:7` nevyvolá `PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION`.
7. Nechat doběhnout alespoň Generation design + první kandidát/rollback a vstup do FineCDF.
8. Pokud se později objeví skutečná nová kladná OFF-DIAGONÁLNÍ relace bez supportu, nová enumerace je správná a povinná.
9. Pokud Windows zamkne starý superseded SQLite při cleanupu, run nesmí spadnout; audit musí uvést `DELETE_DEFERRED_WINDOWS_FILE_LOCK`.
10. Production-ready až po úspěšném real Visum gate; offline testy samy nestačí.
