# V24915 PERF2 R3 live constructor hotfix

## Live failure reproduced from user evidence

The R2 package passed its deployment/runtime preflight, then failed before any
calibration work with:

`TypeError: VisumAdapter.__init__() takes 3 positional arguments but 4 were given`

The live launcher calls `VisumAdapter(visum, cfg, control)`. PERF2 had narrowed
the inherited V24915/PERF1 constructor from `(visum, cfg, control=None)` to
`(visum, cfg)`, which was an API regression not covered by the previous tests.

## Fix

`r1_15a2_trial_adapter_v24915p2.VisumAdapter.__init__` now has:

`(self, visum, cfg, control=None)`

and forwards `control` to the parent adapter before constructing the
CandidateReadbackManager. No calibration mathematics, acceptance policy,
assignment method, diagnostics, path-cache semantics, or CandidateReadbackBundle
state semantics were changed.

## New hard regression gate

Added `tests/test_v24915p2_live_constructor_contract.py` proving:
- parent/child constructor control compatibility;
- binding of the exact launcher positional arity;
- control forwarding to the parent and telemetry forwarding to the bundle manager.

## Test result

The complete test inventory was executed in four bounded groups because one
monolithic pytest process exceeded the environment command timeout:
- 357 passed
- 209 passed
- 130 passed, 4 skipped
- 151 passed

Total: **847 passed, 4 skipped, 0 failed**.
`compileall` PASS. PERF2 deployment/config/runtime preflight PASS with 80 files.

## Separate continuation issue discovered

The failed live run used `ACCEPTED_B_0016_d1211a44ac4d.ver`, while the inherited
V24914 continuation resolver is explicitly pinned to A0009 (`accepted_count=9`,
`next_outer_cycle=6`, exact A0009 semantic hash). R3 does not silently rewrite
that scientific continuation authority. A safe B0016 rebase requires the prior
run's RUN_STATUS/LATEST checkpoint/semantic sidecar and generation-reference
evidence so that the exact accepted phase and remaining outer-loop budget can be
reconstructed fail-closed.
