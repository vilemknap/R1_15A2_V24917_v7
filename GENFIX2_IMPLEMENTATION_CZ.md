# R1 15A2 V24917 - MOBILITY2 / GENFIX2

Datum: 27. 10. 2026
Vysledek: IMPLEMENTOVANO A OFFLINE OVERENO. ZIVY PTV VISUM NEBYL SPUSTEN.

## 1. Rozsah a zdroj

Vychozi autoritou je cely GENFIX1 REPACK2, nikoli starsi rekonstruovana vetev.
SHA-256 puvodniho ZIPu:
7cb7408d85af35e859ff967fd2c2240238f4d3131e432f7dcbbce6e43bdfb390

Z puvodnich 1186 souboru neni zadny odstranen. Pred pridanim dokumentace a dukazu
je zmeneno 19 existujicich souboru a pridano 5 novych Python souboru. Zmeny jsou
v produkcnim kodu, nikoli jen v popisu. Chranenych 1059 souboru starsi zakladni
vrstvy zustava bajtove stejnych. Opravy GENFIX1 zustavaji zachovane.

R1_RUN_OPTIONS.json a vsechny puvodni authority soubory jsou bajtove zachovane.
Manifesty novych aktivnich vrstev byly aktualizovany; historicka base nikoli.
Presne cesty a hashe: GENFIX2_SOURCE_CHANGES.json. Diff: GENFIX2_SOURCE_DIFF.patch.

## 2. Implementovane opravy F01-F08

### F01 - SUPPLYMIX: vlastnictvi obnovy pres cely pokus

V r1_15a2_supply_mix_v24917.py je obal celeho bloku vcetne navrhu, zapisu
vysledku a prijeti. Povinnost obnovit assignment se eviduje nezavisle na tom,
zda jsou prave zmeneny parametry ADDVAL1. Vlastnictvi zapisoveho pokusu vznikne
pred prvnim zapisem, tedy i pred pripadnym castecne neuspesnym COM zapisem.

Obnovene parametry uz nejsou povazovany za obnoveny assignment. Pri chybe
pred druhym pokusem se obnovi a overi skutecny rodic. Osetrene jsou take
OSError, KeyboardInterrupt a uzivatelske preruseni. Selhani zapisovani logu
nesmi preskocit obnovu ani nahradit primarni vyjimku. Pocitadla prijetich zmen
se potvrzuji az po uspesnem ulozeni vysledku. Chybny nebo neuplny blok se
nevydava za uplnou stacionarni prohlidku; vnejsi demand policy dostane stejnou
informaci o neuplnosti.

### F02 - Obnova neni alternativni akceptace

Nouzovy plny prepocet nesmi zavolat candidate acceptance a prijmout materialne
jiny vysledek. Overuje se navrat k puvodnimu rodici spolecnou autoritou.
Neshoda konci explicitne:
GENFIX2_SUPPLYMIX_RECOVERY_NOT_EQUIVALENT_MANUAL_REOPEN

Tato vyjimka neni plateau ani changed=True. Pri uspechu se cache a diagnostika
navazi na skutecne overeny vysledek, bez zvyseni pocitadla prijatych kandidatu.
Pripadny spekulativni posun path-epoch acceptance counteru se pri obnove vraci.

### F03 - Jedna autorita ekvivalence rodice pro GEN / TD / SUPPLY

Novy modul r1_15a2_parent_equivalence_v24917.py vytvari pred mutaci dukaz:
identita snapshotu, identity a poradi os zon, identity a bajty demand matic.
Matice se ukladaji po jedne do kratke docasne slozky R1EQ_* ve formatu NPY,
bez zapisovani do Visumu. Zpracovava se jedna matice v pameti.

