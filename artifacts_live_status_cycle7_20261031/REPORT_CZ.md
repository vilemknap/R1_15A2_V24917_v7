# Dokončený cyklus 7: TD tentokrát zlepšil counts i IDP

Sedm nových souborů potvrzuje dokončenou nativní realizaci TD i přijetí Generation v cyklu 7. Vstupní state_hash přesně navazuje na konec C6. Samostatné blokové reporty Generation/TD jsou totožné s jejich kopiemi v `DEMAND_CYCLE_07_RESULT.json`.

| Stav | Vážené GEH |
| --- | ---: |
| Vstup do TG C7, konec C6 | 22,804861 |
| Po přijaté TG C7 | 22,465413 |
| Rodič TD po mezilehlém ICONG přepočtu | 22,425136 |
| Po přijatém TD C7 | **22,397580** |

TD přijal plnou škálu **1,0**, pouze jeden realizační pokus. Proti vlastnímu rodiči zlepšil GEH o **0,1229 %** a IDP **0,479127 → 0,449256**, tedy o **6,2344 %**. Společné vnější **F = 0,97432505** splňuje mez 0,999. Ochrany profilů i severity prošly. Nativní assignment gap je **0,00168358**. Vnitřní normalizovaný surrogate 0,927669 není totéž co toto vnější F.

Na rozdíl od C6 TD counts zisk TG nezhoršil. Mezi TG a TD navíc probíhá ICONG, takže celou změnu 22,4654 → 22,3976 nelze připsat samotnému TD. Celý cyklus zlepšil GEH proti konci C6 o **1,7859 %**. Proti začátku běhu 30,570246 je nyní GEH nižší o **26,7341 %**.

Finální profilové metriky: model/obs **0,847252**, GEH <5 **53**, <10 **90**, ≥20 **98**, ≥30 **67**. Profilové součty nejsou počtem unikátních cest ani celkovou poptávkou. Jde o nejnižší dodaný koncový GEH v tomto běhu, nikoli automatický důkaz aktualizovaného celoběhového BEST checkpointu; nový `BEST_SO_FAR_CHECKPOINT.json` přiložen není.

## Přijaté parametry

Přijat je c komponent **WORK_noE_C, WORK_noE_noC, SERV_noE_noC a SCHOOL**. Jejich b zůstává stejné. SCHOOL c se mění **−0,430967873 → −0,406573465**. Tím máme další důkaz, že SCHOOL TD je zapojené a změny skutečně přijímá.

LONG 9111–9115 mají v TD vstupní i finální abc shodné. Generation znovu uvádí `changed_long=false`. Podrobný `TDJOINT_SEARCH.json` tohoto cyklu přiložen není; konkrétní důvod nepřijetí LONG z předchozího C6 nelze automaticky přenést na C7.

## Predikce Generation: dvě různá rho a různé agregace

`STEP1_PLAN_01.json` a přijatý pokus souhlasí:

- Vstupní GEH **22,804861**.
- Predikovaný GEH **22,609331**, očekávané zlepšení **0,8574 %**.
- Skutečný GEH **22,465413**, zlepšení **1,4885 %**.
- Poměr zisků samotného GEH je **1,7360**: skutečný zisk byl zde větší než plánovaný.
- Plán používal historicky naučené `rho=0,296890932`.
- Pokus nově zaznamenal `rho_measured=0,2`.

`rho_measured` není poměr skutečného a predikovaného GEH zisku. Funkce `StepModel.learn_rho()` počítá projekci skutečných změn profilových toků do neškálovaného predikovaného vektoru:

```text
rho_raw = dot(delta_pred, delta_measured) / dot(delta_pred, delta_pred)
rho_measured = clip(rho_raw, 0.2, 1.5)
```

Plán pro výpočet GEH naopak použije tokový odhad již násobený historickým rho. GEH je nelineární agregace, takže jde o různé statistiky. Hodnota 0,2 leží na dolní hranici ořezu; přesné neoříznuté rho ani podrobné směrové chyby z tohoto reportu nezjistíme. **Z rho=0,2 nelze tvrdit, že právě v tomto kroku byl zisk GEH přestřelen pětkrát.** Čísla aktuálního plánu ukazují opak. Detailní audit profilu nadále vyžaduje vstupní/výstupní 12D toky nebo novější `STEP1_PRED_AUDIT.json` z dodaného vývojového balíku.

## Čas, rozpočty a stav běhu

TD etapa trvala **4239,067 s = 70 min 39 s**. Samotný návrh TG **880,349 s = 14 min 40 s**; to není celý Generation blok. Nativní procedure_sequence TD má inkluzivně 2876,809 s, diagnostiky 149,474 s. Časy vnořených etap nesčítat jako nezávislé složky.

Živá Generation má stále **planned_trials=3**, TD **60 vyhodnocení** a stop reason **TD_EVALUATION_BUDGET**, dva dokončené poll průchody. Nové větší rozpočty nejsou v těchto datech nasazené. SupplyMix v lichém cyklu 7 není připojený jako samostatný blokový výsledek.

`PROGRESS_CONTINUE_DEMAND`, `LONG_SCHOOL_DESIGN_UNVERIFIED` a `joint_stationary=false` zůstávají. TG i TD přijaly změnu, tudíž ani bez tohoto příznaku nelze cyklus považovat za stacionární. Nejde o záznam pádu. Koncový state_hash:

```text
f305aaf79c60dc2066228c2aa555eef40af29ef2c598298a596d29b003199633
```

## Kontroly a záloha

**17 datových kontrol prošlo**; přesné bajty a SHA všech sedmi uploadů jsou uložené v `INPUTS.json` a `inputs/*.gz.b64`. Dva soubory se shodným názvem `V24917_TIMING.json` mají oddělené štítky `timing_gen` a `timing_td`, žádný nepřepsal druhý. `analyse.py.txt` reprodukuje výpočty, `SUMMARY.json` obsahuje výsledky. Produkční kód nebyl změněn, runtime testy ani Visum se nespouštěly.

```text
python artifacts_live_status_cycle7_20261031/analyse.py.txt
```

Větev obsahuje poslední dodaný zdrojový balík a předchozí čtecí audity. Její nastavení nového SupplyMix nelze zaměnit za nastavení právě analyzovaného staršího běhu.

https://github.com/vilemknap/R1_15A2_V24917_v7/archive/refs/heads/codex/live-status-cycle7-20261031.zip
