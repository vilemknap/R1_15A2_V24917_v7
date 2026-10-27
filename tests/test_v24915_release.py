# -*- coding: utf-8 -*-
"""Release-level hard gates for V2.4.9.15."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import r1_15a2_com_compat as com
from r1_15a2_safety_v24915 import (
    CONTINUATION_AUTHORITY_SHA256,
    PARENT_CONFIG_SHA256,
    PARENT_PATH_IMPLEMENTATION_FILES,
    PARENT_RELEASE,
    RELEASE,
    validate_v24915_config,
    validate_v24915_runtime_bundle,
)

ROOT = Path(__file__).resolve().parents[1]


def _entrypoint():
    path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15.py"
    spec = importlib.util.spec_from_file_location("v24915_user_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v24915_config_runtime_bundle_and_lineage_are_hash_locked():
    entry = _entrypoint()
    cfg = entry.load_config()
    config_result = validate_v24915_config(cfg, ROOT)
    runtime_result = validate_v24915_runtime_bundle(cfg, ROOT)
    assert cfg["release"] == RELEASE
    assert config_result["parent_release"] == PARENT_RELEASE
    assert config_result["accepted_count_start"] == 9
    assert config_result["next_outer_cycle"] == 6
    assert config_result["calibration_math_changed"] is False
    assert runtime_result["continuation_authority_sha256"] == CONTINUATION_AUTHORITY_SHA256
    assert runtime_result["supply_policy_preserved"] is True
    assert runtime_result["files_checked"] >= 64


def test_v24915_generic_retry_is_unchanged_and_long_scopes_are_exact():
    cfg = _entrypoint().load_config()
    policy = cfg["com_resilience"]
    assert com.com_retry_settings(policy) == (5, 0.05, 2.0, 0.8)
    assert com.com_retry_budget_settings(policy, "bounded_path_export") == (
        48, 0.25, 1.7, 3.0, 120.0,
    )
    assert com.com_retry_budget_settings(policy, "final_verification") == (
        12, 0.25, 1.8, 3.0, 30.0,
    )
    assert policy["retry_scope"] == "TRANSIENT_RPC_CALL_REJECTED_OR_RETRY_LATER_ONLY"
    assert policy["bounded_path_export_same_range_required"] is True
    assert policy["page_size_fallback_policy"] == "NONTRANSIENT_MEMORY_OR_RANGE_ERRORS_ONLY"


def test_v24915_v24914_cache_provenance_row_is_exact():
    cfg = _entrypoint().load_config()
    compat = cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"
    ]
    rows = [r for r in compat["predecessors"] if r["source_release"] == PARENT_RELEASE]
    assert len(rows) == 1
    assert rows[0]["source_config_sha256s"] == [PARENT_CONFIG_SHA256]
    assert rows[0]["source_path_implementation_files"] == PARENT_PATH_IMPLEMENTATION_FILES


def test_v24915_contract_records_failure_and_safe_restart_policy():
    contract = json.loads(
        (ROOT / "V24915_COM_BUSY_RETRY_SAFE_FINALIZER_CONTRACT.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["live_failure_evidence"]["hresult"] == -2147418111
    assert contract["live_failure_evidence"]["failed_range_first"] == 22786049
    assert contract["live_failure_evidence"]["failed_range_last"] == 22788096
    assert contract["scope_locks"]["accepted_count_start"] == 9
    assert contract["scope_locks"]["next_outer_cycle"] == 6
    assert contract["finalizer_policy"][
        "manual_reopen_required_for_transient_retry_exhaustion"
    ] is False
    assert contract["finalizer_policy"][
        "safe_restart_from_latest_accepted_checkpoint"
    ] is True
    assert contract["finalizer_policy"]["nontransient_or_state_mismatch"] == (
        "FAIL_CLOSED_MANUAL_REOPEN"
    )
