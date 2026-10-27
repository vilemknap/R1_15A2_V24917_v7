# LONG produkce: mez kalibracniho koeficientu 0,10–0,30

Rozhodnuti uzivatele ze dne 2026-10-28 stanovi odbornym odhadem absolutni
kalibracni rozsah `ADD_PROD_L` pro kazdou domaci zonu na **[0,10; 0,30]**.
Pevna reference AMDY zustava **0,20**. Relativni rozsah proti teto referenci je
**[0,5; 1,5]**; nejde o rozsah relativni k posledni prijate hodnote ani o
omezeni `ADD_ATT_L`.

`MOBILITYZONE1` pouziva tento rozsah pro LONG pri posouzeni vychoziho stavu,
projekci produkcniho kroku, kontrole finalniho kandidata i po nativnim
prepocetu `FP_3_LONG_*`. Pro WORK, SERVICE a SCHOOL zustava stavajici pasmo
`mg_min_ratio`–`mg_max_ratio`, momentalne [0,75; 1,25]. Referencni `FP` se
v ramci behu neprecentruji. Zona s rodicovskou hodnotou mimo rozsah muze zustat
beze zmeny nebo se priblizit k rozsahu, nesmi se vzdalit dale.

`ls_long_envelope_ref` v `R1_RUN_OPTIONS.json` a jeho programove vychozi
hodnoty jsou sjednoceny na [0,5; 1,5]. Samotna aktivni tvorba LONG kroku
zustava zmrazena (`long_generation_permitted=False`), dokud neni dolozen
nativni OD filtr a zivou zkouskou overena odezva TG/TD/20A/20B. Offline
zonální fit prijima meze od volajiciho a nevydava aplikacni kroky. Tato zmena
proto nezapina LONG, nespousti Visum a nemeni zadne OD matice.

V dodanem exportu modelu je `ADD_PROD_L = 4,383411` ve vsech 681 zonach.
Rozsah [0,10; 0,30] nepredpoklada, ze uz probehl rollback na 0,20; pred
aktivni kalibraci je potreba vycist a overit skutecny aktualni stav.

Offline overeni v tomto zdrojovem stavu: 179/179 cilenych testu PASS, vcetne
kontroly obou hranic LONG, navratu z hodnoty nad pasmem, zmeny jen jedne zony,
finalniho kandidata, `FP` readbacku, ostatnich rodin, LONG zmrazeni a runtime
instalace. Zapeceteno 66/66 V24917 runtime souboru; 1 059 puvodnich zdroju
overeno beze zmeny. Zivy Visum/COM test nebyl spusten.
