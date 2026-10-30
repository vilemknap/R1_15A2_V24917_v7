# R1_15A2 V24917: Generation SCHOOL FP link / silent debug, 30. 10. 2026

## Diagnóza z dodaných souborů (nikoliv živý rerun ve Visumu)

Přiložený Generation report `GENERATION_BLOCK_RESULT(20261030-000022).json`
potvrzuje tři kompletní assignmentem vyhodnocené a odmítnuté kandidáty
(výchozí vážené GEH 51.5887673352 a model/obs ratio 0.391242445):

| Trial | Scale | GEH po vyhodnocení | Výsledek |
|---|---:|---:|---|
| 1 | 0.750000 | 44.110825764 | REJECTED: new severe GEH, protected guard, MOBILITY2 |
| 2 | 0.538158 | 46.524209618 | REJECTED: pouze MOBILITY2 |
| 3 | 0.511250 | 46.808145941 | REJECTED: pouze MOBILITY2 |

V každém trialu je `mobility_guard_live.families.WORK.passes=true`
i `SERVICE.passes=true`, ale
`mobilityzone1.violations=575` a všechna mají:
`family=SCHOOL`,
`FP_REFERENCE_OR_FORMULA_CHANGED:FP_5_SCHOOL`.
Ve všech 575 reportovaných školních zónách je
`production/reference_production == 1.0`, a to u všech tří trialů.
Tedy raw FP_5_SCHOOL zůstává stejný, zatímco guard kontroluje
proporční vazbu na kandidátní koeficient ADD_PROD_SCH.

**Není zatím nezávisle potvrzena skutečná formula dependency**
`FP_5_SCHOOL <-> ADD_PROD_SCH` v otevřeném `.ver`. Je také možné,
že koeficient je připojen až v jiné vrstvě nativního TG. Proto tuto
kontrolu NEMĚNÍME na volnější a neprohlašujeme SCHOOL za validní.

Rollback následného odmítnutí prošel: `snapshot_equal=true`,
`diagnostic_equal=true`, `genfix2_parent_proof.passes=true`.
Toto není pád COM ani LONGMASK; Generation nenašla schválitelný
kandidát během tří nakonfigurovaných pokusů.

## Oprava: source-unverified SCHOOL generation freeze

V `r1_15a2_mobility_zone_v24917.py` je bezpečnostní
`SCHOOL_FP_LINK_POLICY=FROZEN_UNTIL_NATIVE_FP_LINK_VERIFIED`.
U skutečného živého běhu `capture()` neuděluje neověřenou certifikaci
formula dependency. `guard_ls()` proto:
1. vyprázdní pouze návrhy `ADD_PROD_SCH` a `ADD_ATT_SCH`,
2. nepustí ani nulové SCHOOL COM write rows do `rows_at_scale()`,
3. přepočte předpověď modelu z reálně zbylých W/S a ostatních
   verifikovaných aktuátorů,
4. nastaví `school_generation_search_complete=false` a
   `school_generation_status=FROZEN_PENDING_NATIVE_FORMULA_PROOF`,
5. ponechá původní `check_live()`, přísné zonální mobility bounds
   a LIVE acceptance beze změny.

Při prokázané změně nativních vzorců je nutné doplnit pozitivní,
source-bound důkaz propojení; testovací fixture může pro své
syntetické přímo proporční FP soubory použít explicitní certifikaci.
**SCHOOL TD není tímto patchem vypnuta. LONG generation nadále
zůstává zamražená z jejího samostatného neověřeného count-response.**
Tato oprava prioritizuje průchod W/S Generation, nikoli deklaraci
kompletně kalibrované školy.

## TD výsledky z přiložených artefaktů

`TD_FINECDF_BLOCK_RESULT(20261030-000031).json` hlásí
`ACCEPTED_FINECDF_TD`, GAP `0.00056377` a změnu parametru
`WORK_E_C` (`c=-0.5119013928` -> `-0.5426154764`).
Globální count GEH se v TD realizaci zhoršilo
`50.0577688564 -> 50.6462251404` (cca 1.18 %), ale vybraný
`WORK_E_C` IDP objective se zlepšil z `0.7004317746`
na `0.5890413404`, a to v rámci TD acceptance.
Jde o **přijatý trade-off**, nikoliv chybu v programu.

`TD_TARGET_PLAN(2).json`: `GLOBAL_IDP_FALLBACK` kvůli
`PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:NATIVE_CS_NOT:616:676`.
Fallback požádal o globální 11D a TD byla přesto přijata.
Targeted path evidence pro tento nový OD pár nebyla v epoch validní,
takže cílený IDP výběr správně neprohlásil za verifikovaný.
`inner.search_complete=false` a
`incomplete_search_reasons=[LONG_SCHOOL_DESIGN_UNVERIFIED]`.
Nejde o doklad globální stacionarity.

Přiložené soubory nejsou spárované jednoznačným společným run-id,
proto nelze automaticky předpokládat, že všechna čísla pocházejí ze
stejného kontinuálního kalibračního běhu.

## Zrychlené další ladění

Silent helper přidal do každého
`R1_15A2_SILENT_DEBUG/SILENT_LATEST_DEBUG.zip` malý
`SILENT_CALIBRATION_SUMMARY.json`, který z velkých
`GENERATION_BLOCK_RESULT*.json`, `TD_FINECDF_BLOCK_RESULT*.json`,
`TD_TARGET_PLAN*.json` a rollbacku ukládá statusy, GEH před/po,
počty důvodů zamítnutí i 5 ukázkových zón. Originální velké soubory
nebyly přepsány; na disk se zapisuje jen dodatečné diagnostické shrnutí.

## Co zůstává neověřeno
- Skutečný živý běh této změny v PTV Visum 2026.
- Native TG závislost `FP_5_SCHOOL` a `ADD_PROD_SCH`;
  před jejím prokázáním nelze SCHOOL Generation povolit.
- Vlastní počet kalibračních cyklů, skutečná konvergence a další
  přijaté stavy za posledním nahraným TD reportem.
- Případná optimální strategie re-enumerace pro nové pozitivní OD
  `NATIVE_CS_NOT:616:676` (není součástí tohoto safety fixu).
