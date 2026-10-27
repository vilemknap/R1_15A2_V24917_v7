# R1 15A2 V24917 GENFIX1 — rozšířený audit kalibrátoru

**Datum:** 27. 10. 2026  
**Auditovaný balíček:** `R1_15A2_V24917_MOBILITY1_GENFIX1_REPACK2_20261027_FULL.zip`  
**SHA-256:** `7cb7408d85af35e859ff967fd2c2240238f4d3131e432f7dcbbce6e43bdfb390`  
**Výsledek:** **Nalezeny další reprodukovatelné závady. Před dlouhým během bez dozoru doporučuji opravit zejména transakce SUPPLYMIX, ověřování rollbacku a ochranu mobility.**

Toto je audit a sada reprodukcí, **nikoli nová opravená verze kalibrátoru**. Produkční Python soubory nebyly upraveny. Poslední oprava GENFIX1 není tímto auditem rušena: její regresní testy procházejí. Obdobné problémy ale zůstaly v jiných větvích a v interakcích novějších modulů.

## 1. Co bylo skutečně provedeno

Archiv byl znovu zkontrolován a rozbalen. CRC kontrola prošla; jeho SHA-256 souhlasí s dříve předaným REPACK2. Audit vychází ze skutečného obsahu tohoto archivu, nikoli jen z předchozího slovního reportu.

Byly projity zejména launcher GENFIX1 a instalační řetězec V24917, STEP1 generation, SUPPLYMIX, MOBILITY1, P/A vyvážení BDPA1, tolerantní rollback TDROLLBACK1/RBCONS1, TD count blend a správa důkazních archivů PERF3. Dva nově přiložené markdowny byly použity jako kontext vzniku ochrany mobility a nastavení TD; neobsahují celý původní průzkum ani všechny vstupní hybnosti.

| Kontrola | Výsledek v tomto auditu |
|---|---:|
| Integrita ZIP / CRC | PASS |
| Syntaktická kontrola Python souborů pomocí AST | 425 bez chyby |
| Původní sada `tests` | 1 335 passed, 4 skipped |
| Původní sada `diagfast_tests` | 138 passed |
| Celkem původní sady | 1 473 passed, 4 skipped |
| Nové auditní scénáře | 18 |
| Nové testy požadovaných bezpečnostních vlastností, které selhaly | **15** |
| Kontrolní scénáře / ověření skutečné sémantiky nastavení | 3 passed |
| V24917 runtime manifest | 52 položek bez neshody |
| V24916 runtime manifest | 50 položek bez neshody |
| DIAGFAST release manifest | 86 položek bez neshody |
| DIAGFAST base manifest | 1 059 položek bez neshody |

Patnáct selhání není patnáct nezávislých kořenových příčin. Jsou seskupena do **osmi nálezů** níže. Testy záměrně požadují bezpečné chování; červený výsledek u současného zdroje je reprodukcí závady, nikoli důkazem její opravy.

**Prostředí:** Linux, Python 3.13.5, pytest 9.0.2. Nové testy volají skutečné funkce z dodaného programu a používají simulované COM/adaptérové rozhraní nebo řízené selhání vstupu či zápisu. U TD reprodukcí A05/A06 je použit skutečný `_td_expected_freeze`, nikoli náhrada jeho validační logiky. Živý běh v PTV Visum, ověření konkrétní instalace pywin32 ani skutečný assignment nebyly provedeny.

## 2. Přehled nálezů

| ID | Priorita | Oblast | Reprodukce |
|---|---|---|---|
| F01 | P1 — před dalším dlouhým během | SUPPLYMIX ztrácí povinnost obnovit assignment; výjimky při zápisu mohou obejít rollback | A08, A09 |
| F02 | P1 | Full recovery SUPPLYMIX může převzít výrazně horší stav bez akceptačního rozhodnutí | A10 |
| F03 | P1 | Tolerantní rollback neprokazuje ekvivalenci celého modelu / diagnostiky | A04–A07 |
| F04 | P1 | Povinná ochrana mobility může být přeskočena nebo ohlásit OK bez použitelných dat | A03, A11, A12 |
| F05 | P1 | Ochrana mobility neplatí automaticky pro menší krok ani pro následné P/A vyvážení | A01, A02 |
| F06 | P2 — funkčnost a účinnost návrhu | STEP1 používá predikci původního fitu po změně kandidáta ochranou mobility | A13 |
| F07 | P2 | Dočasné COM selhání v count modelu se uloží jako neexistující linka | A14 |
| F08 | P2 | Selhání vytvoření důkazního ZIPu smaže jeho původní obsah | A15 |

