# TD cyklu 2: odmítnuté COM volání a neověřený rollback

Čtecí audit 14 dodaných souborů, 2026-10-31. Všech **36 kontrol návaznosti prošlo**; nejde o test úspěšnosti rollbacku. Naopak, dodaný TD výsledek rollback výslovně označuje za selhaný. Identifikace původních vstupů, jejich velikosti a SHA jsou v `SUMMARY.json`.

## Rozhodující stav

`TD_FINECDF_BLOCK_RESULT.json` obsahuje:

```text
status = ROLLBACK_FAILED_MANUAL_REOPEN_REQUIRED
td_realization_complete = false
next_generation_permitted = false
error = Volaný odmítl volání.
rollback_error = Could not locate readable Trip Distribution operation
```

Toto není běžné vyčerpání pokusů ani pouhá absence souborů v předem vytvořeném adresáři. TD pokus selhal a následná obnova nebyla potvrzena. Ze souborů nelze zjistit aktuální stav Windows procesu ani to, zda ještě čeká některý vnější zotavovací obal. Živý model proto nelze označit za ověřeného rodiče.

## Přesné pořadí selhání

1. TD targeting už hlásí `GLOBAL_IDP_FALLBACK` s důvodem `com_error:Volaný odmítl volání.`. Stejný důvod je v `TD_ACTIVE_COMPONENT_MASK.json`.
2. Při zahájení vnitřního TD selhal konstruktor `_compatible_init` v `r1_15a2_td09c_16or17_hotfix_v24916.py:95`, konkrétně přístup `self.v.Procedures.Operations` před `rt.get_all(...)`. Přímý COM getter je mimo explicitní `com_call_with_retry`. Není doložen začátek samotného vnitřního hledání b/c.
3. Handler vyvolal `_rollback_td_all(..., ROLLBACK_AFTER_TD_FAILURE, ...)`.
4. Obnova parametrů přes `restore_td_parameters → apply_td_candidates → read_td_parameter_state` skončila hláškou, že čitelnou TD operaci nelze najít.
5. Handler uložil výše uvedený tvrdý stav a požadavek na ruční otevření ověřeného checkpointu.

Primární chyba znamená odmítnutí COM volání Visumem. Konkrétní příčinu odmítnutí (modalita, zaneprázdněné UI nebo jiný stav hostitele) samotný traceback neprokazuje. Nelze ji připsat uživatelově interakci bez dalšího důkazu.

## Proč je složka rollbacku prázdná

`r1_15a2_overnight_controller_coupled_v24915p2_force100._rollback_td_all` nejprve vytvoří adresář. Pak inicializuje kontext a volá obnovu TD parametrů. `r1_15a2_inplace_transaction_v24915p2.restore_td_parameters` zapisuje první `ROLLBACK_PARAMETER_READBACK.json` až po dokončení `vp.apply_td_candidates` a kontrole readbacku.

Dodaná výjimka nastala uvnitř úvodního čtení TD parametrů. Proto v tomto adresáři ještě nevznikl první důkaz úspěšné obnovy. Prázdná složka odpovídá místu selhání; nedokazuje čekání na probíhající assignment ani úspěšné dokončení rollbacku.

Ve čtečce `r1_15a2_visum_parameters._iter_operations` je navíc permissivní `except Exception: return []`. Odmítnuté COM čtení tak může být zakryto jako prázdný seznam operací a následně jako obecné `Could not locate readable Trip Distribution operation`. Tato hláška sama o sobě **neprokazuje, že TD operace byla z modelu odstraněna**. Bez nového živého čtení nelze přesně rozlišit všechny příčiny sekundární nečitelnosti.

## Proč RUNNING / STARTED neznamená pokračující výpočet

`00_MASTER_SUMMARY.json` má `last_phase=START` a shodný čas `started=updated=2026-10-31T03:11:35+01:00`. Výjimka nastala při inicializaci před normálním dokončením vnitřního solveru, takže zde zůstal starý počáteční stav `RUNNING`.

