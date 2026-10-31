# Přijatá Generation cyklu 7; LONG stále bez návrhu

Nových šest souborů patří **Generation cyklu 7**, nikoli již dokončenému C6. Číslo 7 je přímo v `ACCEPTANCE.severity_transition_guard.outer_cycle`; vstupní profilové metriky přesně souhlasí s koncem TD C6. Přijat je krok škály **1,0**, bez důvodů zamítnutí.

| Metrika | Před TG | Po přijaté TG |
| --- | ---: | ---: |
| Vážené GEH | 22,804861 | **22,465413** |
| Profilový model/obs poměr | 0,836841 | **0,850689** |
| GEH <5 | 52 | **54** |
| GEH <10 | 88 | **90** |
| GEH ≥20 | 102 | **100** |
| GEH ≥30 | 71 | **68** |

GEH se zlepšilo o **0,339448**, tedy **1,4885 %**. Profilové součty nejsou počty unikátních cest nebo celková poptávka. Vůči nejlepší samotné TG C6 (22,419918) zde nevzniká nové minimum GEH; po mezilehlém TD se napravuje část ztraceného counts zisku. Následující TD C7 ani nový BEST checkpoint dodány nejsou.

## Co se měnilo

Preview obsahuje **1929 kandidátních řádků**: 1869 základních + 60 hraničních WORK/SERVICE. Základ zahrnuje 452 řádků ADD_ATT_W, 452 ADD_SALARY, 360 ADD_ATT_S, 310 ADD_PROD_W, 275 ADD_PROD_S a 20 ZAHR řádků. `summary.candidate_count=1869` zahrnuje pouze základ; skutečná délka preview je 1929. Nejde o dalších 60 LONG změn.

`V24917_LONG_SCHOOL_ROWS.json` obsahuje pouze **60 BOUNDARY řádků WORK/SERVICE**, ač jeho historický název naznačuje jiný obsah. **ADD_PROD_L: 0, ADD_ATT_L: 0.** Také žádný řádek SCHOOL Generation; ta má dle zavedené politiky zachovat původní AMDY P/A.

Aktuální rodičovský LONGGUARD má `long_generation_permitted=true`, `support_clean=true`, `fine_cdf_verified=true`; objem pod povolenou mezí OSRM 80 km je nula. Jemná podmíněná RMSE LONG 100–200 km je dostupná, 0,053188 před a 0,053196 po. Akceptační záznam výslovně uvádí `changed_long=false`.

**LONG TG tedy neblokuje zde uvedená FineCDF/support brána. Návrh LONG změn v těchto souborech chybí.** Nelze z nich rozhodnout mezi odložením incidence/cache, neověřeným nebo nulovým fit výsledkem a jiným dřívějším vyřazením v návrhu. `skipped_rows=[]` není důkaz dokončené LONG návrhové větve: tento seznam popisuje již sestavený základní návrh. Pro přesnou příčinu stále chybí poslední designový `V24917_FIT_SUMMARY.json` a případný `LONG_SHARED_CACHE_DEFERRED.json`.

## Counts a IDP jdou v tomto kroku opačným směrem

Komponentový IDP ukazatel **společného ledgeru** se zhoršil **0,453317 → 0,477483**, tedy o **5,331 %**. Není to stejná agregace jako `ACCEPTANCE.idp_mean_degradation`, který hlásí absolutní rozdíl průměrné chyby 0,012380. Tyto hodnoty nelze zaměňovat.

Generation je zde podle stávající politiky counts-first: `COMPONENT_IDP=0` v cíli před i po, obecné IDP degradační meze jsou 1e30 a opravu distribuce vlastní následující TD. Společný counts ledger klesl 0,748732 → 0,737628, penalizace ADDVAL1 zůstala 0,00275. Reference ledgeru je před i po shodná. Samotné přijetí TG tedy neprokazuje zlepšení plného společného cíle za celý cyklus. Data opět ukazují opačný účinek TG/TD na counts a rozdělení délek; není to samo důkaz chyby sítě nebo nemožnosti další poptávkové změny.

Profilové, severity, nativní mobilitní i path-support kontroly prošly. V závěrečném mobility/projection guardu nebyl další krok oříznut; to nevypovídá o případném omezení už uvnitř původního fitu. Například skutečný navržený ADD_PROD_W v zóně 91 je 1,387951 → 1,734939 (+25 %).

## Predikce a omezení důkazu

`GENFIX2_FINAL_MOBILITY_AND_PREDICTION.json` obsahuje **247 profilových predikovaných změn toků** a přesně souhlasí s `preview.genfix2_prediction`. Nemá však potřebnou úplnou tabulku vstupních a skutečných výstupních toků ani globální predikované GEH. Z těchto šesti souborů proto nelze znovu spočítat poměr skutečného a predikovaného zlepšení ρ nebo kvantifikovat přestřelení predikce. Pomohl by odpovídající `STEP1_PLAN`/`GENERATION_BLOCK_RESULT` nebo kompletní 12D tabulky rodiče a kandidáta. Není podklad pro nové tvrzení o poměru 3–5× právě v tomto kroku.

## Ověření a GitHub záloha

**16 datových kontrol prošlo**, všech šest přesných uploadů je uloženo gzip+base64 v `inputs/` a má ověřený SHA. Kontroly zahrnují návaznost na C6, přijetí, přepočet zisku, identitu predikce, počty řádků, průchod LONGGUARD a nulové LONG zásahy. Výsledky jsou v `SUMMARY.json` a `CHECKS.json`. Produkční kód nebyl měněn, runtime testy ani živý Visum nebyly spuštěny. Větev pouze přidává čtecí evidenci k poslednímu dodanému kódu a předchozímu auditu C6.

```text
python artifacts_live_status_generation7_20261031/analyse.py.txt
```

Kompletní záloha větve:

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/live-status-generation7-20261031.zip