P1 znamená možný nesoulad skutečného a vykazovaného stavu nebo obejití ochrany výsledku. P2 znamená podstatnou chybu návrhu, diagnostiky či obnovitelnosti, nikoli tvrzení o každém běhu.

## 3. F01 — SUPPLYMIX má obdobu transakční chyby opravené v generation

**Zdroj:** `r1_15a2_supply_mix_v24917.py:353–545`, zejména 453–455, 489–502 a 517–534.

Po odmítnutém přepočteném pokusu se před dalším pokusem obnoví pouze parametry ADDVAL1 a proměnná `applied` se nastaví na `None`. To ale neznamená, že se obnovily vypočtené linkové intenzity. Snapshot tohoto typu zásahu může být shodný s rodičem, protože zachycuje parametry a demand matice, nikoli všechny výsledky assignmentu.

V A08 první pokus proběhne a je odmítnut. Parametry se následně vrátí. Před zápisem dalšího pokusu vyvolá test chybu v `begin_candidate_readback_context`. Funkce vrátí rodičovský stav se statusem `TRIAL_FAILED_BEFORE_WRITE`, ale vypočtené výsledky stále odpovídají prvnímu odmítnutému pokusu. Proběhl pouze jeden assignment; ověřený přepočet rodiče chybí.

A09 zkouší jinou cestu: zápis `SUPPLYMIX_BLOCK_RESULT.json` selže po přepočtu kandidáta. Tento zápis leží mimo vnitřní transakční ochranu. Výjimka unikne bez lokálního rollbacku; zůstanou změněné parametry i assignment. Stejný problém může vzniknout při chybě zápisu uvnitř obsluhy jiné výjimky.

**Dopad:** pokračování s rodičovskými parametry a cizími výsledky, nebo nutnost ručně obnovit model po chybě, kterou měla transakce zvládnout. Testuje se odpovědnost tohoto bloku; vnější finalizátor může běh zastavit a vyžádat ruční otevření checkpointu, což však nenahrazuje jeho správný rollback.

**Oprava:** převést princip transakčního vlastníka z GENFIX1 do SUPPLYMIX. Oddělit „aktuálně zapsané parametry“ od „assignment může být neplatný“. Recovery evidenci uvolnit až po ověřeném úplném rollbacku nebo dokončeném přijetí. Celý blok včetně plánování, zápisů a acceptance bookkeeping musí být chráněn i proti přerušení a chybám souborového systému. Selhání zápisu logu nesmí zabránit obnově ani překrýt primární výjimku.

**Důkaz:** `evidence/A08_supply_dirty_assignment.json`, `A09_supply_io_escapes_rollback.json`.

## 4. F02 — Obnova po chybě může obejít akceptační bránu

**Zdroj:** `r1_15a2_supply_mix_v24917.py:549–606`, zejména 588–605; předání výsledku 609–641.

Když běžný rollback selže, `_rollback_or_recover` obnoví část parametrů, spustí plný generation přepočet a načte novou diagnostiku. Následně zavolá `accepted_state_changed` a může vrátit `changed=True`. V této větvi chybí porovnání s rodičem v explicitní toleranci i běžné akceptační rozhodnutí.

V A10 je po neúspěšném rollbacku řízeně změněn výsledek obnovovacího přepočtu. Vážený průměr GEH se zhorší z **2,3072 na 122,7783**. Funkce přesto vrátí `RECOVERED_FULL_RECOMPUTE_FROM_PARENT_PARAMETERS`, `changed=True` a zaznamená přechod accepted-state. Běžná brána kandidáta byla v tomto scénáři odmítavá.

Toto není pozorování skutečného Visum běhu s takto velkým zhoršením. Je to důkaz, že dotčená obnovovací větev **velikost ani přípustnost rozdílu nekontroluje**.

**Oprava:** obnova musí dokazovat návrat k témuž přijatému rodiči, nikoli nahrazovat rodiče libovolným novým výpočtem. Numericky ekvivalentní rekonstrukci lze připustit jen po společné omezené kontrole matic, 12D, 11D a zamražených parametrů. Materiální rozdíl musí skončit odmítnutím / požadavkem na otevření posledního checkpointu, bez přechodu accepted-state.

