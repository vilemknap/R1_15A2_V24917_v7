# R1 15A2 V2.3.1 — First live Visum run checklist

**Do NOT run V2.3 master for this CSD408 model.** Use the V2.3.1 master.

1. Open the accepted real R1 .ver corresponding exactly to the exported 535 CountLocations. Verify the 408 reserved CSD numbers (920001–920444 subset) remain unchanged.
2. Run with `R1_15A2_CONFIG_V2_3_1.json`, `apply=false`. The baseline 12D must report exactly 408 (372 CAL, 36 VALID) and `PASS_EXACT_APPROVED_ROSTER_AND_LIVE_VALUES`.
3. Check `12D_BASELINE` evidence for 19_CSD408_AUTHORITY_CHECK.json and 01_DETAIL_408_FORENSIC.csv. Confirm all live CountLocation physical links still exist and preserve original RPDI intensities.
4. Review 920214, 920215, 920418 (mapping scope review); and conflicting collocated sites 920259/920421 and 920260/920420 (same exact directed link, distinct observed values). Decide their modeling/weighting policy explicitly. Until then `csd408_mapping_review_acknowledged=false` prevents APPLY.
5. Confirm path export coverage, all 12 personal DSegs including CL/CF and exogenous EE, and actual path-link topology.
6. Fill verified `assignment_operations` and `gap_readback.attribute` in the V2.3.1 config; do not guess COM IDs or GAP fields.
7. Verify fixed OD, generation, b/c, link VDF/permissions, ADDVAL1 readback, and assignment gap before a single guarded APPLY.
8. No full production run until the above gates all pass.
