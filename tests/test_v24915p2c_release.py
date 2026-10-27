# -*- coding: utf-8 -*-
"""Packaging and fail-closed release gates for PERF2C overlay."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import r1_15a2_safety_v24915p2c as safety
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C.py"


def _load_launcher_module():
    spec = importlib.util.spec_from_file_location("perf2c_launcher_test", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_overlay_manifest_and_contract_are_hash_pinned():
    result = safety.preflight_v24915p2c_overlay(ROOT)
    assert result["passes"] is True
    assert result["files_checked"] == 6
    assert result["public_snapshot_schema_changed"] is False
    assert result["cross_call_cache"] is False
    assert result["first_call_exact_shadow_parity"] is True


def test_contract_forbids_state_machine_and_cross_call_cache_changes():
    contract = json.loads((ROOT / safety.CONTRACT_FILE).read_text(encoding="utf-8"))
    assert contract["scope"] == "LOCAL_PER_SNAPSHOT_READ_COALESCING_PLUS_READONLY_MAIN_SQLITE_TEMP_SCHEMA_SUPPLY_HOTFIX"
    assert contract["cross_snapshot_cache"] is False
    assert contract["new_mutation_epoch"] is False
    assert contract["new_authority_token"] is False
    assert contract["rollback_changed"] is False
    assert contract["candidate_math_changed"] is False
    assert contract["acceptance_changed"] is False
    assert contract["first_live_call_exact_shadow_parity"] is True
    hotfix = contract["supply_sqlite_hotfix"]
    assert hotfix["persistent_main_database_uri_mode"] == "ro"
    assert hotfix["persistent_main_database_writable"] is False
    assert hotfix["connection_local_temp_schema_required"] is True
    assert hotfix["supply_design_math_changed"] is False


def test_wrapper_is_importable_and_patches_only_adapter_and_overlay_evidence():
    module = _load_launcher_module()
    assert module.RELEASE == safety.RELEASE
    assert module._OVERLAY_ACTIVE is False
    cfg = module._load_config_with_overlay("FULL")
    feature = cfg["v24915_perf2c_runtime_options"]
    assert feature["enabled"] is True
    assert feature["shadow_parity_once"] is True
    assert feature["fallback_to_legacy"] is True
    assert feature["cross_call_cache"] is False
    assert feature["new_mutation_epoch"] is False
    assert feature["new_authority_token"] is False
    # Parent calibration configuration remains the R5 overnight50 authority.
    assert cfg["package_revision"] == "V24915_PERF2_R5_OVERNIGHT50_B0016_CONTINUATION"
    assert cfg["coupled_demand"]["max_outer_cycles"] == 50
    assert cfg["trial_calibration"]["max_runtime_seconds"] == 64800.0


def test_overlay_preflight_detects_runtime_file_tamper(tmp_path):
    for name in (
        safety.MANIFEST_FILE,
        safety.CONTRACT_FILE,
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C.py",
        "r1_15a2_single_pass_snapshot_v24915p2c.py",
        "r1_15a2_trial_adapter_v24915p2c.py",
        "r1_15a2_supply_temp_sqlite_hotfix_v24915p2c2.py",
        "R1_15A2_SUPPLY_ONLY_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_R2.py",
    ):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    target = tmp_path / "r1_15a2_single_pass_snapshot_v24915p2c.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    with pytest.raises(SupplyContractError, match="OVERLAY_INVALID"):
        safety.preflight_v24915p2c_overlay(tmp_path)
