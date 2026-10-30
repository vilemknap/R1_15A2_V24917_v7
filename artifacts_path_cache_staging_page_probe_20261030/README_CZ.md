# Volitelný SQLite staging a kvalifikace COM stránek

Baseline: GitHub commit `a4042f1df6401298e60c404afe5d8956133556e2`, větev
`codex/path-store-build-perf-20261030`, strom
`416085935680c5f0e018d17d10e27248426c18ae`. Lokální ekvivalent baseline je
`dc5c150f169df7fbe7504eb36010a1058327ffc1` se stejným stromem.
Nová pracovní větev: `codex/path-cache-staging-page-probe-20261030`.

## Výsledek a výchozí stav

Oba mechanismy jsou implementované. V dodaném `R1_RUN_OPTIONS.json` jsou
`path_io.fast_staging=false` a `path_io.page_probe=false`.
Dosavadní zrychlení parseru a sdílení map cest zůstává aktivní.
Nový staging je volitelný, protože lokální milionový benchmark nepotvrdil
významné zrychlení pouhým vypnutím synchronních commitů.

Dosavadní FULL durability se platí za transakci, nikoli za každý INSERT.
Geometrie již používá dávky po 5000 cestách; objemy se commitují po DSeg.
Na Windows/síťovém disku mohou mít synchronní commity jinou cenu než zde.

Při V24917 exportu se nyní velikost stránky vždy fixuje před enumerací.
Při vypnutém profilu se použije stávající konfigurovaná velikost. Při zapnutém
profilu vítězná kvalifikovaná velikost. Chyba dlouhého exportu NIKDY nezmění
stránkování. Omezený retry stejných FirstObject/LastObject při transientním COM
odmítnutí zůstává zachovaný. Historické zapečetěné exportery se nepřepisují.

## Jak to spustit

1. **Samostatné read-only COM měření:** v otevřeném Visumu přes
   `Scripts -> Run script file` spusť `R1_BENCHMARK_PATH_EXPORT.py`.
   Výsledek vznikne vedle skriptu v `PATH_EXPORT_BENCHMARK_*/REPORT.json`.
   Skript neprovádí TG, TD, assignment, uložení modelu ani zápisy OD.
   Čte oba režimy a oba typy seznamů, kontroluje 681 zón, 12 DSeg a otisky
   OD matic před/po měření. Výsledek je poradní, nepřenáší oprávnění do další
   assignment epochy nebo jiného Visumu.
2. **Plná kalibrace s oběma novými mechanismy:** spusť
   `01_SPUSTIT_V24917_PATH_IO_PROBE_SILENT.py`.
   Toto JE normální kalibrace s nativními výpočty a změnami modelu. Pouze pro
   dobu volání nastaví `R1_PATH_STORE_FAST_STAGING=1` a
   `R1_PATH_EXPORT_PAGE_PROBE=1`; po skončení/chybě obnoví původní prostředí.
   Profil stránek se znovu změří a ováže ke skutečnému rodiči konkrétního buildu.
3. Běžný `01_SPUSTIT_V24917_TDJOINT1_SILENT.py` používá dodané výchozí volby.
   Samostatně lze zapnout jen jednu funkci příslušnou proměnnou prostředí
   před spuštěním Visumu. Přijímají se `1/0/true/false`.

Konfigurační JSON ani manifesty není potřeba ručně přepisovat. JSON je součástí
SHA manifestu; podporované přepínače prostředí jsou určené pro tyto pokusy.

## SQLite architektura

`r1_15a2_path_cache_publish_v24917.py` zavádí tento postup pro lokální same-run
cache aktivního V24917 adaptéru:

```
.UNPUBLISHED_PATH_CACHE_<uuid>/TWO_MODE_PATH_STORE.sqlite
  sealed constructor + schema + one initial FULL commit
  bulk load: journal_mode=MEMORY, synchronous=OFF
  exact actual volume/key/geometry hashes + SQL profile-flow parity
  completeness + row counts + integrity_check + foreign_key_check
  immutable metadata; DELETE/FULL; close; file fsync; SHA-256
  semantic manifest + fsync; final live parent snapshot check
  atomic directory rename -> PATH_CACHE_<uuid>/
  read back manifest and file identity -> mode=ro&immutable=1
  hand off collector -> retire obsolete payload LAST
```

MEMORY journal zachovává logický rollback při SQL chybě. Obsah pracovní DB
před publikací není autorita. Ošetřená chyba pracovní adresář odstraní; tvrdý
pád procesu může zanechat orphan adresář, který se automaticky nepoužije.
`open_existing()` odmítá nepublikovaný adresář i při přítomnosti původních
značek dokončené enumerace. Publikovaný store vyžaduje platný manifest a SHA;
otevření se žádostí o zapisovatelnou hlavní DB je odmítnuto.

Hlavní DB je read-only, ale TEMP prostor je zapisovatelný v RAM. To je nutné
pro Supply `current_impact`; `query_only=ON` by tuto tabulku zakázalo.
Opětovné otevření také obnovuje klasifikaci CAL/protected/driver, včetně
`cal_indices`, kterou historické otevření samo neinicializovalo.

UNIQUE/PK indexy zůstávají při buildu aktivní, protože definují identitu cest a
objemů. Schéma nemá další sekundární indexy, které by bylo smysluplné odkládat.
Nativní TG/TD, autoritativní matice, LONG/SCHOOL a jejich masky, reference,
akceptace, epochy a rollback modelu se tímto nepřepisují.
Cross-run persistent cache zůstává v aktivní větvi vypnutá. Pokud ji jiný
konfigurovaný klient zapne, používá původní FULL publikační mechanismus.

