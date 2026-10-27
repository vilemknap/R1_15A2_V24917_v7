# Live Visum acceptance — PERF2C

1. Open `ACCEPTED_B_0016_d1211a44ac4d.ver`.
2. Run the PERF2C launcher.
3. Require overlay preflight PASS and parent runtime preflight PASS.
4. Require first snapshot telemetry `PERF2C_SINGLE_PASS_PARITY_PASS`.
5. Require identical component hashes and `state_hash` to the parent full snapshot.
6. Record snapshot wall time, Operations.GetAll count and fallback events.
7. Any parity mismatch must use parent fallback; do not relax equality.
8. Do not claim live speed-up until measured in Visum.
