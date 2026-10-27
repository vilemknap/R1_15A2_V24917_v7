from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

import r1_15a2_core as core

ROOT = Path(__file__).resolve().parents[1]


def _model_for_geh(observed: float, target_geh: float) -> float:
    o = float(observed)
    g = float(target_geh)
    d = (g * g + math.sqrt(g ** 4 + 16.0 * g * g * o)) / 4.0
    return o + d


def _row(code: str, geh_value: float, observed: float = 1000.0, weight: float = 1.0):
    return {
        "role": "CALIBRATION",
        "countlocation_no": code,
        "observed": observed,
        "model": _model_for_geh(observed, geh_value),
        "profile_weight": weight,
    }


def _cfg(cycle: int = 1, scope: str = "GENERATION"):
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_12.json").read_text(encoding="utf-8"))
    cfg["runtime_acceptance_outer_cycle"] = cycle
    cfg["runtime_acceptance_scope"] = scope
    return cfg


def test_v24912_policy_is_active_through_cycle_12_and_not_after_horizon():
    for cycle in (1, 8, 9, 12):
        p = core.early_exploration_policy(_cfg(cycle), "GENERATION")
        assert p is not None
        assert p["through_outer_cycle"] == 12
        assert p["severity"]["policy_level"] == "BASELINE_RELATIVE_BUDGET_V24912"
    assert core.early_exploration_policy(_cfg(13), "GENERATION") is None


def test_v24912_small_geh60_threshold_crossing_is_diagnostic_not_absolute_veto():
    cfg = _cfg(2, "GENERATION")
    guard = core.severity_transition_guard([_row("A", 59.5)], [_row("A", 60.5)], cfg, "GENERATION")
    assert guard["passes"] is True
    assert len(guard["new_geh60"]) == 1
    assert guard["high_geh_delta_violations"] == []
    assert "ABSOLUTE_GEH_CEILING_EXCEEDED" not in guard["violation_codes"]
    assert "V24912_GEH60_THRESHOLD_CROSSING_DIAGNOSTIC_ONLY" in guard["warning_codes"]


def test_v24912_high_geh_material_delta_remains_hard():
    cfg = _cfg(2, "TD")
    guard = core.severity_transition_guard([_row("A", 70.0)], [_row("A", 81.0)], cfg, "TD")
    assert guard["passes"] is False
    assert "V24912_HIGH_GEH_DELTA_BUDGET_EXCEEDED" in guard["violation_codes"]


def test_v24912_single_profile_increase_over_15_remains_hard():
    cfg = _cfg(2, "GENERATION")
    guard = core.severity_transition_guard([_row("A", 10.0)], [_row("A", 26.0)], cfg, "GENERATION")
    assert guard["passes"] is False
    assert "SINGLE_PROFILE_GEH_INCREASE_EXCEEDED" in guard["violation_codes"]


def test_v24912_geh40_uses_net_count_budget_generation_five_pass_six_fail():
    cfg = _cfg(2, "GENERATION")
    stable_before = [_row(f"H{i}", 50.0) for i in range(100)]
    stable_after = [_row(f"H{i}", 50.0) for i in range(100)]

    before5 = stable_before + [_row(f"N{i}", 39.9) for i in range(5)]
    after5 = stable_after + [_row(f"N{i}", 40.1) for i in range(5)]
    g5 = core.severity_transition_guard(before5, after5, cfg, "GENERATION")
    assert g5["geh40_net_count_increase"] == 5
    assert g5["passes"] is True

    before6 = stable_before + [_row(f"N{i}", 39.9) for i in range(6)]
    after6 = stable_after + [_row(f"N{i}", 40.1) for i in range(6)]
    g6 = core.severity_transition_guard(before6, after6, cfg, "GENERATION")
    assert g6["geh40_net_count_increase"] == 6
    assert g6["passes"] is False
    assert "V24912_GEH40_NET_COUNT_BUDGET_EXCEEDED" in g6["violation_codes"]


