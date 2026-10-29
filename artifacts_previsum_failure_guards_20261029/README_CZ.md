# Stabilizace před Visum: LONGMASK, SOURCE / WORKING_COPY

Datum: 2026-10-29. GitHub základ: `codex/fix-longmask-09c-partial-assignment-20261029`, commit `d0e1223045ccfff79558f989d0d4ea75ea709b4b`.

## Úkol / bezpečnostní hranice
Opravit známý živý pád `LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH` a ověřit bezpečnost již dříve zavedené diagnostiky `WORKING_COPY_SEMANTIC_IDENTITY_MISMATCH:operations_hash`, **před** dlouhou kalibrací, bez změny metodiky TG/TD, bez kalibračního běhu a bez zásahů do uživatelova Visum.

## Co skutečně víme z nahraných důkazů

- `RUN_20261029_224737_496385`: `status=FAILED`, `BASELINE_FULL_RECOMPUTE`, `accepted_count=0`, `completed_demand_cycles=0`, chyba `LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH`.
- `00_SUPPLY_ASSIGNMENT_PLAN.json` prošel: jediná schválená finální PrT assignment/GAP autorita = **OP20**. V proceduře jsou ale také tři **aktivní dílčí** assignmenty OP17–19, které smějí běžet před OP20. Původní LONGMASK chybně zaměňoval množinu všech aktivních 101 za množinu finálních autorit.
- `SOURCE_SEMANTIC_RESTART_AUTHORITY.json` a `00_RESULT.json` tohoto běhu uvádějí **shodnou** zdrojovou i pracovní sémantickou autoritu `f0b8c4d8acbc2736a94a4732fd803d87fcd02b10dc540d469002fb790263a95c`. V tomto konkrétním běhu se tedy starší chyba `operations_hash` nevyskytla.
- Ve starším odděleném běhu vznikla `WORKING_COPY_SEMANTIC_IDENTITY_MISMATCH:operations_hash`; skutečná změněná operace **není v dostupných hashových důkazech identifikovatelná**. Nebylo legitimní shodu obcházet. Existující `r1_15a2_snapshot_reads_v24917.py` publikuje před vyhozením chyby `WORKING_COPY_OPERATIONS_DIFF.json` s přesnou změněnou operací.
- `DIAGFAST_DIRECT START` ze screenshotu je informační výpis, nikoli chyba. Jeho ztišení je samostatná UX úprava, která nepřispívá k opravě kalibračního pádu.

## Co opravuje tato větev

- `r1_15a2_long_post_td_mask_v24917.py`: zachovává jedinou finální autoritu OP20; dovoluje pouze prověřené dílčí OP17 (LNV/NV), OP18 (CF/CL) a OP19 (CS/CW + noT), kontroluje jejich přesné DSEGSET proti skutečnému Visum a odmítá neznámé operace, chybějící OP20, duplicitní schválení i špatný OPERATIONTYPE.
- Nově je finální OP20 DSEGSET ověřeno i při supply-only aktivaci bez OP17–19, pokud je v konfiguraci deklarováno. Bez deklarovaného DSEGSET zůstává původní minimální testovací fixture kompatibilní; živá V24917 konfigurace má deklarovaných všech 14 DSeg.
- `tests/test_v24917_longmask_09c_live_scope_regression.py`: regresní testy pro živý model 09C, finální/částečné autority, support mask, nezměněné ACTIVE a chybové stavy.
- `V24917_RUNTIME_MANIFEST.json` a `DIAGFAST_V1_RELEASE_MANIFEST.json`: aktualizované SHA256 změněného runtime a testu, původní vědecké autority beze změny.
- `.github/workflows/previsum-v24917-failure-guards.yml`: izolované offline testy na Pythonu 3.13 a plné sady v oddělených procesech; žádný přístup k Visum, žádné modelové COM zápisy.

## Ověření / omezení
- `python -m py_compile` produkčního modulu a regresního testu.
- GitHub Actions: `python -m pytest -q -p no:cacheprovider tests/test_v24917_longmask_09c_live_scope_regression.py tests/test_v24917_long_post_td_mask.py`: **28 PASS** v dřívějším běhu před rozšířením celých sad.
- GitHub Actions: `python -m pytest -q -p no:cacheprovider tests/test_v24917_working_copy_operation_diff.py`: **13 PASS** ve stejném běhu.
- Celé hlavní / DIAGFAST / auditní sady přidány do workflow; jejich aktuální konečný stav je vždy na GitHub Actions, nikoli v tomto statickém README.
- `LIVE_VISUM_NOT_RUN`. Žádná opravná verze není prohlášena za definitivně validovanou.

## Bezpečný další krok ve Visumu (teprve po PASS offline sad)
1. Rozbalit celý ZIP této jedné stabilizační větve do NOVÉ složky, nemíchat se staršími soubory. Na zdrojové `R1_novy_start.ver` nic nepřepisovat.
2. Ručně otevřít zdrojovou `.ver` a spustit stávající `01_SPUSTIT_V24917_TDJOINT1.py`. Tato větev není silent; kritické chyby musí zůstat viditelné.
3. Nejprve ověřit `BASELINE_FULL_RECOMPUTE` a `LONG_MASK_EXECUTION_PLAN.json`: `final_assignment_authority=[20]`, `validated_partial_assignments=[17,18,19]`, TD→maska 9111..9115→realizace→maska 9291..9295, 9305→OP17..20.
4. Pokud znovu selže source/working-copy identita, dodat jediný soubor `WORKING_COPY_OPERATIONS_DIFF.json`. Bez konkrétních změněných atributů se nesmí vypnout `operations_hash` ani tvrdit, že byl starší problém opraven.
5. Až po úspěchu těchto bran povolit krátký řízený kandidát a ověřený rollback. Zatím **nepouštět 100 cyklů**.

## Nedotčené invariants
Žádná změna kalibračního objektivu, počtu profilů 248 CAL, count/survey vah, b/c, mobility, SHORT/LONG/SCHOOL alokace, IPF tolerance, OSRM `>=80 km` podpory, POVOLENÉHO úbytku LONG objemu, FOREIGN, zdrojové `.ver`, akceptačních bran ani native rollbacku.

Tato oprava **nevyřešila** neznámou příčinu staršího občasného `operations_hash`; jen ji bezpečně diagnostikuje a odmítá.
