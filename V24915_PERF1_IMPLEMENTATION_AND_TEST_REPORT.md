# V24915 PERF1 — implementace exact-safe zrychlení

## Výsledek

Stav: `V24915_PERF1_OFFLINE_VERIFIED_READY_FOR_LIVE_BENCHMARK`

Nová větev je čistě aditivní potomek ověřeného V24915. Původní parent strom nebyl změněn ani o jeden soubor: `723` parent souborů zůstává byte-for-byte zachováno; přibylo `13` implementačních a testovacích souborů.

## Implementované optimalizace

1. **Phase-specific Procedure Sequence**
   - GENERATION: zachová původní aktivní prefix po schválený PrT assignment a vynechá pouze explicitně ověřenou post-assignment display operaci 21.
   - TD: startuje prvním aktivním TD krokem a pokračuje po schválený assignment 20; Trip Generation a display-only operace se vynechají jen při přesné shodě živého inventáře.
   - SUPPLY: zachovává assignment-only režim a aktivní strukturální groups.
   - Jakákoli neznámá operace, neshoda typu/textu nebo chybějící autorita automaticky vrací původní plnou Procedure Sequence.

2. **Delta-only přepínání ACTIVE s přesnou obnovou**
   - zapisují se pouze skutečně měněné příznaky;
   - každý zápis má COM readback;
   - původní stav celé sekvence se po běhu znovu načte a přesně porovná;
   - i když první zápis uspěje a jeho readback selže, operace je zahrnuta do povinné obnovy.

3. **Levnější ověření rollbacku**
   - po restore + recompute musí přesně souhlasit celý semantic snapshot;
   - poté se jedním bulk profilem ověří všech 498 profilů přes 12 osobních DSegů, včetně směrových a BOTH profilů;
   - teprve po tomto důkazu se může znovu použít již vypočtený baseline 12D/11D payload;
   - při chybě, neúplnosti nebo jediné odchylce se spustí původní plné 12D+11D diagnostiky.

4. **Eliminace přesně duplicitních efektivních kandidátů**
   - platí pouze pro kandidáty ze stejného immutable accepted parentu;
   - identita je hash skutečných parameter writes, nikoli jen jméno/scale;
   - první výskyt se vyhodnotí v původním pořadí, další přesné duplicity se pouze zaznamenají a nepřepočítají.

## Co se nezměnilo

- kandidátní matematika ani pořadí unikátních kandidátů;
- native IPF tolerance;
- assignment metoda a gap gate;
- 12D/11D acceptance;
- restart A0009: accepted count 9, další outer cycle 6;
- supply policy, persistent path-cache semantics a COM-busy oprava V24915;
- žádné přímé OD writes, žádný LoadVersion rollback, žádná candidate parallelism.

## Testy

- focused PERF1: **10 passed**;
- úplná inherited + PERF1 sada: **793 passed, 4 skipped, 0 failed**;
- `compileall`: **PASS**;
- parent V24915 runtime/deployment manifest: **PASS**;
- child config, contract a runtime manifest: **PASS**.

## Pravdivá hranice

Výkon v živém Visumu zatím nebyl změřen. Nelze tedy číselně tvrdit konkrétní speed-up. Implementace je offline ověřená a připravená pro kontrolovaný A/B benchmark z `ACCEPTED_A_0009_cebb9c7a9349.ver`. `calibration_complete=false` a `production_ready=false`.

## Evidence

- implementation tree SHA-256: `0bc7afddb9025df62d015b829eaec02f2c11604d207fb2366d1f50af5712dad1`
- source patch SHA-256: `125affd7287b4b777b6da547c63b7334304971683ef9e329934e25bcf5da7a20`
- machine status: `V24915_PERF1_MACHINE_STATUS.json`
- test report: `V24915_PERF1_TEST_REPORT.json`
- source inventory: `V24915_PERF1_IMPLEMENTATION_SOURCE_INVENTORY.json`
