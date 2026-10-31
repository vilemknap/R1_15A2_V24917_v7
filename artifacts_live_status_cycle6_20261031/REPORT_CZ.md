# Dokončený TD cyklu 6

Z nahrané evidence stejného běhu `RUN_20261031_125929_863675`: **ACCEPTED_FINECDF_TD**, plná realizace škály **1,0**, všechny vnější akceptační kontroly prošly. Nejde pouze o nejlepší vnitřní kandidát. `DEMAND_CYCLE_06_RESULT.json` potvrzuje dokončenou realizaci i přijatý koncový stav.

## Vývoj šestého cyklu

| Stav | Vážené GEH |
| --- | ---: |
| Vstup do Generation C6, konec TD C5 | 22,743760 |
| Přijatá Generation C6 | 22,419918 |
| Rodič TD po mezilehlém přepočtu ICONG | 22,446912 |
| Přijaté TD C6 | **22,804861** |

Generation přijala první pokus, ale nezměnila LONG koeficienty (`longguard1.changed_long=false`). SupplyMix zkusil dva pokusy a oba odmítl kvůli `CAL_GEH_OBJECTIVE_NOT_IMPROVED` a `SHARED_OBJECTIVE_NOT_IMPROVED`. Jeho report obsahuje původní limity 12 skupin, 120 hran, 2 pokusy; nově dodaný rozšířený SupplyMix v tomto běhu ještě nebyl použit.

Vnější TD má **GEH +1,595 %**, IDP **0,490890 → 0,454964**, tedy **−7,319 %**. Společné skóre:

```text
F = 0,60 × 1,015946470 + 0,40 × 0,926813331
  = 0,980293215 ≤ 0,999
```

Ochrany profilů a severity prošly. Assignment gap je **0,00180594**. TD skutečně vrátilo část counts zisku TG, ale dosáhlo dostatečného zlepšení společného cíle. Počáteční GEH běhu bylo 30,570246, takže nynější 22,804861 je přibližně o **25,40 %** nižší. Samotné GEH je proti konci C5 mírně vyšší o **0,269 %**.

Koncové profilové metriky: model/obs **0,836841**, GEH <5 **52**, <10 **88**, ≥20 **102**, ≥30 **71**. Součty intenzit profilů nejsou počty unikátních cest ani celková poptávka.

## Přijaté parametry

Přijato je c komponent **WORK_noE_C, WORK_noE_noC, SERV_E_C, SERV_noE_noC**. Jejich b se nemění. Parametry LONG 9111–9115 i SCHOOL 9117 jsou ve vstupu a finálním vnitřním stavu shodné a nejsou v přijatých vnějších změnách.

Nativní koncový stav cyklu:

```text
0b7f25ac5a29adc5bd80bbe342765e4f4fc67e097624e8a4620878c8cbabf98c
```

## LONG TD: nově doložený konkrétní důvod

`TDJOINT_SEARCH.json` obsahuje **9 skutečně vyhodnocených LONG sond**. Všechny mají `SAFE`, žádná není odmítnuta nativním nebo survey guardem. První dva pollingové průchody pokrývají oba parametry a oba směry. Nejlepší LONG sonda je `J01_LONG_COMPOSITE_LOGC_M`:

```text
vnitřní skóre 1,0 → 0,99957296498
relativní zlepšení 0,000427035 = 0,0427035 %
minimum_relative_objective_improvement = 0,001 = 0,1 %
```

Ve druhém průchodu je nejlepší LONG zlepšení jen **0,03399 %**. LONG tedy při těchto sondách nepřekonal vnitřní minimální zlepšení. V kódu `_is_better()` je nutné překročit maximum absolutního minima 1e−9 a relativního minima 0,001×výchozího skóre. Pozitivní LONG sondy se proto ani nedostaly do žebříčku přijatelných směrů. Toto není doklad globálního zmrazení nebo chybějícího spuštění LONG TD.