Na POSIX se flushuje také adresář. Python na Windows nemá ekvivalent tohoto
directory fsync; soubory se flushují a rename je logická publikační hranice.
Tato implementace není živý certifikát odolnosti Windows/SMB proti výpadku
napájení. Ztracená cache se obnovuje enumerací, nemění autoritu checkpointu.

## COM profil

`r1_15a2_path_export_probe_v24917.py` porovnává stejné úseky se samostatnou
referencí čtenou po 256 řádcích. Kandidáti: **256, 2048, 4096, 8192, 16384**.
Používá se dvojice zvolených oken, oba režimy, parent i path-link seznam,
dvě opakování s obráceným pořadím kandidátů. Každý kandidát musí zachovat
počty/obsah, projít na všech čtyřech seznamech, poskytnout skutečně plnou
stránku a dodržet limit Python payloadu. Reference se po testech čte znovu.
Změna živého rodiče/OD autority měření zneplatní.

Report obsahuje rows/s, COM latency, Python page bytes, vzorky RSS hostitele,
chyby a výskyt transientních odmítnutí. Měření nevidí native peak alokací ani
interní retry COM message filteru. Krátký úsek necertifikuje stabilitu všech
22,8 milionu řádků. Neúspěšná kvalifikace velikosti probíhá PŘED exportem;
samotný export potom nemá adaptivní fallback ani unbounded čtení.

## Milionový offline benchmark

180 000 cest na režim, 2,16 milionu objemových řádků, 360 000 geometrických
cest, 3,24 milionu vstupních řádků geometrie. Porovnávají se stejné silné
publikační kontroly pro oba režimy. Jde o syntetická data na lokálním Linux disku.

| Finální ověřovací běh | DELETE/FULL | MEMORY/OFF |
| --- | ---: | ---: |
| Bulk včetně incidence/comparison hash | 33,608 s | 33,625 s |
| Publikace včetně kontrol, fsync a SHA | 8,306 s | 8,404 s |
| Celkem | **41,914 s** | **42,029 s** |

Rozdíl je asi 0,3 % opačným směrem, tedy bez průkazné úspory.
Předchozí dvě opakování dala mediány 41,986 s vs 41,640 s, rovněž rozdíl pod 1 %.
Obsahové/strukturální/objemové hashe i profilová parita jsou shodné.
Starší dvojice běhů je označena jako předchozí měření; finální otevření cache
má navíc ochranu nepublikovaných adresářů a ověřování manifestu při reopen.

Pro zopakování syntetického testu:

```
python benchmarks/run_path_cache_staging_benchmark.py --output RESULT.json --paths-per-mode 180000 --repetitions 2
```

## Benchmark na skutečném store bez nové COM enumerace

Po skončení běhu lze vzít hotový `TWO_MODE_PATH_STORE.sqlite` a spustit:

```
python benchmarks/run_sqlite_path_store_replay.py --source-store "D:\R1_RUN\TWO_MODE_PATH_STORE.sqlite" --work-root "D:\R1_SQLITE_SCRATCH" --output "D:\R1_SQLITE_RESULTS\REPORT.json"
```

Scratch adresář musí existovat; jeho disk je disk, jehož chování se měří.
Nástroj potřebuje jen standardní Python/SQLite. Zdroj otevírá `mode=ro`,
kontroluje SHA před/po a zapisuje pouze do vlastních dočasných kopií. Kopie
mají původní schéma/indexy, po replay se porovnají všechny tabulky, integrity,
FK a SHA. Kopie nikdy nejsou kalibrační autorita a po měření se odstraní.
Kontroluje se místo pro kopii/journal/vacuum. Příprava prázdné kopie není
v časovaném insert testu; `--commit-rows` určuje batching a výsledek není
přímý odhad času celé kalibrace. Skutečný uživatelův store zde nebyl dostupný;
tento vstup byl offline ověřen na malém syntetickém store.

## Ověření a soubory

Závěrečně prošlo **242 cílených testů**, hlavní sada **2155 passed, 4 skipped**,
DIAGFAST **138 passed**, audit GENFIX2 **18 passed**. SHA souhlasí pro
**83/83 runtime**, **161/161 release** a **1059/1059 původních zapečetěných
souborů**. Kompilace změněných zdrojů a `git diff --check` prošly.

Přesné příkazy/návratové kódy a souhrny jsou v `RESULTS.json`, `CHECKS.json`,
`INTEGRITY.json`; plné logy a milionová měření jsou přiložené. `SOURCE.patch`
obsahuje zdrojové změny, nové soubory a manifesty. Předchozí neúspěšné pokusy
jsou zachované v `prior_attempts/`, nejsou vydávané za závěrečné PASS.

Testy pokrývají úplný 12-DSeg export skutečným adaptérem nad fake COM,
poškozené objemy/geometrii/evidenci, chybějící značky, zastavení a selhání
před/po rename, skutečný hard exit subprocessu, read-only + TEMP Supply,
reopen/manifest/SHA, signed zero, odložení smazání staré cache, fixní rozsahy,
retry stejného rozsahu, velikosti nad 4096, limity, kvalifikaci stránek a
read-only replay zdroje. Celá regrese zahrnuje původní kalibrační řetězec.

**LIVE_VISUM_NOT_RUN.** Následující ohraničené ověření je read-only COM profil
ve skutečném Visumu a replay hotového store na skutečném cílovém disku.
