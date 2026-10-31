# TDRECOVERY1: zotavení po zamítnuté Generation a SupplyMix

Baseline je poslední dodaná větev diagnostiky: remote `cc7feee316797c04a4690e38d2fdcff8b71f40e3`, lokální mirror `b9a9199489d046b354ac321e3dee88f542f3577f`, totožný strom `4a785bf80c8997fa08d98bdd89d85c717735d919`. Oprava je v samostatné větvi `codex/td02-recovery-fix-20261031`. Obsahuje i dřívější opravu LONG DIRECTIONAL/DIRECTED; žádná změna nebyla nasazena do živého Visumu.

## Potvrzená návaznost a hranice původní chyby

V dodaném běhu cyklu 2 Generation nepřijala žádný kandidát a SupplyMix má `NO_ACCEPTED_TRIAL`. Uchovaný referenční snapshot má stejné `generation_hash`, `td_hash` a `addval_hash` jako checkpoint B0002. Zdrojová návaznost a kontrolní přehrání formátu skutečného snapshotu 16 nativních kalibrovaných komponent jsou v `LIVE_DATA_LINKAGE.json`. FOREIGN má samostatnou zmrazenou autoritu. Toto přehrání není nové živé čtení.

První chyba v tracebacku nastala již při čtení `visum.Procedures.Operations` v inicializaci TD, před vnitřním hledáním b/c. Obecný handler pak bezpodmínečně vyvolal obnovu všech b/c. Ta skončila při hledání čitelné TD operace. Prázdná složka rollbacku vznikla před touto neúspěšnou obnovou, ještě před zápisem prvního readback auditu.

Shoda b/c sama neprokazuje shodu celého modelu: před TD se může měnit také impedance M9002 a její báze. Proto oprava nezavádí přeskakování celého rollbacku ani převod selhání na úspěšný TD krok.

## Implementace

### 1. Čtecí inicializace TD má explicitní omezený retry

`r1_15a2_combusy2_v24917.py` přidává `install_td_constructor_retry`. Opakovat lze pouze konkrétní chráněný TD09C `_compatible_init`, jehož tělo neprovádí nativní výpočet, COM zápisy parametrů ani OD zápisy. Nestačí zkopírovaný příznak kompatibility: ověřuje se identita funkce. Neznámý konstruktor se automaticky neopakuje.

Používá se stávající `com_call_with_retry`, politika příslušného outer adapteru a existující COMBUSY2 lease. Vypnutý retry se respektuje; netransientní chyby se nepřepočítávají na dočasné. Nová nativní operace nebo assignment se touto obálkou neopakuje. Dočasné odmítnutí zachycené během opakované čtecí inicializace má novou událost `TD_CONSTRUCTOR_READ_RETRY`.

`r1_15a2_td_joint_runtime_v24917.py` provede idempotentní instalaci před voláním vnitřního TD, kdy je již aktuální kompatibilní konstruktor aktivovaný. Tím chrání i první getter `Procedures`, který dříve ležel mimo explicitní retry. Původní chráněný TD09C soubor se nemění.

### 2. Nezměněné b/c se v chybovém rollbacku nezapisují znovu

`r1_15a2_intrazonal_penalty_v24917.py` přidává omezenou kontrolu `_unchanged_failure_td_audit` pro scope `ROLLBACK_AFTER_TD_FAILURE`. Před rozhodnutím provede **nový necachovaný `generation_guard_snapshot()`**. Nestačí uložený předmutovaný snapshot nebo příznak verified.

Musí odpovídat všechny TD řádky i přesné `td_hash` a `operations_hash`. Hashy musí mít platný SHA-256 formát, řádky status OK, unikátní komponenty, úplné požadované pokrytí a konečná číselná b/c bez bool hodnot. Pokud čtení selže, nelze vystavit důkaz nezměněnosti. Pokud se hodnoty nebo procedurální scope liší či důkaz není úplný, použije se původní obnova parametrů.

Pouze při platné shodě se vynechá opakovaný COM zápis b/c. `ROLLBACK_PARAMETER_READBACK.json` pak výslovně obsahuje `write_skipped=true` a `UNCACHED_LIVE_TD_AND_OPERATIONS_MATCH_PARENT`. Zápis tohoto důkazu je kritický a jeho selhání se předá zotavovacímu vlastníku.

**Obnova impedance a intrazonálních penalizací, plný nativní přepočet a následné ověření snapshotu a živých 12D/11D zůstávají zachované.** Integrační test skutečné původní funkce `_rollback_td_all` ověřuje, že se neprovedou b/c zápisy, ale tyto ostatní kroky se vykonají. Nezavádí se LoadVersion, přímý OD zápis ani přijetí neověřeného stavu.

### 3. Ručně obnovitelná chyba ukončí retry

COMBUSY2 dříve mohl v příčinách výjimky nalézt původní RPC odmítnutí a začít dalších až dvacet čtení rodiče, přestože vnější zotavovací vlastník již vyžadoval ruční otevření modelu. Při dlouhých snapshot leasech to mohlo vytvořit zdání zaseknutí.

