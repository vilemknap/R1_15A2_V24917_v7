# R1 15A2 V2.3.2 - Complete observation roster (offline only)

## Authoritative inputs

The user's 2026-10-15 CountLocations spreadsheet contains 535 locations: 408 current CSD 2022 (372 CAL + 36 VALID), plus 127 legacy urban profiles (90 active CAL + 37 inactive). The exact active roster in V2.3.2 has 498 rows: 462 CAL + 36 VALID. The model does not restore the 36 deliberately deleted CSD locations.

Both CSV authorities are sealed by SHA256 and staged next to the 12D executable; the original user spreadsheet is preserved under authorities/source. Only the column **R1 Obs RPDI** is an observed intensity; values are already converted to passenger-car RPDI. `R1 Obs Value`, `R1 Obs Scope`, original vehicle classes and original measurement year do not trigger any additional conversion.

**CITY BOTH** compares this observed passenger-car RPDI to the *sum* of directional model car flows for `(LinkNo, FromNodeNo, ToNodeNo)` and `(same LinkNo, ToNodeNo, FromNodeNo)`. It is not averaged or halved. Both physical links must exist in live Visum; a missing reverse direction blocks the 12D gate instead of treating the value as unidirectional. LNV/NV freight remains excluded from the passenger-car GEH.

Relative priority is controlled by exported `R1 Weight`: 0.9 for each active CITY and 1.0 for each CSD; the shared CAL GEH2 loss and generation guidance honor it. VALID is report only.

`ActualRouteCollector`, exact route-sequence proposal and generation sparse-incidence each use both directional keys for a BOTH observation. When an assignment path runs in either direction, it contributes to the *same* CITY model/driver; there is no double-counting of the CITY observed target.

## Run

1. Unpack archive with all files and authorities.
2. Open the accepted `.ver` containing the current CountLocations, both physical link directions, all supply and demand matrices, IDP distance skims and saved routes.
3. Run `R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_2.py` manually from Visum Script Run, not as an active Procedure Sequence operation.
4. Keep default `apply=false`. Inspect 12D source-group summaries and `19_CSD408_CITY90_AUTHORITY_CHECK.json`.
5. Verify all 90 city reverse-link mappings and the pre-existing CSD duplicate/review flags.
6. Only after distinct assignment operation IDs/types, convergence GAP and demand frozen-state authority are established, consider an explicitly approved APPLY trial. The master intentionally blocks APPLY until both QA acknowledgements are set in config.

Do not use V2.3.1's 408-only 12D as the measurement authority for this version. Do not modify the original Excel's R1 Obs RPDI values.

### Limitations
- The actual live reverse-link availability and measurement station semantics have not yet been verified.
- Some CSD CountLocations share a directed physical link with conflicting observed counts, as documented in V2.3.1.
- Original historical vehicle labels were carried only as audit metadata. This does not imply a new car/vehicle conversion was calculated here.
- A future operator change to the CountLocation roster or RPDI values requires an explicitly resealed new authority rather than silently updating the source.
