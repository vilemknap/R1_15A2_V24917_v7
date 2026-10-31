# Schválené uvolnění GEH: SEVRELAX3, 2026-10-31

Základ: vzdálený commit `b1db2b2049e43024f6b3b74272dd7eae6f2f7dc4`, lokální shodný tree v commitu `82640a1d328283fdbe346c4d39228d3635ae9350`. Větev `codex/geh-relaxation-20261031`. Obsahuje předchozí nový zónový refit i opravy LONG a TD02 recovery.

Uživatel výslovně požádal o uvolnění chráněných profilů, severity a obecných GEH mezí. Potvrdil variantu: chráněné profily pod GEH40, obecný skok +50 a při výsledném GEH nad 60 skok +30. Rozpočty jednotlivých bloků byly před implementací uvedeny v komentáři. Tato metodická změna je schválená; žádná ochrana se nevypíná kvůli získání zelených testů.

## Nová výchozí politika

| Kontrola | Dosud | Nově |
| --- | ---: | ---: |
| Profil s rodičovským GEH < 5: výstup musí být pod | 20 | 40 |
| Maximální zvýšení GEH jednoho profilu | 25 | 50 |
| Maximální zvýšení profilu, jehož výsledné GEH je >60 | 15 | 30 |
| Generation: relativní zhoršení severity20 | 8 % | 20 % |
| Generation: relativní zhoršení severity30 | 10 % | 25 % |
| Generation: čistý přírůstek počtu profilů GEH ≥40 | 5 | 10 |
| TD: relativní zhoršení severity20 | 25 % | 40 % |
| TD: relativní zhoršení severity30 | 30 % | 50 % |
| TD: čistý přírůstek počtu profilů GEH ≥40 | 15 | 25 |
| SupplyMix: relativní zhoršení severity20 | 20 % | 35 % |
| SupplyMix: relativní zhoršení severity30 | 25 % | 45 % |
| SupplyMix: čistý přírůstek počtu profilů GEH ≥40 | 20 | 30 |

Hodnoty jsou vůči aktuálnímu rodiči jednotlivého pokusu, nikoli začátku běhu. Při opakovaném přijetí se proto lokální zhoršení může kumulovat. Severity20/30 jsou původní vážené spojité penalizace, nikoli procenta průměrného GEH. Jejich definice a diagnostické prahy 20/30/40/60 se nemění. Při nulové rodičovské severity zůstává původní zacházení s první kladnou severity; nebyla přidána nová normalizační konstanta. Pro již vysoké profily nad GEH60 platí samostatný limit +30 i při obecném limitu +50. Výstup chráněného profilu s GEH ≥40 stále znamená zamítnutí (nulový rozpočet katastrofických chráněných profilů zůstává).

## Implementace a návaznost

- `R1_RUN_OPTIONS.json`: nové schválené výchozí hodnoty a objekt `sev_scope_budgets` pro generation/td/supply.
- `r1_15a2_demand_policy_v1.py`: shodné defaults, přísná validace vnořených rozpočtů a volitelný JSON override přes `R1_SEV_SCOPE_BUDGETS`. Částečné override doplní výchozí hodnoty ostatních polí. Neznámé klíče/scopes, null, NaN, inf, záporné hodnoty, necelé počty nebo vadný JSON vyvolají chybu. Relativní hodnoty mají rozsah 0..3.0, počty 0..5000. Vnořené defaults se nekopírují sdíleně a nemutují se.
- `r1_15a2_severity_relax_v24917.py`: SEVRELAX3 zvyšuje rozpočty v kopiích akceptační konfigurace přes `max(původní, požadované)`. Vyšší explicitní původní rozpočet nesnižuje. Nevytváří chybějící/vypnutou akceptační politiku. Existující záznam `aggressive_tuning.v24917_severity_relax` zachycuje změny; runtime status a startup log uvádějí nové rozpočty.
- `tests/test_v24917_geh_relaxation.py`: 45 nových regresních případů přes skutečné core brány a produkční config builders.
- `tests/test_v24917_rbcons_audit.py`: aktualizace jedné kontroly schváleného defaultu z 0 na 40. Historické testy explicitní volby 0 zůstávají zachovány.
- Oba SHA manifesty aktualizovány; počet 91 runtime položek zachován.

Stávající wrappery `_generation_counts_cfg` a `_td_acceptance_cfg_for_cycle` předávají novou politiku do scope adaptéru. Generation STEP1 predikční brána i konečný core gate tak používají stejnou konfiguraci. SupplyMix používá generation builder pro kopii konfigurace, ale vybírá samostatnou SUPPLY politiku se svými rozpočty. TD má vlastní scope a nadále aplikuje kombinované skóre. Integrační testy ověřují cykly 1, 13 a 100, tedy i pokračování po původním 12. cyklu. Původní prodloužení demand horizontu zůstává zapnuté; nemění se tím historická neaktivní legacy politika mimo nakonfigurovaný běh.

