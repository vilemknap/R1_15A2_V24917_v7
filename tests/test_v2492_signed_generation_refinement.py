from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

import r1_15a2_core as core
import r1_15a2_multiblock as mb
from r1_15a2_overnight_controller_v242 import _generation_counts_cfg

ROOT = Path(__file__).resolve().parents[1]


def cfg():
    c = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_2.json").read_text(encoding="utf-8"))
    c["salary"]["enabled"] = False
    c["min_add_log_step"] = 1.0e-10
    return c


def zone(no, domestic=True, **values):
    row = {
        "zone_no": no,
        "NOT_ZAHR": 1 if domestic else 0,
        "ZAHR_SUSED": 0 if domestic else 1,
        "POP_ZP": 100.0,
        "AV_INCOME": 1500.0,
        "ADD_PROD_W": 1.0,
        "ADD_ATT_W": 1.0,
        "ADD_PROD_S": 1.0,
        "ADD_ATT_S": 1.0,
        "ADD_SALARY": 1.0,
        "ZAHR_PROD_WORK": 10.0,
        "ZAHR_ATR_WORK": 8.0,
        "ZAHR_PROD_SERV": 10.0,
        "ZAHR_ATR_SERV": 8.0,
    }
    row.update(values)
    return row


def prow(z, role, step, family="WORK", base=1000.0):
    return {
        "zone_no": z,
        "family": family,
        "role": role,
        "log_step": step,
        "base_margin_volume": base,
        "guided_margin_delta": base * math.expm1(step),
        "projected_margin_delta": base * math.expm1(step),
    }


def test_signed_design_can_raise_one_zone_and_lower_another_with_zero_total_pattern():
    c = cfg()
    # exp(+a)+exp(b)=2 makes the multiplicative weighted total exactly zero.
    a = 0.015
    b = math.log(2.0 - math.exp(a))
    projection = [
        prow(1, "PROD", a), prow(2, "PROD", b),
        prow(3, "ATT", a), prow(4, "ATT", b),
    ]
    design = mb.design_generation_candidates(
        projection, [zone(i) for i in range(1, 5)], c, reference_values=None)
    rows = [r for r in design["candidate_rows"] if r["attr"] in {"ADD_PROD_W", "ADD_ATT_W"}]
    effects = [float(r["actual_attr_log_effect"]) for r in rows]
    assert any(x > 0 for x in effects)
    assert any(x < 0 for x in effects)
    audit = design["summary"]["signed_generation_refinement"]
    assert audit["enabled"] is True
    assert audit["families"]["WORK"]["relative_gap_after"] < 1e-10
    work = design["summary"]["estimated_pa_delta_by_family"]["WORK"]
    assert abs(work["estimated_prod_delta"]) < 1e-7
    assert abs(work["estimated_att_delta"]) < 1e-7


def test_opposite_role_global_signs_remove_global_drift_but_keep_spatial_correction():
    c = cfg()
    projection = [
        prow(1, "PROD", 0.02), prow(2, "PROD", -0.005),
        prow(3, "ATT", 0.005), prow(4, "ATT", -0.02),
    ]
    design = mb.design_generation_candidates(
        projection, [zone(i) for i in range(1, 5)], c)
    audit = design["summary"]["signed_generation_refinement"]
    assert audit["families"]["WORK"]["status"] == "OPPOSITE_SIGN_GLOBAL_REMOVED"
    rows = design["candidate_rows"]
    assert any(float(r.get("actual_attr_log_effect", 0.0)) > 0 for r in rows)
    assert any(float(r.get("actual_attr_log_effect", 0.0)) < 0 for r in rows)
    work = design["summary"]["estimated_pa_delta_by_family"]["WORK"]
    assert work["estimated_abs_gap"] < 1e-7


