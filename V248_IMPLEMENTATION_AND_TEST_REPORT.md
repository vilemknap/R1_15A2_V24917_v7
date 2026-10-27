# R1 15A2 V2.4.8 — implementační a testovací report

## Výchozí základ

- CP07 / R1 15A2 V2.4.7 Path Epoch Calibration;
- V2.4.7 path epoch reuse uvnitř jednoho běhu zachován;
- V2.4.6 adaptivní TG/TD/ADDVAL1, FineCDF v1.8, bulk COM čtení a paging zachovány;
- CP03 path-length a rollback-diagnostic hotfixy zachovány.

## Implementovaná změna

V2.4.8 přidává persistentní cross-run path epoch checkpointy:

- immutable SQLite po každé úspěšné enumeraci;
- úplný `PRAGMA integrity_check` před publikací;
- SHA-256 souboru a samostatný sidecar;
- hashovaný manifest;
- explicitní origin a accepted-state bindings;
- read-only aktivní SQLite při kalibraci;
- přesná vazba rotačního `.ver` checkpointu na path epochu;
- jednorázový fail-closed import úplného V2.4.7/V2.4.5 store;
- retence podle počtu i celkové velikosti;
- odstranění stale indexů a bindingů po prune.

## Autorizační vrstvy

Cross-run restore musí projít:

1. nalezení podle exact origin hash nebo explicitního accepted-state bindingu;
2. kontrolu bindingu proti manifestu;
3. kontrolu manifest self-hash;
4. kontrolu config/runtime/observation/link/immutable kontraktu;
5. kontrolu velikosti SQLite;
6. SQLite `quick_check` a foreign-key check;
7. SHA-256 a sidecar;
8. kontrolu path basis, comparison basis a structure hash po otevření.

Selhání kteréhokoli kroku reuse zakazuje.

## Legacy import

Starý store se pouze vyhledá podle lehkých metadata. Úplná kontrola se provede až na exact-state kandidátu. Vyžadována je all-profile path-flow parita, která současně ověřuje historické profilové indexy. Import vytvoří novou kopii; starý store se nikdy nepřepisuje.

## Checkpoint lineage

`LATEST_ACCEPTED_CHECKPOINT.json` a slotové pointery nyní obsahují `path_epoch_checkpoint`, takže je auditně doloženo, která immutable epocha patří ke konkrétnímu accepted `.ver`.

## Testování

Po implementaci prošla úplná zděděná i nová sada:

```text
581 passed
0 failed
0 skipped
```

Nové testy pokrývají:

- publish + úplný integrity gate;
- exact-origin restart bez COM enumerace;
- accepted descendant restart přes binding bez COM enumerace;
- skutečné otevření store read-only;
- legacy V2.4.7 exact-state import bez COM enumerace;
- manifest, binding a SQLite tamper;
- observation/profile-order drift;
- immutable context drift;
- retenci a přepis fyzického indexu;
- odstranění bindingů na pruned cache;
- auditní vazbu `.ver` checkpointu na cache epochu;
- config a launcher hash lock.

Samostatný syntetický uživatelský benchmark prokázal:

```text
fresh run path enumeration calls: 1
exact-origin restart calls:       0
accepted-state restart calls:     0
```

Benchmark není měřením skutečného Visum wall time.

## Hranice tvrzení

- implementace a offline testy: ano;
- syntetický restart přes skutečný SQLite manager a adapter: ano;
- cloud vývojové checkpointy: ano;
- skutečný Windows PTV Visum 2026 COM restart: neproveden zde;
- production ready: ne, dokud neprojde živý checklist.
