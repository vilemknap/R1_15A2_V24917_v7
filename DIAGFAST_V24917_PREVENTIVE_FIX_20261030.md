> **Historický záznam předchozí STRICT varianty.** Aktuální balík má omezenou numerickou toleranci popsanou v `DIAGFAST_V24917_BOUNDED_NUMERIC_PARITY_20261030.md`; text níže dokumentuje pouze starší variantu.

# V24917 DIAGFAST strict parity / targeted fallback repair

## Baseline and scope

This patch is based **only on the source ZIP uploaded by the user**:
`R1_15A2_V24917_v7-codex-a0001-matrix-semantic-forensic-20261030.zip`.
It is not a hot-reload instruction for the running PTV Visum calibration.

The archived `DEMAND_CYCLE_01_TD_FINECDF.zip` contains dynamic 11D evidence,
but **does not contain the original `DIRECT_PARITY_*.json` report** identifying
the three mismatched LEGACY/FAST artifacts. Consequently their precise live
scientific or provenance mismatch cannot yet be diagnosed from the uploads.
No claim is made that this patch eliminates that specific mismatch.

## Defect addressed

The old `r1_15a2_diagfast_direct_v2.DirectGuard` performed one strict parity
comparison. If FAST failed for *any* reason (including one 11D artifact
mismatch) and the old helper worked, it set one global `mode=LEGACY`. Both
independent diagnostic helpers then remained in slow LEGACY for the rest of
calibration, even if the other helper had already passed its own full parity.

## Implemented repair

1. Keep exact strict parity for all artifacts, with **no numeric tolerances,
   no arbitrary ignored files, and no bypass of missing artifacts**.
2. If and only if the full parity audit returns an **explicit artifact
   mismatch**, try individually disabling small, optional V2 features while
   executing the same complete LEGACY-vs-FAST artifact comparison:
   - 11D: `numpy_11d`, `bulk_11d_matrices`, `bulk_11d_countlocations`;
   - 12D: `bulk_12d_links`, `bulk_12d_countlocations`.
3. A reduced FAST configuration can be adopted **only after exact PARITY_PASS**.
   Reuse its feature limits on subsequent calls. User configuration is copied;
   existing disabled features are never re-enabled.
4. If parity still fails (or FAST raises for another reason), execute the
   affected helper using the original LEGACY implementation. The other helper
   retains its independently certified FAST status. If LEGACY fails too, the
   original error still propagates.
5. Preserve each strict parity attempt's `DIRECT_PARITY_*.json`, including
   specific failed artifact names, and log every decision and selected feature
   limits. `R1_DIAGFAST_INLINE_PARITY` remains enabled by default.

No COM model writes, source checkpoint or SQLite changes, no change to TG/TD,
GEH, IDP, acceptance, rollback, numerical target, or source scientific values.

## Tests / limitations

New regression module: `diagfast_tests/test_direct_feature_isolation.py`.
It tests an actual numeric mismatch in CSV + JSON, reduced-feature parity
recovery, irreparable parity failures, independent 12D/11D behavior,
source config immutability, FAST runtime failure and attempt limits.

The existing 11D helper was also exercised against the offline COM-shaped
fixture with three zones: **32 of 32 artifacts equal**, mode FAST_EXACT.
This fixture does not prove the same result against real Windows Visum 2026,
681-zone matrices and a live assignment.

**Do not replace files in an already running Visum process.** The current
Python interpreter may have cached the old modules. Apply this entire
re-sealed package at the next verified restart and inspect the new
`DIRECT_GUARD_*.jsonl` and `DIRECT_PARITY_*.json` records for the first 11D.
If 11D still falls back, the report will show the exact remaining difference
and 12D should remain independently FAST (provided it passes its audit).
