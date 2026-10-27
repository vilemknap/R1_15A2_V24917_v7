# R1 15A2 V2.4.9.5 — GEH20 hysteréze a omezený severity budget

V2.4.9.5 navazuje přímo na V2.4.9.4 a nemění signed Generation, FineCDF TD,
LONG_COMPOSITE, observation-weighted mean GEH, persistent path cache, COM retry
ani semantic restart. Jediná metodická změna je nahrazení diskontinuálního
`max_new_geh20 = 0` jako aktivního acceptance pravidla za omezený trade-off
mechanismus s hysterézí. Historické pole `max_new_geh20` zůstává v konfiguraci
jen kvůli kompatibilitě starších release; při aktivním V2495 policy se nepoužívá.

## Proč změna vznikla

Dosavadní hard guard odmítl kandidáta i při přechodu například GEH
`19.84 -> 20.02`. To je numericky velmi malá změna, ale stará logika ji
vyhodnotila stejně jako podstatné překročení hranice. Takový skokový guard
omezoval možnost redistribuovat chybu mezi profily i v situaci, kdy se globální
kalibrační objective výrazně zlepšovala.

## Autoritativní pravidlo V2.4.9.5

Hranice GEH20 zůstává diagnostická, ale acceptance používá:

- threshold: `20.0`;
- hysteresis low: `19.5`;
- hysteresis high: `20.5`;
- nový GEH30: stále `0` povolených přechodů.

Přechod `before < 20 <= after` je `HYSTERESIS_CROSSING`, pokud zároveň
`before >= 19.5` a `after <= 20.5`. Takový přechod se pouze reportuje a
nespotřebovává material severity budget.

Ostatní nové přechody nad GEH20 jsou `MATERIAL_NEW_GEH20` a podléhají budgetu.

### Generation budget

- max. 3 material new GEH20 profily;
- max. zhoršení jednoho takového profilu: `+2.0 GEH`;
- součet `max(after_GEH - 20, 0)` přes material new GEH20 profily: max. `2.0`;
- nový GEH30: zakázán.

### TD budget

TD je přísnější, protože jeho primární objective je distribuce/IDP a CSD GEH je
síťový guard:

- max. 1 material new GEH20 profil;
- max. zhoršení jednoho takového profilu: `+1.0 GEH`;
- součet `max(after_GEH - 20, 0)`: max. `0.75`;
- nový GEH30: zakázán.

## Co zůstává beze změny

- Generation musí stále zlepšit observation-weighted mean GEH alespoň o 0.1 %;
- TD smí zhoršit aggregate CAL weighted mean GEH nejvýše o 0.5 %;
- protected profile guard `5 / 10 / 30` zůstává aktivní;
- max. 3 `protected -> warn`, max. 0 `protected -> hard`;
- observation authority nesmí změnit role ani observed hodnoty;
- LONG se přijímá jako jeden `LONG_COMPOSITE`;
- `new GEH30` zůstává hard zero-tolerance;
- V2494 same-range transient COM retry a semantic restart jsou zachované.

## Kontinuální penalty

Kontinuální severity-cost funkce není ve V2.4.9.5 implementována. Je výslovně
`DEFERRED_NOT_IMPLEMENTED_IN_V2495`. Tato verze je vědomý mezikrok:
hysteréze + explicitní omezený budget, nikoli změna hlavního objective.

## Offline acceptance

Release musí projít:

- focused testy severity policy a předchozích metodických/COM guardů;
- celý zděděný pytest suite;
- compileall;
- package manifest + SHA verification;
- mechanický verifier hysteréze, Generation budgetu, TD budgetu a GEH30;
- V2494 COM path-export retry regression;
- V2494 semantic restart regression;
- tamper gate a cloud readback.

Reálný PTV Visum COM běh V2.4.9.5 zatím není součástí offline gate.
