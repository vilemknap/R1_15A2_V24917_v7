# DŮLEŽITÉ: COMPLETE R2

Tento balík je runtime-complete revize `V24912_COMPLETE_R2`. Policy je vložena přímo v `r1_15a2_core.py`; live běh již nezávisí na pozdním importu `r1_15a2_guard_policy_v24912`. Před prvním zápisem launcher automaticky vytvoří a ověří `V24912_RUNTIME_BUNDLE_PREFLIGHT.json`.

# R1 15A2 V2.4.9.12 — Guard Policy Rebase

## Co tato větev opravuje

V24912 je plný successor V2496, ne overlay. Zachovává kompletní V2496 source tree a mění pouze policy/severity vrstvu, která v rané kalibraci blokovala dobré Generation/TD kandidáty kvůli absolutní kvalitě celého after-state.

Zásadní změna: kalibrační kandidát se posuzuje relativně vůči aktuálně přijatému baseline. GEH20/30 jsou kontinuální severity budgety, GEH35 warning, GEH40 používá scope-specific net-count budget a GEH60 je diagnostický práh s hard delta guardem. Samotný malý přechod 59.x -> 60.x není hard reject.

## Hard ochrany, které se neuvolňují

Observation authority, CAL/VALID role, semantic restart identity, frozen model context, native IPF tolerance, fresh TG/TD + assignment + 12D/11D, parameter readback, coefficient envelopes/P-A consistency, rollback/final-state verification, protected profile <GEH5 -> >=GEH20, single-profile +15 GEH a high-GEH after >60 s delta >10 zůstávají fail-closed.

## Policy

Generation: severity20 +8 %, severity30 +10 %, GEH40 net +5. TD: min +0.25 % distribution objective, CAL cost <=5 %, benefit/cost >=1.5, selected/nonselected component cost <=20 %, severity20 +25 %, severity30 +30 %, GEH40 net +15. Tato exploration policy platí přes všech 12 coupled-demand cycles.

## Reálný V2496 replay

Counterfactual replay skutečných live-Visum diagnostik: Generation 1.0 ACCEPT, 0.5 REJECT, 0.25 ACCEPT; TD 0.5 REJECT, 0.25/0.125/0.0625 ACCEPT. TD 1.0 zůstává native-IPF retry/nonconvergence a tolerance se neuvolňuje.

## Ověření balíku

754/754 full regression PASS, 11/11 V24912 focused tests PASS, compileall PASS, package verifier PASS a úmyslně pozměněný TD Pareto limit je fail-closed detekován. Kritické inherited moduly mimo `r1_15a2_core.py` zůstaly proti V2496 byte-identical.

## Stav

`real_visum_tested=false`, `production_ready=false`. V24912 je offline ověřena a připravena na první live Visum běh z posledního skutečně accepted V2496 checkpointu.
