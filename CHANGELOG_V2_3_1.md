# V2.3.1 CSD408 authority hotfix

- User explicitly approved the exact CountLocations remaining after deliberate network/count-location deletion, not the former 444 references.
- Added immutable 408-row CSV authority from user XLSX, original workbook copy and QA report.
- New 12D script loads approved CSV, checks SHA256 and validates exact roster, obs values, role, active flag and physical directional link.
- 12 physical link remaps adopted from actual Visum `LinkNo/FromNodeNo/ToNodeNo`, not stale `R1 Link No` UDAs.
- 127 unrelated CountLocations out of CSD selection; 36 historical CSD CountLocations intentionally out.
- Selectable 12D helper with staged manifest copy inside runtime; old 444 helper retained unmodified.
- Expected 408/372/36 in V2.3.1 configuration.
- QA warning/explicit APPLY gate for 3 `MAPPING_SCOPE_REVIEW` and two collocated directional links with different observations.
- V2.3 path-sequence solver and IDP authority are unchanged.
- Offline tests and fake-COM read/export stage only; no live Visum trial conducted.
