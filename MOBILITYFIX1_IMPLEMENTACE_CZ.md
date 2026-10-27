# MOBILITYFIX1 – audit posledniho behu a cileny hotfix

## Prokazane zive selhani
Posledni beh 2026-10-27 skoncil v cyklu 1 v GENERATION_DESIGN s `MOBILITY2_BLOCKED_DATA_NOT_A_PLATEAU` po uspesnem preflightu. Doslo k tomu pred prvnim kalibracnim pokusem; prijato 0 zmen, TD a Supply se nespustily. `RUN_STATUS.json` potvrzuje `live_matches_last_accepted: true` a `manual_reopen_required: false`. Vystup `V24917_MOBILITY_BLOCKED.json` obsahujici puvodni `exception_type:error` nebyl mezi predanymi logy, proto konkretni pricina blokady v tomto realnem behu nebyla z dostupnych podkladu prokazana.

## Potvrzena chyba ve zdrojovem kodu
`r1_15a2_mobility_guard_v24917.zone_productions()` overovala `ADD_PROD > 0` pred zjistenim, zda je soucet produkce vsech peti komponent v zone nenulovy. Domaci zona s nulovou produkci a nulovym multiplikatorem je bez vlivu na obe sumy R, presto vyvolala `MOBILITY2_INVALID_MULTIPLIER`. Oprava nejdrive striktne overi pet FP vstupu (finite, nezaporne), pak prispevek a preskoci pouze matematicky nulovou produkci. Pro nenulovou produkci zustava `ADD_PROD > 0` povinne, nefinite multiplier se odmitne vzdy.

## Potvrzena chyba v diagnostice
`_blocked_generation()` uchovavala puvodni vyjimku jen v hluboko ulozenem V24917_MOBILITY_BLOCKED.json. Vysledek GEN blok a hlavni traceback vracely pouze obecny retezec. Rozdelena faze `ZONE_AUTHORITY_READ`, `MOBILITY_OPTIONS`, `FLOWBUNDLE_MASK`, `MOBILITY_GUARD` a puvodni vyjimka se nyni promitne take do `GENERATION_BLOCK_RESULT.json`, do textu bezprostredni vyjimky a do standardniho run statusu. Nejde o potlaceni guardu; jakykoli neprokazany problem dal zastavuje.

## Nezmenene casti
Nativni TG/TD, segmentovy assignment, GEH, IDP, skimy, DD skoly/Long, 65/35 vs 60/40, pruzkumne autority, SupplyMix COSTFIX1, checkpoint/rollback a puvodni 248 kalibracnich/0 validacnich profilu zustaly beze zmeny. Kalibrace musi pri chybe zustat fail closed. Zadne .ver nebylo upravovano.

## Vedlejsi nalezy
DIAGFAST 11D parity selhala pouze u tri sumarizacnich artefaktu a program presel na LEGACY; toto nebyla fatalni chyba. Dalsi upozorneni o jednom linku s nulovou jizdni dobou jen vyrazuje linku z kalibracniho ADDVAL1. Zivy log nedoklada, ze by doslo k poruseni stavu predchoziho checkpointu.

## Overeni
Hlavni suite: 1456 passed / 4 skipped / 0 failed. DIAGFAST: 138 passed. GENFIX2 audit: 18 passed. Celem 1612 passed, 4 skipped, 0 failed (ve trech oddelenych behich). 67 cilene spustenych testu proslo (tyto jsou podmnozinou hlavni suite). SHA-256 manifesty aktualizovany v poradi DIAGFAST release -> V24917 runtime -> GENFIX2 payload. Presne 3 produkcni zdroje zmeneny. Skutecny PTV Visum 2026 nelze zde spustit, takze ziva validace otevrena.

## Kontrola po opetovnem spusteni
Pokud se bude opakovat `MOBILITY2_BLOCKED_DATA_NOT_A_PLATEAU`, poskytnout `GENERATION_BLOCK_RESULT.json` (nyni obsahuje `mobility_block`) a `V24917_MOBILITY_BLOCKED.json`. Tak bude zjevne, zda selhava maska, zonalni atribut, nulova aktivita, nebo samotna ochrana R. Nikdy nevypinat `mg_enabled` jen kvuli tomu, aby pokus prosel.
