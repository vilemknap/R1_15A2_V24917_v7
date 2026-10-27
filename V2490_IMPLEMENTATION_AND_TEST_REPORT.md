# V2.4.9.0 implementace a testy

## Implementace

- nový hash-locked FineCDF authority `reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py`;
- survey mobility CDF = soft directional reference, nikoli exact-fit constraint;
- inner FineCDF odmítá mikrozlepšení pod 0.1 %;
- full-realization TD gate vyžaduje >=0.5 % agregované selected improvement;
- selected/nonselected per-component trade-off max 5 %;
- global IDP mean/worst bounded 0.01/0.05 absolute;
- CAL GEH² guard 0.5 %, observation/protected/severity gates nezměněny;
- soft-rejected realized candidate backtrackuje na menší scale;
- všechna soft zamítnutí po technicky úspěšných realizacích => verified-parent `SOFT_REFERENCE_PLATEAU`;
- native IPF tolerance unchanged; exhaustion fail-closed;
- TD read-back freeze: exact context+metadata, numeric b/c abs 1e-8 / rel 1e-10;
- V2489 persistent path-cache predecessor je explicitně hashově pinovaný.

## Testy před release wiring

Focused TD/release suite: 35 passed.
Plná source-tree regrese před finálním balením: 657 passed, 0 failed.

Finální package verifier, clean extract, tamper gate a cloud readback se zapisují do CP23 evidence.
