# TD optimalizace 2026-10-30

Implementováno všech pět požadovaných optimalizací. Vývojová větev `codex/td-perf-20261030` vychází z opravy LONG Generation `a63cb38ef459004ac152b45536a40bfcbcc95aab`; lokální mirror `6e8159069350560f5a3743dd5d1fda5d8728f231` má totožný strom `4beba774320bcbda12138b00d1c455b32890556d`. Zahrnuje tedy předchozí opravu předávání LONG_COMPOSITE do LONGGUARD1. Žádný zásah do právě běžícího Visumu: `LIVE_VISUM_NOT_RUN`.

## Co ukázal dodaný běh

Dodaný TD cyklus skončil `ACCEPTED_FINECDF_TD`, scale 1, gap 0,00111732. Přijal změnu c ve WORK_noE_C a WORK_noE_noC. Vlastní rodičovské GEH tohoto TD kroku je 40,73705 → 40,68361; nesměšujeme jej s rodičem starších Generation/SupplyMix souborů. Vnitřní normalizované skóre 1 → 0,9633518 je jiná metrika než vnější GEH.

Čas TD je 2399,609 s, přibližně 40 minut. Časování eviduje 28 vyhodnocení solveru a 40 `procedure_sequence` calls. Tyto čítače jsou vnořené/inclusive: nejsou důkazem 40 nezávislých celých TD řetězců ani 12 zbytečných přepočtů. Duplicitní restore je prokázán přímo řídicím kódem a novým integračním testem.

V běhu bylo šest aktivních skupin. První poll dokončil obě znaménka b i logc pro každou skupinu, včetně SCHOOL a LONG. Druhý poll stihl jen dvě b sondy. Nové prokládání zejména chrání větší pool (až 12 skupin) a částečné polly. Původní běh není dokladem úplného vynechání SCHOOL/LONG: jejich návrhy byly skutečně vyhodnoceny a jejich generation freeze readback prošel. Žádná stationarita nebyla certifikována.

`UPLOADED_TD_AUDIT.json` a `inputs/` uchovávají 16 načtených samostatných podkladů a přesné SHA-256. ZIP a dva ACCEPTED NPZ přesahují limit přenosu 32 MiB a nebyly načteny; jejich obsahové hashe proto nebyly nezávisle ověřeny. Závěry o přijetí vycházejí z dodaných JSON, ne z prohlédnutí velkých maticových checkpointů.

## Implementace

1. **Sondy:** `r1_15a2_td_joint_v24917.py` nyní proloží b a logc napříč všemi skupinami před druhými znaménky. Vedoucí osa i znaménko rotují; neproveditelné znaménko u meze neodebere souřadnici její první dostupnou sondu. Při 28 evaluacích dostane všech 12 vnitřních skupin obě souřadnice. Původní velikosti, meze a množina sond zůstávají zachovány; `coordinate_coverage` v `TDJOINT_SEARCH.json` ukazuje skutečné pokrytí. Rozpočet ani kritérium úplného pollu/stationarity se neuvolňují.
2. **Duplicitní best restore:** nový `r1_15a2_td_restore_v24917.py` instaluje obal skutečného bridge. První restore vždy provede původní nativní výpočet a ověření všech požadovaných OD. Jednorázový receipt dovolí následující shodný restore vynechat teprve po novém čtení parametrů, OD, protected 9001/9697/9116, utility 9002, Generation, ADDVAL1, všech exportních vehicle OD a šesti DIS; ověřuje též interní skim/family pole, aktuální dokončenou epochu, session/run identitu, zóny a procedurální kontext. Nedostupný či změněný důkaz vede k původnímu nativnímu přepočtu; skutečné porušení chráněných zdrojů se dál předá transakčnímu vlastníku. Nově se také kontroluje, že nativní restore sám nepřepsal požadované a/b/c. Receipt se spotřebuje a ruší před každým set_abc/execute i při chybě. FROZEN_PATHS bez potřebné živé autority tuto úsporu nepoužije. Vnější realizace, acceptance, reject a rollback se nevynechávají. `TD_PERF_RESTORE_AUDIT.json` vykazuje skutečné native restores/reuses a jejich čas.
3. **Čtyři váhy skimů:** `r1_15a2_finecdf_gapfix_v24917.py` čte pro vážené vzdálenosti pouze NATIVE_CW/CW_NOT/CS/CS_NOT. Stejně je ohraničen refresh skimů ve `r1_15a2_trial_adapter_v24917.py`. Veřejné úplné čtení Generation a path incidence zůstává mimo tuto scope původní. Při 12 DSeg odpadá osm GetValues na refresh; pro 681² float64 je to 29,68 MB dat, před započtením režie COM/Python převodu.
4. **FineCDF indexy:** nový `r1_15a2_td_numpy_v24917.py` sdílí výběr buněk, coarse/fine bin indexy a diagonální masku pro shodnou vzdálenost/hrany/grid během jediného evaluate(). Připravuje 3 sady místo 12. Žádná indexová cache nepřežije volání, chybu ani novou epochu. Každá komponenta má nadále vlastní hmotnosti, cíl, redukce, 512bodovou CDF a residualy. Shoda části výpočtu od `weights` po návratový slovník je ověřena také přes AST.
5. **Hashování:** dynamický manager v paměti používá existující blokový float.hex helper. Přesné kopie LONG/FOREIGN přebírají hash právě načteného CL/CF DIS. Plných hashů je 8 místo 10; všech šest DIS se nadále čte a ověřuje. SHA protokol, znaménko nuly a výsledný epoch hash jsou totožné.

