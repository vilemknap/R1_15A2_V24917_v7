# Konfigurace domácího WORK/SERVICE: produkce 0,5–3; atrakce 0,5–5

Uživatel potvrdil změnu horních mezí z 2,5/4 na **3/5** a následně novou spodní mez **0,5**. Balík proto sjednocuje aktivní domácí WORK/SERVICE návrhové meze a kontroly:

| Koeficient / kontrola | Před | Nyní |
| --- | --- | --- |
| `ADD_PROD_W`, `ADD_PROD_S` | 0,75–2,5 | **0,5–3,0** |
| `ADD_ATT_W`, `ADD_ATT_S` | 0,75–4,0 | **0,5–5,0** |
| Mobilitní pásmo produkce W/S | 0,75–2,5 | **0,5–3,0 pevné reference** |
| REFINE soft band W/S | shodné s původním hard band | **shodné s novými hard bandy podle role** |

Reference domácích produkčních koeficientů zůstává 1,0; nejde o pohyblivou referenci obnovovanou po cyklu. Meze ADD_ATT jsou absolutní koeficientové meze, nikoli násobek mobilitní produkční pojistky.

## Baseline a implementace

Výchozí kód je GitHub commit **1dc217e7205e840b71377a3a0ae4fcebbcb80e09**, lokální zrcadlo **c0099ede6e5ccee059dac7cde8986813ecfa6c93**, shodný tree **1b68c37f1e36d104a6d5a64fd92c2aa7530816ab**. Obsahuje již širší rozpočty TG/TD, predikční audit a SupplyMix 24 skupin / 240 hran / 4 pokusy. Nová větev: `codex/ws-prod3-att5-20261031`.

- `R1_RUN_OPTIONS.json`: `mg_min_ratio=0.5`, `mg_max_ratio=3.0`.
- `r1_15a2_demand_policy_v1.py`: stejné výchozí hodnoty i bez souboru options.
- `r1_15a2_targeted_generation_v24917.py`: hard i soft role-specific obálky v CATCH_UP a REFINE nyní PROD [0.5,3], ATT [0.5,5]. Samotná změna JSON by ponechala původní návrhové meze, proto jsou sladěné i tyto role-specific smlouvy.
- `r1_15a2_mobility_guard_v24917.py`: produkční default i samostatná absolutní atrakční pojistka odpovídají novým mezím; kontroluje se finální kandidát i skutečné hodnoty po nativním přepočtu.
- `r1_15a2_mobility_zone_v24917.py`: produkční band 0.5–3 pro W/S. SCHOOL má nově explicitně ohraničené oba konce svého původního pásma 0.75–2, aby z rozšíření W/S nepřevzalo nižší minimum.
- `r1_15a2_fresh_universal_v24917.py`: startovací i skutečně nainstalovaná runtime konfigurace vyžadují nové W/S meze; smíšená stará a nová konfigurace se odmítne. Záznam fresh contract nově obsahuje i produkční minimum 0.5.
- `r1_15a2_v24917_runtime.py`: publikovaná semantika atrakčního pásma je 0.5–5.
- Čtyři relevantní testové moduly jsou aktualizované a doplněné o oba konce nových mezí, skutečné návrhy koeficientů a kontrolu starých mezer v launch řetězci.
- Audit návrhového fallbacku je sladěn s novým stropem 3. Jeho vstup je 2.4 s požadovaným +50% krokem (raw 3.6), aby test nadále prokazoval skutečné omezení fallbacku, nejen změněné očekávané číslo.
- Oba SHA manifesty jsou aktualizovány bez změny jejich seznamu souborů.

Historické zapečetěné konfigurace nejsou přepisovány. Zpětně kompatibilní scalar bounds query bez W/S role ponechává své původní pásmo; aktivní W/S dostává role PROD/ATT i přes původní multiblock mapper. Regresní testy ověřují, že nové meze skutečně doputují do koeficientových řádků, nikoli jen do reportu.

## Zachované samostatné smlouvy

