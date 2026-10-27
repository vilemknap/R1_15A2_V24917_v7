# V24912 COMPLETE R2 – oprava prvního live pádu

## Zjištěná chyba

První live běh původního V24912 skončil v prvním Generation trialu chybou:

```text
No module named 'r1_15a2_guard_policy_v24912'
```

Model nebyl přijat ani změněn (`accepted_count = 0`). Chyba vznikla tím, že
live acceptance v `r1_15a2_core.py` prováděla pozdní dynamický import policy
modulu až uvnitř kandidátního vyhodnocení. Takový import není bezpečný v dlouhé
Visum session, protože helper/procedure kontext může změnit efektivní importní
cestu po úvodním načtení launcheru.

## Systémová oprava

- Autoritativní V24912 policy je nyní vložena přímo do `r1_15a2_core.py`.
- Live acceptance už neprovádí žádný pozdní import policy modulu.
- `r1_15a2_guard_policy_v24912.py` zůstává pouze jako kompatibilní/auditní
  facade a reexportuje funkci z core.
- Launcher před jakýmkoli zápisem do Visumu spouští automatický kompletní
  `V24912_RUNTIME_BUNDLE_PREFLIGHT`.
- Preflight ověří SHA-256 a velikost 60 runtime-kritických souborů, helpery,
  authority soubory, reference skripty a všechny lokální runtime moduly.
- Preflight explicitně reprodukuje původní failure boundary: odstraní release
  root ze `sys.path`, odebere policy facade z `sys.modules` a znovu provede
  syntetické severity vyhodnocení. To musí projít z vložené implementace v core.
- Neúplné rozbalení se zastaví jednou souhrnnou chybou před kalibrací; chybějící
  soubory se nehledají postupně během jednotlivých trialů.

## Co se nemění

Guard-policy prahy, Generation/TD metodika, nativní IPF tolerance, assignment,
12D/11D, rollback a semantic restart zůstávají shodné s auditovaným V24912.
Jde o runtime/deployment opravu, nikoli o další změnu kalibračního cíle.

## Bezpečný start

1. Rozbalit celý flat deployment ZIP do prázdné složky
   `C:\Users\vilem_knap\Documents\VISUM\v45\2022\R1_15A2_V24912`.
2. Otevřít poslední accepted `.ver` z V2496/V24912 B0000.
3. Spustit `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py`.
4. První nový run musí obsahovat `V24912_RUNTIME_BUNDLE_PREFLIGHT.json` s
   `passes=true`, `package_revision=V24912_COMPLETE_R2` a
   `late_policy_import_required=false`.

`real_visum_tested=false` a `production_ready=false` zůstávají až do nového
reálného live běhu COMPLETE R2.