`RUN_STATUS.json` eviduje cyklus 2 jako `TD_RUNNING`, `td_realization_pending=true`, `final_state_verified=false` a `calibration_complete=false`. Nedodává terminální potvrzení bezpečného dokončení. Konkrétní selhaný TD výsledek nelze přepsat interpretací starého obecného statusu.

`GENFIX2_PARENT_PROOF_RETAINED.json` má pouze `CAPTURED_BEFORE_MUTATION`. Jde o uchovaný referenční podklad, nikoli důkaz, že po tomto selhání proběhl rollback a živé porovnání. Jeho snapshot ID se ani neshoduje s checkpointovým live_state_hash; z rozdílu ID samotného tento audit nevyvozuje konkrétní poškození parametrů.

## Poslední zaznamenaný přijatý checkpoint

`LATEST_ACCEPTED_CHECKPOINT.json` a pointer ve vnějším statusu se shodují:

```text
C:\Users\vilem_knap\R1F_742748e4\R1_15A2_V16_RUNS\RUN_20261031_010656_550362\CALIBRATION\CHECKPOINTS\ACCEPTED_B_0002_c810a3269231.ver
```

- Přijatý počet: 2, slot B.
- Evidovaná velikost: 534913169 bajtů.
- Evidovaný SHA-256: `22a1e58040b305092f5664cb32eaccd46c4b129335e389d22d71aa9400dd433a`.
- Checkpointový stav navazuje na přijaté TD cyklu 1.

Samotný `.ver` nebyl nahrán. Tento audit proto **neověřil jeho fyzickou přítomnost ani aktuální SHA na uživatelově disku**. Manifest však obsahuje konkrétní cestu a identitu posledního přijatého souboru. Starší `BEST_SO_FAR_0001_fdc123035603.ver` je samostatný přijatý stav číslo 1, nikoli totéž co poslední přijatý checkpoint.

Pro obnovu: z aktuální neověřené instance nepokračovat v kalibraci a nepřepsat přijaté checkpointy jejím stavem. Pokud skript skončil a Visum je ovladatelné, použít ruční otevření uvedeného přijatého checkpointu. Neprovádět automatický `LoadVersion` uvnitř právě běžícího skriptu. Pokud skript ještě běží nebo je otevřený modal dialog, je nejprve nutné zjistit stav UI; tato otázka byla uživateli položena.

Konečný wrapper status a Python log by měly být pod:

```text
C:\Users\vilem_knap\R1F_742748e4\R1_15A2_SILENT_DEBUG\SILENT_LATEST_STATUS.json
C:\Users\vilem_knap\R1F_742748e4\R1_15A2_SILENT_DEBUG\SILENT_LATEST_DEBUG.zip
```

Tyto soubory v aktuálních přílohách nejsou; status se publikuje až po návratu z hlavního skriptu. Mohou odlišit dokončený pád od ještě běžící vnější obsluhy.

## Rozsah a další oprava

Je potřeba pokrýt explicitním omezeným retry také úvodní čtecí COM řetězce při sestavování TD adapteru a zachovat příčinu transientního odmítnutí při hledání TD operace v rollbacku. Povolené scope musí rozlišovat opakovatelná čtení od transakčních zápisů. Chybějící TD operace, změna procedurálního scope či neověřený rollback nesmí být převedeny na úspěch nebo automatické pokračování.

Tento diagnostický krok opravu retry **neimplementuje**, neobnovuje model a nespouští Visum. Samostatná větev `codex/td02-com-failure-audit-20261031` přidává pouze důkazy a rozbor nad posledním dodaným zdrojovým stromem. Přiložený ZIP není nová COM oprava.

Audit: `/workspace/.venvs/r1/bin/python /workspace/work/td_failure_review_20261031/audit_inputs.py`, exit 0, 36 kontrol PASS. Skript je přiložen jako text s původními lokálními cestami. Runtime, manifesty a akceptační politiky zůstaly beze změny; jejich dosavadní unit testy nebyly pro tento datový rozbor znovu spouštěny.
