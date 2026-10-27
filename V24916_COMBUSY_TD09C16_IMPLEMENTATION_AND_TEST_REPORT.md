# V24916 PROFILE488FIX1 — integrace COMBUSY + TD09C16

## Výchozí stav

Výchozí balík byl:

`R1_15A2_V24916_PERF2C_FRESH0_DYNAMICSKIM1_FASTCAL1_PROFILE488FIX1_20261023`

Byly porovnány tři dodané donor balíky:

1. `R1_15A2_PROFILE488_AGGRESSIVE_TGTD_V1_FIX1_IOFIX4_BASE_20261022`
2. `R1_15A2_AGGRESSIVE_V1_FIX1_COMBUSY_RETRY_HOTFIX1_FULL_20261023`
3. `R1_15A2_AGGRESSIVE_FIX1_COMBUSY_TD09C16_HOTFIX2_FULL_20261023`

HOTFIX1 přidával nad agresivní základ přesně pět souborů: nový entrypoint,
COM-busy runtime overlay, test a dva informační artefakty. HOTFIX2 přidával
přesně dalších pět souborů: nový entrypoint, TD09C 16/17 overlay, test a dva
informační artefakty. Žádný parent soubor v těchto dvou hotfixech nebyl změněn.

## Rozhodnutí k IOFIX4

IOFIX4 nebyl slepě kopírován přes V24916. Aktuální
`r1_15a2_runtime_io_hotfix_profile488.py` ve V24916 již obsahuje stejnou
long-path/short-temp/atomic-publication vrstvu a navíc chrání V24916-specific
coefficient ledger, demand evidence a live-authority writers. Současný
`r1_15a2_perf_telemetry_failopen_hotfix_profile488.py` je funkčně shodný s donor
telemetry kompatibilitou, pouze používá novější V24916 I/O modul. Přepsání donor
IOFIX4 by proto bylo downgrade.

## Přenesená oprava 1 — COMBUSY snapshot retry

Nový modul:

`r1_15a2_com_busy_snapshot_hotfix_v24916.py`

Aktivuje se v hlavním one-click launcheru před live preflightem. Bounded retry
se vztahuje pouze na read-only vstupy:

- `r1_15a2_supply_visum.VisumAdapter.read_links`,
- `r1_15a2_supply_visum.VisumAdapter.snapshot`,
- `r1_15a2_single_pass_snapshot_v24915p2c.single_pass_exact_snapshot`,
- alias importovaný v `r1_15a2_trial_adapter_v24915p2c`.

Retry používá existující `com_call_with_retry` a pouze transientní HRESULT
`RPC_E_CALL_REJECTED` a `RPC_E_SERVERCALL_RETRYLATER`. Výchozí scope je maximálně
64 pokusů / 75 sekund na jeden vnější read-only snapshot. Vnořené `snapshot ->
read_links` nesmí násobit retry budget. Nejsou přidány žádné Visum writes,
LoadVersion, procedure execution ani fallback při nevalidních datech.

## Přenesená oprava 2 — TD09C 16/17 kompatibilita

Nový modul:

`r1_15a2_td09c_16or17_hotfix_v24916.py`

Donor oprava původně patchovala historický bridge V242. V této integraci byla
převedena přímo na aktivní `r1_15a2_finecdf_bridge_v24916`, včetně zachování:

- `outer_adapter`,
- `dynamic_skim_enabled`,
- `dynamic_skim_epoch`,
- `dynamic_eval_index`,
- fresh assignment + šest dynamických DIS skimů.

Povoleny jsou výhradně dvě přesné varianty jednoho aktivního TD operation type
46:

- `FULL17`,
- `NATIVE16_FOREIGN_SEPARATE` — 16 native strata bez `4_FOREIGN`.

Jakákoli chybějící SCHOOL komponenta, extra komponenta, duplicita nebo více
odpovídajících TD operací je fail-closed. `4_FOREIGN` je vyřazen z inner native
TD, ale jeho A/B/C musí zůstat samostatně čitelné a matrix 9116 zůstává v
protected hash guardu. Zdrojový rozsah DSTRATSET se po každém inner běhu obnoví
přesně do původního 16- nebo 17-prvkového stavu.

## Zapojení do launcheru

Hlavní skript zůstává:

`00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py`

Pořadí před live preflightem:

1. COM retry 4→5 compatibility,
2. IOFIX3/PATHFIX3,
3. fail-open telemetry,
4. COMBUSY snapshot retry,
5. TD09C 16/17 runtime patch,
6. read-only TD09C source preflight,
7. běžný V24916 live authority preflight,
8. calibration handoff.

## Nezměněné kontrakty

- 488 PROFILE488 řádků, všechny CALIBRATION;
- FlowBundle targeting;
- dynamické assignment skimy;
- FASTCAL1 TG/TD parametry;
- native IPF tolerance;
- FineCDF objective a acceptance;
- assignment metoda;
- žádné přímé OD matrix writes;
- fresh cycle 1 / accepted_count 0;
- persistent cross-run path cache vypnutá.

## Ověření

V24916 focused suite:

- **111 passed**
- **0 failed**

Celá historická sada byla dokončena v šesti deterministických oddílech, protože
monolitický proces dosáhl limitu testovacího harnessu bez zjištěné chyby:

- oddíl 1: 177 passed,
- oddíl 2: 185 passed, 1 skipped,
- oddíl 3: 190 passed, 1 skipped,
- oddíl 4: 140 passed,
- oddíl 5: 212 passed,
- oddíl 6: 129 passed, 2 skipped.

Celkem:

- **1033 passed**
- **4 skipped**
- **0 failed**

Dále:

- `compileall`: PASS,
- V24916 runtime manifest: **50/50 PASS**,
- COMBUSY fault injection: transient retry / non-transient fail-fast / PERF2C
  exact parity PASS,
- TD09C: native16 / full17 / unauthorized scopes / frozen FOREIGN / read-only
  preflight PASS.

Reálný Windows/PTV Visum běh nebyl v tomto prostředí proveden. Integrace je
staticky, synteticky a regresně ověřena; definitivní live potvrzení vznikne až z
následujícího spuštění v otevřené instanci Visumu.
