# R1 15A2 V2.4.5 - audit, opravy a overeni

Datum: 2026-10-16. Vychozi zdroj: presny dodany V2.4.4 ZIP, SHA-256
`6e5f886e96f6b93b072d2f0dc4a2ef0948fbfd0f3cc73564b3a6b45b9ea3233c`.

## Vysledek a rozsah dukazu

**522 passed, 0 failed, 0 errors, 0 skipped.** Compileall rc=0. Puvodni V2.4.4 mela
457 prochazejicich testu; tato sada presto nepokryvala skutecny pad 15 -> 57.
Pribylo 66 regresnich pripadu. Jeden stary negativni pripad, ktery nespravne
vyzadoval odmitnuti kazde 0-link interzonalni cesty, je nahrazen explicitnimi
testy prazdneho versus chybejiciho exportu a zachovani kladneho objemu.

**Stav je OFFLINE_REPAIR_REGRESSION_PASS_LIVE_VISUM_NOT_RUN.** Na Linuxu neni
Visum COM. Neni tvrzeno dokonceni realne kalibrace, test GUI, produkcni pripravenost
ani zaruka bezchybnosti cizi aplikace. Strojovy report tyto gate uvadi NOT_RUN.

## Opravy nalezene ve zdroji

| Oblast | Puvodni chyba/riziko | Implementovana oprava |
|---|---|---|
| 0-link interzonalni path | EMPTY_INTERZONAL_GEOMETRY i pro explicitni uplny parent s kladnym volume | Prazdna sekvence je BLOB b'', edge_count=0, ZERO_LINK_INTERZONAL_NO_ADDVAL1_EFFECT. NULL/chybejici export zustava chyba. |
| Parita a attribution | Pripusteni prazdne sekvence samo nestaci; coverage by stale odmitala validni cache | Objem zustava v DSeg/OD parite a OD denominatoru. Pouze link-coverage denominator a postings nezahrnuji 0-link trasy. Neni vytvoren zadny fiktivni link. |
| Dokonceni cyklu | STARTED cycle vypadal jako iterace s false zmenami | Stavovy automat GENERATION_RUNNING -> TD_RUNNING -> COMPLETED, SEARCH_INCOMPLETE, FAILED nebo INTERRUPTED. Null flags do skutecneho provedeni; samostatny completed_demand_cycles. |
| Stationarita | Jediny no-accepted cyklus mohl odemknout supply | Dva po sobe jdouci uplne a uspesne prohledane TG+TD cykly. Budget/stop/truncation/error nikdy nejsou plateau. Jde o lokalni search, ne dukaz dobreho fitu. |
| Generation acceptance | Counts-only config byl v ledgeru, ale adapter.block_gate stale cetl puvodni IDP veto | Transakcni config scope prenasi tutez politiku do skutecneho adapter gate a vzdy obnovi puvodni cfg. IDP je povinnou nasledujici FineCDF casti, nikoli ignorovany ukazatel celeho workflow. |
| Supply chyby | Design/trial failure mohl skoncit jako no-improvement konvergence | Technicka chyba zastavi fazi. Omezeny neprozkoumany search nema konvergencni status. FAILED supply nema COMPLETED prefix. |
| Rollback a stop | STOP/time checkpoint mohl zablokovat navrat rozpracovaneho kandidata | Odklad kooperativniho stopu jen v kritickem obnovovacim useku; potom stop plati. Obnova parametru + recompute + snapshot + diagnostika, bez LoadVersion a bez zapisu OD. |
| Finalni stav | Stary lokalni hash a samotny status-string autorizovaly finalni soubor | Nezavisle overeni ziveho snapshotu a diagnostiky; final_state_verified povinny. Uplny a castecny overeny vystup maji odlisne nazvy. |
| Checkpointy | Slot mohl byt smazan pred novym uspesnym ulozenim; prazdny/stary soubor mohl projit | Unikatni payload, nenulovy soubor, SHA, az potom pointer. Predchozi slot zanikne az po publikaci noveho. Dva rotujici uspesne sloty. Partial SaveVersion nepokracuje fallbackem. |
| Frozen data | Generation/TD nemely dost explicitni ochranu pevnych matic | FOREIGN 9116, EXOG_EE a LNV/NV nejsou povolene vedlejsi mutace. TD freeze atributy a ADDVAL musi byt citelne; konec izolace overuje ACTIVE/DSTRATSET readback. |
| Lifecycle/leaky | Otevreny SQLite pri konstrukcni chybe, stale ready flag, vice zadrzenych COM proxy | Close pri selhani, idempotentni invalidace, zakaz dvojiteho materializovani evidence, uvolneni pomocneho slovniku linkovych COM objektu. |
| Spousteni/verze | Stara slozka v sys.path mohla predbehnout aktualni verzi; cleanup selhal pri chybe zapisu statusu | Priorita celeho aktualniho baliku, kontrola puvodu modulu, obnova sys.path i obou globalnich Visum referenci. Lock/busy cleanup i pri chybe finalniho reportu. |
| Recompute output | Spolecny writer spolehal na pripravene slozky | Parent-safe adresar je vytvoren ve skutecnem execute_procseq, nejen ve V243 wrapperu. |

