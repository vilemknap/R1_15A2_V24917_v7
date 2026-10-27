# R1 15A2 V2.4.6 — implementační a testovací report

## Základ

- runtime základ: CP03 `R1_15A2_V2_4_5_CP03_LIVE_PATHLEN_HOTFIX_20261016`;
- výkonová specifikace: CP02;
- nový release: `R1_15A2_V2_4_6_ADAPTIVE_PERFORMANCE_20261016`;
- nový launcher a config jsou oddělené, historický V2.4.5 launcher zůstává beze změny.

## Implementované oblasti

1. **CP03 zachován** — krátké run roots a helper workspaces, rollback state evidence před diagnostikou.
2. **Bulk COM read** — `GetMultiAttValues(attr, False)`, index-set a object-NO readback, scalar fallback.
3. **Adaptive path paging** — bounded fallback ladder, ochrana proti opakované stránce a překročení budgetu.
4. **Lazy Supply evidence** — incidence pro TG ihned, branch-pair evidence až při Supply, bez reexportu.
5. **First-sufficient search** — jen po původním live acceptance gate a minimálním zlepšení.
6. **Větší počáteční TG obal** — pouze rané cykly; finální stage obnovuje plný původní search envelope.
7. **FineCDF v1.8** — aktivní/stabilní bloky, adaptivní trust region, stále 512 CDF bodů a combined native verification.
8. **Progresivní TD** — bounded explore/refine, explicitní non-convergent progress state, finální úplné ověření.
9. **ADDVAL1 4/2/1** — explicitní amplitudy s all-path budgetem a všemi původními mezemi.
10. **Telemetrie** — atomická, append-only evidence bez vlivu na acceptance.

## Automatické testy

Testy pokrývají zejména:

- úplnou inherited V2.4.5 regresi;
- bulk/scalar parity a inactive-object argument;
- COM bulk failure, object-order mismatch a scalar fallback;
- adaptivní stránkování bez ztráty/duplicity;
- incidence-ready před deferred Supply evidence;
- ADDVAL1 amplitudy a impedance budget;
- first-sufficient bez obejití acceptance;
- progresivní TD a dvě úplné stationary iterace;
- globální STOP, který se nesmí změnit na progress-continue;
- tamper reference SHA/path a neplatné TG/TD schedules;
- atomickou telemetrii;
- nový uživatelský launcher, zdrojový `.ver` a finální SaveVersion;
- skutečný FineCDF v1.8 Runner nad COM-shaped backendem;
- reprodukovatelný performance benchmark s pravdivou boundary.

Aktuální výsledky se zapisují do release statusu při balení. Všechny testy jsou offline nebo COM-shaped fixture; žádný z nich není skutečný Windows PTV Visum COM běh.

## Benchmark

`V246_PERFORMANCE_BENCHMARK.json/.md` odděluje:

- naměřený syntetický controller;
- odvozené COM/page request counts z rozměrů živého běhu;
- skutečný Visum wall-time, který zatím zůstává `null`.

V syntetickém kompletním workflow V2.4.6 použila méně assignment/recompute volání než V2.4.5, ale skončila v jiném validním adaptivním stavu. Výsledek proto není vydáván za bitovou ani numerickou paritu.

## Truth boundary

Tento release je **offline-verified candidate**, nikoli production-ready model. K production statusu chybí živý Visum 2026 bounded gate a celý noční běh podle `LIVE_VISUM_ACCEPTANCE_V2_4_6_CZ.md`.

## Finální offline gate této dodávky

- `compileall`: PASS
- `pytest`: **554 passed, 0 failed, 0 skipped**
- nový FineCDF v1.8 source SHA je shodný s konfigurací;
- benchmark: `PASS_OFFLINE_EVIDENCE_ONLY`;
- package verifier a nezávislé rozbalení jsou součástí finálního balení.
