# V2.4.7 — živý acceptance checklist v PTV Visum 2026

## 1. Vstup

- otevřít čistý autoritativní zdrojový `.ver`;
- ověřit, že neběží starší skript;
- rozbalit celý V2.4.7 balík do krátké lokální cesty;
- spustit pouze `R1_15A2_FULL_OVERNIGHT_PATH_EPOCH_V2_4_7.py`.

## 2. Gate A — počáteční enumerace

Musí vzniknout první `PATH_EPOCH.json` s:

- `epoch = 1`;
- nenulovým exact a comparison basis hashem;
- kompletní parent/geometry paritou;
- `sequence_evidence_ready = false` během Generation, pokud Supply ještě nezačal.

Počáteční path export smí proběhnout jednou. Každý další export musí mít explicitní důvod `LOCAL_PLATEAU_REFRESH` nebo povinný support refresh nově kladné OD relace.

## 3. Gate B — reuse po přijatém stavu

Po prvním přijatém Generation nebo FineCDF stavu musí být v block resultu:

```text
path_epoch_transition.retained = true
```

Následující Generation design musí použít stejné:

```text
path_epoch_parent_hash
path_basis_hash
path_basis_comparison_hash
```

ale jiné nebo aktuální `live_parent_hash`, pokud se stav změnil.

Mezi těmito stavy nesmí vzniknout nový COM path export.

## 4. Gate C — živá OD reweighting

`TWO_MODE_CACHE_REUSE.json` a incidence summary musí uvádět:

```text
FROZEN_PATH_EPOCH_LIVE_OD_REWEIGHT_NO_COM_REEXPORT
```

Kontroly:

- žádný kladný live OD tok bez epochového supportu;
- žádné NaN, záporné hodnoty nebo změna OD os;
- path/link coverage se počítá na aktuálních live volumes;
- candidate acceptance stále používá čerstvý assignment.

## 5. Gate D — Supply rebind

Při vstupu do Supply musí vzniknout `PATH_EPOCH_PROFILE_REBIND.json` a deferred sequence evidence bez nového path exportu.

Po přijatém ADDVAL1 stavu:

- epoch zůstává stejná;
- live profile models a driver set se obnoví;
- ON/OFF evidence se znovu vytvoří ze stejného SQLite store;
- další kandidát projde novým assignmentem a live diagnostikou.

## 6. Gate E — refresh až na plateau

Po úplném cyklu bez přijaté změny musí vzniknout:

```text
PATH_EPOCH_PLATEAU_GATE.json
```

### Pokud je basis změněná

Očekávané:

```text
action = NEW_PATH_BASIS_CONTINUE_CALIBRATION
stationarity_confirmed = false
```

Kalibrace pokračuje a Supply zůstává zamčené, pokud jde o demand fázi.

### Pokud je basis ekvivalentní

Očekávané:

```text
action = FRESH_ENUMERATION_CONFIRMED_LOCAL_PLATEAU
stationarity_confirmed = true
```

Pouhé přečíslování PathIndex nebo změna pod 1e-6 path volume nesmí samo vytvořit novou epochovou změnu; exact hash ale může zůstat odlišný pro audit.

## 7. Gate F — disk a checkpointy

Po úspěšném refreshi:

- nový SQLite store existuje;
- starý superseded `TWO_MODE_PATH_STORE.sqlite` je odstraněn;
- `PATH_EPOCH_STORE_RETENTION.json` uvádí odstraněné soubory;
- aktuální store se nikdy nemaže;
- accepted `.ver` checkpointy a hashové evidence zůstávají.

## 8. Gate G — zdrojový model

Na konci nebo po bezpečném STOP:

- `source_file_unchanged = true`;
- `load_version_called = false`;
- `live_matches_last_accepted = true`;
- při neúspěchu se nesmí vytvořit `FINAL_CALIBRATED_WORKING_COPY.ver`;
- při dokončení musí finální state hash souhlasit s controllerem.

## Doporučený první živý bounded průchod

Nechte běh projít alespoň:

```text
baseline
→ první path epoch
→ Generation trial + rollback/adoption
→ další Generation design bez path re-exportu
→ FineCDF
→ první úplný demand plateau
→ fresh path refresh
```

Poté lze použít kooperativní `STOP_REQUESTED`, aby se ověřilo bezpečné ukončení na posledním accepted checkpointu. Následně spusťte plný noční běh z čistého zdroje.
