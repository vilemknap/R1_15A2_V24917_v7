from __future__ import annotations
import math
import pytest
import r1_15a2_multiblock as mb


def _cfg():
    return {
        "preserve_zero_add": True,
        "add_min": 0.0,
        "add_max": 3.0,
        "min_add_log_step": 1e-8,
        "explicit_excluded_zone_nos": [],
        "generation_bound_constrained_projection": {
            "enabled": True,
            "mode": "DIRECT_ACTUATOR_CAPACITY_CLIP_THEN_SAME_FAMILY_ROLE_ATTENUATION",
            "relative_balance_tolerance": 1e-10,
            "preserve_spatial_pattern": True,
            "outward_bound_policy": "CLIP_TO_EXACT_FEASIBLE_LOG_EFFECT",
            "role_balance_policy": "ATTENUATE_ONLY_LARGER_IMPLEMENTABLE_PA_SIDE",
            "opposite_sign_policy": "FAIL_CLOSED_UNCHANGED_GENERATION_GATE",
            "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
        },
        "zahr": {
            "domestic_mask_attr": "NOT_ZAHR",
            "domestic_threshold": 0.5,
            "neighbour_attr": "ZAHR_SUSED",
            "population_attr": "POP_ZP",
            "min": 0.0,
            "max": 10.0,
            "preserve_zero": True,
            "seed_floor": 0.0,
            "explicit_excluded_zone_nos": [],
        },
        # Disable salary in the unit contract so the test isolates the hard
        # ZAHR production bound and the P/A attenuation itself.
        "salary": {"enabled": False},
    }


def _zones():
    return [
        {
            "zone_no": 1, "NOT_ZAHR": 1, "ZAHR_SUSED": 0, "POP_ZP": 100,
            "ADD_PROD_W": 1.0, "ADD_ATT_W": 1.0, "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0,
            "ZAHR_PROD_WORK": 1.0, "ZAHR_ATR_WORK": 1.0,
            "ZAHR_PROD_SERV": 1.0, "ZAHR_ATR_SERV": 1.0,
        },
        {
            "zone_no": 2, "NOT_ZAHR": 1, "ZAHR_SUSED": 0, "POP_ZP": 100,
            "ADD_PROD_W": 1.0, "ADD_ATT_W": 1.0, "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0,
            "ZAHR_PROD_WORK": 1.0, "ZAHR_ATR_WORK": 1.0,
            "ZAHR_PROD_SERV": 1.0, "ZAHR_ATR_SERV": 1.0,
        },
        {
            "zone_no": 619, "NOT_ZAHR": 0, "ZAHR_SUSED": 1, "POP_ZP": 100,
            "ADD_PROD_W": 1.0, "ADD_ATT_W": 1.0, "ADD_PROD_S": 1.0, "ADD_ATT_S": 1.0,
            "ZAHR_PROD_WORK": 10.0, "ZAHR_ATR_WORK": 8.0,
            "ZAHR_PROD_SERV": 10.0, "ZAHR_ATR_SERV": 8.0,
        },
    ]


def test_v2486_saturated_zahr_production_is_capacity_clipped_and_pa_rebalanced():
    # Start from a balanced projection: domestic + saturated ZAHR production
    # together equal the single domestic attraction request.
    prod_dom = math.expm1(0.02) * 1000.0
    prod_zahr = math.expm1(0.08) * 1000.0
    att_step = math.log1p((prod_dom + prod_zahr) / 1000.0)
    projection = [
        {"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.02,
         "base_margin_volume": 1000.0, "guided_margin_delta": prod_dom, "projected_margin_delta": prod_dom},
        {"zone_no": 619, "family": "WORK", "role": "PROD", "log_step": 0.08,
         "base_margin_volume": 1000.0, "guided_margin_delta": prod_zahr, "projected_margin_delta": prod_zahr},
        {"zone_no": 2, "family": "WORK", "role": "ATT", "log_step": att_step,
         "base_margin_volume": 1000.0, "guided_margin_delta": prod_dom + prod_zahr,
         "projected_margin_delta": prod_dom + prod_zahr},
    ]
    d = mb.design_generation_candidates(projection, _zones(), _cfg(), 1.0)
    audit = d["summary"]["bound_constrained_projection"]
    assert audit["enabled"] is True
    assert audit["clipped_count"] == 1
    assert audit["role_rebalance"]["WORK"]["status"] == "BALANCED_BY_ROLE_ATTENUATION"
    assert audit["role_rebalance"]["WORK"]["scaled_role"] == "ATT"
    assert 0.0 < audit["role_rebalance"]["WORK"]["scale"] < 1.0
    # The saturated ZAHR production actuator must never be written above 10.
    assert not any(r["zone_no"] == 619 and r["attr"] == "ZAHR_PROD_WORK" for r in d["candidate_rows"])
    assert any(r.get("reason") == "BOUND_SATURATED_CONSTRAINED_PROJECTION" for r in d["skipped_rows"])
    work = d["summary"]["estimated_pa_delta_by_family"]["WORK"]
    rel = work["estimated_abs_gap"] / max(1.0, abs(work["estimated_prod_delta"]), abs(work["estimated_att_delta"]))
    assert rel < 1e-9
    assert d["summary"]["max_abs_effect_log_error"] < 1e-9


