# R1 15A2 V2.4.9.13 — Supply Route-Choice Readiness

## Účel release

V2.4.9.13 navazuje přímo na ověřenou V2.4.9.12 COMPLETE R2. Nemění matematiku Trip Generation ani FineCDF Trip Distribution. Uzavírá route-choice fázi, která se má spustit až po dosažení joint TG/TD fixed pointu.

Hlavní změny:

1. samostatná baseline-relative acceptance policy pro `SUPPLY_ADDVAL1`;
2. uvolněné, ale stále bounded ADDVAL/route-choice limity;
3. skutečný branch-local backtracking stejné trasy `80 → 40 → 20 → 10 → 5 s`;
4. samostatný supply-cycle clock — dlouhá demand fáze nespotřebuje supply exploration budget;
5. fail-closed handoff z ověřeného `DEMAND_CONVERGED.json`;
6. supply-only launcher, který nepočítá znovu TG/TD a ověří přesnou shodu otevřeného modelu s converged demand stavem;
7. demand matrix / Generation / TD hashe musí během supply zůstat přesně zmrazené.

## Co V24913 kalibruje

Aktivním route-choice parametrem je pouze **LINK `ADDVAL1`**.

Autoritativní převod je zachovaný z Visumu:

```text
1 ADDVAL1 = 10 generalized seconds
0.5 ADDVAL1 = 5 generalized seconds
```

VDF, kapacity, `V0PrT`, turn ADDVAL, connector ADDVAL a node impedance jsou v této release frozen. Z countů samotných je nelze bezpečně současně identifikovat s LINK ADDVAL1.

## Nové route-choice limity

| Parametr | V24912 | V24913 |
|---|---:|---:|
| ADDVAL lattice | 1.0 = 10 s | **0.5 = 5 s** |
| max. jednotlivý krok | 4 = 40 s | **8 = 80 s** |
| backtracking | 40/20/10 s | **80/40/20/10/5 s** |
| max. kumulativní změna od run-start | ±4 = ±40 s | **±15 = ±150 s** |
| absolutní ADDVAL rozsah | −50…+50 | **−100…+100** |
| max. path-bundle dopad | 120 s | **360 s** |
| max. změněných linků | 12 | **30** |
| max. candidate proposals | 10 | **40** |
| max. live supply trials/cycle | 6 | **40** |
| max. driver profilů | 24 | **80** |
| min. driver GEH | 10 | **5** |
| min. absolutní residual | 300 voz. | **100 voz.** |
| min. attribution coverage | 99.5 % | **90 %** |
| min. path coverage | 98 % | **90 %** |
| min. path-volume coverage | 99.5 % | **95 %** |

Uvolnění není bezpodmínečné. Každý kandidát stále musí projít fresh Visum assignmentem, fresh 12D/11D, observation-authority checkem, demand freeze, bounds/readback, rollback/reapply a shared-objective monotonicity.

## Supply acceptance contract

Supply kandidát musí současně:

- skutečně snížit CAL observation-weighted mean GEH;
- zlepšit fixed-reference shared objective více než numerická epsilon;
- nezměnit observation authority;
- zachovat všechny demand hashe;
- nezničit profil původně pod GEH 5 až nad GEH 20;
- nepřekročit jednotlivý GEH nárůst 20;
- nezhoršit existující profil nad GEH 60 o více než 15;
- dodržet severity20 budget +20 %;
- dodržet severity30 budget +25 %;
- dodržet net GEH40 budget +20 profilů;
- dodržet IDP mean degradation +2 % a component degradation +8 %.

GEH20/30/40 jsou tedy baseline-relative budgety, nikoli staré binární zdi. Technické, frozen-context a rollback guardy zůstávají hard.

## Dvě možnosti spuštění

### A. Doporučená: přepnout na V24913 ještě před supply

1. cooperative zastavit V24912 na verified boundary;
2. otevřít její `LATEST_ACCEPTED_CHECKPOINT`;
3. spustit `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_13.py`;
4. V24913 pokračuje TG/TD z aktuálního accepted modelového stavu;
5. po joint convergence sama použije novou supply policy.

Toto je nejbezpečnější varianta, protože již běžící Python proces V24912 nelze spolehlivě hot-patchovat.

### B. Supply-only z už converged demand stavu

Použij:

```text
R1_15A2_SUPPLY_FROM_CONVERGED_DEMAND_V2_4_9_13.py
```

Launcher vyžaduje:

- platný `DEMAND_CONVERGED.json`;
- `stationary_cycle_streak >= 2`;
- správný convergence criterion;
- otevřený `.ver` se stejným `state_hash` jako convergence authority.

Pokud cokoli nesedí, supply se nespustí.

## Co tato release netvrdí

- Strategic `TURN_SHARE` a `CORDON_PAIR_SHARE` nejsou v tomto konkrétním balíku zapojeny do live V24913 objective, protože jejich autoritativní datové soubory nejsou součástí V24912 runtime package.
- VDF/capacity/V0 tuning není povolen.
- Turn a connector ADDVAL nejsou actuatable.
- Real-Visum supply běh ještě nebyl proveden.

Stav:

```text
real_visum_supply_tested = false
production_ready = false
```
