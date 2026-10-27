# R1 15A2 V2.4.9.3 — metodické a COM korekce

V2.4.9.3 navazuje přímo na V2.4.9.2 a zachovává signed Generation, TD soft-reference,
nativní IPF toleranci, persistentní path cache, rollback a všechny živé 12D/11D
acceptance gates. Nejde o nový kalibrační algoritmus; release opravuje čtyři přesně
vymezené kontrakty odhalené živým během V2.4.9.0.

## 1. CSD objective používá GEH, nikoli GEH²

Hlavní `CSD_CAL` člen je nyní explicitně

`sum_i(weight_i * GEH_i) / sum_i(weight_i)`.

`objective_geh2_mean` zůstává v reportu jako diagnostika a pro reprodukci starších
release, ale V2.4.9.3 jej nepoužívá pro candidate acceptance. Individuální guards
`new_geh20` a `new_geh30` zůstávají nad běžným GEH beze změny.

## 2. Součty přes profily nejsou součty unikátních cest

`obs_sum`, `model_sum` a `model_obs_ratio` jsou označeny jako
`DIAGNOSTIC_ONLY_PROFILE_PASSAGE_CHECKSUM`. Jedna cesta může projít více profily,
proto tyto hodnoty nesmějí být interpretovány jako celkový počet cest nebo vozidel.

## 3. LONG je jeden global composite

Pět nativních LONG matic ve Visumu zůstává zachováno, ale kalibrační a acceptance
autorita je jediný `LONG_COMPOSITE`. Všechny LONG komponenty dostávají společný
posun `b` a společný multiplikátor `c`; tím se zachovává jejich komponentový mix.
Downstream acceptance už nevyžaduje pět neexistujících component targetů.

## 4. Zónové transakce a transientní COM chyby

Při inicializaci adaptéru se jednou načte a ověří mapování `Zone.NO -> COM row key`.
Generation apply i rollback používají tuto cache přes `SetMultiAttValues`, poté
provedou readback. Retry je omezen pouze na transientní HRESULT
`RPC_E_CALL_REJECTED` a `RPC_E_SERVERCALL_RETRYLATER`; fallback starší COM signatury
je oddělený od retry logiky. Celý 12D/11D helper lze zopakovat jen při stejné
transientní třídě chyby.

## Kompatibilita

V2.4.9.2 je připnuta jako přesný read-only predecessor persistentní path cache.
Starší konfigurace bez `csd_calibration_objective` nadále používají legacy GEH² a
bez `com_resilience` zachovávají původní pětimístné rozhraní `run_helper`.

## Stav ověření

- kompletní offline regresní sada: 692 PASS;
- compileall: PASS;
- nový safety/config contract: PASS;
- reálný PTV Visum COM acceptance běh: zatím neproveden.

Release proto není označen `production_ready=true`. První použití má být bounded
live běh z posledního ověřeného B_0000 checkpointu V2.4.9.0.
