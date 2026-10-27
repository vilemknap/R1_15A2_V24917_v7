# R1 15A2 V2.4.7 — kalibrace s epochami cest

## Účel verze

V2.4.7 navazuje na plně offline ověřenou V2.4.6 a mění životní cyklus nejnákladnější části běhu: enumerace uložených cest z PTV Visum.

Nové pravidlo je:

1. po baseline se provede úplná počáteční enumerace cest;
2. tato cesta-báze se používá opakovaně pro návrhy Trip Generation, Trip Distribution a ADDVAL1;
3. každý kandidát se stále přijímá nebo odmítá výhradně podle čerstvého nativního přepočtu Visumu a živých 12D/11D diagnostik;
4. přijatá změna sama o sobě již cestovní cache nemaže;
5. nová enumerace se provede až po úplném lokálním vyčerpání kandidátů na aktuální path bázi;
6. pokud čerstvá enumerace přinese jinou cestovní bázi, kalibrace pokračuje;
7. pokud přinese ekvivalentní bázi, může se započítat stacionární cyklus.

Tím se omezuje opakované čtení desítek milionů path/path-link řádků, aniž by uložené cesty převzaly roli autority pro přijetí kandidáta.

## Co znamená „stejná path báze“

Audit uchovává dva typy identity:

- **exact hash** — přesná identita parent klíčů, PathIndex a IEEE-754 path volumes;
- **comparison hash** — kanonická identita podle DSeg, módu, OD, skutečné linkové sekvence, geometry kind a agregovaného path volume zaokrouhleného na 6 desetinných míst.

Comparison hash je odolný proti:

- pouhému přečíslování PathIndex;
- rozdělení jedné shodné sekvence do více identických path řádků;
- podmikro numerickému šumu v path volumes.

Neignoruje změnu skutečné sekvence, OD, DSeg, geometry kind ani materiální změnu path volume.

## Trip Generation nad zmrazenou epochou

Aktuální OD totals se promítnou na zmrazené podíly cest v daném OD. Tím Generation používá současnou poptávku, ale nemusí znovu číst path listy.

Jestliže se objeví nově kladná OD relace, pro kterou epochová báze nemá žádný parent nebo měla pouze nulový support, skript nesmí podíl cesty vymyslet. Vynutí okamžitou novou enumeraci. Když ani čerstvá enumerace support nedodá, běh selže fail-closed.

## Supply / ADDVAL1 nad zmrazenou epochou

Po každém živém assignmentu se znovu načtou současné modelové hodnoty všech profilů a přepočítá se:

- driver/protected klasifikace;
- ON/OFF sekvenční evidence;
- support a collateral exposure;
- pořadí ADDVAL1 kandidátů.

Toto se děje nad již uloženou geometrií bez nového COM path exportu. Dopad kandidáta se však vždy ověří novým assignmentem.

## Kdy se path epoch obnoví

### Coupled demand

Refresh je povolen pouze po kompletním TG + plném FineCDF TD cyklu bez přijaté změny. Zkrácený EXPLORE/REFINE TD budget, chyba, STOP nebo neúplný search refresh ani konvergenci nepotvrzuje.

### Supply

Refresh je povolen pouze po úplném Supply cyklu bez přijatého kandidáta a bez zkráceného candidate search.

### Limity

Konfigurace omezuje počet refreshů:

- demand: 4;
- supply: 8.

Vyčerpání limitu je technická chyba, nikoli konvergence.

## Disková politika

Aktivní SQLite path store může být velmi velký. V2.4.7 proto po úspěšném vytvoření a ověření nové epochy odstraní pouze superseded soubor přesného názvu `TWO_MODE_PATH_STORE.sqlite` včetně případných journal/WAL/SHM souborů.

Zachovány zůstávají:

- všechny hashové a souhrnné evidence;
- `PATH_EPOCH.json`;
- `PATH_EPOCH_PLATEAU_GATE.json`;
- accepted `.ver` checkpointy;
- diagnostiky a rozhodnutí kandidátů.

Mazání jinak pojmenovaného souboru je zakázáno fail-closed.

## Co se nemění

- 512bodové IDP CDF a FineCDF v1.8;
- nativní Visum Multi jako autorita TD outputu;
- CAL/VALID role a 498 observačních řádků;
- FOREIGN, LNV/NV a ostatní fixed matice;
- čerstvý assignment a živé diagnostiky pro přijetí každého kandidáta;
- rollback bez LoadVersion;
- dva úplné stacionární demand cykly;
- atomické rotační `.ver` checkpointy;
- CP03 Windows path-length opravy;
- V2.4.6 adaptivní TG/TD/ADDVAL1 optimalizace.

## Spuštění

1. Rozbalte celý balík do nové krátké lokální složky.
2. V PTV Visum 2026 otevřete čistý autoritativní zdrojový `.ver`.
3. Spusťte přes `Scripts → Execute script file`:

```text
R1_15A2_FULL_OVERNIGHT_PATH_EPOCH_V2_4_7.py
```

Nespouštějte launcher jako krok Procedure Sequence a nekopírujte jej samostatně do staršího balíku.

## Důležité výstupy

V každém epochovém adresáři:

```text
PATH_EPOCH.json
PATH_EPOCH_PROFILE_REBIND.json
TWO_MODE_CACHE_REUSE.json
PATH_EPOCH_PLATEAU_GATE.json
PATH_EPOCH_STORE_RETENTION.json
```

Globálně zůstávají rozhodující:

```text
00_RESULT.json
CALIBRATION/RUN_STATUS.json
CALIBRATION/LATEST_ACCEPTED_CHECKPOINT.json
```

## Stav ověření

Balík je offline testovaný a má syntetické end-to-end uživatelské testy. Skutečný Windows PTV Visum 2026 COM běh musí být proveden podle `LIVE_VISUM_ACCEPTANCE_V2_4_7_CZ.md`.
