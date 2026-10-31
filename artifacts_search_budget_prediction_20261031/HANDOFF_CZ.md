# Rozpočty hledání a audit predikce Generation, 2026-10-31

Základ: GitHub `a3fc6c691052764008ab065dc941b28182672aa5`, lokální shodný tree `f1efdda1662e6ce3eb674f0d9ffd7da3ce929b99`. Větev `codex/larger-search-budgets-20261031`. Uživatel potvrdil, že většími rozpočty myslí počet pokusů/vyhodnocení. Následně požádal nejprve o diagnostiku nespustitelného a3fc6c6 a o identifikaci chyby predikce profilu 920023. Start si mezitím obnovil odstraněním lock souboru a potvrdil, že kalibrace běží. Do tohoto procesu nebylo zasahováno.

## 1. Proč nešel poslední start

V nahraném `00_RESULT.json` je `FileExistsError` při `os.open(..., O_CREAT|O_EXCL|O_WRONLY)` nad `C:\Users\vilem_knap\R1F_742748e4\.R1_15A2_V16.lock`. Nativní Generation pokusy ještě nezačaly. Runtime status obsahuje správný SEVRELAX3 a schválené hodnoty GEH. Preflight cest prošel a původní .ver na disku měl stejný SHA před/po.

Po ručním smazání zámku uživatel potvrdil běžící kalibraci. **Neprokázali jsme PID/liveness původního vlastníka; nelze z těchto souborů rozhodnout, zda byl zámek opuštěný.** Nebylo implementováno automatické mazání locků, obcházení souběhu ani patch chráněného bootstrapu. Diagnóza a všech devět souborů jsou v `startup/`; SHA původních uploadů v `STARTUP_UPLOADS.json`. Při publikaci byla sjednocena zakončení řádků na LF.

## 2. Co skutečně ukazuje chyba predikce

`GENFIX2_FINAL_MOBILITY_AND_PREDICTION` / preview uvádí pro profil 920023 při scale 0.115395 hodnotu **−12.806566 voz./den**. Je to odhad finálních implementovaných efektů ze zónového operátoru před dodatečnou rho/sekantovou korekcí; není to přesná hodnota, kterou ve třetím pokusu použil plánovač.

STEP1 po prvním nativním pokusu používá měřené opravy:

`m(s) = m0 + delta_model(s) + (s/sk) * (m_measured(sk) - m0 - delta_model(sk))`.

Druhý a třetí plán mají `SECANT_MEASURED`. Zveřejněný nejmenší krok byl v plánování robustně přípustný; při tehdejším nulovém rozpočtu chráněných profilů a prahu 20 musela plánovací GEH brána 920023 předpokládat GEH pod 20. Přesnou korigovanou hodnotu tohoto profilu staré logy neukládaly.

| Scale | Skutečné GEH 920023 | Předpovězený globální vážený GEH | Skutečný globální vážený GEH |
| --- | ---: | ---: | ---: |
| 1.0 | 21.060184 | 24.183822 | 25.111921 |
| 0.239474 | 34.356264 | 28.840354 | 28.966310 |
| 0.115395 | 37.393888 | 29.711408 | 29.696367 |

Rodičovský GEH byl 1.522286. Globální predikce posledního kroku se lišila pouze o 0.015041 GEH (~0.051 %), ale na konkrétním profilu selhala. Menší koeficientový krok nedal menší místní odchylku. Takovou odezvu nelze reprezentovat jednou přímkou přes rodiče a předchozí pokus. Patnáctiprocentní robustní margin jen zkouší sousední větší scale uvnitř téhož modelu; není intervalem nejistoty skutečného assignmentu.

Při pozorování 5586 voz./den a uvedených GEH lze bez hádání znaménka odvodit:

- rodičovský tok byl buď 5700.3558, nebo 5472.8029;
- výsledný tok byl buď 8752.1557, nebo 3118.9957;
- skutečná změna toku měla tedy absolutně **nejméně 2353.807 voz./den**, nejméně 183.797násobek velikosti nekorigovaného odhadu 12.807;
- samotné přičtení −12.807 k rodičovskému toku by dalo GEH 1.353 nebo 1.695. To není tvrzení o korigovaném STEP1 odhadu.

Bez skutečných modelových intenzit nelze ze samotného GEH určit znaménko odchylky. Extrakt původních hodnot a SHA zdrojů je v `OBSERVED_RUN_EXTRACT.json`, výpočet v `PREDICTION_FINDINGS.json`.

### Konkrétní nesoulad v modelu

`r1_15a2_zonal_count_fit_v24917.build_problem` vytváří G z přiřazených vozidlových OD toků na zmrazených trasách. K jejich aktuálnímu originu přiřazuje produkční zónový aktuátor, k destination atrakční a odečítá jeden průměr rodiny:

