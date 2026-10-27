from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

import r1_15a2_core as core
import r1_15a2_overnight_controller_v240 as ctl240
import r1_15a2_overnight_controller_v242 as ctl242

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "v2496_master_for_test",
    ROOT / "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
)
master = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(master)


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


def _base_cfg(cycle: int = 1, scope: str = "GENERATION"):
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_6.json").read_text(encoding="utf-8"))
    cfg["runtime_acceptance_outer_cycle"] = cycle
    cfg["runtime_acceptance_scope"] = scope
    return cfg


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


def _bulk_rows(before_geh: float, after_geh: float, n: int = 100):
    before = [_row(f"S{i}", before_geh) for i in range(n)]
    after = [_row(f"S{i}", after_geh) for i in range(n)]
    return before, after


def test_early_generation_accepts_any_real_positive_weighted_geh_improvement_and_soft_crossing():
    cfg = _base_cfg(3, "GENERATION")
    before = [_row("DRIVER", 50.0), _row("EDGE", 19.91)]
    after = [_row("DRIVER", 49.80), _row("EDGE", 20.08)]
    decision = core.acceptance_decision(before, after, {}, {}, cfg, "GENERATION")
    assert decision["accepted"] is True
    assert decision["active_acceptance_stage"] == "EARLY_EXPLORATION"
    assert decision["acceptance_path"] == "EARLY_EXPLORATION_ANY_POSITIVE_WEIGHTED_GEH"
    assert decision["severity_transition_guard"]["new_geh20"]
    assert decision["severity_transition_guard"]["passes"] is True


def test_early_generation_accepts_nonmonotonic_two_percent_tradeoff_when_severity_improves():
    cfg = _base_cfg(4, "GENERATION")
    before = [_row("HIGH", 50.0)] + [_row(f"M{i}", 20.0) for i in range(10)]
    after = [_row("HIGH", 40.0)] + [_row(f"M{i}", 21.1) for i in range(10)]
    decision = core.acceptance_decision(before, after, {}, {}, cfg, "GENERATION")
    assert decision["cal_objective_relative_improvement"] < 0.0
    assert -decision["cal_objective_relative_improvement"] < 0.02
    assert decision["severity_transition_guard"]["severity30_relative_improvement"] > 0.01
    assert decision["accepted"] is True
    assert decision["exploration_nonmonotonic_accepted"] is True
    assert decision["acceptance_path"] == "EARLY_EXPLORATION_NONMONOTONIC_SEVERITY_TRADEOFF"


def test_early_generation_rejects_more_than_two_percent_degradation_even_with_severity_gain():
    cfg = _base_cfg(4, "GENERATION")
    before = [_row("HIGH", 50.0)] + [_row(f"M{i}", 20.0) for i in range(10)]
    after = [_row("HIGH", 40.0)] + [_row(f"M{i}", 22.0) for i in range(10)]
    decision = core.acceptance_decision(before, after, {}, {}, cfg, "GENERATION")
    assert -decision["cal_objective_relative_improvement"] > 0.02
    assert decision["accepted"] is False
    assert "CAL_GEH_OBJECTIVE_NOT_IMPROVED" in decision["reasons"]


def test_early_severity_makes_geh20_30_soft_geh35_warning_and_geh40_hard():
    cfg = _base_cfg(2, "GENERATION")
    soft = core.severity_transition_guard(
        [_row("A", 19.0), _row("B", 29.0), _row("C", 34.0)],
        [_row("A", 24.0), _row("B", 32.0), _row("C", 36.0)], cfg, "GENERATION")
    assert soft["passes"] is True
    assert len(soft["new_geh20"]) == 1
    assert len(soft["new_geh30"]) == 1
    assert len(soft["new_geh35_warning"]) == 1
    hard = core.severity_transition_guard(
        [_row("A", 39.0)], [_row("A", 40.1)], cfg, "GENERATION")
    assert hard["passes"] is False
    assert "NEW_GEH40_COUNT_EXCEEDED" in hard["violation_codes"]


