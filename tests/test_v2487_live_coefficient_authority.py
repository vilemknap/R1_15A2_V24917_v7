from __future__ import annotations

import math
from pathlib import Path

import pytest

import r1_15a2_multiblock as mb


def _policy():
    return {
        "enabled": True,
        "mode": "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP_THEN_DOMAIN_ONLY_PA_REBALANCE",
        "relative_balance_tolerance": 1e-10,
        "preserve_spatial_pattern": True,
        "outward_bound_policy": "NO_GLOBAL_ABSOLUTE_MAX_CURRENT_VALUE_PLUS_RELATIVE_LOG_STEP",
        "role_balance_policy": "ATTENUATE_ONLY_LARGER_IMPLEMENTABLE_PA_SIDE",
        "opposite_sign_policy": "FAIL_CLOSED_UNCHANGED_GENERATION_GATE",
        "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
        "legacy_absolute_upper_bounds_enforced": False,
        "current_live_values_are_authority": True,
    }


def _cfg(salary=False):
    return {
        "preserve_zero_add": True,
        "add_min": 0.0,
        "add_max": None,
        "min_add_log_step": 1e-8,
        "explicit_excluded_zone_nos": [],
        "generation_coefficient_authority": {
            "enabled": True,
            "mode": "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP",
            "multiplicative_minimum": 0.0,
            "legacy_absolute_bounds_role": "DISABLED_NOT_ENFORCED",
        },
        "generation_bound_constrained_projection": _policy(),
        "zahr": {
            "domestic_mask_attr": "NOT_ZAHR",
            "domestic_threshold": 0.5,
            "neighbour_attr": "ZAHR_SUSED",
            "population_attr": "POP_ZP",
            "min": 0.0,
            "max": None,
            "preserve_zero": True,
            "seed_floor": 0.0,
            "explicit_excluded_zone_nos": [],
        },
        "salary": {
            "enabled": salary,
            "income_attr": "AV_INCOME",
            "salary_attr": "ADD_SALARY",
            "work_attraction_attr": "ADD_ATT_W",
            "formula_offset": 1000.0,
            "formula_denominator": 2700.0,
            "factor_floor": 0.05,
            "salary_min": None,
            "salary_max": None,
            "max_abs_delta_per_block": 0.08,
            "min_eligible_zones": 2,
            "zone_add_ridge_lambda": 1.0,
            "basis_ridge_lambda": 0.01,
            "include_intercept": False,
        },
    }


def _zone(no, domestic=True, **updates):
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
        "ZAHR_PROD_WORK": 1.0,
        "ZAHR_ATR_WORK": 1.0,
        "ZAHR_PROD_SERV": 1.0,
        "ZAHR_ATR_SERV": 1.0,
    }
    row.update(updates)
    return row


def test_v2487_zahr_above_ten_is_live_authority_and_can_increase():
    zones = [
        _zone(1, True),
        _zone(2, True),
        _zone(619, False, ZAHR_PROD_WORK=12.5, ZAHR_ATR_WORK=11.0),
    ]
    dom = math.expm1(0.02) * 1000.0
    border = math.expm1(0.08) * 1000.0
    att_step = math.log1p((dom + border) / 1000.0)
    projection = [
        {"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.02,
         "base_margin_volume": 1000.0, "guided_margin_delta": dom,
         "projected_margin_delta": dom},
        {"zone_no": 619, "family": "WORK", "role": "PROD", "log_step": 0.08,
         "base_margin_volume": 1000.0, "guided_margin_delta": border,
         "projected_margin_delta": border},
        {"zone_no": 2, "family": "WORK", "role": "ATT", "log_step": att_step,
         "base_margin_volume": 1000.0, "guided_margin_delta": dom + border,
         "projected_margin_delta": dom + border},
    ]
    design = mb.design_generation_candidates(projection, zones, _cfg(False), 1.0)
    row = next(r for r in design["candidate_rows"]
               if r["zone_no"] == 619 and r["attr"] == "ZAHR_PROD_WORK")
    assert row["current"] == pytest.approx(12.5)
    assert row["proposed"] == pytest.approx(12.5 * math.exp(0.08))
    assert row["proposed"] > 10.0
    assert row["coefficient_authority"] == "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP"
    audit = design["summary"]["bound_constrained_projection"]
    assert audit["clipped_count"] == 0
    assert audit["legacy_absolute_upper_bounds_enforced"] is False
    assert design["summary"]["generation_coefficient_authority"]["current_live_values_are_authority"] is True
    work = design["summary"]["estimated_pa_delta_by_family"]["WORK"]
    rel = work["estimated_abs_gap"] / max(
        1.0, abs(work["estimated_prod_delta"]), abs(work["estimated_att_delta"]))
    assert rel < 1e-9
    assert design["summary"]["max_abs_effect_log_error"] < 1e-9


