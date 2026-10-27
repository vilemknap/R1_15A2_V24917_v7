# -*- coding: utf-8 -*-
"""PERF2C R3A: sibling-run-root hotfix for the B0018 Demand extension 16..25.

The R3 extension intentionally resumes from an accepted checkpoint stored under
R1_15A2_V24915_PERF2_RUNS/RUN_... .  The inherited PERF2 nesting guard treated
any new sibling RUN_... under the same central RUNS directory as if it were
nested under the prior run tree.  This wrapper narrows that guard to its intended
semantics: a direct sibling under the same RUNS root is allowed; a run created
inside any previous run-tree descendant remains forbidden.

No calibration, snapshot, candidate, acceptance, TD, assignment, rollback, or
path-cache semantics are changed.
"""
from __future__ import annotations

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
_INJECTED_VISUM = globals().get("Visum")
_INJECTED_COM = globals().get("COM")
_ORIGINAL_SYS_PATH = list(sys.path)
sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]

import R1_15A2_DEMAND_EXTENSION_B0018_CYCLES16_25_V2_4_9_15_PERF2C_R3 as r3


def _sibling_safe_assert_new_run_is_not_nested(run_directory, prior_run_roots):
    run = Path(run_directory).resolve()
    for prior in prior_run_roots:
        root = Path(prior).resolve()
        try:
            run.relative_to(root)
        except ValueError:
            continue
        # Intended central-run-root continuation: RUN_new is a direct sibling
        # of RUN_old below the same ..._RUNS directory.
        if run.parent == root and run.name.upper().startswith("RUN_"):
            continue
        raise RuntimeError(
            "V24915P2_NEW_RUN_STILL_NESTED_UNDER_PRIOR_RUN_TREE:%s" % root
        )


def main():
    try:
        r3._INJECTED_VISUM = _INJECTED_VISUM
        r3._INJECTED_COM = _INJECTED_COM
        r3._activate_extension()
        parent = r3.perf2c.parent
        parent._assert_new_run_is_not_nested = _sibling_safe_assert_new_run_is_not_nested
        if _INJECTED_VISUM is not None:
            parent.Visum = _INJECTED_VISUM
        if _INJECTED_COM is not None:
            parent.COM = _INJECTED_COM
        return parent.main("FULL")
    finally:
        sys.path[:] = _ORIGINAL_SYS_PATH


if __name__ == "__main__" or _INJECTED_VISUM is not None or _INJECTED_COM is not None:
    main()
