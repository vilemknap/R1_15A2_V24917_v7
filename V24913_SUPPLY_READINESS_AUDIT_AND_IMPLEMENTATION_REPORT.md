# V24913 Supply Route-Choice Readiness — audit a implementace

## 1. Audit původní V24912 supply větve

Původní V24912 měla kompletní základní mechaniku route-choice kalibrace:

- `SUPPLY_ADDVAL1` blok;
- actual ordered Visum path evidence;
- diverge/rejoin contiguous branch candidate design;
- LINK ADDVAL1 apply/readback;
- fresh assignment a 12D/11D;
- demand freeze;
- transactional rollback/reapply/commit;
- persistent path cache a path-epoch refresh;
- supply convergence přes full cycle bez accepted candidate.

Audit však našel dvě P0 vady:

1. `early_exploration_policy()` vracela pro `SUPPLY*` `None`; supply proto nepoužívala V24912 baseline-relative severity a vracela se do zděděného příliš tvrdého guardu.
2. candidate ordering bylo globálně step-first. Při malém trial budgetu mohly všechny pokusy spotřebovat různé 40sekundové kandidáty a jemnější krok stejné branch se vůbec nevyhodnotil.

Dále byly původní search limity příliš úzké pro ranou route-choice kalibraci.

## 2. Implementované změny

### 2.1 Samostatný supply acceptance clock

Controller při každém supply cycle nastaví:

```text
runtime_acceptance_supply_cycle
runtime_acceptance_scope = SUPPLY_ADDVAL1
```

Demand outer-cycle index již neovlivňuje supply exploration horizon.

### 2.2 Baseline-relative supply policy

`r1_15a2_core.py` nyní pro Supply aktivuje:

```text
V24913_SUPPLY_ROUTE_CHOICE_BASELINE_RELATIVE
```

Supply vyžaduje reálné snížení weighted mean GEH a fixed-reference shared objective. GEH20/30/40 používají kontinuální/net budgety. Existing GEH>60 není state veto; hard je jen materiální další zhoršení.

### 2.3 Branch-local backtracking

`propose_sequence_supply()` seskupí candidate amplitudy podle fyzické route branch a publikuje je souvisle:

```text
stejná branch: 80 → 40 → 20 → 10 → 5 s
teprve potom další branch
```

Candidate cap nikdy nepublikuje neúplný ladder. Každý candidate nese:

```text
backtracking_group_id
backtracking_group_rank
backtracking_step_rank
branch_preference
```

### 2.4 Uvolněné limity

Viz `V24913_SUPPLY_LIMITS_BEFORE_AFTER.csv`. Uvolnění je kompenzováno fresh live assignmentem, monotónním shared objective, demand freeze, severity/IDP budgety a exact rollbackem.

### 2.5 Verified converged-demand handoff

Nový `r1_15a2_supply_handoff_v24913.py`:

- hledá validní `DEMAND_CONVERGED.json`;
- vyžaduje dvě stationary cycles;
- ověří exact live `state_hash`;
- spustí pouze `SUPPLY_ADDVAL1`;
- po dokončení znovu ověří `matrix_hash`, `generation_hash`, `td_hash`.

## 3. Explicitně frozen parametry

V24913 nemění:

- VDF registry a parametry;
- capacity;
- V0PrT;
- turn/node VDF;
- connector impedance;
- turn/connector ADDVAL;
- demand matrices, TG a TD parametry během supply.

Toto je metodická ochrana před neidentifikovatelnou společnou kalibrací více impedance vrstev pouze z countů.

## 4. Objective boundary

Live V24913 používá stávající 12D/CITY count authority a 11D IDP diagnostiku. Strategic TURN_SHARE/CORDON_PAIR authority je metodicky vhodná pro route-choice, ale její runtime soubory a operátory nejsou obsahem V24912 package. V24913 je proto nevydává za zapojené.

## 5. Testy

- focused V24913 supply tests;
- inherited supply/sequence/acceptance regressions;
- full package pytest;
- compileall;
- config reviewed-delta validation;
- runtime manifest SHA validation;
- half-lattice positive/negative tests;
- branch-local complete-ladder test;
- supply severity boundedness test;
- demand-convergence handoff fail-closed test;
- tamper tests.

## 6. Pravdivý status

```text
implementation_complete = true
offline_tested = true
real_visum_supply_tested = false
production_ready = false
```
