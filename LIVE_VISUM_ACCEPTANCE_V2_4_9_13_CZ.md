# Live Visum acceptance — V2.4.9.13

## Kritická provozní poznámka

Již běžící V24912 má staré supply moduly a config načtené v paměti. Samotným přepsáním lokálních `.py` nebo JSON souborů se její budoucí supply fáze bezpečně nezmění.

Proto:

- V24912 a V24913 nikdy nespouštět souběžně;
- nejbezpečněji V24912 cooperative zastavit na verified boundary a pokračovat V24913 full launcherem z nejnovějšího accepted `.ver`;
- supply-only launcher použít jen nad přesně ověřeným converged demand checkpointem.

## Full continuation

Otevři nejnovější accepted `.ver` a spusť:

```text
R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_13.py
```

Očekávané preflight soubory:

```text
V24913_DEPLOYMENT_PREFLIGHT.json
V24913_RUNTIME_BUNDLE_PREFLIGHT.json
```

Oba musí mít `passes=true`.

Po joint TG/TD convergence očekávej:

```text
DEMAND_CONVERGED.json
SUPPLY_ROUTE_CHOICE/
SUPPLY_ACCEPTANCE_CONTEXT_001.json
```

## Supply-only continuation

Otevři accepted `.ver`, který odpovídá `DEMAND_CONVERGED.json`, a spusť:

```text
R1_15A2_SUPPLY_FROM_CONVERGED_DEMAND_V2_4_9_13.py
```

Před prvním zápisem vznikne:

```text
VERIFIED_DEMAND_TO_SUPPLY_HANDOFF.json
```

Musí obsahovat:

```text
criterion_verified = true
supply_only = true
demand_parameters_frozen_during_supply = true
live_state_hash == demand_convergence_authority.state_hash
```

## První supply cycle — očekávané evidence

```text
SUPPLY_ACCEPTANCE_CONTEXT_001.json
SUPPLY_ADDVAL1/DESIGN.json
SUPPLY_ADDVAL1/TRIAL_*/ACCEPTANCE.json
SUPPLY_ADDVAL1/ADOPTION/ADOPTION_ACCEPTANCE.json
```

V designu kontroluj:

```text
backtracking_order = BRANCH_LOCAL_DESCENDING_STEP
step_units_schedule = [16, 8, 4, 2, 1]
```

Při lattice 0.5 to odpovídá:

```text
80 / 40 / 20 / 10 / 5 sekund
```

Každá publikovaná `backtracking_group_id` musí mít úplný sestupný ladder, pokud daný krok neodřízl hard impedance/bounds guard.

## Hard live gates

- exact source/working semantic identity;
- assignment op. 20 a gap <= 0.005;
- fresh 12D/11D;
- exact ADDVAL write/readback;
- matrix/generation/TD hashes frozen;
- observation set unchanged;
- protected-profile catastrophic guard;
- shared objective musí klesnout;
- rejected trial rollbackne přesně na accepted parent;
- adopted candidate musí být reprodukovatelný při fresh reapply.

## Live release boundary

Úspěšný první accepted ADDVAL kandidát prokáže funkčnost apply/evaluate/rollback/reapply/commit cesty. Produkční připravenost ale vyžaduje alespoň jeden celý supply cycle a následný full cycle bez accepted candidate s ověřeným path-basis plateau.
