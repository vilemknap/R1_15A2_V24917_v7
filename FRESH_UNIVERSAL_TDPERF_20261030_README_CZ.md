# R1 V24917 – univerzální nový běh, optimalizované TD (PATHROOTFIX1, 2026-10-31)

**Účel:** druhá nezávislá kalibrace **od počátku** ze zvoleného kompatibilního modelu .ver, bez čekání na TD cyklus 06 staršího procesu a bez pokračování z B0002/B0008. Základ kódu: `codex/td-perf-review-20261030` @ `6794184143df5516708651c1d27b5f57c04b94b8`.

## Spuštění

1. Stáhnout **celou tuto větev** jako ZIP, rozbalit do samostatné složky zdrojového kódu. Nekopírovat jednotlivé Python soubory do zdrojové složky právě běžící kalibrace.
2. V **druhé samostatné instanci PTV Visum 2026** otevřít původní/požadovaný výchozí kompatibilní model `.ver`, nejlépe základní nekalibrovanou verzi roku 2022. **Není potřeba B0002 ani soubory z jiného RUN_***. Pokud výchozí .ver je checkpoint jiné kalibrace, stane se novým baseline s novou linií; historie předchozích přijetí se nepřenáší.
3. V druhém Visumu vybrat Scripts → Run script file → `01_SPUSTIT_V24917_FRESH_UNIVERSAL_TDPERF_SILENT.py`.
4. Spouštěč ověří zdroj, integritu balíku, strukturu sítě, měření/parametry/operace, projde nativní počáteční assignment, vytvoří pracovní kopii a začne **Generation 01 → TD 01 → Generation 02 → TD 02 → ...**. Žádné dřívější přijetí nebude znovu přehrávat. **TD se nepřeskakuje v žádném vnějším demand cyklu.**
5. Podle prvních auditů ověřit vlastní enumeraci. Kontrolní soubor u skutečného prvního exportu: `.../CALIBRATION/DEMAND_CYCLE_01_GENERATION/GENERATION_CACHE/FRESH_UNIVERSAL_NATIVE_EPOCH.json`. Úspěšný stav je přesně `FRESH_NATIVE_ENUMERATION_VERIFIED` a `allow_persistent_restore_passed_to_native: false`. Soubor `PATH_EPOCH.json` a databáze `TWO_MODE_PATH_STORE.sqlite` musí být ve **stejné nové** kalibrační složce.
6. Při pokračujícím běhu kontrolovat `TDJOINT_SEARCH.json` (SCHOOL/LONG a skutečné sondy), `TD_PERF_RESTORE_AUDIT.json` (počty `native_restores` a `verified_reuses`), `V24917_TIMING.json` a `RUN_STATUS.json`. **V běžícím procesu nic nepřepisovat**.

## TD v každém cyklu – bez řídkého plánování

Nová univerzální větev má v `R1_RUN_OPTIONS.json` výslovně:

```json
{
  "td_policy": "ALWAYS",
  "td_every_n_cycles": 1,
  "td_during_catchup": true,
  "td_first_cycle": true,
  "td_inner_mode": "DYNAMIC",
  "td_joint_enabled": true,
  "school_td_enabled": true,
  "long_composite_td_enabled": true,
  "td_inner_max_evaluations": 60
}
```

Řadič `r1_15a2_demand_policy_v1.DemandPolicy.td_due()` v režimu `ALWAYS` vrací `(True, "ALWAYS")` **pro každý vnější cyklus** bez ohledu na to, zda se Generation změnila, zda jde o plateau, nebo zda model běží v režimu `CATCH_UP`. Tím se odstraňuje původní přeskočení například TD 04 a TD 05 v politice `EVERY_N = 3`.

Spouštěč současně ověřuje skutečně nainstalovanou politiku `demand_policy.note.options`; pokud ji např. proměnná prostředí `R1_TD_POLICY`, `R1_TD_EVERY_N` nebo `R1_TD_DURING_CATCHUP` přepíše na jiné hodnoty, nová kalibrace **bezpečně selže ještě před kandidátní kalibrací**, aby nebylo možné omylem znovu přeskakovat TD.

