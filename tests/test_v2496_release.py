# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from r1_15a2_safety_v2496 import (
    EXPECTED_EARLY_POLICY, RELEASE, V2495_CONFIG_SHA256,
    V2495_PATH_IMPLEMENTATION_FILES, V2495_RELEASE, validate_v2496_config,
)
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_6.py"


def load():
    spec = importlib.util.spec_from_file_location("v2496_launcher", ROOT / LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2496_release_contract_validates():
    module = load()
    cfg = module.load_config()
    out = validate_v2496_config(cfg, ROOT)
    assert module.RELEASE == cfg["release"] == cfg["safety_gate_release"] == RELEASE
    assert cfg["early_exploration_acceptance"] == EXPECTED_EARLY_POLICY
    assert out["early_exploration_through_outer_cycle"] == 8
    assert out["td_cal_degradation_limit"] == 0.05
    assert out["best_so_far_checkpoint"] is True
    assert out["production_ready"] is False


def test_v2496_exactly_pins_v2495_path_cache_predecessor():
    cfg = load().load_config()
    compat = cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    row = next(r for r in compat["predecessors"]
               if r["source_release"] == V2495_RELEASE)
    assert compat["target_release"] == RELEASE
    assert row["source_config_sha256s"] == [V2495_CONFIG_SHA256]
    assert row["source_path_implementation_files"] == V2495_PATH_IMPLEMENTATION_FILES


def test_v2496_policy_numbers_are_hard_locked():
    cfg = load().load_config()
    p = cfg["early_exploration_acceptance"]
    assert p["through_outer_cycle"] == 8
    assert p["generation"]["max_cal_relative_degradation_for_severity_tradeoff"] == 0.02
    assert p["td"]["max_cal_relative_degradation"] == 0.05
    assert p["td"]["min_benefit_cost_ratio"] == 1.5
    assert p["severity"]["max_new_geh40"] == 0
    assert p["severity"]["absolute_geh_ceiling"] == 60.0


def test_v2496_rejects_unreviewed_relaxation_drift():
    cfg = load().load_config()
    cfg["early_exploration_acceptance"]["td"]["max_cal_relative_degradation"] = 0.10
    with pytest.raises(SupplyContractError, match="EARLY_EXPLORATION_POLICY"):
        validate_v2496_config(cfg, ROOT)


def test_v2496_retains_v2495_post_exploration_contract():
    cfg = load().load_config()
    assert cfg["min_cal_objective_relative_improvement"] == 0.001
    assert cfg["td"]["max_cal_geh_relative_degradation"] == 0.005
    assert cfg["geh20_transition_policy"]["mode"] == "HYSTERESIS_BUDGET"
    assert cfg["geh20_transition_policy"]["max_new_geh30"] == 0


def test_v2496_run_root_is_not_nested(tmp_path):
    module = load()
    project = tmp_path / "2022"
    source = (project / "R1_15A2_V2495_RUNS" / "RUN_A" /
              "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == project.resolve()
    new_run = project / "R1_15A2_V2496_RUNS" / "RUN_X"
    module._assert_new_run_is_not_nested(
        new_run, layout["detected_run_roots_nearest_first"])
