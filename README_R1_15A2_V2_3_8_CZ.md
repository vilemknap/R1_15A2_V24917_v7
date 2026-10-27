# R1 15A2 V2.3.8 - dvourezimovy kolektor, pouze DESIGN ONLY

**Spoustej `R1_15A2_DESIGN_ONLY_TWO_MODE_V2_3_8.py`.** Je to kompletni navrhovy
master, ne dalsi mala sonda. Rozbal cely balik do nove slozky. Starsi vstupni
skripty V2.3.7 v baliku zustavaji pro zavislosti, testy a dohledatelnost;
nespoustej je jako vstup do teto vetve.

## Co tato verze dela

Geometrii skutecnych ulozenych PrT tras nacita celou pouze pro dva reprezentanty:
`NATIVE_CW` pro rezim `C` a `NATIVE_CW_noT` pro rezim `C_noT`.
Pro kazdy z 12 osobnich DSegu nacte samostatne **vsechny rodicovske klice a
jeho vlastni `Vol(AP)`**, vcetne nulovych hodnot. Kladne objemy se neorezavaji.
Jedna geometrie tedy neznamena jeden spolecny objem nebo slouceni segmentu.

Pred sdilenim proveri v aktualnim behu presnou shodu uplnych mnozin klicu uvnitr
rezimu a shodu stejnych omezenych oken geometrie. Obe cele reprezentativni
geometrie projdou kontrolou existence hran, poradi, topologicke navaznosti a
uplnosti vuci rodicovskym klicum. Rodic trasy se zachovava i pres hranici stranek.
Jiny DSeg, rezim, chybejici klic, prerusena sekvence nebo neshodne vzorky beh
zastavi; zadna nejkratsi cesta ani nahradni hrana se nevyrabi.

**Uplna shoda geometrie vsech DSegu stale neni prokazana.** Sdileni je experimentalni
predpoklad pro navrhovou analyzu. Vystupy, kandidati i dopady nesou
`PROVISIONAL_SAME_MODE_GEOMETRY_NOT_FULLY_VERIFIED` a `apply_permitted=false`.
Ani shoda profilu a objemu tento predpoklad nepromeni v dukaz geometricke identity.

## Co zustalo zachovane

- Vsech 498 pozorovani: 462 CAL a 36 VALID, autoritativni `R1 Obs RPDI`, puvodni
  vahy a obousmerne vyhodnoceni mestskych profilu. Konfliktni zdrojove profily se
  nadale nepouzivaji jako ridici profily ADDVAL1; pozorovani se nemeni ani nemazou.
- Epsilon 0.005, kontrola posledniho spolecneho GAP, +1 ADDVAL1 = 10 sekund,
  originalni limity kroku, skutecne souvisle sekvence a sequence-level CAP-SPLIT.
- Stejne numericke resice generation a distribuce, autority IDP, TG a VDF.
- Validacni pozorovane hodnoty neridi navrh kandidatu.
- Zadny assignment, zadna kalibracni zmena zony, matice, b/c ani ADDVAL1.

Nove se ani nevola `SaveVersion` nebo `LoadVersion`. Misto drivejsiho
`READ_ONLY_GUARD.ver` vznika ciste datovy `READ_ONLY_GUARD.snapshot.json`.
Neni to zaloha modelu a neni to soubor, ktery lze otevrit jako .ver.
Pred spustenim si tedy obvyklym zpusobem zachovej vlastni ulozeny vychozi model.
Skript nebude menit nazev aktualne otevrene .ver na nazev pomocneho checkpointu.

## Ukladani a znovupouziti

`TWO_MODE_PATH_STORE.sqlite` obsahuje geometrii jednou na rezim, samostatne
objemy po DSeg, slovnik presnych smerovych hran, pruchody profily a kompaktni
index hran pro vypocet dopadu. Posloupnosti jsou bezeztratove seznamy indexu do
slovniku hran, nikoli zjednodusene nebo aproximovane trasy.

Blok `GENERATION` pouzije **stejnou cache ze stejneho behu a stavu modelu**.
Nevyvola znovu COM export geometrie pro ctyri native WORK/SERVICE segmenty.
P/A incidence se vypocita z presnych pruchodu profily a segmentovych objemu;
puvodni numericke resice se nemeni. Pri chybe cache se nespousti druhy, stary
export jako skryta zalozni varianta.

Cache se nepouziva mezi behy ani po zmenach modelu. Pred jejim pouzitim se
kontroluji snapshoty; vsech 12 prislusnych matic se cte a porovnava take pred a po
exportu. Parita se pocita ze **stejneho aktualniho behu** proti mezizonove casti
matice, s nezmenenou toleranci 1 %. Diagonala je vykazana samostatne.

## Spusteni ve Visumu

1. Pouzij aktualni ulozenou .ver s hotovym assignmentem a ulozenymi trasami.
   Jestlize se od assignmentu zmenily matice nebo b/c, nejdrive mimo tento skript
   obnov prislusne navazujici vypocty. Behem navrhoveho behu model neupravuj a
   nespoustej soubezne jinou kalibraci v teze instanci.
2. Rozbal cely ZIP do nove slozky. V otevrenem Visumu pres
   **Scripts > Execute script file** spust
   `R1_15A2_DESIGN_ONLY_TWO_MODE_V2_3_8.py`, mimo Procedure Sequence.