- SCHOOL P/A zůstávají původní AMDY; kontrolní pásmo SCHOOL zůstává **0,75–2,0**.
- LONG produkční reference **0,3**, band **0,15–0,45**, další samostatné LONG meze a OSRM maska zůstávají.
- ZAHR koeficienty zůstávají **0,5–10 × pevná run-start reference**; hraniční P/A mají vlastní původní obálku.
- ADD_SALARY má původní vlastní meze. Při jeho společném ladění může ADD_ATT kompenzovat změnu salary faktoru; zachované per-step limity se posuzují na výsledném P/A účinku.
- Strukturální nuly zůstávají nulami. Rodič mimo nové pásmo smí držet hodnotu nebo se vracet, nikdy se vzdálit dále; nedochází k automatickému ořezání rodiče.
- Akceptační GEH/IDP/severity pravidla, TD b/c prostor, přiřazení, čerstvé diagnostiky a ověřený rollback se nemění. SupplyMix zůstává **24/240/4** s kroky 4,3,2,1 ADDVAL1.

## Ověření

| Kontrola | Výsledek |
| --- | --- |
| Cílené testy čtyř oblastí | **134 prošlo** |
| Další end-to-end případy nové obálky | **4 prošly** |
| Hlavní sada | **2458 prošlo, 4 přeskočeny** |
| DIAGFAST | **189 prošlo** |
| Audit GENFIX2 | **18 prošlo** |
| Chráněný základ | **1059/1059 SHA souhlasí** |
| Release / runtime manifest | **180/180 a 91/91 SHA souhlasí; pokrytí zachováno** |
| Kompilace a `git diff --check` | **PASS** |

Pozorované výsledky jsou v `VALIDATION.json` a `checks/`. Cíleně nejprve prošlo **134 testů**, poté další **4 nové end-to-end případy** pro CATCH_UP/REFINE a oba konce nové obálky. V prvním průchodu cílenou sadou bylo nutné opravit starší test: při společném ADD_SALARY nesprávně vztahoval limit P/A kroku na samotný ADD_ATT. Test nyní kontroluje výsledný P/A efekt, správné absolutní meze koeficientu a zachovaný produkční krok; produkční step limity se kvůli testu neměnily.

První celá regrese měla hlavní sadu i DIAGFAST zelené; audit ještě očekával starou mez 2.5. Po jeho úpravě na nový schválený strop a zesílení vstupu nad 3 proběhla celá regrese znovu. Původní výstupy jsou v `checks_initial/`, finální v `checks/`.

Příkazy:

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_aligned_bounds.py tests/test_v24917_mobility_guard.py tests/test_v24917_targeted_catchup.py tests/test_v24917_fresh_universal_tdperf.py
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_targeted_catchup.py -k new_ws_band
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/refresh_v24917_manifests.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/ws_prod3_att5_20261031/checks_verified
PYTHONPYCACHEPREFIX=/workspace/work/ws_prod3_att5_20261031/pycache /workspace/.venvs/r1/bin/python -m py_compile r1_15a2_demand_policy_v1.py r1_15a2_fresh_universal_v24917.py r1_15a2_mobility_guard_v24917.py r1_15a2_mobility_zone_v24917.py r1_15a2_targeted_generation_v24917.py r1_15a2_v24917_runtime.py tests/test_v24917_aligned_bounds.py tests/test_v24917_fresh_universal_tdperf.py tests/test_v24917_mobility_guard.py tests/test_v24917_targeted_catchup.py genfix2_audit_tests/test_audit_regressions.py
git diff --check
```

Testy kontrolují průchod produkce/atrakce 0.5, produkce 3 a atrakce 5, odmítnutí 0.499 a hodnot nad 3/5, live readback, strukturální nuly a držení/návrat rodiče mimo pásmo. Startovací testy odmítají starou dolní mez 0.75 v hard/soft obálce a nesoulad runtime/environment produkčního pásma. Pevná SCHOOL/LONG pásma jsou ověřená samostatně.

Úplný implementační diff je v `IMPLEMENTATION.patch.gz.b64`. **LIVE_VISUM_NOT_RUN**: v tomto prostředí se nespouštěl Visum, neprováděly COM zápisy ani změny uživatelova běžícího modelu. Skutečné zlepšení kalibrace s novými mezemi není změřeno. Nový balík má nové SHA a podléhá stávající integritní/certifikační kontrole; není vydáván za živě ověřený.

Kompletní ZIP pro další spuštění:

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/ws-prod3-att5-20261031.zip
