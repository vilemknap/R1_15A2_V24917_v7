# Live VISUM acceptance — V24915 PERF1

## Povinný benchmark

1. Start z `ACCEPTED_A_0009_cebb9c7a9349.ver`.
2. Stejný Visum build, stejné program options a stejná Procedure Sequence jako parent V24915.
3. Nejdřív zaznamenat parent V24915 wall-time pro alespoň jeden TD trial + rollback; potom stejný kandidát spustit v PERF1.
4. Ověřit shodu candidate writes, assignment gap, 498 modelových profilů, decision a post-rollback state hash.
5. Ověřit, že phase plan je `PHASE_SPECIFIC`, nebo že jasně eviduje bezpečný `FULL_SEQUENCE_FALLBACK`.
6. Ověřit, že rollback reuse nastane pouze při PASS semantic snapshotu a PASS 498×12 signature; jinak musí proběhnout plné diagnostiky.
7. Při COM/operation mismatch musí stav zůstat fail-closed a původní ACTIVE flags musí být obnoveny.

## Přijímací hranice

- žádná změna accepted/rejected výsledku;
- žádná změna IPF tolerance, assignment gap gate ani acceptance policy;
- parent checkpoint zůstává nedotčený;
- teprve živý benchmark může stanovit skutečný speed-up;
- do té doby `production_ready=false`.
