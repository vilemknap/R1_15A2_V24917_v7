# Oprava blokované LONG Generation: DIRECTIONAL / DIRECTED

Baseline je uživatelem označená živá verze `977cef4e77ab67f159bbe392edc8d3d485dc72ee`, strom `46b7e1d6fae3f513edfc521d1b8d302dc1f0236d`. Lokální přesný mirror je `92dd9589edd90ce43486e3a4125799ffaf789328`. Oprava je oddělená ve větvi `codex/long-profile-direction-fix-20261031`; žádná změna nebyla nasazena do živého Visumu.

## Potvrzená příčina z aktuálního běhu

Uživatel dodal 18 souborů. Jejich velikosti, SHA a návaznost jsou v `LIVE_EVIDENCE_CHECKS.json`; všech **45 kontrol prošlo**. Čtecí skript je přiložen jako `audit_inputs.py.txt` (pracuje s původními lokálními cestami z `UPLOADS.json`).

- `LONGGUARD1_PARENT.json`: `support_clean=true`, objem pod 80 km je 0, `fine_cdf_verified=true`, FineCDF RMSE `0.050598093290813106`, `long_generation_permitted=true`. Oprava předávání LONG_COMPOSITE v této verzi tedy funguje.
- `LONG_SHARED_CACHE_DEFERRED.json`: přesně `LONG_INCIDENCE_PROFILE_AUTHORITY_DIRECTION_INVALID`.
- `V24917_FIT_SUMMARY.json`: LONG je vyžádaný, ale `long_generation_candidate_eligible=false`; `long_school.long_deferred_reason` obsahuje stejnou chybu a `long_zone_steps=0`.
- Návrh, přijaté preview ani projekční CSV neobsahují žádný `ADD_PROD_L` / `ADD_ATT_L` krok. Není to zamítnutý LONG pokus ani pouze zaokrouhlení v tabulce.

Produkční bootstrap `r1_15a2_fresh0_shortroot_parent_v24916._load_current_profile_authority()` doplňuje pro CSD CSV bez pole `observation_direction` hodnotu **`DIRECTIONAL`**. Aktuální autorita obsahuje **196 těchto směrovaných CSD profilů a 52 městských BOTH profilů**. LONG čtečka přijímala pouze `DIRECTED` a `BOTH`, a proto celou incidenci odmítla už u prvního CSD profilu. Dosavadní fixture používaly `DIRECTED` a nesoulad s produkčním bootstrapem neodhalily.

## Rozsah opravy

`r1_15a2_long_incidence_read_v24917.py`: na hranici čtení autority se jediný známý název `DIRECTIONAL` převádí na `DIRECTED`. Stále se kontroluje přesná směrovaná trojice linka/from/to, úplný seznam CountLocations a původní jedno-/obousměrný rozsah. Neznámé názvy se odmítají. Zdrojový roster, observations ani předané profily se nemění.

Sdílená cache i samostatný čtecí export používají tuto společnou kontrolu. Oprava nemění získávání tras, přepočet citlivosti, kalibrační meze, mobilitu, masku OSRM >=80 km bez horní meze, referenční FineCDF, TD, akceptaci ani rollback.

`tests/test_v24917_long_profile_authority_direction.py`: 11 nových regresních případů. Testy používají i skutečný bootstrap loader a ověřený roster 248 profilů. Kontrolují průchod sdílenou cache až k nenulovému zónovému LONG návrhu, čtecí export, odmítnutí neznámých názvů, zakázané přidání opačného směru, odebrání směru z BOTH a záměnu orientace linky. Test s celým rosterem nemění zdroje; časované změny bootstrap konstant se po testu obnoví.

