# V24916 BOOTSTRAPFIX2 — live recursion repair

Date: 2026-10-22

## Live failure reproduced from Visum

Observed terminal bootstrap failure:

- stage: `PARENT_MAIN_FULL`
- exception: `RecursionError: maximum recursion depth exceeded`
- secondary error while formatting the exhausted-stack exception: `AttributeError: pathlib._local.WindowsPath object has no attribute '_str'`

## Root cause

`00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py` intentionally replaces
`parent._stable_project_layout` with `_isolated_project_layout` during runtime installation.
However `_base_layout()` dereferenced the mutable module attribute again:

`_isolated_project_layout -> _isolated_workspace -> _base_layout -> parent._stable_project_layout`

After the replacement, the final target was `_isolated_project_layout` itself, producing an
infinite wrapper cycle before the parent calibration could allocate its run directory.
The `WindowsPath._str` message was a secondary exception emitted while Python tried to format
paths after the recursion stack was already exhausted; it is not treated as an independent
filesystem/path contract failure.

## Fix

- freeze the original parent `_stable_project_layout` immediately after importing the parent module;
- make `_base_layout()` call that frozen pre-patch resolver;
- keep the runtime replacement of `parent._stable_project_layout` intact for the parent calibration;
- update runtime-manifest SHA for the intentionally changed launcher;
- add a regression test that first replaces `parent._stable_project_layout` with the isolated resolver
  and then calls the isolated resolver, reproducing the exact live topology that previously recursed.

No Dial-B, TG/TD, FlowBundle targeting, TD component mask, 12D/11D, guard, acceptance,
coefficient, supply, path-cache or calibration mathematics were changed.

## Verification

- compileall: PASS
- targeted BOOTSTRAPFIX/FRESH0/PATHFIX tests: 25 passed
- full pytest: 1002 passed, 4 skipped, 0 failed
- V24916 runtime manifest: 45/45 PASS
- protected parent runtime file `r1_15a2_fresh0_shortroot_parent_v24916.py`: unchanged

## Expected live behavior

The launcher should now pass the `PARENT_MAIN_FULL` layout-resolution step without recursion.
`R1_15A2_V16_RUNS` is allocated before live preflight and its location is also written to
`V24916_LAST_RUNS_LOCATION.txt` in the package directory.
