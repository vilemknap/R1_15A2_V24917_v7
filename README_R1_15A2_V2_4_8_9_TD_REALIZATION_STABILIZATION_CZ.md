# R1 15A2 V2.4.8.9

## Účel

Oprava živě doloženého pádu po přijaté Generation změně, kdy FineCDF našel kandidáta, ale plná downstream realizace skončila na nativním 20B IPF `max_rel_err=3.495787955651562e-06`. Tolerance IPF se neuvolňuje. Místo toho se kandidát zmenšuje z téhož accepted parentu v souřadnicích `b, log(-c)`.

## Bezpečnost

- další Generation je zakázána, dokud TD realizace neskončí úspěšně;
- před každým pokusem se obnoví parent b,c;
- retry je povolen jen pro doloženou nativní IPF nonkonvergenci;
- ostatní chyby zůstávají fail-closed;
- 11D/12D evidence se kopíruje atomicky a při dlouhé cestě do krátkého `RUN/H/<token>` mirroru;
- staré absolutní stropy 3/10 zůstávají vypnuté;
- persistentní path cache V2488 je explicitně hashově autorizovaný predecessor.

## Launcher

`R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_9.py`

## Restart

Použij B_0000 před metodicky nečistým A_0001 z běhu se starými stropy.
