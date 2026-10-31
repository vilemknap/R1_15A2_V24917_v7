# Generation bez CATCH_UP a s jemnými kroky

Uživatel chce zrušit CATCH_UP a používat jemnější kroky. Nový balík nastavuje **REFINE od prvního cyklu a po restartu**, nezávisle na poměru profilového model/pozorování. Nejvyšší P/A změna jednoho plného návrhu je **+5 % / −5 %**, s dalším zmenšením podle aktivního cyklického harmonogramu. Celkové meze koeficientů nejsou velikostí kroku a zůstávají W/S produkce **0,5–3**, atrakce **0,5–5**.

## Skutečné aktivní kroky

| Vnější cykly | Nejvyšší zvýšení P/A | Nejvyšší snížení P/A |
| --- | ---: | ---: |
| 1–4 | **+5,00 %** | **−5,00 %** |
| 5–100 | **+3,05 %** | **−2,96 %** |

Aktivní načtený harmonogram používá log limity 0.1 / 0.06 / 0.03 v cyklech 1–2 / 3–4 / 5–100. Historický základní JSON má jiné hodnoty; skutečná konfigurace je překrývá již před cíleným Generation návrhem. Nový REFINE bere minimum aktivního limitu a log(1.05), respektive −log(0.95). V pozdější fázi tedy platí log ±0.03. Test prochází skutečným `_generation_counts_cfg` až po cyklus 100.

Škála STEP1 0.05–1 násobí návrh v log prostoru; 1.05 při škále 0.5 dává přibližně 1.0247. Skutečná zónová změna může být menší. Šest nativních pokusů je maximum celého bloku, první přijatý zůstává na místě. Při společné změně ADD_SALARY se meze vztahují na výsledný P/A účinek; samotný ADD_ATT může kompenzovat salary faktor.

## Proč bylo potřeba změnit více než přepínač

Původní CATCH_UP se vyhodnocoval při každém návrhu podle poměru profilových součtů s hranicí 0.80. Nebyla to jednorázová inicializační fáze: mohl se vrátit při poklesu poměru nebo novém spuštění. Samotný původní REFINE současně používal `max(stage_limit, refine_limit)`, a tím menší harmonogram přepisoval na +25 % / −20 %. Nově používá omezení shora pomocí `min`.

- `R1_RUN_OPTIONS.json` a `r1_15a2_demand_policy_v1.py`: `tg_catchup_enabled=false`, rovněž při absenci options souboru.
- `r1_15a2_targeted_generation_v24917.py`: REFINE limit log(1.05) a log(0.95), respektování menších aktivních stage caps. Chybějící nepovinný import již nevolí CATCH_UP jako výchozí stav.
- `r1_15a2_fresh_universal_v24917.py`: fresh konfigurace i skutečně nainstalovaná demand policy musí mít CATCH_UP vypnutý. Opětovné zapnutí prostředím `R1_TG_CATCHUP` proto při tomto launcheru skončí explicitní chybou konfigurace, nikoli tichým návratem k velkým krokům. Kontrolují se také jemné refine caps a zachování stage caps; fresh contract je publikuje.
- Dva testové moduly ověřují nízký poměr model/obs, opakované vyhodnocování, restart, environment override, aktivní harmonogram a skutečné změnové koeficienty/P/A efekty.
- Staré explicitní CATCH_UP API zůstává pro kompatibilitu; dodaná konfigurace ani striktní fresh launcher jej neaktivují.
- Oba navázané SHA manifesty jsou obnovené se stejným pokrytím.

## Baseline, zachované části a bezpečnost

Baseline GitHub **e264314a8b5a9a4cfa9695438b6ffce3ca777aeb**, lokální zrcadlo **00d5e0dab295f1887a8987744e71feed597ebbc0**, tree **e09c4b7292db77bdc98fa65eb765cd661a00ba3b**. Větev: `codex/generation-fine-no-catchup-20261101`.

Balík zahrnuje W/S meze 0.5–3 / 0.5–5 a SupplyMix **24 skupin / 240 hran / 4 pokusy**. SCHOOL P/A zůstávají pevné, LONG a ZAHR mají své samostatné celkové obálky. Návrhy LONG při zapojení respektují i menší aktuální stage cap. TD policy/budgets, akceptační GEH/IDP/severity pravidla, nativní assignment, čerstvé skimy a ověřený in-memory rollback se nemění.

Běžící model ani soubory na počítači uživatele nebyly měněny. **LIVE_VISUM_NOT_RUN**: offline testy neprokazují skutečné zrychlení nebo zlepšení kalibrace ve Visumu. Změněné SHA podléhají stávajícím integritním a certifikačním pravidlům.

## Ověření a záloha

Cíleně **132 testů prošlo**. Nové testy kromě čistých limitů ověřují reálný návrh při přehnaném požadavku ±1 log jednotka: plná realizace zůstane na 5 % v C1 a na ±0.03 log v C7. Konfigurace se při tom nemění in-place.

Finální hlavní sada: **2475 prošlo, 4 přeskočeny**; DIAGFAST **189 prošlo**, audit **18 prošlo**. Kompilace změněných Python souborů a `git diff --check` prošly. Všechny SHA odpovídají: chráněný základ **1059**, release **180**, runtime **91** souborů, beze změny pokrytí.

Příkazy a finální logy jsou v `VALIDATION.json` a `checks/`:

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_targeted_catchup.py tests/test_v24917_fresh_universal_tdperf.py tests/test_v24917_aligned_bounds.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/refresh_v24917_manifests.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/generation_fine_no_catchup_20261101/checks_final
git diff --check
```

Úplný diff je v `IMPLEMENTATION.patch.gz.b64`, přesné SHA a výsledky kontrol v `VALIDATION.json`. Kompletní ZIP:

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/generation-fine-no-catchup-20261101.zip
