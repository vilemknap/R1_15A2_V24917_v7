# R1 15A2 V2.4.8.8 — path-cache semantic compatibility

## Proč tato verze vznikla

První reálný běh V2.4.8.7 skončil před sestavením Generation cache na
`PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH:config_sha256`. Přitom modelový state
zůstal na posledním accepted B_0000 a samotná Generation fáze nebyla spuštěna.

Příčina byla v identitě persistentní path cache: předchozí implementace používala
SHA celého JSON configu jako součást exact path-cache kontraktu. To je příliš
široké, protože config SHA se změní i při změně Generation/TD/Supply nastavení,
která nemění uloženou path geometrii. Zároveň historický compatibility registry
obsahoval pro jednu V2.4.8.2 větev jiný config digest než skutečně vydaný
`ZERO_VOLUME_SUPPORT` archiv.

## Nový kontrakt

V2.4.8.8 rozděluje identitu na dvě vrstvy:

- `config_sha256` a z něj odvozený `contract_hash` jsou provenance;
- path-cache reuse autorizují explicitní path-data pole: cache/schema verze,
  DSeg scope, representatives, profile order/observation authority, edge dictionary,
  immutable network snapshot, sequence budgets a úplná sedmimodulová identita
  kódu, který path data vytvářel/interpretoval.

Pro reviewed predecessor release musí sedět celý source hash map těchto modulů:
`r1_15a2_two_mode_v238.py`, `r1_15a2_trial_adapter_v240.py`,
`r1_15a2_persistent_path_cache_v248.py`, `r1_15a2_sequence_v23.py`,
`r1_15a2_supply.py`, `r1_15a2_core.py`, `r1_15a2_runtime_v1.py`.

Registry obsahuje skutečné vydané identity V248, V2481, obou V2482 větví,
V2483, V2484, obou V2485 větví, V2486 a V2487.

## Fail-closed hranice

Pouze semantická nekompatibilita cache je výkonový miss: cache se nepoužije a
běh zkusí legacy exact-state import nebo fresh enumeration. Následující chyby se
nikdy nezměnily na soft fallback: manifest/binding tamper, SQLite integrity,
foreign-key error, store size, SHA-256/sidecar mismatch, parent/state hash,
path basis/comparison/structure hash a immutable network context.

## Generation autorita

V2.4.8.7 live-coefficient contract zůstává beze změny: historické absolutní
stropy 3/10 nejsou používány. Násobné koeficienty vycházejí z aktuální živé
hodnoty a relativního log kroku. Fresh Visum assignment + live 12D/11D jsou stále
jedinou acceptance autoritou.

## Spuštění

Launcher:
`R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_8.py`

Runtime cache nemažte:
`%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248`

Nové runy jsou vždy pod projektovým kořenem v `R1_15A2_V2488_RUNS`.

## Stav ověření

Offline regressions, package verifier a tamper gate jsou součástí release evidence.
Skutečný Windows PTV Visum gate musí být proveden na cílovém počítači.
`production_ready=false` do jeho dokončení.
