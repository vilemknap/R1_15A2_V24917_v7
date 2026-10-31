# Stav běžící kalibrace: čtyři cykly a další Generation

Z dodaných výsledků běhu `RUN_20261031_125929_863675`: kalibrace přijímá změny a vykazuje zlepšení. Po dokončeném 4. cyklu má nejlepší doložený checkpoint vážené GEH **22.8402**, proti počátečním **30.5702**: zlepšení **25.29 %**. Následující samostatný Generation report přijímá další krok na **22.5826** (celkem −26.13 % proti startu), ale jeho následující TD ani novější checkpoint dodány nejsou.

Jde o čtecí audit nahraných výsledků, nikoli o připojení k Visumu nebo změnu běžícího procesu. Zdrojová větev tohoto reportu navazuje na poslední dodaný kód b59e059; **samotné výsledky stále vykazují původní rozpočty a starší a3fc6c6 běh**, nikoli nový balík s rozpočty 6/56–180.

| Cyklus | GEH po Generation | GEH na konci cyklu | Přijaté TD komponenty | SupplyMix |
| --- | ---: | ---: | --- | --- |
| 1 | 27.3919 | 27.5210 | WORK_noE_noC, SCHOOL | nenaplánován |
| 2 | 23.5395 | 23.4529 | WORK_noE_noC, SERV_stud | bez přijatého pokusu |
| 3 | 22.7701 | 22.8650 | SERV_E_C, SERV_stud | nenaplánován |
| 4 | 22.5437 | 22.8402 | SERV_E_C, SERV_noE_noC, SCHOOL | přijat, 29 změn ADDVAL1 |

Koncové hodnoty jsou z přijatých vnějších TD rozhodnutí, nikoli z vnitřního surrogate score. Mezi Generation a TD probíhá i aktualizace impedance ICONG a v naplánovaných cyklech SupplyMix; nelze proto rozdíl obou GEH sloupců celý připsat TD.

## Celkové metriky nejlepšího doloženého checkpointu

| Metrika | Start | Checkpoint po cyklu 4 |
| --- | ---: | ---: |
| Vážené GEH | 30.5702 | 22.8402 |
| Poměr součtů model/pozorování na profilech | 0.6984 | 0.8587 |
| Profilů GEH <5 | 27 | 56 |
| Profilů GEH <10 | 47 | 91 |
| Profilů GEH ≥20 | 135 | 109 |
| Profilů GEH ≥30 | 92 | 73 |
| Komponentový IDP ukazatel checkpointového ledgeru | 0.498829 | 0.471876 |

IDP ukazatel se zlepšil o **5.40 %**. Není totožný s agregací vnějšího TD blendu a nelze jej zaměňovat s procentem chybné délky cesty. Součty profilových intenzit nejsou počtem unikátních cest ani odhadem celkové poptávky; jedno vozidlo může projet více profily. Metriky zahrnují 247 pozitivně pozorovaných CAL řádků.

Nejlepší dodaný checkpoint má accepted_count **8** a stejný state_hash jako konec 4. cyklu:

```text
BEST_SO_FAR_0008_22bdb5563733.ver
ACCEPTED_B_0008_e84f405c9e20.ver
```

Oba souborové záznamy uvádějí stejný SHA a velikost. Kontrola je nad JSON metadaty; samotný .ver není přiložen a jeho bajty nebyly nezávisle znovu hashovány.

## Další Generation po tomto checkpointu

Přiložený samostatný `GENERATION_BLOCK_RESULT.json` má výchozí cal_metrics i raw_component_idp přesně shodné s checkpointem č.8, takže navazuje na konec 4. cyklu. Neobsahuje přímo číslo vnějšího cyklu; přirozeně jde o následující Generation, její číslo proto nepovažujeme za samostatně dokázané.

- ACCEPTED, první pokus, scale 1.0, 2171 změnových řádků.
- GEH **22.8402 → 22.5826**; predikce celkového GEH byla **22.4731**.
- Profilový model/observed poměr **0.8587 → 0.8514**; průměrné GEH se přesto zlepšilo. Zlepšení není totéž co monotónní růst součtu intenzit.
- Komponentový IDP ledgeru se zhoršil **0.471876 → 0.481856**, přibližně o **2.12 %**. Následný TD jej má znovu vyhodnotit/opravit.
- Při převzetí stejných plných vah checkpointového ledgeru vychází čistě aritmeticky přibližně **1.223318** proti checkpointovým **1.221763**. Tato rekombinace je čtecí výpočet, nikoli nové native rozhodnutí. Vysvětluje, proč nižší GEH v samotné Generation automaticky nedokazuje lepší společný checkpoint.

Generation používá counts-first dílčí ledger s odloženým IDP; jeho `total` proto nelze přímo porovnávat s `BEST_SO_FAR.objective.total`, kde je IDP zahrnuto. Reference hash ve všech těchto záznamech souhlasí.

## Nové zónové hledání se opravdu použilo

V cyklu 1 byl první návrh odmítnut kvůli chráněným profilům. Následoval `MEASURED_ZONAL_REFIT` a druhý pokus byl přijat. Nový zónový směr se tedy v živém běhu prokazatelně aktivoval a jeho kandidát prošel nativními kontrolami. Z toho ale neplyne certifikace jednotlivých derivací G; jde stále o návrhový model.