Z puvodnich produkcnich souboru je skutecne zmeneno **8 runtime modulu**,
ne pouze README nebo wrapper. Jsou zmeneny dva existujici testovaci soubory.
Nezmizel zadny zdrojovy soubor; odstraneno je pouze 7 puvodne pribalenych .pyc.
Diff je v SOURCE_PATCH_V244_TO_V245.diff.

## Co presne se spustilo

Puvodni i nova pytest sada byly skutecne provedeny. Nove testy pouzivaji
skutecne produkcni parsovani, stavovy automat, vyber kandidata, jeho navrat,
opakovane aplikovani, hashove kontroly, checkpoint publish a finalni launcher.
Native Visum vypocet a COM odpovedi maji vyslovne deklarovane synteticke hranice.

Plny controller fixture: `COMPLETED_CONFIGURED_DEMAND_AND_SUPPLY_SEARCH`, 3 dokoncene demand cykly,
3 prijatych zmen a 21 volani assignment fixture vcetne rollbacku,
recompute a adopce. Test prochazi az ke konecnemu vystupnimu souboru pres realny
V245 launcher ve slozce s mezerami a ceskymi znaky. Tento soubor je ve fixture
JSON, nikoli simulovane platny Visum model; zadny realny .ver se tim neoveruje.

Samostatne bezel skutecny referencni FineCDF Runner a jeho 512bodova metrika,
nikoli nahrada algoritmu. Pouzita byla ctyrzonova COM-shaped fixture se
syntetickou native odezvou. Probehlo 9 evaluaci, objective
2.231113209481 -> 0.554304906480.
Stop MAX_ITERATIONS zustal spravne search_complete=false. Skutecny 681zonovy
preflight datove opravy je v teto fixture vypnut a jeho overeni se netvrdi.
V dodane konfiguraci skutecneho launcheru se tento preflight nevypina.

Chybove scenare zahrnuji chybu generation design, TD chybu po zapisu b/c,
chybu supply, assignment exception, KeyboardInterrupt, STOP, TD/outer budget,
truncated search, chybejici geometrii, chybu COM streamu, zmenu frozen matice,
chybu finalnich diagnostik, chybu zapisu statusu, poskozeny checkpoint a cizi lock.
Test opakovane vytvori a zavre 30 SQLite cache a kontroluje pocet linuxovych
file descriptoru; to neni dukaz absence Windows COM nebo dlouhodobych RAM leaku.

## Zachovane autority a historie

V3.7/3.8 byly vyvoj/proby saved paths a dvou modu; V3.9 safety gates; V4.0
pridal celonocni trial controller; V4.1 hierarchii; V4.2 spojeny demand a
referencni FineCDF; V4.3 opravu adresare recompute; V4.4 native Multi guard.
Soubory vlozene textove evidence popisuji pad V4.3; stejny fatal guard byl
mechanicky reprodukovan primo na dodanem V4.4 zdroji. Prvni TG nebylo dokoncene.

Referencni v1.7 zdroj, vsechny dodane authorities a diagnosticke helpers
zustaly byte-for-byte shodne s V4.4. SHA reference:
`2160f79fbd5de1645635327cb46e4a7daf6a14304af3e683d4f5dce98ebccf82`.
CAL/VALID role, 498 observation rows, VDF/impedance podklady, FOREIGN a
native-Multi diagnostic policy se neprepisovaly. Podrobnosti jsou v
PROTECTED_AUTHORITY_BYTE_PARITY.json. Sdilena C/C_NOT geometrie zustava
provisional pouze pro navrh; akceptaci stale rozhoduje cerstvy assignment.

## Predani a dalsi skutecne live gate

Spoustet pouze R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_5.py z noveho kompletne
rozbaleneho baliku. Neprepisovat starou slozku jednotlivymi soubory. Postup,
STOP a checkpointy popisuje START_HERE_V245_CZ.txt. Stare launchery, manifesty
a reporty v baliku jsou zachovany jako historicke podklady, nikoli V245 evidence.

Zive cilove prostredi musi jeste overit COM/schema, korektni realne TD a
assignment spusteni, cerstvost saved paths/GAP, zive candidate acceptance,
vykon, dostupnou RAM, opravneni a pripadne modalni dialogy Visumu. Zde nelze
zarucit jejich uspech. Nejedna se o odlozenou implementaci: opravy jsou fyzicky
v tomto source tree a vsechny zde dostupne testy byly provedeny.