def test_v2487_domestic_add_above_legacy_three_is_not_clamped():
    zones = [_zone(1, True, ADD_PROD_W=4.5), _zone(2, True, ADD_ATT_W=5.0)]
    delta = math.expm1(0.04) * 1000.0
    projection = [
        {"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.04,
         "base_margin_volume": 1000.0, "guided_margin_delta": delta,
         "projected_margin_delta": delta},
        {"zone_no": 2, "family": "WORK", "role": "ATT", "log_step": 0.04,
         "base_margin_volume": 1000.0, "guided_margin_delta": delta,
         "projected_margin_delta": delta},
    ]
    design = mb.design_generation_candidates(projection, zones, _cfg(False), 1.0)
    prod = next(r for r in design["candidate_rows"] if r["attr"] == "ADD_PROD_W")
    att = next(r for r in design["candidate_rows"] if r["attr"] == "ADD_ATT_W")
    assert prod["proposed"] == pytest.approx(4.5 * math.exp(0.04))
    assert att["proposed"] == pytest.approx(5.0 * math.exp(0.04))
    assert prod["proposed"] > 3.0 and att["proposed"] > 3.0


def test_v2487_salary_above_legacy_three_uses_live_value_not_clamp():
    zones = [
        _zone(1, True, AV_INCOME=1000.0, ADD_SALARY=5.0),
        _zone(2, True, AV_INCOME=3000.0, ADD_SALARY=5.5),
        _zone(3, True),
        _zone(4, True),
    ]
    # Different attraction requests correlated with income create a non-zero
    # salary basis coefficient. Production rows keep the family P/A balanced.
    step1, step2 = 0.015, 0.045
    d1, d2 = math.expm1(step1) * 1000.0, math.expm1(step2) * 1000.0
    total = d1 + d2
    pstep = math.log1p(total / 2000.0)
    projection = [
        {"zone_no": 3, "family": "WORK", "role": "PROD", "log_step": pstep,
         "base_margin_volume": 1000.0, "guided_margin_delta": total / 2,
         "projected_margin_delta": total / 2},
        {"zone_no": 4, "family": "WORK", "role": "PROD", "log_step": pstep,
         "base_margin_volume": 1000.0, "guided_margin_delta": total / 2,
         "projected_margin_delta": total / 2},
        {"zone_no": 1, "family": "WORK", "role": "ATT", "log_step": step1,
         "base_margin_volume": 1000.0, "guided_margin_delta": d1,
         "projected_margin_delta": d1},
        {"zone_no": 2, "family": "WORK", "role": "ATT", "log_step": step2,
         "base_margin_volume": 1000.0, "guided_margin_delta": d2,
         "projected_margin_delta": d2},
    ]
    design = mb.design_generation_candidates(projection, zones, _cfg(True), 1.0)
    salary_rows = [r for r in design["candidate_rows"] if r["attr"] == "ADD_SALARY"]
    assert salary_rows, design["summary"]["salary"]
    assert all(r["current"] > 3.0 for r in salary_rows)
    assert all(r["proposed"] > 3.0 for r in salary_rows)
    assert design["summary"]["salary"]["coefficient_authority"] == \
        "LIVE_CURRENT_VALUE_PLUS_BOUNDED_DELTA"


def test_v2487_legacy_config_still_reproduces_historical_clamp():
    cfg = _cfg(False)
    cfg.pop("generation_coefficient_authority")
    cfg["add_max"] = 3.0
    cfg["zahr"]["max"] = 10.0
    cfg["generation_bound_constrained_projection"] = {
        **_policy(),
        "mode": "DIRECT_ACTUATOR_CAPACITY_CLIP_THEN_SAME_FAMILY_ROLE_ATTENUATION",
        "outward_bound_policy": "CLIP_TO_EXACT_FEASIBLE_LOG_EFFECT",
    }
    zones = [_zone(1, False, ZAHR_PROD_WORK=10.0), _zone(2, True)]
    delta = math.expm1(0.04) * 1000.0
    projection = [
        {"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.04,
         "base_margin_volume": 1000.0, "guided_margin_delta": delta,
         "projected_margin_delta": delta},
        {"zone_no": 2, "family": "WORK", "role": "ATT", "log_step": 0.04,
         "base_margin_volume": 1000.0, "guided_margin_delta": delta,
         "projected_margin_delta": delta},
    ]
    design = mb.design_generation_candidates(projection, zones, cfg, 1.0)
    assert not any(r.get("attr") == "ZAHR_PROD_WORK" for r in design["candidate_rows"])
    assert design["summary"]["bound_constrained_projection"]["clipped_count"] == 1
