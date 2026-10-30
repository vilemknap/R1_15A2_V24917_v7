# LONG Generation + Distribution – audit návaznosti a opravy

Základ: dokončená SCHOOL revize `37019951b5feff212994610c5934253368c633fa` / lokální strom `91799e46878312a46846d9d5a922230d4418a72b`. Aktuální přepínače LONG TG i LONG_COMPOSITE TD zůstávají zapnuté, TD v režimu DYNAMIC, se společným count/IDP skóre 60/40. Rozsah je LONG řetězec; živý Visum zde není dostupný.

## Nalezené mezery a opravy

1. **Identita matice před čtením a maskováním.** Společný LONG `_read` kontroloval pouze požadovaný klíč ItemByKey, nikoli skutečné `Matrix.NO` vráceného objektu. Nyní NO striktně ověří ještě před GetValues a před jakýmkoli SetValues. Stejný reader používá i LONGGUARD1 při akceptaci Generation. Cizí matice včetně FOREIGN se nemůže vydávat za LONG jen proto, že má správné rozměry.
2. **Skutečně aktuální důkaz LONG.** Readiness ověřuje trvalou vazbu na dokončený assignment, mutation epoch, assignment token, aktuální CL skimy a pořadí zón. Vazba musí odpovídat před celým čtením i po něm; znovu se ověří také fixní OSRM identita. Chybějící/stará vazba nebo změna během čtení nedostane READY. Pravidlo zachovává úmyslné end_candidate chování: dočasné `assignment_completed=false` samo nezneplatňuje již dokončený a stále vázaný assignment.
3. **Navázání dalšího nativního TD pokusu.** Chráněný FineCDF bridge zachytává skimy přímo, nikoli přes běžný refresh vnějšího adaptéru. Wrapper proto po jeho úspěšném LONG vyhodnocení ověří vrácený objekt aktuální skim epochy a publikuje právě dokončenou assignment vazbu. Neúspěšný nebo nedokončený přepočet ji nepřepíše.
4. **LONG Generation je během TD skutečně fixní.** Před i po nativním LONG TD se měří všech pět `FP_3_LONG_*` a `FA_3_LONG`, a při aktivním LONG/SCHOOL zdroji také `ADD_PROD_L` a `ADD_ATT_L`. Zónové identity se kontrolují před i po čtení. Reference se v rámci inner stage nepřesouvá. Jakákoli změna, záporná/nečíselná data či neúplná identita zastaví pokus; nativní výjimky nadále vlastní existující rollback. Bez ověřeného readbacku se LONG stage nesmí publikovat jako platný.
5. **Návrh patří svému b/c rodiči.** Inner stage nyní publikuje kompletní vstupní abc. Před vnější realizací LONG se jeho b/c musí shodovat s aktuálním rodičem. Rozlišuje se správný rozsah: nativní abc má 17 strata včetně chráněné FOREIGN 9116; vnější kalibrační snapshot má 16 mutable komponent. Starý/neúplný plán se odmítne ještě před voláním realizace.
6. **Atomický parametrický plán.** Záporné nové b se nyní odmítne stejně jako neplatné c. Duplicitní rodičovské komponenty a šestý alias stejné LONG matice nesmějí projít kontrolou úplné pětičlenné skupiny. Společné Δb a násobek c, všechny tři škály backtrackingu a společná realizace pěti komponent zůstávají.
7. **Bez opakovaného čtení stejného důkazu.** Při readiness se dříve četlo 11 matic pro kontrolu podpory a dalších 6 znovu pro kontrolu 9291–9295 ↔ 9305. Nyní se každá z 11 LONG matic čte jednou; komponentní součet vzniká průběžně ze stejného čtení. Neudržuje se dalších pět kopií vozidlových matic. OSRM se kvůli konzistenci celého důkazu ověřuje na obou koncích. Nejde o měření času celé kalibrace.

## Zkontrolované návaznosti, které se metodicky nemění

