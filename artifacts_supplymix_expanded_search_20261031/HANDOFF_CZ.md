# SupplyMix: větší kandidát a čtyři pokusy

SupplyMix nově umožňuje společný kandidát až pro **24 profilových skupin a 240 směrovaných hran**, oproti původním 12/120. V jednom bloku má **nejvýše čtyři pokusy**, oproti dvěma. První přijatý pokus se ponechá na místě a blok končí; chybějící legální cesta nebo vyčerpané varianty mohou znamenat méně pokusů.

Uživatel výslovně potvrdil, že „další dva cykly“ znamenají čtyři pokusy uvnitř bloku SupplyMix. Počet vnějších kalibračních cyklů se tím neprodlužuje. SupplyMix dál běží po Generation v cyklech **2, 4, 6…**.

## Výchozí balík a rozsah

- GitHub baseline: `b59e05959c23a72b8b614de8b17cc9cb51a7a5ea`, předchozí balík s většími rozpočty TG/TD a profile prediction auditem.
- Lokální zrcadlo téhož zdrojového stromu: `fc009126ee163fc8d8b5d872400e7db9b81242c2`.
- Výchozí tree: `4e1cf52eaf128351f0bd9d734818e4076b77329c`.
- Nová větev: `codex/supplymix-expanded-search-20261031`.
- Úpravy jsou připravené pro další spuštění. Běžící Visum, jeho soubory, model ani konfigurace na počítači uživatele nebyly měněny.

## Nové nastavení

| Parametr | Před | Nyní |
| --- | ---: | ---: |
| `sp_max_groups` | 12 | **24** |
| `sp_max_edges` | 120 | **240** |
| `sp_max_trials` | 2 | **4** |
| `sp_step_units` | `[8, 4]` | **`[8, 6, 4, 2]`** |
| Stropy změny ADDVAL1 | 4; 2 | **4; 3; 2; 1** |
| Odpovídající sekundy impedance na hraně | 40; 20 | **40; 30; 20; 10** |

Jeden step unit je 0,5 ADDVAL1; 1 ADDVAL1 přidává 10 zobecněných sekund. Všechny čtyři nové stropy jsou celé jednotky ADDVAL1 a fungují s celočíselným atributem Visumu. Přidání stupně 0,5 jako čtvrtého pokusu by v takovém modelu nevytvořilo další legální změnu. Výchozí maximální amplituda zůstává 4 ADDVAL1.

## Implementace a návaznosti

1. `R1_RUN_OPTIONS.json` a výchozí hodnoty v `r1_15a2_demand_policy_v1.py` jsou sjednocené na 24/240/4 a novou sestupnou řadu. `r1_15a2_supply_mix_v24917.options()` používá stejné hodnoty.
2. `r1_15a2_supply_mix_v24917.py` přidá všechny požadované amplitudy do návrhové řady pouze pro aktuální `supply_design()`. Starý zapečetěný základ nemá unit 6, takže samotná změna JSON by přeskočila reálný krok 3 ADDVAL1. Nový krok nyní projde původním mechanismem důkazu skutečných uložených tras, souvislých větví, přípustných ADDVAL1 a path-impact kontroly. Nevzniká pouhým přenásobením starého kandidáta.
3. Návrhový limit kandidátních řádků se odvozuje od počtu úplných stupňů a počtu skupin. S aktivní základní řadou `[16, 8, 4, 2, 1]` doplněnou o 6 se při tomto nastavení zvýší dočasně na **144 řádků**. Počet skutečně použitelných skupin stále závisí na trasách, rozpočtu hran a nepřekryvu.
4. Návrhová konfigurace i policy se obnoví v `finally`, také při chybě návrhu. Původní chráněné konfigurační soubory se neupravují.
5. Pokud menší strop vrátí již vyhodnoceného kandidáta, neproběhne další assignment. Duplicita je zapsaná do `costfix1.trials[].skip_reason` a hledání pokračuje na další menší strop. Dřívější `break` mohl skrýt pozdější platný malý krok. `TRY_04` proto může být druhým skutečným nativním pokusem, pokud dvě mezilehlé škály pouze opakovaly dřívější kandidát.
6. `tools/refresh_v24917_manifests.py` nyní zachovává již existující runtime pokrytí `r1_15a2_fresh_universal_v24917.py` a `01_SPUSTIT_V24917_FRESH_UNIVERSAL_TDPERF_SILENT.py`. Pomocný nástroj je dříve vynechával, ač v dodaném výchozím manifestu byly. Výsledný runtime manifest zachovává stejných **91 jmen**.
7. Oba navázané SHA manifesty jsou aktualizovány po změnách zdrojů.

