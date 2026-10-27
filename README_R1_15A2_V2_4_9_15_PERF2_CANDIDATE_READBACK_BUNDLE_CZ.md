# R1 15A2 V24915 PERF2 — CandidateReadbackBundle

This release is an additive exact-safe performance descendant of V24915 PERF1.

## Purpose

Read each unchanged candidate state once through the legacy Visum COM authority, hash it, and reuse the resulting immutable payload only while the exact session/run/parent/block/candidate/mutation/assignment identity remains current.

## Safety rule

`NO PROOF → NO REUSE`

`READ ONCE → VERIFY → HASH → REUSE ONLY INSIDE THE EXACT SAME STATE`

Every model write and every procedure execution invalidates the bundle before the side effect. Stale, incomplete or tampered bundles are rejected. The original live snapshot and live 12D/11D paths remain the fallback authorities.

## Offline gate

- focused: 61 passed;
- full regression: 844 passed, 4 skipped, 0 failed;
- compileall: PASS;
- exact snapshot parity: PASS;
- fault injection: PASS;
- live Visum benchmark: pending.

The release is **not production-ready** and must be live-benchmarked from `ACCEPTED_A_0009_cebb9c7a9349.ver`.


## R2 runnable hotfix

- celý runtime je dodán přímo v jednom rozbalitelném stromu;
- launcher se spouští z Visum `Scripts -> Execute script file`;
- run root byl opraven z `R1_15A2_V24915_PERF1_RUNS` na `R1_15A2_V24915_PERF2_RUNS`;
- package revision: `V24915_PERF2_CANDIDATE_READBACK_BUNDLE_R3_LIVE_CTOR_HOTFIX`;
- kalibrační matematika CandidateReadbackBundle nebyla změněna.
