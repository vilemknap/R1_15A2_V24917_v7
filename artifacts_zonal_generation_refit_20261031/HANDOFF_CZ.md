# Zónová Generation: audit shluků a nový směr po odmítnutí

Výchozí vzdálený commit: `dd175ee07af1ae328789df92f87afb26fea53b84`, lokální zrcadlo `df1c186e4be985b99b4cfcc0c6efe6f2a8128197`. Samostatná větev `codex/zonal-generation-refit-20261031`. Obsahuje také předchozí opravy LONG směrové autority a TD02 recovery. Do běžícího Visumu nebylo zasahováno.

## Co prokázal skutečný export

Soubor `ZONE-2026-10-31-03-39-29.xlsx` obsahuje 681 zón. Všech 2724 hodnot čtyř W/S koeficientů odpovídá uchovanému přijatému rodiči v `GENFIX2_PARENT_PROOF_RETAINED.json` při toleranci abs/rel 1e-12. Nejde o zbytek odmítnutého Generation2 pokusu.

| Koeficient | Změněných zón v přijatém Gen1 | Různých hodnot před → po, při zaokrouhlení na 10 míst |
| --- | ---: | ---: |
| ADD_PROD_W | 638 | 39 → 46 |
| ADD_ATT_W | 494 | 72 → 93 |
| ADD_PROD_S | 638 | 31 → 45 |
| ADD_ATT_S | 463 | 33 → 45 |

Velké shluky byly už před Gen1: 343 zón mělo WORK produkci 2; 414 zón SERVICE produkci přibližně 2. Po Gen1 je 324 zón přesně na WORK produkci 2.0757549144184662. SERVICE má při 10 desetinných místech 391 zón na 2.0762705397. Export má skutečně i jiné samostatné hodnoty; zónový fit běžel. Jeho velké skupiny saturují společné meze a stejná přijatá škála na stejném vstupu dává stejný výstup. Není důvod přidávat náhodné rozdíly.

LONG zůstává ve všech zónách 0.3 / 1; oprava jeho směrové autority již byla provedena v předchozím commitu. SCHOOL ADD koeficienty mají zůstat 1: aktivní původní AMDY vzorce je nepoužívají. Nová úprava je sama nezmění.

Reprodukce auditu bez openpyxl nebo Visumu:

```text
python audit_zone_export.py.txt --workbook ZONE-2026-10-31-03-39-29.xlsx --preview GENERATION_PREVIEW_0_181579.json --parent GENFIX2_PARENT_PROOF_RETAINED.json --output audit
```

SHA vstupů, přesné a zaokrouhlené četnosti jsou v `ZONE_EXPORT_AUDIT.json`. CSV `ZONE_BEFORE_AFTER.csv` zachovává hodnoty všech 681 zón před a po Gen1 včetně názvu a domácího příznaku. Žádné hodnoty v modelu nebyly resetovány.

## Co se změnilo v hledání

Dosavadní STEP1 vypočítal zónový směr jednou a po nativním odmítnutí jen zmenšoval jeho společnou škálu. Naměřenou chybu používal ke změně předpovědi intenzit, nikoli k novému zónovému řešení. V dodaném Generation2 tak tři škály stejného směru znovu poškodily chráněné profily.

Po prvním kompletně změřeném a odmítnutém pokusu nyní může **jednou za blok** proběhnout čistě NumPy přepočet směru W/S a společných hraničních P/A aktuátorů. Původní rodič, jeho incidence, vstupní koeficienty a reference zůstávají zachovány. Používá se skutečný implementovaný log efekt po salary splitu, ořezu a P/A úpravách.

Lokální operátor se opraví minimální sekantovou aktualizací:

`G_new = G + (delta_measured - G @ x_actual) outer x_actual / (x_actual @ x_actual)`.

Nové řešení tak může vybrat jiné zóny, jiná znaménka a různé velikosti kroků. Jeho box je nejvýše polovinou původního rozsahu, konkrétně `0.5 * measured_scale` původních dolních/horních log mezí. Zůstává původní ridge, cíle, P/A vyrovnání i jednotlivé koeficientové meze. Znovu se aplikují FlowBundle maska a oba mobility guards; konečný preview a nativní akceptace zůstávají autoritou.

Při změně směru se zahodí stará škálová sekanta a preview cache. Nová predikce používá nový operátor. Další zamítnutí může využít změřenou sekantu tohoto nového směru. Všechny směry sdílejí původní rozpočet nejvýše tří skutečných pokusů; přepočet fitu sám nevolá COM ani assignment. Přijatý kandidát se adoptuje na místě dosavadní cestou. Recovery drží sjednocení změněných parametrů obou směrů až do přijetí nebo ověřeného úplného rollbacku.