Obálky bloku i rollbacku nyní před opakováním respektují explicitní `MANUAL_REOPEN`, `MANUAL_RECOVERY_REQUIRED` a `REOPEN_LATEST_ACCEPTED_REQUIRED`. U takové chyby se nepokoušejí znovu číst rodiče ani opakovat blok. Běžná transientní chyba po ověřeném zotavení se dál řídí původní politikou.

Identita nové COMBUSY2 vrstvy: **`R1_15A2_V24917_COMBUSY2_TDRECOVERY1_20261031`**.

## Ověření a reprodukce

Nový soubor `tests/test_v24917_td02_recovery.py` má 23 případů. Používá i skutečný chráněný TD09C konstruktor s COM-shaped fixture a native16 scope. Ověřuje dočasně odmítnutý getter, konečný počet pokusů, vypnutý retry, netransientní chybu, zachování vlastníka Visum instance, neměnné scope/matice a žádné nativní execution během inicializace. Dále ověřuje chybný scope/parametry/hash/status/NaN/bool/duplicity, selhání čtecího důkazu nebo auditního I/O, zachování jiných rollback scope a zastavení při manuální obnově.

- Stejná konečná 23případová sada na původním zdroji v samostatném baseline worktree: **15 selhalo, 8 prošlo**, `baseline_verified_reproductions.log`. To není tvrzení o 15 nezávislých produkčních vadách; více scénářů pokrývá stejné chybějící mechanismy. Osm již platných kontrol se dál zachovává.
- Cílený výběr na opraveném zdroji: **127 prošlo**, návratový kód 0.
- Závěrečná celá hlavní sada: **2335 prošlo, 4 přeskočeny**.
- DIAGFAST: **189 prošlo**; GENFIX2 audit: **18 prošlo**. Všechny závěrečné návratové kódy 0.
- Všech **1059 původních, 177 release a 91 runtime hashů** odpovídá zdrojům. Runtime manifest zachoval všech 91 původních klíčů; změnily se pouze SHA tří upravených runtime modulů a navázaného release manifestu. Přibyl jeden test v release manifestu. Chráněné originály zůstaly byteově shodné.
- Čtyři upravené/přidané Python soubory prošly kompilací; diff a reverzní kontrola implementačního patche prošly.

První úplný běh měl jediné selhání starého testu simulujícího MAX_PATH: zvolený delší `--basetemp=/tmp/r1tdrecovery` vytvořil už samotný cílový název za jeho simulovanou hranicí 260 znaků. Produkční I/O kód se kvůli tomu neměnil. Stejný test prošel se stávajícím krátkým `/tmp/r1longdir`, poté prošly všechny úplné sady. Původní neúspěšný log a CHECKS jsou přiloženy v `first_full/`.

Závěrečné příkazy z kořene zdrojů:

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 /workspace/.venvs/r1/bin/python -m pytest -q -p no:cacheprovider tests/test_v24917_td02_recovery.py tests/test_v24917_combusy2.py tests/test_v24916_td09c_native16_compat.py tests/test_v24917_tdrollbackfix1.py tests/test_v24917_intrazonal_penalty.py
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/r1/bin/python diagfast_tools/refresh_source_manifest.py
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS=--basetemp=/tmp/r1longdir /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/td02_recovery_fix_20261031/verified_release_final
git diff --check
git apply --reverse --check --unidiff-zero artifacts_td02_recovery_fix_20261031/IMPLEMENTATION.patch
```

Runtime manifest byl aktualizován omezeně ve čtyřech schválených SHA položkách; statický seznam staršího kompletního refresh nástroje by neponechal oba fresh launcher záznamy baseline. Přiložený patch obsahuje celé tři zdrojové změny, nový test a oba manifesty. Je vytvořen s nulovým kontextem; pro jeho aplikaci/ověření se používá `--unidiff-zero`. Textové kopie logů mají pouze sjednocené LF a odstraněné koncové mezery; původní SHA jsou v `EVIDENCE_COPY_FORMAT.json`.

## Použití a omezení

Tento komplet používá stejný launcher `01_SPUSTIT_V24917_FRESH_UNIVERSAL_TDPERF_SILENT.py`. Oprava začne platit až při novém spuštění kompletního balíku. Nezasahuje do nynějšího procesu ani neprohlašuje jeho aktuální stav za obnovený. Pro další běh je výchozím bodem ručně otevřený ověřený přijatý checkpoint, nikoli neověřená diagnostická kopie po selhání.

`LIVE_VISUM_NOT_RUN`: testy prokazují konkrétní chování produkčních funkcí nad offline COM-shaped fixtures. Neprokazují živou odezvu pywin32, nepřerušený nativní assignment ani odstranění každé možné COM chyby. Při skutečně neověřeném rodiči je dál povinné zastavení a ruční obnova. Kalibrační meze, cíle, aktivní účely, LONG maska, akceptační a rollback tolerance se nemění. Adaptivní přeřešení targeted Generation podle poškozených profilů není součástí této opravy.
