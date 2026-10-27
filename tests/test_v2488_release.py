# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
from pathlib import Path

from r1_15a2_safety_v2488 import validate_v2488_config

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "R1_15A2_V2_4_8_8_PATH_CACHE_SEMANTIC_COMPAT_20261016"


def load_launcher():
    path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_8.py"
    spec = importlib.util.spec_from_file_location("v2488_launcher_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2488_release_config_and_safety_contract():
    module = load_launcher()
    cfg = module.load_config()
    result = validate_v2488_config(cfg, ROOT)
    assert module.RELEASE == RELEASE == cfg["release"] == cfg["safety_gate_release"]
    compat = cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    assert compat["policy"] == \
        "READ_ONLY_EXACT_PATH_DATA_CONTRACT_FULL_SOURCE_IMPL_PIN_CONFIG_DIGEST_PROVENANCE_ONLY"
    assert compat["incompatible_candidate_policy"] == \
        "REJECT_CACHE_AS_PERFORMANCE_MISS_THEN_LEGACY_OR_FRESH_ENUMERATION"
    assert result["full_config_digest_role"] == \
        "PROVENANCE_ONLY_FOR_PATH_CACHE_COMPATIBILITY"
    assert len(compat["predecessors"]) == 10


def test_v2488_run_root_stays_at_project_root_for_nested_checkpoint(tmp_path):
    module = load_launcher()
    project = tmp_path / "2022"
    source = project / "R1_15A2_V2481_RUNS" / "RUN_A" / "CALIBRATION" / \
        "CHECKPOINTS" / "R1_15A2_V2483_RUNS" / "RUN_B" / "CALIBRATION" / \
        "CHECKPOINTS" / "ACCEPTED.ver"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"probe")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == project.resolve()
    new_run = project / "R1_15A2_V2488_RUNS" / "RUN_TEST"
    module._assert_new_run_is_not_nested(new_run, layout["detected_run_roots_nearest_first"])