Jde o výsledek konkrétních sond, ne důkaz, že nemůže existovat lepší jiný LONG krok. Třetí průchod skončil na rozpočtu, u LONG v něm proběhla pouze jedna sonda b. LONG Generation je jiný mechanismus; příčinu jeho nulových přijatých změn tento TD log sám neurčuje.

## SCHOOL TD

Proběhlo **10 SCHOOL sond**, všechny `SAFE`. Nejlepší směry log(c) zlepšily vnitřní skóre přibližně o **0,317 %**, **0,397 %** a **0,368 %** podle průchodu. SCHOOL se dostal do žebříčku, ale výše stály směry WORK/SERVICE. Solver porovnává nejlepší samostatné změny a případně měřenou kombinaci nejvýše dvou nejsilnějších směrů; ponechá nejnižší skóre. SCHOOL proto v tomto cyklu nezměnil b/c. P/A SCHOOL zůstaly během TD ověřeně fixní podle zavedené politiky.

## Vnitřní stav, obnovení a dokončení hledání

Vnitřní skóre **1,0 → 0,885383095** je normalizovaný GEH²/FineCDF surrogate; nesmí se vydávat za vnější F nebo procentní změnu skutečného váženého GEH. `BEST_STATE.json` odkazuje na vnitřní `ACCEPTED_060.npz`; nejde o nový celoběhový `BEST_SO_FAR_CHECKPOINT.json`, který přiložen není.

Bylo vyčerpáno **60 vyhodnocení**, proběhly tři průchody, z toho dva úplné a třetí neúplný. Stop reason je **TD_EVALUATION_BUDGET**. Vnitřní etapa dle časů master reportu trvala **61 min 48 s**; nejde o samostatně doložený celkový čas všech částí vnějšího TD bloku.

`TD_PERF_RESTORE_AUDIT.json` uvádí tři ověřené nativní obnovy a jedno `VERIFIED_CONSECUTIVE_REUSE` za 8,139 s. Vnější akceptace nebyla přeskočena. Kontrakt TD09C uvádí 16 nativních strát včetně LONG/SCHOOL a samostatně zmrazený FOREIGN; toto jsou tvrzení ověřovacích záznamů, nikoli naše nové COM čtení.

Cyklus končí `PROGRESS_CONTINUE_DEMAND`, `LONG_SCHOOL_DESIGN_UNVERIFIED`, `joint_stationary=false`. TG i TD přitom přijaly změnu, takže společná stacionarita není doložena ani nezávisle na příznaku odloženého hledání. Úspěšné dokončení TD neznamená dokončení celé kalibrace.

## Rozsah ověření a záloha

**18 datových kontrol prošlo**; přepočet F, návaznost hashů, identita samostatných a vložených souhrnů, úplný přijatý krok, nezměněné LONG/SCHOOL b/c a pokrytí sond. SHA ověřeny pro všech **14 dostupných souborů**. `analyse.py.txt` tento audit reprodukuje ze souborů `inputs/*.gz.b64` a vytváří `SUMMARY.json` a `CHECKS.json`.

Oba uploady `ACCEPTED_051.npz` a `ACCEPTED_060.npz` překročily **32 MiB limit přenosu nástroje**. Nelze je zde stáhnout, archivovat ani nezávisle ověřit jejich obsah či deklarovaný SHA. Jejich identita a důvod omezení jsou v `INPUTS.json`; záloha obsahuje 14 dostupných souborů, nikoli tyto dvě matice. Nebyl spuštěn Visum ani runtime testy a produkční kód nebyl měněn.

Větev tohoto čtecího reportu vychází z posledního dodaného kódu `1dc217e7205e840b71377a3a0ae4fcebbcb80e09`, který již obsahuje rozšířený SupplyMix; analyzovaný živý běh stále používá staré limity, jak potvrzuje jeho vlastní report.

```text
python artifacts_live_status_cycle6_20261031/analyse.py.txt
```

Záloha zdrojů a dostupné evidence:

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/live-status-cycle6-20261031.zip
