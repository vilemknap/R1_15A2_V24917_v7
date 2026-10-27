# MOBILITYZONE1 - dokonceni zonalni ochrany produkce

Zaklad: R1_15A2_V24917_SAFETYFIX2_LONGGUARD1_20261027_FULL.zip.
Datum: 2026-10-27. Zivy Visum ani Windows COM zde nebyly k dispozici.

## Obnova prerusene prace

V aktualnim prostredi se zachovala dokumentace rozpracovaneho MOBILITYZONE1,
ale nikoli jeho Python moduly a testy. Implementace byla znovu sestavena nad
poslednim fyzicky dostupnym, CRC overenym LONGGUARD1. Drive uvadene vysledky
nedokoncenych testu nejsou prevzaty; vsechny zde vykazane testy byly spusteny znovu.

## Co presne pojistka chrani

Kazda domaci zona x rodina WORK / SERVICE / LONG / SCHOOL ma vlastni referenci.
Kontroluje se hruba domaci produkce osobocest FP pred prevodem na vozidla,
symetrizaci a pripocitanim syntetickeho hranicniho P09F4. Nejde o soucet prujezdu
vozidel pres scitaci profily ani o pocet nakladnich vozidel.

Pro zonu z a skupinu g plati:

    P_ref[z,g] = FP_parent[z,g] * coefficient_ref / ADD_PROD_parent[z]
    r[z,g] = FP_live[z,g] / P_ref[z,g]

Referencni koeficienty (nikoli koeficienty ze zacatku behu):

| Rodina | Atribut | Referencni hodnota |
|---|---|---:|
| WORK | ADD_PROD_W | 1.0 |
| SERVICE | ADD_PROD_S | 1.0 |
| LONG | ADD_PROD_L | 0.2 |
| SCHOOL | ADD_PROD_SCH | 1.0 |

Puvodni vzorce, H, socioekonomicke vstupy a faktory AMDY zustavaji zachovany.
Reference je rovnice AMDY pri kanonickem koeficientu, NE neupravena empiricka
hybnost z pruzkumu. Technicke zhrnutie AMDY, tabulka 13, uvadi deleni 2.8,
SERVICE navic faktor 0.9 a LONG faktor 0.2. Tyto faktory se nesmeji vydavat za
pocet osob v aute nebo zamestnavat dalsim delenim. Guard zadne H neprepisuje.

Pevny referencni vektor FP se drzi v ramci behu; dalsi cyklus jej neprecentruje
na nove kalibrovane koeficienty. Zmena FP/ADD_PROD znamena zmenu zakladni rovnice
nebo dat, ktera se nesmi tise povazovat za novou referenci. Numericke porovnani
reference pouziva atol=1e-7 a rtol=1e-10, nikoli dalsi metodickou toleranci.

Tolerance poctu cest je [mg_min_ratio, mg_max_ratio], vychozi [0.75, 1.25].
Jde o limit proti pevne referenci, NIKOLI o povoleni opakovane pridavat 25 %
za kazdy cyklus. Puvodni agregatni MOBILITY2 pro WORK/SERVICE zustava dalsi brana.

## Uz existujici odchylky a nuly

Pokud zona zacina mimo pasmo, smi zustat beze zmeny nebo se priblizovat pasmu;
nesmi se vzdalovat ani preskocit za opacnou hranici. Napriklad 1.8 -> 1.7 ano,
1.8 -> 1.9 ne. Neni zavedeno nucene prenormovani vsech koeficientu pri startu.
Takovy parent je explicitne vykazan jako target_satisfied=false. Neni to dukaz,
ze model uz splnuje +-25 %. Dokud reference neni plna nebo ma parent odchylky,
cyklus neosvedcuje uplnou stacionaritu a stavajici politika muze pokracovat.

FP=0 pri kladnem koeficientu je znamy nulovy zaklad: dalsi FP musi zustat nulove.
FP=0 a koeficient=0 nedava dovoleni delit malym epsilon ani vymyslet hybnost.
Takova produkcni promenna se zmrazi. Kladne FP s nulovym koeficientem je chyba dat.
Negativni/NaN/nekonecne hodnoty nejsou nahrazeny nulami.

## Tri mista zapojeni

1. Navrh: jednotlive WORK/SERVICE produkcni log-kroky se omezi jeste pred
   agregatnim MOBILITY2 a vyvazenim P/A. LONG zustava jedinym globalnim krokem:
   pouzije se nejprisnejsi povolena velikost mezi jeho domacimi zonami.
   SCHOOL se omezi po zonach. Nezavadeji se nezavisle zonalni LONG kalibrace.
2. Tesne pred zapisem: finalni kandidati po maskach, mezich a P/A vyvazeni
   museji projit zonalnim i agregatnim overenim. Puvodni FP a koeficienty se
   znovu nactou pred prvnim COM zapisem; stary plan se neaplikuje na jiny parent.
