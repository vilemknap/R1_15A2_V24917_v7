# Živý Visum acceptance V2.4.9.0

1. Run root musí být top-level `R1_15A2_V2490_RUNS/RUN_*`.
2. Persistentní path cache musí být obnovena/autorizována nebo bezpečně nahrazena fresh enumerací.
3. Generation guardraily se nemění; `NEW_SEVERE_GEH_PROFILE` zůstává hard reject.
4. FineCDF v1.9 používá survey CDF jako soft directional reference a `exact_curve_match_required=false`.
5. Každý TD kandidát se musí realizovat přes plný downstream Visum recompute.
6. Nativní 20B/IPF tolerance zůstává nezměněná (`ipf_tolerance_relaxed=false`).
7. Po realizaci musí vzniknout `TD_PARAMETER_FREEZE_AUDIT.json`; frozen context a TD metadata jsou exact, pouze b/c mají abs 1e-8 / rel 1e-10 read-back toleranci.
8. Po realizaci musí vzniknout `TD_SOFT_REFERENCE_ACCEPTANCE.json`. Přijetí vyžaduje >=0.5 % agregované selected zlepšení a bounded trade-offs, zároveň musí projít hard network/observation/protected/severity gates.
9. Soft reject smí backtrackovat přes scale 1, .5, .25, .125, .0625. Ne-IPF technická chyba nesmí být vydávána za step-size problém.
10. Pokud všechny technicky realizované kandidáty selžou pouze soft-reference gate, musí se ověřeně obnovit parent a výsledek být `SOFT_REFERENCE_PLATEAU`, ne FAILED.
11. Vyčerpaná nativní IPF nonkonvergence zůstává fail-closed.
12. Další Generation ani Supply se nesmí odemknout z neověřeného TD stavu.

`production_ready=false` zůstává do úspěšného skutečného PTV Visum průchodu tohoto gate.
