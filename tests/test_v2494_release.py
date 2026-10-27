# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from r1_15a2_safety_v2494 import (
    RELEASE, V2493_CONFIG_SHA256, V2493_PATH_IMPLEMENTATION_FILES,
    V2493_RELEASE, validate_v2494_config,
)
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_4.py"


def load():
    spec = importlib.util.spec_from_file_location("v2494_launcher", ROOT / LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2494_release_contract_validates():
    module = load()
    cfg = module.load_config()
    out = validate_v2494_config(cfg, ROOT)
    assert module.RELEASE == cfg["release"] == cfg["safety_gate_release"] == RELEASE
    assert out["path_export_retry"] == "SAME_RANGE_TRANSIENT_ONLY"
    assert out["page_size_fallback"] == "NONTRANSIENT_MEMORY_OR_RANGE_ONLY"
    assert out["restart_authority"] == "SEMANTIC_MODEL_STATE"
    assert out["production_ready"] is False


def test_v2494_exactly_pins_v2493_path_cache_predecessor():
    cfg = load().load_config()
    compat = cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    row = next(r for r in compat["predecessors"]
               if r["source_release"] == V2493_RELEASE)
    assert compat["target_release"] == RELEASE
    assert row["source_config_sha256s"] == [V2493_CONFIG_SHA256]
    assert row["source_path_implementation_files"] == V2493_PATH_IMPLEMENTATION_FILES


def test_v2494_raw_ver_sha_is_not_restart_acceptance_authority():
    cfg = load().load_config()
    restart = cfg["restart_authority"]
    assert restart["mode"] == "SEMANTIC_MODEL_STATE"
    assert restart["raw_ver_sha_used_for_restart_acceptance"] is False
    assert restart["cross_release_snapshot_state_hash_comparison_allowed"] is False
    assert restart["require_source_unchanged_during_run"] is True
    assert "NOT_CROSS_RUN_RESTART_ACCEPTANCE" in restart["raw_ver_sha_role"]


def test_v2494_active_path_export_has_no_unwrapped_raw_ole_invoke():
    for name in (
        "r1_15a2_two_mode_v238.py",
        "r1_15a2_runtime_v1.py",
        "r1_15a2_live_api_audit.py",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert ".Invoke(" not in text, name
    helper = (ROOT / "r1_15a2_com_compat.py").read_text(encoding="utf-8")
    assert helper.count("ole.Invoke(") == 1
    assert "bounded_ole_invoke_with_retry" in helper


def test_v2494_rejects_page_fallback_for_all_exceptions():
    cfg = load().load_config()
    cfg["com_resilience"]["page_size_fallback_policy"] = "ALL_COM_ERRORS"
    with pytest.raises(SupplyContractError, match="COM_PATH_EXPORT_RETRY"):
        validate_v2494_config(cfg, ROOT)


def test_v2494_rejects_raw_sha_restart_gate():
    cfg = load().load_config()
    cfg["restart_authority"]["raw_ver_sha_used_for_restart_acceptance"] = True
    with pytest.raises(SupplyContractError, match="SEMANTIC_RESTART"):
        validate_v2494_config(cfg, ROOT)


def test_v2494_run_root_is_not_nested(tmp_path):
    module = load()
    project = tmp_path / "2022"
    source = (project / "R1_15A2_V2493_RUNS" / "RUN_A" /
              "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == project.resolve()
    new_run = project / "R1_15A2_V2494_RUNS" / "RUN_X"
    module._assert_new_run_is_not_nested(
        new_run, layout["detected_run_roots_nearest_first"])
