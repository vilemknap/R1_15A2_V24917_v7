# Nové výsledky běžící kalibrace: cykly 3–5

Zkontrolováno všech 19 přiložených souborů, 74 programových kontrol prošlo. Jde o čtecí rozbor skutečných výsledků; žádný runtime soubor, model, parametr ani právě běžící proces nebyl změněn. Tento audit je uložen nad vývojovou verzí `6794184143df5516708651c1d27b5f57c04b94b8`, ale přílohy nejsou měřením této nové verze. Opravy se do již běžícího procesu samy nepromítají.

## Vývoj výsledků

| Cyklus | Generation: vážené GEH před → po | Přijatý pokus / scale | TD |
| --- | --- | --- | --- |
| 3 | 40,68361 → 38,16097 (−6,20 %) | 2 / 0,286842 | Přijat; aktuální vnější rodič 38,03234 → 37,98602 |
| 4 | 37,98602 → 36,03211 (−5,14 %) | 2 / 0,286842 | Plánovaně přeskočen, NOT_DUE |
| 5 | 36,03211 → 33,39185 (−7,33 %) | 3 / 0,512368 | Plánovaně přeskočen, NOT_DUE |

Od začátku cyklu 3 do konce cyklu 5 kleslo GEH o **17,92 %**. Profilový poměr model/pozorování se posunul z **0,52159 na 0,65269**. Počet profilů s GEH ≥20 klesl ze 187 na 148 a s GEH ≥30 ze 146 na 97. Profilové součty nejsou počtem unikátních cest ani součtem celkové poptávky; dopravní vztah může procházet více profily.

Každý z cyklů přijal Generation in-place, s `solver_converged=true`. Přijaté pokusy mají PASS pro chráněné profily, severity a mobilitu. Odmítnuté větší kroky nebyly pády: důvody jsou `NEW_SEVERE_GEH_PROFILE`, někdy společně s `PROTECTED_PROFILE_GUARD_FAILED`. Například v cyklu 5 měly trialy 1/2 lepší celkové GEH 31,30/32,65, ale neprošly ochranami. Přijat byl menší bezpečný krok na 33,39.

Rozdíl mezi Generation-after 38,16097 a skutečným TD parent 38,03234 není třeba zaměňovat za čistý účinek ladění b/c. TD pracuje s novým nativním přepočtem a vlastním živě vyhodnoceným rodičem. Srovnání TD je 38,03234 → 37,98602; výsledky čtyř různých hranic nejsou jedna neměnná diagnostika.

## SCHOOL skutečně prošla TD kalibrací

Cyklus 3 přijal tři komponentní změny při scale 1:

- WORK_noE_noC: c −2,86927408898 → −2,70686234809;
- SERV_noE_noC: c −1,97721521865 → −1,86529737609;
- **SCHOOL: c −0,59378217414 → −0,52846402113**, b zůstalo 0,0359375.

Dílčí SCHOOL objective kleslo z **0,60441077 na 0,55774545**, zlepšení **7,72 %**. Toto je zdrojový komponentní TD objective, nikoli tvrzení, že stejným procentem kleslo globální GEH nebo samostatná RMSE CDF. Native gap přijatého TD je 0,00134218. Pro tuto změnu je tedy doloženo skutečné přijetí, nikoli jen zapnutý přepínač či přítomnost cíle v seznamu.

LONG_COMPOSITE je také mezi šesti aktivními skupinami a má `READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE`. V tomto TD kroku ale nebyla přijata žádná změna LONG b/c. Jeho aktivaci a nepřijetí návrhu nelze zaměňovat za blokovanou zonální Generation.

## LONG Generation zůstává v tomto běhu zablokovaná

Ve všech třech cyklech má rodičovský LONG guard:

```text
support_clean = true
below_min_km = 0
fine_100_200_rmse = null
fine_cdf_verified = false
long_generation_permitted = false
```

Podpora OSRM ≥80 km je v pořádku; chybí ověřená agregovaná FineCDF metrika. Výsledky tedy stále odpovídají dříve odhalenému problému předávání LONG_COMPOSITE. Jeho oprava je připravená v nové GitHub verzi. Tyto přílohy nedokládají její živé použití ani její selhání. V aktuálních result souhrnech není seznam změn zónových koeficientů, proto z jejich absence neodvozujeme konkrétní počet LONG řádků ani skutečné hodnoty všech zónových ADD koeficientů.

