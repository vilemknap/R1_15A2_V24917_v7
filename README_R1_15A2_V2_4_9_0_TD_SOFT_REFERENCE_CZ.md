# R1 15A2 V2.4.9.0 — TD soft reference

## Účel

Tato verze mění metodickou autoritu trip distribution. Křivky z průzkumu mobility jsou **měkká směrová reference**, nikoli deterministická křivka, kterou musí model přesně reprodukovat. Modelový TD kandidát smí být přijat jen po plné Visum realizaci a pouze tehdy, když přinese materiální agregované zlepšení vybraných TD komponent a současně nepřekročí povolené trade-offy ani síťové/pozorovací guardraily.

Současně opravuje živě doložený V2.4.8.9 false positive `V242_TD_UNREQUESTED_PARAMETER_CHANGE`: metadata a zmrazený kontext zůstávají exact, ale numerické COM read-back hodnoty `b,c` mají úzkou toleranci 1e-8 abs / 1e-10 rel.

## Soft-reference kontrakt

- survey role: `SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT`;
- exact curve match: `false`;
- minimální agregované relativní zlepšení selected TD objective: 0.5 %;
- maximální relativní zhoršení jednotlivé selected komponenty: 5 %;
- maximální relativní zhoršení non-selected komponenty: 5 %;
- maximální absolutní zhoršení global IDP mean: 1 procentní bod;
- maximální absolutní zhoršení global IDP worst component: 5 procentních bodů;
- CAL GEH² guard zůstává 0.5 % a není uvolněn;
- protected profile, severity transition a observation-set authority zůstávají hard;
- nativní 20B/IPF tolerance se **nemění**.

Po plné downstream realizaci se kandidát vyhodnotí live. Při zamítnutí soft TD gate se zkusí menší krok `1, 0.5, 0.25, 0.125, 0.0625`. Pokud jsou všechny kroky technicky realizovatelné, ale žádný není bezpečné materiální zlepšení, obnoví se accepted parent a TD se označí jako bounded plateau. Není to chyba ani důvod nutit model na survey křivku.

## Hard fail zůstává

Korupce/změna observation authority, fixed matrices, generation/addval kontextu, nečekaná změna TD metadata, b/c změna nad read-back toleranci, ne-IPF COM chyba nebo vyčerpaná nativní IPF realizace zůstávají fail-closed.

## Launcher

`R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_0.py`

## Restart

Pro první živý gate použij bezpečný B_0000 z V2.4.8.9 runu, nikoli částečně přijatý stav z jiné větve. Persistentní path cache v `%LOCALAPPDATA%\R1_15A2_PATH_CACHE_V248` nemaž.
