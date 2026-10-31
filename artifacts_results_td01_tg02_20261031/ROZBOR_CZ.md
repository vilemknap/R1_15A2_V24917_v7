# Výsledky: TD cyklu 1 a Generation cyklu 2

Čtecí audit 16 nově dodaných JSON souborů, 2026-10-31. Všech **66 kontrol návaznosti prošlo**. `ACCEPTANCE.json` a `ACCEPTANCE - kopie.json` jsou byteově shodné; jde tedy o 15 unikátních obsahů. Původní názvy, upload ID, velikosti a SHA jsou v `SUMMARY.json`.

Tato samostatná větev `codex/results-td01-tg02-20261031` ukládá pouze rozbor a ověření. Je odvozena z poslední dodané opravy LONG směrové autority `67e6ab5540c15c56e0f5ed5f0f3152e8b397f4cf` (lokální mirror `e5591122c29116b35ad0f9ef028bd6987c2826a2`, strom `60d897baca9fadd56f4494a9f835206b0296348f`). To neprokazuje nasazení této opravy v procesu, ze kterého pocházejí nové výsledky; k přílohám není přiložen aktuální runtime manifest ani commit běžícího balíku.

## Skutečné pořadí kroků

1. `TD_FINECDF_BLOCK_RESULT.json` zachycuje **TD cyklu 1**, `ACCEPTED_FINECDF_TD`.
2. `GENERATION_BLOCK_RESULT.json` zachycuje **Generation cyklu 2**, `CONFIGURED_GENERATION_SEARCH_EXHAUSTED`.
3. Generation zamítla všechny tři kandidáty a rollback obnovil stav přijatý po TD. Diagnostic hash rollbacku je přesně `103d532f7cd16472333c0bc4d45860e7eceebdea6845e7ddcb5323424375c7f5`, shodný s přijatým TD. Rodičovské GEH následující Generation se shoduje s GEH přijatého TD.

Pořadí potvrzují i čítače: TD snapshot obsahuje jeden Generation design; pozdější Generation snapshot dva. Oba mají totožný kumulativní záznam jediného TD kroku. Nelze tedy tvrdit, že po nyní zamítnuté Generation už následovalo další TD.

## TD: skutečně přijata pouze komponenta SERVICE

Vnitřní solver navrhl WORK_noE_noC a SERV_noE_noC. Společná realizace byla zamítnuta na škálách 1; 0,5; 0,25 kvůli `V24917_TD_BLEND_NOT_IMPROVED`. Následná izolovaná realizace přijala pouze **SERV_noE_noC**, škála 1:

- c: `-1.86529737608591 → -1.75971450574142`; b se nezměnilo.
- Vážené GEH čerstvého TD rodiče: **30.608496800572112 → 30.570246334395467**.
- Blend **F = 0.9968458296247732**, váhy 0,6 GEH / 0,4 IDP; podmínka F <=0,999 prošla. IDP poměr `0.9939890764146228` je pod limitem 1,25.
- Vybraný komponentový survey objective SERVICE se zlepšil o **4,0716 %**. Tento údaj není zlepšení globálního GEH ani samostatný FineCDF RMSE.
- Gap `0.00458014`; realizace dokončena.

Rozlišujeme původní návrh v `target_changed_rows` / `tdjoint.final_abc` a skutečné přijaté řádky v outer `changed_rows`. Původní vnitřní návrh zahrnoval WORK, ale po komponentní izolaci se přijal pouze SERVICE. LONG a SCHOOL byly v aktivním poolu, LONG má `READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE`, žádná jejich b/c změna v tomto kroku přijata nebyla.

TD trvalo **2923,096 s = 48 min 43 s**, při 28 vnitřních vyhodnoceních (EXPLORE). Solver skončil na `TD_EVALUATION_BUDGET`. Obal navíc zaznamenává `LONG_SCHOOL_DESIGN_UNVERIFIED`; jde o neúplnou LONG/SCHOOL Generation část, ne o důkaz pádu samotného TD. Čítač procedure_sequence uvádí 47 volání / 1604,262 s; nejde o důkaz 47 úplných assignment řetězců. Časování je inkluzivní a vnořené položky se nesčítají na celkový wall time.

