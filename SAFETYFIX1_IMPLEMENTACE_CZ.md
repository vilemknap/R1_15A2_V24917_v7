# SAFETYFIX1 – oprava tří potvrzených chyb (27. 10. 2026)

**Výchozí verze:** úplný MOBILITYFIX1 s GENFIX2, TDJOINT1, COSTFIX1, IMPORTFIX1 a PROCSEQFIX1.  
**Rozsah:** pět produkčních souborů, dva testovací soubory, kontrolní SHA manifesty a nové regresní testy.  
**Ochrana:** 1 059 souborů chráněného DIAGFAST V1 BASE manifestu zůstalo byte-identických.

## Zásada pokračování

Odlišuji nebezpečnou *akceptaci* od bezpečného *pokračování*. Výpadek dílčího důkazu neumožní přijmout kandidáta. U TD jej původní realizační algoritmus zamítne, zmenšuje krok a nakonec provede ověřený rollback. Po ověření rodiče pokračuje kalibrace. Pokud nelze rollback dokázat, program se musí zastavit: není správné pokračovat na neznámém stavu.

### 1. TD outer fail-open → fail-closed candidate, progress-continue run

V `r1_15a2_trial_adapter_v24917.py` při `blend.outer_decision()` výjimce zůstával rodičovský `accepted=True`. Nyní se nastaví `accepted=False`, důvod `V24917_TD_SHARED_OBJECTIVE_UNAVAILABLE` a původní výjimka zůstává v diagnostice. Původní TD realizace zajistí backtracking a ověřenou obnovu rodiče. V `r1_15a2_demand_policy_v1.py` se incomplete TD nezapočte jako stacionarita; `inner.progress_continue=True` umožní další cyklus. Žádná automatická akceptace bez společného GEH/IDP skóre.

### 2. Nulové FlowBundle důkazy → GLOBAL_IDP_FALLBACK

Původní skóre `alignment_score=0` pro nulovou váhu společné rodiny mohlo na prahu `>=0` vybrat komponenty abecedně. Ve vrstvě `r1_15a2_active_demand_evidence_v24917.py` se nyní před publikací kontrolují kladné *konečné* důkazní váhy i skóre. Komponenty bez doloženého signálu se neoznačují jako aktivně cílené. Pokud není žádná kladná evidence, publikuje se `status=GLOBAL_IDP_FALLBACK`, `active_components=[]`; původní FineCDF běží na globální průzkumové referenci. Původní zapečetěný modul `r1_15a2_demand_evidence_v24916.py` nebyl změněn.

### 3. LONG/SCHOOL: transient RPC není chybějící atribut

`r1_15a2_long_school_generation_v24917.py` používá `r1_15a2_com_compat.com_call_with_retry` pouze pro dvě známé dočasné COM RPC chyby a s omezeným počtem pokusů. Ověřeně chybějící atribut se hlásí `ATTRIBUTES_MISSING`; vyčerpané přechodné čtení `TRANSIENT_COM_EXHAUSTED`; ostatní neověřené čtení `ATTRIBUTE_READ_UNVERIFIED`. Poslední dvě varianty **neznamenají**, že dané atributy ve Visumu neexistují. V daném cyklu lze pokračovat s WORK/SERVICE bez zápisu do LONG/SCHOOL, ale výsledek se nepočítá jako kompletní hledání/konvergence. Podobně výjimka v aktivním LS návrhu má explicitní `LS_DESIGN_ERROR` a `search_complete=False`.

Konfigurace LONG/SCHOOL se nesmí potichu změnit na implicitní limity. Nevalidní konfigurace proto vyvolá explicitní chybu, kterou generování eviduje jako neúplný LS návrh; W/S může pokračovat.

## Ověření

- `pytest -q tests`: **1 469 PASS, 4 SKIP, 0 FAIL**.
- `pytest -q diagfast_tests`: **138 PASS**.
- `PYTHONPATH=.:tests pytest -q genfix2_audit_tests`: **18 PASS**.
- Celkem **1 625 úspěšných testů, čtyři historická přeskočení**. Sady byly spouštěny odděleně, aby se nepletly názvy historických `conftest.py`.
- Aktivní manifesty V24917, V24916, DIAGFAST, GENFIX2 a návazné distribuční SHA manifesty znovu ověřeny.
- Reálné Visum **nebylo** v tomto prostředí dostupné; testy COM a rollbacku používají kontrolované simulace.

## Zbylá omezení

Pokud dojde k neověřené obnově, chybě základní konfigurace, poškození matic nebo nedostupnosti nutného živého preflightu, je bezpečné ukončení správné chování. Po opakovaných dočasných výpadcích čtení LONG/SCHOOL mohou být jejich parametry po celý běh zmrazené: stav je výslovně uveden, nic se nesmí vydávat za kalibrované LONG/SCHOOL. Další doporučené úkoly z předchozího auditu (pokrytí incidenční mapy, SupplyMix config fallback, nezávislá prověrka assignment op 17–20, DIAGFAST 11D parity) jsou mimo tento cílený patch.
