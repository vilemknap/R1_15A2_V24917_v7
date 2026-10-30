# SCHOOL TD – kontrola zapojení, opravy a optimalizace

Výchozí stav je uživatelem zvolená větev `codex/v24917-school-td-finecdf-active-20261030`, commit `0f2204a3f0a4a4c74bda0f32c8ea7323320e0f70`. Načteno 33 skutečně změněných souborů proti předchozí místní verzi; všechny Git blob identity souhlasily. Jde o pokračování nového SCHOOL/LONG řetězce, nikoli návrat ke starší zmrazené LONG variantě.

## Výsledné chování

SCHOOL TD je již zapnutý pomocí `school_td_enabled=true`. Ladí se pouze nativní `b/c` pro `5_SCHOOL` a osobní matici **9117**, s původním **512bodovým DIRECT_PURPOSE IDP cílem 0,1–100 km**. Parametr `a` se nemění. Školní Generation je fixní podle původních funkcí AMDY; nepoužité `ADD_PROD_SCH`/`ADD_ATT_SCH` se neoptimalizují.

1. **Výhradně DYNAMIC pro SCHOOL.** Validace nastavení i cíleného scope odmítají SCHOOL ve FROZEN_PATHS. Ten nemá vlastní ověřenou školní count odezvu. Obranná kontrola skóre také odmítne půjčení W/S frozen aproximace pro SCHOOL.
2. **Měřené počty nevyžadují W/S incidenci.** Při DYNAMIC pochází count složka ze živého nativního assignmentu. Ověření už její dostupnost nezaměňuje za dostupnost frozen W/S lineární mapy. Školní pokus může fungovat bez předchozí Generation cache; původní požadavky na incidenci pro frozen W/S zůstávají.
3. **LONG podpora při SCHOOL-only pokusu.** Jedno společné nativní TD přepočítává i LONG matice, přestože se mění pouze školní b/c. Jestliže vnější adaptér vlastní LONG masku, musí jeho maskovací scope obalit i takový pokus. Maskování 80+ km bez horní hranice se tak nevynechá pouze proto, že LONG_COMPOSITE není v daném shortlistu.
4. **Skutečné zmrazení školní Generation.** Před a po nativním školním pokusu se podle identit zón čtou `FP_5_SCHOOL` a `FA_5_SCHOOL`. Reference je v rámci celého inner stage pevná. Změna hodnot, neúplná/duplicitní identita, nečíselná nebo záporná data zastaví pokus. Výjimka nativního výpočtu dál přejde k existujícímu vlastníkovi obnovy; context masky se vždy ukončí. Shrnutí SCHOOL nesmí tvrdit nezměněnou Generation bez ověřeného důkazu.
5. **Úspora v měřeném count modelu.** Dynamická větev již nečte pomocné matice pro globální κ/band aproximaci, nekopíruje osobní OD matice do frozen reference a nesestavuje nepoužitou lineární mapu. Počty čte jednou za vyhodnocení, včetně první reference. Složka počtů zůstává ve společném skóre jednou; vzorec ani váhy se nemění.
6. **Úplné manifesty.** Vývojové refresh nástroje zachovávají nové SCHOOL/silent moduly, run options i dodatečně zapečetěný chráněný FineCDF bridge z této větve. Původní nástroje by při refreshi tyto ručně přidané položky vynechaly. Chráněné zdroje se nemění.

## Co zůstává autoritou

Původní FineCDF reference, nativní TG/TD/20A/20B/assignment, aktuální skimy, původní společné 60/40 skóre, externí akceptace, chráněné profily, P/A ochrany a ověřený in-memory rollback. Nevznikají přímé zápisy do školní OD, nové školní cíle ani samostatná školní procedura. Běžné WORK/SERVICE frozen hledání si zachovává svůj dosavadní mechanismus.

Školní důkaz je v `TDJOINT_SUMMARY.json` pod `school_generation_freeze` a v cíleném `TDSCHOOL_TARGET_SCOPE.json` pod `generation_freeze_readback`. Obsahuje hash pevných FP/FA, shodný hash readbacku a počet ověřených nativních vyhodnocení. Dostupnost samotného source IDP cíle se nadále kontroluje odděleně.

## Ověření a omezení

- 97 cílených testů prošlo; nová sada přidává 18 testů proti nalezeným chybám.
- Na původní větvi stejné tři vybrané testy selhaly: chybějící zákaz SCHOOL frozen režimu, zbytečná pomocná čtení v dynamickém count modelu a vynechaný LONG maskovací scope při SCHOOL-only pokusu. Log je v `baseline_reproduction.log`.
- Kompletní offline sada: **2 030 prošlo, 4 přeskočeny**; DIAGFAST **138**; audit **18**. Závěrečné procesní výsledky jsou v `CHECKS.json` a `RESULTS.json`.
- Syntetická inicializace count modelu, 17 matic 681×681 / 248 profilů: počet pomocných maticových čtení **21 → 0**, zadržené kopie OD **63 071 496 → 0 bajtů**. `Q_ref` je shodné. Měří se pouze tato inicializace bez COM; nejde o čas celého Visum běhu. Detaily v `BENCHMARK.json`.
- Runtime manifest má 78 položek; release manifest 147. Všechny SHA musí souhlasit a všech 1 059 chráněných původních souborů zůstává bajtově identických.

**LIVE_VISUM_NOT_RUN.** Offline testy neprokazují první skutečný nativní školní b/c krok, jeho dopad na M9117 ani úspěšný rollback na konkrétním modelu. Další živý krok je jeden omezený školní pokus se změnou b/c, čerstvou FineCDF/GEH a důkazem obnovení při odmítnutí.

## Spuštění

Rozbal celý aktuální GitHub ZIP do samostatné složky. Otevři ověřený zdrojový model a spusť **`01_SPUSTIT_V24917_TDJOINT1_SILENT.py`** přes Scripts → Run script file. SCHOOL i LONG přepínače jsou převzaty z uživatelem dodané větve, není potřeba další auditní launcher. Skript ani dlouhý živý běh zde nebyl spuštěn.

`benchmark_measured.py.txt` je reprodukovatelný zdroj syntetického měření. Spouští se Pythonem z kořene Git checkoutu s NumPy a dostupným výchozím commitem `0f2204a3`; ZIP bez `.git` neumí načíst starou verzi pro porovnání. Kompletní source patch je přiložen samostatně.
