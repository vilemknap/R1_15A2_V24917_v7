# R1 15A2 V2.4.8.7 — živá autorita zonálních kalibračních koeficientů

## Účel verze

V2.4.8.7 opravuje chybný předpoklad ve V2.4.8.5/V2.4.8.6, že hodnoty `3` pro `ADD_*`/`ADD_SALARY` a `10` pro `ZAHR_*` jsou hard bounds. Nejsou. Jde o kalibrační koeficienty a jejich aktuální hodnota v právě otevřeném modelu je numerickou autoritou.

Oprava proto nezvyšuje jeden magic number na jiný. Absolutní horní strop je z produkční Generation větve odstraněn.

## Nový kontrakt

Pro násobné koeficienty:

```text
proposed = current_live_value * exp(requested_log_step)
```

Platí:

- aktuální živá hodnota může být vyšší než historických 3 nebo 10;
- navržená hodnota může být vyšší než historických 3 nebo 10;
- krok je stále omezen `generation_step_schedule`, backtrackingem a `min_add_log_step`;
- hodnota musí být konečná a nezáporná;
- nulové koeficienty se řídí existující `preserve_zero` politikou;
- žádný řádek se nesmí aktivovat mimo způsobilou zónu nebo mimo aktivní vzorec.

Pro `ADD_SALARY`:

```text
proposed = current_live_value + bounded_delta
```

Neplatí už clamp do intervalu 0–3. Zůstává:

- maximální absolutní změna za blok;
- konečnost;
- platná doména salary faktoru;
- `factor_floor`;
- společné rozložení efektu mezi `ADD_ATT_W` a `ADD_SALARY`.

## Co se nezměnilo

Nejsou relaxovány acceptance/quality gates:

- `max_generation_effect_log_error`;
- `max_generation_pa_relative_gap`;
- solver/projection convergence;
- nové GEH20/GEH30;
- protected profily;
- IDP degradační limity;
- čerstvý Visum assignment;
- živé 12D/11D diagnostiky;
- rollback a reprodukovatelné opakované aplikování.

Absolutní coefficient cap byl odstraněn; matematická a dopravní validace nikoli.

## Dodaný export zón

Soubor `ZONE-2026-10-16-21-09-22.xlsx` byl použit jako auditní snapshot, ne jako zdroj mezí. V tomto konkrétním exportu jsou maxima například:

- `ZAHR_PROD_WORK = 10`;
- `ZAHR_PROD_SERV = 10`;
- `ZAHR_ATR_WORK = 8`;
- `ZAHR_ATR_SERV = 8`;
- domácí `ADD_*` přibližně 1,1;
- `ADD_SALARY` přibližně 1,2.

Tyto hodnoty popisují snapshot. Nejsou hard bounds. Živý model může obsahovat větší koeficienty a V2.4.8.7 je přijme, pokud jsou konečné a formula-valid.

Audit je v:

```text
V2487_ZONE_COEFFICIENT_AUTHORITY_AUDIT.json
V2487_ZONE_COEFFICIENT_AUTHORITY_AUDIT.csv
```

## Reálným pádem tvarovaný replay

Návrh z neúspěšného V2484 běhu byl přehrán nad novou logikou:

```text
projection rows: 1374
clipped rows:    0
zone 619 ZAHR_PROD_WORK: 10 -> 10.789216458...
zone 619 ZAHR_PROD_SERV: 10 -> 10.393926399...
WORK P/A relative gap:    ~1.0e-15
SERVICE P/A relative gap: ~8.2e-13
max effect log error:     ~1.1e-16
```

Jde o čistý proposal replay, nikoli o náhradu živého Visum assignmentu.

## Spuštění

Rozbal celý balík do nové složky, například:

```text
C:\Users\vilem_knap\Documents\VISUM\v45\2022\R1_15A2_V2487
```

Spusť:

```text
R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_7.py
```

přes `Scripts -> Execute script file`.

Nový run musí vzniknout pod:

```text
C:\Users\vilem_knap\Documents\VISUM\v45\2022\R1_15A2_V2487_RUNS\RUN_...
```

Persistentní path cache nemaž:

```text
%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248
```

## První živé kontroly

V `GENERATION_DESIGN.json` ověř:

```text
summary.generation_coefficient_authority.mode = LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP
summary.generation_coefficient_authority.legacy_absolute_upper_bounds_enforced = false
summary.bound_constrained_projection.clipped_count = 0
```

U zóny 619 se očekává, že `ZAHR_PROD_WORK` a `ZAHR_PROD_SERV` mohou dostat návrh nad 10. Rozhodující není číslo 10, ale následný skutečný Visum výpočet a acceptance.

## Stav ověření

Offline vývoj a regrese jsou dokončené. Skutečný živý PTV Visum běh V2.4.8.7 musí ještě proběhnout.