**Důkaz:** `evidence/A10_supply_recovery_unchecked.json`.

## 5. F03 — Tolerantní rollback má příliš úzkou definici shody

**Zdroj:** `r1_15a2_td_rollback_tolerant_v24917.py:34,56–72,93–155`; `r1_15a2_rollback_consistency_v24917.py:99–109,149–164`.

### Matice

TDROLLBACK1 vyřadí `matrices` a `matrix_hash` z porovnání parametrů. Rozdílné hashe matic pouze zaznamená. Nezjišťuje velikost změny buněk, sum, řádkových/sloupcových součtů ani rozsah změny distribuce.

A05 zachovává ID a rozměry matice, nezápornost, celkovou sumu 100 i TD parametry. Matice je změněna z `[[50,0],[0,50]]` na `[[0,50],[50,0]]`. Maximální buněčný rozdíl je 50 a L1 rozdíl 200. Při shodných simulovaných profilových intenzitách je takový snapshot přijat jako `PARAMETER_EXACT_NUMERICALLY_EQUIVALENT_RECOMPUTE`.

Stejné intenzity na omezeném souboru profilů nejsou důkazem totožné OD struktury. Tento závěr nevyžaduje znalost konkrétní sítě: kontrolovaná funkce vůbec nemá test velikosti maticového rozdílu.

### 11D a komponentové signály

A04 a A06 mění 11D / komponentový diagnostický obsah při zachování 12D. `RBCONS1.tolerant_compare` i TDROLLBACK1 takovou změnu propustí, protože 11D ani `signals` nekontrolují. RBCONS1 navíc vrací starou rodičovskou diagnostiku a vykazuje její hash jako referenci. Bez dalšího důkazu tak mohou vykazované 11D výsledky zaostávat za skutečným modelem.

### Duplicity profilů

`profile_drift` vytváří slovník podle ID bez kontroly duplicit. A07 obsahuje duplicitní ID a prohodí intenzity 500 a 500 000 mezi dvěma takovými řádky; souhrnný GEH zůstane stejný. Celé tolerantní porovnání vrátí PASS. To je chyba obrany při neplatném diagnostickém vstupu; audit netvrdí, že aktuální schválený roster takové duplicity skutečně obsahuje.

**Oprava:** jedna společná autorita ekvivalence pro GEN/TD/SUPPLY. Zachovat nezbytné tolerance pro zaokrouhlení, ale zavést omezené numerické porovnání matic a všech rozhodných diagnostik, úplnost a jednoznačnost identifikátorů, shodu pozorování/rolí/vah a explicitně rozlišovat přesnou shodu od numerické ekvivalence. Ověřenou toleranci nelze deklarovat jen podle několika profilových agregátů.

**Důkaz:** `A04_11d_ignored.json`, `A05_unbounded_matrix_drift.json`, `A06_td_11d_ignored.json`, `A07_duplicate_profiles.json`.

## 6. F04 — MOBILITY1 není vynucená ochrana všech návrhů

**Zdroj:** `r1_15a2_trial_adapter_v24917.py:168–176,209–217`; `r1_15a2_mobility_guard_v24917.py:56–82,99–140`.

Jsou reprodukovány tři cesty:

- A11: při chybě čtení FP se vytvoří `GUARD_ERROR_NOT_APPLIED`, ale program vrátí změnové řádky dál.
- A12: chyba zonálního fitu vrátí zděděný parent proposal bez stejné kontroly mobility. V testu návrh posune poměr z 1,25 na **1,875**.
- A03: při nulovém pokrytí použitelnými domácími zónami vzniknou poměry `NaN`, přesto vrchní status zní `OK`.

První chování odpovídá i přiloženému vývojovému zápisu: chyba FP měla pouze vyvolat varování. Jde tedy o problém návrhu bezpečnostní politiky, nikoli jen o chybně popsaný název funkce.

**Oprava:** při zapnuté povinné ochraně musí každý návrh, včetně fallbacku, projít jednou společnou kontrolou. Chybějící či neplatné podklady musí vést k explicitnímu blokování kandidáta bez zápisu, ne ke statusu OK nebo k falešné stacionaritě. Případné vypnutí ochrany musí být vědomé, zaznamenané nastavení, nikoli důsledek výjimky.