Zmeneny hash matice nelze prominout jen na zaklade shody vybranych profilu.
Pro numerickou ekvivalenci musi existovat neporusena kopie z doby pred pokusem,
aktualni cteni musi odpovidat snapshotu a musi projit omezene porovnani bunek,
L1 rozdilu, sum, radkovych/sloupcovych souctu, rozmeru, os, konecnosti a
nezapornosti. Bez dukazu lze pouzit pouze presnou shodu, nikoli nepodlozenou
toleranci. Neobjasnena zmena samotneho state_hash je odmitnuta.

Numericke tolerance (nove explicitni meze pro dosud neomezene domeny):
- matice: ATOL 1e-7, RTOL 1e-10;
- marginalni a celkove soucty: ATOL 1e-6, stejny RTOL;
- komponentove/diagnosticke signaly: ATOL 1e-9, RTOL 1e-8.
Puvodni profilove meze 0,5 vozidla / relativne 1e-4 a mez GEH 0,01 se nezvetsuji.

Kontrola zahrnuje 12D, 11D, signaly, jednoznacnost identit, pozorovani, role,
vahy a segmentove objemy. Ani presna shoda parametru nesmi obejit kontrolu
11D. Cesty docasnych vystupu, casy a transportni metadata se neporovnavaji
jako vysledek modelu; mapa outputs musi presto zachovat klice a typy.

RBCONS a TDROLLBACK vraceji skutecne nactenou diagnostiku a jeji hash, nikoli
stary rodicovsky objekt. Cache se navaze bez predstirani noveho prijateho kroku.
Pri uspechu se docasny dukaz uklidi; pri selhani se zachova a zaznamena cesta
v GENFIX2_PARENT_PROOF_RETAINED.json. Nutna je zapisovatelna docasna slozka a
misto na kopie demand matic. To pridava cteni a diskove I/O; nejde o zrychleni.

### F04 - MOBILITY2 je povinna i pri fallbacku

Chybejici nebo neplatne FP, multiplier, domaci maska, identita zony nebo
nulove pouzitelne pokryti uz neznamenaji GUARD_ERROR_NOT_APPLIED ani OK s NaN.
Pri zapnute ochrane je kandidat blokovany bez zapisu a bez falesne stacionarity.
Fallback navrh prochazi stejnou ochranou jako normalni fit.

### F05 - Mobilita po masce, P/A, zvolene skale i zivem prepocitu

R(scale) pri smisenych znamenkach neni monotonnni. MOBILITY2 kontroluje oba
konce i pripadne vnitrni minimum konvexniho souctu exponencial a hleda bezpecny
pocatecni interval skal. P/A vyvazeni nesmi zneplatnit potvrzenou obalku;
nevyresena rovnovaha je odmitnuta, ne oznacena jako hotova.

Pro kazdou pouzitou skalu se znovu kontroluji finalni implementovatelne radky,
a to po maskach, bounds, salary/LS a P/A upravach. Pred prvnim COM zapisem se
porovna cerstve sestaveny plan se schvalenym preview. Po skutecnem prepocitu
se pred prijetim znovu overi zive FP proti puvodni pevne referenci. Zmena
reference ani NaN se nesmi interpretovat jako uspech.

Definice R=sum(FP)/sum(FP/ADD_PROD), rodiny WORK/SERVICE, domaci rozsah a pasmo
0,75-1,25 jsou zachovane. U rodice mimo pasmo je zachovana puvodni zasada
nevzdalovat se dale. LONG/SCHOOL a zahranicni formule nejsou touto opravou
predefinovany. Nezavisla spravnost pruzkumovych koeficientu nebyla prokazana.

### F06 - Predikce skutecneho kroku

STEP1 predikuje z finalnich implementovanych efektu, nikoli ze stareho solution
pred omezenim mobility. Zohlednuje finalni log efekty, G operator, boundary a
LS prispevky. Stejna predikce slouzi volbe skaly, trialu a aktualizaci rho.
Nedostupny operator znamena nedostupnou predikci, nikoli vymysleny kladny prinos.

### F07 - COM count model nema trvale nuly z docasne chyby

