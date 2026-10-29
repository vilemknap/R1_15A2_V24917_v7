# V24917 – oprava V240_OP20_SCOPE_AUTHORITY_FAILED (29. 10. 2026)

## Rozsah a zdrojové důkazy

**Nový skutečný běh:** `RUN_20261029_230508_775915` (PTV Visum 2026). `00_RESULT(20261029-221607).json`: `status=FAILED`, `error=V240_OP20_SCOPE_AUTHORITY_FAILED`, `accepted_count=0`, `completed_demand_cycles=0`. Výjimka vznikla v `r1_15a2_trial_adapter_v240.py:72` během `preflight`, před `BASELINE_FULL_RECOMPUTE`. Zdrojový/working-copy sémantický hash byl v tomto běhu **shodný**: `4c9fefa9e2c8e129b2efa37eae3c34d270253344a44543ec61fb1bfb1d358005`.

`00_V240_ASSIGNMENT_SCOPE(2).json` dokazuje výlučné chyby `OP_17_INACTIVE`, `OP_18_INACTIVE`, `OP_19_INACTIVE`. Zároveň `OP20=ACTIVE=1`, `OPERATIONTYPE=101`, `DSEGSET` = všech 14 požadovaných DSeg (PASS). `00_PROCSEQ_AUDIT_SUMMARY(10).json` je PASS a obsahuje jedinou aktivní assignment operaci 20. `COM_API_PREFLIGHT(10).json`: všech 132 kontrol PASS v read-only API auditu.

**Příčina:** historický V239 `audit_assignment_scope` vyžaduje `ACTIVE=1` i pro OP17/18/19, které jsou pouze dílčí alternativy. Předčasně je odmítne, aniž přečte jejich `DSEGSET`. Jde o nesoulad mezi finální OP20 autoritou a požadavkem na aktivaci pomocných operací, nikoli o chybu 14 DSeg finální OP20.

## Implementace v této větvi

1. `r1_15a2_preflight_explain_v24917.py`: přidává read-only V24917 wrapper `_wrap_inactive_partial_scope_audit` a instaluje jej do `r1_15a2_trial_adapter_v240.audit_assignment_scope`. Původní funkci V239 a její historickou pečeť **nemění**.
2. Wrapper smí znovu ověřit **výhradně** `OP_17_INACTIVE`, `OP_18_INACTIVE`, `OP_19_INACTIVE`. Každá neaktivní dílčí operace musí existovat, zůstat typu 101 a mít přesné normalizované, neduplicitní `DSEGSET`. Jinak vrátí konkrétní `OP_n_DSEGSET`, `OP_n_UNREADABLE` nebo `OP_n_ACTIVITY_OR_TYPE_DRIFT` a pokračování zamítne.
3. Všechny ostatní chyby původního auditu zůstávají tvrdé; zejména chybějící/neaktivní OP20, špatný typ OP20 nebo odchylka jejího 14-DSeg rozsahu. Pro trial se nadále vybírá **pouze OP20** a žádná operace se nesmí automaticky aktivovat.
4. `tests/test_v24917_preflight_op20_partial_activation.py`: syntetický přesný reálný stav OP17/18/19 inactive, OP20 active; chyby scope/typu; chybná finální OP20; kombinace aktivity a integrace do `V240.preflight`.
5. `tests/test_v24917_longmask_09c_live_scope_regression.py`: doplněn scénář jediného aktivního OP20 pro maskovací třífázový řetězec; test izoluje dynamicky importované helpery po historickém purgování modulů ostatními testy (řeší nestabilitu kompletního pytest běhu).
6. `V24917_RUNTIME_MANIFEST.json` a `DIAGFAST_V1_RELEASE_MANIFEST.json`: reseal jen relevantních hashů, plus registrace nového testu. `.github/workflows/previsum-v24917-failure-guards.yml`: cílená V240 regrese + kompletní sady na Pythonu 3.13 a read-only ověření hashů.

**Nedotčeno:** V239 historický soubor, nativní definice OP5/6/17–20, matice a OSRM distance, TG/TD / LONG/SCHOOL metodika, 248 CAL profilů, váhy counts/IDP, koeficienty, gap, akceptace, rollback, source `.ver`.

## Ověření a hranice tvrzení

- Testovací příkazy v CI workflow: `python -m py_compile`; `python -m pytest -q -p no:cacheprovider` pro V240/09C/LONGMASK, working-copy diff, celý `tests`, `diagfast_tests`, `genfix2_audit_tests` (oddělené procesy).
- Platný skutečný stav testů vždy viz odkaz **GitHub Actions aktuální větve**; žádný test `LIVE_VISUM` ani Windows COM zde neproběhl.
- Starší `WORKING_COPY_SEMANTIC_IDENTITY_MISMATCH:operations_hash` se **v tomto novém běhu neprojevil**. Rozpoznání změněné operace při recidivě stále zajišťuje `WORKING_COPY_OPERATIONS_DIFF.json`; toto bezpečnostní pravidlo není uvolněno.
- Předchozí `LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH` má samostatnou opravu v rodičovské větvi, kterou tato větev přebírá.
- Při testech je rozdíl `PASS` (offline simulace) vs `LIVE_VISUM_NOT_RUN` (reálná validace).

## Další bezpečný test na uživatelově PC

Stáhnout **celou GitHub větev jako ZIP**, rozbalit do jedné **nové složky**, neprohazovat jednotlivé soubory do původního balíčku. V PTV Visum načíst ručně původní `R1_novy_start.ver` a spustit stávající `01_SPUSTIT_V24917_TDJOINT1.py`. Nejprve zkontrolovat `PREFLIGHT/00_V240_ASSIGNMENT_SCOPE.json`: očekává se PASS s `validated_inactive_partial_operations=[17,18,19]`, `selected_trial_assignment_operations=[20]`. Následně se musí podařit `BASELINE_FULL_RECOMPUTE` a věrohodná OP20 GAP/12D/11D kontrola. Při nové chybě poskytnout aktuální `00_RESULT.json`, `00_V240_ASSIGNMENT_SCOPE.json` a `LONG_MASK_EXECUTION_PLAN.json`.

**Nespouštět dlouhý běh 100 cyklů, dokud není úspěšně prokázán první nativní přepočet.**
