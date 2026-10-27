# R1 15A2 V2.4.6 — adaptivní výkonová verze

**Release:** `R1_15A2_V2_4_6_ADAPTIVE_PERFORMANCE_20261016`

V2.4.6 je nová spustitelná větev postavená na posledním opraveném CP03. Zachovává opravy nulových linkových tras, rollbacku, checkpointů a krátkých pracovních cest z CP03 a implementuje bezpečně realizovatelnou část výkonového návrhu CP02.

## Co se proti V2.4.5 změnilo

### Režie a COM

- hromadné čtení devíti linkových atributů přes `GetMultiAttValues(attr, False)`;
- nezávislé ověření identity každého linku a povinný scalar fallback;
- adaptivní stránkování Visum listů `2048 → 1024 → 512 → 256 → 80`, bez neomezeného fallbacku;
- atomická výkonová telemetrie pro nativní výpočty, rollbacky, diagnostiky, SaveVersion, COM čtení a path export.

### Trip Generation

- první dva vnější demand cykly používají větší, explicitně omezený návrhový obal:
  - `max_od_relative_up = 0.12`,
  - `max_add_log_up = 0.08`,
  - `salary max_abs_delta_per_block = 0.08`;
- od následných cyklů se výpočet vrací k původnímu plnému V2.4.5 obalu `0.08 / 0.04 / 0.04`;
- první kandidát lze přijmout bez zkoušení menších kroků jen tehdy, když již prošel původním live assignmentem, společným objective a všemi acceptance gates a překročil minimální relativní zlepšení;
- žádný „first sufficient“ výsledek se nepovažuje za konvergenci.

### Trip Distribution / FineCDF v1.8

- zachováno všech 512 bodů IDP CDF, nativní Visum Multi a kombinované ověření výsledného `b,c` vektoru;
- upravena line-search logika, aby blok na lokálním plateau nevynucoval zbytečné menší kroky pro ostatní bloky;
- rychlejší růst trust regionu po dobře fungujícím kroku;
- progresivní schedule:
  - cykly 1–2: `EXPLORE`, max. 4 iterace / 28 TD vyhodnocení,
  - cykly 3–4: `REFINE`, max. 10 iterací / 60 TD vyhodnocení,
  - cykly 5–12: `FULL_VERIFY`, původních 35 iterací / 180 vyhodnocení;
- raný ukončený rozpočet je stav `PROGRESS_CONTINUE_DEMAND`, nikdy stationarity ani povolení Supply;
- Supply se odemkne až po dvou po sobě jdoucích úplných TG→TD cyklech bez změny.

### ADDVAL1

- kandidáti mohou používat explicitní amplitudy `4, 2, 1` jednotka;
- amplituda je kontrolována proti `max_step`, kumulativnímu limitu, absolutním mezím a skutečnému all-path impedance budgetu;
- dopad kandidáta stále musí potvrdit nový nativní assignment a live diagnostika.

### Path cache

- Generation připraví jen export, parity a incidence potřebné pro TG;
- drahá ON/OFF divergentní/rejoin evidence se vytvoří až při skutečném vstupu do Supply;
- používá se tentýž accepted-state SQLite store, bez nového COM exportu;
- po změně accepted stavu je cache povinně invalidována.

## Co zůstává beze změny

- 498 observačních řádků a CAL/VALID role;
- FineCDF 512bodové targety a LONG autorita;
- nativní Visum Multi jako autorita distribuce;
- FOREIGN, fixed EE, LNV/NV a další chráněné vstupy;
- nový assignment pro každé přijímané Supply řešení;
- in-place rollback bez `LoadVersion`;
- reprodukovatelné opakované aplikování vybraného kandidáta;
- atomické rotační checkpointy a zachování zdrojového `.ver`;
- CP03 opravy path-length a rozlišení „stav obnoven / diagnostika selhala“.

## Výslovná změna semantics

V2.4.6 **není bitově identická akcelerace**. First-sufficient výběr, větší počáteční TG kroky, progresivní TD a větší ADDVAL1 amplitudy mohou vést jinou posloupností accepted stavů než V2.4.5. Všechny live acceptance a rollback gates však zůstávají povinné.

## Co nebylo aktivováno

Následující CP02 návrhy zůstávají záměrně mimo aktivní runtime, protože by před použitím potřebovaly samostatný živý důkaz ve Visumu:

- přenášení TD Jacobianu přes změnu P/A;
- výpočet jen části `DSTRATSET`, dokud nebude prokázána nezávislost sdílených cílových matic a reset semantics;
- paralelní kandidáti nad jednou sdílenou instancí Visumu;
- oslabení rollbacku, finálního combined TD verification nebo checkpointů.

## Spuštění

1. Rozbal celý ZIP do nové samostatné složky.
2. Ve Visumu 2026 otevři čistý autoritativní zdrojový model.
3. Spusť přes **Scripts → Execute script file**:

   `R1_15A2_FULL_OVERNIGHT_ADAPTIVE_V2_4_6.py`

4. Nespouštěj launcher jako krok Procedure Sequence a nekopíruj jej samostatně do CP03/V2.4.5 složky.
5. Výstupy jsou vedle projektových diagnostik v `R1_15A2_V246_RUNS/RUN_*`.

Hlavní stavové soubory:

- `00_RESULT.json`
- `00_PROGRESS.json`
- `CALIBRATION/RUN_STATUS.json`
- `CALIBRATION/PERFORMANCE/SUMMARY.json`
- `CALIBRATION/LATEST_ACCEPTED_CHECKPOINT.json`

Řízený STOP: vytvoř prázdný `STOP_REQUESTED` v aktivním `RUN_*` nebo v jeho rodičovské složce. Zastavení se provede až v bezpečném bodě po obnově/ověření mutovaného stavu.

## Stav ověření

- kompletní offline/regresní sada: viz `V246_IMPLEMENTATION_AND_TEST_REPORT.md`;
- syntetický COM-shaped user workflow: PASS;
- skutečný PTV Visum 2026 COM běh: **zatím neproveden v tomto prostředí**;
- produkční připravenost vznikne až po bounded live acceptance a následném úplném běhu.