def test_early_severity_rejects_catastrophic_jump_and_absolute_ceiling():
    cfg = _base_cfg(2, "GENERATION")
    jump = core.severity_transition_guard(
        [_row("A", 10.0)], [_row("A", 26.0)], cfg, "GENERATION")
    assert jump["passes"] is False
    assert "SINGLE_PROFILE_GEH_INCREASE_EXCEEDED" in jump["violation_codes"]
    ceiling = core.severity_transition_guard(
        [_row("A", 55.0)], [_row("A", 61.0)], cfg, "GENERATION")
    assert ceiling["passes"] is False
    assert "ABSOLUTE_GEH_CEILING_EXCEEDED" in ceiling["violation_codes"]


def test_early_protected_profile_below_five_can_move_but_not_cross_twenty():
    cfg = _base_cfg(2, "GENERATION")
    allowed = core.protected_profile_guard([_row("A", 4.0)], [_row("A", 15.0)], cfg, "GENERATION")
    rejected = core.protected_profile_guard([_row("A", 4.0)], [_row("A", 20.0)], cfg, "GENERATION")
    assert allowed["passes"] is True
    assert rejected["passes"] is False
    assert rejected["mode"] == "EARLY_EXPLORATION_CATASTROPHIC_ONLY"


def test_early_td_accepts_live_like_five_point_five_percent_for_sub_one_percent_cal_cost():
    cfg = _base_cfg(3, "TD")
    before, after = _bulk_rows(50.0, 50.30, 100)
    before += [_row("C20", 19.82), _row("C30", 29.47)]
    after += [_row("C20", 21.01), _row("C30", 30.17)]
    decision = master.td_acceptance_decision(
        before, after, _summary(0.20), _summary(0.189),
        _signal(0.20), _signal(0.189), ["WORK_E_C"], cfg)
    assert decision["selected_relative_improvement"] > 0.05
    assert 0.0 < decision["cal_csd_relative_degradation"] < 0.01
    assert decision["benefit_cost_ratio"] > 1.5
    assert decision["severity_transition_guard"]["new_geh30"]
    assert decision["accepted"] is True


def test_early_td_accepts_scale_quarter_like_large_gain_and_two_point_six_percent_cal_cost():
    cfg = _base_cfg(3, "TD")
    before, after = _bulk_rows(50.0, 51.30, 100)
    before += [_row(f"N{i}", 28.0 + 0.1 * i) for i in range(7)]
    after += [_row(f"N{i}", 30.2 + 0.1 * i) for i in range(7)]
    decision = master.td_acceptance_decision(
        before, after, _summary(0.20), _summary(0.1568),
        _signal(0.20), _signal(0.1568), ["WORK_E_C"], cfg)
    assert decision["selected_relative_improvement"] > 0.20
    assert 0.02 < decision["cal_csd_relative_degradation"] < 0.05
    assert decision["accepted"] is True


def test_early_td_rejects_low_benefit_cost_and_more_than_five_percent_cal_loss():
    cfg = _base_cfg(3, "TD")
    before, after = _bulk_rows(50.0, 50.5, 100)
    low_ratio = master.td_acceptance_decision(
        before, after, _summary(0.20), _summary(0.198),
        _signal(0.20), _signal(0.198), ["WORK_E_C"], cfg)
    assert low_ratio["benefit_cost_ratio"] < 1.5
    assert "TD_BENEFIT_COST_RATIO_TOO_LOW" in low_ratio["reasons"]
    before2, after2 = _bulk_rows(50.0, 53.1, 100)
    too_costly = master.td_acceptance_decision(
        before2, after2, _summary(0.20), _summary(0.15),
        _signal(0.20), _signal(0.15), ["WORK_E_C"], cfg)
    assert too_costly["cal_csd_relative_degradation"] > 0.05
    assert "CAL_CSD_DEGRADED_TOO_MUCH" in too_costly["reasons"]


def test_cycle_nine_restores_v2495_hysteresis_and_monotonic_materiality():
    cfg = _base_cfg(9, "GENERATION")
    before = [_row("DRIVER", 50.0), _row("EDGE", 19.91)]
    after = [_row("DRIVER", 49.99), _row("EDGE", 20.08)]
    assert core.early_exploration_policy(cfg, "GENERATION") is None
    decision = core.acceptance_decision(before, after, {}, {}, cfg, "GENERATION")
    assert decision["active_acceptance_stage"] == "INHERITED"
    assert decision["accepted"] is False
    assert "CAL_GEH_OBJECTIVE_NOT_IMPROVED" in decision["reasons"]


