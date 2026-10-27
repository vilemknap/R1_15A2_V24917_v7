# R1_IDP_DISTRIBUTION_AUTHORITY_V1

Current authority bundle rebuilt from IDP_AMDY_17_STRATA_EXTRACTOR V5 output exported at 2026-10-06T16:11:54.645Z.

Status: PASS / PASS_EXTRACTED_AUTHORITY_LONG_MIXTURE_DEFERRED.

Backend contract:
- DIST_KM is the active behavioral distribution authority for component-level calibration.
- TIME_MIN is kept only as a diagnostic export; it must not be bound as backend constraint.
- WORK, SERVICE and SCHOOL have finalized 0-100 km target curves.
- LONG has 100-200 km purpose-basis curves only; component mixtures remain PENDING_BASELINE_SIMPLEX_FIT.
- FOREIGN has no domestic IDP target.

Files:
- R1_IDP_DIST_KM_TARGET_CURVES_V1.csv
- R1_IDP_TIME_MIN_DIAGNOSTIC_CURVES_V1.csv
- R1_IDP_LONG_DIST_KM_BASIS_V1.csv
- R1_IDP_LONG_TIME_MIN_DIAGNOSTIC_BASIS_V1.csv
- R1_IDP_TARGET_SUMMARY_V1.csv
- R1_IDP_COMPONENT_AUTHORITY_STATUS_V1.csv
- R1_IDP_WEIGHTS_GLOBAL_HYBNOST_V1.csv
- SOURCE_MANIFEST_V1.json
