# V2.4.7 path-enumeration benchmark

Toto je offline syntetický benchmark počtu požadavků na path enumeration. Není to měření wall-time v PTV Visum.

## Malý kompletní fixture

Obě politiky vyžadovaly 3 enumerace:

- V2.4.6 model: initial + invalidace po accepted stavech;
- V2.4.7 model: initial + povinné čerstvé ověření demand plateau + povinné čerstvé ověření Supply plateau.

To je záměrné: V2.4.7 nešetří finální ověřovací enumerace.

## Stress fixture s 12 po sobě přijatými demand stavy

- V2.4.6 invalidation model: 12 enumeration requests;
- V2.4.7 frozen epoch: 1 enumeration request;
- rozdíl: 11, tedy 91,67 %.

Oba běhy měly stejný stav, stejný počet přijatých změn a stejný počet assignment/recompute volání. Fixture izoluje pouze životní cyklus path cache.

Přesná data jsou v `V247_PATH_ENUMERATION_BENCHMARK.json`. Reálný přínos závisí na počtu accepted stavů mezi plateau refreshi, rychlosti COM list exportu, disku a konkrétním Visum modelu.
