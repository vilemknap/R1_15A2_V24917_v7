# V2487 live failure → V2488 remediation

## Pozorovaný pád

Reálný V2.4.8.7 run skončil v demand cycle 1 před Generation návrhem chybou
`PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH:config_sha256`. `accepted_count=0`,
Generation ani TD nebyly dokončeny a Supply nebyla spuštěna. Proto mohl adresář
`GENERATION_CACHE` zůstat prázdný nebo bez očekávané restore evidence.

## Kořenová příčina

Persistent path cache kontrakt používal SHA celého release configu jako exact
identitu. V2487 změnila Generation coefficient authority, a tím změnila config SHA,
i když uložená route geometry a profile/link path semantics zůstaly stejné.
Compatibility registry navíc nebyl založen výhradně na přesných deployovaných
release archivech; konkrétně skutečný V2482 ZERO_VOLUME_SUPPORT config SHA je
`339dc5d273e780e2d6edf0785353483a7e1a03ed459875feacc15cb17c33d6ec`.

## Oprava

V2488 ponechává full config SHA jako provenance. Restore autorizují explicitní
path semantic fields. Když se liší path implementation, source release musí být
reviewed a musí přesně sedět celý sedmimodulový source implementation map.

Cache, která je pouze semanticky nekompatibilní, je nyní performance miss a
běh smí pokračovat legacy exact-state importem nebo fresh enumeration. Integrita,
SHA, binding, immutable network context a path basis hashe zůstávají hard fail.
