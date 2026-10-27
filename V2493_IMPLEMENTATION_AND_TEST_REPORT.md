# V2.4.9.3 implementation and test report

## Implementováno

- observation-weighted mean GEH jako hlavní `CSD_CAL` objective;
- zachování GEH² pouze jako diagnostiky a legacy defaultu;
- explicitní zákaz interpretace součtů profilových průjezdů jako unikátních cest;
- global `LONG_COMPOSITE` acceptance z pěti nativních LONG matic;
- zachování společného LONG Δb a c-multiplieru;
- cache `Zone.NO -> COM row key` při startu adaptéru;
- `SetMultiAttValues` apply/rollback s readbackem;
- bounded retry pouze pro call-rejected/retry-later HRESULT;
- oddělený overload fallback;
- bounded transient-only opakování 12D/11D helperu;
- přesný V2.4.9.2 persistent-path-cache predecessor pin.

## Kompatibilita

Starší konfigurace bez nových opt-in polí zachovávají GEH², individuální legacy
LONG behavior a pětimístné `run_helper` rozhraní. V2.4.9.2 release/safety testy
zůstaly součástí plné regrese.

## Testy

- nové metodické a COM adversarial testy: 10 PASS;
- nové V2.4.9.3 release/safety testy: 10 PASS;
- focused release gate: 35 PASS;
- úplná sada: **692 PASS, 0 failures**;
- compileall: PASS.

## Hranice

Reálný PTV Visum COM běh v tomto prostředí nebyl možný. `production_ready` proto
zůstává `false`; dalším gate je bounded live acceptance na uživatelově Visum stroji.