3. Vystupy vzniknou vedle .ver otevrene na zacatku behu:

```
R1_15A2_V2_3_8_RUNS/
    LATEST_RUN.txt
    RUN_.../
        00_RELEASE.txt
        00_PROGRESS.json
        00_RESULT.json
        00_FINAL_STATUS.txt
        CONSOLE_CAPTURE.log
        API_PREFLIGHT/
        CALIBRATION/
            BASELINE/READ_ONLY_GUARD.snapshot.json
            DESIGN_SUPPLY_ADDVAL1/
                TWO_MODE_PATH_STORE.sqlite
                TWO_MODE_CACHE_AUDIT.json
                TWO_MODE_GEOMETRY_SAMPLE_QA.json
                03D_DSEG_PATH_VOLUME_PARITY.csv
                SUPPLY_PROFILE_FLOW_PARITY.csv
                SUPPLY_DUPLICATE_SCOPE_AUDIT.json
                SUPPLY_PATH_SEQUENCE_DESIGN.json
            DESIGN_GENERATION/
                TWO_MODE_CACHE_REUSE.json
                GENERATION_PROPOSAL.json
            DESIGN_TD_COMPONENT_.../
```

Detailni surova data jsou v SQLite. Zamerne se nevyrabeji obri duplicitni
`03_PRT_PATHS_ALL.csv` a `04_PRT_PATHLINKS_ALL.csv` pro kazdy DSeg.
Prubezny soubor se zapisuje atomicky, typicky nejvyse jednou za dve sekundy.
V casti dlouheho synchronniho COM/SQL volani nebo numerickeho solve nemusi jit
obnovovat, dokud se volani nevrati. `00_FINAL_STATUS.txt` patri celemu masteru;
stejne pojmenovany soubor v `API_PREFLIGHT` patri jen diagnosticke komponente.

## Casovy rozpocet a preruseni

Pro tuto nocni variantu `two_mode.max_runtime_seconds = 36000` znamena **10 hodin pro cely beh**. Puvodni verze mela 1800 sekund (30 minut).
Jde o kooperativni limit: kontroluje se mezi strankami, davkami a fazemi, nikoli
nasilne uvnitr probihajiciho COM, SQL nebo numerickeho volani. Neznamena tedy
zarucene ukonceni presne v 1800. sekunde. Neni to prislib, ze kompletni vypocet
v tomto case dokonci; skutecny full-scale cas nove vetve jeste nebyl zmeren.

Pro rucni zastaveni vytvor prazdny soubor **`STOP_REQUESTED` bez pripony** bud
primo v aktualnim `RUN_...`, nebo v jeho rodici `R1_15A2_V2_3_8_RUNS`.
Skript po nejblizsi kontrole skonci, proveri nemennost stavu a nespusti dalsi
bloky. Pred novym behem tento soubor odstran. Neprepisuj kod ani nepoustej
novou kopii skriptu, kdyz stara jeste bezi.

Casovy a diskovy rozpocet se daji upravit v `R1_15A2_CONFIG_V2_3_8.json`.
Zakaz APPLY tim odblokovat nelze: vynucuje ho vstupni skript i novy adapter.
Cache ma navic limit velikosti 12 GiB a kontrolu alespon 1 GiB volneho mista.
Stop ponecha neuplny audit na disku, ale neuplna cache neni oznacena za hotovou
ani pouzita pro navrhy. Nejde o resumovatelny checkpoint.

## Jak vyhodnotit konec

`DESIGN_ONLY_COMPLETE_PROVISIONAL_GEOMETRY` znamena dokonceny navrhovy pruchod,
nikoli kalibracni zlepseni nebo povoleni APPLY. `DESIGN_ONLY_BLOCKERS` obsahuje
konkretni neprosle bloky. `DESIGN_ONLY_STOPPED` znamena rucni stop nebo vycerpany
rozpocet. `...STATE_UNVERIFIED_MANUAL_REOPEN_REQUIRED` vyzaduje kontrolu a znovuotevreni
ulozeneho vychoziho modelu; skript automaticky nezkousi COM rollback.

Pro dalsi vyhodnoceni staci `00_RESULT.json`, `TWO_MODE_CACHE_AUDIT.json`,
`03D_DSEG_PATH_VOLUME_PARITY.csv`, `SUPPLY_PROFILE_FLOW_PARITY.csv` a, pokud vznikl,
`SUPPLY_PATH_SEQUENCE_DESIGN.json`. Celou SQLite databazi obvykle neni treba posilat.

## Overeni vydani

Aktivni verifikator je `VERIFY_PACKAGE_V2_3_8.py`. Historicke verifikatory ve
slozce patrily jinym balikum. Testy: `python -m pytest -q`.
Vysledky tohoto vydani jsou v `V238_VERIFICATION.json`.

Regresni testy porovnavaji novy kolektor s puvodnim per-DSeg kolektorem a novou
P/A incidenci s puvodnim jadrem. Zahrnuji dva rezimy, rozdilne objemy, nulove
trasy, smycky, poradi, hranice stranek, obousmerne/duplicitni profily, paritu,
zmenu stavu, zakaz zapisu, stop a skutecne zapojeni exportu do adapteru.

`BENCHMARK_TWO_MODE_SYNTHETIC.json` je pouze offline mereni syntetickeho generatoru:
neni to rychlost COM, doba Visumu ani dukaz totoznosti geometrii na skutecne siti.
