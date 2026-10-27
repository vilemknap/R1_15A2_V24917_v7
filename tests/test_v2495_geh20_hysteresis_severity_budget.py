from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

import r1_15a2_core as core

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "v2495_master_for_test",
    ROOT / "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
)
master = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(master)


def _model_for_geh(observed: float, target_geh: float) -> float:
    """Return model > observed with the requested GEH value."""
    o = float(observed)
    g = float(target_geh)
    d = (g * g + math.sqrt(g ** 4 + 16.0 * g * g * o)) / 4.0
    return o + d


def _row(code: str, geh_value: float, observed: float = 1000.0):
    return {
        "role": "CALIBRATION",
        "countlocation_no": code,
        "observed": observed,
        "model": _model_for_geh(observed, geh_value),
        "profile_weight": 1.0,
    }


def _policy():
    return {
        "mode": "HYSTERESIS_BUDGET",
        "threshold": 20.0,
        "hysteresis_low": 19.5,
        "hysteresis_high": 20.5,
        "max_new_geh30": 0,
        "generation": {
            "max_material_new_geh20": 3,
            "max_single_profile_geh_increase": 2.0,
            "max_total_new_geh20_excess": 2.0,
        },
        "td": {
            "max_material_new_geh20": 1,
            "max_single_profile_geh_increase": 1.0,
            "max_total_new_geh20_excess": 0.75,
        },
        "legacy_max_new_geh20_role": "IGNORED_WHEN_HYSTERESIS_BUDGET_ENABLED",
        "continuous_penalty_role": "DEFERRED_NOT_IMPLEMENTED_IN_V2495",
    }


def _cfg():
    return {
        "geh20_transition_policy": _policy(),
        "max_new_geh20": 0,
        "max_new_geh30": 0,
        "max_protected_to_warn": 3,
        "max_protected_to_hard": 0,
        "protected_geh": 5.0,
        "protected_warn_geh": 10.0,
        "protected_hard_geh": 30.0,
        "min_cal_objective_relative_improvement": 0.001,
        "idp_max_mean_degradation": 0.005,
        "idp_max_component_degradation": 0.02,
        "csd_calibration_objective": {"metric": "WEIGHTED_MEAN_GEH"},
        "td": {
            "min_selected_component_relative_improvement": 0.005,
            "max_selected_component_relative_degradation": 0.05,
            "max_nonselected_component_objective_degradation": 0.05,
            "max_cal_geh_relative_degradation": 0.005,
            "max_cal_geh2_relative_degradation": 0.005,
            "max_global_idp_mean_degradation": 0.01,
            "max_global_idp_component_degradation": 0.05,
        },
    }


def _summary(obj: float):
    return {
        "component_dist_summary_rows": [{
            "component": "WORK_E_C",
            "family": "WORK",
            "target_status": "ACTIVE_COMPONENT_DIST_TARGET",
            "mean_model_conditioned": 10.0,
            "mean_target": 10.0,
            "l1_distance_half": obj,
            "rmse_share": 0.0,
        }]
    }


def _signal(obj: float):
    return {
        "WORK_E_C": {
            "component": "WORK_E_C",
            "family": "WORK",
            "calibratable": True,
            "l1_half": obj,
            "rmse_share": 0.0,
            "mean_target": 10.0,
            "mean_delta": 0.0,
            "conditioned_volume": 1000.0,
        }
    }


def test_hysteresis_crossing_19_84_to_20_02_is_diagnostic_only():
    guard = core.severity_transition_guard(
        [_row("A", 19.84)], [_row("A", 20.02)], _cfg(), "GENERATION")
    assert guard["passes"] is True
    assert len(guard["new_geh20"]) == 1
    assert len(guard["hysteresis_geh20"]) == 1
    assert len(guard["material_new_geh20"]) == 0
    assert guard["total_new_geh20_excess"] == pytest.approx(0.0)


def test_generation_allows_three_bounded_material_crossings():
    before = [_row("A", 19.0), _row("B", 19.0), _row("C", 19.0)]
    after = [_row("A", 20.4), _row("B", 20.4), _row("C", 20.4)]
    guard = core.severity_transition_guard(before, after, _cfg(), "GENERATION")
    assert guard["passes"] is True
    assert guard["material_new_geh20_count"] == 3
    assert guard["total_new_geh20_excess"] == pytest.approx(1.2, abs=1e-9)
    assert guard["violation_codes"] == []


