# R1 15A2 V2.3 - actual-path sequence ADDVAL1 calibration

## Vychozi verze a hranice dukazu

V2.3 navazuje na **skutecny V2.2 OFFLINE_VERIFIED** ZIP,
SHA-256 `63b581520c0e590415c80bbbed026dba32f708719fc5022627c359eae1a522dd`.
Nemeni puvodni TG/TD numeriku, vyhodnocovani sdileneho objective ani COM zapisovaci
adapter a checkpoint/rollback controller. Pridava oddelenou route-sequence supply navrhovou vrstvu.

**V2.3 je OFFLINE_VERIFIED, nikoli LIVE_VISUM_VERIFIED ani PRODUCTION_READY.**
Bez zivych COM identifikatoru assignment operaci, gap readbacku, exportu realnych
Visum saved paths a overeni VDF/impedance authority nespoustet APPLY.

## Jak funguje ADDVAL1 route choice

1. Pro kazdy CAL profil se vyberou skutecne PrT paths pres jeho smerovy link.
2. V ramci stejneho **DSeg x OrigZoneNo x DestZoneNo** se vyhledaji skutecne
   ulozene cesty profilem neprochazejici.
3. Kolem profilu se z paru cest vyberou **spolecne uzlove kotvy diverge/rejoin**.
   ON a OFF vetve jsou doslovne souvisle vyrezy existujicich ulozenych paths.
   Neni dovoleno skladat jednu "sekvenci" z hran ruznych tras.
4. Pro zatizeny profil muze byt ON znevýhodnena nebo OFF zvÿhodnena; pro
   podhodnoceny profil naopak. Spolecne linky on/off vetvi nejsou kandidatem.
5. Jedna puvodni sekvence muze mit zkraceny **souvisly** podusek. Pri CAP-SPLIT
   se meni pocet samostatne dolozenych bundles, ne libovolny seznam hran.
6. Cely export osobnich PrT paths je uchovan v SQLite a nad **vsemi dotcenymi
   ulozenymi cestami** je pocitana presna prime ADDVAL1 expozice v sekundach:
   `10 * SUM(multiplicity(edge,path) * delta_ADDVAL1(edge))`.
   CAL-other, CAL-protected, driver-ON a ostatni paths maji oddelene metriky.
   VALID pozorovani se pro navrh ani impact classification nepouzivaji.
7. Candidate se zapisuje stale jako **smerove linkove ADDVAL1**, nikoli jako
   uprava cesty. Odezvu noveho assignmentu predpovidat z existence soucasnych
   ulozenych cest nesmime. Trial musi spustit assignment pri uplne zmrazene
   poptavce a projit stavajicim V2.2 ACCEPT/ROLLBACK postupem.

Duvod: `actual_path_impact` je presny **prime cost-impact v soucasnem path setu**,
nikoli simulace zmenenych cest a zatezi po nove equilibrium assignment.

Pri chybejici ulozene alternativni ceste vznikne pouze navrh
`ACTUAL_PATH_PROBE_REQUIRES_NEW_ASSIGNMENT` na dolozenem ON path window.
Neni vytvarena synteticka alternativni cesta.

## Nejdulezitejsi konfigurace

`R1_15A2_CONFIG_V2_3.json`, klic `supply.sequence`:

- `sequence_cap_schedule`: `[8,4,2,1]`; pokusy z mensich skupin se nesmi ztratit
  zarezanim seznamu na maximalni pocet candidate.
- `max_pairs_per_market`: 64; kontrolovany limit zpracovanych ON/OFF paru,
  nedodelane dvojice se reportuji jako nerevidovana evidence, nic se z nich neodvozuje.
- `max_unique_sequences`: 100000; explicitni pametovy fail-closed limit.
- `max_collateral_volume_to_driver_ratio`: `null` (pouze report). Konkretni
  numericky collateral limit musi byt vybrany a schvaleny z realne R1 baseline;
  lze jej potom aktivovat nastavenim cisla.

Soucasne zustava V2.2: max +/-1 ADDVAL1 na jeden link a pokus, baseline +/-4,
nejvyse 6 linku, max 60 ekvivalentnich sekund na jakoukoli dostupnou
ulozenou cestu, nejmene kladna impedance pri volnem proudu,
**10 s na jednotku ADDVAL1**. Desetinna vychozi hodnota se nezaokrouhluje.

## Spusteni ve Visumu

Rucne z otevrene `.ver` pres `Scripts > Execute Script` spustit:

`R1_15A2_SUPPLY_DEMAND_MASTER_V2_3.py`

Vzdy nejprve pri `apply=false`, s cestami z assignmentu s `Storage of paths
= Save as routes`. Nesmi byt umisten jako operace bezici uvnitr Procedure
Sequence. Hlavni forenzni soubory:

- `00_DSEG_INVENTORY.json`, `00_SUPPLY_ASSIGNMENT_PLAN.json`, `00_PREFLIGHT.json`
- `SUPPLY_PATH_SEQUENCE_DESIGN.json`
- `SUPPLY_ACTUAL_ROUTE_STORE.sqlite` - zdrojovy dukaz konkretne nactenych cest
- `03_PRT_PATHS_ALL.csv`, `04_PRT_PATHLINKS_ALL.csv` - ulozeny PrT export
- `SUPPLY_WRITE_READBACK.json`, `ACCEPTANCE.json`, `ACCEPTED_STATE.json` po APPLY

`R1_15A2_V23_APPLY=1` by bylo povoleno az po realnem PASS. Vychozi konfigurace
zamerne nema vyplnene `supply.assignment_operations` a
`supply.gap_readback.attribute`, proto je automaticky APPLY zatim **BLOKOVAN**.

## Dedicnost souboru

`r1_15a2_supply.py`, `r1_15a2_supply_visum.py`, `r1_15a2_controller_v22.py`
a jejich 124 historickych testu zustaly zachovane. Novy vstup pouziva:
`r1_15a2_sequence_v23.py` a `r1_15a2_supply_visum_v23.py`.
Historicke V2.2 `MANIFEST` a `SHA256SUMS` jsou jen parent provenance, ne
manifest noveho baliku. Pro V2.3 plati nove root manifesty.

## Castecna omezeni

- Nabidka ON/OFF vetvi je podminena existujicimi ulozenymi Visum cestami.
- Diverge/rejoin potrebuje skutecne sdilene uzlove kotvy. Pokud nejsou,
  nabizi se pouze oznaceny ON probe, bez tvrzeni o dolozene OFF alternative.
- Soucasny route-store nedoklada alternativy, ktere Visum neulozil.
- SQLite evidence vyzaduje dostatek diskoveho prostoru; normalizace pouziva
  smerove linkove klice, nikoliv jen LinkNo.
- Zive COM operace a jeji konvergencni readback jeste nebyly overeny.
- Pro LONG b,c stale chybi schvalena komponentni autorita.
- Komponentni SCHOOL ma stale zdedenou V2.1 politiku AUTO; rozhodnuti o
  jejim produkcnim nastaveni je nezavisly otevreny bod.
- Snapshot zdedeny z V2.2 hashuje exportovane VDF/impedance soubory,
  neprokazuje uplne vsechny zive parametry site.
