# -*- coding: utf-8 -*-
"""PERF2C R3: exact B0018 Demand extension, outer cycles 16..25.

This is deliberately Demand-only.  It resumes from the exact semantic B0018
checkpoint, resets the inherited stationary streak, expands only Generation
backtracking to two smaller scales, runs at most ten additional coupled Demand
outer cycles, and keeps Supply locked for explicit review after cycle 25.
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
_INJECTED_VISUM = globals().get("Visum")
_INJECTED_COM = globals().get("COM")
_ORIGINAL_SYS_PATH = list(sys.path)

if _INJECTED_VISUM is not None or _INJECTED_COM is not None:
    if getattr(sys, "_r1_15a2_calibration_busy", False):
        raise RuntimeError("ANOTHER_15A2_RUN_IS_ACTIVE")
    for module_name in list(sys.modules):
        if module_name.startswith("r1_15a2_"):
            del sys.modules[module_name]
sys.path[:] = [str(HERE)] + [path for path in sys.path if path != str(HERE)]

import R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C as perf2c
import r1_15a2_demand_extension_b0018_v24915p2c3 as extension_continuation
from r1_15a2_safety_v24915p2c3 import (
    RELEASE, PACKAGE_REVISION, preflight_v24915p2c3_overlay,
    validate_v24915p2c3_config_delta,
)

_BASE_LOAD_CONFIG = perf2c._load_config_with_overlay
_BASE_COMBINED_RUNTIME_PREFLIGHT = perf2c._combined_runtime_preflight
_BASE_COMBINED_DEPLOYMENT_PREFLIGHT = perf2c._combined_deployment_preflight
_EXTENSION_ACTIVE = False


def _load_config_extension(execution_mode="FULL"):
    if str(execution_mode).upper() != "FULL":
        raise RuntimeError("V24915P2C3_DEMAND_EXTENSION_FULL_MODE_ONLY")
    base_cfg = _BASE_LOAD_CONFIG("FULL")
    cfg = copy.deepcopy(base_cfg)
    cfg["coupled_demand"]["max_outer_cycles"] = 25
    # Start=16 and inherited streak is forcibly reset to zero.  Eleven
    # consecutive stationary cycles cannot fit into the ten-cycle extension,
    # therefore the existing controller cannot unlock Supply inside this run.
    cfg["coupled_demand"]["min_stationary_cycles"] = 11
    cfg["backtracking_scales"] = [1.0, 0.5, 0.25, 0.125, 0.0625]
    cfg["trial_calibration"]["max_trials_per_block"]["GENERATION"] = 5
    cfg["v24915_perf2c_r3_demand_extension"] = {
        "schema": "R1_15A2_V24915_PERF2C_R3_B0018_DEMAND_EXTENSION_RUNTIME_V1",
        "enabled": True,
        "source_checkpoint": "ACCEPTED_B_0018_3d57d34487ba.ver",
        "outer_cycle_start": 16,
        "outer_cycle_end": 25,
        "outer_cycle_count": 10,
        "reset_stationary_streak": True,
        "supply_locked_during_extension": True,
        "review_required_after_cycle_25": True,
        "generation_backtracking_scales": [1.0, 0.5, 0.25, 0.125, 0.0625],
        "generation_max_trials_per_block": 5,
        "acceptance_thresholds_changed": False,
        "td_math_changed": False,
        "assignment_changed": False,
    }
    cfg["v24915_perf2c_r3_overlay_revision"] = PACKAGE_REVISION
    validate_v24915p2c3_config_delta(cfg, base_cfg, HERE)
    return cfg


def _deployment_preflight_extension(package_root=None):
    base = dict(_BASE_COMBINED_DEPLOYMENT_PREFLIGHT(package_root))
    overlay = dict(preflight_v24915p2c3_overlay(package_root))
    base["perf2c_r3_b0018_demand_extension"] = overlay
    base["files_checked_perf2c_r3"] = overlay.get("files_checked", 0)
    base["files_checked"] = int(base.get("files_checked", 0)) + int(overlay.get("files_checked", 0))
    return base


def _runtime_preflight_extension(cfg, package_root=None):
    # Reconstruct the exact PERF2C R2 parent config and run every parent gate on
    # it.  Then validate that the live child differs only in the reviewed R3
    # extension dimensions.
    base_cfg = _BASE_LOAD_CONFIG("FULL")
    validate_v24915p2c3_config_delta(cfg, base_cfg, package_root)
    base = dict(_BASE_COMBINED_RUNTIME_PREFLIGHT(base_cfg, package_root))
    overlay = dict(preflight_v24915p2c3_overlay(package_root))
    base["perf2c_r3_b0018_demand_extension"] = overlay
    base["demand_extension_outer_cycles"] = [16, 25]
    base["demand_extension_count"] = 10
    base["supply_locked_during_extension"] = True
    base["generation_backtracking_scales"] = [1.0, 0.5, 0.25, 0.125, 0.0625]
    return base


def _wrap_controller(original):
    def run(adapter, cfg, folder, control, package_root):
        result = original(adapter, cfg, folder, control, package_root)
        cycles = [int(row.get("cycle")) for row in result.get("demand_cycles", [])
                  if isinstance(row, dict) and row.get("cycle") is not None]
        if result.get("supply_started") is True:
            raise RuntimeError("V24915P2C3_SUPPLY_STARTED_DURING_DEMAND_EXTENSION")
        if str(result.get("status")) == "DEMAND_MAX_OUTER_CYCLES_REACHED_SUPPLY_LOCKED":
            expected = list(range(16, 26))
            if cycles != expected:
                raise RuntimeError(
                    "V24915P2C3_EXTENSION_CYCLE_SEQUENCE_MISMATCH:%r" % (cycles,))
            result["status"] = "DEMAND_EXTENSION_16_25_COMPLETED_SUPPLY_LOCKED"
            result["demand_extension_complete"] = True
            result["demand_extension_outer_cycles"] = expected
            result["demand_extension_review_required"] = True
            result["supply_started"] = False
            result["continuation_required"] = True
            result["next_outer_cycle"] = 26
        return result
    return run


def _activate_extension():
    global _EXTENSION_ACTIVE
    if _EXTENSION_ACTIVE:
        return
    perf2c._INJECTED_VISUM = _INJECTED_VISUM
    perf2c._INJECTED_COM = _INJECTED_COM
    perf2c._activate_overlay()
    parent = perf2c.parent
    original_controller = parent.run_overnight_calibration_coupled
    parent.RELEASE = RELEASE
    parent.load_config = _load_config_extension
    parent.preflight_v24915p2_deployment_files = _deployment_preflight_extension
    parent.validate_v24915p2_runtime_bundle = _runtime_preflight_extension
    parent.demand_continuation_r5 = extension_continuation
    parent.run_overnight_calibration_coupled = _wrap_controller(original_controller)
    if _INJECTED_VISUM is not None:
        parent.Visum = _INJECTED_VISUM
    if _INJECTED_COM is not None:
        parent.COM = _INJECTED_COM
    _EXTENSION_ACTIVE = True


def main():
    try:
        _activate_extension()
        return perf2c.parent.main("FULL")
    finally:
        sys.path[:] = _ORIGINAL_SYS_PATH


if __name__ == "__main__" or _INJECTED_VISUM is not None or _INJECTED_COM is not None:
    main()
