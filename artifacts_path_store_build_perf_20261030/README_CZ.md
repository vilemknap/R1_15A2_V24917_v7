# SQLite saved-path build: PATH_STORE_BUILD1

Výchozí stav: GitHub `codex/long-chain-review-20261030`, commit
`074fd24eb1dc69ce9073ed7a95b87908a5a1ce7e` (strom
`b79eb9a8644347ebdbd9ce283542e96750d29f08`). Lokální ekvivalent je
`82470787043fcfed9107e92c9366b251590a9c0f` se stejným stromem.
Pracovní větev: `codex/path-store-build-perf-20261030`.

## Úprava

- Nový `r1_15a2_path_store_build_v24917.py` zrychluje přípravu SQLite path-store.
  `r1_15a2_v24917_runtime.install_all()` jej instaluje před kalibrací. Patchuje
  metody existující třídy, takže fungují i aliasy dříve importované adaptéry.
  Historický, zapečetěný `r1_15a2_two_mode_v238.py` zůstává byte-exact.
- Parser oficiální geometrie nealokuje pro každé dítě sedmiprvkové řady další
  řezy, generátory a pomocné n-tice příznaků. Stejné kontroly schématu, ID,
  hierarchie, návaznosti, indexů, existence linek a úplnosti zůstávají aktivní.
  Kontroly násobnosti průchodů a explicitní cesty bez linkových dětí se zachovávají.
- Mapa `(origin, destination, path_index) -> gid` se sdílí pro navazující DSeg
  stejného režimu v jediném collector buildu. Existuje nejvýše jedna taková
  mapa; při změně režimu, chybě, dokončení geometrie a close se uvolňuje.
  Lokální SQL změny a cizí commity invalidují cache přes `total_changes` a
  `PRAGMA data_version`. Jde o soukromou pracovní DB jednoho buildu, nikoli
  podporu souběžného zápisu více autorit nebo nové oprávnění k cross-run reuse.
  Shoda rodičovských klíčů se stále kontroluje přesně, nejen jejich hashem.
- Pro každý DSeg se klíče třídí jednou. Objemové řádky se vkládají v pořadí
  primárního klíče gid. Již ověřený hash stejné množiny klíčů se znovu nepočítá.
- Zápisy zachovávají původní schéma, indexy, foreign keys, `DELETE/FULL`,
  počet cest na commit i omezené COM stránky a jejich retry/fallback protokol.
  Rozpracovaná SQL transakce se při chybě rollbackuje; částečná DB nemá značku
  dokončeného exportu a nelze ji otevřít jako platný persistent store.
- V `TWO_MODE_CACHE_AUDIT.json` a `03A_PATH_EXPORT_SUMMARY.json` přibývá
  `path_store_build`: časy rodičů a geometrie, časy flushů včetně komprese a
  commitu, počty flushů a načtení map. Časy fází zahrnují iteraci COM vstupu;
  nelze je vydávat za izolované časy Pythonu nebo COM.

## Offline měření

Tři opakování se střídáním pořadí původní/optimalizovaný builder, 12 DSeg,
12 000 cest na každý ze dvou režimů, 984 000 řádků geometrie. Směrované
cyklické cesty obsahují opakované linky, objemy zahrnují nulové řádky.

| Fáze, medián | Původní | Nová | Poměr časů |
| --- | ---: | ---: | ---: |
| Rodiče a objemy | 0,824 s | 0,637 s | 1,29× |
| Geometrie | 2,346 s | 1,232 s | 1,90× |
| Celý build včetně incidence | 3,316 s | 2,003 s | 1,66× |

Celkový medián klesl asi o 40 %. SQL načtení map klíčů kleslo ze 16 na 4.
Každé opakování porovnalo obsah všech tabulek, hashe struktury a objemů,
indexově invariantní comparison hash i profilový tok: přesná shoda.
Benchmark nepoužívá Visum ani Windows COM a nezahrnuje jeho čekání ani síťový
disk. Nejde o příslib 1,66× rychlejší celé kalibrace. Původní profiling je
přiložen jako doklad volby úzkého místa; výše uvedené časy jsou bez profileru.

## Ověření

- 185 cílených testů prošlo, včetně 34 nových případů. Kontroluje se skutečná
  instalace launcherem, úplný mock export 12 DSeg, read-only reopen, všechny
  tabulky a hashe proti zapečetěnému builderu, Supply evidence, hierarchické,
  ploché a částečně vyplněné řádky, serializovaná ID, hranice COM stránek,
  násobnosti průchodů, explicitní nulové cesty, chyby a limity, invalidace mapy
  po lokálním i externím SQL zápisu a rollback při vynucené chybě SQL.
- Celá hlavní sada: **2098 passed, 4 skipped**.
- DIAGFAST: **138 passed**. Audit GENFIX2: **18 passed**.
- SHA: **79/79 runtime**, **151/151 release**, **1059/1059 původních autorit**.
- Kompilace změněných Python souborů a `git diff --check` prošly.
- **LIVE_VISUM_NOT_RUN**. Native TG/TD/20A/20B, LONG/SCHOOL, masky, OD zápisy,
  assignment epoch, akceptace ani rollback modelu se touto úpravou nemění.

Příkazy a návratové kódy jsou v `CHECKS.json` a `RESULTS.json`, plné výstupy
v přiložených `.log` souborech. `SOURCE.patch` obsahuje všechny zdrojové úpravy
včetně nových souborů a manifestů.

## Spuštění a další ověření

Použij celý ZIP této větve a běžný `01_SPUSTIT_V24917_TDJOINT1_SILENT.py`.
Optimalizace se instaluje automaticky. Další ohraničené ověření je první
normální živý export: přečíst `path_store_build` a porovnat podíl geometrie,
SQL flushů a čekání na COM na skutečném modelu. Samotnou velikost COM stránek
bez takového měření tato změna nezvyšuje.
