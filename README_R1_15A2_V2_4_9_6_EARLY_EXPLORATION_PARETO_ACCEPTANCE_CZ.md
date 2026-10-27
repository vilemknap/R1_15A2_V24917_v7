# R1 15A2 V2.4.9.6 — raná explorace a Pareto acceptance

V2.4.9.6 navazuje přímo na V2.4.9.5. Nemění matematiku signed Generation,
FineCDF TD, `LONG_COMPOSITE`, observation-weighted mean GEH, nativní Visum IPF,
persistentní path cache, transientní COM retry ani semantic restart. Mění pouze
acceptance režim v prvních osmi coupled-demand outer cycles, aby se model na
začátku kalibrace mohl přesunout do jiné oblasti parametrického prostoru.

## Důvod změny

Live V2.4.9.4 ukázal, že model je stále v raném stavu: většina CAL profilů má
vysoký GEH. Přesto byly odmítány kandidáty, které:

- bezpečně zlepšily weighted mean GEH o malý, ale skutečný krok;
- zlepšily TD soft-reference objective o několik až desítek procent;
- překročily pouze ostré diskontinuální hranice GEH20/30;
- měly technicky přesnou realizaci `b,c`, validní frozen context a čerstvý
  assignment + 12D/11D.

V rané fázi proto GEH20 a GEH30 nemají fungovat jako binární zdi. Přísné
monotónní guardy se vracejí po skončení explicitní explorace.

## Aktivní stage

`EARLY_EXPLORATION` je aktivní v outer cycles 1–8 včetně. Od cycle 9 se přesně
obnovuje V2.4.9.5: monotónní Generation materiality, 0.5% TD CAL guard a GEH20
hysteresis budget s nulovou tolerancí nového GEH30.

Runtime policy je aktivní pouze tehdy, když controller explicitně připojí:

- `runtime_acceptance_outer_cycle`;
- `runtime_acceptance_scope = GENERATION` nebo `TD`.

Supply blok zůstává mimo ranou exploraci.

## Generation acceptance v cycles 1–8

Generation může být přijata dvěma cestami.

### 1. Libovolné skutečné zlepšení

Jakékoli konečné kladné zlepšení observation-weighted mean GEH větší než
numerická epsilon `1e-12` je materiality-eligible. Původní minimum 0.1 % se v
rané fázi nepoužívá.

### 2. Nemotónní severity trade-off

Generation může dočasně zhoršit weighted mean GEH nejvýše o 2 %, pokud zároveň
prokazatelně zlepší alespoň jednu z následujících severity charakteristik:

- weighted continuous severity nad GEH20 alespoň o 1 %;
- weighted continuous severity nad GEH30 alespoň o 1 %;
- počet CAL profilů nad GEH20 alespoň o 3;
- počet CAL profilů nad GEH30 alespoň o 1.

Tato cesta je explicitně označena
`EARLY_EXPLORATION_NONMONOTONIC_SEVERITY_TRADEOFF` a pouze pro ni smí controller
obejít monotónní shared-objective guard.

## TD acceptance v cycles 1–8

TD kandidát musí:

- zlepšit agregovaný selected TD objective alespoň o 0.25 %;
- nezhoršit žádnou selected ani non-selected komponentu o více než 20 %;
- zhoršit CAL weighted mean GEH nejvýše o 5 %;
- při kladné CAL ceně mít poměr
  `TD relative improvement / CAL relative degradation >= 1.5`;
- zachovat observation authority, frozen context, nativní IPF toleranci a
  čerstvý assignment + 12D/11D.

Tím mohou projít i velké rané distribuční kroky, například přibližně 20% TD
zlepšení za 2–3% CAL cenu, ale nikoli kandidát s malým TD benefitem a vysokou
CAL cenou.

## Severity policy v cycles 1–8

- GEH20: diagnostika + continuous severity penalty, nikoli hard reject;
- GEH30: diagnostika + continuous severity penalty, nikoli hard reject;
- GEH35: warning;
- nový přechod přes GEH40: hard reject;
- zhoršení jednoho profilu o více než 15 GEH: hard reject;
- absolutní GEH nad 60: hard reject;
- profil s `before GEH < 5` nesmí skončit na `after GEH >= 20`;
- změna observation setu, observed hodnot nebo CAL/VALID role: hard reject.

Continuous severity je reportována jako vážený průměr
`max(GEH-threshold, 0)^2` pro threshold 20 a 30.

## Current exploratory versus best-so-far

Každý přijatý stav zůstává aktivním `CURRENT_EXPLORATORY_STATE`, aby bylo možné
překonat lokální sedlo. Současně controller udržuje samostatný immutable
`BEST_SO_FAR` checkpoint podle fixed-reference shared objective.

Výstupy:

- `current_exploratory_checkpoint` v `RUN_STATUS.json`;
- `BEST_SO_FAR_CHECKPOINT.json`;
- samostatný `CHECKPOINTS/BEST_SO_FAR_*.ver`;
- semantic restart sidecar k best checkpointu.

Rotace běžných accepted checkpointů proto nikdy nesmaže nejlepší dosud nalezený
stav.

## Co zůstává beze změny

- weighted mean GEH je hlavní CSD metriku;
- GEH² je pouze diagnostika/legacy kompatibilita;
- LONG se přijímá jako jediný `LONG_COMPOSITE` při společném Δb a c-multiplieru;
- Generation zůstává signed a P/A-balanced;
- nativní IPF tolerance se neuvolňuje;
- žádný direct OD matrix write;
- path export používá same-range bounded transient COM retry;
- restart authority je semantic model state, ne cross-run raw `.ver` SHA;
- rollback/readback zůstává fail-closed;
- po cycle 8 se přesně obnoví V2.4.9.5 acceptance.

## Offline gate

Release musí projít focused testy, celý zděděný pytest suite, compileall,
manifest/SHA verifier, mechanickou reprodukci obou early acceptance cest,
TD benefit/cost testy, cycle-9 fallback, best-so-far checkpoint test, inherited
COM/restart regresi, tamper gate a cloud readback.

Offline PASS není tvrzením o reálném Visum acceptance. První bounded live běh
musí být spuštěn z uživatelem zvoleného accepted checkpointu.
