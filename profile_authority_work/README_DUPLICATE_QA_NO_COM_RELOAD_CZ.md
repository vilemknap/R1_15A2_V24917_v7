# 15A2 V2.3.7 - bezpečný návrhový test po chybě duplicate scope / COM LoadVersion

**Pouze DESIGN ONLY:** `apply=false` je pevně vynucené. Kalibrační změny `ADDVAL1`, zónových parametrů a matic se nezapisují.

## Forenzní důvod změny

Z uzamčeného CSD408 registru vyplývají dvě skupiny profilů se stejným směrovým linkem a neslučitelnými pozorováními:

- `920259` a `920421`: link `(2003608,1000670,1000663)`, 2103 vs 1373 OA/den.
- `920260` a `920420`: link `(2003608,1000663,1000670)`, 2103 vs 1373 OA/den.

Tato pozorování **nejsou přepisována, slučována ani odstraňována**. Ve výlučně diagnostickém `SUPPLY_ADDVAL1` se obě skupiny vyřadí jen jako řídicí profily pro vytvoření návrhu. Nadále patří do všech 498 měření, objektivu a QA. Zaznamenají se také sdílené směrové hrany napříč městskými a CSD profily. Statický audit schválené autority (včetně obou směrů u městských BOTH) našel 37 překrytých směrových hran: 2 skupiny uvnitř CSD a 35 mezi CSD a městskými profily. Případný další APPLY zůstává blokovaný až do samostatného metodického schválení kolizí.

`SUPPLY_DUPLICATE_SCOPE_AUDIT.json` obsahuje všechny konfliktní skupiny, hodnoty a přehled překryvů měření.

Druhá chyba: po vzniku výjimky volal starý `run_calibration` při `apply=false` COM `LoadVersion`, který selhal kvůli 34392 referencovaným síťovým prvkům. Nová DESIGN ONLY větev už automatický `LoadVersion` **nikdy nevolá**. Místo toho porovná nezměněnost úplného snapshotu po **každém bloku, i neúspěšném**. Při driftu nebo nečitelnosti snapshotu ihned končí s pokynem ručně otevřít uložený výchozí `.ver`. Checkpoint `READ_ONLY_GUARD.ver` je pouze archiv pro ruční obnovu.

## Spuštění

1. Starou instanci Visumu po neúspěšném rollbacku zavři; otevři uložený původní `.ver` nebo jeho nezměněnou kopii. **Nepokračuj jen z paměti téže instance**.
2. Rozbal kompletní balík do nové složky vedle `.ver`.
3. Přes Visum Scripts > Execute script file spusť `R1_15A2_DESIGN_ONLY_FIRST_RUN_V2_3_7.py`, **ne** jako Procedure Sequence.
4. Pošli `00_RESULT.json`, `CALIBRATION/DESIGN_SUPPLY_ADDVAL1/SUPPLY_DUPLICATE_SCOPE_AUDIT.json` a `CALIBRATION/DESIGN_SUPPLY_ADDVAL1/SUPPLY_PATH_SEQUENCE_DESIGN.json` (pokud vznikne).

## Omezení

- Nová data modelu nebyla měněna; oprava nebyla ověřena v živém Visumu.
- Příznak konvergence společného přiřazení zůstává epsilon 0.005 (bez zpřísnění).
- `assignment_operations=[]` a obě QA acknowledgement false zůstávají; žádný APPLY není odblokován.
- Snapshot kontroluje vyjmenované kalibrační parametry a matice, ne každý interní zobrazovací stav Visumu; nepředstírá bitovou identitu celého .ver.
- V případě selhání rollbacku z předchozího pokusu použij při dalším startu externě uložený původní soubor `.ver`.