def test_shared_objective_can_be_bypassed_only_for_reviewed_nonmonotonic_generation(monkeypatch, tmp_path):
    class Control:
        def checkpoint(self, *args, **kwargs):
            return None
    class Adapter:
        def __init__(self, nonmono):
            self.state = {"state_hash": "before"}
            self.nonmono = nonmono
        def snapshot(self):
            return dict(self.state)
        def assign(self, folder, supply_only=False):
            return 0.0
        def parameter_persistence(self, block, rows):
            return None
        def diagnostics(self, folder, label):
            return {"label": "after"}
        def block_gate(self, block, before, after, rows):
            return {"accepted": True, "reasons": [],
                    "exploration_nonmonotonic_accepted": self.nonmono}
    adapter = Adapter(True)
    before = {"state_hash": "before"}
    baseline_diag = {"label": "before"}
    monkeypatch.setattr(ctl240, "_apply_candidate",
                        lambda adapter, *args, **kwargs: (setattr(adapter, "state", {"state_hash": "after"}) or [{}]))
    monkeypatch.setattr(ctl240, "diagnostic_hash", lambda value: str(value))
    monkeypatch.setattr(ctl240, "assert_freeze", lambda *args, **kwargs: None)
    monkeypatch.setattr(ctl240, "ledger", lambda *args, **kwargs: {"total": 1.01})
    def rollback(adapter, block, before, *args, **kwargs):
        adapter.state = dict(before)
        return {"passes": True}, baseline_diag
    monkeypatch.setattr(ctl240, "rollback_and_verify", rollback)
    ev, _, err = ctl240._evaluate_candidate(
        adapter, {"shared_objective": {"minimum_improvement": 1e-8}}, object(),
        "GENERATION", {"scale": 1.0}, [{}], {}, before, baseline_diag,
        {"total": 1.0}, {}, {}, tmp_path / "YES", Control())
    assert err is None and ev["eligible"] is True
    assert ev["decision"]["shared_objective_monotonicity_bypassed"] is True
    adapter2 = Adapter(False)
    ev2, _, err2 = ctl240._evaluate_candidate(
        adapter2, {"shared_objective": {"minimum_improvement": 1e-8}}, object(),
        "GENERATION", {"scale": 1.0}, [{}], {}, before, baseline_diag,
        {"total": 1.0}, {}, {}, tmp_path / "NO", Control())
    assert err2 is None and ev2["eligible"] is False
    assert "SHARED_OBJECTIVE_NOT_IMPROVED" in ev2["decision"]["reasons"]


def test_best_so_far_checkpoint_is_dedicated_and_rotates_without_losing_current(tmp_path):
    class Adapter:
        cfg = {"restart_authority": {"checkpoint_semantic_sidecar": False}}
    src1 = tmp_path / "accepted1.ver"; src1.write_bytes(b"first")
    cp1 = {"path": str(src1), "sha256": ctl242._sha256_file(src1), "size": src1.stat().st_size}
    rec1 = ctl242._publish_best_so_far_checkpoint(
        Adapter(), tmp_path, cp1, {"state_hash": "aaa111"}, {"total": 1.0}, 1)
    best1 = Path(rec1["checkpoint"]["path"])
    assert best1.is_file() and best1.read_bytes() == b"first"
    src2 = tmp_path / "accepted2.ver"; src2.write_bytes(b"second")
    cp2 = {"path": str(src2), "sha256": ctl242._sha256_file(src2), "size": src2.stat().st_size}
    rec2 = ctl242._publish_best_so_far_checkpoint(
        Adapter(), tmp_path, cp2, {"state_hash": "bbb222"}, {"total": 0.9}, 2)
    best2 = Path(rec2["checkpoint"]["path"])
    pointer = json.loads((tmp_path / "BEST_SO_FAR_CHECKPOINT.json").read_text())
    assert best2.is_file() and pointer == rec2
    assert not best1.exists()
    assert src1.is_file() and src2.is_file()
