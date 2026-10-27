# V24912 – audit guardů a policy rebase

## Závěr

V2496 měla funkční Generation/TD návrhy a Pareto acceptance, ale exploratory severity byla stále implementována jako absolutní stavová zeď. To blokovalo kandidáty, které model globálně zlepšovaly nebo nabízely silný TD benefit za přijatelnou CAL cenu. V24912 proto mění pouze severity interpretaci na baseline-relative budget; technické a metodické integrity zůstávají fail-closed.

Zároveň byla opravena nekonzistence dřívějšího návrhu V24912: **nový přechod přes GEH60 nemůže být bezpodmínečně hard**, protože skutečný TD scale 0.25 má tři malé přechody přes 60 a přitom splňuje zamýšlený Pareto kontrakt. Hard pravidlo je nově `after GEH > 60` **a současně** `GEH delta > 10`.

## Counterfactual replay skutečných V2496 kandidátů

| Blok | scale | původně | V24912 | hlavní důvod |
|---|---:|---|---|---|
| GENERATION | 1.0 | REJECT | ACCEPT | severity v budgetu; ostatní acceptance gate prošly |
| GENERATION | 0.5 | REJECT | REJECT | CAL_GEH_OBJECTIVE_NOT_IMPROVED; SHARED_OBJECTIVE_NOT_IMPROVED |
| GENERATION | 0.25 | REJECT | ACCEPT | severity v budgetu; ostatní acceptance gate prošly |
| TD | 1.0 | REJECT | REJECT | native IPF nonconvergence – tolerance se neuvolňuje |
| TD | 0.5 | REJECT | REJECT | CAL_CSD_DEGRADED_TOO_MUCH; NEW_SEVERE_GEH_PROFILE |
| TD | 0.25 | REJECT | ACCEPT | severity v budgetu; ostatní acceptance gate prošly |
| TD | 0.125 | REJECT | ACCEPT | severity v budgetu; ostatní acceptance gate prošly |
| TD | 0.0625 | REJECT | ACCEPT | severity v budgetu; ostatní acceptance gate prošly |

## Klíčové policy hodnoty

- Generation: severity20 +8 %, severity30 +10 %, GEH40 net +5; positive weighted-GEH krok může projít; non-monotonic tradeoff zůstává max +2 % CAL při zlepšení severity.
- TD: min. +0,25 % TD objective, max. +5 % CAL weighted GEH, benefit/cost >= 1,5, selected/nonselected component cap 20 %, severity20 +25 %, severity30 +30 %, GEH40 net +15.
- Per-profile hard: protected <5 -> >=20, GEH delta >15, nebo after GEH >60 se zhoršením >10.
- Exploratory policy platí přes všech 12 coupled-demand cycles; žádné automatické utažení v cycle 9.

## Co zůstává hard

- **OBSERVATION_AUTHORITY** – CAL/VALID role, observed value and observation set must be identical before/after.
- **SEMANTIC_MODEL_STATE_IDENTITY** – Cross-run restart uses semantic hashes; raw .ver SHA is provenance/sentinel only.
- **FROZEN_DEMAND_SUPPLY_CONTEXT** – Frozen matrices/foreign/AddVal state remain protected by existing owners.
- **NATIVE_IPF_TOLERANCE** – Never relaxed; native IPF nonconvergence remains retryable/fail-closed.
- **FRESH_TG_TD_ASSIGNMENT_12D_11D** – Fresh Visum recomputation remains acceptance authority.
- **PARAMETER_WRITE_READBACK** – Generation/TD writes and rollback must read back exactly.
- **GENERATION_COEFFICIENT_ENVELOPE** – Absolute/relative coefficient envelopes and P/A consistency unchanged.
- **ROLLBACK_FINAL_STATE_VERIFY** – Rejected trials must restore and verify state before continuing.
- **PROTECTED_GEH_LT5_TO_GE20** – Catastrophic damage to a previously good profile remains forbidden.
- **SINGLE_PROFILE_GEH_DELTA_GT15** – Independent catastrophic per-profile increase guard.
- **HIGH_GEH_AFTER_GT60_DELTA_GT10** – Replaces absolute after-state GEH60 wall; material worsening stays hard.

## Stav ověření

Tento audit je offline replay skutečných V2496 live-Visum diagnostik. Nejde o nový live V24912 běh. `real_visum_tested=false` a `production_ready=false` zůstávají do prvního skutečného běhu pravdivě zachovány.