Toto neznamená automaticky přijetí TD změny: i při provedené kalibraci může být výsledek odmítnut a vrácen rollbackem, nebo hledání zůstat neúplné. Výpadek Visumu či porušení safety brány zůstává chybou, nikoli přeskokem. Počítejte s tím, že každý provedený TD může být časově náročný; žádný naměřený čas celého cyklu zatím nová verze nemá.

## Rozšířené meze Generation pro WORK / SERVICE

Při zachování dolní hranice **0,75** se mění horní hranice domácích zón v kalibračních koeficientech:

| Účel a role | Atributy zón | Původní maximum | Nové maximum |
|---|---|---:|---:|
| WORK a SERVICE, produkce | `ADD_PROD_W`, `ADD_PROD_S` | 2,5 | **3,0** |
| WORK a SERVICE, atrakce | `ADD_ATT_W`, `ADD_ATT_S` | 4,0 | **5,0** |

Předchozí univerzální vydání mělo 2,5 pro produkci a 4,0 pro atrakci; toto vydání je nahrazuje. Spodní mez 0,75 se nemění. Nové hranice platí pro `CATCH_UP` i `REFINE`, shodně pro tvrdou mez a soft band; návrh, P/A projekce, zonální solver a finální kontrola realizovaného koeficientu používají stejnou hodnotu. `MOBILITY2` a `MOBILITYZONE1` měly v posledním vydaném balíku ochranu produkce 2,5, která by nové povolené hodnoty předčasně blokovala. Pro **WORK a SERVICE** je horní limit těchto produkčních kontrol nově **3,0** (`mg_max_ratio=3.0`), jejich dolní limit 0,75 a veškeré důkazy z nativních `FP_*` zůstávají povinné. Ochrana `SCHOOL` zůstává na [0,75; 2,0] a `LONG` na vlastní původní hranici.

**Dodatečné zajištění MOBILITY2:** produkční mobilitní poměr `R = sum(FP)/sum(FP/ADD_PROD)` zůstává pro WORK i SERVICE omezen **0,75–3,0**; nemění se na 5,0. Atrakční koeficienty `ADD_ATT_W` a `ADD_ATT_S` mají **samostatnou** zonální pojistku **0,75–5,0** při konečném sestavení kandidáta i při živém přečtení výsledku z Visumu. Nadlimitní A kandidát se odmítne, i když mobilitní P poměr vyhovuje. U původních hodnot mimo hranici se povoluje pouze stagnace nebo pohyb směrem dovnitř. `ZAHR` a nezávislé `LONG/SCHOOL` zůstávají mimo tuto domácí W/S atrakční pojistku. Chybějící hodnoty domácích `ADD_ATT_W/S` v nativním snapshotu jsou chyba, nikoli důvod pro vypnutí ochrany.

**Beze změny:** `ADD_SALARY` [0,5; 2,0], ZAHR relativní interval [0,5×; 10×] podle startovního koeficientu, LONG/SCHOOL, zachování strukturálních nul, intervaly změny koeficientu za jeden cyklus (+50 % / −20 % v `CATCH_UP`; +25 % / −20 % v `REFINE`), přesné bilancování produkcí a atrakcí, TD, akceptační bezpečnost a rollback.

Pokud by proměnná prostředí přepsala `mg_max_ratio` na starou hodnotu 2,5 nebo 2,0 nebo chyběla nová role-specific Generation policy, univerzální spouštěč odmítne zahájit kalibraci; nesmí potichu přejít na jinou interpretaci. Předchozí stažený ZIP s původními mezemi nepoužívat.

## Adresáře a nezávislost

Zdrojový .ver zůstává na místě. Jeho skutečný projektový kořen je složka obsahující .ver, případně nadřazená složka původního *nejvnějšího* `R1_15A2_*_RUNS`.

Nové soubory vznikají **odděleně od původních**, přímo pod uživatelským profilem Windows:

