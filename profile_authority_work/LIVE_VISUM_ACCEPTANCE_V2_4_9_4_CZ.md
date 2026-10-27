# Live Visum acceptance — V2.4.9.4

## Start

1. Otevřít zvolený B_0000 checkpoint v nové Visum session.
2. Ruční předchozí uložení checkpointu je přípustné; raw SHA nemusí odpovídat
   historicky zaznamenaným bajtům.
3. Nespouštět skript z Procedure Sequence, ale přes `Scripts > Execute script file`.
4. Spustit:

`R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_4.py`

## Povinné startovní důkazy

V novém run adresáři musí vzniknout:

- `SOURCE_SEMANTIC_RESTART_AUTHORITY.json`;
- `SOURCE_VERSION_AUTHORITY.json` s
  `raw_ver_sha_used_for_restart_acceptance=false`;
- `WORKING_COPY_SEMANTIC_IDENTITY.json`;
- `WORKING_START.ver.semantic.json`;
- `METHODOLOGY_STATUS.json` s bounded path-export retry policy.

Pokud existuje sidecar vedle načteného checkpointu, musí jeho sémantika přesně
odpovídat živému modelu. Absence sidecaru u staršího checkpointu je povolena.

## Očekávané chování při COM busy stavu

Při `RPC_E_CALL_REJECTED` nebo `RPC_E_SERVERCALL_RETRYLATER` musí progress audit
ukázat opakování stejného:

- `bounded_range_first`;
- `bounded_range_last`;
- `bounded_page_size`.

Nesmí vzniknout `page_size_fallback_from/to` jen kvůli transientnímu RPC
odmítnutí. Po maximálně pěti pokusech se běh ukončí fail-closed.

Page-size fallback je přípustný pouze pro explicitní ne-transientní
memory/range/overflow chybu.

## Bounded live gate

První live běh má zůstat omezený aktuální konfigurací:

- nejvýše 2 outer cycles;
- nejvýše 1 accepted block;
- working-copy trial calibration;
- žádný production apply.

Povinně ověřit:

1. path export překoná místo, kde V2.4.9.3 skončila po 13 062 144 řádcích;
2. Generation design se skutečně vytvoří;
3. weighted mean GEH se používá jako `CSD_CAL`;
4. LONG je v acceptance pouze `LONG_COMPOSITE`;
5. rejected candidate se vrátí do sémanticky shodného parentu;
6. accepted checkpoint má `.ver.semantic.json` sidecar;
7. source `.ver` zůstane během běhu beze změny.

## Co se nepovažuje za chybu

- odlišný raw SHA ručně znovu uloženého startovního `.ver`;
- odlišný obecný `state_hash` mezi různými release, pokud explicitní sémantické
  hashe odpovídají;
- absence V2.4.9.4 sidecaru u historického B_0000.

## Co je hard failure

- rozdíl v některém ze sedmi sémantických restart hashů;
- transientní RPC chyba přesměrovaná do page-size fallbacku;
- změna bounded range mezi retry pokusy;
- raw `ole.Invoke` mimo centrální retry wrapper v aktivní path-export cestě;
- změna zdrojového `.ver` během právě běžící kalibrace;
- accepted checkpoint bez sémantického sidecaru.