def test_domestic_empirical_envelope_blocks_further_outward_drift_and_allows_return():
    c = cfg()
    low, high, policy = mb._multiplicative_coefficient_bounds(
        "DOMESTIC", c, current=2.10, reference=2.10)
    assert (low, high) == pytest.approx((0.5, 2.10))
    assert policy == "AMDY_LIKE_DOMESTIC_ABSOLUTE_ENVELOPE"
    # Because current is already above the hard envelope, a positive move has no room.
    assert math.log(high / 2.10) == pytest.approx(0.0)
    assert math.log(low / 2.10) < 0.0


def test_zahr_bounds_are_relative_to_run_start_reference_not_raw_two():
    c = cfg()
    low, high, policy = mb._multiplicative_coefficient_bounds(
        "ZAHR", c, current=10.0, reference=10.0)
    assert (low, high) == pytest.approx((5.0, 20.0))
    assert policy == "RUN_START_REFERENCE_RELATIVE_MULTIPLIER"


def test_soft_band_damps_only_outward_motion():
    outward, changed = mb._damp_outward_log_step(1.24, 0.06, 0.8, 1.25, 0.25)
    inward, inward_changed = mb._damp_outward_log_step(1.24, -0.06, 0.8, 1.25, 0.25)
    assert changed is True
    assert 0.0 < outward < 0.06
    assert inward == pytest.approx(-0.06)
    assert inward_changed is False


def test_generation_schedule_becomes_tighter_and_more_distribution_focused():
    base = cfg()
    early = _generation_counts_cfg(base, 1)
    middle = _generation_counts_cfg(base, 3)
    late = _generation_counts_cfg(base, 5)
    assert early["max_add_log_up"] == pytest.approx(0.06)
    assert early["max_add_log_down"] == pytest.approx(0.06)
    assert middle["max_add_log_up"] == pytest.approx(0.04)
    assert late["max_add_log_up"] == pytest.approx(0.02)
    assert late["max_add_log_down"] == pytest.approx(0.02)
    assert late["generation_signed_refinement"]["max_family_global_log_up"] == pytest.approx(0.005)
    assert early["generation_signed_refinement"]["max_family_global_log_up"] == pytest.approx(0.03)


def test_signed_guidance_keeps_overloaded_profiles_as_negative_drivers():
    # Minimal direct sparse incidence with one underloaded and one overloaded profile.
    op = core.SparseOperator(
        core.np.asarray([0, 1], dtype=core.np.int64),
        core.np.asarray([0, 1], dtype=core.np.int64),
        core.np.asarray([1.0, 1.0], dtype=float), 2, 2)
    incidence = {
        "profiles": [
            {"role": "CALIBRATION", "observed": 2000.0, "model": 1000.0, "profile_weight": 1.0},
            {"role": "CALIBRATION", "observed": 1000.0, "model": 2000.0, "profile_weight": 1.0},
        ],
        "variables": [
            {"dseg_code": "NATIVE_CW", "origin": 1, "destination": 2, "q_current": 100.0, "family": "WORK"},
            {"dseg_code": "NATIVE_CW", "origin": 2, "destination": 1, "q_current": 100.0, "family": "WORK"},
        ],
        "incidence": op,
        "q_current": core.np.asarray([100.0, 100.0]),
        "full_profile_model_from_paths": core.np.asarray([1000.0, 2000.0]),
        "mutable_profile_model_from_paths": core.np.asarray([1000.0, 2000.0]),
        "pair_observations": {},
    }
    c = cfg()
    c.update({"min_mutable_share": 0.0, "min_driver_geh": 1.0,
              "min_driver_abs_residual": 1.0, "max_solver_variables": 10})
    problem = core.prepare_guidance_problem(incidence, c)
    signed = [r for r in problem.objective_rows if r["kind"] == "SIGNED_DRIVER"]
    assert len(signed) == 2
    assert {math.copysign(1.0, float(r["target"])) for r in signed} == {-1.0, 1.0}


def test_signed_salary_bounds_follow_same_amdy_like_envelope():
    c = cfg()
    low, high, policy = mb._salary_coefficient_bounds(c, current=1.0)
    assert (low, high) == pytest.approx((0.5, 2.0))
    assert policy == "AMDY_LIKE_SALARY_ABSOLUTE_ENVELOPE"
