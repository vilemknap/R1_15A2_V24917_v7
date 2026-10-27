# R1 15A2 V2.4.8.6 — sjednocená oprava

## Proč vznikla nová verze

Dvě paralelně vyvinuté V2.4.8.5 řešily různé reálné chyby a nebylo bezpečné jednu z nich označit za nadřazenou:

- větev `STABLE_PROJECT_ROOT` opravila vnořování nových runů pod checkpointy starších runů;
- větev `GENERATION_SATURATION_HOTFIX` opravila návrh změn, když přímý Generation aktuátor už leží na hard boundu.

V2.4.8.6 vznikla merge postupem, nikoli prostým překopírováním jednoho ZIPu přes druhý. Základem je root větev; numerický `r1_15a2_multiblock.py` pochází ze saturation větve a byl doplněn o obdobnou ochranu preserved-zero aktuátorů.

## Run-root kontrakt

Při otevření checkpointu z jednoho nebo více vnořených `R1_15A2_*_RUNS` stromů se vybere rodič nejvzdálenějšího legitimního run rootu. Nový run musí ležet zde:

```text
<PROJECT_BASE>\R1_15A2_V2486_RUNS\RUN_...
```

Po vytvoření se kontroluje, že neleží pod žádným detekovaným předchozím run rootem.

## Generation bound-constrained projection

Před zápisem trialu se u přímých aktuátorů vyhodnotí skutečně dosažitelný log-efekt podle aktuální hodnoty, minima, maxima, zero policy a seed policy. Nedosažitelná část se odstraní ještě před P/A gate. Větší implementovatelná P/A strana stejné family se pouze utlumí; její prostorový pattern zůstává zachovaný.

Fail-closed zůstává:

- opačné znaménko P/A stran;
- nečitelný parametr;
- nevyřešený joint aktuátor;
- překročení generation effect nebo P/A gate po přesném mapování;
- odmítnutí fresh assignment / 12D / 11D.

## Cache kompatibilita

Read-only compatibility bridge je explicitně hashově omezen na V2.4.8.1–V2.4.8.4 a obě divergentní V2.4.8.5 větve. Ostatní cache kontrakty se nepovolují.

## Hranice důkazu

Offline testy, čisté rozbalení, manifest, tamper gate a replay dodané V2484 evidence mohou prokázat integraci kódu. Nemohou nahradit reálný PTV Visum COM běh.
