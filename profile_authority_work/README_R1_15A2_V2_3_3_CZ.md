# R1 15A2 V2.3.3 - COM/API prověřená větev

**Nejprve spusť samostatnou diagnostiku, nikoli APPLY.**

## 1. Jednorázový tichý test v aktuálním Visumu

`R1_15A2_VISUM_COM_PREFLIGHT_V2_3_3.py`

Soubor je samostatný. Spusť ho přes Scripts > Execute script file v okně se správným modelem. Také lze celý jeho obsah vložit jako dočasný Internal script. Nepřidávej ho trvale ke každé kalibrační iteraci.

Nespouští assignment, nic nemění v modelu, neukládá ani nenačítá .ver, nemá potvrzovací okna. Testuje i čtení dat; výpočet matic definovaných formulí může Visum při čtení sám vyhodnotit.

Výstup se zapisuje do projektového adresáře vráceného `Visum.GetPath(2)`:

```
R1_15A2_COM_API_PREFLIGHT/
  LATEST_RUN.txt
  RUN_.../
    00_STARTED.txt
    COM_API_PREFLIGHT.json
    00_FINAL_STATUS.txt
```

Není-li projektový adresář použitelný, tichá diagnostika zkusí `%LOCALAPPDATA%/R1_15A2_COM_API_PREFLIGHT` (poté domovskou složku); tuto volbu uvede v reportu. Pošli `COM_API_PREFLIGHT.json` z posledního běhu. Report vypíše nezávislé nesrovnalosti současně, nemusíme opravovat jednu chybu po druhé naslepo.

## 2. Celý kalibrátor

Rozbal celý ZIP. Nový vstupní soubor je pouze:

`R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_3.py`

Konfigurace: `R1_15A2_CONFIG_V2_3_3.json`. Starší vstupní soubory a reporty v balíku jsou historie/regresní závislosti, nikoli alternativní doporučené verze pro tento běh.

Master spusť ručně přes Scripts > Execute script file; **nevkládej ho jako aktivní krok Procedure Sequence**. Na rozdíl od tichých helperů 20A/20B řídí celý běh, spouští procedury a potřebuje LoadVersion pro rollback.

Pracuj v COM prostředí Python3.13 nebo Legacy; ne v PTV Hub cloud computing. Menu Scripts > Execute script file používá dle dokumentace Legacy. Samotný fakt, že Legacy běží v hostitelském wx vláknu, není chybou.

Předvolené `apply=false` zůstává. Nepřepínej APPLY, dokud nejsou potvrzeny skutečné assignment operace, jejich DSeg scope, dosažený convergence gap a stávající mapovací kontroly. Nový main nejprve uloží COM/API audit do podsložky API_PREFLIGHT; při nalezených chybách kalibraci nespustí.

Nové proměnné: `R1_15A2_V233_APPLY`, `R1_15A2_V233_RESUME_FROM`. Starý resume s jinou identitou implementace nepřejímat jako stejný běh.

## Zachováno

498 pozorování =462 CAL+36 VALID. 90 městských BOTH: součet modelových směrů. Jediná pozorovaná hodnota R1_OBS_RPDI, bez další konverze. Skutečné nuly zatížení jsou platné; nečitelný atribut není nula. ADDVAL1+1=10 ekvivalentních sekund. Výběr skutečných sekvencí cest, oddělení supply/demand, IDP a schválené autority se nemění.

## Odkazy v balíku

`COM_API_AUDIT_REPORT_V2_3_3.md`: nálezy, opravy a meze důkazu.
`COM_API_SOURCE_REGISTER.json`: oficiální webové zdroje.
`V233_OFFLINE_GATE_STATUS.json`: skutečné offline testy.
`VERIFY_PACKAGE_V2_3_3.py`: kontrola manifestu a hashů.

**Windows/Visum live COM zatím nebyl spuštěn.** Testy s COM-shaped objekty nejsou produkčním důkazem nad R1.
