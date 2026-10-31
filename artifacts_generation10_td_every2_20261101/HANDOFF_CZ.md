# Generation ±10 %; kalibrační TD každý druhý cyklus

Nová konfigurace nastavuje mírně větší Generation kroky a omezuje optimalizační blok TD/FineCDF na vnější cykly **2, 4, 6, …, 100**. CATCH_UP zůstává vypnutý; W/S meze produkce **0,5–3** a atrakce **0,5–5** zůstávají součástí balíku.

## Výsledné chování

- **TG:** plný REFINE návrh má v každém cyklu strop **+10 % / −10 % výsledného P/A účinku**, v log prostoru log(1.10) / log(0.90). Nepřebírá dřívější nižší přibližně 3% strop pozdních fází. Škála 0.05–1 může skutečný krok dále zmenšit. Každá zóna stále dostává vlastní fitted krok a celkové koeficientové/mobilitní meze jej mohou omezit.
- **TD kalibrace:** `td_policy=EVERY_N`, `td_every_n_cycles=2`, `td_first_cycle=false`, `td_when_generation_plateau=false`. Nespustí se navíc v C1 ani na lichém plató TG. Přeskočení vrací stejný přijatý stav, označuje neprovedené TD hledání a neprohlašuje konvergenci.
- **Nativní výpočet trip distribution uvnitř TG:** zůstává nutnou součástí úplného přepočtu a ověření každého Generation kandidáta. Změna frekvence se týká drahého **kalibračního hledání b/c pomocí FineCDF**, nikoli vynechání nativního přepočtu poptávky při změně TG.
- **Rozpracovaný návrat/pending TD:** původní pravidlo dokončení výslovně obnoveného neúplného TD kroku bez výsledku TG je zachované. Nejde o běžný dodatečný TD fit na lichém cyklu nového běhu.

Samotné ADD_ATT může při společné změně ADD_SALARY kompenzovat jeho účinek; procentní strop se týká P/A, nikoli izolovaného koeficientu při takové kompenzaci. Strukturní nuly a grandfathering rodičů mimo obálku se nemění.

## Implementace a návaznosti

Baseline GitHub **7b4c681732080a28264c616daee87f7d23a8d643**, lokální zrcadlo **1e3b9978cad62cb609b8b81526be80bb06d3154b**, tree **14bf238966e91c797910e257ab7096cc75e97c01**. Nová větev `codex/generation10-td-every2-20261101`.

1. `R1_RUN_OPTIONS.json` a výchozí hodnoty `r1_15a2_demand_policy_v1.py` jsou sladěné na pravidelné TD každý druhý cyklus bez prvního/plateau extra spuštění.
2. `r1_15a2_targeted_generation_v24917.py` má REFINE ±10 % a nepřebírá nižší stage limit. CATCH_UP je dál vypnutý v dodané konfiguraci.
3. `r1_15a2_fresh_universal_v24917.py` kontroluje novou periodu, oba zakázané extra spouštěče a správný desetiprocentní TG režim. Kontrola skutečné nainstalované demand policy odmítá nesoulad vzniklý i přes R1_* prostředí. Staré vynucení TD v každém cyklu by bez této úpravy blokovalo start nové konfigurace.
4. Sledování stacionarity rozlišuje plánovanou mezeru od dokončeného TD hledání. Vynechané TD **nepřidává** důkaz ani počet stacionárních hledání. Již ověřená série se může zachovat přes plánovanou mezeru pouze při úplné TG bez změny; jakýkoli pokrok nebo neověřená TG ji zruší. Následující skutečné úplné TD musí znovu potvrdit stav. Jinak by periodické vynechání sérii vždy nulovalo a konfigurace dvou potvrzení by nikdy nemohla dosáhnout.
5. Testy kontrolují přesně 50 skutečných volání TD ve 100 cyklech, včetně oddělení plató, restartu, pending výjimky a nepřítomnosti nového důkazu na přeskočeném TD. Staré explicitní opt-in chování prvního cyklu je ověřované samostatně, ale není součástí nové konfigurace.
6. Oba navázané SHA manifesty jsou obnovené bez změny pokrytí. Chráněné původní soubory se nemění.

Integrační DIAGFAST test používá skutečný coupled controller s testovacím adaptérem: při změnách TG v C1–C6 a následném plató volá TD v C2,C4,C6,C8,C10, ověřená stacionarita vznikne z úplných TD v C8 a C10 a běh skončí před TG C11 s ověřeným finálním stavem. Lichý C9 sám nepřidává žádné nové potvrzení.

Zůstává **6 nativních pokusů TG**, dosavadní vnitřní TD rozpočty a SupplyMix **24 skupin / 240 hran / 4 pokusy**. Akceptační GEH/IDP/severity pojistky, nativní assignment, čerstvé skimy, SCHOOL/LONG samostatné obálky a ověřený in-memory rollback nejsou uvolněny.

## Ověření

Cílených **202 testů prošlo**. Test používá skutečný `wrap_td`, nikoli pouhé čtení JSON: běžné TD volá přesně v cyklech 2,4,…,100, v lichých vrací policy skip se `search_complete=false`. Stavové testy nedovolí potvrdit stacionaritu samotným vynecháním ani přeskočit neúplnou TG. Návrhové testy ověřují skutečný P/A účinek ±10 % v C1 i C7 a nastavení v cyklech až do C100.

Finální výsledky celých sad jsou v `VALIDATION.json` a `checks/`. Příkazy:

Finálně: hlavní sada **2479 prošlo, 4 přeskočeny**, DIAGFAST **189 prošlo**, audit **18 prošlo**. Kompilace a kontrola diffu prošly. Všech **1059 chráněných SHA** souhlasí; release **180/180** a runtime **91/91** mají správné SHA a stejné pokrytí jako baseline.

První celá regrese měla hlavní sadu a audit zelené, tři starší DIAGFAST testy ještě očekávaly výchozí TD periodu 5, první cyklus a plateau výjimku. Jejich očekávání a celý simulovaný coupled průchod jsou aktualizované pro schválenou periodu 2; explicitní legacy opt-in zůstává pokrytý. První logy jsou v `checks_initial/`, finální v `checks/`.

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_targeted_catchup.py tests/test_v24917_fresh_universal_tdperf.py tests/test_v24917_aligned_bounds.py tests/test_v24917_supply_mix.py tests/test_v24917_safetyfix1.py tests/test_v24917_td_stage_integration.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/refresh_v24917_manifests.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/generation10_td_every2_20261101/checks_verified
PYTHONPYCACHEPREFIX=/workspace/work/generation10_td_every2_20261101/pycache /workspace/.venvs/r1/bin/python -m py_compile r1_15a2_demand_policy_v1.py r1_15a2_targeted_generation_v24917.py r1_15a2_fresh_universal_v24917.py tests/test_v24917_targeted_catchup.py tests/test_v24917_fresh_universal_tdperf.py tests/test_v24917_supply_mix.py diagfast_tests/test_demand_policy.py
git diff --check
```

Úplný patch je v `IMPLEMENTATION.patch.gz.b64`. **LIVE_VISUM_NOT_RUN**: uživatelův běžící model, soubory ani COM nebyly měněny. Skutečná úspora času a zlepšení modelu s novou frekvencí nejsou změřené. Nová release SHA se posuzuje stávajícími integritními/certifikačními kontrolami.

Kompletní ZIP pro další spuštění:

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/generation10-td-every2-20261101.zip
