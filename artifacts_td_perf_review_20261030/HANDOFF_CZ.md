# Revize optimalizací TD: spolehlivost důkazu pro opakovaný restore

**Baseline:** GitHub `3609b4726fadfac6328eab7586fe31fab8037e91` (`codex/td-perf-20261030`), lokální mirror `74f2e559c454e08ee9e565c136b5eaa80ede769f`, totožný strom `1bc3cca828763bfc012c90ad7a31a444e5d9ba3b`. Revize je v samostatné větvi `codex/td-perf-review-20261030`. Zahrnuje všech pět předchozích optimalizací a opravu LONG Generation. Pracovní strom baseline byl čistý.

## Nalezené a opravené mezery

V předchozím `r1_15a2_td_restore_v24917.py` byly tři skupiny nedostatků:

1. **Předčasné publikování důkazu.** Receipt se uložil před zápisem auditu. Když zápis selhal, restore skončil výjimkou, ale ponechal důkaz pro další vynechání výpočtu. Receipt se nyní publikuje jako poslední krok až po úspěšném auditu. Selhání nesmí vytvořit autoritu pro další restore.
2. **Nedostatečná vazba na živé zdroje.** Kontrola porovnávala číselný obsah, ale ne vždy aktuální NO/CODE, DSeg→OD vazby a aktuální procedurální/TD objekty. Identická data v nově přiřazené matici tak mohla projít jako původní stav. Nyní čteme aktuální zdrojová metadata chráněných/utility matic a všech požadovaných vehicle OD. DIS zdroje se znovu objeví přes skutečný živý inventory. Procedury se čtou z aktuální kolekce, nikoli z dříve uložených objektů. Parametry a/b/c se čtou původním přístupovým kódem nad aktuálním `TripDistributionParameters` aktuální TD operace; dočasně se mění pouze Python handle a vždy se obnoví v `finally`. Změna typu/pozice TD či jeho `DSTRATSET` je tvrdá chyba. Kontroluje se také shodný vlastník Visum instance. Nová metadata používají existující omezené COM retry a přísné snapshot čtečky.
3. **Cache Generation nesmí dokazovat nové živé čtení.** Při aktivním `_v24917_generation_reads` se opětovné využití důkazu nepovolí. Původní nativní restore proběhne a v této scope se nevytvoří nový receipt. Tím se odstranila možnost, že nezměněná epocha spolu se starým polem zakryje změnu vehicle OD.

Změněné zdrojové soubory:

- `r1_15a2_td_restore_v24917.py`: uvedené opravy; stav runtime má release `R1_V24917_TD_CONSECUTIVE_RESTORE_PROOF_REVIEW1_20261030`.
- `tests/test_v24917_td_restore_perf.py`: dosavadní offline native seam doplněn o skutečnou COM strukturu metadat (NO/CODE, DSeg vazby, aktuální kolekci operací a TD kořen).
- `tests/test_v24917_td_perf_review.py`: osm nových negativních regresních případů.
- `DIAGFAST_V1_RELEASE_MANIFEST.json`, `V24917_RUNTIME_MANIFEST.json`: odpovídající přesealování přes standardní vývojový nástroj. Žádná kontrola integrity se nevypíná.

Původní nativní restore je dál výchozí cesta. Chybějící či odlišný důkaz nemůže vést k vynechání přepočtu. Skutečné porušení chráněných zdrojů či procedurálních hranic se předává dál transakčnímu vlastníku. Zánik receipt při set_abc/execute, jednorázové spotřebování, numerické tolerance původního rollbacku a samostatná outer acceptance zůstávají zachované.

## Reprodukce a testy

Osm nových scénářů:

| Scénář | Opravené chování |
| --- | --- |
| Selhání zápisu auditu | Výjimka; žádný nový receipt |
| Přesměrování DIS na jiné NO se stejnými hodnotami | Nový nativní výpočet |
| Aktivní cache Generation se zastaralým vehicle OD | Nový nativní výpočet; žádný receipt v této scope |
| Přesměrování DSeg na jinou stejně naplněnou OD matici | Nový nativní výpočet |
| Změna CODE chráněné matice při stejných hodnotách | Nový nativní výpočet, který dál podléhá původním nativním guardům |
| Jiný vlastník Visum instance | Reuse zakázán |
| Živá kolekce obsahuje nahrazenou operaci jiného typu | Tvrdé odmítnutí před spuštěním změněného řetězce |
| Nahrazený TD parametrický objekt se změnou b | Změna není skryta starým COM handle; požadované parametry nelze falešně certifikovat |

