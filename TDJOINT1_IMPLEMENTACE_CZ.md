# TDJOINT1 nad GENFIX2 - implementace a overeni

Datum: 27. 10. 2026. Stav: OFFLINE_TESTED_LIVE_VISUM_VALIDATION_PENDING.
Jde o prvni omezeny prirustek, nikoli prepis celeho FineCDF nebo novy dopravni model.

## 1. Zamer a hranice zmeny

Dve nove oddelene vrstvy: r1_15a2_td_joint_v24917.py (skore a hledani) a
r1_15a2_td_joint_runtime_v24917.py (zapojeni a volitelne izolovane realizace).
Generation, SupplyMix, jejich akceptace a nativni distribuce se nemenily.
GENFIX2 transakcni ochrany zustaly zachovane. Vsech 1059 chranenych puvodnich
souboru a 24 souboru v authorities zustava bajtove stejnych.

Vychozi vaha zustava 65 % counts / 35 % pruzkum. Samostatny spoustec
02_SPUSTIT_V24917_TDJOINT1_60_40.py nastavi pro jeden beh 60/40 pres promennou
prostredi; po skonceni nebo vyjimce vrati predchozi hodnotu. Ostatni volby nemeni.
Nevytvari se validacni profily. Pojistka mobility [0.75, 1.25] a lokalni mez
TD IDP_after/IDP_before <= 1.25 jsou zdedene, nikoli nove nebo rozsirene.

## 2. Co se zmenilo

### Spolecne vnitrni skore

TDJOINT1 pouziva existujici Blend.stacked() s count rezidualem prave jednou:
F_inner = w_count * Q(M)/Q_ref + (1-w_count) * sum(J_c)/sum(J_c,ref).
Q je vazena kvadraticka chyba typu GEH^2 se zmrazenym jmenovatelem.
J_c je puvodni 512bodove FineCDF vcetne odchylky prumerne vzdalenosti.
Pri nenulovych referencnich chybach zacina F_inner na 1; count cast se neopakuje
za kazdou komponentu. Surove metriky komponent zustavaji oddelene, neprepisuji se.

Dulezite: neprovedlo se uplne sjednoceni vnitrni a vnejsi metriky. Vnejsi brana
stale pouziva skutecny vazeny prumer GEH a komponentove 11D po cerstvem assignmentu.
Je to zamerne mensi zasah. Presne znaceni surrogate versus live score je v logu.

### Male nativni sondy a vyber uvnitr existujiciho shortlistu

Zachovava se soucasna TD_ACTIVE_COMPONENT_MASK. V tomto shortlistu se zkousi
samostatne male plus/minus zmeny b a log(-c), v puvodnich mezich parametru.
Kazda sonda projde skutecnym nativnim TD; zadna matice se primo neprepise.
Poradi kandidatu se urcuje podle zlepseni spolecneho skore, nikoli jen chyby
samostatne komponenty. Vyhodnocuji se pritom vsechny dostupne FineCDF cile.
Pokud jsou dobre dva samostatne smery, jejich kombinace se opet nativne prepocita.
Nelze pouze secist jejich slibovana zlepseni. Pri nebezpecne kombinaci zustane
lepsi izolovany kandidat. Nejvyse dve slozky se takto kombinuji v jednom pollu.
Vaha counts zahrnuje podhodnocene i nadhodnocene kalibracni profily.

Nemenil se celkovy vyber shortlistu na novy globalni targeting vsech komponent.
Presne vozidlove prispevky po OD, novy kappa model a persistentni empiricky
Jacobian nejsou soucasti teto verze. FROZEN_PATHS dale pouziva zdedenou aproximaci
intenzit; nejde o zmereny assignment pri kazde sonde.

### Omezene samostatne realizace po odmitnuti kombinace

Puvodni plna realizace a backtracking bezi jako prvni.
Teprve po vysledku SOFT_REFERENCE_PLATEAU a uspesne overenem rollbacku muze
TDJOINT1 provest nejvyse dva dalsi izolovane komponentove pokusy, kazdy v meritku
1.0 vuci konecnemu vnitrnimu navrhu. Nejde o jednotkovou zmenu parametru.
Poradi izolaci je deterministicke podle nazvu komponenty; neni prezentovano jako
predikce jejich skutecneho izolovaneho prinosu. Prvni platny prijaty pokus ukonci
hledani. Kazdy je posouzen puvodni zivou akceptaci a pri odmitnuti obnoven.
Numericka chyba, neovereny rollback nebo vyjimka se nesmi premenit na plateau.
Pri soucasne navrzene zmene intrazonalni penalizace se izolace v teto prvni verzi
nepouziji; puvodni spojena BC+IZ realizace zustava beze zmeny.
Vnejsi pokusy jsou navic oproti puvodnimu limitu: obvykle nejvyse 3 + 2 kandidati,
plus nutne obnovovaci prepocty. Nejde o slib zrychleni kazdeho jednotliveho cyklu.

### Chybejici data a diagnostika

