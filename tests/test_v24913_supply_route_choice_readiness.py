from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

import r1_15a2_core as core
from r1_15a2_supply import SupplyPolicy, SupplyContractError, check_addval_change
from r1_15a2_sequence_v23 import propose_sequence_supply
from r1_15a2_supply_handoff_v24913 import discover_demand_convergence_authority
from test_sequence_v23 import fixture, links

ROOT = Path(__file__).resolve().parents[1]


def _cfg(cycle=1):
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_13.json").read_text(encoding="utf-8"))
    cfg["runtime_acceptance_supply_cycle"] = cycle
    cfg["runtime_acceptance_scope"] = "SUPPLY_ADDVAL1"
    return cfg


def _model_for_geh(observed: float, target_geh: float) -> float:
    o = float(observed); g = float(target_geh)
    d = (g * g + math.sqrt(g ** 4 + 16.0 * g * g * o)) / 4.0
    return o + d


def _row(code, geh_value, observed=1000.0):
    return {"role": "CALIBRATION", "countlocation_no": code,
            "observed": observed, "model": _model_for_geh(observed, geh_value),
            "profile_weight": 1.0}


def test_v24913_relaxed_supply_limits_are_active():
    cfg = _cfg()
    p = SupplyPolicy.from_config(cfg)
    assert p.lattice == 0.5
    assert p.max_step == 8.0
    assert p.max_cumulative == 15.0
    assert (p.absolute_min, p.absolute_max) == (-100.0, 100.0)
    assert p.max_bundle_equivalent_seconds == 360.0
    assert p.max_edges == 30
    assert p.max_candidates == 40
    assert p.max_driver_profiles == 80
    assert p.min_geh == 5.0
    assert p.min_residual == 100.0
    assert p.min_attribution_coverage == 0.90
    assert p.min_path_coverage == 0.90
    assert p.min_path_volume_coverage == 0.95


def test_half_addval_lattice_supports_five_second_final_step():
    p = SupplyPolicy.from_config(_cfg())
    link = {"eligible": True, "t0_c_seconds": 100.0}
    got = check_addval_change((1, 1, 2), 0.0, 0.5, 0.0, link, p)
    assert got["equivalent_seconds"] == 5.0
    with pytest.raises(SupplyContractError, match="BASELINE_RELATIVE_INTEGER_LATTICE"):
        check_addval_change((1, 1, 2), 0.0, 0.25, 0.0, link, p)


def test_supply_policy_has_its_own_cycle_clock_and_horizon():
    p = core.early_exploration_policy(_cfg(77), "SUPPLY_ADDVAL1")
    assert p is not None
    assert p["scope"] == "SUPPLY"
    assert p["supply_cycle"] == 77
    assert p["through_supply_cycle"] == 100
    assert core.early_exploration_policy(_cfg(101), "SUPPLY_ADDVAL1") is None


def test_supply_accepts_any_real_positive_weighted_geh_improvement_with_rebased_severity():
    cfg = _cfg(1)
    before = [_row("DRIVER", 60.0), _row("EDGE", 39.9)]
    after = [_row("DRIVER", 56.0), _row("EDGE", 41.0)]
    decision = core.acceptance_decision(before, after, {}, {}, cfg, "SUPPLY_ADDVAL1")
    assert decision["accepted"] is True
    assert decision["acceptance_path"] == "SUPPLY_ROUTE_CHOICE_ANY_POSITIVE_WEIGHTED_GEH"
    assert decision["active_acceptance_stage"] == "SUPPLY_ROUTE_CHOICE_EXPLORATION"
    assert decision["severity_transition_guard"]["passes"] is True
    assert decision["idp_mean_degradation_limit"] == 0.02
    assert decision["idp_component_degradation_limit"] == 0.08


def test_supply_still_rejects_no_cal_improvement():
    cfg = _cfg(1)
    decision = core.acceptance_decision([_row("A", 20.0)], [_row("A", 20.1)], {}, {}, cfg,
                                        "SUPPLY_ADDVAL1")
    assert decision["accepted"] is False
    assert "CAL_GEH_OBJECTIVE_NOT_IMPROVED" in decision["reasons"]


def test_supply_severity_budget_is_wider_but_not_unbounded():
    cfg = _cfg(1)
    before = [_row(f"A{i}", 50.0) for i in range(100)]
    moderate = [_row(f"A{i}", 52.2) for i in range(100)]
    severe = [_row(f"A{i}", 65.0) for i in range(100)]
    g1 = core.severity_transition_guard(before, moderate, cfg, "SUPPLY_ADDVAL1")
    g2 = core.severity_transition_guard(before, severe, cfg, "SUPPLY_ADDVAL1")
    assert g1["passes"] is True
    assert g2["passes"] is False


def test_sequence_candidates_publish_complete_branch_local_backtracking_ladders():
    policy = replace(SupplyPolicy.from_config(_cfg()), min_geh=1.0, min_residual=1.0)
    c = fixture(policy=policy)
    try:
        design = propose_sequence_supply(
            c, links(), {k: 0.0 for k in links()}, policy,
            sequence_caps=(12, 8, 4, 2, 1), step_units=(16, 8, 4, 2, 1))
        assert design["backtracking_order"] == "BRANCH_LOCAL_DESCENDING_STEP"
        assert design["complete_backtracking_groups"]
        groups = design["complete_backtracking_groups"]
        assert any(g["step_units"] == [16, 8, 4, 2, 1] for g in groups)
        # Every published group is contiguous in the candidate list and follows
        # its complete admissible descending ladder.  An 80-second step may be
        # absent only when the minimum-cost guard makes that amplitude illegal.
        offset = 0
        for group in groups:
            rows = design["candidates"][offset:offset + len(group["step_units"])]
            assert {x["backtracking_group_id"] for x in rows} == {group["group_id"]}
            assert [x["step_units"] for x in rows] == group["step_units"]
            assert group["step_units"] == sorted(group["step_units"], reverse=True)
            offset += len(rows)
    finally:
        c.close()


def test_demand_convergence_authority_discovery_is_stateful_and_fail_closed(tmp_path):
    source = tmp_path / "R1_15A2_V24912_RUNS" / "RUN_X" / "CALIBRATION" / "CHECKPOINTS" / "A.ver"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    authority_path = source.parent.parent / "DEMAND_CONVERGED.json"
    authority_path.write_text(json.dumps({
        "cycle": 8,
        "state_hash": "a" * 64,
        "diagnostic_hash": "b" * 64,
        "stationary_cycle_streak": 2,
        "criterion": "CONSECUTIVE_COMPLETE_SUCCESSFUL_CONFIGURED_TG_TD_SEARCHES_WITH_NO_CHANGE",
    }), encoding="utf-8")
    found = discover_demand_convergence_authority(source)
    assert found["path"] == str(authority_path)
    authority_path.write_text("{}", encoding="utf-8")
    with pytest.raises(SupplyContractError, match="REQUIRES_VALID_DEMAND_CONVERGENCE_AUTHORITY"):
        discover_demand_convergence_authority(source)
