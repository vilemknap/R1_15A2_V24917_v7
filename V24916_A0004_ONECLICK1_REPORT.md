# V24916 A0004 ONECLICK1

## Duvod opravy
Predchozi dvoukrokovy workflow byl provozne nejasny: `00_1` byl read-only preflight a zamerne nevytvarel `RUN_*`. Ve Visum Script UI navic neni `print()` spolehlivy stavovy kanal, takze uspesny preflight mohl pusobit jako neaktivni skript.

## Oprava
Novy `00_0_SPUSTIT_V24916_A0004_ONECLICK_ACTIVE_TARGETING.py`:

- okamzite vytvori projektovou bootstrap slozku `R1_15A2_V24916_PERF2C_PROFILE488_A0004_ACTIVE_TARGETING_RUNS`;
- zapise `LATEST_BOOTSTRAP.json` jeste pred live preflightem;
- provede stejny read-only FlowBundle / DIST_KM / semantic preflight;
- pri PASS bez dalsiho kliknuti nainstaluje V24916 active-targeting overlay;
- preda rizeni puvodnimu reviewovanemu A0004 IOFIX1 runtime;
- teprve parent runtime vytvori skutecny `RUN_*` a `runtime_persistent_path_cache_root`;
- pri chybe zapise exception a traceback do bootstrap JSONu.

Metodika, A0004 continuation, PROFILE488, IOFIX1, no-wallclock a acceptance authority se nemeni.