`LONG_SCHOOL_DESIGN_UNVERIFIED` není důkaz, že SCHOOL TD nefunguje. Vnější policy tímto důvodem přepíše `inner.stop_reason`, pokud zůstala nedokončená Generation LONG/SCHOOL. V původním `inner.tdjoint.stop_reason` je skutečný konec solveru `TD_EVALUATION_BUDGET`, s 60 evaluacemi a dvěma dokončenými polly. SCHOOL TD přitom bylo prokazatelně přijato.

## SupplyMix cyklu 4

Dva pokusy skončily zamítnutím:

| Stav | GEH |
| --- | ---: |
| Rodič po Generation 4 | 36,03210725 |
| SupplyMix trial 1, 18 linků | 36,09805984 |
| SupplyMix trial 2, 16 linků | 36,07727884 |

Zhoršil se i sdílený objective; důvody jsou `CAL_GEH_OBJECTIVE_NOT_IMPROVED` a `SHARED_OBJECTIVE_NOT_IMPROVED`. Zápis a zpětné čtení všech 16 změn druhého kandidáta se shodují. Z dodaných dokladů neplyne chyba zápisu SupplyMix.

Závěrečný rollback má `passes=true`, shodný snapshot, ekvivalentní diagnostiku, hlášené přesné fingerprinty matic a **nulový drift 248 profilů**. GEH se vrátilo přesně na 36,03210724894257. Diagnostický hash souhlasí s koncem cyklu 4; přijatá Generation zůstala zachována. Samostatný rollback trialu 1 nebyl přiložen, takže pro něj netvrdíme nezávislé ověření.

## Časování a návaznost

- TD cyklu 3: **4073,549 s = 67 min 53,5 s**, 60 evaluací. Předchozí TD cyklu 2 mělo 28 evaluací a zhruba 40 min. Zvýšený rozpočet je podstatnou součástí vysvětlení delšího TD; není to nové měření právě vyvinutých optimalizací.
- Čítač `procedure_sequence` obsahuje 73 calls / 2680,931 s. Časy jsou inclusive a vnořené; nejde o důkaz 73 samostatných plných TD řetězců ani o 73 samostatných assignmentů.
- SupplyMix 4: **905,3 s = 15 min 5,3 s** bez přijaté změny.
- Dva samostatné 623B TD výsledky jsou byteově totožné kopie **cyklu 5**. Dva malé TD timing soubory jsou také totožné kopie snapshotu s 0,027 s pro přeskočený TD krok. Nejsou to dvě nezávislá provedení ani podklady pro samostatné časy cyklů 4/5.
- Oba podkroky všech tří cyklů mají `generation_completed=true`, `td_completed=true` a `td_realization_complete=true`. Celkový `completed=false`, `search_complete=false`, `joint_stationary=false` se zde pojí s pokračováním hledání, ne s doloženým pádem.
- Hash konce cyklu 3 přesně odpovídá začátku cyklu 4; konec cyklu 4 odpovídá začátku cyklu 5. Samostatný Generation soubor přesně odpovídá Generation 3. Samostatný velký TD soubor přesně odpovídá TD 3. SupplyMix soubor odpovídá vloženému SupplyMix v cyklu 4 po vynechání samotné cesty `folder`.

Za stávajícího plánu EVERY_N=3 a TD během CATCH_UP je další plánovaný TD krok **cyklus 6**. Přílohy nepotvrzují, zda již začal ani kde se právě nachází živý proces. Nedokládají ani fyzické uložení nejnovějšího `.ver` checkpointu; přijímací a rollback tvrzení zde vycházejí z dodaných JSON.

Doporučení: běh nechat pokračovat. Zlepšování je opakované a ochrany odmítají nepřípustné větší kroky. Před dalším spuštěním použít připravenou opravenou verzi; během tohoto běhu nenahrazovat soubory. Žádnou novou změnu kalibrační politiky ani runtime kódu tento rozbor neprovádí.

## Evidence

`SUMMARY.json` obsahuje přesné hodnoty a 74 provedených kontrol. `SOURCE_FILES.json` má názvy, jednoznačné labely, upload ID, byte counts a SHA-256 všech 19 vstupů. `audit_cycles.py.txt` je přesný čtecí skript spouštěný v tomto vývojovém prostředí nad zaznamenanými lokálními cestami; neslouží ke spuštění ve Visumu. Velké původní JSON nejsou do tohoto kompaktního reportu znovu kopírovány; identitu zachycují jejich hashe a potřebné výřezy v SUMMARY. Běžící Visum nebyl připojen ani změněn.