- LONG TG používá sdílenou NATIVE_CL OD→profil incidenci a skutečné aktuální 9291–9295/9305. Frozen geometrie je přiznaný lokální návrh, nikoli analytická derivace TG. Chybějící/paritně nevyhovující zdroj se obnoví jedním běžným refresh pokusem, jinak LONG návrh zůstane odložen.
- Zónové kroky LONG jsou nejvýše ±10 %, produkční reference 0,3 s pásmem 0,15–0,45 a atrakční pásmo 0,5–1,5 × neměnný run-start. Strukturální nuly a neexponované/proměnné mimo povolené domácí zóny jsou nadále omezeny existujícími guardy.
- Pět person matic 9111–9115 je po jednom společném nativním TD násobeno podporou OSRM M9697 ≥80 km bez horní hranice, s přijetím úbytku objemu. Po 20A/20B je stejná podpora vyžadována u 9291–9295 a součtu 9305. Formulová 9305 se pouze čte; její přímý zápis zůstává zakázán.
- LONG TD má jeden původní LONG_COMPOSITE IDP cíl, 512 bodů podmíněně 100–200 km, a jeden společný b offset / c násobek pro pět vrstev. Podpora 80+ a podmíněná FineCDF mají rozdílné vzdálenostní zdroje a nesmějí se zaměňovat.
- Kandidát pořád vyžaduje původní nativní recompute, assignment, nové skimy, 12D/11D a původní akceptaci. Shared-group backtracking a případná izolace zachovávají pět LONG vrstev pohromadě. Při odmítnutí se používá původní in-memory obnova/recompute/ověření; ne přímé vložení OD nebo LoadVersion.

Nové důkazy: `TDJOINT_SUMMARY.json` obsahuje `entry_abc`, `long_generation_freeze` a aktuální `long_composite_live_readiness.assignment_binding`; cílený `TDLONG_COMPOSITE_TARGET_SCOPE.json` přikládá `generation_freeze_readback`.

## Ověření a omezení

- Závěrečně **215 cílených testů**. Hlavní sada **2 064 prošlo, 4 přeskočeny**, DIAGFAST **138**, audit **18**. V nové sadě je 34 regresních případů včetně odmítnutí před mutátorem a korektního přechodu dvou po sobě dokončených assignment epoch.
- `BASELINE_REPRODUCTION.json` potvrzuje na původním kódu přijetí špatného objektu matice, záporného nového b a readiness bez dokončené assignment vazby. Změřeno také **17 → 11 čtení LONG matic** se shodným vozidlovým součtem. `reproduce_baseline.py.txt` potřebuje Git checkout s výchozím commitem a pytest/NumPy; nejde o živý COM test.
- První plná sada odhalila nevhodné použití dočasného candidate flagu místo trvalé dokončené assignment vazby. Oprava zachovala původní platné end_candidate chování; původní selhání a výsledky jsou zachovány v `prior_attempt/`. Závěrečné logy jsou ze stavu po této opravě a po doplnění epoch handoff.
- Všech 1 059 chráněných původních souborů a původní FineCDF zdroj zůstávají bajtově shodné. Oba manifesty jsou aktualizované a jejich položky zachované. Diff, kompilace a zpětné ověření kompletního source patche prošly.

**LIVE_VISUM_NOT_RUN.** Nelze z toho prohlásit celý LONG řetězec za živě bezchybný. Zůstává nutné na skutečném modelu potvrdit vazby ADD_PROD_L → FP_3_LONG_* a ADD_ATT_L → FA_3_LONG a odezvu jedné TG změny i společné TD změny, čerstvé skóre a návrat po odmítnutí. Existující native-response guard (změna M9305), mobility a podpůrné kontroly se nevypínají; source formule se automaticky nepřepisují. Formulové komponenty s nepovolenou krátkou poptávkou nadále vyžadují řešení ve zdroji a neobcházejí se přímým zápisem do FORMULA.

Rozbal celý nový ZIP a použij stejný **`01_SPUSTIT_V24917_TDJOINT1_SILENT.py`**. Přepínače ani launcher se v tomto kroku nemění.
