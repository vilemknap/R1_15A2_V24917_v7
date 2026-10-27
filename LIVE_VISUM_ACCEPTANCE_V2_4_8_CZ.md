# V2.4.8 — živý acceptance checklist persistentní path cache

## Gate 0 — čisté prostředí

- rozbal celý V2.4.8 balík do krátké lokální cesty;
- nepoužívej launcher ze starší složky;
- ověř, že neběží jiný R1 15A2 skript;
- otevři čistý autoritativní `.ver` nebo přesný accepted `.ver` checkpoint;
- spusť `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8.py`.

## Gate A — první publikace epochy

Při prvním běhu bez cache musí proběhnout právě jedna počáteční enumerace. Potom musí existovat:

```text
%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248\EPOCH_...\
  TWO_MODE_PATH_STORE.sqlite
  TWO_MODE_PATH_STORE.sqlite.sha256
  PATH_EPOCH_MANIFEST.json
```

Požadované kontroly:

- manifest SHA souhlasí;
- `store_sha256` souhlasí se souborem i sidecarem;
- `sqlite_integrity.result = ok`;
- `incidence_ready = true`;
- origin binding existuje;
- aktivní store je v kalibrátoru otevřen read-only.

## Gate B — restart ze stejného origin stavu

1. Po bezpečném STOP zavři běh.
2. Znovu otevři tentýž origin `.ver`.
3. Spusť stejný V2.4.8 launcher.

Očekávané:

```text
PERSISTENT_PATH_CACHE_RESTORE.json:
  status = PERSISTENT_PATH_EPOCH_RESTORED
  matched_by = STATE_BINDING nebo ORIGIN_STATE_HASH
  store_sha256_verified = true
```

Mezi baseline a prvním Generation designem nesmí proběhnout nový COM path export.

## Gate C — restart z accepted checkpointu

1. Nech přijmout alespoň jeden TG nebo TD kandidát.
2. Ověř, že `LATEST_ACCEPTED_CHECKPOINT.json` obsahuje `path_epoch_checkpoint` a nenulové `persistent_cache_id`.
3. Bezpečně ukonči běh.
4. Otevři přesný `.ver` uvedený v accepted checkpointu.
5. Spusť V2.4.8.

Očekávané:

```text
matched_by = STATE_BINDING
origin_state_hash != aktuální live state hash je dovoleno
immutable context musí být shodný
```

Nová enumerace se nesmí spustit.

## Gate D — převzetí starého runu

Pro první migraci lze ponechat původní V2.4.7/V2.4.5 run directory. Otevři přesně stejný origin stav jako při starém exportu.

Očekávané:

```text
matched_by = LEGACY_EXACT_STATE_IMPORT
legacy_profile_flow_gate.passes = true
```

Poté musí vzniknout nová immutable V2.4.8 epocha. Původní starý SQLite se nesmí změnit ani smazat.

## Gate E — neshoda musí vyvolat nový export

Záměrně otevři model s jiným accepted stavem bez bindingu nebo změň bezpečně testovací immutable kontrakt. Cache se nesmí použít. Očekávané:

```text
NO_AUTHORIZED_PERSISTENT_CACHE_MATCH
```

následované novou enumerací, nikoli tichým reuse.

## Gate F — pokračování v rámci epochy

Po reuse musí dál platit V2.4.7 pravidla:

- accepted TG/TD/ADDVAL stav epochu nemaže;
- live OD volumes se reweightují na frozen shares;
- live profily se znovu navážou;
- každý kandidát má nový assignment a diagnostiku;
- fresh re-enumeration nastane až na úplném plateau nebo při novém kladném OD bez supportu.

## Gate G — disk a retence

Ověř:

- index neodkazuje na chybějící adresáře;
- po více epochách zůstávají nejvýše tři;
- součet je omezen nastaveným 24GiB limitem, s výjimkou právě publikované povinné epochy;
- bindingy na odstraněnou epochu jsou odstraněny;
- accepted `.ver` checkpointy zůstávají nedotčené.

## Gate H — integrita zdroje

Na konci nebo po bezpečném STOP:

```text
source_file_unchanged = true
load_version_called = false
live_matches_last_accepted = true
```

Při jakémkoli neověřeném stavu se nesmí publikovat finální kalibrovaný `.ver`.

## Doporučený bounded test

```text
běh 1:
  baseline → první enumerace → publikace cache → 1 accepted krok → bezpečný STOP

běh 2:
  otevřít accepted .ver → hash/integrity restore → žádná enumerace → další Generation/FineCDF krok

běh 3:
  pokračovat do lokálního plateau → fresh re-enumeration → nová persistentní epocha
```
