# V24915 PERF2 R4 - B0016 resume + sealed 11D authority hotfix

## Status

`PERF2_R4_OFFLINE_VERIFIED_READY_FOR_LIVE_B0016_RESUME`

## Forensic conclusion

The supplied continuation evidence proves the latest accepted state is B0016 at accepted_count=16. Cycle 11 accepted its Generation step but failed before completing TD. The original source status explicitly allows safe restart from the latest accepted checkpoint. R4 therefore resumes cycle 11 at `TD_FINECDF_V17` and does not replay the already accepted Generation mutation.

The cycle-11 failure was an 11D compatibility-gate failure in which `SERV_noE_C` and `SERV_noE_noC` were reported without active/valid target data. The 11D helper resolves `R1_IDP_AUTHORITY_DIR` before package-local fallback locations, while R3 did not ship an extracted package-local authority folder. R4 removes that deployment ambiguity by shipping the embedded authority as explicit package data and overriding `R1_IDP_AUTHORITY_DIR` process-locally only after exact hash and 512-row-per-component validation. The 11D equations and compatibility gate are unchanged.

## Exact continuation contract

- source checkpoint: `ACCEPTED_B_0016_d1211a44ac4d.ver`
- accepted_count: 16
- semantic_state_hash: `46a0c61d45e55cc9d2a91be0c62839fee7ef9236924e59d6ebc27b62619c63d2`
- next/resumed outer cycle: 11
- resume substep: `TD_FINECDF_V17`
- cycle-11 Generation: already completed and changed; replay forbidden
- inherited stationary streak: 0
- max lineage outer cycle: 12 (unchanged)
- supply_started: false
- GenerationCountsReference SHA-256: `57016672bc247a820075998e98453e7dd4155d6e5b3fd2dcdf752731f6c29e2c`
- R4 continuation authority SHA-256: `602d0cdf7b40ad6cb8ab49d36030e6bc16c06eba757d56ffdf7d4ad28e3185a9`

## Sealed 11D authority

- target curves SHA-256: `f68087c249d6f1da2582e2ea1d723a8b3d1a8d99af82ffe5283f63d0de6a0737`
- required components: 11
- points per component: 512 exactly
- environment policy: package-sealed authority wins only after exact validation
- no relaxed 11D gate or tolerance

## Code delta relative to R3

Changed parent files (5):
- `R1_15A2_CONFIG_V2_4_9_15_PERF2.json`
- `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py`
- `V24915_PERF2_RUNTIME_BUNDLE_MANIFEST.json`
- `r1_15a2_overnight_controller_coupled_v24915p2.py`
- `r1_15a2_safety_v24915p2.py`

Added R4 files (27):
- `V24915_B0016_CONTINUATION_AUTHORITY.json`
- `V24915_PERF2_R4_SEALED_IDP_AUTHORITY_MANIFEST.json`
- `continuation_b0016/ACCEPTED_B_0016_d1211a44ac4d.ver.semantic.json`
- `continuation_b0016/DEMAND_CYCLE_11_RESULT.json`
- `continuation_b0016/EFFECTIVE_CONFIG.json`
- `continuation_b0016/GENERATION_COUNTS_REFERENCE.json`
- `continuation_b0016/LATEST_ACCEPTED_CHECKPOINT.json`
- `continuation_b0016/RUN_STATUS.json`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/R1_IDP_COMPONENT_AUTHORITY_STATUS_V1.csv`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/R1_IDP_DIST_KM_TARGET_CURVES_V1.csv`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/R1_IDP_LONG_DIST_KM_BASIS_V1.csv`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/R1_IDP_LONG_TIME_MIN_DIAGNOSTIC_BASIS_V1.csv`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/R1_IDP_TARGET_SUMMARY_V1.csv`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/R1_IDP_TIME_MIN_DIAGNOSTIC_CURVES_V1.csv`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/R1_IDP_WEIGHTS_GLOBAL_HYBNOST_V1.csv`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/README_R1_IDP_DISTRIBUTION_AUTHORITY_V1.md`
- `helpers/R1_IDP_DISTRIBUTION_AUTHORITY_V1/SOURCE_MANIFEST_V1.json`
- `r1_15a2_demand_continuation_v24915r4.py`
- `r4_evidence/COLLECT_ONLY.txt`
- `r4_evidence/COMPILEALL.txt`
- `r4_evidence/FOCUSED_R4_PYTEST.txt`
- `r4_evidence/FULL_REGRESSION_BATCH_0_20.txt`
- `r4_evidence/FULL_REGRESSION_BATCH_20_40.txt`
- `r4_evidence/FULL_REGRESSION_BATCH_40_60.txt`
- `r4_evidence/FULL_REGRESSION_BATCH_60_80.txt`
- `r4_evidence/RUNTIME_PREFLIGHT.txt`
- `tests/test_v24915p2_r4_b0016_resume.py`

Removed files: 0.

## Tests

- test collection: 855
- passed: 851
- skipped: 4 inherited skips
- failed: 0
- focused R4/live-boundary tests: 11 passed
- full suite executed across all 80 test modules in four batches because a single invocation exceeds the execution-harness time limit
- compileall: PASS
- launcher import: PASS
- deployment preflight: PASS
- config validation: PASS
- runtime bundle preflight: 98/98 PASS
- sealed IDP activation: PASS

## Methodology unchanged

Calibration mathematics, candidate acceptance, assignment method/gap, native IPF tolerance, 12D/11D calculation, GEH/IDP/Pareto guards, path-cache semantics and supply gate remain unchanged. R4 changes restart orchestration and deterministic authority selection only.

## Live boundary

No real PTV Visum execution was possible in the offline build environment. Therefore:

- `real_visum_tested = false`
- `calibration_complete = false`
- `production_ready = false`

The next required action is a live run from the exact B0016 checkpoint.
