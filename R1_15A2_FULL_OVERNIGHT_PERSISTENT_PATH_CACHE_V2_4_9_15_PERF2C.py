# -*- coding: utf-8 -*-
"""Runnable PERF2C overlay: exact single-pass full semantic snapshot.

This wrapper preserves the complete R6/R5 calibration runtime and replaces only
its VisumAdapter class with the additive PERF2C child.  The parent deployment
preflight remains mandatory and an additional hash-pinned overlay preflight is
merged into the same runtime evidence.
"""
from __future__ import annotations

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

import R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2 as parent
from r1_15a2_trial_adapter_v24915p2c import VisumAdapter
from r1_15a2_supply_temp_sqlite_hotfix_v24915p2c2 import activate_supply_temp_sqlite_hotfix
from r1_15a2_safety_v24915p2c import (
    PACKAGE_REVISION, RELEASE, preflight_v24915p2c_overlay,
)

_parent_deployment_preflight = parent.preflight_v24915p2_deployment_files
_parent_runtime_preflight = parent.validate_v24915p2_runtime_bundle
_parent_load_config = parent.load_config


def _combined_deployment_preflight(package_root=None):
    base = dict(_parent_deployment_preflight(package_root))
    overlay = dict(preflight_v24915p2c_overlay(package_root))
    base["perf2c_overlay"] = overlay
    base["files_checked_parent"] = base.get("files_checked", 0)
    base["files_checked_overlay"] = overlay.get("files_checked", 0)
    base["files_checked"] = (
        int(base.get("files_checked_parent", 0))
        + int(base.get("files_checked_overlay", 0)))
    return base


def _combined_runtime_preflight(cfg, package_root=None):
    base = dict(_parent_runtime_preflight(cfg, package_root))
    overlay = dict(preflight_v24915p2c_overlay(package_root))
    base["perf2c_overlay"] = overlay
    base["perf2c_single_pass_exact_snapshot"] = True
    base["public_snapshot_schema_changed"] = False
    base["cross_call_cache"] = False
    return base


def _load_config_with_overlay(execution_mode="FULL"):
    cfg = _parent_load_config(execution_mode)
    cfg["v24915_perf2c_runtime_options"] = {
        "schema": "R1_15A2_V24915_PERF2C_CONFIG_V1",
        "enabled": True,
        "shadow_parity_once": True,
        "fallback_to_legacy": True,
        "public_snapshot_schema_changed": False,
        "semantic_hashes_changed": False,
        "matrix_fingerprint_semantics_changed": False,
        "cross_call_cache": False,
        "new_mutation_epoch": False,
        "new_authority_token": False,
        "persistent_cache_main_database_writable": False,
        "connection_local_temp_schema_for_supply": True,
    }
    cfg["v24915_perf2c_overlay_revision"] = PACKAGE_REVISION
    cfg["v24915_perf2c_features"] = [
        "LOCAL_PER_SNAPSHOT_READ_CONTEXT_ONLY",
        "FIRST_LIVE_CALL_EXACT_OBJECT_PARITY",
        "PERMANENT_ADAPTER_LOCAL_FALLBACK_ON_MISMATCH_OR_READ_ERROR",
        "ONE_OPERATIONS_GETALL_SHARED_BY_TD_AND_OPERATION_INVENTORY",
        "DSeg_BINDING_READS_ONLY_PUBLISHED_SEMANTIC_FIELDS",
        "FULL_MATRIX_GETVALUES_AND_ALL_STATE_HASHES_UNCHANGED",
        "NO_CROSS_SNAPSHOT_CACHE",
        "NO_NEW_EPOCH_OR_AUTHORITY_TOKEN",
        "PERSISTENT_CACHE_MAIN_DB_URI_MODE_RO_WITH_CONNECTION_LOCAL_TEMP_SCHEMA",
    ]
    return cfg


_OVERLAY_ACTIVE = False


def _activate_overlay():
    global _OVERLAY_ACTIVE
    if _OVERLAY_ACTIVE:
        return
    activate_supply_temp_sqlite_hotfix()
    parent.VisumAdapter = VisumAdapter
    parent.RELEASE = RELEASE
    parent.preflight_v24915p2_deployment_files = _combined_deployment_preflight
    parent.validate_v24915p2_runtime_bundle = _combined_runtime_preflight
    parent.load_config = _load_config_with_overlay
    if _INJECTED_VISUM is not None:
        parent.Visum = _INJECTED_VISUM
    if _INJECTED_COM is not None:
        parent.COM = _INJECTED_COM
    _OVERLAY_ACTIVE = True


def main(execution_mode="FULL"):
    try:
        _activate_overlay()
        return parent.main(execution_mode)
    finally:
        sys.path[:] = _ORIGINAL_SYS_PATH


if __name__ == "__main__" or _INJECTED_VISUM is not None or _INJECTED_COM is not None:
    main("FULL")