def test_generation_rejects_fourth_material_crossing():
    before = [_row(c, 19.0) for c in "ABCD"]
    after = [_row(c, 20.4) for c in "ABCD"]
    guard = core.severity_transition_guard(before, after, _cfg(), "GENERATION")
    assert guard["passes"] is False
    assert "MATERIAL_NEW_GEH20_COUNT_EXCEEDED" in guard["violation_codes"]


def test_generation_rejects_single_jump_above_two_geh_points():
    guard = core.severity_transition_guard(
        [_row("A", 19.0)], [_row("A", 21.2)], _cfg(), "GENERATION")
    assert guard["passes"] is False
    assert "SINGLE_PROFILE_GEH_INCREASE_EXCEEDED" in guard["violation_codes"]


def test_generation_rejects_total_new_geh20_excess_budget():
    before = [_row("A", 19.2), _row("B", 19.2)]
    after = [_row("A", 21.2), _row("B", 21.2)]
    guard = core.severity_transition_guard(before, after, _cfg(), "GENERATION")
    assert guard["passes"] is False
    assert guard["total_new_geh20_excess"] == pytest.approx(2.4, abs=1e-9)
    assert "TOTAL_NEW_GEH20_EXCESS_EXCEEDED" in guard["violation_codes"]


def test_td_budget_is_tighter_than_generation_budget():
    before = [_row("A", 19.4), _row("B", 19.4)]
    after = [_row("A", 20.4), _row("B", 20.4)]
    gen = core.severity_transition_guard(before, after, _cfg(), "GENERATION")
    td = core.severity_transition_guard(before, after, _cfg(), "TD")
    assert gen["passes"] is True
    assert td["passes"] is False
    assert td["material_new_geh20_count"] == 2
    assert "MATERIAL_NEW_GEH20_COUNT_EXCEEDED" in td["violation_codes"]


def test_new_geh30_remains_hard_zero_tolerance():
    guard = core.severity_transition_guard(
        [_row("A", 29.0)], [_row("A", 30.01)], _cfg(), "GENERATION")
    assert guard["passes"] is False
    assert len(guard["new_geh30"]) == 1
    assert "NEW_GEH30_COUNT_EXCEEDED" in guard["violation_codes"]


def test_legacy_config_without_policy_keeps_old_zero_tolerance_wall():
    legacy = {
        "max_new_geh20": 0,
        "max_new_geh30": 0,
    }
    guard = core.severity_transition_guard(
        [_row("A", 19.84)], [_row("A", 20.02)], legacy, "GENERATION")
    assert guard["mode"] == "LEGACY_DISCRETE_COUNT"
    assert guard["passes"] is False


def test_generation_acceptance_uses_generation_hysteresis_budget():
    cfg = _cfg()
    before = [_row("GOOD_EDGE", 19.84), _row("BAD_EDGE", 35.0)]
    after = [_row("GOOD_EDGE", 20.02), _row("BAD_EDGE", 10.0)]
    decision = core.acceptance_decision(before, after, {}, {}, cfg)
    assert decision["accepted"] is True
    guard = decision["severity_transition_guard"]
    assert guard["policy_scope"] == "GENERATION"
    assert len(guard["hysteresis_geh20"]) == 1


def test_td_acceptance_uses_tighter_td_budget():
    cfg = _cfg()
    before = [_row("A", 19.4), _row("B", 19.4), _row("BAD", 35.0)]
    after = [_row("A", 20.4), _row("B", 20.4), _row("BAD", 10.0)]
    decision = master.td_acceptance_decision(
        before, after,
        _summary(0.20), _summary(0.10),
        _signal(0.20), _signal(0.10),
        ["WORK_E_C"], cfg,
    )
    assert decision["accepted"] is False
    assert "NEW_SEVERE_GEH_PROFILE" in decision["reasons"]
    guard = decision["severity_transition_guard"]
    assert guard["policy_scope"] == "TD"
    assert "MATERIAL_NEW_GEH20_COUNT_EXCEEDED" in guard["violation_codes"]
