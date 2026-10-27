# LONGGUARD1 — bezpečnost délkové přípustnosti při Trip Generation

Základ: SAFETYFIX2 / TDROLLBACKFIX1, beze změny nativní struktury TD nebo hodnot b/c.

## Důvod

Existující cílová křivka `LONG_COMPOSITE` je **podmíněná na 100–200 km** a normalizuje se pouze mezi těmito hranicemi. Sama nezaručuje, že celkové LONG OD nemají cesty pod 100 km. Také nezahrnuje přes 200 km; to ale nejsou nepřípustné cesty. LSGEN1 dříve mohl měnit `ADD_PROD_L` pro všech 681 zón bez této ochrany.

## Nové chování

1. Před generation design se z právě aktivní a k 11D diagnostice přiřazené epochy získá `DIS` skim **NATIVE_CL** v kilometrech a matice `9111–9115`. Z 2D OD sum vznikají tři **nepodmíněné** části: `<100`, `100–200` a `>200` km. Součet se musí rovnat celkové LONG poptávce.
2. LONG krok má navíc pevný samostatný limit +/-10 % za kandidáta, i když obecné `ls_max_step_up` v konfiguraci dovoluje +50 %. SCHOOL si zachovává vlastní dosavadní nastavení.
3. Při existujícím kladném objemu pod 100 km, nedostupném/stale skimu, neplatné COM hodnotě nebo chybějící 512bodové kompozitní diagnostice se **nevytvoří LONG generation kandidát**. WORK, SERVICE, SCHOOL mohou pokračovat. Nedostupnost LONG se ale nezapočítává jako dosažená stacionarita.
4. Pokud je rodič čistý, může LSGEN1 vytvářet návrhy `ADD_PROD_L`. Po plném nativním assignmentu a čerstvé 11D musí brána znovu prokázat, že objem `<100 km` je pod numerickou tolerancí 1e-6 vozidel/den a zhoršení 512bodového LONG CDF nepřesáhlo 5 % relativně plus 0,002 absolutně oproti rodiči ani prvnímu platnému rodiči v daném běhu.
5. Pokud má už rodič sub-100 objem a LONG je zmrazen, jiné generace jsou přípustné, pokud pod-100 objem nezvětší. Pokud rodičovský LONG skim nelze ověřit, jiné rodiny mohou pokračovat bez LONG změn; tento stav je označen za **neúplný**, nikoli za ověřenou stacionaritu.
6. Nevyhovující generation kandidát dostane `accepted=false`, po němž stávající controller zkusí menší škálu, případně provede **ověřený COM rollback v téže instanci**. Žádný `LoadVersion()` ani žádné přímé `SetValues()` OD matic nejsou přidány.

## Meze řešení

Tato oprava je **ochranná akceptační brána**, nikoli strukturální omezovač nativního Visum TD. Nepřepisuje stávající OD matice. Pokud vstupní `.ver` již obsahuje LONG cesty pod 100 km, běh je sice vykáže a dál je nesmí navyšovat, ale **nedokáže je tím sám odstranit**. K úplnému vyčištění výchozího stavu musí následovat nativní strukturální maska/přípustnost LONG OD v samostatné, otestované úpravě (předpoklad pro plnou TDLONG1). Pouhé úpravy sdílené matice 9002 by zasáhly i ostatní účely cest a nejsou zde použity.

Ochrana 100+ km **nevyřazuje cesty nad 200 km**. Globální 512bodová křivka pro 100–200 km zůstává cílem, nikoli absolutní rovností; ochrana pouze hlídá její významné zhoršení. Ostatní změny TD a komponentového targetingu nejsou součástí tohoto patche.

## Výstupy

- `LONGGUARD1_PARENT.json` při generation design: skutečné objemy a zdrojová epocha.
- `GENERATION_BLOCK_RESULT.json` a `ACCEPTANCE.json`: `longguard1`, `longguard1_parent`, `longguard1_after`, zamítnutí a důvody.
- `V24917_FIT_SUMMARY.json`: `longguard1_long_step_deferred`, `long_school_search_incomplete`.

## Offline ověření

Nové testy: 100/200 km hranice a >200 km, součet všech pěti OD matic, chybné/NaN vzdálenosti a objemy, stale 11D epoch, chyby COM, kontrola aktuální 512bodové chyby, odmítnutí kandidáta, zachování SCHOOL při zmrazeném LONG. Živý Visum COM není zde dostupný a zůstává nutnou akceptací.