**Důkaz:** `A03_missing_coverage.json`, `A11_guard_error_fails_open.json`, `A12_fallback_bypasses_mobility.json`.

## 7. F05 — Platnost ochrany se ztrácí při změně kroku a P/A vyvážení

**Zdroj:** `r1_15a2_mobility_guard_v24917.py:74–82,99–140`; `r1_15a2_boundary_pa_v24917.py:120–190`; pořadí operací v adapteru a generation preview.

### Menší krok nemusí být bezpečnější

Dokumentační tvrzení modulu, že poměr je monotónní ve škále kroku, neplatí pro směs kladných a záporných log-kroků. Poměr má tvar váženého součtu exponenciál; může mít minimum uvnitř intervalu.

A01 používá změny +50 % a −20 %, tedy meze odpovídající CATCH_UP. Počáteční i plný krok mají poměr **0,755** a projdou. Poloviční krok má ale **0,7465468**, pod dolní hranicí 0,75. Nejde o numerický šum.

### P/A vyvážení se děje až potom

A02 nejprve projde ochranou s poměrem 1,25. Následné skutečné `subset_rebalance` zeslabí záporný produkční krok, aby vyrovnalo P/A v projekční bázi. Výsledný poměr mobility je **1,3392857**, přesto je P/A vyvážené.

Reprodukce výslovně rozlišuje person-production FP a projekční margin volumes: program je čerpá z odlišných struktur a nikde neprokazuje jejich totožnost po zónách.

**Oprava:** kontrolovat skutečné finální `candidate_rows` pro každou vybranou škálu až po vyvážení, maskách a ostatních úpravách. Po recompute ověřit skutečné živé FP před přijetím. Případné hledání škály musí respektovat obě hranice a smíšená znaménka; nestačí předpoklad „menší krok je vždy bezpečný“.

**Důkaz:** `A01_smaller_step.json`, `A02_rebalance_bypasses_mobility.json`.

## 8. F06 — STEP1 predikuje jiný krok, než se má aplikovat

**Zdroj:** `r1_15a2_trial_adapter_v24917.py:171–203,243–257`.

Ochrana mobility upraví `rows`. STEP1 model se ale dál sestavuje ze starého `solution["predicted_change"]` a výsledku LS fitu. Neodráží nutně oslabení mobility, masku ani pozdější P/A zásahy.

V A13 ochrana zredukuje všechny W/S produkční kroky prakticky na nulu (max. absolutní log-krok přibližně `1,1e-16`), ale predikce stále hlásí změnu profilové intenzity **+100**.

**Dopad:** nesprávné pořadí škál, odhad přínosu, učení `rho` a plýtvání drahými assignmenty. Běžná živá akceptace kandidáta tím sama o sobě není vypnutá; tento nález proto není tvrzením o automatickém přijetí nekvalitního kroku.

**Oprava:** vytvořit predikci z finálních implementovatelných změn a tutéž podobu použít pro plán, trial a aktualizaci modelu.

**Důkaz:** `A13_stale_prediction.json`.

## 9. F07 — Zaneprázdněný COM může v count modelu znamenat trvalou nulu

**Zdroj:** `r1_15a2_td_count_blend_v24917.py:132–155`.

`CountModel._link` zachytí jakoukoli výjimku a uloží pro danou linku `None`. `_vol(None)` pak znamená nulu. Rozpoznání dočasné chyby a opakování zavedené v GENFIX1 pro snapshot zde není.

A14 simuluje jediné `RPC_E_CALL_REJECTED`. Při druhém dotazu je linka již dostupná, ale funkce se na COM vůbec znovu nezeptá: vrátí uložené `None`. `_vol` navíc zvlášť potlačuje chyby čtení jednotlivých DSeg.

**Dopad:** neúplná reference vnitřního count modelu / chybné směrování TD návrhu. Finální živá akceptace zůstává samostatnou ochranou; nejde o důkaz, že všechny výsledky 12D používají tento permissive reader.

**Oprava:** rozlišovat dočasný COM stav, skutečně neexistující volitelný objekt a povinně chybějící data. Dočasná chyba se nesmí cachovat jako nula ani jako chybějící linka. Při trvalém selhání označit model jako neplatný a zabránit použití neúplné reference.

**Důkaz:** `A14_transient_link_cache.json`.

## 10. F08 — Neúspěšná archivace zničí původní důkazy