def test_v2486_unconstrained_generation_matches_legacy_when_no_bound_is_hit():
    c = _cfg()
    projection = [
        {"zone_no": 1, "family": "WORK", "role": "PROD", "log_step": 0.02, "base_margin_volume": 1000.0},
        {"zone_no": 2, "family": "WORK", "role": "ATT", "log_step": math.log1p(math.expm1(0.02)), "base_margin_volume": 1000.0},
    ]
    d = mb.design_generation_candidates(projection, _zones(), c, 1.0)
    audit = d["summary"]["bound_constrained_projection"]
    assert audit["clipped_count"] == 0
    assert audit["role_rebalance"]["WORK"]["status"] == "ALREADY_BALANCED"
    assert len(d["candidate_rows"]) == 2
    assert d["summary"]["max_abs_effect_log_error"] < 1e-9


def test_v2486_preserved_zero_direct_actuator_is_removed_before_pa_balance():
    c = _cfg()
    zones = _zones()
    # A preserved zero production actuator has no implementable multiplicative
    # effect. The opposite attraction side must be attenuated to zero before the
    # live trial, rather than creating a deterministic P/A gap after mapping.
    zones[0]["ADD_PROD_S"] = 0.0
    projection = [
        {"zone_no": 1, "family": "SERVICE", "role": "PROD", "log_step": 0.04,
         "base_margin_volume": 1000.0},
        {"zone_no": 2, "family": "SERVICE", "role": "ATT", "log_step": 0.04,
         "base_margin_volume": 1000.0},
    ]
    d = mb.design_generation_candidates(projection, zones, c, 1.0)
    audit = d["summary"]["bound_constrained_projection"]
    assert audit["clipped_count"] == 1
    assert audit["role_rebalance"]["SERVICE"]["status"] == "BALANCED_BY_ROLE_ATTENUATION"
    assert audit["role_rebalance"]["SERVICE"]["scale"] == pytest.approx(0.0)
    assert not d["candidate_rows"]
    assert any(r.get("reason") == "PRESERVED_ZERO_CONSTRAINED_PROJECTION"
               for r in d["skipped_rows"])
    service = d["summary"]["estimated_pa_delta_by_family"].get("SERVICE", {})
    assert abs(service.get("estimated_prod_delta", 0.0)) < 1e-12
    assert abs(service.get("estimated_att_delta", 0.0)) < 1e-12


def test_v2486_real_failure_shape_balances_work_and_service_saturation():
    c = _cfg()
    zones = _zones()
    # Shape and magnitudes taken from the V2484 live failure evidence. The two
    # ZAHR production actuators are already at 10.0 and must not be written.
    projection = [
        {"zone_no": 1, "family": "WORK", "role": "PROD",
         "log_step": math.log1p(1674.0538619109655 / 100000.0),
         "base_margin_volume": 100000.0},
        {"zone_no": 619, "family": "WORK", "role": "PROD",
         "log_step": 0.07596206623275155, "base_margin_volume": 4569.390251114766},
        {"zone_no": 2, "family": "WORK", "role": "ATT",
         "log_step": math.log1p(2034.6776609155581 / 100000.0),
         "base_margin_volume": 100000.0},
        {"zone_no": 1, "family": "SERVICE", "role": "PROD",
         "log_step": math.log1p(3691.184919452171 / 100000.0),
         "base_margin_volume": 100000.0},
        {"zone_no": 619, "family": "SERVICE", "role": "PROD",
         "log_step": 0.038636728182244603, "base_margin_volume": 2810.1727117179607},
        {"zone_no": 2, "family": "SERVICE", "role": "ATT",
         "log_step": math.log1p(3801.866971595385 / 100000.0),
         "base_margin_volume": 100000.0},
    ]
    d = mb.design_generation_candidates(projection, zones, c, 1.0)
    audit = d["summary"]["bound_constrained_projection"]
    assert audit["clipped_count"] == 2
    assert audit["unresolved_families"] == []
    for family in ("WORK", "SERVICE"):
        rec = audit["role_rebalance"][family]
        assert rec["status"] == "BALANCED_BY_ROLE_ATTENUATION"
        assert rec["relative_gap_after"] < 1e-9
    assert not any(r.get("zone_no") == 619 and r.get("attr") in
                   {"ZAHR_PROD_WORK", "ZAHR_PROD_SERV"}
                   for r in d["candidate_rows"])
