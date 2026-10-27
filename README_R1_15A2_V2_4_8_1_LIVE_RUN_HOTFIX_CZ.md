# R1 15A2 V2.4.8.1 LIVE RUN HOTFIX

Tato patch verze navazuje na V2.4.8 persistent path cache a opravuje dva problémy odhalené prvním skutečným V2.4.7 během dne 2026-10-16.

## Opravené problémy

1. Kladná intrazonální OD relace (v živém běhu `NATIVE_CW:7:7`) už není považována za chybějící síťovou cestu. Diagonální OD nemá network-link geometrii a je z path-support gate i path incidence vyloučena. Kladná chybějící OFF-DIAGONÁLNÍ relace nadále vynutí novou enumeraci.
2. Windows `PermissionError / WinError 32` při odstraňování již nahrazeného lokálního SQLite store po úspěšné nové enumeraci už není fatální kalibrační chyba. Cleanup se označí jako odložený. Modelové acceptance gate se tím nemění.

## Reuse V2.4.7 cache

V2.4.8.1 zachovává persistentní cache manager V2.4.8. Při startu prohledá také `R1_15A2_V247_RUNS`. Dokončený V2.4.7 `TWO_MODE_PATH_STORE.sqlite` smí být importován pouze pokud:

- metadata mají přesně stejný origin state hash,
- store je strukturálně kompletní a incidence-ready,
- SQLite quick check a FK kontrola projdou,
- všech 498 profilů projde live path-flow parity gate,
- importer vytvoří novou immutable kopii ve V2.4.8 persistent cache.

Legacy store se nikdy nepřepisuje.

## Doporučené spuštění po tomto konkrétním V2.4.7 běhu

Nejbezpečnější je otevřít poslední accepted checkpoint z neúspěšného runu:

`R1_15A2_V247_RUNS/RUN_20261016_162053_068586/CALIBRATION/CHECKPOINTS/ACCEPTED_B_0000_61129884aaf7.ver`

Potom spustit:

`R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_1.py`

přes `Scripts -> Execute script file`.

Pokud exact-state a parity gate projdou, očekáváme `matched_by = LEGACY_EXACT_STATE_IMPORT` a nulovou novou počáteční COM enumeraci. Pokud neprojdou, skript fail-closed provede normální novou enumeraci.

## Ověření

- focused regression: 30/30 PASS
- complete suite: 584/584 PASS
- compileall: PASS
- actual Windows/Visum COM rerun: ještě neproveden

Viz `V247_REAL_RUN_POSTMORTEM.json` a `V247_REAL_RUN_POSTMORTEM.md`.
