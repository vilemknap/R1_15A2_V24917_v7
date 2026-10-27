# V2.3.7 - kandidát COM adapteru GAP na základě živého 09Q

Tato verze doplňuje čtení z `Visum.Workbench.Lists.CreatePrTAssQualityList` (sloupce `DSEGCODE`, `ITERATION`, `GAP`) místo nesprávného univerzálního `Visum.Net.AttValue("GAP")`.

Ověření čte přesně všechny řádky ve stránkách, vyžaduje identickou množinu DSeg jako aktivní PrT assignment na pozici 20, a právě jeden řádek s nejvyšší iterací. Zachovává se výpis výsledků dalších DSeg rozsahů. Historický výstup 09Q sám o sobě nedokazuje čerstvost assignmentu.

**PRODUKČNÍ APPLY ZŮSTÁVÁ ZAKÁZANÝ.** `apply=false`, `assignment_operations=[]`, `maximum_gap=1e-6`. Žádný automatický přepis na 0.005 nebo jinou neodsouhlasenou toleranci. Ani jediná hodnota schválených matic, κ, IDP, 498 měření nebo generačních formulí se nemění.

Použij master `R1_15A2_SUPPLY_DEMAND_MASTER_V2_3_7.py` mimo Procedure Sequence; preflight V2.3.6 zůstává beze změny a již živě prošel 129 kontrolami. V2.3.7 zatím není otestovaná v živém Visumu. Po případném schválení op. 17-20 a metodické tolerance bude třeba samostatně posoudit freshness a marginální bezpečnost.

**Samostatná chyba `MARGINAL_PROBE_REJECTED_BACKOFF` se touto úpravou neřeší.** K opravě je třeba konkrétní kód daného guardu a jeho soubor `MARGINAL_GUARD.csv`, který v dodaném balíku 15A2 V2.3.6 není.
