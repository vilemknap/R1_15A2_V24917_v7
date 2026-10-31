# TD cyklu 5: přijatý čtvrtinový krok

Nahraný `TD_FINECDF_BLOCK_RESULT.json` končí **ACCEPTED_FINECDF_TD**, `td_realization_complete=true` a `td_outer_evidence_complete=true`. Vnitřní cesta výslovně ukazuje `DEMAND_CYCLE_05_TD_FINECDF` stejného běhu `RUN_20261031_125929_863675`. Jde tedy o následné TD k dříve dodané Generation po 4. cyklu.

Tento rozbor čte tři dodané soubory a porovnává je s předchozími osmi uploady. Nejde o připojení k Visumu, spuštění COM ani změnu běžící kalibrace. Zdrojová větev obsahuje poslední dodaný kód, avšak živá data nadále vykazují staré rozpočty běhu a3fc6c6.

## Výsledek a význam akceptace

| Realizační škála | GEH po pokusu | IDP blendu po pokusu | F | Rozhodnutí |
| --- | ---: | ---: | ---: | --- |
| 1,00 | 23,427509 | 0,455962 | 1,000973416 | zamítnuto |
| 0,50 | 23,031062 | 0,469087 | 1,001328899 | zamítnuto |
| 0,25 | **22,743760** | **0,475473** | **0,998992882** | **přijato** |

Všechny tři pokusy mají stejného rodiče pro vnější TD bránu: GEH **22,576998**, IDP **0,482027**. První dvě škály byly zamítnuty výhradně přes `V24917_TD_BLEND_NOT_IMPROVED`. Ochrany chráněných profilů i severity ve všech pokusech prošly; nejsou zde důvodem zmenšování kroku.

Přijatý krok zvýšil samotné GEH o **0,739 %** a snížil IDP o **1,360 %**:

```text
F = 0,60 × 1,007386373 + 0,40 × 0,986402644
  = 0,998992882 ≤ 0,999
```

Jde o zlepšení společného lokálního skóre přibližně o **0,1007 %**, těsně nad požadovanými 0,1 %. Rozdíl do meze je asi 0,000007118. Výpočet byl nezávisle přepočítán z uložených hodnot; zaokrouhlení F na 0,999 není důvodem označit rozhodnutí za chybné. IDP poměr současně splňuje strop 1,25.

Předchozí Generation skončila GEH 22,582594. TD rodič 22,576998 je až po mezilehlé aplikaci ICONG: jeho vstupní profilový model/observed poměr přesně navazuje na Generation a po přepočtu se změní. Tyto dva rodičovské stavy proto nelze zaměňovat.

## Stav vůči začátku a checkpointu

- Počáteční GEH 30,570246 → nyní přijaté **22,743760**, zlepšení **25,60 %**.
- Proti konci 4. cyklu 22,840160 je nynější GEH nižší o **0,422 %**.
- Profilový model/observed poměr je 0,852534. Jde o součet průjezdů profily, nikoli počet unikátních cest či celkovou poptávku.
- Aktuální profilové počty: GEH <5: **51**, <10: **91**, ≥20: **105**, ≥30: **70**. Předchozí nejlepší checkpoint měl 56 / 91 / 109 / 73; ne každá dílčí statistika se zlepšuje současně.
- Nový `BEST_SO_FAR_CHECKPOINT.json` přiložen není. Nižší GEH samo nedokazuje lepší společný checkpoint a IDP agregát vnějšího blendu nelze automaticky zaměnit za komponentový ledger. Aktualizaci BEST těmito přílohami nedokládáme; poslední skutečně dodaný BEST zůstává checkpoint č.8 po 4. cyklu.

Přijatý TD stav má hash:

```text
2446f0187b2e7633543155f0336710c64c7bb144a5582ca1a10f6f442e54bcf1
```

## Co se skutečně změnilo

V přijaté vnější realizaci se mění pouze c tří komponent, b zůstává stejné:

| Komponenta | c rodiče | c skutečně přijaté |
| --- | ---: | ---: |
| WORK_noE_C | −2,209741463 | −2,242166870 |
| SERV_E_C | −0,212984135 | −0,219280588 |
| SERV_noE_noC | −1,477490232 | −1,435065374 |

Škála 0,25 je interpolace v `log(−c)`, nikoli čtvrtina rozdílu samotného c. Byla přepočítána pro všechny tři řádky. `inner.tdjoint.final_abc` zachycuje plný vnitřní cíl; živě přijaté hodnoty jsou v hlavních `changed_rows`, nikoli v tomto plném cíli.