`delta_od ≈ u_origin + v_destination - g_family`.

To není Jacobian celé nativní TG→TD→20A/20B→assignment sekvence. Nativní dvojitě omezená TD znovu řeší OD vazby a převod osobních účelových cest na vozidla sdružuje oba OD směry. Stávající TD `CountModel.delta_for` to výslovně modeluje přes `0.5*(dT[o,d]+dT[d,o])`; zónový G tento účelový/směrový převod nemá. Samotná vozidlová zóna origin proto nemusí být domácí produkční zónou, jejíž koeficient vytvořil danou cestu.

Čistý matematický protipříklad používající skutečný současný `build_problem`:

- osobní T12=1000, T21=0;
- po symetrizaci je vozidlové OD v každém směru 500;
- mění se P1 a A2, oba o log-step 0.01, při vyrovnané P/A změně;
- současný G dává změnu profilu ve směru 1→2 **+7.5**, v opačném **−2.5**;
- první řád symetrického osobního→vozidlového převodu dává **+5 v obou směrech**.

To reprodukuje schopnost modelu splést i znaménko. **Není to přehrání Visumu ani důkaz, že přesně tento člen způsobil celých 2354 vozidel na 920023.** Zjednodušená TD citlivost, převody a změny tras mohou působit současně. Konkrétní operační podíl bez mezivýsledků OD nelze určit.

Druhá ověřená mez: `TwoModeRouteCollector.incidence` přepočítává objem na aktuální OD, ale ponechává podíly původních uložených tras (`live_volume/stored_volume`). `accepted_state_changed` zachovává path epoch až do plateau. Původní parita je vázána na assignment při vzniku epochy, nikoli na každý následný rodičovský assignment. Ani změny tras pevné poptávky ostatních DSegů nepředpovídá změna čtyř W/S matic. Globální rho a sekanta z jednoho směru tento lokální nedostatek neidentifikují.

Dodaný pokus neměl hlášený chybějící OD support (všude PASS a 0 missing). Gapy byly 0.00122141 / 0.00054224 / 0.00044081. Tyto kontroly nepotvrzují správnost lokálního derivativního modelu. Finální salary split vykázal chybu implementovaného log efektu nejvýše 1.65e-16 a P/A součty byly vyrovnány, takže podklady nevykazují chybu přepisu požadovaných efektů jako vysvětlení této odchylky. Současné podklady rovněž nestačí k nezávislému vyloučení závislosti na stavu/pořadí nativních přepočtů mezi backtracky.

Reprodukce matematických závěrů bez Visumu:

```text
python artifacts_search_budget_prediction_20261031/reproduce_prediction_findings.py.txt
```

## 3. Nový audit každého skutečného pokusu

`r1_15a2_step_search_v24917.py` nyní uloží `TRY_nn/STEP1_PRED_AUDIT.json` pro všech 248 profilů:

- `raw_proposal_delta` bez dodatečné rho/škálové sekantové korekce;
- `planner_model` a `planner_geh`, přesně z modelu použitého pro krok;
- `measured_model`, `measured_geh` a chybu v voz./den;
- předchozí měřenou scale, režim a původ modelu (`LINEAR_FIT` / `MEASURED_ZONAL_REFIT`), rodičovský a kandidátský state hash, assignment gap;
- deset největších lokálních chyb.

Používá již dostupné 12D řádky, žádná další COM čtení ani assignment. Nepublikuje odhad jako důkaz přijetí nebo jako rozklad účinků nativních operací. Nekonzistentní profilová identita, pozorování, role nebo neplatné intenzity se označí `UNAVAILABLE`.

Finální preview se navíc uloží před první změnou modelu, včetně scale vzniklé dodatečným pre-apply zmenšením mimo plánovací grid. Tak se po přepočtu již nesestavuje zpětně ze změněného modelu; jde o odchylku mezi skutečně předem použitou predikcí a skutečným výsledkem. Je zachována samostatná identita směru po měřeném zonálním refitu.

Samotný fyzikální G ani nativní solver nebyl v této úpravě nahrazen. Pro kvantitativní oddělení příčin bude potřeba spojit již čtené W/S vozidlové matice před/po pokusu se zmrazenou incidencí: rozdíl G-predikce vs. tok přepočtený ze skutečné OD změny ukáže chybu TG/TD/převodu; zbývající rozdíl do skutečného profilu zahrne změny tras a odezvu ostatních DSegů. Toto rozšíření nyní není implementované a staré chybějící mezivýsledky nedopočítáváme fikcí.

## 4. Větší rozpočty pro další spuštění

