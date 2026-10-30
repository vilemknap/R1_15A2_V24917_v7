# R1 V24917 – DIAGFAST relaxed semantic parity, 30. 10. 2026

## Scope

Branch derived from `codex/diagfast-bounded-numeric-parity-20261030` (commit
`acc85241cb4c322f6d1f9036de074393c5b077fc`), which in turn comes from
`codex/a0001-matrix-semantic-forensic-20261030`. This is a **diagnostic output
parity** change, NOT a model/Visum/TD/GEH acceptance-policy change.

The owner is `r1_15a2_diagfast_parity_v1.compare_artifacts()`, used by
`r1_15a2_diagfast_direct_v2.DirectGuard` for the initial FAST_EXACT–LEGACY
11D/12D comparison and each per-feature retry. No actual helper calculations,
Visum COM writes, assignment, rollback or cached paths were edited.

## New numerical parity

For finite JSON *float* fields and CSV decimal/exponent fields (not IDs):

```
abs(fast - legacy) <= max(0.001, 0.001 * max(abs(fast),abs(legacy)))
AND
abs(fast - legacy) <= 0.05 * max(abs(fast),abs(legacy))
```

The second condition prevents treating 100% differences in small nonzero
magnitudes as acceptable simply because the numbers are close to zero.

For a zero or sign crossing, both magnitudes must be <= 0.000001 and the
absolute difference <= 0.000002. Larger support/sign changes remain failures.
This numeric threshold belongs to **diagnostic implementation parity only**;
it must not be reused for scientific checkpoint hashes, protected profile
acceptance, TD objective, model GEH or odometry.

### SHA: relax equality of report outputs, not cryptographic identity

- Different SHA-256 values of canonical JSON/CSV outputs do NOT force LEGACY
  if their structure and scientific numeric content compare successfully.
  Both original SHA values are retained in the parity report.
- Whitelisted *derived diagnostic report* digest fields (`output_sha256`,
  `artifact_sha256`, `report_hash`, etc.) may differ **only if numeric fields
  in the same report can actually be independently compared**. Each tolerated
  SHA pair is logged with JSON/CSV path, both digests and reason.
- A report containing only a digest (or no numeric scientific content) cannot
  establish semantic parity and is rejected when the digest differs.
- Exact source/model/data identity remains mandatory: `source_ver_sha256`,
  `checkpoint_sha256`, `matrix_hash`, `state_hash`, `path_basis_hash`, cache
  SHA, release manifests, source code SHA and numeric/non-numeric IDs cannot
  be waived. No partial-prefix, Hamming-distance or truncated SHA comparison:
  SHA equality is binary; the *parity decision* can rely on proven content.
- Cosmetic differences in diagnostic text output (CRLF/LF, trailing horizontal
  whitespace and redundant terminal empty lines) are canonicalized before
  artifact SHA. Text numbers, paths, provenance, ID and scientific sentences
  otherwise remain exact. ZIP entries are still opened and compared one by one.

### Must remain exact

Present/absent artifacts, nested ZIP names, JSON keys/types, CSV schema,
row/column order, counts, source identifiers, frozen authority fields,
booleans, `PASS/FAIL`, approval and rollback statuses. Material numeric
changes still trigger the original feature-isolation retries, and ultimately
helper-scoped `LEGACY` only if retries fail.

## Evidence and audit

- New report schema `R1_DIAGFAST_PARITY_REPORT_V3` preserves `status`,
  `equal_artifacts`, `failures`, `legacy_sha256`/`fast_sha256` and adds
  `semantic_match_despite_sha_mismatch`, `tolerated_derived_digest_count`,
  `tolerated_derived_digests`, `canonical_sha_equal_artifacts`, thresholds and
  zero/sign policy.
- Numeric tolerance can still be disabled via
  `compare_artifacts(..., numeric_tolerance=False)` for forensic equality.
- Refresh both `DIAGFAST_V1_RELEASE_MANIFEST.json` and
  `V24917_RUNTIME_MANIFEST.json` using the existing developer-only tool.
  Release SHA integrity is ALWAYS strict.
- Validate in distinct offline processes:

```
python -m pytest -q -p no:cacheprovider diagfast_tests
python -m pytest -q -p no:cacheprovider tests
PYTHONPATH=.:tests python -m pytest -q -p no:cacheprovider genfix2_audit_tests
```

**Do not hot-patch a running Visum process.** A future restart with this
package and a real `DIRECT_PARITY_*.json` report is needed to establish
whether the three earlier 11D mismatches were cosmetic, numerical, derived
SHA, or material scientific drift. `LIVE_VISUM_NOT_RUN`.
