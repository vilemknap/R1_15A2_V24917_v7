# First PTV Visum run checklist - V2.3.2

1. Use accepted `.ver`; script execution is manual and `apply=false`.
2. Verify all 498 approved active CountLocations: CSD 408 (372/36), CITY90 (90/0). All other 37 inactive urban profiles excluded.
3. Verify exact sealed R1_OBS_RPDI values; never multiply by original source-class fractions or apply another annual conversion.
4. Verify for each CITY CountLocation that the physical LinkNo and both node directions are present in Visum Net.Links; check no duplicate/broken reverse mappings.
5. Compare 12D `01_DETAIL_498_FORENSIC.csv`, `02B_BY_SOURCE_GROUP.csv`, and `19_CSD408_CITY90_AUTHORITY_CHECK.json`.
6. For all native and EXOG_EE PrT DSegs, verify actual saved paths parity to BOTH and directed CountLocations.
7. Validate no use of 36 VALID as design or objective targets.
8. Resolve 3 CSD mapping-review flags and 2 contradictory co-located CSD count pairs before APPLY.
9. Explicitly determine assignment-only operation IDs / DSeg scope / gap readback, and frozen OD SHA gates.
10. Only then acknowledge CSD and CITY QA; consider one bounded ADDVAL1 trial with exact PRE rollback.
