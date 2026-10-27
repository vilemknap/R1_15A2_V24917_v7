# -*- coding: utf-8 -*-
from __future__ import annotations
import importlib.util
from pathlib import Path
import pytest
from r1_15a2_safety_v2489 import validate_v2489_config
from r1_15a2_supply import SupplyContractError

ROOT=Path(__file__).resolve().parents[1]
RELEASE='R1_15A2_V2_4_8_9_TD_REALIZATION_STABILIZATION_20261016'
LAUNCHER='R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_9.py'

def load():
    spec=importlib.util.spec_from_file_location("v2489_launcher", ROOT/LAUNCHER)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def test_v2489_release_config_contract():
    m=load(); cfg=m.load_config(); out=validate_v2489_config(cfg, ROOT)
    assert m.RELEASE == cfg["release"] == cfg["safety_gate_release"] == RELEASE
    assert out["ipf_tolerance_relaxed"] is False
    assert out["next_generation_requires_td_realization"] is True

def test_v2489_v2488_cache_predecessor_is_pinned():
    cfg=load().load_config()
    rows=cfg["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"]["predecessors"]
    row=next(r for r in rows if r["source_release"] == "R1_15A2_V2_4_8_8_PATH_CACHE_SEMANTIC_COMPAT_20261016")
    assert row["source_config_sha256s"] == ["0d8af79ad2f3cd069f9413a32cd4f3ab4f4d56042ca3ecb66b4c74a1c7d57a03"]
    assert len(row["source_path_implementation_files"]) == 7

def test_v2489_rejects_ipf_tolerance_relaxation():
    m=load(); cfg=m.load_config(); cfg["coupled_demand"]["finecdf_td"]["ipf_tolerance_policy"]="RELAX"
    with pytest.raises(SupplyContractError, match="IPF_TOLERANCE"):
        validate_v2489_config(cfg, ROOT)

def test_v2489_nested_checkpoint_normalizes_to_project_root(tmp_path):
    m=load(); project=tmp_path/"2022"
    src=project/"R1_15A2_V2481_RUNS"/"RUN_A"/"CALIBRATION"/"CHECKPOINTS"/"ACCEPTED.ver"
    src.parent.mkdir(parents=True); src.write_bytes(b"x")
    layout=m._stable_project_layout(src)
    assert layout["project_base"] == project.resolve()
    m._assert_new_run_is_not_nested(project/"R1_15A2_V2489_RUNS"/"RUN_X", layout["detected_run_roots_nearest_first"])
