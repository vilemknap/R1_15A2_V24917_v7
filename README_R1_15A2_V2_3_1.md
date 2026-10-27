# R1 15A2 V2.3.1 — Approved CSD408 CountLocations

This branch preserves V2.3 actual-path sequence ADDVAL1 solver and updates the authoritative CSD2022 CountLocation roster to the user-provided 2026-10-15 export.

**Live Visum status: NOT TESTED. Default APPLY: false.**

## Observations

- Total CountLocations in user export: 535; CSD2022 408; unrelated R1LC records 127, excluded from CSD calibration.
- Exactly **372 CALIBRATION** profiles determine proposals, objective, acceptance, protected-profile guards and stop logic.
- Exactly **36 VALIDATION** profiles are report-only; never design or acceptance inputs.
- The 36 removed CSD2022 profiles are intentionally absent. They are NOT errors and must not be restored or replaced without a new approved export.
- All 408 retained CSD ID/Code/profile_id/role/observed RPDI values agree with the previous historical 444 manifest.
- No IDs are renumbered. Exclusion is exact by 408-row roster, not a crude range-size check.

## Link mapping

The **live physical** `CountLocation.LinkNo,FromNodeNo,ToNodeNo` exported by Visum is the mapping authority. `R1 Link No`/`R1 From Node`/`R1 To Node` are stale for 12 CountLocations; those original UDA values are retained only as historical evidence. The approved CSV contains the correct physical link keys.

- 12 preserved CountLocations had a physical directed-link remap vs the historical manifest.
- 3 CountLocations are marked `MAPPING_SCOPE_REVIEW`: **920214, 920215, 920418**.
- Two different CSD sites map to the SAME physical directed link in both directions: **920259 (2103) vs 920421 (1373)**, and **920260 (2103) vs 920420 (1373)**. These conflicting targets are deliberately not silently reweighted, merged, or discarded. A single model link flow cannot equal both observed values simultaneously.
- Acknowledgement of the three review flags and duplicate-link modeling decision is required before live APPLY. `csd408_mapping_review_acknowledged` is **false** by default.

## Runtime behavior

Run `R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_1.py` from **Visum > Scripts > Run script file** with the current .ver open. Do not embed the master as a Procedure Sequence operation.

The master loads `R1_15A2_CONFIG_V2_3_1.json`, which selects `R1_12D_CSD2022_GEH_FORENSIC_408_APPROVED.py`. The runtime stages the approved CSV directly beside the helper (the helper executes from a per-run working folder). The CSV's SHA256 is checked in both stages. The 12D helper aborts on missing/new CSD profile ID, incorrect obs/role/code/scope, different physical directional mapping, missing live directed link, incorrect active flag or weight. The 127 non-CSD CountLocations are ignored. Diagnostic output is `01_DETAIL_408_FORENSIC.csv`. Old 444 script and legacy configuration remain for provenance, but are **not** the V2.3.1 active authority.

The existing V2.3 actual saved-path route-sequence ADDVAL1, frozen-demand assignment, shared objective, generation/TD blocks and rollback are otherwise not changed. IDP 11D source and distribution curves are untouched.

## Required live gates

1. `apply=false` first; use exact .ver matching the approved CountLocation roster and physical links.
2. 12D full authority PASS (408; 372/36, all exact IDs and values). Resolve mapping reviews and collocated observations before setting QA acknowledgment to true.
3. Confirm 12D reconstruction from full DSeg passenger assignment and path parity.
4. Confirm true assignment-only operation IDs, DSeg scope, convergence-gap readback and immutable demand matrices.
5. Only after these are approved consider one bounded live supply candidate with exact rollback.

## Verification

The static and synthetic tests must not be treated as a real PTV Visum 2026 run. The complete 12D read/export stage was exercised with **mock COM-shaped** objects for all 408 observations (PASS); the physical link mapping and values were checked against the workbook extract. This does not prove real live Visum paths, operations or observed network permission coverage.
