# Live Visum acceptance — V2.4.9.2

## Povinný bounded test

1. Start z bezpečného accepted checkpointu po vyhodnocení V2.4.9.0.
2. Ověřit run root `R1_15A2_V2492_RUNS` mimo staré run stromy.
3. Ověřit restore persistentní path cache bez nové enumerace, pokud state binding sedí.
4. Ověřit vznik `00_GENERATION_COEFFICIENT_REFERENCE.json`.
5. Generation design musí obsahovat kladné i záporné zonální kroky, pokud je
   živá evidence vyžaduje; žádný syntetický požadavek na oba směry se nevynucuje.
6. Ověřit hard envelope a inward-only chování hodnot již mimo envelope.
7. Ověřit P/A relative gap a čerstvý assignment + 12D/11D acceptance.
8. Po cyklu 5 ověřit aktivní stage `DISTRIBUTION_FOCUS` a family-total limit 0.005.
9. TD musí dál končit `REALIZED_AND_ACCEPTED` nebo `SOFT_REFERENCE_PLATEAU`.

## Povinné soubory

- `RUN_ROOT_AUTHORITY.json`
- `PERSISTENT_PATH_CACHE_RESTORE.json`
- `00_GENERATION_COEFFICIENT_REFERENCE.json`
- `GENERATION_SIGNED_REFINEMENT_AUDIT.json`
- `GENERATION_DESIGN.json`
- `TRIAL_RESULT.json`
- `TD_PARAMETER_FREEZE_AUDIT.json`
- `TD_SOFT_REFERENCE_ACCEPTANCE.json`

## Acceptance

Release nelze označit `production_ready=true`, dokud reálný Visum běh
neprokáže signed korekci, rollback, checkpoint a následný TD průchod.
