# V24917 – SCHOOL Trip Distribution FineCDF: samostatná b/c kalibrace

**Vývojová větev:** `codex/v24917-school-td-finecdf-active-20261030`  
**Základ:** `codex/v24917-unlock-long-zonal-tg-composite-td-20261030`

## Závazná metodika

SCHOOL Trip Generation je **fixní podle původních funkcí AMDY**:
`FP_5_SCHOOL` a `FA_5_SCHOOL` NEPOUŽÍVAJÍ `ADD_PROD_SCH`
ani `ADD_ATT_SCH`. Proto se tyto dva dodatečné atributy
neoptimalizují a jejich návrhy se odfiltrují. Záměrně fixní Generation
se nesmí vydávat za nedokončené hledání nebo důvod ke zrušení konvergence.

SCHOOL Trip Distribution je **samostatná** nativní demand stratum
`5_SCHOOL` s person OD maticí **9117**. Kalibrují se pouze
gravitační parametry `b` a `c`, parametr `a` zůstává fixní,
ostatních 16 komponent se nesmí měnit mimovolně.

Referenční distribuční cíl je již přítomný v byte-identickém
`reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py`:

- `FINE_AUTHORITY.targets.SCHOOL`: `grid=atomic`, `source=DIRECT_PURPOSE`
- **512 bodů** IDP FineCDF v rozsahu **0,1–100 km** (cíl je vzdálenost, nikoli čas)
- jeden SCHOOL cíl pro M9117 (nikoli společná směs s WORK ani samostatná LONG křivka)
- původní diagnostické šestitřídní rozdělení SCHOOL má průměr **9,085186 km**
- žádné přepisování IDP referenčního zdroje nebo jiné normalizace křivky

## Aktivace

`R1_RUN_OPTIONS.json` obsahuje `school_td_enabled=true`.
Výchozí hodnota pro jiná nasazení je `false`. Pro aktivaci je nutný
`td_joint_enabled=true` a nenulová politika TD. Nynější V24917
pracuje s `td_inner_mode=DYNAMIC`; ten společně platí také pro
WORK/SERVICE a LONG. Nelze zaměňovat DYNAMIC s dynamickým přidělením
časových intervalů; jde o opakovanou síťovou realizaci každého návrhu.

SCHOOL se zařadí do:
- **ACTIVE**: cílený seznam W/S + SCHOOL + (pokud požadován) jeden LONG_COMPOSITE
- **GLOBAL_IDP_FALLBACK**: při zapnuté funkci je SCHOOL součástí
  referenční množiny optimalizovaných komponent; při vypnutí je explicitně vyřazen

Nadále platí **jedna společná objektivní funkce** TDJOINT1:
60 % kalibračních intenzit a 40 % IDP. Skóre počtů se
započítává jednou, nikoli jednou za každou vrstvu. Inner výběr není
přijetí; realizovaný kandidát musí projít původními hard guardy,
GAP, 11D/12D, chráněnými profily a zdokumentovaným rollbackem.
Během samostatného TD kroku zůstává Generation fixní.

## Ochrany a důkazy

`r1_15a2_school_td_v24917.py` validuje source `DIRECT_PURPOSE`,
matrici 9117, demand stratum `5_SCHOOL`, monotónní 512bodový CDF,
hranice gridu 0,1–100 km a skutečnou mutabilitu b/c. Pokud některá
podmínka nesedí, TD SCHOOL se nesmí odemknout.

`r1_15a2_td_joint_runtime_v24917.py` provádí scoped výběr
SCHOOL a LONG v aditivní vrstvě V24917, nikoli změnu chráněného
`r1_15a2_finecdf_bridge_v24916.py`.

Při cíleném kroku vzniká `TDSCHOOL_TARGET_SCOPE.json`, dále
`TDJOINT_SUMMARY.json`, `V24916_FINECDF_INNER_RESULT.json`,
`TD_ACTIVE_COMPONENT_MASK.json`. Pro LONG nadále vzniká původní
`TDLONG_COMPOSITE_TARGET_SCOPE.json`.

## Nedoložené části

Tato změna se testuje offline. **Skutečný Visum 2026 běh zatím
není součástí potvrzeného výsledku**. Před dlouhou kalibrací je
nutné ověřit první SCHOOL kandidát v nativním TD: změněné b/c
`5_SCHOOL`, přepočítaná M9117, změna školní FineCDF / GEH,
nedotčené školní FP/FA a následný úspěšný návrat parametrů při
odmítnutí kandidáta. Teprve pak lze deklarovat provozní připravenost.