## SCHOOL a LONG

**SCHOOL TD funguje:** jeho nativní c bylo skutečně přijato ve 1. a 4. cyklu. Není jen v přepínači. SCHOOL Generation zůstává původní AMDY funkcí podle zavedené politiky.

**LONG TD je v aktivním prostoru a má deklarovanou aktuální živou připravenost:** v každém cyklu `READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE`, měřený DYNAMIC assignment a čerstvé skimy. Porovnání všech záznamů 9111–9115 `entry_abc` a `final_abc` ale ukazuje **nulové změny ve všech čtyřech vnitřních etapách**; ani vnější přijaté řádky LONG neobsahují. Aktivaci nelze zaměňovat s přijatým vylepšením LONG. Detailní rank/poll log pro konkrétní důvod nepřijetí LONG přiložen není.

**LONG Generation zde nemá doložený přijatý zásah:** ve všech přijatých Generation pokusech, včetně dalšího samostatného bloku, je `longguard1.changed_long=false`. Zároveň rodičovský LONGGUARD1 v dodaných pokusech LONG povoluje, takže není podklad opakovat staré vysvětlení chybějící FineCDF. Celý běh ale stále hlásí `ls_search_incomplete=true` a `LONG_SCHOOL_DESIGN_UNVERIFIED`.

Přesný důvod (cache/incidence, numerický fit, odložená data nebo jiná konkrétní větev) tyto souhrny neobsahují. Rozhodující další podklady jsou z posledního `DESIGN/V24917_TARGETED_GENERATION/`:

```text
V24917_FIT_SUMMARY.json
LONG_SHARED_CACHE_DEFERRED.json  (pokud vznikl)
```

Pomocná pole `td_target_plan.frozen_components` ještě uvádějí SCHOOL/LONG, ale skutečný vnitřní active/frozen seznam a přijaté SCHOOL změny prokazují jejich aktivaci v TD. Ve 3. cyklu je navíc uložený joint component_pool širší než vnější aktivní seznam; bez detailního TDJOINT_SEARCH nelze z tohoto souhrnu přesně zrekonstruovat rozložení sond mezi skupiny. Tyto diagnostické popisky nejsou důkazem odpojení SCHOOL nebo LONG.

## Proč je stav stále PROGRESS_CONTINUE

Generation i TD mají v cyklech 1–4 přijaté změny, takže společný stacionární stav ještě nenastal. Vnější TD evidence je označena jako úplná a realizace dokončená. `completed=false` / `search_complete=false` zde neoznačuje pád: controller pokračuje s příznakem neověřeného LONG/SCHOOL hledání.

Skutečný TDJOINT vnitřní důvod zastavení je v každém cyklu **TD_EVALUATION_BUDGET**: 28 / 28 / 60 / 60 vyhodnocení. Nadřazený report jej překrývá společným `LONG_SCHOOL_DESIGN_UNVERIFIED`. Nové vyšší rozpočty v těchto datech ještě nejsou aktivní. Generation má stále planned_trials=3.

TD může přijmout nepatrné zhoršení samotného GEH, pokud se zlepší společné F. V cyklu 4 se během vnější TD realizace GEH změnilo **22.8243 → 22.8402** (+0.069 %), současný vnější IDP poměr byl **0.966608** (−3.34 %) a F **0.987059**, což splňuje mez 0.999. Nejde o stejný IDP agregát jako raw_component_idp v checkpointovém ledgeru.

## Čas a doporučení

Přiložený timing uvádí pro čtyři TD etapy celkem **11835 s**, průměrně **49 min 19 s**. Poslední Generation design zabral **845 s**, přibližně **14 min 5 s**. Jsou to inkluzivní časy vnořených etap; nesčítat je jako nezávislé složky celkové doby běhu.

Z těchto výsledků není důvod produktivní běh zastavovat. Přijímá další změny a nejnovější dodaná etapa končí ACCEPTED. Přesný stav okna Visumu v okamžiku čtení z nahraných souborů zjistit nelze. Během běhu nevyměňovat kód ani R1_RUN_OPTIONS.json. Pro LONG před dalším během vyhodnotit uvedený designový důkaz; neodvozovat úspěšnou LONG kalibraci jen ze společného zlepšení GEH.

## Reprodukce a záloha

Produkční kód ani manifesty nejsou v tomto auditu měněny. `SUMMARY.json` uchovává strojový přehled. `analyse.py.txt` dekomprimuje osm přesných původních uploadů, ověří SHA a zkontroluje návaznost stavů, přijetí TD a vazbu další Generation. Příkaz:

```text
python artifacts_live_status_cycles1_4_20261031/analyse.py.txt
```

Bajty všech osmi souborů jsou zachovány gzip+base64 v `inputs/`, SHA a velikosti v `INPUTS.json`. Osm základních konzistenčních kontrol prošlo; nejde o nové runtime testy softwaru nebo spuštění Visumu. Výsledek v `CHECKS.json`. Kompletní archiv větve je dostupný přes:

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/live-status-cycles1-4-20261031.zip
