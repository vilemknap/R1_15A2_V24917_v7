# R1 15A2 V2.4.5 CP03 — LIVE PATH LENGTH HOTFIX

## Proč CP03 vznikl

První reálný běh V2.4.5 dne 2026-10-16 skončil v prvním Generation trialu technickou chybou při zápisu 12D diagnostiky. Výpočetní logika nebyla příčinou: selhal zápis souboru do hluboce zanořeného adresáře.

Pozorovaná cesta k `01_DETAIL_498_FORENSIC.csv` měla 261 znaků, tedy přesně za historickou hranicí Windows `MAX_PATH=260`. Helper byl spuštěn z hlubokého `.../DEMAND_CYCLE_01_GENERATION/TRY_01/ROLLBACK/12D_ROLLBACK/...` a sám pod sebe přidal další dvě úrovně.

Run následně správně skončil fail-closed. Žádný kandidát nebyl přijat. Dodaný run status současně potvrzoval `live_matches_last_accepted=true`; zdrojový `.ver` zůstal beze změny.

## Opravy

1. **Krátký run root**
   - nový runtime run root: `R1_15A2_V245_RUNS`
   - nahrazuje dlouhé `R1_15A2_V2_4_5_FULL_CALIBRATION_REPAIR_RUNS`
   - stejná známá problematická cesta by tím klesla z 261 na 235 znaků.

2. **12D a 11D helpery běží v krátkém OS temp workspace**
   - helper už není fyzicky spuštěn uvnitř hlubokého TRY/ROLLBACK stromu;
   - plná helper evidence se po doběhu uloží do ZIPu v run directory;
   - do run tree se zkopírují jen kompaktní soubory nutné pro downstream logiku a audit;
   - temp workspace se po bezpečném publikování evidence odstraní.

3. **Output-directory lifecycle hardening**
   - stage log parent directory se vytváří před zápisem;
   - eliminuje další stejnou třídu `FileNotFoundError` při čerstvém stage adresáři.

4. **Rollback evidence před diagnostikou**
   - po obnovení parametrů a přepočtu se nejprve zapíše `ROLLBACK_STATE_RESTORED.json`;
   - až potom se spouští file-heavy 12D/11D diagnostika;
   - pokud diagnostika selže, evidence o již obnoveném modelovém stavu se neztratí.

5. **Přesnější klasifikace rollback chyby**
   - pokud po selhání rollback diagnostiky živý snapshot stále přesně odpovídá `before`, stav se označí `ROLLBACK_DIAGNOSTIC_VERIFICATION_FAILED_STATE_RESTORED` místo zavádějícího `MANUAL_REOPEN`;
   - pokračování se přesto fail-closed zastaví, dokud diagnostická kontrola neprojde.

## Testy

- původní kompletní offline sada + nové regrese: **535 passed, 0 failed**;
- nové testy přímo reprodukují známou 261znakovou cestu;
- ověřují, že 12D běží mimo hluboký controller tree;
- ověřují durable mirror + ZIP evidence;
- ověřují, že důkaz obnoveného rollback stavu vzniká před následným diagnostickým I/O.

## Co CP03 nemění

Nemění matematiku TG, FineCDF TD, ADDVAL1, CAL/VALID role, 498 observation rows, targety IDP, native Multi policy ani acceptance kritéria. Neobsahuje PERF2/PERF3 optimalizace z CP02 návrhu.

## Jak znovu spustit

Rozbal CP03 do **nové samostatné složky** a spusť pouze:

`R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_5.py`

přes `Scripts > Execute script file` v PTV Visum 2026.

Nepoužívej starou složku `R1_15A2_V2_4_5_FULL_CALIBRATION_REPAIR_20261016`; obsahuje přesně kód, který vyprodukoval 261znakovou helper cestu.

CP03 je offline ověřený hotfix. Skutečný druhý Visum COM run po této opravě zatím nebyl proveden.
