from __future__ import annotations
import copy

import r1_15a2_fresh0_shortroot_parent_v24916 as parent
import r1_15a2_active_targeting_runtime_v24916_fresh0isolated as base
import r1_15a2_fastcal_runtime_v24916p2c as fast


def _configs():
    p = parent.load_config("FULL")
    b = base.apply_active_runtime_delta(p)
    c = fast.apply_active_runtime_delta(p)
    return p, b, c


def test_fastcal1_exact_requested_policy_and_validation():
    p, b, c = _configs()
    audit = fast.validate_active_runtime_delta(c, p)
    assert audit["passes"] is True

    stages = c["performance"]["generation_step_schedule"]
    assert [s["name"] for s in stages] == ["SIGNED_EXPLORE", "SIGNED_REFINE", "DISTRIBUTION_FOCUS"]
    assert [s["signed_max_family_global_log_up"] for s in stages] == [0.10, 0.06, 0.03]
    assert [s["signed_max_family_global_log_down"] for s in stages] == [0.10, 0.06, 0.03]
    assert [s["max_add_log_up"] for s in stages] == [0.10, 0.06, 0.03]
    assert [s["max_add_log_down"] for s in stages] == [0.10, 0.06, 0.03]
    assert [s["max_od_relative_up"] for s in stages] == [0.20, 0.14, 0.08]
    assert [s["max_od_relative_down"] for s in stages] == [0.20, 0.14, 0.08]

    assert c["backtracking_scales"] == [1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125]
    assert c["trial_calibration"]["max_trials_per_block"]["GENERATION"] == 6
    assert c["min_cal_objective_relative_improvement"] == 1.0e-5
    assert c["td"]["min_selected_component_relative_improvement"] == 5.0e-4
    assert c["td_soft_reference_policy"]["aggregate_selected_min_relative_improvement"] == 5.0e-4
    assert c["coupled_demand"]["finecdf_td"]["realization_backtracking_scales"] == [
        1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125, 0.015625]


def test_fastcal1_keeps_early_exploration_and_scientific_authorities_unchanged():
    p, b, c = _configs()
    assert c["early_exploration_acceptance"] == b["early_exploration_acceptance"]
    assert c["v24916_flowbundle_skim_runtime"] == b["v24916_flowbundle_skim_runtime"]
    assert c["demand_evidence_targeting"] == b["demand_evidence_targeting"]
    assert c["require_active_assignment"] == b["require_active_assignment"]
    assert c["path_epoch_method"] == b["path_epoch_method"]
    assert c["require_path_parity_for_apply"] == b["require_path_parity_for_apply"]
    assert c["coupled_demand"]["finecdf_td"]["ipf_tolerance_policy"] == b["coupled_demand"]["finecdf_td"]["ipf_tolerance_policy"]
    assert c["coupled_demand"]["finecdf_td"]["inner_min_relative_objective_improvement"] == b["coupled_demand"]["finecdf_td"]["inner_min_relative_objective_improvement"]


def test_fastcal1_delta_is_fail_closed_on_unreviewed_change():
    p, b, c = _configs()
    bad = copy.deepcopy(c)
    bad["idp_max_mean_degradation"] = 999.0
    try:
        fast.validate_active_runtime_delta(bad, p)
    except RuntimeError as exc:
        assert "V24916_FASTCAL1" in str(exc)
    else:
        raise AssertionError("FASTCAL1 validator accepted an unreviewed hard-guard change")