CountModel opakuje rozpoznane docasne COM chyby v omezenem retry. Cachuje jen
uspesne nactenou linku. Vycerpani retry ani trvale selhani povinneho cteni se
neprevede na None/nulu; oznami chybu a znemozni pouzit neuplnou referenci.
Take cteni jednotlivych DSeg musi byt konecne a nezaporne.

### F08 - Dukazy se neztrati pri chybe ZIPu

Archivace pouziva unikatni docasny ZIP, kontrolu presneho seznamu souboru,
velikosti a CRC, pak atomicke publikovani. Zdroj se smaze az po overenem
archivu. Neuspech nebo neuplny, byt jinak validni ZIP zachova originalni slozku
s logy a ulozi .ARCHIVE_FAILED.json. Puvodni explicitni politika kompaktniho
logovani odmitnutych pokusu je od chyby archivace odlisena; nebyla potichu
zmenena na trvale uchovavani vseho.

## 3. Dalsi nalezy R01-R05 a zachovana metodika

R01: td_max_survey_degradation=1.25 zustava LOKALNI pomer diagnosticke chyby
po jednom TD kroku / pred krokem. Neni to globalni limit 25 % od pruzkumu ani
od zacatku behu. Globalni limit nebyl bez podkladu vymyslen. Volba a vstupni
soubor R1_RUN_OPTIONS.json zustavaji bajtove zachovane. Popis aktivni politiky
tento rozdil nyni uvadi. Puvodni pruzkumova autorita, mapovani populaci a
koeficienty 2,8 / 0,9 se v tomto kroku nevalidovaly ani nemenily.

R02: proposal_usable, solver_converged, uplnost nakonfigurovaneho hledani a
stacionarita jsou odlisene. Pouhe zlepseni objective neni dukazem konvergence.
Stacionaritu lze v nove vetvi potvrdit pouze pro konvergovany navrh, uplny
nakonfigurovany pocet skutecnych pokusu, jejich odmitnuti a overeny rollback.
Jde o konecnou nakonfigurovanou prohlidku, NIKOLI dukaz globalniho optima.
Zkracene, modelove, blokovane nebo chybove hledani ji nepotvrzuje. Vnejsi
DemandPolicy uz explicitni stationarity_confirmed=False neignoruje.

R03: primy STEP1 zustava na PLNEM assignmentu. Runtime metadata to explicitne
uvadeji. fa_enabled samo o sobe neni dukazem zkraceneho vypoctu. FASTASSIGN
nebyl narychlo zapojen do nove cesty bez akceptacniho overeni.

R04: sev_extend_early_horizon zustava podle existujicich options. Neni tvrzeno,
ze se zaver behu automaticky prepne do prisnejsiho rezimu. Samostatna finalni
metodicka brana nebyla bez konkretni autority novych prahu domyslena.

R05: podporovany tools/run_genfix2_checks.py spousti tri sady v oddelenych
procesech. Tim resi kolizi conftest bez prepisu chranenych legacy testu.
Nejde o tvrzeni, ze prosty pytest tests diagfast_tests nyni funguje v jednom
procesu. Puvodni nazvove kolize se obchazi explicitni procesni izolaci.

## 4. Skutecne vysledky testu

Prostredi: Linux, Python 3.13.5, numpy/scipy/pytest z dostupneho prostredi.
Testy volaji produkcni funkce, ale COM a assignment jsou simulovane.

| Sada | Proslo | Preskoceno | Selhalo |
|---|---:|---:|---:|
| Hlavni tests (vcetne 45 novych GENFIX2 pripadu) | 1380 | 4 | 0 |
| DIAGFAST | 138 | 0 | 0 |
| Auditni scenare pro novy kontrakt | 18 | 0 | 0 |
| Celkem | 1536 | 4 | 0 |

AST kontrola: 430 Python souboru, bez chyby.
DIAGFAST base: 1059 polozek; release: 91; V24917 runtime: 54;
V24916 runtime: 50. Vsechny hashe odpovidaji.

### Transparentni zmena testovaciho kontraktu

