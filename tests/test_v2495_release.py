# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from r1_15a2_safety_v2495 import (
    RELEASE, V2494_CONFIG_SHA256, V2494_PATH_IMPLEMENTATION_FILES,
    V2494_RELEASE, validate_v2495_config,
)
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_5.py"


def load():
    spec = importlib.util.spec_from_file_location("v2495_launcher", ROOT / LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2495_release_contract_validates():
    module = load()
    cfg = module.load_config()
    out = validate_v2495_config(cfg, ROOT)
    assert module.RELEASE == cfg["release"] == cfg["safety_gate_release"] == RELEASE
    assert out["geh20_transition_mode"] == "HYSTERESIS_BUDGET"
    assert out["generation_material_new_geh20_limit"] == 3
    assert out["td_material_new_geh20_limit"] == 1
    assert out["new_geh30_limit"] == 0
    assert out["continuous_penalty"] == "DEFERRED"
    assert out["production_ready"] is False


def test_v2495_exactly_pins_v2494_path_cache_predecessor():
    cfg = load().load_config()
    compat = cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    row = next(r for r in compat["predecessors"]
               if r["source_release"] == V2494_RELEASE)
    assert compat["target_release"] == RELEASE
    assert row["source_config_sha256s"] == [V2494_CONFIG_SHA256]
    assert row["source_path_implementation_files"] == V2494_PATH_IMPLEMENTATION_FILES


def test_v2495_policy_numbers_are_hard_locked():
    cfg = load().load_config()
    p = cfg["geh20_transition_policy"]
    assert (p["hysteresis_low"], p["threshold"], p["hysteresis_high"]) == (19.5, 20.0, 20.5)
    assert p["generation"] == {
        "max_material_new_geh20": 3,
        "max_single_profile_geh_increase": 2.0,
        "max_total_new_geh20_excess": 2.0,
    }
    assert p["td"] == {
        "max_material_new_geh20": 1,
        "max_single_profile_geh_increase": 1.0,
        "max_total_new_geh20_excess": 0.75,
    }
    assert p["max_new_geh30"] == 0


def test_v2495_rejects_relaxed_geh30_guard():
    cfg = load().load_config()
    cfg["geh20_transition_policy"]["max_new_geh30"] = 1
    with pytest.raises(SupplyContractError, match="GEH20_HYSTERESIS_BUDGET"):
        validate_v2495_config(cfg, ROOT)


def test_v2495_rejects_unreviewed_generation_budget_drift():
    cfg = load().load_config()
    cfg["geh20_transition_policy"]["generation"]["max_material_new_geh20"] = 4
    with pytest.raises(SupplyContractError, match="GEH20_HYSTERESIS_BUDGET"):
        validate_v2495_config(cfg, ROOT)


def test_v2495_retains_v2494_com_and_semantic_restart_contracts():
    cfg = load().load_config()
    assert cfg["com_resilience"]["bounded_path_export_retry_enabled"] is True
    assert cfg["com_resilience"]["bounded_path_export_same_range_required"] is True
    assert cfg["restart_authority"]["mode"] == "SEMANTIC_MODEL_STATE"
    assert cfg["restart_authority"]["raw_ver_sha_used_for_restart_acceptance"] is False


def test_v2495_run_root_is_not_nested(tmp_path):
    module = load()
    project = tmp_path / "2022"
    source = (project / "R1_15A2_V2494_RUNS" / "RUN_A" /
              "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == project.resolve()
    new_run = project / "R1_15A2_V2495_RUNS" / "RUN_X"
    module._assert_new_run_is_not_nested(
        new_run, layout["detected_run_roots_nearest_first"])
