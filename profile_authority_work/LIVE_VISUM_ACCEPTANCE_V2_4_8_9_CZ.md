# Živý Visum acceptance V2.4.8.9

1. Run root je top-level `R1_15A2_V2489_RUNS/RUN_*`.
2. Persistentní cache je obnovena nebo bezpečně nahrazena.
3. Generation může být přijata.
4. FineCDF target se realizuje přes `TD_REALIZATION_ATTEMPTS.json`.
5. Při IPF nonkonvergenci se zkouší menší scale; `ipf_tolerance_relaxed=false`.
6. Před každým scale je doložen restore accepted parent b,c.
7. Ne-IPF chyba se neopakuje jako step-size backtracking.
8. Další Generation nevznikne před `td_realization_complete=true`.
9. Rollback 11D/12D evidence používá existující atomický cíl nebo krátký `RUN/H` mirror.
10. Supply se neodemkne bez plné coupled-demand stationarity.

Release zůstává `production_ready=false`, dokud tento gate neprojde ve skutečném PTV Visum.
