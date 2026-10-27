# Schvalene epsilon Visum = 0.005 (R1 15A2 V2.3.7 policy alignment)

Uzivatel potvrdil zachovani konvergence epsilon=0.005 v modelu Visum.
Zmena v baliku je pouze kalibracni kontrola `supply.gap_readback.maximum_gap`:
`1e-6` -> `0.005` v `R1_15A2_CONFIG_V2_3_7.json`.

**Nemenime parametr epsilon ani dalsi nastaveni assignmentu v souboru .ver.**
COM adapter bere dosazeny GAP z posledni jednoznacne iterace se stejnou
mnozinou DSeg jako aktivni operace 20 (14 DSegu); nerozhoduje podle samostatnych
predchozich podskupin. Vyssi GAP v dilcich rozsazich zustava zaznamenan v auditu.

Zive historicke cteni 09Q: operace 20, iterace 2, GAP 0.00328696.
Protoze 0.00328696 <= 0.005, historicky vysledek splnuje schvaleny limit.
To ale NEPROKAZUJE jeho cerstvost po zmenach site/poptavky.
Pri novem assignmentu musi byt GAP znovu precten; neplatna ci nejednoznacna
COM evidence nadale zpusobi FAIL.

BEZPECNOST: apply=false, assignment_operations=[], zadne automaticke povoleni
kalibracniho zapisu. MARGINAL_GUARD je samostatny nezavisly problem;
tento hotfix jej neresi ani nezmirnuje.

Pro spusteni pouzij mimo Procedure Sequence stejny master jako V2.3.7:
`R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_7.py`. Nacte stejnojmenny JSON z teto
slozky a proveri jeho hash. Neprepisuj samostatne skript ve starsim baliku.
Pro rychlou rucni aktualizaci existujici V2.3.7 lze pouzit jen tento JSON,
ale drive vygenerovane MANIFEST/SHA256SUMS starsiho baliku pak nebudou platne.
Proto je doporucen cely nove podepsany ZIP.

Oproti V2.3.7 puvodnimu baliku: numericke jadro, 498 mereni, kappa, IDP,
COM adapter a vsechny prahove hodnoty krome GAP zůstávaji beze zmen.