Puvodni nemeneny audit reprodukoval na GENFIX1 15 failed / 3 passed.
Na GENFIX2 nemeneny audit vraci 17 passed / 1 failed: A10 neoceka vyjimku,
protoze predpoklada normalni navrat z nebezpecne obnovy. Novy program spravne
vyvola explicitni pozadavek na manualni otevreni checkpointu a neprijme stav.

V kopii auditu je zmenen pouze A10: vyzaduje tuto vyjimku a nulovy pocet
accepted-state prechodu. Vysledek teto 18clenne sady je 18 passed. Puvodni
nemeneny test, oba logy a jediny diff jsou soucasti evidence. Netvrdime,
ze nezmeneny original audit prosel kompletne.

Ctyri existujici testovaci soubory V24917 byly aktualizovany: maji kompletni
povinna FP data, nevyzaduji vraceni zastarale diagnostiky ani stacionaritu bez
dukazu konvergence, a toleranci matic overuji samostatne na skutecnem diskovem
dukazu. Zadny novy test nebyl preskocen, zadny bezpecnostni prah zvetsen.
Puvodni 4 skipy zustavaji z historicke sady.

Nove testy zahrnuji materialni drift a poskozenou kopii matic, shodu os,
11D/segmentove/authority zmeny, transportni metadata, smisenou mobilitu na
huste siti skal, finalni preview pred zapisem, zive FP, nebezpecnou recovery,
KeyboardInterrupt, zachovani logu pri neuplnem ZIPu a cache/policy/counter
integraci. Kladne kontroly overuji i prijeti skutecne drobneho zaokrouhleni.

## 5. Spusteni a hranice overeni

Rozbalit cely novy ZIP do kratke cesty, napr. C:\R1. Nemichat soubory se
starym balickem. Vznikne C:\R1\R1_V24917_GENFIX2.
Ve Visumu rucne otevrit posledni overeny accepted checkpoint (.ver), nikoli
pokračovat v modelu po neoverene obnove. Spustit pres Scripts / Run script file:
01_SPUSTIT_V24917_GENFIX2.py

Launcher zachovava PREFLIGHTIOFIX1. Nezaklada novy Visum, automaticky nenacita
model a neobsahuje uzivateluv .ver. Nejde o novy vypocet kalibrace v tomto chatu.

Offline opakovani kontrol ze slozky balicku:
python tools/run_genfix2_checks.py --output C:/R1/GENFIX2_TEST_LOGS

Pred dlouhym bezobsluznym behem je stale potreba kratky zivy test ve Visumu:
(1) odmitnuty generation kandidat a obnova; (2) odmitnuty SUPPLYMIX a chyba
pred dalsim zapisem; (3) TD numericka rekonstrukce rodice; (4) mobilita blizko
hranice pri smisenych znamenkach; (5) shoda finalni diagnostiky s checkpointem.

Zivy Visum, Windows COM/pywin32 a realny assignment zde NEBYLY testovany.
Nezname provozni odchylky se nemaji resit rozsirenim toleranci bez dukazu;
novy build je radeji zastavi s diagnostikou. Offline PASS neni zaruka uplne
bezchybnosti vsech zdedenych modulu ani certifikace metodiky.

## 6. Obsah predani

GENFIX2_SOURCE_CHANGES.json - identity a uplny seznam zmen.
GENFIX2_SOURCE_DIFF.patch - produkcni/testovaci diff proti presnemu vstupu.
GENFIX2_VALIDATION.json - strojovy souhrn finalnich kontrol.
GENFIX2_PAYLOAD_MANIFEST.json - SHA-256 vsech souboru krom tohoto manifestu.
evidence_genfix2/ - protokoly, reprodukce a transparentni uprava A10.
00_START_HERE_V24917_GENFIX2_CZ.txt - hlavni aktualni startovaci navod.

Starsim navodum a reportum uvnitr baliku zustava historicka platnost pro jejich
verzi; pro tento build jsou nadrizene tento report a startovaci navod GENFIX2.
