# R1 V24917 — LONG diagnostic epoch repair (2026-10-30)

## Incident
Runtime: cycle 1, Generation STEP1 trial 2 accepted (scale 0.538158).
TDJOINT baseline failed with `LONG_INCIDENCE_ASSIGNMENT_BINDING_STALE_OR_MISSING`.
The subsequent TD rollback itself returned `VERIFIED_PARENT` with
`snapshot_equal=true`, `diagnostic_equal=true`, `parent_equivalence.passes=true`.
Run ended `FAILED_MANUAL_REOPEN_LATEST_ACCEPTED_REQUIRED`.

## Root cause
V24917 binds LONG incidence to a completed assignment and current skim during
`_refresh_dynamic_skims_after_assignment`. Inherited PERF2 `diagnostics()`
invalidates potential CountLocation UDA writes, incrementing
`readback_manager.mutation_epoch`. An unchanged assignment then fails the
binding equality check *before the first TDJOINT native evaluation*.

## Fix
V24917 `VisumAdapter.diagnostics` captures a strict live parent snapshot only
when a valid completed LONG binding exists. After the inherited diagnostics it
requires: same assignment epoch, skim hash, token, zone-order hash; precisely one
expected mutation-epoch increment; exact semantic snapshot equality (including
the V24917 intrazonal penalty fields). Only then does it call the existing
`bind_after_assignment` to renew the binding. Missing or stale binding is
never repaired; actual model/skim/assignment drift fails closed.

No direct matrix writes, LoadVersion, changed TD parameters, gate relaxation, or
modification to sealed FineCDF target occurred. The V24917 runtime manifest
was updated for the one changed application file.

## Evidence / limits
New offline regression test: `tests/test_v24917_long_diagnostics_epoch_fix.py`.
Test scenarios: valid UDA-only invalidation; changed semantic model, skim,
assignment epoch and unexpected mutation; missing/stale proof; diagnostic error.

**NOT_RUN:** Native Visum/Windows COM integration and full offline pytest.
The live failure and rollback status above are from supplied logs, not from
a rerun of the patched version. Before restart reopen the latest verified
accepted .ver; never treat the failed working Visum state as accepted.

### Suggested exact offline validation
```bash
python -m py_compile r1_15a2_trial_adapter_v24917.py tests/test_v24917_long_diagnostics_epoch_fix.py
python -m pytest -q -p no:cacheprovider tests/test_v24917_long_diagnostics_epoch_fix.py tests/test_v24917_long_incidence_read.py tests/test_v24917_long_tg_td_unlock.py
python -m pytest -q -p no:cacheprovider tests
python -m pytest -q -p no:cacheprovider diagfast_tests
python -m pytest -q -p no:cacheprovider genfix2_audit_tests
```
