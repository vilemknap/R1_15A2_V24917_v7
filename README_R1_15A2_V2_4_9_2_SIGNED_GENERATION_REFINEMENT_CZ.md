# R1 15A2 V2.4.9.2 — Signed Generation Refinement

V2.4.9.2 navazuje na V2.4.9.0. Zachovává TD soft-reference, nativní IPF toleranci,
persistentní path cache, rollback a všechny živé acceptance gates. Mění pouze
Generation návrh tak, aby mohl jednu zónu zvýšit a jinou současně snížit.

## Proč změna vznikla

`POSITIVE_ONLY` uměl opravovat hlavně podhodnocené zóny. Při pozdějším ladění,
kdy bude celková matice již přibližně „dofouknutá“, potřebujeme především
prostorovou redistribuci. Bez záporných zonálních korekcí by se část chyby P/A
musela nesprávně kompenzovat přes distribuční parametry `b,c`.

## Nová parametrizace

Pro každou rodinu WORK/SERVICE a roli PROD/ATT se návrh rozkládá na:

1. společný family-total log krok;
2. zonální signed log korekci s nulovou nelineární změnou celkového marginu.

Centrování splňuje:

`sum_i base_margin_i * (exp(zone_log_effect_i) - 1) = 0`.

Produkce a atrakce dostávají společný konzervativní family-total efekt. Když
jejich agregované návrhy míří opačnými směry, globální efekt se odstraní a
zůstane pouze prostorový pattern.

## Rozsahy koeficientů

Běžné `ADD_PROD_W/S`, `ADD_ATT_W/S` a `ADD_SALARY`:

- hard envelope: 0.5 až 2.0;
- soft AMDY-like pásmo: 0.8 až 1.25;
- pohyb ven ze soft pásma je tlumen, pohyb zpět dovnitř nikoli;
- existující hodnota mimo hard envelope není násilně skokově oříznuta, ale smí
  se pohybovat pouze dovnitř.

`ZAHR_*` se neomezuje raw hodnotou 0–2. Jeho hard rozsah je 0.5–2.0 násobek
hodnoty uložené na začátku běhu; soft pásmo je 0.7–1.3 násobek reference.

Nuly zůstávají pod původním `preserve_zero` kontraktem.

## Postupné zaměření na distribuci

- cykly 1–2 `SIGNED_EXPLORE`: zonální krok ±6 %, family total ±3 %;
- cykly 3–4 `SIGNED_REFINE`: zonální krok ±4 %, family total ±1.5 %;
- cykly 5–12 `DISTRIBUTION_FOCUS`: zonální krok ±2 %, family total ±0.5 %.

Pozdější cykly tedy dovolují malé prostorové korekce, ale omezují další globální
nafukování demandu a dávají větší prostor TD refinementu.

## Co zůstává hard

Každý kandidát stále vyžaduje čerstvý Visum výpočet, assignment, 12D/11D,
CAL GEH² ochranu, protected-profile gate, P/A konzistenci, rollback a
reprodukovatelné přijetí. Průzkumové TD křivky zůstávají měkkou referencí podle
V2.4.9.0, nikoliv exact-fit cílem.

## Evidence

Na začátku běhu vznikne neměnná reference koeficientů:

`00_GENERATION_COEFFICIENT_REFERENCE.json`.

Každý Generation trial zapisuje:

`GENERATION_SIGNED_REFINEMENT_AUDIT.json`.
