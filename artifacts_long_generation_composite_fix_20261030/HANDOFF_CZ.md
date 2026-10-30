# LONG Generation: oprava blokované kompozitní diagnostiky + kontrola SupplyMix

**Zadání:** opravit blokování zonální LONG Generation a prověřit dokončený SupplyMix cyklu 2. Vývoj a ověření jsou offline; `LIVE_VISUM_NOT_RUN`.

**Výchozí verze:** uživatelem zvolená větev `codex/v24917-tdlong-school-epochfix-20261030`, commit `25594238f24451191bf6535fa3a4c9865f8fc979`, strom `c215ba6e98243deee9ff598d42e2fac965f84f98`. Lokální zrcadlo `1cb5eac4132a4f222b42ede2f3b2662dd8ce3b9d` má totožný strom. Výsledná samostatná větev: `codex/long-generation-composite-fix-20261030`. Tento krok nepřebírá samostatné návrhy optimalizace TD ani nepovinné SQLite staging/page-probe úpravy z jiných větví.

## Příčina a oprava

Z nahraného přijatého Generation návrhu je 3 454 řádků, žádný `ADD_PROD_L` ani `ADD_ATT_L`. `LONGGUARD1_PARENT` potvrzuje čistou podporu OSRM, ale `fine_cdf_verified=false`, RMSE `null` a `long_generation_permitted=false`. Zapnutí LONG v konfiguraci nestačí: inherited dynamická 11D aktualizuje pouze existující atomické řádky. `LONG_COMPOSITE` mezi 17 atomickými komponentami není, ačkoli jej `DynamicFamilyMetrics` vypočítá. Původní brána jej hledá právě v těchto řádcích.

- Nový `r1_15a2_long_composite_diagnostic_v24917.py` vymezuje samostatný ověřitelný kompozitní záznam.
- `r1_15a2_dynamic_11d_files_v24917.py` přebírá již spočtenou metriku pro 9111–9115 a publikuje ji pod `long_composite_dynamic` v dynamickém summary i samostatně v `DYNAMIC_LONG_COMPOSITE.json`. Původních 17 řádků/CSV zůstává zachováno.
- `r1_15a2_long_distance_guard_v24917.py` váže metriku na aktuální assignment/skim, NATIVE_CL, zóny, přesnou referenci a 512bodový cíl 100–200 km. Pomocí pěti již načtených polí ji ověří čistým NumPy přepočtem jednoho cíle. Nečte kvůli tomu další OD matice přes COM. Chybějící/neshodné údaje LONG dál odloží s konkrétním důvodem.
- `r1_15a2_parent_equivalence_v24917.py` nejprve záznam ověří, teprve pak porovnává obsah při nové assignment epoše rollbacku. Normalizuje pouze čtyři známé execution identifikátory; číselné výsledky, reference a obsahové hashe dál kontroluje.
- Doplněny regresní testy a explicitní runtime manifest. Existující testy s neověřenými syntetickými LONG řádky nyní používají skutečnou referenci a kompletní vazbu na epochu.

`BASELINE_REPRODUCTION.json` reprodukuje problém původním modulem nad stejnými offline vstupy: původní `long_generation_permitted=false`, opravené `true`. Integrační test navíc provádí skutečný zděděný overlay; další test propojuje důkaz, sdílenou NATIVE_CL SQLite incidenci a skutečný zonální solver a získá nenulové LONG koeficientní kroky. Chybné stáří, reference, matice, metrika či OSRM podpora se odmítají.

## Dokončený SupplyMix cyklu 2

`SUPPLYMIX_BLOCK_RESULT`: `NO_ACCEPTED_TRIAL`, `search_complete=true`, `stationarity_confirmed=false`, 924,7 s. Oba návrhy byly řádně zamítnuty:

| Stav | Vážené GEH | Sdílené skóre |
| --- | ---: | ---: |
| Přijatý rodič po Generation | 41,63552485193917 | 0,8087943788053094 |
| SupplyMix trial 1, 22 linků | 41,70741983161766 | 0,8126159807608526 |
| SupplyMix trial 2, 21 linků | 41,78569383621272 | 0,812536498999741 |

