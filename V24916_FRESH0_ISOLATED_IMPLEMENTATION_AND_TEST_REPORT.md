# V24916 PROFILE488 FRESH0 ISOLATED ACTIVE TARGETING — IOFIX3 / PATHFIX3

## Výsledek

Release: `R1_15A2_V24916_PERF2C_PROFILE488_FRESH0_ISOLATED_ACTIVE_TARGETING_IOFIX3_PATHFIX3_CACHE_DISABLED_20261022`

Tato verze začíná novou kalibrační lineage z čistého PROFILE488 baseline (`accepted_count=0`, `outer_cycle=1`) a může běžet paralelně s V24915 v samostatném procesu Visumu. Persistentní path cache je úplně vypnutá; první path basis se vždy nově enumeruje z live Visumu a používá se pouze uvnitř tohoto běhu.

## Oprava délky cest

Do V24916 byla přenesena obecná IOFIX3/PATHFIX3 vrstva z dodané V24915:

- krátký samostatný run-root `R1_15A2_V16_RUNS`;
- samostatný lock `.R1_15A2_V16.lock`;
- krátké opaque temp názvy `.r1*_0123456789abcdef.tmp`;
- Win32 extended-length cesty na Python filesystem boundary;
- bounded retry + fail-closed pro kritické JSON/CSV/text/copy/replace/hash operace;
- fail-open long-path-safe performance telemetry;
- long-path-safe runtime JSON/CSV, PERF1 rollback proof, geometry progress, helper evidence, BEST_SO_FAR a dynamický FineCDF JSON/CSV/NPZ;
- V24916-specific FlowBundle evidence, coefficient ledger, DIST_KM authority a live-authority publication používají stejnou hardened vrstvu;
- `PATH_LENGTH_PREFLIGHT.json` vzniká po vytvoření `RUN_*`, ale před model-side mutation.

Pro projektovou cestu `C:\Users\vilem_knap\Documents\VISUM\v45\2022` je projektované maximum 234 znaků, pod interním limitem 240.

## Opravené integrační rozhraní

Active adapter už nehledá natvrdo A0004 authority v package root. Launcher předává přesnou run-specific `runtime_v24916_live_authority_path`, takže FRESH0 preflight a vlastní adapter používají stejnou zapečetěnou autoritu.

## Izolace od paralelní V24915

- V24916 používá `R1_15A2_V16_RUNS`;
- V24916 používá `.R1_15A2_V16.lock`;
- V24915 RUNS ani lock se nečtou ani nepřepisují;
- `%LOCALAPPDATA%` V248 cache se nečte;
- `performance.persistent_path_cache.enabled = false`;
- legacy import i predecessor restore jsou vypnuté;
- cache sentinel `PC_OFF` musí zůstat nepřítomný.

## Targeting a metodika

Aktivní zůstává Generation FlowBundle targeting, TD component mask a DIST_KM kontext. FlowBundle/skim pouze zužují search-space. Acceptance nadále provádí fresh Visum assignment + live 12D PROFILE488 + live 11D. Kalibrační matematika, candidate order, assignment a acceptance se nezměnily.

## Ověření

- focused PATHFIX3/V24916: 79 passed;
- kompletní regrese: 993 passed, 4 skipped, 0 failed;
- compileall: PASS;
- V24916 runtime manifest: 45/45 PASS;
- parent V24915 PERF2 deployment: PASS;
- PERF2C overlay: PASS;
- Fresh100 runtime/config preflight: PASS;
- PROFILE488: 488/488/0 PASS;
- projected path budget: 234/240 PASS;
- reviewed parent launcher zůstal byte-identický; krátký parent je aditivní V24916 copy.

## Live hranice

`real_visum_tested=false`, `production_ready=false`. První spuštění v live Visumu je acceptance gate tohoto konkrétního release.
