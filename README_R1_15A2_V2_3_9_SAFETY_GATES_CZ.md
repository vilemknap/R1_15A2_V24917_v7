# R1 15A2 V2.3.9 — bezpečnostní gate před trial-assignment kalibrací

Tento balík **není produkční APPLY kalibrátor**. Uzavírá tři podmínky, které musí být živě prokázány před tím, než dovolíme automatické pokusné změny parametrů a jejich vyhodnocení skutečným PTV Visum assignmentem.

## Co řeší V2.3.9

1. **Autorita assignmentu pro supply trial:** operace **20**, typ **101**, s přesným 14-DSeg `DSEGSET`, je jediná povolená supply-only assignment operace. Operace 17–19 se stále živě auditují jako známé dílčí scope, ale pro supply trial se samostatně nespouštějí, protože op20 obsahuje celý společný rozsah.
2. **Úplná geometrie dvourežimové cache:** porovnají se **všechny uložené PrT path-link sekvence** všech 12 osobních DSegů. Shoda rodičovských klíčů ani vzorků nestačí.
3. **Rollback bez `LoadVersion`:** řízená dočasná změna `ADDVAL1`, generation a TD parametru se po přepočtu obnoví přímým vrácením původních parametrů a stejným přepočtem modelu. Návrat musí obnovit přesný snapshot i diagnostický hash. `LoadVersion` ani `SaveVersion` se nepoužijí.

Produkční `APPLY` zůstává zakázaný. Count authority 498, epsilon 0,005 a všechny stávající numerické autority zůstávají beze změny.

---

# Krok 1 — 15T, read-only úplný gate

Spusť v původní uložené baseline `.ver` přes:

**Scripts → Execute script file**

soubor:

`R1_15A2_15T_ASSIGNMENT_SCOPE_FULL_GEOMETRY_READONLY.py`

15T:

- nic nezapisuje do modelu,
- nespouští assignment,
- nevolá `SaveVersion` ani `LoadVersion`,
- ověří operace 17–20: číslo, typ 101, ACTIVE a přesný `DSEGSET`,
- vybere pro budoucí supply trial **jen op20**,
- kompletně přečte `PrTPathLinkList` všech 12 osobních DSegů,
- pro režim `C` vytvoří referenční SHA-256 každé trasy a porovná proti němu všech 7 ostatních DSegů,
- pro režim `C_noT` analogicky porovná zbývající 3 DSegy,
- kontroluje pořadí indexů hran a spojitost `ToNode -> FromNode`,
- před a po auditu porovná úplný modelový snapshot,
- uloží SHA-256 otevřené `.ver`.

Výstup vznikne vedle `.ver`:

`R1_15A2_15T_SAFETY_GATE/RUN_.../`

Klíčové soubory:

- `15T_ASSIGNMENT_SCOPE.json`
- `15T_FULL_GEOMETRY_IDENTITY.json`
- `15T_SAFETY_GATE_RESULT.json`
- `15T_PROGRESS.json`
- `00_FINAL_STATUS.txt`

Jediný PASS pro pokračování je:

`PASS_ASSIGNMENT_SCOPE_AND_FULL_GEOMETRY_IDENTITY`

15T má maximální časový rozpočet 8 hodin. Z předchozích živých testů víme, že jde o velký export; může trvat hodiny. Lze jej nechat běžet přes noc. `STOP_REQUESTED` v run/root složce provede bezpečné zastavení při nejbližším kontrolním bodě.

**Pokud 15T neprojde, 15U nespouštěj.**

---

# Krok 2 — vytvoření pracovní kopie pro 15U

Po úspěšném 15T:

1. Zavři/nech beze změny baseline `.ver`; **neukládej do ní žádný trial stav**.
2. Na disku vytvoř bitově identickou kopii baseline ve **stejné složce**, například:

   `R1_2022_15U_WORKING_COPY.ver`

   Název musí obsahovat přesný token `15U_WORKING_COPY`.
