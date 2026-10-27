# V24916 FRESH0 UNIVERSAL_VER IOFIX3/PATHFIX3 - implementation and test report

Release: `R1_15A2_V24916_PERF2C_PROFILE488_FRESH0_UNIVERSAL_VER_ISOLATED_ACTIVE_TARGETING_IOFIX3_PATHFIX3_CACHE_DISABLED_20261022`

## Universal source baseline

There is no package-baked semantic-state hash gate. The currently opened `.ver` becomes the fresh baseline after fail-closed live structural compatibility checks. Its semantic hash is captured dynamically as provenance and is required to remain unchanged only between preflight and calibration handoff.

The live preflight checks all 488 PROFILE488 CountLocations read-only (NO, R1_OBS_RPDI, LINKNO/FROMNODENO/TONODENO), plus DSegs, zone order, DIST_KM, FlowBundle DIRECTED/BOTH samples, PERF2C snapshot parity and runtime manifest.

## Other retained properties

- accepted_count=0, outer_cycle=1
- persistent path cache disabled
- parallel V24915 isolation retained
- Generation FlowBundle + TD component targeting active
- IOFIX3/PATHFIX3 retained
- acceptance mathematics unchanged

