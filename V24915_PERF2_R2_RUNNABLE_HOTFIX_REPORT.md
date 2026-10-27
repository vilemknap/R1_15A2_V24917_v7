# V24915 PERF2 R2 runnable hotfix

Status: `OFFLINE_VERIFIED_RUNNABLE_DEPLOYMENT_HOTFIX_READY_FOR_LIVE_VISUM`

## Zjištěná příčina

Původní PERF2 delivery ZIP nebyl přímo runnable deployment. Obsahoval především evidence a vnořený `CP95_V24915_PERF2_FULL_SOURCE_CHECKPOINT.zip`, takže launcher neměl po běžném rozbalení vedle sebe kompletní runtime strom. Současně PERF2 launcher zdědil názvy output run rootu `R1_15A2_V24915_PERF1_RUNS`.

## Oprava

- celý runtime strom je přímo v jednom ZIPu pod krátkým kořenem `R1_15A2_V24915_PERF2_RUN`;
- launcher zůstává `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py`;
- output run root je `R1_15A2_V24915_PERF2_RUNS` / `R1_15A2_V24915_PERF2_SUPPLY_RUNS`;
- package revision je `V24915_PERF2_CANDIDATE_READBACK_BUNDLE_R2_RUNNABLE_HOTFIX`;
- runtime manifest byl znovu připnut;
- kalibrační matematika, CandidateReadbackBundle, acceptance a 12D/11D nebyly změněny.

## Testy

- focused PERF2: 51 passed;
- komplet ve 4 deterministických skupinách: 844 passed, 4 skipped, 0 failed;
- runtime import: PASS;
- config validation: PASS;
- deployment preflight: PASS, 80/80 files;
- runtime bundle preflight: PASS;
- compileall: PASS.

## Spuštění

1. Rozbal ZIP do krátké lokální cesty, např. `C:\R1_PERF2\`.
2. Ve Visumu otevři `ACCEPTED_A_0009_cebb9c7a9349.ver`.
3. `Scripts -> Execute script file`.
4. Vyber `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py` ze stejné rozbalené složky.

Nespouštěj launcher z externího Pythonu; bez injected Visum COM záměrně skončí `NO_INJECTED_VISUM`.
