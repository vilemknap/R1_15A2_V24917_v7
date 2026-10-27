# V24915 PERF2 R6 — non-finite diagnostic-reference hotfix

## Live failure reproduced from user run
R5 reached live baseline diagnostics and then failed in the PERF2-only
`CandidateReadbackManager.attach_diagnostics()` call.

The strict `canonical_hash()` uses `json.dumps(..., allow_nan=False)`, while the
returned live diagnostic payload contained a legitimate `inf` sentinel. The
exception therefore occurred after diagnostics, before cycle-11 TD continuation.

## Fix
Runtime file changed:
- `r1_15a2_candidate_readback_bundle_v24915p2.py`

New evidence-hash behavior:
- finite JSON-native payloads keep the exact previous SHA-256;
- `+inf`, `-inf`, and `NaN` are deterministically tagged only for the PERF2
  diagnostics-reference hash;
- the original live diagnostics object is not modified;
- unexpected unsupported serialization types trigger `BUNDLE_FALLBACK` and
  do not fail an otherwise valid legacy/live diagnostic result.

No calibration/acceptance logic was changed.

## Integrity pins updated
- candidate module SHA-256: `03778ff5da5398af2cf007b9f7f4077e376dde0812989753c00da300306ee4ff`
- runtime manifest SHA-256: `d32d02b878b12cbe6ecf1c662824689736dd0b2a5991d7b84353256914b450bc`
- config SHA-256: `6aad964325002c8d13c10412bce3f0242ee75fae3640214bc5ab8ec823edda56`
- safety module SHA-256: `8049bb7d460562f9c1e576dcfc3709658b6db7543876afdbe401ee7cc362daf4`

The internal package revision remains
`V24915_PERF2_R5_OVERNIGHT50_B0016_CONTINUATION` intentionally: R6 is a
runtime safety hotfix over the exact R5 calibration configuration.

## Tests
- Focused PERF2/R4/R5/R6/release suite: **72 passed, 0 failed**.
- Full suite, all 82 test modules in four batches: **862 passed, 4 skipped, 0 failed**.
- `compileall`: **PASS**.
- Runtime bundle deployment preflight: **PASS, 101 files checked**.
- R6 live-path synthetic regression drives `VisumAdapter.diagnostics()` with
  nested `+inf` and proves that the exact R5 failure no longer raises.

## Live status
`real_visum_tested = false` for R6 itself.
The source B0016 semantic authority is unchanged.
Next action: run the R6 package from `ACCEPTED_B_0016_d1211a44ac4d.ver`.
