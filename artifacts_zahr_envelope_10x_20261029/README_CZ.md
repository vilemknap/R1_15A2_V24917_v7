# ZAHR: celkové pásmo 0,5–10 × počáteční hodnota běhu

Uživatelem schválená změna z 29. 10. 2026 pro aktivní V24917 řetězec:

| Koeficient | Nové celkové meze |
| --- | --- |
| ZAHR_PROD_WORK | 0,5–10 × jeho pevná počáteční hodnota běhu |
| ZAHR_ATR_WORK | 0,5–10 × jeho pevná počáteční hodnota běhu |
| ZAHR_PROD_SERV | 0,5–10 × jeho pevná počáteční hodnota běhu |
| ZAHR_ATR_SERV | 0,5–10 × jeho pevná počáteční hodnota běhu |

Po dříve připraveném resetu kladných koeficientů na 1 jsou tedy meze 0,5–10. Resetovací COM skript zůstává součástí kompletního balíku a nadále nastavuje referenci 1; rozšíření pásma ho nemění. Pro jinou počáteční hodnotu, například 8, jsou meze 4–80. Reference se nepřepočítává po jednotlivých cyklech.

V `r1_15a2_targeted_generation_v24917.py` je rozšířeno tvrdé pásmo i odpovídající REFINE soft pásmo, aby starý strop 2 neomezoval návrhy uvnitř nově povoleného pásma. Per-step stropy jsou zachovány: CATCH_UP +50 % / −20 %, REFINE +25 % / −20 %, před případným dalším zmenšením pokusu. Nulové/neaktivní zóny zůstávají zmrazené; rodič mimo pásmo může držet hodnotu nebo se vracet dovnitř.

Hraniční P/A objemy `P09F4_PER_PRE_*` / `A09F4_PER_PRE_*` dosud používaly stejné nastavení jako čtyři ZAHR koeficienty. Jejich dosavadní pásmo 0,5–2 × počáteční objem je nyní uchováno pod samostatným validovaným klíčem `boundary_reference_multiplier`; adaptér používá tento klíč. Rozšíření čtyř ZAHR koeficientů tedy nerozšiřuje pásmo objemových vstupů hraničních přechodů.

Nemění se domácí koeficienty, SCHOOL, LONG, FOREIGN, supply, akceptační politika ani rollback. Zachována je způsobilost ZAHR větve podle NOT_ZAHR, ZAHR_SUSED a POP_ZP. Historické chráněné zdrojové soubory nejsou měněny; aktivní runtime používá nové zapečetěné V24917 nastavení.

Ověření zahrnuje skutečný návrh všech čtyř koeficientů v CATCH_UP i REFINE, pevné reference 1 a 8, růst přes starý strop 2, dosažení nového stropu 10, zachování dolní meze, nul a chování rodiče mimo pásmo. Samostatný test ověřuje skutečné napojení adaptéru na nezměněné pásmo hraničních P/A. Přiložené `CHECKS.json`, `RESULTS.json` a logy obsahují výsledky offline sad. Patch zahrnuje veškeré změny zdrojů, testů a manifestů oproti předchozímu balíku.

Instalace: použij kompletní GitHub ZIP této větve, ne směs starých a nových Python souborů. Spouštění zůstává přes stávající kalibrační launcher. Živý Visum se zde nespouštěl (`LIVE_VISUM_NOT_RUN`).

První celá sada odhalila v novém hraničním testu odkaz na modul uchovaný při sběru testů, zatímco startovací testy modul znovu načítají. Test byl opraven, aby upravoval skutečný `adapter.bdgen`; produkční kód kvůli tomuto selhání nebyl měněn. Původní selhání je zachováno v `prior_attempt/`.

Závěrečné ověření: 72 cílených testů; hlavní sada 1 930 prošlo a 4 přeskočeny; DIAGFAST 138 prošlo; audit 18 prošlo. Manifest runtime obsahuje 73 souborů a release 135; všechny hashe souhlasí. Ověřeno všech 1 059 chráněných původních souborů. `git diff --check`, kompilace změněných modulů i zpětné ověření patche prošly.
