# R1 15A2 V2.4.9.4 — oprava path-export COM retry a sémantického restartu

V2.4.9.4 navazuje přímo na V2.4.9.3. Zachovává všechny metodické korekce
V2.4.9.3: kalibrační objective založený na observation-weighted mean GEH,
diagnostickou roli součtů přes profily, jediný `LONG_COMPOSITE`, signed Generation,
nativní IPF toleranci, persistentní path cache a čerstvé 12D/11D acceptance gates.

Release opravuje dvě chyby odhalené prvním živým během V2.4.9.3.

## 1. Transientní COM chyba v bounded path exportu

Živý V2.4.9.3 běh doběhl až k exportu více než 13 milionů path-link řádků a
poté skončil v přímém volání `ole.Invoke(...)` chybou `Volaný odmítl volání`.
Předchozí COM resilience pokrývala diagnostiku, zónové transakce a helpery, ale
nepokrývala všechny low-level bounded `SaveToArray` cesty.

V2.4.9.4 zavádí jediný produkční wrapper:

`bounded_ole_invoke_with_retry(...)`

pro všechny aktivní bounded path-export cesty:

- two-mode parent a geometry export;
- obecný `PrTPathLink` streamer;
- geometry sample audit;
- read-only live API bounded sample.

Retry je povolen pouze pro:

- `RPC_E_CALL_REJECTED` (`-2147418111`);
- `RPC_E_SERVERCALL_RETRYLATER` (`-2147417846`).

Každý retry zachovává přesně stejný `FirstObject`, `LastObject` a page size.
Před dalším pokusem se pumpují čekající COM zprávy a použije se bounded
exponenciální backoff. Po vyčerpání retry se běh ukončí fail-closed.

### Page-size fallback

Transientní RPC odmítnutí už nikdy nesnižuje page size. Menší stránka se smí
použít pouze při explicitní ne-transientní paměťové, overflow nebo rozpoznané
range/size chybě. Obecná COM chyba ani generické `E_INVALIDARG` nejsou samy o
sobě autorizací ke změně stránkování.

## 2. Restart authority není raw SHA celého `.ver`

Normální ruční `Save` ve Visumu může znovu serializovat `.ver` a změnit jeho
binární SHA-256 bez změny modelového stavu. Proto V2.4.9.4 rozlišuje:

- raw `.ver` SHA — provenance a kontrola, že source nebyl změněn během právě
  běžící kalibrace;
- restart acceptance — explicitní sémantický fingerprint modelu.

Sémantický restart fingerprint obsahuje:

- `fixed_link_hash`;
- `dseg_hash`;
- `operations_hash`;
- `addval_hash`;
- `matrix_hash`;
- `generation_hash`;
- `td_hash`.

Cross-run restart nikdy neporovnává raw `.ver` SHA ani cross-release obecný
`state_hash`. Pokud je vedle checkpointu soubor `<checkpoint>.ver.semantic.json`,
jeho sémantika se ověří fail-closed. U staršího checkpointu bez sidecaru se
sémantika načte přímo z otevřeného živého modelu a sidecar je pouze volitelný.

Po `SaveVersion` do `WORKING_START.ver` se znovu pořídí sémantický snapshot a
musí přesně odpovídat zdrojovému modelu. Každý nový accepted checkpoint V2.4.9.4
publikuje vedle `.ver` také vlastní semantic sidecar.

## Zachované kontrakty V2.4.9.3

- `CSD_CAL = sum(weight * GEH) / sum(weight)`;
- `objective_geh2_mean` pouze diagnosticky a pro historickou kompatibilitu;
- individuální `new_geh20` a `new_geh30` guards nad běžným GEH;
- `obs_sum`, `model_sum`, `model_obs_ratio` pouze jako passage checksumy;
- pět nativních LONG matic, ale jedna acceptance autorita `LONG_COMPOSITE`;
- společný LONG posun `b` a společný multiplikátor `c`;
- signed Generation s family-global a centrovanou zonální složkou;
- nezměněná nativní IPF tolerance;
- fresh assignment + live 12D/11D před přijetím kandidáta.

## Offline ověření

- focused regression: 119 PASS;
- úplná sada po opravě: 708 PASS;
- compileall: PASS;
- stejný bounded range při transientním retry: PASS;
- transientní chyba nikdy nevyvolá page-size fallback: PASS;
- legitimní ne-transientní page-size fallback: PASS;
- rozdílný raw `.ver` SHA při stejné sémantice: PASS;
- sémantický rozdíl při stejném raw SHA: fail-closed PASS;
- checkpoint semantic sidecar: PASS.

Reálný PTV Visum COM běh této nové verze zatím nebyl proveden. Proto zůstává:

`real_visum_tested = false`

`production_ready = false`
