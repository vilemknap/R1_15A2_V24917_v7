# -*- coding: utf-8 -*-
"""Release-level hard gates for V24915 PERF2 CandidateReadbackBundle."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from r1_15a2_safety_v24915p2 import (
    PARENT_RELEASE,
    RELEASE,
    validate_v24915p2_config,
    validate_v24915p2_runtime_bundle,
)

ROOT = Path(__file__).resolve().parents[1]


def _entrypoint():
    path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py"
    spec = importlib.util.spec_from_file_location("v24915_perf2_user_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_perf2_config_runtime_bundle_and_parent_are_hash_locked():
    cfg = _entrypoint().load_config()
    config_result = validate_v24915p2_config(cfg, ROOT)
    runtime_result = validate_v24915p2_runtime_bundle(cfg, ROOT)
    assert cfg["release"] == RELEASE
    assert config_result["parent_release"] == PARENT_RELEASE
    assert config_result["calibration_math_changed"] is False
    assert config_result["assignment_method_changed"] is False
    assert config_result["acceptance_changed"] is False
    assert config_result["candidate_readback_bundle"] is True
    assert config_result["legacy_fallback"] is True
    assert config_result["live_12d_11d_unchanged"] is True
    assert runtime_result["parent_deployment_intact"] is True
    assert runtime_result["files_checked"] >= 80
    assert runtime_result["real_visum_tested"] is False
    assert runtime_result["production_ready"] is False


def test_perf2_keeps_a0009_continuation_and_exact_safe_contract():
    cfg = _entrypoint().load_config()
    continuation = cfg["demand_continuation"]
    assert continuation["accepted_count"] == 9
    assert continuation["next_outer_cycle"] == 6
    assert continuation["mode"] == "EXACT_SEMANTIC_A0009_LINEAGE_CONTINUATION"
    feature = cfg["performance"]["v24915_perf2_candidate_readback_bundle"]
    assert feature["enabled"] is True
    assert feature["shadow_parity_mode"] is True
    assert feature["fallback_to_legacy"] is True
    assert feature["require_exact_snapshot_parity"] is True
    assert feature["candidate_math_changed"] is False
    assert feature["acceptance_changed"] is False
    assert feature["assignment_method_changed"] is False
    assert feature["matrix_fingerprint_semantics_changed"] is False
    assert feature["diagnostic_method_changed"] is False
    assert feature["candidate_parallelism"] is False
    assert feature["cross_run_cache"] is False
    assert feature["invalidate_before_side_effect"] is True


def test_perf2_entrypoint_routes_only_to_perf2_runtime_modules():
    module = _entrypoint()
    assert module.VisumAdapter.__module__ == "r1_15a2_trial_adapter_v24915p2"
    assert module.run_overnight_calibration_coupled.__module__ == \
        "r1_15a2_overnight_controller_coupled_v24915p2"
    assert module.run_verified_supply_only.__module__ == \
        "r1_15a2_supply_handoff_v24915p2"
    cfg = module.load_config()
    required = {
        "r1_15a2_candidate_readback_bundle_v24915p2.py",
        "r1_15a2_trial_adapter_v24915p2.py",
        "r1_15a2_inplace_transaction_v24915p2.py",
        "r1_15a2_overnight_controller_v24915p2.py",
        "r1_15a2_overnight_controller_coupled_v24915p2.py",
        "r1_15a2_supply_handoff_v24915p2.py",
        "r1_15a2_safety_v24915p2.py",
    }
    assert required <= set(cfg["implementation_files"])
    assert all(len(cfg["implementation_files"][name]) == 64 for name in required)


def test_perf2_status_boundary_remains_offline_only():
    cfg = _entrypoint().load_config()
    assert cfg.get("apply") is False
    assert cfg.get("production_apply") is False
    assert cfg["trial_calibration"]["v24915_perf2_candidate_readback_bundle"] == {
        "candidate_readback_bundle": True,
        "legacy_snapshot_fallback": True,
        "live_12d_11d_unchanged": True,
        "candidate_parallelism": False,
        "assignment_method_changed": False,
        "acceptance_changed": False,
    }