Změněné produkční soubory:

- `r1_15a2_zonal_count_fit_v24917.py`: čistá, nemutující sekantová oprava operátoru a menší trust box.
- `r1_15a2_trial_adapter_v24917.py`: mapování skutečných efektů, validace profilové/rodičovské autority, nový zonální fit a opětovné ochrany.
- `r1_15a2_step_search_v24917.py`: jeden volitelný přepočet směru uvnitř stávajícího trial/accept/reject/rollback řetězce.
- `tests/test_v24917_measured_zonal_refit.py`: 24 nových testů numeriky, identity dat a skutečné orchestrace.
- Oba SHA manifesty: změněné identity; všech 91 runtime položek bylo zachováno.

## Hranice platnosti

Sekantová aktualizace odpovídá jednomu naměřenému směru. **Není identifikovaným nativním zónovým Jacobianem ani důkazem, že nový směr zlepší model.** Ten musí projít čerstvým nativním TG→TD→20A/20B→assignment a původní 12D/11D akceptací. Ochrany profilů, IDP, LONG masky, mobility, reference, TD a rollback nebyly uvolněny.

Při nenulových současných LONG/SCHOOL aktuátorech se tento W/S přepočet odloží s `DEFERRED_MIXED_LONG_SCHOOL_ACTUATORS`: jednu společnou naměřenou odezvu nelze přiřadit samotnému W/S operátoru. Nezmění se tím aktivace LONG; pokračuje dosavadní společné škálové hledání. Při chybějících datech, neshodě pozorování, nekonvergenci nebo neproveditelném fitu se důvod zapíše a rovněž pokračuje dosavadní sekantové hledání. Nejde o fallback akceptačních pravidel.

247 profilů pro 2604 zónových proměnných navíc samo o sobě neurčuje jedinečné jednotlivé koeficienty. Test proto výslovně ověřuje, že zóny se shodnou incidencí mohou nadále mít shodné kroky. Tato změna nezaručuje odstranění všech shluků; odstraňuje omezení na jeden neměnný zónový směr.

## Offline důkazy

- Stejných 24 nových testů na původním commitu: 24 FAIL, protože nový mechanismus neexistuje; nejde o 24 nezávislých nalezených chyb.
- Cílená regrese: 278 PASS.
- Hlavní sada: 2359 PASS, 4 SKIPPED.
- DIAGFAST: 189 PASS.
- Audit GENFIX2: 18 PASS.
- Závěrečná kontrola nových testů a runtime instalace: 33 PASS po odstranění prázdného koncového řádku testu a novém zapečetění jeho SHA.
- 1059 chráněných souborů beze změny, 178 release SHA a 91 runtime SHA souhlasí. Kompilace čtyř změněných/přidaných Python souborů prošla.
- Test se skutečným adaptérem probíhá bez objektu Visumu. Integrační test ověřuje nový zónový směr, zachování rodiče, původní trial budget, nemožnost obejít nativní odmítnutí i úplné obnovení po chybě druhého směru.
- `LIVE_VISUM_NOT_RUN`; žádné živé měření zrychlení ani kvality nového řešení nebylo provedeno.

Příkaz úplných sad:

```text
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 PYTEST_ADDOPTS='--basetemp=/tmp/r1longdir' /workspace/.venvs/r1/bin/python tools/run_genfix2_checks.py --output /workspace/work/zonal_generation_refit_20261031/checks --timeout 600
```

Přesné příkazy jednotlivých sad a exit codes jsou v `CHECKS.json`, logy ve stejném adresáři. `IMPLEMENTATION.patch` zahrnuje nový test i oba manifesty; kvůli nulovému kontextu použít `git apply --unidiff-zero IMPLEMENTATION.patch`. Výchozí tree musí odpovídat uvedenému commitu. Kompletní větev/ZIP již obsahuje aplikované změny.

Při příštím samostatně spuštěném běhu ověřit `MEASURED_ZONAL_REFIT.json`, `STEP1_PLAN_02.json` s režimem `MEASURED_ZONAL_REFIT`, skutečné zónové řádky druhého pokusu a jeho `ACCEPTANCE.json`. Probíhajícímu procesu nelze bezpečně vyměňovat načtené moduly; tento balík je určen pro další spuštění.