3. Po nativnim prepoctu: skutecne FP se porovnaji s pevnym jmenovatelem,
   u WORK/SERVICE/LONG samostatne pro pet skupin a take souhrnne za rodinu.
   SCHOOL ma jeden dostupny FP_5_SCHOOL, ne pet fiktivnich cilovych skupin.

Pouha spravna hodnota ADD_PROD nestaci: zmena FP pri stejnem koeficientu se
odhali. Zameny mezi skupinami se nesmeji skryt ve stejnem souctu. Pokryti zon,
domaci maska a navaznost reference zustavaji kontrolovane.

## Pokracovani a ochrana stavu

Nedostupne volitelne LONG/SCHOOL FP se cte existujicim striktnim COM readerem
s omezenym retry. Neuspech odlozi dotcenou rodinu, zmrazi jeji PROD/ATT navrhy
a ponecha ostatni rodiny. Neni oznacen za overenou konvergenci. Po uspesnem
ziskani dat v dalsim cyklu lze rodinu opet vyhodnotit, pokud je LSGEN aktivni.

Nevyhovujici finalni kandidat se odmitne; pouzije se stavajici backtracking
nebo overeny rollback. Zonalni guard nevola LoadVersion, nevytvari novou instanci
Visumu a nezapisuje primo do OD matic. Skutecne neoveritelny parent/rollback
stale nesmi byt automaticky prohlasen za bezpecny.

## Predikce po omezeni kroku

LSGEN vraci svuj linearni operator G a jeho promenne. Po omezeni kroku se jeho
predikovany efekt prepocita pro skutecne pouzitelne kroky. Neni vydavan puvodni
solverovy odhad za odhad omezeneho kandidata. Pokud operator chybi, predikce
je explicitne nedostupna a stavajici STEP1 pouzije merene pokusy. Puvodni
solverovy pomer zustava oznaceny jako raw_solver; neupraveny pomer neni publikovan
jako finalni. Finalni akceptaci stale rozhoduje nativni assignment a diagnostika.

## Rozsah kodu

Novy modul: r1_15a2_mobility_zone_v24917.py.
Upravene produkcni moduly: r1_15a2_trial_adapter_v24917.py (zapojeni),
r1_15a2_long_school_generation_v24917.py (publikace efektoveho operatoru).
Novy test: tests/test_v24917_mobilityzone1.py, 60 pripadu.
Aktualizace: DIAGFAST release, V24917 runtime a GENFIX2 payload manifest.
R1_RUN_OPTIONS, vsech 24 autorit a chraneny zaklad 1059 souboru beze zmeny.

## Vystupy

- DESIGN/V24917_TARGETED_GENERATION/MOBILITYZONE1_PARENT.json:
  pevne reference, produkce, pomery, out_of_band, unavailable, target_satisfied.
- V24917_FIT_SUMMARY.json -> mobilityzone1: omezene navrhy a odlozene rodiny.
- GENERATION_PREVIEW / GENFIX2_FINAL_MOBILITY_AND_PREDICTION.json:
  mobilityzone1 uvnitr mobility/genfix2_mobility.
- GENERATION_BLOCK_RESULT / ACCEPTANCE: mobility_guard_live.mobilityzone1:
  skutecne FP po realizaci, reference, pomery a konkretni poruseni.

## Testy a meze dukazu

Viz MOBILITYZONE1_VALIDATION.json a evidence_mobilityzone1/. Hlavni sada je
spustena v sedmi oddelenych procesech a porovnana s uplnym seznamem testu.
Zachovana zdedena testovaci kolize identity SupplyContractError pri hromadnem
reloadu modulu je izolovana samostatnym procesem TDROLLBACKFIX1; jeji kontroly
nejsou vypnute. Prvni kombinovany pruzkumny beh obsahoval i opraveny problem
manifestu a prazdne autority. Neni vykazovan jako PASS. DIAGFAST je oddeleny
kvuli zdedenemu conftest/import kontextu. Audit vyzaduje root a tests v PYTHONPATH.

Oprava nepredstavuje nezavisle overeni spravnosti vsech H, jednotek a vlozenych
rovnic v konkretnim zivem modelu. Hlida raw domaci TG FP, nikoli sama o sobe
vsechny finalni radkove soucty po TD balancing, boundary prefeed a symetrizaci.
Neresi konverzi prumerneho pracovniho dne na RPDI ani znovu neodhaduje mode share.
Krivek delky cesty samotnych nelze pouzit k odvozeni celkoveho poctu cest.

Zachovany LONGGUARD1 hlida delkovou pripustnost a tvar LONG; neodstranuje existujici
kratke LONG OD. Nativni strukturirani LONG 100+ support a aktivni TDLONG1
zustavaji dalsi samostatnou ulohou, nejsou deklarovany jako vyresene timto patchem.
