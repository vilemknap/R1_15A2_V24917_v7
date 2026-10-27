# IMPORTFIX1: oprava padu GENFIX2 + TDJOINT1 + COSTFIX1 (27.10.2026)

## Pricinny dukaz

Dodan `DEMAND_CYCLE_01_RESULT(20261027-115432).json`:
`status=FAILED`, `generation_completed=false`, `accepted_count=0`,
`error=No module named 'r1_15a2_parent_equivalence_v24917'`.
Tento modul je pritom v kompletni distribuci COSTFIX1 i ve
`V24917_RUNTIME_MANIFEST.json`. Jde o pozdni import v transakcni vetvi
GENFIX2; z JSON souboru samotnych nelze dokladovat, zda uzivatelska
kopie modulu byla v okamziku padu pritomna a zda import selhal kvuli
obnoveni sys.path nebo cache v dlouho bezicim Visum Python hostu.

## Oprava

V `r1_15a2_v24917_runtime.py` se pri `install_all()` pred prvnim
kalibracnim pokusem zavola `preload_parent_equivalence()`:
- overi SHA-256 zdroje oproti `V24917_RUNTIME_MANIFEST.json`;
- nacita primarne z absolutniho souboru v aktivnim balicku, nikoli
  pres neudrzenou importni cestu a cache;
- binduje modul do `sys.modules`, aby nasledujici pozdni importy
  v GENERATION, TD rollback a SupplyMix fungovaly i po obnove sys.path;
- stary modul z jineho adresare odmitne pred jakoukoli modelovou mutaci;
- pri chybnem nebo chybejicim zdrojovem modulu fail-closed uz pri startu.

Ve `V24917_RUNTIME_STATUS.json` pribyva
`v24917.parent_equivalence_preload` s cestou, hashem a stavem.

**Zadna zmena**: generation/TD algoritmy, vahy 65/35 (ci volitelnych 60/40),
kalibracni profily, native assignment, SupplyMix COSTFIX1, ulozene autority,
rollbackove testy a pravidla prijeti. Ctyri zmenene existujici soubory:
1. `r1_15a2_v24917_runtime.py` (jediny produkcni soubor),
2. `tests/test_v24917_runtime_install.py` (3 nove regresni testy),
3. `DIAGFAST_V1_RELEASE_MANIFEST.json`,
4. `V24917_RUNTIME_MANIFEST.json`.

## Overeni

- Hlavni suite: 1390 PASS, 4 SKIP, 0 FAIL.
- TDJOINT1 suite: 51 PASS, 0 FAIL.
- DIAGFAST suite: 138 PASS, 0 FAIL.
- GENFIX2 audit suite: 18 PASS, 0 FAIL (`PYTHONPATH=.:tests`).
- Celkem 1597 PASS, 4 SKIP, 0 FAIL (unikatni nepřekryvne sady).
- Syntakticke overeni vsech Python souboru.
- Ctverice aktivnich integritnich manifestu: 0 neshod.
- Startup-integration pres separatni subprocess a simulovane
  odstraneni slozky balicku ze sys.path: PASS.
- Skutecny Visum 2026 COM beh: NEOVERENO.

## Dalsi logove upozorneni (NEreseno touto opravou)

V konzoli je `DIAGFAST_DIRECT_INLINE_PARITY_FAILED:11D` pro tri vystupy
(porovnani 30/33) s korektnim fallbackem na LEGACY pro zbytek behu.
Jde o neblokujici diagnosticke upozorneni, nikoliv o `ModuleNotFoundError`.
Zamerne jsme do teto opravy nemichali presnost rychleho 11D.
