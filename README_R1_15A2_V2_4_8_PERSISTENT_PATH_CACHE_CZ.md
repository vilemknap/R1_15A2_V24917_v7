# R1 15A2 V2.4.8 — persistentní path-epoch cache

## Co verze řeší

V2.4.7 už uměla jednu úplnou enumeraci cest používat opakovaně uvnitř stejného běhu. Po pádu nebo ukončení skriptu se však při novém spuštění musela path báze znovu exportovat z PTV Visum.

V2.4.8 ukládá každou úspěšně dokončenou enumeraci jako samostatný, neměnný a hashovaný checkpoint. Nový běh proto může začít:

```text
načtení modelu
→ levný snapshot a kontrola kontraktu
→ SHA-256 + SQLite quick_check + FK kontrola
→ otevření existující epochy read-only
→ Generation
```

Místo nové enumerace se stará epocha použije jen tehdy, když je autorizována jedním z těchto způsobů:

1. aktuální model má přesně stejný `state_hash` jako stav, z něhož epocha vznikla; nebo
2. aktuální accepted stav má explicitní binding na danou epochu, vytvořený při předchozím úspěšném accepted kroku.

Při jakékoli neshodě se cache nepoužije a proběhne nová enumerace.

## Co se ukládá

Výchozí lokální kořen je:

```text
%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248
```

Každá epocha obsahuje:

```text
EPOCH_<čas>_<state>_<basis>/
  TWO_MODE_PATH_STORE.sqlite
  TWO_MODE_PATH_STORE.sqlite.sha256
  PATH_EPOCH_MANIFEST.json
```

Vedle toho existují:

```text
BINDINGS/<accepted_state_hash>.json
PATH_EPOCH_INDEX.json
LATEST_PERSISTENT_PATH_EPOCH.json
```

## Co manifest uzamyká

Cache je použitelná pouze při shodě:

- verze cache schématu;
- SHA konfigurace;
- hashů relevantních runtime modulů;
- schématu SQLite;
- počtu zón;
- množiny passenger DSegů a jejich mode membership;
- reprezentativních DSegů pro C a C_NOT;
- observation authority a pořadí profilů;
- směrového linkového slovníku;
- `fixed_link_hash`, `dseg_hash` a `operations_hash`;
- path-basis a comparison hashů.

Samotná existence souboru SQLite nikdy nestačí.

## Obnova ze stejného vstupního modelu

Když předchozí běh vytvořil persistentní epochu a nový běh otevře stejný accepted modelový stav, V2.4.8 ji automaticky najde, ověří a otevře read-only. COM path enumeration se nevolá.

## Obnova z accepted `.ver` checkpointu

Každý accepted stav, který dál používá stejnou path epochu, dostane explicitní state binding. Rotační `.ver` checkpoint současně obsahuje auditní blok `path_epoch_checkpoint` s:

- ID persistentní cache;
- epoch indexem;
- origin a live state hashem;
- exact a comparison basis hashem;
- cestou k lokálnímu cache adresáři.

Po otevření tohoto `.ver` na stejném počítači nový běh najde binding podle live `state_hash`.

## Import ze starého V2.4.7/V2.4.5 běhu

V2.4.8 umí jednorázově převzít úplný `TWO_MODE_PATH_STORE.sqlite` ze staršího run directory, ale pouze když:

- metadata uvádějí přesně stejný origin `state_hash`;
- export i incidence jsou označené jako úplné;
- schéma odpovídá;
- all-profile path-flow parita proti současné živé diagnostice projde;
- je dost volného místa pro vytvoření nové immutable kopie.

Starý store se neupravuje. Po úspěšné kontrole se zkopíruje do nového V2.4.8 checkpointu, projde úplným `PRAGMA integrity_check`, dostane SHA-256, manifest a binding.

## Bezpečnost

Persistentní cesty zůstávají pouze autoritou pro návrh kandidátů. Každý kandidát stále vyžaduje:

- skutečný nativní přepočet PTV Visum;
- živé 12D/11D diagnostiky;
- původní acceptance a guardrail pravidla;
- rollback bez `LoadVersion`, pokud kandidát neprojde.

Cache tedy nezamrazuje objective ani výsledné intenzity. Zmrazená je jen enumerovaná path geometrie a uložené path shares v rámci autorizované epochy.

## Fail-closed situace

Nová enumerace nebo ukončení s chybou nastane mimo jiné při:

- chybějícím či neplatném bindingu;
- změně immutable kontextu;
- neshodě manifest SHA;
- neshodě SQLite SHA nebo sidecaru;
- chybě `quick_check`, `integrity_check` nebo FK kontroly;
- změně observation authority či pořadí profilů;
- změně DSeg/link/config/runtime kontraktu;
- nově kladné OD relaci bez uloženého supportu;
- vyčerpání refresh budgetu.

## Retence a disk

Výchozí politika ponechává nejvýše tři epochy a současně maximálně 24 GiB. Právě publikovaná aktivní epocha se zachová vždy; starší epochy a jejich bindingy se odstraní až po úspěšném publikování nové epochy a přepsání fyzicky ověřeného indexu.

## Spuštění

1. Rozbal celý balík do nové krátké lokální složky.
2. V PTV Visum 2026 otevři čistý vstupní nebo accepted checkpoint `.ver`.
3. Spusť přes `Scripts → Execute script file`:

```text
R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8.py
```

Launcher nespouštěj z Procedure Sequence a nekopíruj jej samostatně do starší verze.

## Jak poznat reuse

V run directory musí vzniknout:

```text
PERSISTENT_PATH_CACHE_LOCATION.json
.../PERSISTENT_PATH_CACHE_RESTORE.json
.../PATH_EPOCH.json
```

Úspěšný restart má například:

```text
status = PERSISTENT_PATH_EPOCH_RESTORED
matched_by = STATE_BINDING nebo ORIGIN_STATE_HASH
store_sha256_verified = true
restored_cross_run = true
```

Pokud není autorizovaný match, objeví se:

```text
status = NO_AUTHORIZED_PERSISTENT_CACHE_MATCH
```

následované novou enumerací.

## Hranice ověření

Implementace je offline a synteticky otestovaná. Skutečný Windows PTV Visum 2026 COM restart musí projít checklistem `LIVE_VISUM_ACCEPTANCE_V2_4_8_CZ.md`.
