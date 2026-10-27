# V2.4.8.9 implementace a testy

## Implementace

- TD realization backtracking v `b, log(-c)`;
- parent restore před každým pokusem;
- pouze IPF nonkonvergence je retryable;
- žádná relaxace nativní tolerance;
- explicitní pending gate TG -> TD;
- atomické kopírování 11D/12D evidence;
- centrální krátký mirror pod run rootem.

## Core test gate

Před release wiring prošlo 636/636 testů. Finální source-tree regrese prošla **640/640** testy; `compileall` prošel.