Před TD se také uplatnila zaznamenaná aktualizace přetížené impedance ICONG1. Proto nelze rozdíl mezi GEH předchozí přijaté Generation (30,3316) a nynějším výsledkem připsat samotné akceptované změně SERVICE. Výše uvedené TD zlepšení je vůči jeho skutečnému čerstvému rodiči 30,6085.

## Generation: všechny tři návrhy odmítnuty, rodič zachován

| Škála | GEH kandidáta | Výsledek |
| --- | --- | --- |
| 1,0 | 25,1119 | Zamítnut |
| 0,239474 | 28,9663 | Zamítnut |
| 0,115395 | 29,6964 | Zamítnut |

Rodičovské GEH je **30,570246334395467** a po rollbacku zůstalo stejné. Ve všech pokusech sice kleslo průměrné GEH, ale selhaly `NEW_SEVERE_GEH_PROFILE` a `PROTECTED_PROFILE_GUARD_FAILED`.

U nejmenší škály je rozhodující profil **920023**: GEH **1,5223 → 37,3939**, takže původně chráněný profil překročil tvrdou hranici 20. Nárůst je 35,8716, nad povoleným jednotlivým nárůstem 25. Profil **920022** vzrostl **19,8642 → 45,3947**, nárůst 25,5305, také nad limitem. Zamítnutí tedy odpovídá zaznamenaným ochranám, nikoli chybě importu nebo pádu při realizaci.

Rollback má `passes=true`, `snapshot_equal=true`, `diagnostic_equal=true`, `diagnostic_equivalent=true`. Ověřil 248 profilů s nulovým driftem, přesné matrix fingerprints a původní GEH. Použil plnou 12D/11D kontrolu; zamítnutí levnějšího reuse proof v tomto záznamu není selhání rollbacku. `LoadVersion`, `SaveVersion` ani přímé OD zápisy rollback nehlásí. Čas rollbacku byl 161,201 s. Generation design trval 179,189 s; tento údaj nezahrnuje celý Generation blok.

`stationarity_verified=true` se výslovně vztahuje jen ke konvergentnímu návrhu a dokončeným třem konfigurovaným pokusům. Zároveň `search_complete=false`, `stationarity_confirmed=false`, `ls_search_incomplete=true`; globální konvergence celé poptávky tedy potvrzena není.

## LONG a další hranice důkazu

Design má 2753 řádků, preview posledního odmítnutého pokusu 2993. **Žádný neobsahuje ADD_PROD_L ani ADD_ATT_L.** Dalších 240 řádků souboru `V24917_LONG_SCHOOL_ROWS.json` jsou hraniční WORK/SERVICE úpravy. Guard LONG přitom prochází, parent FineCDF je ověřená, krátká OSRM poptávka je nulová a `changed_long=false`.

Nové přílohy nedodávají aktuální `V24917_FIT_SUMMARY.json` ani `LONG_SHARED_CACHE_DEFERRED.json`. Nelze z nich určit nynější přesný důvod vyloučení LONG, ani prohlásit novou chybu či úspěšné živé nasazení opravy DIRECTIONAL/DIRECTED. Dokládají pouze, že LONG v tomto Generation kroku stále nedostal zónovou změnu. `VERIFIED_FIXED_LONG_GENERATION` ve vnitřním TD znamená zachování TG koeficientů během TD; samotný tento příznak neznamená vypnutí samostatné LONG Generation.

V dodaných stavech není důkaz pádu. Proces nyní nemáme možnost živě sledovat; přílohy nedokládají jeho současnou pozici ani finální stav celého běhu. Další konkrétní místo k ladění návrhu je jeho dopad na profily 920022/920023; ochranné limity tento audit nemění.

Ověření: `/workspace/.venvs/r1/bin/python /workspace/work/new_results_audit_20261031/audit_inputs.py`, návratový kód 0, 66 kontrol PASS. Skript je přiložen jako text s původními lokálními vstupními cestami. Runtime ani manifesty se v této větvi nemění, Visum nebyl spuštěn ani upraven. Tento datový audit není nový běh jednotkových testů produkčního kódu.