3. Vedle této `.ver` vytvoř textový soubor:

   `15U_WORKING_COPY_ACK.txt`

   s jediným řádkem:

   `I_CONFIRM_DISPOSABLE_WORKING_COPY`

4. Otevři ve Visumu **tuto pracovní kopii**.

15U před jakýmkoli přepočtem ověří:

- že existuje poslední 15T PASS ve stejné složce,
- že SHA-256 pracovní kopie `.ver` je přesně stejný jako u 15T,
- že aktuální modelový `state_hash` odpovídá 15T,
- že assignment scope 17–20 stále odpovídá autoritě,
- že preflight pro skutečný assignment prochází.

Bez kterékoli podmínky skončí před první dočasnou změnou.

---

# Krok 3 — 15U, rollback smoke se skutečným assignmentem

Na **pracovní kopii** spusť:

`R1_15A2_15U_NO_LOADVERSION_ROLLBACK_SMOKE.py`

Tento skript **dočasně mění model v paměti**. Proto se nesmí spouštět na produkčním/originálním `.ver` a během běhu se model nesmí ručně ukládat.

Nejprve vytvoří čerstvou baseline spuštěním současné aktivní Procedure Sequence. Potom postupně otestuje:

### A. SUPPLY_ADDVAL1

- zvolí jeden malý bezpečný `ADDVAL1` trial,
- spustí **jen op20** (plus aktivní strukturální group operace nutné pro její dosažitelnost),
- vyhodnotí kandidátní stav,
- vrátí původní `ADDVAL1`,
- znovu spustí op20,
- požaduje přesnou shodu snapshotu a diagnostického hashe s baseline.

### B. GENERATION

- dočasně změní jeden `ADD_PROD_W` o relativních `1e-4`,
- spustí celou aktivní Procedure Sequence,
- vrátí původní hodnotu,
- znovu spustí celou Procedure Sequence,
- požaduje přesný návrat snapshotu a diagnostiky.

### C. TD_COMPONENT_WORK

- dočasně změní `b` komponenty `WORK_E_C` o `1e-4`,
- spustí celou aktivní Procedure Sequence,
- vrátí původní `b,c`,
- znovu spustí celou Procedure Sequence,
- opět požaduje přesný návrat.

Pokud kandidátní přepočet vyhodí chybu, `finally` větev se stále pokusí o rollback. Pokud rollback nelze prokázat, výstup explicitně požaduje ruční znovuotevření pracovní `.ver`.

15U **nikdy nevolá `LoadVersion` ani `SaveVersion`** a neprovádí přímé zápisy do OD matic.

Výstup:

`R1_15A2_15U_ROLLBACK_SMOKE/RUN_.../`

Klíčové soubory:

- `15U_ASSIGNMENT_SCOPE.json`
- `BASELINE_AUTHORITY.json`
- `SUPPLY_ADDVAL1/15U_BLOCK_RESULT.json`
- `GENERATION/15U_BLOCK_RESULT.json`
- `TD_COMPONENT_WORK/15U_BLOCK_RESULT.json`
- `15U_ROLLBACK_SMOKE_RESULT.json`
- `00_FINAL_STATUS.txt`

Jediný úplný PASS je:

`PASS_NO_LOADVERSION_ROLLBACK_SUPPLY_GENERATION_TD`

---

# Co mi poslat

Po 15T pošli:

- `15T_SAFETY_GATE_RESULT.json`
- `15T_FULL_GEOMETRY_IDENTITY.json`
- `15T_ASSIGNMENT_SCOPE.json`

Po 15U pošli:

- `15U_ROLLBACK_SMOKE_RESULT.json`
- všechny tři `15U_BLOCK_RESULT.json`
- případný `ROLLBACK_VERIFICATION.json` z bloku, který selhal.

Teprve po **živém PASS 15T + živém PASS 15U** je metodicky obhajitelné sestavit noční trial-assignment kalibrátor, který bude kandidáty skutečně aplikovat v pracovní kopii, spouštět assignment, porovnávat 498 profilů/IDP a přijímat jen prokazatelná zlepšení.