**Zdroj:** `r1_15a2_perf_v24917.py:122–137`.

`_finalize` zachytí chybu tvorby archivu a vypíše varování, ale v `finally` bezpodmínečně odstraní odloženou zdrojovou složku. A15 vyvolá `OSError` při tvorbě ZIPu. Potom neexistuje ani ZIP, ani původní `trace.txt`.

To není vysvětlení dřívějšího problému s rozbalením distribučního ZIPu. Jde o jinou, nyní reprodukovanou chybu v archivaci diagnostických důkazů za běhu.

**Oprava:** mazat zdroj až po úspěšném vytvoření a ověření archivu. Při chybě zachovat složku, zapsat její umístění do evidence a nevydávat archiv za existující. Tato úprava je důležitá zejména při nedostatku místa a dlouhých Windows cestách.

**Důkaz:** `A15_lost_forensic_evidence.json`.

## 11. Další nesrovnalosti a rizika — nikoli všechny jsou automaticky bug

### R01: „25 %“ má dvě různé sémantiky

MOBILITY1 hlídá rodinný poměr produkce vůči odvozené jednotkové referenci. `td_max_survey_degradation=1.25` v `outer_decision` naopak omezuje poměr TD diagnostické chyby **po kroku / před krokem**. Není to absolutní záruka maximálně 25% odchylky od průzkumu ani kumulativní limit vůči začátku běhu.

Kontrolní scénář opakuje tři lokální změny IDP chyby ×1,2 při zlepšení počtů ×0,7. Všechny tři skutečné `outer_decision` projdou; finální IDP chyba je ×**1,728** proti startu. Jde o důkaz implementované lokální politiky, ne o automaticky chybnou volbu uživatele.

Je nutné přesně rozhodnout a popsat, zda má být limit lokální, globální nebo obojí. Žádný práh nebyl v tomto auditu změněn.

Přiložený výpis průzkumu navíc rozlišuje celodenní / všednodenní základ a skupiny obyvatel. Samotné tvrzení „ADD_PROD = 1 odpovídá průzkumu“ neověřuje správnost napojení konkrétních H atributů, koeficientů 2,8 / 0,9, období a vymezení populace. K jejich nezávislému metodickému ověření je potřeba úplná původní autorita hybností a mapování; dva výpisy ji nenahrazují.

**Důkaz lokální sémantiky:** `evidence/R01_local_vs_global_survey_bound.json`.  
**Zdroj:** `r1_15a2_td_count_blend_v24917.py:367–398`.

### R02: Zlepšení fitu není totéž co konvergence

Adapter nastaví souhrnné `converged=True` i tehdy, když solver sám vrátí `converged=False`, pokud se jeho objective alespoň zlepšil. Původní `fit_solver_converged` sice zůstává zaznamenané, ale vnější projection check používá první příznak. STEP1 následně může po omezeném hledání vykázat `stationarity_confirmed=True`.

Částečně optimalizovaný návrh lze legitimně zkusit; nesmí se však zaměňovat s důkazem konvergence nebo úplné stacionarity. Doporučuji oddělit `proposal_usable`, `solver_converged`, `configured_search_exhausted` a `stationarity_verified`.

**Zdroj:** adapter 182–187; STEP1 275–286 a 515–521.

### R03: Zapnutá FASTASSIGN není automaticky aktivní v STEP1

FASTASSIGN zapíná zkrácený warm trial jen uvnitř svého `_evaluate_candidate` scope. Výchozí STEP1 implementace ale volá `_assign_candidate` přímo. Samotné `fa_enabled=true` v options tedy neprokazuje, že tato optimalizace v aktivní generation větvi skutečně pracuje.

To je primárně výkonová / reportovací nesrovnalost, nikoli doporučení bez dalšího zkrátit přepočet. Ověřit skutečné `fast_trials` a plán operací, potom buď optimalizaci řádně integrovat s odpovídající akceptací, nebo ji v reportu označit jako pro tuto cestu neaktivní.

**Zdroj:** FASTASSIGN 160–194; STEP1 413; instalační řetězec V24917.

### R04: „Early exploration“ může běžet po celý horizont

Dodané options mají `sev_extend_early_horizon=true`. Modul severity relaxation umí prodloužit původní early horizont na celý běh. To je zvolená politika, nikoli prokázaná chyba. Není ale správné bez kontroly tvrdit, že závěrečné cykly automaticky používají přísnější režim než počáteční.

