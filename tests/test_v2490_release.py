# -*- coding: utf-8 -*-
from __future__ import annotations
import copy
import hashlib
import importlib.util
from pathlib import Path
import pytest

from r1_15a2_safety_v2490 import (
    RELEASE, V19_ID, V19_REL, V19_SHA256, V2489_CONFIG_SHA256,
    V2489_PATH_IMPLEMENTATION_FILES, V2489_RELEASE, validate_v2490_config,
)
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = 'R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_0.py'


def load():
    spec = importlib.util.spec_from_file_location('v2490_launcher', ROOT / LAUNCHER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_v2490_release_config_contract():
    m = load(); cfg = m.load_config(); out = validate_v2490_config(cfg, ROOT)
    assert m.RELEASE == cfg['release'] == cfg['safety_gate_release'] == RELEASE
    assert cfg['performance']['release'] == 'V2.4.9.0'
    assert out['survey_reference_role'] == 'SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT'
    assert out['exact_curve_match_required'] is False
    assert out['native_ipf_tolerance_relaxed'] is False


def test_v2490_v2489_cache_predecessor_is_exactly_pinned():
    cfg = load().load_config()
    compat = cfg['performance']['persistent_path_cache']['explicit_predecessor_read_compatibility']
    assert compat['target_release'] == RELEASE
    row = next(r for r in compat['predecessors'] if r['source_release'] == V2489_RELEASE)
    assert row['source_config_sha256s'] == [V2489_CONFIG_SHA256]
    assert row['source_path_implementation_files'] == V2489_PATH_IMPLEMENTATION_FILES
    assert len(row['source_path_implementation_files']) == 7


def test_v2490_v19_reference_bytes_are_hash_locked():
    p = ROOT / V19_REL
    assert p.is_file()
    assert hashlib.sha256(p.read_bytes()).hexdigest() == V19_SHA256
    text = p.read_text(encoding='utf-8')
    assert V19_ID in text
    assert 'minimum_relative_objective_improvement' in text


def test_v2490_soft_reference_not_exact_curve_matching():
    cfg = load().load_config()
    fine = cfg['coupled_demand']['finecdf_td']
    td = cfg['td']; soft = cfg['td_soft_reference_policy']
    assert fine['survey_reference_role'] == 'SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT'
    assert fine['exact_curve_match_required'] is False
    assert td['acceptance_policy'] == 'AGGREGATE_SELECTED_IMPROVEMENT_WITH_BOUNDED_COMPONENT_TRADEOFF'
    assert td['exact_curve_match_required'] is False
    assert td['min_selected_component_relative_improvement'] == pytest.approx(.005)
    assert td['max_selected_component_relative_degradation'] == pytest.approx(.05)
    assert td['max_nonselected_component_objective_degradation'] == pytest.approx(.05)
    assert soft['native_ipf_tolerance_relaxed'] is False


def test_v2490_retains_hard_count_guard():
    cfg = load().load_config()
    assert cfg['td']['max_cal_geh2_relative_degradation'] == pytest.approx(.005)


def test_v2490_rejects_ipf_tolerance_relaxation():
    m = load(); cfg = m.load_config()
    cfg['coupled_demand']['finecdf_td']['ipf_tolerance_policy'] = 'RELAX'
    with pytest.raises(SupplyContractError, match='IPF_TOLERANCE'):
        validate_v2490_config(cfg, ROOT)


def test_v2490_rejects_exact_curve_match_reintroduction():
    m = load(); cfg = m.load_config()
    cfg['coupled_demand']['finecdf_td']['exact_curve_match_required'] = True
    with pytest.raises(SupplyContractError, match='SOFT_REFERENCE|SURVEY'):
        validate_v2490_config(cfg, ROOT)


def test_v2490_rejects_widened_td_readback_tolerance():
    m = load(); cfg = m.load_config()
    cfg['coupled_demand']['finecdf_td']['realization_parameter_atol'] = 1e-6
    cfg['td_parameter_freeze_policy']['absolute_tolerance'] = 1e-6
    with pytest.raises(SupplyContractError, match='ATOL_TOO_WIDE'):
        validate_v2490_config(cfg, ROOT)


def test_v2490_nested_checkpoint_normalizes_to_project_root(tmp_path):
    m = load(); project = tmp_path / '2022'
    src = project / 'R1_15A2_V2481_RUNS' / 'RUN_A' / 'CALIBRATION' / 'CHECKPOINTS' / \
          'R1_15A2_V2489_RUNS' / 'RUN_B' / 'CALIBRATION' / 'CHECKPOINTS' / 'ACCEPTED.ver'
    src.parent.mkdir(parents=True); src.write_bytes(b'x')
    layout = m._stable_project_layout(src)
    assert layout['project_base'] == project.resolve()
    new_run = project / 'R1_15A2_V2490_RUNS' / 'RUN_X'
    m._assert_new_run_is_not_nested(new_run, layout['detected_run_roots_nearest_first'])
