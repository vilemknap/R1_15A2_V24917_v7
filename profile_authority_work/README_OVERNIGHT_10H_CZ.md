# R1 15A2 V2.3.8 - OVERNIGHT 10H - pouze navrh

Toto je specialni nocni konfigurace puvodniho V2.3.8 baliku. Jedina zmena
ve vedecke/runtime JSON konfiguraci je `two_mode.max_runtime_seconds`:
1800.0 -> 36000.0 sekund (10 hodin). Zadne Python moduly, numericka jadra,
metodicke autority, matice, pozorovani ani parametry modelu se nemeni.

## Pred spustenim

1. Uloz vychozi .ver na disk a otevri ji v PTV Visum 2026. Pouzij stav s
   dokoncenym aktualnim assignmentem a ulozenymi PrT trasami. Pokud se po
   poslednim assignmentu zmenila poptavka, sit nebo b/c, nejprve obnov
   odpovidajici vypocty. Provozuj jen jednu instanci tohoto masteru.
2. Rozbal cely ZIP do nove slozky. Nesmis kombinovat nove a stare skripty.
3. Pripoj notebook k napajeni; nastav Windows, aby pocitac nepresel do rezimu
   spanku ani hibernace, a pri zavreni vika nebyl uspany. Monitor se smi vypnout.
   Over volne misto na disku s vystupy (doporuceno alespon 20 GiB), aktivni
   licencovani Visumu a riziko naplanovaneho restartu Windows.
4. Neodpojuj disk s otevrenou .ver a nezasahuj do modelu behem vypoctu.

## Spusteni

Ve Visumu pouzij Scripts > Execute script file a spust pouze:
`R1_15A2_DESIGN_ONLY_TWO_MODE_V2_3_8.py`
NESPOUSTEJ z Procedure Sequence ani v paralelni instanci skriptu.

## Chovani

- `apply=false` je vynuceno ve vstupnim skriptu i adapteru.
- Neprovede assignment, SaveVersion, LoadVersion ani kalibracni zapisy.
- Je to JEDEN navrhovy pruchod; zadna iterativni optimalizace do zlepseni.
- Skonci po dokonceni, chybe, manualnim stopu nebo po 10h limitu.
- Limit je kooperativni; blokujici COM/SQL/numericke volani muze trvat dele.
- Prvni uplny produkcni rozmer tohoto kolektoru zatim nebyl otestovan v
  zivem Visumu. Pokud vypadne proud, Visum nebo OS, cache nelze resumovat.

## Stav a rucni stop

Vedle .ver je `R1_15A2_V2_3_8_RUNS/LATEST_RUN.txt`. Tento soubor urcuje
`RUN_...`, kde je `00_PROGRESS.json` a nakonec `00_RESULT.json`.
Pocatecni outputy mohou vznikat pomaleji pri prvnim preflightu.

Pro kooperativni stop vytvor prazdny soubor `STOP_REQUESTED` bez pripony
v `RUN_...` nebo v `R1_15A2_V2_3_8_RUNS` (pred novym spustenim smazat).
Neklikej na spousteni druheho behu behem prvniho.

## Pri rannim vyhodnoceni

- Zkontroluj `00_FINAL_STATUS.txt` a `00_RESULT.json` v aktualnim RUN.
- Pokud bezi, sleduj `00_PROGRESS.json` a aktualizaci souboru SQLite.
- Pokud je `DESIGN_ONLY_STATE_UNVERIFIED_MANUAL_REOPEN_REQUIRED`, nezachovavej
  aktualni pracovni stav a otevri puvodni ulozenou .ver.
- Vystupy jsou predbezne (provisional geometry), ne schvaleny APPLY.
- Zasli `00_RESULT.json`, `TWO_MODE_CACHE_AUDIT.json`,
  `03D_DSEG_PATH_VOLUME_PARITY.csv`, `SUPPLY_PROFILE_FLOW_PARITY.csv`
  a pripadne `SUPPLY_PATH_SEQUENCE_DESIGN.json`.

Limity SQLite 12 GiB, kontrola volneho mista alespon 1 GiB, epsilon 0.005,
12 DSeg, 498 mereni a vsechny ostatni pojistky zustaly NEZMENENE.