Před produkčním závěrem je potřeba určit, co tvoří finální validační bránu a zda má mít jiné limity než explorace. Neměnit tyto parametry potichu.

### R05: Testovací sady kolidují při společném spuštění

`python -m pytest tests diagfast_tests` skončilo 31 chybami při sběru: přímé importy `from conftest import ...` načetly stejnojmenný modul z druhé sady. Obě sady při samostatném spuštění v oddělených procesech prošly.

Je to reprodukovaná nekonzistence testovací infrastruktury, ne důkaz 31 chyb produkčního kalibrátoru. Případná oprava má přesunout sdílené fakes do jednoznačně pojmenovaného modulu / balíčku. Do té doby spouštět sady odděleně.

**Důkaz:** `evidence/baseline_pytest.log`, `tests.log`, `diagfast.log`.

## 12. Doporučené pořadí oprav a podmínky předání

1. **SUPPLYMIX transakce a full recovery:** sjednotit povinnost rollbacku, ochránit všechny mimořádné výstupy a odstranit neověřené převzetí nového rodiče.
2. **Společná verifikace rodiče:** matice, 12D, 11D, frozen context, úplnost a jedinečnost identit; explicitní numerické tolerance místo slepého hashového rebase.
3. **MOBILITY2:** jedna povinná kontrola po všech úpravách, pro každou škálu i fallback; živé ověření po recompute.
4. **Predikce a COM čtení:** model skutečného kandidáta, žádné cachované nuly po dočasné chybě.
5. **Důkazy a deklarovaná politika:** neztrácet zdrojové logy, ujasnit lokální/globální toleranci a stav reálně aktivních optimalizací.

Nový opravený build musí projít původními testy i těmito scénáři. Nesmí pouze změnit očekávání testů, přejmenovat FAILED na PLATEAU, vypnout ochrany ani rozšířit tolerance, aby testy „vyšly“.

Potom je potřeba řízený krátký test ve Visumu: odmítnutý generation pokus a obnova, odmítnutý SUPPLYMIX a chyba před dalším zápisem, TD numerická obnova, mobility near-band se smíšenými znaménky a kontrola shody finálního checkpointu s uloženou diagnostikou. Doporučení dlouhého bezobslužného běhu před těmito kontrolami nepovažuji za podložené.

## 13. Reprodukce a obsah důkazního balíčku

Auditní ZIP obsahuje tento report, `AUDIT_FINDINGS.json`, zdroj nových testů, jejich spouštěč, úplné protokoly a jednotlivé strojově zapsané reprodukce. Neobsahuje náhradní produkční zdroj ani opravený launcher.

V prostředí s pytest a závislostmi původního balíčku:

```text
python run_audit.py --source C:/R1/R1_V24917_GENFIX1
```

Na auditované verzi je očekávaný návratový kód **1**, protože testy požadují dosud chybějící bezpečnostní vlastnosti. V tomto auditu vyšlo **15 failed, 3 passed**. Výstupy nového spuštění se uloží do `rerun_evidence`.

Původní sady pro kontrolu základu spouštět samostatně:

```text
python -m pytest -q -p no:cacheprovider tests
python -m pytest -q -p no:cacheprovider diagfast_tests
```

Původní sada při běhu v pracovní kopii přepsala dva stavové výstupy `V24916_LAST_BOOTSTRAP_FAILURE.json` a `V24916_LAST_RUNS_LOCATION.txt`. Byly vráceny na původní bajty z ZIPu; následná kontrola všech 1 186 původních souborů zjistila **0 změn**. Nešlo o úpravu produkčního kódu.

## 14. Hranice závěru

Tento audit dokazuje existenci uvedených chyb na konkrétním zdroji a vstupních scénářích. Nedokazuje, že se všechny již projevily v uživatelově modelu, ani že některá z nich způsobila historický první pád generation. Bez obou snapshotů původního pádu stále nelze zpětně určit jeho přesnou změněnou položku.

Prošlé testy a manifesty jsou pozitivní důkaz konzistence dodávky, nikoli certifikace úplné správnosti modelu. Ruční kontrola se soustředila na aktivní bezpečnostně významné cesty; nejde o vyčerpávající důkaz bezchybnosti všech zděděných modulů ani o ověření všech COM rozhraní konkrétní instalace Visumu.