V odděleném pytest procesu byl vložen přesný původní modul z baseline commitu. **Všech osm testů na baseline selhalo**, na opraveném kódu prošly. `baseline_final_reproductions.log`, přesný baseline zdroj jako `baseline_restore.py.txt` a původní izolovaný plugin jsou přiloženy. SHA původního modulu je ověřen proti baseline v `RELEASE_INTEGRITY.json`. Plugin je vývojová reprodukce s původními lokálními cestami, nikoli launcher pro Visum; ve vývojovém prostředí se spouštěl s `PYTHONPATH=/workspace/work/td_perf_review_20261030` a `-p baseline_review_plugin`.

- Cílená sada: **146 passed**.
- Závěrečná celá hlavní sada: **2246 passed, 4 skipped**.
- DIAGFAST: **189 passed**; GENFIX2 audit: **18 passed**.
- Všechny závěrečné návratové kódy 0, přesné příkazy a logy v `verified_release/`.
- Během revize dvě nové testovací kontroly narazily na již známou skutečnost, že launcher nahrazuje moduly v `sys.modules`. Testy nyní očekávají výjimku skutečného testovaného vlastníka (`restore.SupplyContractError`), nikoli později znovu importovanou jinou třídu. Produkční ochrana správně odmítala stav již před touto opravou testů. Mezilehlý log je zachován.

Závěrečné příkazy v kořeni zdrojů:

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_td_perf_review.py tests/test_v24917_td_restore_perf.py tests/test_v24917_td_numpy_perf.py tests/test_v24917_tdjoint1.py tests/test_v24917_long_composite_diagnostic.py tests/test_v24916_dynamic_assignment_skims.py --basetemp=/tmp/r1tdreview7
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/refresh_v24917_manifests.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS=--basetemp=/tmp/r1long /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/td_perf_review_20261030/verified_release
git diff --check
git apply --reverse --check artifacts_td_perf_review_20261030/TD_PERF_REVIEW_COMPLETE.patch
```

## Zbytek optimalizací a bezpečnost

Při revizi sond, čtyřmatricového čtení, FineCDF grid scope a blokového hashování nebyla v kontrolovaném kódu/regresích zjištěna další nesrovnalost vyžadující změnu. Jejich zdrojové soubory zůstaly byteově shodné s baseline. Dosavadní přesná numerická parita a benchmark těchto nezměněných kernelů jsou v předchozím `artifacts_td_perf_20261030/`; toto není nové živé měření.

Ověřeno 89/89 runtime hashů, 172/172 release hashů a všech 1059 chráněných originálů. Původní FineCDF bridge, dynamický skim soubor, reference v19, konfigurační možnosti, LONG maska i oprava Generation zůstávají zachované. Tři změněné/přidané Python soubory prošly kompilací, `git diff --check` prošel. Úplný patch zahrnuje i nový test a oba manifesty.

`LIVE_VISUM_NOT_RUN`: žádný COM zápis, zásah do právě běžícího modelu, jeho přerušení, LoadVersion ani merge nebyl proveden. Nové ověřování přidává metadata čtení. Jeho čistý časový přínos proti vynechanému nativnímu přepočtu musí potvrdit živý běh; offline testy jej nevyčíslují. Tyto kontroly nenahrazují samostatnou outer realizaci a čerstvé 12D/11D přijetí.

Další omezený krok: při příštím spuštění kompletní revidované verze ověřit runtime `td_restore.release` s `REVIEW1` a porovnat `TD_PERF_RESTORE_AUDIT.json` s TD timingem. Soubory právě běžícího procesu nenahrazovat. GitHub větev je oddělená vývojová záloha a nebyla sloučena do běžící větve.
