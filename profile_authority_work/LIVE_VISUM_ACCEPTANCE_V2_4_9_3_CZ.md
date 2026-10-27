# Live Visum acceptance — V2.4.9.3

## Povinný start

1. Otevřít `ACCEPTED_B_0000_2b3bb8f7818b.ver` z běhu V2.4.9.0, nikoli neověřený
   in-memory stav po COM chybě.
2. Spustit launcher V2.4.9.3 v nové session PTV Visum.
3. Ověřit run root `R1_15A2_V2493_RUNS` mimo všechny starší RUNS stromy.
4. Ověřit restore autorizované persistentní path cache nebo bezpečnou fresh enumeraci.

## Bounded gate

- nejvýše dva coupled-demand cykly;
- musí vzniknout kladné i záporné signed zonální efekty, pokud je vyžaduje evidence;
- `CSD_CAL` musí reportovat `WEIGHTED_MEAN_GEH`;
- `obs_sum/model_sum` musí být pouze diagnostické passage checksumy;
- LONG acceptance musí obsahovat jeden `LONG_COMPOSITE`, nikoli pět missing authorities;
- po každém Generation apply/rollback musí být zónový readback PASS;
- transientní COM retry musí být omezené a auditované;
- každý kandidát vyžaduje fresh assignment a live 12D/11D.

## Hard guards, které zůstávají

- observation-set identity a role;
- individuální `new_geh20/new_geh30` nad běžným GEH;
- protected-profile transitions;
- P/A konzistence;
- frozen context a TD metadata;
- nezměněná nativní IPF tolerance;
- rollback/checkpoint reprodukovatelnost.

## Povinné výstupy

`RUN_ROOT_AUTHORITY.json`, `METHODOLOGY_STATUS.json`,
`00_GENERATION_COEFFICIENT_REFERENCE.json`,
`GENERATION_SIGNED_REFINEMENT_AUDIT.json`, `GENERATION_DESIGN.json`,
`TD_PARAMETER_FREEZE_AUDIT.json`, `TD_SOFT_REFERENCE_ACCEPTANCE.json`,
`TRIAL_RESULT.json`, `LATEST_ACCEPTED_CHECKPOINT.json` a `00_RESULT.json`.

Release lze povýšit na live-accepted teprve po úspěšném bounded běhu. Offline PASS
sám o sobě není produkční acceptance.