Manifesty byly přesealovány po ověřené změně. Standardní `diagfast_tools/refresh_source_manifest.py` doplnil také dva již existující fresh launcher zdroje do release manifestu; jejich obsah zůstává shodný s baseline. Runtime manifest zachoval **všech 91 původních klíčů**, včetně fresh launcheru. Změnily se pouze dva runtime SHA: čtečka LONG a navázaný release manifest. Plný `tools/refresh_v24917_manifests.py` zde nebyl použit, protože jeho statický seznam by neponechal oba fresh launcher záznamy této baseline.

## Ověření

- Nová sada na původním produkčním kódu: **6 selhání, 5 průchodů**. Tři pozitivní scénáře končí přesnou živou chybou; tři scénáře kontroly orientace se k původní přesné směrové kontrole ani nedostanou. Pět neznámých názvů je správně odmítnuto už na baseline. Log `baseline_reproduction.log`.
- Po opravě cílený výběr: **90 prošlo**, návratový kód 0, `focused_tests.log`.
- Celá hlavní sada: **2312 prošlo, 4 přeskočeny**.
- DIAGFAST: **189 prošlo**; GENFIX2 audit: **18 prošlo**. Všechny tři procesy skončily s kódem 0; přesné příkazy jsou v `CHECKS.json`.
- **1059 základních, 176 release a 91 runtime SHA odpovídá souborům**, `RELEASE_INTEGRITY.json`.
- `git diff --check`, kompilace obou upravených/přidaných Python souborů a reverzní kontrola přiloženého implementačního patche prošly.

Základní příkazy z kořene zdrojů:

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_long_profile_authority_direction.py
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_long_profile_authority_direction.py tests/test_v24917_long_incidence_read.py tests/test_v24917_long_cache_generation.py tests/test_v24917_long_composite_diagnostic.py tests/test_v24917_long_diagnostics_epoch_fix.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python diagfast_tools/refresh_source_manifest.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS=--basetemp=/tmp/r1longdir /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/long_live_cache_fix_20261031/verified_release
git diff --check
git apply --reverse --check artifacts_long_profile_direction_fix_20261031/IMPLEMENTATION.patch
```

## Stav dodaného Generation kroku a použití opravy

Generation přijala třetí kandidát se škálou `0.181579`: vážené GEH **31.7050954836247 → 30.331603748167616**, zlepšení **4.332085 %**, gap `0.00396248`. První dvě škály byly zamítnuty kvůli novým závažným GEH a chráněným profilům. Přijatých 2991 řádků zahrnuje W/S, salary a hraniční úpravy, **žádný LONG koeficient**. Soubor `V24917_LONG_SCHOOL_ROWS.json` v tomto kroku obsahuje 240 hraničních W/S řádků; jeho název není důkaz změny LONG. Aktivní count fit má 247 kladných CAL pozorování; autorita stále zahrnuje všech 248 profilů. Součty přes profily nejsou počty unikátních cest.

Opravený komplet používá tentýž launcher `01_SPUSTIT_V24917_FRESH_UNIVERSAL_TDPERF_SILENT.py`. Oprava se uplatní při dalším spuštění tohoto kompletu. Právě běžící Python proces má již načtený původní modul a tuto opravu nepřevezme pouhým přepsáním souboru. Současný běh nebyl zastaven ani změněn.

`LIVE_VISUM_NOT_RUN`: offline důkaz odstraňuje konkrétní reprodukovaný blokátor. Nedokazuje, že příští LONG návrh projde všemi dalšími živými kontrolami nebo bude přijat. Při dalším spuštění má LONG projít kontrolou směrové autority; následně je rozhodující `LONG_SHARED_CACHE_INCIDENCE.json`, případný nový přesný důvod odložení a skutečné přijaté řádky `ADD_PROD_L` / `ADD_ATT_L`.

Textové kopie důkazů používají LF; v kopii baseline pytest logu jsou odstraněné pouze koncové mezery. Původní SHA logu a popis převodu je v `EVIDENCE_COPY_FORMAT.json`; SHA původních nahraných souborů jsou v `LIVE_EVIDENCE_CHECKS.json`.
