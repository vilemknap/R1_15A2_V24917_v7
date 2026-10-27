# První živý Visum gate V2.2

## 1. Vstupní model a design-only

Otevřít správný čistý přijatý `.ver`. Potvrdit aktuálnost přiložených impedance/VDF exportů a existence 12 osobních DSegů, freight DSegů a komponentních matic. Předem uložit původní model. Assignment musí mít uložené skutečné PrT paths; jejich stav musí odpovídat aktuálním OD a síti.

Ponechat `apply=false`. Spustit `R1_15A2_SUPPLY_DEMAND_MASTER_V2_2.py` ručně z Scripts, nikoli ze samotné Procedure Sequence. Prohlédnout `00_DSEG_INVENTORY.json`, `00_SUPPLY_ASSIGNMENT_PLAN.json`, `00_PREFLIGHT.json`, návrhy bloků a supply path/parity reporty.

## 2. Explicitní assignment konfigurace

Do `supply.assignment_operations` přidat pouze skutečně ověřená čísla operací a typy z živého inventory. Každá položka používá `no`, `operation_type` a případně `dseg_object_path` / `dseg_attribute`, jsou-li jiná než výchozí. `no` je číslo operace podle konfigurovaného `operation_number_attribute`, nikoli odhad pozice.

Nastavit `supply.gap_readback.object_path`, `attribute` a `maximum_gap` podle skutečné instalace a konkrétního assignmentu. Testové názvy/typy z mock testů nejsou živá autorita. Nedostupný gap nesmí být nahrazen konstantou nebo návratovým kódem Execute.

Potvrdit, že vybrané assignment operace současně pokrývají osobní i freight dopravu a pracují v požadovaném režimu společné kongesce. Samotná shoda DSeg názvů není úplný důkaz správného vícetřídního nastavení. Další agregovaná matice nesmí znovu přiřadit stejnou dopravu.

## 3. Jeden bounded APPLY

Po vyřešení preflight blokací změnit APPLY a ponechat `max_accepted_blocks=1`. Supply musí prokazatelně vypnout TG/TD a ostatní neodsouhlasené operace, provést assignment, obnovit původní ACTIVE masku, zkontrolovat gap a nezměněné OD/generation/b,c.

Kontrolovat úplnost 12D CAL/VALID autority, všechny uložené path objemy, profile parity, přesné readback ADDVAL1, původní baseline kotvu a vyhodnocení každého kandidáta. ACCEPT je doložen přesným vybraným checkpointem a `ACCEPTED_STATE.json`. REJECT musí mít ověřený návrat.

## 4. Ověřit zbývající provozní hranice

Zkontrolovat live aktuálnost impedance/VDF i node/turn/connector konfigurace; současný snapshot není univerzální full-network COM audit. Ověřit uložené trasy po SaveVersion/LoadVersion a stabilitu diagnostik při opakovaném načtení. Vyzkoušet controlled reject a resume ze samostatného procesu. Resume restartuje cyklus se zachováním původní kotvy/reference.

Teprve po těchto živých důkazech lze výsledek označit za live-integration verified. Offline release se tak neoznačuje.