Pri kladne count vaze chybejici incidence nebo prazdna mapa aktivni rodiny
vyvola chybu; joint optimalizace neprejde potichu na pruzkum bez intenzit.
Castecne pokryti je stale zdedena aproximace, vykazane v logu; nova arbitrarni
mez pokryti se nezavadela. Zamerna nulova count vaha zustava explicitni volbou.
Telemetrie rozlisuje FROZEN_PATHS a DYNAMIC. Cerstvy assignment pri kazde vnitrni
sonde se netvrdi jen proto, ze existuje dynamicky skim.

Rozpocet vyhodnoceni a iteraci zustava z puvodni politiky. Zastaveni na rozpoctu
nema search_complete/stationarity_confirmed. Lokalni dokonceni muze nastat jen
po opakovanych uplnych kontrolach vsech aktivnich komponent, vcetne sond na
minimalnim polomeru, bez nativnich numerickych odmitnuti. To neni dukaz globalniho
optima. Vnejsi podminky konvergence a kontrola epoch zustavaji platne.

## 3. Prepinace (R1_RUN_OPTIONS.json)

- td_joint_enabled: true. false vrati puvodni vnitrni hledani a realizaci GENFIX2.
- td_joint_outer_isolates: true. false ponecha spolecne vnitrni hledani, ale bez
  dalsich plnych izolovanych realizaci.
- td_joint_max_isolates: 2. Povoleno 0 az 2; chybne hodnoty jsou odmitnuty.

Volby a vahy nemente za behu. Pro oddeleni ucinku algoritmu a vah je zaklad 65/35.

## 4. Overeni

Hlavni sada: 1431 passed, 4 skipped; 1435 sesbiranych pripadu, pokryti 1435/1435.
V tom je 51 novych regresnich pripadu TDJOINT1. DIAGFAST: 138 passed.
GENFIX2 audit: 18 passed. Celkem bez zapocteni opakovanych behu: 1587 passed,
0 failed, 4 skipped. AST: 435 Python souboru bez syntakticke chyby.

Velke monoliticke behy nebo subprocess-orchestrator v tomto prostredi opakovane
narazily na casovy limit nastroje. Nejsou vykazane jako PASS. Uspech cele sady je
dolozen dokoncenymi rozdelenymi pytest behy, JUnit protokoly a presnou kontrolou
jedinecnych testovacich identifikatoru proti novemu collect-only. Duvod timeoutu
nebyl jednoznacne prokazan. Audit vyzaduje PYTHONPATH s tests/; prvni pokus bez
nej skoncil chybou sberu, spravny opakovany beh dokoncil 18 testu. Puvodni testy
nebyly pro zeleny vysledek meneny.

Nove testy zahrnuji skutecny zpeceteny Runner.evaluate, nativni parametricky prostor,
kontroly marginal, DynamicFamilyMetrics, Blend a NPZ checkpoint. Druha integrace
pouziva skutecnou vnejsi realizaci, interpolaci, freeze kontrolu a rollback;
Visum/assignment a rozhodnuti adapteru jsou v tomto ridicim testu simulovane.
Je pokryto spolecne zhorseni dvou dobre vypadajicich kroku, zachovani dobre solo
zmeny, chyba incidence, limity, nekompletni poll, zmena vah mezi fazemi,
nesouhlas target planu, vypnuta vrstva, selhani rollbacku i 60/40 spoustec.

Zivy PTV Visum, konkretni Windows/COM a realne zlepseni kalibrace otestovany nebyly.
Stare evidence_genfix1/evidence_genfix2 v plnem archivu jsou historicke;
aktualni dukazy jsou pouze evidence_tdjoint1 a TDJOINT1_VALIDATION.json.

## 5. Prvni zivy test

Rozbalit do nove kratke cesty, napr. C:/R1/R1_TDJOINT1. Ve Visumu otevrit posledni
skutecne prijaty checkpoint .ver, pak novy launcher. Nevkladat soubory do slozky
jiz beziciho GENFIX1. Model .ver neni soucasti archivu. Launcher nespousti novou
instanci Visumu ani automaticky nenacita cizi model.

Zkontrolovat R1 TDJOINT1: ENABLED a zapsane vahy v TDJOINT_SUMMARY.json; sledovat
zmenu spolecneho vnitrniho skore a nasledne skutecny vysledek realizace. Zajimava
je situace kombinace odmitnuta / izolovana SERV nebo WORK prijata, nikoli pouhe
snizeni surrogate bez uspechu zive brany. Vyzkouset take odmitnuti obou a overeni
rodice. Tato verze neslibuje, ze predchozi SERV_E_noC samostatne projde.

## 6. Soubory pro diagnostiku

TDJOINT_SEARCH.json: kazda sonda, komponenta, plus/minus, skore, guard a kombinace.
TDJOINT_SCORE.json v EVAL slozkach: jednotne skore, vahy, metoda a pokryti incidence.
TDJOINT_SUMMARY.json: vyhodnoceni, rezim, mistni ukonceni a parametry ciloveho stavu.
TDJOINT_REALIZATION.json: kombinace a pripadne izolovane plne realizace.
TD_REALIZATION_ATTEMPTS.json: zachovane puvodni dukazy vcetne hierarchie izolaci.
V24916_FINECDF_INNER_RESULT.json: opravena souhrnna semantika a tdjoint sekce.

Prepinac umoznuje srovnani s GENFIX2; neni duvod vypinat ochrany nebo zvetsovat
akceptacni tolerance kvuli tomu, aby kandidati prosli.
