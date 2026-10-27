# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

import r1_15a2_core as core
from r1_15a2_safety_v2493 import (
    RELEASE, V2492_CONFIG_SHA256, V2492_PATH_IMPLEMENTATION_FILES,
    V2492_RELEASE, validate_v2493_config,
)
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_3.py"


def load():
    spec = importlib.util.spec_from_file_location("v2493_launcher", ROOT / LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2493_release_contract_validates():
    module = load(); cfg = module.load_config()
    out = validate_v2493_config(cfg, ROOT)
    assert module.RELEASE == cfg["release"] == cfg["safety_gate_release"] == RELEASE
    assert out["csd_calibration_objective"] == "WEIGHTED_MEAN_GEH"
    assert out["long_acceptance_mode"] == "GLOBAL_LONG_COMPOSITE"
    assert out["com_retry_scope"] == "TRANSIENT_ONLY"


def test_v2493_exactly_pins_v2492_path_cache_predecessor():
    cfg = load().load_config()
    compat = cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    row = next(r for r in compat["predecessors"]
               if r["source_release"] == V2492_RELEASE)
    assert compat["target_release"] == RELEASE
    assert row["source_config_sha256s"] == [V2492_CONFIG_SHA256]
    assert row["source_path_implementation_files"] == V2492_PATH_IMPLEMENTATION_FILES


def test_v2493_uses_weighted_mean_geh_and_keeps_individual_geh_guards():
    cfg = load().load_config()
    assert cfg["csd_calibration_objective"]["metric"] == "WEIGHTED_MEAN_GEH"
    assert core.csd_objective_key(cfg) == "objective_geh_mean_weighted"
    assert cfg["max_new_geh20"] == 0
    assert cfg["max_new_geh30"] == 0


def test_v2493_long_acceptance_is_global_composite():
    cfg = load().load_config()
    assert cfg["td"]["long_acceptance_mode"] == "GLOBAL_LONG_COMPOSITE"
    assert cfg["td"]["long_composite_authority"] == "AGGREGATE_CL_GUARD_GLOBAL_MIX"
    assert cfg["td"]["max_cal_geh_relative_degradation"] == 0.005


def test_v2493_com_contract_is_bounded_transient_only():
    cfg = load().load_config(); com = cfg["com_resilience"]
    assert com["enabled"] is True
    assert com["max_attempts"] == 5
    assert com["zone_identity_cache"] is True
    assert com["retryable_hresult"] == [-2147418111, -2147417846]
    assert com["retry_scope"] == "TRANSIENT_RPC_CALL_REJECTED_OR_RETRY_LATER_ONLY"


def test_v2493_rejects_geh2_regression():
    cfg = load().load_config()
    cfg["csd_calibration_objective"]["metric"] = "WEIGHTED_MEAN_GEH2"
    with pytest.raises(SupplyContractError, match="CSD_OBJECTIVE"):
        validate_v2493_config(cfg, ROOT)


def test_v2493_rejects_individual_long_acceptance_regression():
    cfg = load().load_config()
    cfg["td"]["long_acceptance_mode"] = "INDIVIDUAL_COMPONENTS"
    with pytest.raises(SupplyContractError, match="LONG_COMPOSITE"):
        validate_v2493_config(cfg, ROOT)


def test_v2493_rejects_unbounded_or_generic_com_retry():
    cfg = load().load_config()
    cfg["com_resilience"]["retry_scope"] = "ALL_EXCEPTIONS"
    with pytest.raises(SupplyContractError, match="COM_RESILIENCE"):
        validate_v2493_config(cfg, ROOT)


def test_v2493_run_root_is_not_nested(tmp_path):
    module = load(); project = tmp_path / "2022"
    src = project / "R1_15A2_V2492_RUNS" / "RUN_A" / "CALIBRATION" /           "CHECKPOINTS" / "ACCEPTED.ver"
    src.parent.mkdir(parents=True); src.write_bytes(b"x")
    layout = module._stable_project_layout(src)
    assert layout["project_base"] == project.resolve()
    new_run = project / "R1_15A2_V2493_RUNS" / "RUN_X"
    module._assert_new_run_is_not_nested(new_run,
                                         layout["detected_run_roots_nearest_first"])


def test_v2492_raw_config_keeps_legacy_geh2_default():
    import json
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_2.json").read_text(encoding="utf-8"))
    assert "csd_calibration_objective" not in cfg
    assert core.csd_objective_metric(cfg) == "WEIGHTED_MEAN_GEH2"
