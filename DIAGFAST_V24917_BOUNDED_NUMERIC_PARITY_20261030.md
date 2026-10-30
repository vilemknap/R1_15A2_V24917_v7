# R1 V24917 DIAGFAST — bounded numerical parity

**Baseline:** exact full package `R1_V24917_DIAGFAST_STRICT_FEATURE_ISOLATION_20261030.zip`, based on the user's running `codex/a0001-matrix-semantic-forensic-20261030` source archive. This patch changes only parity comparison, its DIRECT decision/report metadata, relevant regression tests and source identity manifests. It does not change the helper's computational implementation or Visum COM writes.

## Why and what changed

Old `compare_artifacts()` accepted only an identical SHA-256 of the normalized JSON/CSV payload. A single last-bit floating-point difference forced fallback to LEGACY, although all scientific quantities could be equivalent. User authorized relaxing *numerical* parity (2026-10-30). Non-numerical identity remains strict.

The new default acceptance for two finite floating-point values `x`,`y` (JSON **float** vs **float**, or CSV **decimal/exponent** cells in non-identity columns) is:

```
abs(x-y) <= max(1e-8, 1e-9 * max(abs(x),abs(y)))
AND
abs(x-y) <= 1e-6 * max(abs(x),abs(y))
```

The second bound prevents large **relative** drift near zero despite the absolute tolerance. Identical `+0.0` and `-0.0` pass as zero; zero vs **any** nonzero fails, as do sign changes, NaN vs finite and changes of infinity. There is no rounding of the actual output or its scientific values. Floating-point values are never silently replaced by their LEGACY counterparts.

**Still exact:** filenames, artifact presence, ZIP membership, JSON object keys, array lengths and ordering, JSON types, CSV header/row count and ordering, integer values, booleans, codes and IDs (even decimal-formatted numbers in identity fields), SHA/digests, status/decision fields, text, binary data and normalized provenance fields. Full scientific text, including any embedded numbers, is compared exactly. A material numeric difference still fails and triggers narrowed FAST feature retries and ultimately helper-scoped LEGACY fallback.

The JSON parity report now uses schema `R1_DIAGFAST_PARITY_REPORT_V2` while preserving `PARITY_PASS` / `PARITY_FAILED` and the `equal_artifacts` / `failures` interface. It also contains:

- `numeric_tolerance` with absolute/relative thresholds and the exact rule;
- `byte_equal_artifacts`, `tolerated_artifacts`, `tolerated_value_count`;
- maximum tolerated absolute and relative difference;
- per-artifact `tolerated_examples` (up to 10 paths and values) and strict mismatches (up to 30).

For byte-for-byte forensic comparisons, the public `compare_artifacts(..., numeric_tolerance=False)` switch retains the previous strict behavior. The DIRECT guard explicitly opts into bounded parity and records tolerance in its startup certificate, INLINE_PARITY_REPORT and INLINE_PARITY_PASS events. It retains independent 11D/12D fallback and every existing feature-isolation retry; the search never disables full schema checks.

## Limitations and operating rules

This patch is **not** a calibrated scientific accuracy threshold; the adopted `1e-8`/`1e-9` bounds are conservative engineering defaults for comparing alternative read-only diagnostic implementations. GEH/IDP/TD targets and acceptance/rollback policy are unchanged. The numeric parity only certifies scientific comparability within the documented limits, **not** bitwise identity. Unchanged status/decision fields must remain exactly equal.

The original live `DIRECT_PARITY_*.json` for the reported three mismatches was not included in the user's TD archive. If mismatches were in text provenance or structural fields, this relaxation deliberately will NOT resolve them. A live Visum check is still needed; numerical results in the running process won't change until a verified restart. Do not edit/import modules in the current Visum process.

## Validation contract

Run three offline suites separately (their `conftest.py` modules can conflict):

```
python -m pytest -q -p no:cacheprovider diagfast_tests
python -m pytest -q -p no:cacheprovider tests
PYTHONPATH=.:tests python -m pytest -q -p no:cacheprovider genfix2_audit_tests
```

The new tests cover 1-ULP differences in both JSON and CSV, larger 681-zone-style volumes, strict support-zero/sign/ID/structural handling, ZIP recursion, nonfinite values, missing artifacts, explicit strict mode and bad tolerance configurations. Test status is published separately; the Windows PTV Visum COM run remains **NOT_RUN** in this development environment.
