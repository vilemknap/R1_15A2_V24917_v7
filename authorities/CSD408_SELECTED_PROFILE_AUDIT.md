# CSD408 profile selection audit

From the user-approved Excel export: **535 rows total**, of which **408** have CSD2022 identifiers (920001–920444, noncontiguous) and **127** are R1LC (912xxx) and outside this calibration. The surviving 408 have **372 CAL** and **36 VALID**, and match the frozen historical CSD2022 values. The missing **36 original IDs** are deliberately not used:

920018, 920034, 920228, 920229, 920289, 920290, 920295, 920296, 920301, 920302, 920309, 920310, 920317, 920318, 920321, 920322, 920323, 920324, 920335, 920336, 920337, 920338, 920339, 920340, 920345, 920346, 920347, 920348, 920371, 920372, 920373, 920374, 920405, 920406, 920413, 920414

**Physical directed-link remaps:** 12 preserved CountLocations have updated physical `LinkNo/FromNodeNo/ToNodeNo`; the stale UDA keys are archived in the CSV but never used to locate modeled flow.

**Mapping review:** 920214, 920215, 920418 remain included and flagged.

**Physical link duplicates with incompatible observed values:**

| Directed physical link | CountLocation | CSD2022 observed RPDI |
|---|---|---:|
| 2003608 / 1000670 → 1000663 | 920259 | 2103 |
| 2003608 / 1000670 → 1000663 | 920421 | 1373 |
| 2003608 / 1000663 → 1000670 | 920260 | 2103 |
| 2003608 / 1000663 → 1000670 | 920420 | 1373 |

No changes to the user's approved selection, to weights, roles, or observed values have been made to resolve these. This is an explicit scientific QA issue for APPLY review; do not silently pick one target.