| Rozpočet | Dosud | Nově |
| --- | ---: | ---: |
| Generation: nejvýše skutečných pokusů za blok | 3 | 6 |
| TD cykly 1–2: eval / iterace | 28 / 4 | 56 / 8 |
| TD cykly 3–4: eval / iterace | 60 / 10 | 120 / 20 |
| TD cykly 5–100: eval / iterace | 60 / 12 | 180 / 35 |
| TD vnější škály v jedné realizační větvi | 3 | 5 |

Škály TD jsou 1, 0.5, 0.25, 0.125, 0.0625. Dvě možné komponentní izolace a případné samostatné IZ/b/c realizační větve zůstávají původní; pět škál proto není celkový limit všech vnějších přepočtů celého TD bloku. Generation i realizace končí dříve, jakmile přijmou kandidáta.

`R1_RUN_OPTIONS.json` a defaults: `tg_max_trials=6`, `td_realization_max_trials=5`, `td_inner_max_evaluations=180`, nově `td_inner_budget_multiplier=2`. Násobitel 1..4 je validovaný, lze jej zadat i přes `R1_TD_INNER_BUDGET_MULTIPLIER`. Změna samotného stropu by nerozšířila časné fáze, proto `r1_15a2_td_count_blend_v24917.search_budget` násobí původní fázový rozpočet a následně aplikuje strop 180 a původní celkovou mez 35 iterací. Při omezení počtu evalů se zachová návazná mez iterací `max(2, cap//5)`.

Při zkrácení požadovaného rozpočtu je zachováno `allow_progress_continue` a diagnostika původního, požadovaného i skutečného rozpočtu v `v24917_search_budget`. Budget exhaustion není označen jako prokázané stationarity. Starý explicitní malý rozpočet s násobitelem 1 zůstává podporovaný.

Lokální časový limit TD **4 hodiny** zůstává; dřívější konvergence/stagnace nebo stop mohou hledání ukončit dřív než počtový limit. Aktuální FRESH100 launcher nadále používá původní režim bez globálního wallclock limitu. Číslo 64800 ve zděděné kompatibilní konfiguraci proto není nový autoritativní globální limit tohoto launcheru.

Schválené GEH limity SEVRELAX3, IDP/TD skóre 60/40 a F≤0.999, mobility a koeficientové meze, OSRM LONG masky, nativní IPF tolerance, rollback a zacházení s epochami nebyly uvolněny. Testy ověřují šest skutečných Generation pokusů a jediné konečné ověřené obnovení, časné přijetí i plynulé předávání TD rozpočtu.

## 5. Soubory a důkazy

Produkční změny: `R1_RUN_OPTIONS.json`, `r1_15a2_demand_policy_v1.py`, `r1_15a2_td_count_blend_v24917.py`, `r1_15a2_step_search_v24917.py`. Nových 24 testů v `tests/test_v24917_search_budget_prediction_audit.py`; čtyři existující testové soubory aktualizují schválené defaulty nebo zpřístupňují konfiguraci testovacího harnessu. U kontroly živých call signatures se pevné 3/3/60 nahradilo kontrolou aktuálních validovaných limitů; přesné nové limity ověřují nové testy. Oba SHA manifesty aktualizované, všech 91 runtime položek zachováno, 1059 původních chráněných souborů beze změny.

Cílená sada: 159 PASS; dodatečné rozpočtové/intrazonální kontroly: 53 PASS; závěrečné testy auditu, transakce a zonálního refitu: 61 PASS. První plná sada odhalila jednu starou testovou podmínku `len(scales)<=3`, která neodpovídala schválenému rozpočtu 6; její celý log je zachován. Nešlo o odstranění akceptační ochrany. Finální celé sady: **2428 PASS, 4 SKIPPED; DIAGFAST 189 PASS; audit GENFIX2 18 PASS**. Příkazy, exit codes a počty viz `CHECKS.json`, `TEST_TOTALS.json` a příslušné logy.

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 PYTEST_ADDOPTS='--basetemp=/tmp/r1longdir' /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/larger_search_budgets_20261031/release_checks --timeout 600
```

`IMPLEMENTATION.patch` obsahuje všechny zdrojové změny, nové testy a manifesty. Použít `git apply --unidiff-zero IMPLEMENTATION.patch` pouze na uvedený základ; kompletní GitHub ZIP je již upravený. SHA důkazů jsou v `ARTIFACT_SHA256.json`.

**LIVE_VISUM_NOT_RUN.** Uživatelův běžící a3fc6c6 proces nebyl aktualizován. Nový ZIP použít až pro další spuštění; během běhu neměnit ani R1_RUN_OPTIONS.json. Na dalším běhu lze z `STEP1_PRED_AUDIT.json` konečně přesně přečíst skutečnou korigovanou předpověď 920023 a její chybu. Oprava celého nativního citlivostního modelu je samostatná navazující úloha, nikoli prokázaný výsledek tohoto balíku.
