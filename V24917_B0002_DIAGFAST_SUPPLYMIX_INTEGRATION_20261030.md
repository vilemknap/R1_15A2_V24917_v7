# R1 V24917 B0002 - DIAGFAST and SupplyMix combined integration

**Integration base:** PR #1 commit `f7ba0a1b5af30d772b03e103443505cd15461bb6`.
This keeps the accepted B0002 restart, fresh native path-epoch smoke and
balanced TD SCHOOL/LONG candidate proposals unchanged.

**DIAGFAST:** imported production modules and tests from
`codex/diagfast-relaxed-semantic-parity-20261030`
(commit `e7b725837c00502012e53fd9dbde1b65f97f0a70`).
Semantic artifact parity uses 0.1% relative / 0.001 absolute tolerance, with
a smaller zero-crossing allowance. Selected *derived diagnostic* SHA mismatches
are permitted only with verified content; source/model/cache identities,
numeric structural shape and scientific decisions are not relaxed.
Retries reduced FAST features before per-helper LEGACY fallback.

**SupplyMix:** imported production fix and tests from
`codex/supplymix-incomplete-isolation-fix-20261030`
(commit `0e94d3be63cc8d60cc4d8f8df01eee6d1821b968`).
An unsuccessful, no-write SupplyMix search cannot turn a completed
Generation search into DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED.
It still blocks joint stationarity and preserves its own incomplete reason.
ADDVAL1 safety, native trial semantics and rollback are unchanged.

Both runtime and DIAGFAST SHA256 manifests are sealed for this ONE combined
tree; the SupplyMix isolated completion test is now included in the release
manifest, unlike the original source branch.

## Windows Visum validation sequence
1. Open the exact original accepted B0002 .ver from the original run.
2. Start `01_SPUSTIT_V24917_B0002_PATH_EPOCH_SMOKE_SILENT.py`.
   It runs native route enumeration but no TG/TD candidates.
3. Inspect smoke PASS, path support and source/hash evidence.
4. Reopen the exact same original B0002 .ver from disk.
5. Run `01_SPUSTIT_V24917_RESUME_B0002_CYCLE2_FRESH_EPOCH_SILENT.py`.
6. Inspect first DIAGFAST parity reports, SupplyMix own completion reason and
   TD SCHOOL/LONG candidate/rollback evidence from the actual Visum run.

Do not mix separate source branches or use an old runtime manifest.
The DIAGFAST parity tolerance is NOT a calibration acceptance tolerance.
Offline tests are necessary but do not verify Windows PTV Visum COM behavior.
