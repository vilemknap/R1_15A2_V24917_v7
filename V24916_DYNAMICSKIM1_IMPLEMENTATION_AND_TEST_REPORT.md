# V24916 DYNAMICSKIM1 implementation and test report

## Executive result

DYNAMICSKIM1 corrects the Trip Distribution calibration distance authority for a congested network.
The static `R1_OSRM_DIST_KM` matrix is no longer used as the active FineCDF/11D distance authority.
It remains protected as reference/provenance only.

Every dynamic FineCDF evaluation now performs the complete feedback step:

`write b,c -> native Trip Distribution -> downstream vehicle realization -> fresh approved PrT assignment -> six native Calculate PrT skim operations -> fresh DIS matrices -> IDP/FineCDF evaluation -> next b,c`

This is an additive runtime change. It does not change the sealed FineCDF v1.9 target mathematics,
acceptance thresholds, VDFs, P/A, Generation coefficients, or the approved assignment authority.

## Why the previous contract was wrong

The previous V24916 path treated `R1_OSRM_DIST_KM` as the active distance basis while FineCDF tried
multiple Trip Distribution parameter candidates. On a saturated network this is methodologically invalid:
assignment can divert flow to longer alternative routes, therefore the effective OD distance distribution
changes with the current assigned path volumes.

## Dynamic skim contract

Required native demand segments:

- `NATIVE_CW`
- `NATIVE_CW_noT`
- `NATIVE_CS`
- `NATIVE_CS_noT`
- `NATIVE_CL`
- `NATIVE_CF`

The runtime requires exactly six active PrT skim operations and exactly one `DIS` skim matrix for each
required native demand segment. The resulting matrices are bound to the exact fresh assignment epoch.
A stale assignment/skims binding is rejected fail-closed.

Family distance matrices used by FineCDF/11D:

- WORK = current-OD-volume weighted `NATIVE_CW` + `NATIVE_CW_noT` DIS
- SERVICE = current-OD-volume weighted `NATIVE_CS` + `NATIVE_CS_noT` DIS
- LONG = `NATIVE_CL` DIS
- FOREIGN = `NATIVE_CF` DIS (provenance/parity; not a domestic distribution target)

For zero-current-demand cells in toll/no-toll combinations, the runtime uses the shorter available native
family assignment skim only as a finite deterministic placeholder. Such cells carry zero current IDP weight.

## FineCDF mathematics

`DynamicFamilyMetrics` reproduces the sealed FineCDF v1.9 target calculations and changes only the
source of the distance matrix. The CDF target, coarse bins, mean-distance term, residual definition,
objective construction, and diagnostics remain unchanged.

A regression test proves numerical parity with the sealed v1.9 metric when the dynamic family distance
matrix is identical to the old static distance matrix.

## Procedure Sequence orchestration

In dynamic mode, each FineCDF evaluation selects only the approved realization chain:

- native TD leaf;
- originally active downstream realization operations through the final approved assignment;
- all six configured native PrT skim operations;
- required group rows.

Trip Generation remains frozen. Unrelated active post-assignment procedures are excluded from the inner
FineCDF realization plan. ACTIVE flags are restored exactly after each evaluation.

The same dynamic realization is used when restoring an accepted b,c state, so rollback does not reuse a
skim from a rejected candidate.

## Live configuration requirement

The runtime can mechanically verify the six skim operation positions and exact resulting `DIS` matrix
identities. For the scientific method, the Visum PrT skim operations must be configured to derive distance
from the current assignment paths and aggregate by path volume (`Use paths from assignment` +
`Mean over path volume`).

The PTV 2026 COM model exposes `PrTSkimMatrixParameters` on a PrT skim operation, but the exact child
member names for those two settings are not sealed in this offline package. Therefore DYNAMICSKIM1 does
not falsely claim that the weighting configuration has already been independently COM-read back. This is
a mandatory live canary/preflight check before production-ready status.

## Main changed files

- `r1_15a2_dynamic_skim_v24916p2c.py` (new)
- `r1_15a2_finecdf_bridge_v24916.py`
- `r1_15a2_trial_adapter_v24916p2c_active.py`
- `r1_15a2_active_demand_evidence_v24916p2c.py`
- `r1_15a2_active_targeting_runtime_v24916p2c.py`
- `r1_15a2_fresh_baseline_live_preflight_v24916p2c.py`
- `tests/test_v24916_dynamic_assignment_skims.py` (new)
- `V24916_PERF2C_RUNTIME_MANIFEST.json`

## Verification

Focused dynamic + PERF2C integration:

`33 passed`

Full suite:

`1008 passed, 4 skipped, 0 failed`

Compileall:

`PASS`

Runtime manifest:

`46 / 46 PASS`

## Status

- offline implementation: PASS
- static OSRM active calibration distance: DISABLED
- static OSRM reference/provenance role: PRESERVED
- fresh assignment per FineCDF evaluation: REQUIRED
- fresh six native DIS skims per FineCDF evaluation: REQUIRED
- stale skim reuse: FAIL-CLOSED
- FineCDF v1.9 target mathematics: PRESERVED
- production-ready: NO, until live Visum canary confirms the six skim parameter settings and completes a dynamic TD evaluation