**LONG ani SCHOOL TD tentokrát nepřijaly změnu parametrů.** Porovnání 9111–9115 i 9117 `entry_abc` a `final_abc` je shodné; v přijatých vnějších řádcích také nejsou. LONG je v aktivním poolu a má `READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE`; jeho aktuální native assignment/skim vazba je doložena v reportu. To nepotvrzuje existenci úspěšného LONG kroku. Detailní poll log pro příčinu nepřijetí LONG není v přílohách.

Příznaky `generation_frozen` a `VERIFIED_FIXED_LONG_GENERATION` zde znamenají zachování P/A a koeficientů **během TD**. Nejsou důkazem, že je LONG Trip Generation globálně vypnutá. Hashové readbacky LONG i SCHOOL Generation ve vnitřním TD souhlasí; SCHOOL P/A mají zůstat fixní podle zavedené politiky.

## Neúplné hledání a rozpory v diagnostice

TDJOINT vyčerpal **60 z 60 vyhodnocení**, dokončil 3 iterace, stop reason `TD_EVALUATION_BUDGET`. Parametrický limit iterací byl 12, ale dříve se vyčerpal počet vyhodnocení. Nadřazený report opět uvádí `LONG_SCHOOL_DESIGN_UNVERIFIED`, `search_complete=false` a `stationarity_confirmed=false`. Přijetí kandidáta tak není prohlášením, že je hledání dokončené nebo stacionární.

Dva diagnostické rozpory přetrvávají v dodaném živém reportu:

1. `TD_TARGET_PLAN.frozen_components` obsahuje SCHOOL a LONG_COMPOSITE současně s `active_components`. Skutečný vnitřní active/frozen seznam tento průnik nemá a obě skupiny jsou aktivní. Samotné zastaralé pole plánu proto není důkazem jejich runtime zmrazení.
2. Přípravný blok `long_composite_td` stále nese `READY_FOR_LIVE_PROOF_NOT_YET_CERTIFIED` a blokátor `LIVE_NATIVE_DYNAMIC_COUNT_RESPONSE_PROOF_REQUIRED`, zatímco následný `tdjoint.long_composite_live_readiness` má aktuální pozitivní živý důkaz. Je nutné rozlišovat přípravný souhrn a pozdější měřenou evidenci.

Tento čtecí audit nemění produkční kód ani tyto popisky. Přesný důvod nezměněného LONG Generation nadále vyžaduje poslední `V24917_FIT_SUMMARY.json` a případný `LONG_SHARED_CACHE_DEFERRED.json`; nový TD report Generation návrh neobsahuje.

## Čas a doporučení

Celá TD etapa trvala **4077,959 s = 67 min 58 s**. Inkluzivní nativní `procedure_sequence` uvádí **2676,776 s = 44 min 37 s**, diagnostiky **271,973 s = 4 min 32 s**. Jde o vnořené časy; nesčítat je jako nezávislé části. Timing také nově obsahuje jeden zaznamenaný rollback 130,516 s; výsledek samotné TD realizace je úspěšný a záznam není důkazem uváznutí.

Nové vyšší rozpočty nejsou v tomto běhu aktivní. Z těchto výsledků není důvod běh zastavovat ani za běhu měnit kód či konfiguraci. Stále přijímá změny; zbývá sledovat následující cyklus a samostatně dořešit LONG Generation z designových důkazů. Aktuální stav okna Visumu z uploadů zjistit nelze.

## Ověření a záloha

**20 konzistenčních kontrol prošlo**, včetně přepočtu F, brány, logaritmické realizace c, návaznosti předchozí Generation/epochy a neměnnosti LONG/SCHOOL parametrů. Ověřeny SHA všech 3 nových i 8 předchozích uložených uploadů. Nejde o runtime regresi ani živý Visum test.

`INPUTS.json` uvádí identity a SHA. `inputs/*.gz.b64` zachovávají přesné původní bajty. `analyse.py.txt` je reprodukovatelný čtecí audit se standardní knihovnou Pythonu. Předchozí evidence je součástí téže větve v sousedním adresáři. Produkční soubory a manifesty se nemění.

```text
python artifacts_live_status_cycle5_td_20261031/analyse.py.txt
```

Kompletní záloha větve:

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/live-status-cycle5-td-20261031.zip
