# R1_15A2 – PROCSEQFIX1, komplexní oprava selhání preflightu (27. 10. 2026)

## Příčina z přiložených živých logů
Dva pokusy skončily na `LIVE_API_PREFLIGHT_FAILED -> PROCSEQ_TYPE_ORDER -> NO_ACTIVE_ASSIGNMENT`.
V pracovním modelu byly aktivní operace TG č. 5 a TD č. 6, ale nebyla aktivní
žádná PrT assignment operace 17–20. Bez přiřazení dopravy nelze kalibrovat
živé síťové intenzity. Nejde o chybu `parent_equivalence` ani SupplyMix.
Schválený společný assignment podle konfigurační autority je operace **20**,
typ **101**, se **14 nativními a externími DSegs**. Ostatní dílčí
assignmenty č. 17–19 nejsou nutné a nesmí se bez důkazu zapínat.

## Oprava
1. Nový modul `r1_15a2_procseq_bootstrap_v24917.py` je volán z hlavního
   spouštěcího řetězce **po důkazu sémantické identity zdroje a `WORKING_START.ver`**
   a **před `LIVE_API_PREFLIGHT`**.
2. Načte přes COM skutečnou posloupnost, ověří typy operací 5/6/16/17–20,
   oprávněný `DSEGSET` op. 20, absenci jiného aktivního assignmentu
   a možnost bezpečně opravit právě chybu `NO_ACTIVE_ASSIGNMENT`.
3. Změní `ACTIVE=1` **pouze u operace 20** v pracovní kopii; provede okamžitý
   readback, znovu ověří `audit_procseq` a přes semantic authority sedm
   otisků stavu. Změnit se smí **jen `operations_hash`**.
4. Zapíše `WORKING_PROCSEQ_READY.ver`, jeho semantic sidecar a
   `PROCSEQ_BOOTSTRAPFIX1.json`; ověří SHA-256 zdrojového `.ver`.
5. Sémantickou identitu připraveného pracovního stavu předá následnému
   kontroléru a při nulovém přijetí také finálnímu checkpointu.
6. Při jakékoli chybě v COM zápisu, readbacku, rozsahu segmentů, uložení či
   ostatních sémantických atributech obnoví původní flagy a skončí bezpečně.
   Není povolen tichý fallback ani vypnutí preflightu.

## Další robustnost
- Opravena návaznost diagnostiky pro režim `SUPPLY_ONLY`, kdy nemusí
  existovat slovník `methodology['demand_continuation']`.
- Opravená izolace testu TDJOINT1 proti dříve instalovaným wrapperům rollbacku.
- Ověřené a rekonsolidované SHA-256 v aktivních manifestech včetně
  původního `GENFIX2_PAYLOAD_MANIFEST.json`; původní hodnoty uchovává
  samostatný audit `PROCSEQFIX1_GENFIX2_INVENTORY_RECONCILIATION.json`.
- Testovací artefakty, které historické testy modifikují, byly před
  sestavením vydání obnovené z původní distribuce.

## Rozsah změn
Změny algoritmů generation, TDJOINT1 a SupplyMix COSTFIX1: **žádné**.
Zdrojové modely `.ver`: **žádné**. Kalibrační/validační profily: **248/0 beze změny**.
Nové jsou produkční modul, jeho regresní test a bezpečné zapojení do hlavního
skriptu. Jeden existující test byl izolován; odvozené manifesty byly přepočteny.

## Ověření
- Hlavní testy: **1 451 PASS / 4 SKIP / 0 FAIL**.
- DIAGFAST: **138 PASS / 0 FAIL**.
- Audit GENFIX2: **18 PASS / 0 FAIL**.
- Celkem **1 607 PASS / 4 SKIP / 0 FAIL** ve třech izolovaných dokončených bězích.
- Společný jednoprocestní pytest všech historických suite není prohlášen
  za úspěšný: po eliminaci kolizí sběru se společné vykonávání zastavilo
  na časovém limitu. Vyhodnocují se oddělené dokončené běhy.
- Všechna aktuální integritní kontrolní pole šesti aktivních manifestů PASS.
- Skutečný PTV Visum 2026 COM ani živý assignment **nelze na tomto
  stroji provést**. První živý běh musí toto potvrdit.

## Předepsané artefakty při startu
`WORKING_START.ver`, `WORKING_COPY_SEMANTIC_IDENTITY.json`,
`PROCSEQ_BOOTSTRAPFIX1.json`, při opravě též
`WORKING_PROCSEQ_READY.ver` a jeho `.semantic.json`, následně
`API_PREFLIGHT/00_PROCSEQ_AUDIT_SUMMARY.json` s `assignment_indices: [20]`.

Ostatní skimy, cíle 11D, koeficienty a váhy nyní neměňte; jde čistě o opravu
selhání před prvním kalibračním cyklem.