Navíc proof scope sdílí opakované `read_matrix` pouze během post-execution ověřování. Zaniká před jakýmkoli případným nativním přepočtem. Není to cache přes zápisy či mezi kandidáty.

Runtime zapojení vlastní `r1_15a2_v24917_runtime.py`, aktualizován explicitní runtime manifest a jeho refresh nástroj. Původní V24916 bridge/dynamický skim soubor i reference v19 zůstaly byteově shodné; změny se instalují na skutečné třídy až při startu opraveného launcheru. Standardní 01/02 launchery zůstávají stejné.

## Naměřené výsledky

Syntetické matice 681 × 681, pět opakování, jeden BLAS thread; detailní průběhy v `NUMPY_BENCHMARK.json`:

| Samostatná výpočetní část | Původní medián | Nový medián | Zrychlení |
| --- | ---: | ---: | ---: |
| FineCDF všech 12 cílů | 0,24905 s | 0,08513 s | 2,93× |
| Jeden hex-cell hash | 0,21379 s | 0,11649 s | 1,84× |
| Sestavení šesti skimů/čtyř rodin v NumPy včetně hashů | 2,21570 s | 0,97323 s | 2,28× |

Výstupy všech metrik i všech skim polí/epochových hashů byly přesně stejné. Nativní/COM čas není v benchmarku změřen. Z těchto čísel neplyne 2–3× zrychlení celého TD. Jednu shodnou nativní obnovu lze při úplném důkazu skutečně vynechat, ale důkaz přidává čtení; čistá časová úspora celé kalibrace musí být změřena na dalším živém běhu. První kandidát outer scale=1 se nepřebírá z inner stavu a nadále prochází vlastní realizací.

## Ověření, integrita a bezpečnost

- **138 focused passed**; zahrnuje 54 nových testovacích případů a regresi TDJOINT/LONG/dynamic skims.
- Závěrečná hlavní sada: **2238 passed, 4 skipped**; DIAGFAST **189 passed**; audit **18 passed**. Návratové kódy jsou všechny 0; `verified_final/CHECKS.json` a logy.
- Test volá skutečný sealed `run_finecdf_inner`, původní `execute` a `restore_state` nad offline native seam: optimizer restore provede jeden přepočet, následný owner restore jej po důkazu vynechá. Procedurální cleanup se provede i po vynechání; jeho chyba stále zastaví krok.
- Testy zahrnují OD/vehicle/utility/DIS/cached-array drift, mutation/assignment/session/run změny, přepsání parametrů nativním výpočtem, FP/FA LONG/SCHOOL, protected data, selhání nativního výpočtu a zánik read scope. Tolerance původního rollbacku je zachována.
- Launcher subprocess ověřuje skutečné navázání všech nových wrapperů a manifestovou integritu.
- `RELEASE_INTEGRITY.json`: 89 runtime souborů, 171 release souborů, všech 1059 chráněných originálů beze změny, shodné hashe a syntaxe všech 12 změněných/přidaných Python souborů. FineCDF matematické AST shodné; `git diff --check` prošel.
- První širší běh našel jednu chybu v novém testu: patchoval module instance před jejich nahrazením launcherem. Test nyní pracuje s aktuální module instance skutečného adaptéru. Log v `initial_regression/` je zachován. Nešlo o selhání živé kalibrace.

Konfigurace váhy/cíle/limity, nativní IPF, generování, maskování LONG >=80 km bez horní meze, SCHOOL FP/FA, FOREIGN, všechny akceptační a ochranné brány zůstávají zachované. Žádný nový COM zápis, `LoadVersion`, změna živého modelu, merge ani přerušení běhu nebyly provedeny.

Další omezený krok: při příštím autorizovaném běhu kompletního ZIPu porovnat TD stage timing, `TD_PERF_RESTORE_AUDIT.json` a pokrytí souřadnic v `TDJOINT_SEARCH.json`. Soubory právě běžícího procesu nenahrazovat.

Přesné závěrečné příkazy (výstupy mimo zdrojový strom):

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_td_numpy_perf.py tests/test_v24917_td_restore_perf.py tests/test_v24917_tdjoint1.py tests/test_v24917_long_composite_diagnostic.py tests/test_v24916_dynamic_assignment_skims.py --basetemp=/tmp/r1tdperf3
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /workspace/.venvs/r1/bin/python benchmarks/run_td_numpy_benchmark.py --output /workspace/work/td_perf_20261030/NUMPY_BENCHMARK.json
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/refresh_v24917_manifests.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS=--basetemp=/tmp/r1long /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/td_perf_20261030/verified_final
git diff --check
```
