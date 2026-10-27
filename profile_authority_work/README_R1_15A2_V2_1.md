# R1 15A2 V2.1 — auditovaná actual-path multiblock kalibrace

## Účel

V2.1 kalibruje generativní model ve Visumu bez přímého přepisování OD matic:

1. z aktuálně uložených **skutečných PrT routes** sestaví profil × OD × DSeg incidence;
2. z CSD reziduí vypočte regularizovanou OD guidance;
3. guidance promítne do legitimních parametrů Trip Generation;
4. komponentní chyby DIST_KM promítne do samostatných parametrů `b,c` Visum DemandStrata;
5. po každém kandidátu provede TG → TD → realization → assignment → 12D + 11D;
6. kandidát přijme, nebo načte přesný `PRE.ver` a ověří rollback hashově i parametricky.

Výchozí konfigurace je **design-only** (`apply=false`).

## Kalibrované parametry

### Trip Generation

- `ADD_PROD_W`, `ADD_ATT_W`, `ADD_SALARY`
- `ADD_PROD_S`, `ADD_ATT_S`
- `ZAHR_PROD_WORK`, `ZAHR_ATR_WORK`
- `ZAHR_PROD_SERV`, `ZAHR_ATR_SERV`

`ADD_SALARY` není druhý volný zónový residual. Používá jednu regularizovanou centrovanou příjmovou bázi a zbytkový efekt zůstává na `ADD_ATT_W`, aby byl blok identifikovatelný.

ZAHR aktuátor je povolen jen v zóně, kde skutečný TG člen může působit: `ZAHR_SUSED > 0` a `POP_ZP_2022 > 0`.

### Komponentní Trip Distribution

Samostatný stav `b,c` je veden pro:

- 5 × WORK (`1_WORK_*`)
- 5 × SERVICE (`2_SERV_*`)
- 5 × LONG (`3_LONG_*`)
- 1 × SCHOOL (`5_SCHOOL`)

Bloky se proto jmenují `TD_COMPONENT_WORK`, `TD_COMPONENT_SERVICE`, `TD_COMPONENT_SCHOOL`, `TD_COMPONENT_LONG`. SCHOOL není samostatná assignment family; je to jedna komponentní křivka, která se downstream přidává do WORK/CW větve.

## Autority

- WORK/SERVICE/SCHOOL: čerstvé komponentní 11D targety.
- LONG: přiložená 12B křivka je pouze agregovaný `NATIVE_CL` guard. Nesmí se kopírovat na pět LONG komponent. Produkční `TD_COMPONENT_LONG` proto zůstane `NO_COMPONENT_LONG_AUTHORITY`, dokud nebude přiložena schválená 11E autorita s vlastními biny pro každou LONG komponentu.

Toto je úmyslný fail-closed stav, nikoli chybějící algoritmus. Syntetický test ověřuje funkci rozhraní pro explicitní component authority, ale syntetický target není produkční autorita.

## Důležité bezpečnostní kontrakty

- žádné `SetValues` nad OD maticí;
- CALIBRATION řídí návrh i ACCEPT/REJECT; 40 VALIDATION řádků je report-only;
- `observed <= 0` není demand actuator;
- do solveru vstupují pouze OD, jejichž oba endpointy mají skutečný aktuátor;
- po každém accepted/rejected kroku se incidence znovu vytvoří z čerstvého assignmentu;
- všechny změny mají live readback;
- Procedure Sequence musí obsahovat aktivní TG před TD a assignment po TD;
- konkrétní TG/TD operation musí být aktivní a obsahovat požadovaná strata;
- po rejectu se načte `PRE.ver` a kontrolují se matice, zónové parametry i `b,c`.

## Spuštění

1. Otevřít čistý pre-cluster `.ver`.
2. Assignment musí mít `Storage of paths = Save as routes`.
3. Spustit master s `apply=false`.
4. Zkontrolovat zejména:
   - `00_TG_DEPENDENCY_AUDIT.json`
   - `00_PROCSEQ_AUDIT_SUMMARY.json`
   - `03A_PATH_EXPORT_SUMMARY.json`
   - `05C_PATH_PARITY_SUMMARY.json`
   - generation/TD candidate CSV
   - LONG authority status.
5. Teprve po PASS nastavit `R1_15A2_V21_APPLY=1` a ponechat `max_accepted_blocks=1` pro první živý krok.

## Vstupní soubor

`R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py`

## Truth boundary

Balík prošel offline unit, randomized sparse stress, COM-stub a synthetic E2E testy. Nemohl být v tomto prostředí spuštěn nad živým PTV Visum 2026; první live design-only běh je proto stále povinný integrační gate.