```text
C:\\Users\\<uživatel>\\R1F_<8znakový hash projektového kořene>\\
    .R1_15A2_V16.lock
    R1_15A2_V16_RUNS/
      LATEST_BOOTSTRAP.json
      FRESH_UNIVERSAL_BOOTSTRAP_AUTHORITY.json
      RUN_YYYYMMDD_HHMMSS_ffffff/
        PATH_LENGTH_PREFLIGHT.json
        CALIBRATION/
          RUN_STATUS.json
          DEMAND_CYCLE_01_GENERATION/GENERATION_CACHE/
            TWO_MODE_PATH_STORE.sqlite
            PATH_EPOCH.json
            FRESH_UNIVERSAL_NATIVE_EPOCH.json
    R1_15A2_SILENT_DEBUG/
      SILENT_LATEST_STATUS.json
      SILENT_LATEST_DEBUG.zip
```

**PATHROOTFIX1 (31. 10. 2026):** První živé spuštění v7.3 skončilo bezpečnostním preflightem `V24916_PATH_LENGTH_PREFLIGHT_FAILED:244`: projektový sandbox `...\\2022\\R1FRESH17` prodlužoval nejhlubší budoucí cestu na 244 znaků proti povoleným méně než 240. **Nepovolovali jsme delší cesty ani nevypnuli kontrolu.** Nyní má každý projekt deterministicky přidělen krátký uživatelský kořen `%USERPROFILE%\\R1F_<hash>`; pro přesnou zaznamenanou Windows cestu tak projekce klesne z **244 na přibližně 222 znaků**. Hash se počítá z původního normalizovaného projektového kořene a brání sdílení dat různými projekty. Dřívější chybový adresář `...\\2022\\R1FRESH17` se neimportuje ani automaticky nemaže.

Zabudovaný V24916 `audit_run_path_budget` se nyní volá **dvakrát**: před zahájením parent runtime nad vzorovým budoucím RUN a potom v původním kódu znovu nad skutečným RUN. Pokud je uživatelská cesta výjimečně dlouhá, spuštění bezpečně selže; limit 240 se nikdy nepřekračuje.

**Pozor:** běžící stará verze má samostatný zámek v `<projektový kořen>/.R1_15A2_V16.lock` a data v `<projektový kořen>/R1_15A2_V16_RUNS`. Nová verze používá **svůj krátký kořen v uživatelském profilu** a vlastní zámek. Potřebuje druhou instanci Visumu a dostatek místa na disku (nové SQLite a checkpointy se ukládají do profilu). Dva nové univerzální běhy ze *stejného* projektového kořene se zámkem vzájemně blokují – záměrná ochrana.

Nesnažit se vložit zdrojový .ver **dovnitř** `R1FRESH17` nebo `R1F_<hash>`: spouštěč to odmítne, aby nevzniklo rekurzivní zanoření.

## Zaručená metodika a omezení

- Start `accepted_count=0`, `cycle=1`, `FRESH100`, bez B0002/A0001 restartovací autority.
- Persistent path cache / legacy cache import / cross-run restore jsou zakázané; první a každá další vynucená epocha používá nativní `collect_two_modes`. Změna pozitivní OD podpory spouští standardní novou enumeraci; žádný podíl cest se nedopočítává bez nativního důkazu.
- Reuse již enumerované cesty **uvnitř stejného běhu a stejné platné epochy** zůstává dovoleno, aby se zbytečně neopakovala několikahodinová enumerace.
- TD používá optimalizované schéma `td_numpy`, `td_restore REVIEW1`, `tdjoint1`. Původní native 20B/IPF, parametry, TD/Generation realizace, 12D/11D acceptance, rollback, LONG/SCHOOL omezení, bezpečnostní brány a `td_count_weight=0.6` zůstávají převzaty z uzamčené zdrojové větve.
- Nezkracujeme kalibraci pouhým snížením počtu TD evaluací. První TD cyklus podle konfigurace proběhne skutečně; optimalizace redukují pouze redundantní čtení a výpočet.
- Python silent zachycuje výjimky a připraví omezený debug ZIP v sandboxu. Samotné modal dialogy Visumu tím nelze univerzálně vypnout.
- **Offline testy nejsou živý PTV Visum COM test.** Úspěch enumerace/procedur/rollbacku a reálná úspora času musí být doloženy prvním živým během. Případný audit `FAILED` znamená zastavit používání pracovního modelu a vrátit se k původnímu .ver; nikoli obejít guard.
