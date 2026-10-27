# R1 15A2 V2.4.8.3 — cache compatibility hotfix

Release: `R1_15A2_V2_4_8_3_CACHE_COMPAT_HOTFIX_20261016`

Tato větev zachovává opravu V2.4.8.2 pro `NATIVE_CW 1→7` a opravuje navazující problém s načtením již existující persistentní cache V2481/V2482.

## Proč je V2.4.8.3 nutná

Persistentní cache je správně chráněna přísným kontraktem. Kontrakt obsahuje mimo jiné celý `config_sha256` a hashe spotřebních modulů. V2.4.8.2 změnila konfiguraci i `r1_15a2_two_mode_v238.py`, takže původní V2481 cache by byla odmítnuta ještě před tím, než by se uplatnila oprava zero-share residualu.

V2.4.8.3 nepovoluje obecně nekompatibilní cache. Zavádí pouze explicitní read-only kompatibilitu pro dva přesně známé předchůdce:

- `R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016`;
- `R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016`.

Pro přijetí musí současně platit:

- přesný predecessor release;
- přesný predecessor `config_sha256`;
- přesné staré hashe pouze tří výslovně uvedených spotřebních modulů;
- shodná verze SQLite schématu;
- shodné zóny, DSeg scope, reprezentanti, observation authority, pořadí profilů a edge dictionary;
- shodný immutable snapshot;
- platný manifest, SQLite integrity, store SHA-256 sidecar;
- shodný path basis, comparison basis a structure hash po otevření cache.

Jakákoli další odchylka zůstává hard failure.

## Očekávané načtení

Cache root se nemění:

`%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248`

Při stejném accepted baseline stavu se má v novém runu objevit:

- `PERSISTENT_PATH_CACHE_RESTORE.json`
- `status = PERSISTENT_PATH_EPOCH_RESTORED`
- `matched_by = STATE_BINDING` nebo `ORIGIN_STATE_HASH`
- `contract_validation.mode = EXPLICIT_PREDECESSOR_READ_COMPATIBILITY`

Potom se pro `NATIVE_CW 1→7` použije V2.4.8.2 policy: relace zůstane v projection-base marginals, ale nebude použita jako sparse path-guidance actuator. Nesmí vzniknout počáteční `FORCED_SUPPORT_REFRESH`, pokud nejsou nalezeny jiné skutečné support gaps.

## Spuštění

Otevřít stejný accepted baseline `.ver` a ručně spustit přes **Scripts → Execute script file**:

`R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_3.py`

Existující `%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248` nemažte ani nepřejmenovávejte.

Balík prošel offline testy a tamper gates. Reálný Visum run v tomto prostředí proveden nebyl; `production_ready = false` do úspěšného live gate.
