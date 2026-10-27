# LIVE VISUM ACCEPTANCE - PERF2 R4

1. Open `ACCEPTED_B_0016_d1211a44ac4d.ver`.
2. Execute `R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py` from Visum Scripts.
3. Before any trial mutation require:
   - runtime preflight PASS,
   - sealed IDP authority ACTIVE,
   - semantic B0016 continuation selected,
   - accepted_count=16,
   - resume_outer_cycle=11,
   - resume_substep=TD_FINECDF_V17,
   - generation_replay=false.
4. Confirm 11D now reports ACTIVE targets for all required WORK/SERVICE/SCHOOL components.
5. Do not unlock Supply unless the unchanged coupled-demand convergence rule passes.
6. On any semantic/hash mismatch fail closed.