def test_v24912_td_has_fifteen_profile_geh40_net_budget():
    cfg = _cfg(2, "TD")
    stable_before = [_row(f"H{i}", 50.0) for i in range(100)]
    stable_after = [_row(f"H{i}", 50.0) for i in range(100)]
    before = stable_before + [_row(f"N{i}", 39.9) for i in range(15)]
    after = stable_after + [_row(f"N{i}", 40.1) for i in range(15)]
    guard = core.severity_transition_guard(before, after, cfg, "TD")
    assert guard["geh40_net_count_increase"] == 15
    assert guard["passes"] is True


def test_v24912_continuous_severity_budgets_are_scope_specific():
    # Same severity movement is deliberately too large for Generation but
    # remains inside TD's wider early-distribution budget.
    before = [_row(f"A{i}", 50.0) for i in range(100)]
    after = [_row(f"A{i}", 52.5) for i in range(100)]
    gen = core.severity_transition_guard(before, after, _cfg(2, "GENERATION"), "GENERATION")
    td = core.severity_transition_guard(before, after, _cfg(2, "TD"), "TD")
    assert gen["severity20_relative_degradation"] > 0.08
    assert "V24912_SEVERITY20_BUDGET_EXCEEDED" in gen["violation_codes"]
    assert td["severity20_relative_degradation"] < 0.25
    assert td["severity30_relative_degradation"] < 0.30
    assert td["passes"] is True


def test_v24912_protected_profile_lt5_to_ge20_remains_hard():
    cfg = _cfg(2, "GENERATION")
    guard = core.protected_profile_guard([_row("A", 4.0)], [_row("A", 20.0)], cfg, "GENERATION")
    assert guard["passes"] is False


def test_v24912_positive_generation_candidate_is_not_blocked_by_small_high_threshold_crossing():
    cfg = _cfg(2, "GENERATION")
    before = [_row("DRIVER", 60.0), _row("EDGE", 59.5)]
    after = [_row("DRIVER", 58.0), _row("EDGE", 60.5)]
    decision = core.acceptance_decision(before, after, {}, {}, cfg, "GENERATION")
    assert decision["cal_objective_relative_improvement"] > 0.0
    assert decision["severity_transition_guard"]["passes"] is True
    assert decision["accepted"] is True


def test_v24912_safety_validator_accepts_runtime_config_and_pins_parent():
    if (ROOT / "R1_15A2_CONFIG_V2_4_9_13.json").is_file():
        pytest.skip("V24912 runtime manifest is intentionally superseded by V24913 shared-core changes")
    p = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py"
    spec = importlib.util.spec_from_file_location("v24912_launcher_for_test", p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cfg = module.load_config()
    assert cfg["release"] == "R1_15A2_V2_4_9_12_GUARD_POLICY_REBASE_20261018"
    assert cfg["package_revision"] == "V24912_COMPLETE_R2"
    assert cfg["implementation_files"]["r1_15a2_guard_policy_v24912.py"]
    from r1_15a2_safety_v24912 import validate_v24912_config, validate_v24912_runtime_bundle
    out = validate_v24912_config(cfg, ROOT)
    runtime = validate_v24912_runtime_bundle(cfg, ROOT)
    assert runtime["passes"] is True
    assert out["passes"] is True
    assert out["production_ready"] is False
    assert out["real_visum_tested"] is False


def test_v24912_safety_rejects_budget_tamper():
    p = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py"
    spec = importlib.util.spec_from_file_location("v24912_launcher_for_tamper_test", p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cfg = module.load_config()
    cfg["early_exploration_acceptance"]["td"]["max_cal_relative_degradation"] = 0.50
    from r1_15a2_safety_v24912 import validate_v24912_config
    with pytest.raises(Exception, match="V24912_TD_PARETO_CHANGED"):
        validate_v24912_config(cfg, ROOT)
