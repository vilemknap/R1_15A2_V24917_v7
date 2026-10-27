# V2.3.2: Already-converted R1 Obs RPDI and 90 historical urban counts

- Retain approved CSD2022 roster: 408 (372 CAL, 36 VALID).
- Include exactly 90 of 127 historical urban profiles, those with R1 Active=1 (CAL).
- All 37 inactive historical profiles remain excluded; 36 deleted CSD remain excluded.
- Authoritative observation is only `R1 Obs RPDI`: converted passenger cars, no new time, mode, motorcycle, van, or vehicle-class conversion.
- City scope is BOTH: reconstruct model using two *physical* directed Visum Links with same LinkNo and reversed From/To nodes.
- Fail closed if the reverse physical link is absent. Never halve or duplicate the observed value.
- Store original source year 2014/2018/2019 and original source vehicle scope strictly as provenance.
- Preserve R1 Weight=0.9 for city vs 1.0 for CSD; use weights in shared CAL GEH2 objective and generation guidance.
- Update both generation path incidence and ADDVAL1 actual-path collector/sequence solver to include both directional keys per city observation.
- Supply path proof and parity remain required and do not use VALID observations as drivers.
- New 12D helper `R1_12D_CSD408_CITY90_RPDI_498_APPROVED.py` with two sealed CSV authorities.
- Older 12D helpers, masters and configs are retained for provenance, not active under V2.3.2.
- Default apply=false; CSD mapping/colocated-count review and CITY reverse-link review both block APPLY until acknowledged.

### Important
No live PTV Visum 2026 exercise was performed; offline tests use deterministic COM-shaped mocks. This update does NOT establish all 90 reverse directions exist in the current live network. Full source authority and precise mapping require live QA.
