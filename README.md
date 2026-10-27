# R1 15A2 V2.4.8.9 – TD realization stabilization

Aktuální launcher: `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_9.py`.

V2.4.8.9 zachovává V2.4.8.8 a doplňuje bezpečný backtracking realizace FineCDF TD v souřadnicích `b, log(-c)` bez změny IPF tolerance, blokaci další Generation do dokončení TD a atomickou krátkou rollback diagnostickou evidenci.

# R1 15A2 — aktuální release V2.4.8.8

Aktuální launcher je:

```text
R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_8.py
```

V2.4.8.8 opravuje reálný pád V2.4.8.7 před Generation na
`PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH:config_sha256`. Plný SHA konfigurace je
nyní pro persistentní path cache pouze provenance; reuse se autorizuje přes
explicitní path-data kontrakt a reviewed kompletní source implementation identity.
Skutečně nekompatibilní cache je výkonový miss a běh smí pokračovat legacy
exact-state importem nebo fresh enumeration; korupce, SHA, SQLite integrity,
binding a path-basis chyby zůstávají fail-closed.

Zachováno je:

- persistentní cache `%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248`;
- accepted-state path-epoch bindings;
- zero-share support hotfix;
- outermost project-root normalizace a zákaz vnořených runů;
- live Generation koeficienty bez historických stropů 3/10;
- fresh Visum assignment + live 12D/11D jako acceptance autorita;
- rollback bez `LoadVersion`.

Začni `START_HERE_V2488_CZ.txt` a `LIVE_VISUM_ACCEPTANCE_V2_4_8_8_CZ.md`.
Skutečný V2488 Visum acceptance zatím není uzavřen; `production_ready=false`.