Důvody jsou `CAL_GEH_OBJECTIVE_NOT_IMPROVED` a `SHARED_OBJECTIVE_NOT_IMPROVED`. Lokální zlepšení pěti driver profilů nestačí při zhoršení celkového cíle. U druhého kandidáta je programově ověřena shoda všech 21 zápisů se zpětným čtením. Dodaný závěrečný rollback má `passes=true`, shodný snapshot, ekvivalentní diagnostiku, přesné fingerprinty matic a nulový drift všech 248 profilů. GEH se vrátilo přesně na 41,63552485193917. Použitý režim `FULL_12D_11D_FALLBACK` je úspěšné plné ověření; neúspěšná možnost diagnostického reuse sama neznamená neúspěšný rollback. Není doložen samostatný soubor rollbacku trial 1.

Přijatá Generation zůstává zachována. V těchto podkladech není důkaz chyby SupplyMix; jeho produkční kód nebyl změněn. Řídicí kód po návratu Generation/SupplyMix pokračuje TD, ale nahrané soubory samy nepotvrzují zahájení TD cyklu 2.

## Ověření a integrita

- Cílené testy: **170 passed** (`targeted_final.log`).
- Celá hlavní sada: **2184 passed, 4 skipped**; DIAGFAST **189 passed**; audit **18 passed**. Přesné příkazy, návratové kódy a logy jsou v `verified_release/`.
- `UPLOADED_CYCLE_2_AUDIT.json`: úspěšné programové kontroly skutečných nahraných výsledků, včetně SHA-256 vstupních souborů. Zdroj auditního skriptu je uložen jako `.py.txt`; očekává původní přiložené soubory v uvedených lokálních cestách.
- `RELEASE_INTEGRITY.json`: 87 runtime souborů, 166 release souborů, správné hashe; všech 1059 chráněných originálů a přesná FineCDF reference zachovány. Standardní refresh navíc doplnil do release manifestu pět již existujících souborů baseline, aniž by je měnil. Konfigurace i SupplyMix zůstaly byteově shodné s baseline.
- První širší běh eviduje dvě testovací potíže (`initial_checks/`): nevhodná délka pytest dočasné cesty pro simulaci MAX_PATH a nový test patchující původní module instance po launcher reloadu. Běh používá vhodnou délku `--basetemp=/tmp/r1long`, nový test patchuje aktuální module instance. Původní I/O kód nebyl změněn.
- Syntaxe osmi změněných/přidaných Python souborů a `git diff --check` prošly. Úplný patch obsahuje nové soubory i oba manifesty.

## Živé hranice a další krok

Oprava odstraňuje prokázanou diagnostickou překážku. Nezaručuje přijetí každého LONG návrhu. Aktuální path incidence, profilová parita, dostupná mobilitní autorita/vazby `ADD_PROD_L` → `FP_3_LONG_*`, `ADD_ATT_L` → `FA_3_LONG`, reference a živé akceptační kontroly musí stále projít. Tyto skutečnosti v živém Visumu zde nebyly ověřeny. OSRM >=80 km nemá horní mez; podmíněný FineCDF 100–200 km ji nezavádí. Limity kroků, mobility, podpory, přijetí, maskování a rollbacku se neuvolňují. Žádný COM zápis, `LoadVersion`, změna modelu ani zásah do běžícího procesu nebyl proveden.

Další omezený krok je při příštím spuštění kompletní opravené verze z ověřeného stavu zkontrolovat `LONGGUARD1_PARENT.json` (`fine_cdf_verified`, `long_generation_permitted`) a LONG řádky/`long_deferred_reason` v návrhu Generation. Během stávajícího běhu soubory nenahrazovat. GitHub větev je vývojová záloha; nebyla sloučena do běžící větve.

Příkazy ověření v kořeni zdrojů (návratové kódy všech závěrečných kontrol 0):

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_long_composite_diagnostic.py tests/test_v24917_longguard1.py tests/test_v24917_long_osrm_support.py tests/test_v24917_read_reuse.py tests/test_v24917_tdrollbackfix1.py tests/test_v24917_supplymix_completion_isolation.py --basetemp=/tmp/r1longdiag3
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/refresh_v24917_manifests.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS=--basetemp=/tmp/r1long /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/long_generation_composite_fix_20261030/verified_release
git diff --check
git apply --reverse --check artifacts_long_generation_composite_fix_20261030/LONG_GENERATION_COMPOSITE_FIX.patch
```
