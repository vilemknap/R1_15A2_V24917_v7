# Proč targeted Generation nevytvořila přijatou změnu

Dodatečných 7 souborů patří ke stejnému Generation kroku cyklu 2 jako předchozí audit `75bd8a0d3756c29ec053a254ef87f345aa613529`. Shodují se přesně LONG parent proof i rodičovský model/observed poměr. **29 čtecích kontrol prošlo**; zdrojové SHA a konkrétní hodnoty jsou v `SUMMARY.json`. Tento rozbor nemění runtime ani živý model.

## Aktivace a výsledek fitu

Targeted Generation skutečně běžela: `V24917_ZONAL_COUNT_FIT`, `GUARDED_PROPOSAL`, `solver_converged=true`, `proposal_usable=true`, bez zaznamenané chyby či fallbacku. Fit byl v režimu CATCH_UP. Zpracovával 247 CAL profilů, 2604 proměnných a navrhl 2258 projekčních řádků pro **644 zón**. Z nich 882 dosáhlo horní a 390 dolní meze fitu. Jde o koordinovaný návrh napříč většinou modelu, nikoli o izolovanou úpravu dvou profilů.

Mobilitní podklady jsou dostupné; mobility fit neomezil žádnou další proměnnou (`changed=0`, `frozen=0`) a projekce neodřízla žádný řádek (`rows_clipped=0`). Záznam tedy neukazuje blokaci W/S návrhu kvůli nedostupným FP nebo mobilitě. Samotné numerické coefficient bounds se samozřejmě během řešení uplatňují.

Volitelné následné zeslabení necílových FlowBundle zón je vypnuté: `flowbundle_mask.status=OFF`, `non_target_factor=1.0`. To není vypnutí cíleného zonálního fitu; tento audit obě vrstvy rozlišuje.

## Potvrzený nesoulad lokální predikce

Pro poslední skutečně vyhodnocenou škálu **0,115395** uvádí `GENFIX2_FINAL_MOBILITY_AND_PREDICTION.json` základní predikci změny toku na profilu **920023 jen -12,806566 vozidel/den**. Živá kontrola přitom změřila GEH **1,522286 → 37,393888**. To je podstatná chyba lokálního modelu odezvy, i když celkové GEH kandidáta kleslo **30,570246 → 29,696367**.

Kontrolní výpočet: ověřená CSD autorita dává pozorování 5586. Z tohoto pozorování a počátečního GEH lze dopočítat dvě možné hodnoty počátečního modelu (neznáme znaménko rezidua). Po přičtení uvedeného odhadu -12,806566 by odpovídající GEH bylo přibližně **1,6955 nebo 1,3526**, nikoli 37,3939. Jde o matematické diagnostické možnosti, nikoli o tvrzení, že tyto dopočtené intenzity byly přímo uloženy nebo změřeny v modelu. Skript ověřuje i SHA zdrojového CSV.

Tato základní predikce není totéž co sekantově opravená předpověď STEP1 používaná při výběru další škály. STEP1 už využívá naměřený předchozí pokus ke korekci odhadu. Ani tato korekce však při třetím pokusu nedokázala zajistit průchod živou ochranou.

U profilu 920023 byl překročen chráněný limit GEH 20 a jednotlivý povolený nárůst 25. U opačného směru téže fyzické linky, profilu 920022, se GEH zhoršilo 19,8642 → 45,3947. Přijetí proto správně odmítly původní ochrany. Všechny tři návrhy sice snižovaly průměrné GEH, ale žádný nebyl bezpečný pro všechny povinné kontroly.

## Proč současné targeted řešení tomuto nezabránilo

Zdroj `r1_15a2_zonal_count_fit_v24917.py` řeší přibližný, vážený model lokálních P/A změn odvozený od aktuální path incidence. Chráněné profily dostávají vyšší váhu v reziduálním cíli; jejich skutečné živé GEH není tvrdou nelineární podmínkou uvnitř tohoto solveru. Tvrdé vnitřní podmínky řeší zejména coefficient bounds a P/A bilanci. Numerická konvergence tak potvrzuje dořešení této přibližné úlohy, nikoli shodu její citlivosti s celým nativním TG→TD→20A/20B→assignment řetězcem.

`r1_15a2_step_search_v24917.py` vytvoří zónový kontext před smyčkou pokusů. Po odmítnutí upraví odhad pomocí měřeného průtoku a hledá další globální škálu stejného základního návrhu. Při každé škále znovu sestavuje skutečné preview včetně mezí a P/A úprav, ale **zónový fit znovu neřeší tak, aby změnil směr podle nově poškozených profilů**. Skutečná odezva může být mezi pokusy jiná než předpokládané škálování.

Živě se zkusily pouze škály **1; 0,239474; 0,115395**. Minimum 0,05 bylo v posledním plánu predikčně přípustné a robustní, ale kvůli rozpočtu tří pokusů nebylo skutečně přepočteno. Nelze tvrdit, že by minimum určitě prošlo; další živé zmenšení by bylo samostatné měření, ne potvrzené řešení problému lokální odezvy.

Z těchto JSON není možné oddělit, která nativní fáze způsobila tak velkou lokální odchylku (realizace TG, TD, konverze nebo nové rozdělení tras). Audit proto nepřisuzuje nesoulad výhradně assignmentu a neprohlašuje konkrétní novou produkční chybu bez reprodukce.

## Nezávislý problém LONG

Nový `LONG_SHARED_CACHE_DEFERRED.json` potvrzuje přesně **LONG_INCIDENCE_PROFILE_AUTHORITY_DIRECTION_INVALID**. LONG parent guard přitom prochází a FineCDF je ověřená. LONG je vyžádaný, ale candidate eligibility je false a LONG kroky jsou nulové. Jde o stejnou popsanou blokaci směrové autority; tyto výsledky neukazují její živé odstranění. Není to příčina konkrétního zamítnutí W/S kandidáta na profilu 920023, ale LONG v tomto fitu chybí jako samostatná možnost změny poptávky.

Poslední dodaná oprava `DIRECTIONAL → DIRECTED` je v commitu `67e6ab5540c15c56e0f5ed5f0f3152e8b397f4cf`. Audit neposuzuje nasazení podle pouhého tvrzení o zapnutí přepínače; současný přesný runtime commit nebyl přiložen.

## Doporučený další omezený vývojový krok

Po odmítnutí využít naměřenou chybu chráněných profilů k přeřešení zónového směru, místo samotného globálního zmenšování. Omezovat příspěvky, které zatěžují kritické profily, a výsledek dál ověřovat stejnými živými akceptačními bránami a rollbackem. Vyšší rozpočet pokusů může umožnit ověřit menší škálu, ale sám nespraví nesoulad lokálního modelu. Tento krok nebyl automaticky implementován; uživatel se v této zprávě ptá na vysvětlení.

Příkaz auditu: `/workspace/.venvs/r1/bin/python /workspace/work/targeted_explanation_20261031/audit_inputs.py`, exit 0. Skript s původními lokálními vstupními cestami je přiložen jako text. Zdrojový runtime a jeho manifesty zůstávají beze změny; nová větev doplňuje jen rozbor, vstupní identity a výsledky kontroly. Žádný živý COM test ani zápis do Visumu nebyl proveden.
