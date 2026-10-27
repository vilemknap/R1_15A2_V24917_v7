# V2.3.8 integration / evidence boundary

## Data model

Geometry key: `(parent_snapshot_hash, mode, orig, dest, PathIndex)`.
Volume key: `(geometry_id, normalized_DSeg_code)`.
Directed edge key: `(LinkNo, FromNodeNo, ToNodeNo)`.

The complete parent key set is freshly scanned for EVERY approved DSeg. Sets
are compared exactly, independently of COM presentation order. All numerical
Vol(AP) readbacks are stored separately, including zeros. Geometry is scanned
for one explicit representative per mode, with exact parent membership checks,
index checks, topology checks, complete coverage and an ordered-sequence digest.
Representative geometry is stored as little-endian uint32 edge-dictionary IDs.
Compressed inverse edge postings preserve route IDs and exact multiplicities.

## Provisional assumption, not an identity proof

The user's 15R samples and 15S full parent scans are preserved verbatim under
`provenance/two_mode_live_evidence`. They do NOT authorize full geometry reuse
for production. The requested experimental reuse is implemented for design only.
Same-run sample checks are repeated before every new full geometry scan. A
mismatch is fatal; there is no silent per-DSeg fallback or exception-based alias.

Only representative sequences have been fully read. All path exposure and
GENERATION incidence for other same-mode segments are CONDITIONAL on the
sharing assumption. This remains true even if all matrix/profile parity checks
pass. Both new entrypoint and adapter prohibit APPLY, assignment and reload.
Old candidate confidence labels are retained as representative-only evidence and
replaced with an explicitly provisional overall confidence.

## Numerical preservation

The branch extraction and candidate solver in `r1_15a2_sequence_v23.py` are
unchanged. Numerical generation/distribution routines in `r1_15a2_core.py` and
`r1_15a2_multiblock.py` are unchanged. The V2.1 coordinator gains an optional
precomputed incidence input, permitted only for design, plus phase callbacks.
No fitting, calibration targets or tolerances are changed.

Full profile flow: sum over DSeg volumes times exact stored directed-edge
multiplicity, summed over the approved directional scope of each observation.
For BOTH profiles, both directed keys are included, without halving observations.

Generation catalogs retain the same OD totals and zero-flow keys. The sparse
coefficient for relative OD guidance is `sum_r q_r * count(r,profile)`, not a
binary occurrence and not a geometry-only share. Projection base catalogs include
non-actuatable relations as in the original core. Optional cordon-pair incidence
is explicitly unsupported by the new cache rather than silently approximated.

No cross-run cache reuse is permitted. Snapshot checks and pre/post matrix
fingerprints guard in-run reuse. Historical GAP is not a freshness proof.

## Operational boundaries

Default cooperative run deadline: 1800 seconds. This is not a thread-killing
watchdog; a synchronous host COM/SQL/solver call can overrun until it returns.
Budget expiry or a STOP_REQUESTED file prevents subsequent design blocks, checks
model immutability, and never invokes LoadVersion. No background COM thread is
started. Progress is atomic file output; there are no Python confirmation windows.

The new read-only adapter replaces a .ver save with a JSON snapshot, avoiding a
change to IO.CurrentVersionFile. That JSON is NOT a restorable Visum version.
A new run directory and a run lock prevent file replacement/concurrent starts.
Partial caches remain visibly failed/stopped and are not reusable.

The geometry loop is reduced from 12 full DSeg scans to two full representative
scans, plus small 12-DSeg sample checks. Parent/volume scans remain 12. Total
speedup is NOT necessarily sixfold and has not been measured in live Visum.

## Source basis

- User 15P: live bounded FirstObject/LastObject dispatch and OD diagonal readbacks.
- User 15Q: limited live page throughput, not full-run wall time.
- User 15R: three bounded same-mode geometry windows, not global identity.
- User 15S: complete same-mode parent sets, segment-specific volumes, explicitly
  unverified full geometry.
- Prior uploaded V2.3.7 15P streaming/offdiagonal source package, exact parent
  SHA256 recorded in V238_SOURCE_INTEGRITY.json.

No new external COM interface was assumed: the bounded dispatch and explicit
column/SetObjects shapes are the same as in the successful live probes.