Akceptační cíle, původní povolený Generation severity tradeoff, váhy TD 60/40, F≤0.999, IDP limit 1.25, měření skutečných intenzit, observation authority, mobility, LONG podpora ≥80 km, stavové a assignment kontroly a rollback nebyly měněny. Původní chráněný core ani jiný z 1059 chráněných zdrojů nebyl upraven.

## Přehodnocení skutečného uloženého Generation2 pokusu

Poslední skutečný menší pokus (`GENERATION_PREVIEW_0_115395`) měl pouze důvody `NEW_SEVERE_GEH_PROFILE` a `PROTECTED_PROFILE_GUARD_FAILED`. Celková severity20 se přitom zlepšila z 782.2147 na 750.9350 a severity30 z 535.7126 na 512.6599. Profil 920023 měl GEH 1.522286 → 37.393888: původní chráněný limit 20 a obecný skok 25 jej blokovaly.

Čtecí replay uložených GEH důkazů nově vrací:

- protected PASS;
- severity PASS;
- po odstranění přepočtených GEH důvodů nezůstávají ve starém záznamu jiné důvody zamítnutí.

**Není to nové přijetí kandidáta, aktuální native assignment, ověření rollbacku ani autorizace uložit checkpoint.** Žádný model nebyl otevřen. Replay používá kompletní původní GEH sekce a statistiky, zachovává ostatní uložené důvody a pro nové vyšší limity filtruje úplné původní seznamy překročení. Ověřuje, že limit pouze roste a prahová hodnota pro vysoké GEH se nezměnila; jinak odmítne neúplné důkazy. Nepoužívá neexistující jednotlivé OD ani nevymýšlí nové nativní výsledky.

Všechny použité GEH sekce jsou v `INPUT_STORED_GENERATION2_GEH.json` včetně SHA původního uživatelského ACCEPTANCE.json; výsledek v `STORED_GENERATION2_GEH_REPLAY.json`. Reprodukce z kořene balíku:

```text
python artifacts_geh_relaxation_20261031/replay_stored_geh.py.txt artifacts_geh_relaxation_20261031/INPUT_STORED_GENERATION2_GEH.json replay.json
```

## Ověření

- Původní commit se stejnými novými testy: 37 FAIL, 8 PASS. Jde o rozdíly proti nově schválené politice a validaci, nikoli 37 nezávislých chyb staré produkce.
- Cílená finální regrese: 203 PASS, 1 SKIPPED.
- Hlavní finální sada: 2404 PASS, 4 SKIPPED.
- DIAGFAST: 189 PASS.
- Audit GENFIX2: 18 PASS.
- Kompilace čtyř změněných/přidaných Python souborů prošla.
- SHA: chráněných 1059/1059 beze změny; release 179/179 a runtime 91/91 souhlasí. Příslušné source identity byly vědomě změněny; ověření identity ani live certifikační kontrola nebyly vypnuty.
- `git diff --check` a kontrola aplikace kompletního patche prošly.
- `LIVE_VISUM_NOT_RUN`; skutečná kvalita a přijetí nových návrhů nejsou živě ověřené.

První rozšířený běh během vývoje zachytil moji chybu v nové validaci: `_validate_iz` měl lokální proměnnou `raw` obsahující seznam fa_blocks a nové volání `raw.get` vyvolalo AttributeError. Opravil jsem použití normalizovaného `out` a explicitní zacházení s null v `validate`. Následně byly znovu spuštěny všechny celé sady a prošly. Původní neúspěšné logy jsou zachovány jako `initial_*.log.gz.b64`, původní SHA a velikosti v `INITIAL_FAILURE_LOGS.json`, status v `INITIAL_FAILED_CHECKS.json`. Lze je obnovit přes base64 decode a gzip decompress. Finální počty a přehled jsou v `TEST_TOTALS.json`.

Příkaz finálních sad:

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 PYTEST_ADDOPTS='--basetemp=/tmp/r1longdir' /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/geh_relaxation_20261031/checks_final --timeout 600
```

Přesné příkazy jednotlivých sad a exit codes: `CHECKS.json`. Kompilace použila `py_compile.compile(..., cfile='/tmp/r1_geh_compile_N.pyc', doraise=True)`. Kompletní `IMPLEMENTATION.patch` zahrnuje testy i manifesty a používá nulový kontext: `git apply --unidiff-zero IMPLEMENTATION.patch` pouze na uvedený základ. GitHub ZIP změny již obsahuje.

Při příštím samostatném spuštění zkontrolovat startup `V24917 SEVRELAX3` a v prvním `ACCEPTANCE.json` skutečné hodnoty `protected_guard`, `severity_transition_guard.v24912_policy` a případné další důvody zamítnutí. Běžícímu procesu nebyly vyměňovány moduly ani konfigurace.
