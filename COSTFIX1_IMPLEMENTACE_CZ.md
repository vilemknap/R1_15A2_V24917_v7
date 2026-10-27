# COSTFIX1 – bezpečná atraktivita tras v SupplyMix (27. 10. 2026)

## Problém potvrzený z cyklů 10, 12 a 14 (GENFIX1)

Všechny tři cykly vykázaly `NONPOSITIVE_MINIMUM_GENERALIZED_COST` a následný
`TRIAL_FAILED_ROLLBACK_VERIFIED`. V každém sloučeném návrhu byla komponenta
pro profil 920435 o amplitudě `step_units=1`, tj. `ADDVAL1 = -0,5`, přestože
Visum ukládá ADDVAL1 do celočíselného atributu (ValueType=1).
To je prokazatelná nekonzistence návrh/realizace; konkrétní první selhávající
směrový úsek však nelze z dostupných souhrnných JSON jednoznačně doložit.

Kritická možnost: u linku s nezatíženým nákladem 7 sekund dává
`-0,5` výsledný náklad `7 - 5 = 2 s` (legální), ale dosavadní zaokrouhlení
`-0,5 -> -1` by dalo `7 - 10 = -3 s` (nelegální). Vrstva designu ověřovala
původní půljednotkový návrh a aplikace správně odmítla až nový celočíselný.

## Implementace

Změněn jeden produkční modul: `r1_15a2_supply_mix_v24917.py`.
Nová čistá funkce `cost_safe_merged_candidate` vybere celý doložený kandidát
se zákonným výsledným `ADDVAL1` ještě před `apply_supply`. Kontroluje živé
`T0_PRTSYS(C)` a `ADDVAL1` načtené z modelu a aplikuje původní
`check_addval_change` včetně doménových, kumulativních, krokových a mřížkových
limitů. Ověřuje také shodu očekávané výchozí hodnoty a baseline autoritu.

Při celočíselném atributu nepřevádí půl kroku na větší, nekontrolovaný zásah;
využije pouze původně navržené celočíselně realizovatelné členy sestupného
žebříčku. Pokud je vybraná větev neproveditelná, projde další doložené větve
stejného profilu. Alternativní větev může zdražit skutečně doloženou OFF
objížďku místo zlevnění ON komunikace s příliš malým t0. Není-li taková
alternativa, zkouší zbývající profily a nevytváří fiktivní objížďky.

Neprovádí částečné ořezání segmentu doložené cesty ani umělé navyšování
časů/v0. Nevkládá nové záporné impedance. Při nedostupnosti všech
bezpečných kandidátů se neprovede žádný zápis/assignment a výsledek je
`NO_COST_SAFE_CANDIDATE`, bez falešného označení stacionarity.

Doplňuje `costfix1` evidenci uvnitř `SUPPLYMIX_BLOCK_RESULT.json`, včetně
zamítnutých důvodů, ukázkových klíčů a skutečně použitých stupňů kroku.
Duplicitní opakování identického bezpečného návrhu v jednom bloku se nepřepočítá.

## Co zůstává nedotčeno

- Nativní assignment a všechny ochrany i ověřený rollback GENFIX2.
- Přijatá poptávka, Generation, TDJOINT1 a samostatná optimalizace `b/c`.
- Konzistentní význam 1 ADDVAL1 = 10 zobecněných sekund.
- Pravidla přijetí, minimum cost 0,001 s, ostatní meze profilu.
- Konfigurace a váhy 65/35, volitelný spouštěč 60/40.
- Pevné autority a všech 1059 původních chráněných souborů.

## Testy

1594 unikátních testů prošlo; 4 historické skipy; 0 fail.
Rozdělené samostatné běhy (kvůli historickým kolizím importů):
1387+4 skip hlavní bez TDJOINT, 51 TDJOINT, 138 DIAGFAST a 18 GENFIX2 audit.
Sedm nových regresních testů v `tests/test_v24917_supply_mix.py`.
Kontrola syntaktického překladu i obou runtime/obou DIAGFAST manifestů prošla.

## Omezení a první živý test

Toto je offline oprava, ne potvrzení běhu Windows/Visum COM. Proveďte
kontrolovaný cyklus ze samostatné kopie posledního ověřeného `.ver` a
zkontrolujte `SUPPLYMIX_BLOCK_RESULT.json` / `costfix1` a stav modelu po
zamítnutých kandidátech. Rozhodující je, že už nemá nastat nebezpečný zápis
v návrhu profilu 920435; nenahrazuje to výhledovou potřebu čerstvých
alternativních tras pro skutečně nulově zatížené komunikace.

Pokud je podhodnocená komunikace zcela bez uložené ON trasy a neexistuje
ověřená OFF alternativa, tento malý zásah nezíská nový trasový důkaz.
To už vyžaduje zvláštní návrhový modul pro trasování alternativ, ne změnu
minimální impedance a ne zásah do metodiky poptávky.
