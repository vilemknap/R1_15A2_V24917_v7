# V2.4.7 real-run postmortem

Status: **FAILED** after 1951.235 s (32.52 min).

The expensive path export itself completed: 12/12 DSegs, 5,203,020 path rows, 53,470,275 path-link rows, and DSeg path-volume parity PASS.

The first model-side blocker was `PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:NATIVE_CW:7:7`. OD 7->7 is intrazonal, so it has no network path geometry and must not force re-enumeration. The subsequent forced refresh then reached cleanup of the previous SQLite and failed on Windows with a file lock.

No calibration candidate was accepted (`accepted_count=0`). The live model still matched the last accepted state and the source version remained unchanged.

V2.4.8.1 fixes both runtime defects and retains the V2.4.8 exact-state legacy-import path so this completed V2.4.7 cache can be reused if its exact-state and all-profile parity checks pass.
