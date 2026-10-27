# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

from r1_15a2_safety_v2492 import (
    RELEASE, V2490_CONFIG_SHA256, V2490_PATH_IMPLEMENTATION_FILES,
    V2490_RELEASE, validate_v2492_config,
)
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_2.py"


def load():
    spec = importlib.util.spec_from_file_location("v2492_launcher", ROOT / LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2492_release_and_signed_contract_validate():
    module = load()
    cfg = module.load_config()
    out = validate_v2492_config(cfg, ROOT)
    assert module.RELEASE == cfg["release"] == cfg["safety_gate_release"] == RELEASE
    assert cfg["guidance_mode"] == "SIGNED"
    assert cfg["allow_signed_apply"] is True
    assert out["generation_decomposition"] == \
        "FAMILY_GLOBAL_PLUS_NONLINEAR_CENTERED_ZONE_LOG_EFFECT"
    assert out["late_cycle_stage"] == "DISTRIBUTION_FOCUS"


def test_v2492_exactly_pins_v2490_path_cache_predecessor():
    cfg = load().load_config()
    compat = cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    row = next(r for r in compat["predecessors"]
               if r["source_release"] == V2490_RELEASE)
    assert compat["target_release"] == RELEASE
    assert row["source_config_sha256s"] == [V2490_CONFIG_SHA256]
    assert row["source_path_implementation_files"] == V2490_PATH_IMPLEMENTATION_FILES


def test_v2492_rejects_positive_only_regression():
    module = load(); cfg = module.load_config()
    cfg["guidance_mode"] = "POSITIVE_ONLY"
    with pytest.raises(SupplyContractError, match="SIGNED_GUIDANCE"):
        validate_v2492_config(cfg, ROOT)


def test_v2492_rejects_unbounded_domestic_coefficients():
    module = load(); cfg = module.load_config()
    cfg["generation_signed_refinement"]["domestic_hard_max"] = 99.0
    with pytest.raises(SupplyContractError, match="SIGNED_POLICY_CHANGED"):
        validate_v2492_config(cfg, ROOT)


def test_v2492_rejects_late_generation_stage_widening():
    module = load(); cfg = module.load_config()
    cfg["performance"]["generation_step_schedule"][-1]["max_add_log_up"] = 0.04
    with pytest.raises(SupplyContractError, match="STAGE_LIMIT"):
        validate_v2492_config(cfg, ROOT)


def test_v2492_retains_v2490_td_soft_reference_contract():
    cfg = load().load_config()
    assert cfg["td_soft_reference_policy"]["exact_curve_match_required"] is False
    assert cfg["coupled_demand"]["finecdf_td"]["ipf_tolerance_policy"] == \
        "UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR"
    assert cfg["td_parameter_freeze_policy"]["unrequested_change_above_tolerance"] == \
        "FAIL_CLOSED"


def test_v2492_run_root_is_not_nested(tmp_path):
    module = load(); project = tmp_path / "2022"
    src = project / "R1_15A2_V2489_RUNS" / "RUN_A" / "CALIBRATION" / \
          "CHECKPOINTS" / "ACCEPTED.ver"
    src.parent.mkdir(parents=True); src.write_bytes(b"x")
    layout = module._stable_project_layout(src)
    assert layout["project_base"] == project.resolve()
    new_run = project / "R1_15A2_V2492_RUNS" / "RUN_X"
    module._assert_new_run_is_not_nested(new_run,
                                         layout["detected_run_roots_nearest_first"])