## Ověření

Přesné výsledky a logy jsou ve `VALIDATION.json` a `checks_verified/`. Byly spuštěny příkazy:

| Kontrola | Výsledek |
| --- | --- |
| Cílené SupplyMix / supply / sequence testy | **113 prošlo** |
| Celá hlavní sada po opravě testu | **2438 prošlo, 4 přeskočeny** |
| DIAGFAST | **189 prošlo** |
| Audit GENFIX2 | **18 prošlo** |
| Chráněný základ | **1059/1059 SHA souhlasí** |
| Release / runtime manifest | **180/180 a 91/91 SHA souhlasí; žádné jméno neubylo** |
| Kompilace a `git diff --check` | **PASS** |

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_supply_mix.py tests/test_v24917_supplymix_completion_isolation.py tests/test_supply_v22.py tests/test_sequence_v23.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/refresh_v24917_manifests.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/supplymix_expanded_search_20261031/checks_verified
PYTHONPYCACHEPREFIX=/workspace/work/supplymix_expanded_search_20261031/pycache /workspace/.venvs/r1/bin/python -m py_compile r1_15a2_supply_mix_v24917.py r1_15a2_demand_policy_v1.py tests/test_v24917_supply_mix.py tools/refresh_v24917_manifests.py
git diff --check
```

Nové regresní případy ověřují dosažení 24 skupin/240 unikátních hran, samostatné uplatnění obou rozpočtů, přijetí až čtvrtého pokusu, ověřený návrat k rodiči po čtyřech zamítnutích, pokračování k menší změně po duplicitě, obnovení dočasného stavu po úspěchu i chybě návrhu a generování kroku 3 ADDVAL1 ze skutečného testovacího path-store.

První cílený běh měl 113 PASS. První celá hlavní sada odhalila chybu nového testu: používal fixture s třídou collector zachovanou před reloadem modulů ve startovacích testech. Test nyní vytváří collector ze stejného aktuálního modulu jako solver; produkční typová kontrola se neměnila. Původní výstup je zachován v `checks_initial/`. Po opravě proběhla celá regrese znovu.

## Zachované smlouvy a praktické limity

Změna rozšiřuje hledání SupplyMix. Ponechává jednu větev na profil, zákaz překryvu hran, cost-safe kontrolu a důkaz uložených tras, nativní cold assignment, čerstvou diagnostiku, první přijetí na místě a stávající ověřený in-memory rollback. Akceptační GEH/IDP/severity limity, jejich reference, penalizace ADDVAL1, absolutní a kumulativní meze ADDVAL1 se touto úpravou nemění. Dřívější vyšší rozpočty TG/TD zůstávají součástí balíku.

Více nativních pokusů může prodloužit blok; runtime ani zlepšení GEH na skutečném modelu nebyly změřeny. **LIVE_VISUM_NOT_RUN**. Nový source/release SHA se musí posuzovat podle stávající integrity a certifikační politiky, nikoli vydávat za již živě ověřený balík.

Úplný diff je uložen v `IMPLEMENTATION.patch.gz.b64` a jeho komprimované i rozbalené SHA jsou uvedené ve `VALIDATION.json`. Kompletní ZIP větve obsahuje zdroje, předchozí dodané změny a novou validační evidenci:

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/supplymix-expanded-search-20261031.zip
