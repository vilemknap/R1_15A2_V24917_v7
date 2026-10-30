"""Explicit LONG P/A and shared LONG_COMPOSITE b/c activation: fail-closed seams.

No PTV COM necessary: all native evidence is read through read-only seams,
and the dynamic executable is asserted to be inside the LONG mask scope.
"""
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_demand_policy_v1 as dp
import r1_15a2_long_composite_td_v24917 as long_td
import r1_15a2_long_post_td_mask_v24917 as postmask
import r1_15a2_long_support_distance_v24917 as support
import r1_15a2_td_joint_runtime_v24917 as wire
import r1_15a2_trial_adapter_v24917 as adapter_mod
from r1_15a2_trial_adapter_v24916p2c_active import VisumAdapter as Parent


def _opts(**changes):
    return dict(dp.validate(dict(td_joint_enabled=True, td_inner_mode="DYNAMIC",
                                 long_composite_td_enabled=True,
                                 long_generation_enabled=True)), **changes)


def test_explicit_long_opt_in_and_native_dynamic_are_mandatory():
    opts = dp.validate(dict(td_joint_enabled=True, td_inner_mode="DYNAMIC",
                            long_composite_td_enabled=True,
                            long_generation_enabled=True))
    assert opts["long_composite_td_enabled"] and opts["long_generation_enabled"]
    for changes, code in [
        ({"td_joint_enabled": False}, "R1_LONG_TD_REQUIRES_TDJOINT1"),
        ({"td_inner_mode": "FROZEN_PATHS"}, "R1_LONG_TD_REQUIRES_DYNAMIC"),
        ({"td_policy": "OFF"}, "R1_LONG_TD_REQUIRES_TD_POLICY"),
    ]:
        with pytest.raises(RuntimeError, match=code):
            dp.validate(dict(opts, **changes))


def _long_readback(monkeypatch, **overrides):
    dist = np.array([[0., 110.], [120., 0.]], dtype=np.float64)
    arr = {no: np.zeros((2, 2), dtype=float)
           for no in (*long_td.MATRIX_NOS, 9291, 9292, 9293, 9294, 9295, 9305)}
    arr[9111][0, 1] = 9.
    arr[9291][0, 1] = 4.
    arr[9292][1, 0] = 2.
    arr[9305] = sum((arr[n] for n in (9291, 9292, 9293, 9294, 9295)),
                    np.zeros_like(dist))
    arr.update(overrides)
    epoch = NS(assignment_epoch=77, epoch_hash="sha256-current-77",
               family_distance={"LONG": dist})
    manager = NS(require_current=lambda: epoch)
    outer = NS(_long_post_td_mask_enabled=True, v24916_dynamic_skims=manager)
    bridge = NS(outer_adapter=outer, dynamic_skim_enabled=True, _v24917_frozen=False)
    monkeypatch.setattr(dp, "load_options", lambda *args, **kwargs: _opts())
    monkeypatch.setattr(support, "read_current", lambda outer: (dist, {
        "distance_basis": "FIXED_OSRM_DIST_KM_9697",
        "matrix_no": 9697, "values_sha256": "osrm-fixed",
    }))
    monkeypatch.setattr(postmask, "_read", lambda adapter, no: (None, arr[int(no)]))
    return outer, bridge, arr


def test_real_native_long_proof_reads_911x_929x_9305_and_epoch(monkeypatch):
    _, bridge, _ = _long_readback(monkeypatch)
    proof = long_td.require_live_ready([(long_td.GROUP, [])], bridge=bridge)
    assert proof["status"] == "READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE"
    assert proof["assignment_epoch"] == 77
    assert proof["vehicle_volume"] == pytest.approx(6.)
    assert proof["count_response_method"] == (
        "MEASURED_NATIVE_ASSIGNMENT_EVERY_TD_EVALUATION")
    assert proof["minimum_km"] == 80
    assert proof["finecdf_conditional_km"] == [100., 200.]
    assert proof["aggregate_target_count"] == 1


def test_caller_claims_without_live_readback_cannot_unlock(monkeypatch):
    _, bridge, _ = _long_readback(monkeypatch)
    with pytest.raises(RuntimeError, match="LONG_COUNT_RESPONSE_UNVERIFIED"):
        long_td.require_live_ready([(long_td.GROUP, [])])
    bridge.dynamic_skim_enabled = False
    with pytest.raises(RuntimeError, match="NATIVE_REALIZATION_UNAVAILABLE"):
        long_td.require_live_ready([(long_td.GROUP, [])], bridge=bridge)


def test_formula_aggregate_parity_and_80km_support_are_hard_proofs(monkeypatch):
    _, bridge, arr = _long_readback(monkeypatch)
    arr[9305][0, 1] += 1.
    with pytest.raises(RuntimeError, match="FINAL_9305_COMPONENT_PARITY_FAILED"):
        long_td.require_live_ready([(long_td.GROUP, [])], bridge=bridge)
    arr[9305][0, 1] -= 1.
    arr[9291][0, 0] = 1.
    with pytest.raises(Exception, match="LONGMASK_POST_ASSIGNMENT_SUPPORT_FAILED:9291"):
        long_td.require_live_ready([(long_td.GROUP, [])], bridge=bridge)


def test_frozen_path_mode_cannot_use_long_count_surrogate(monkeypatch):
    _, bridge, _ = _long_readback(monkeypatch)
    bridge._v24917_frozen = True
    with pytest.raises(RuntimeError, match="FROZEN_PATH_COUNT_RESPONSE_FORBIDDEN"):
        long_td.require_live_ready([(long_td.GROUP, [])], bridge=bridge)


def test_native_td_execution_owns_mask_and_preserves_scope(monkeypatch):
    monkeypatch.setattr(wire.joint, "options", lambda: {"long_enabled": True})
    outer = NS(_long_post_td_mask_enabled=True)
    calls = []
    def native(obj):
        calls.append(postmask._SCOPE.get() is outer)
        return "EXECUTED_NATIVE"
    runner = wire.wrap_dynamic_realization(native)
    assert runner(NS(outer_adapter=outer)) == "EXECUTED_NATIVE"
    assert calls == [True]
    assert postmask._SCOPE.get() is None


def test_native_td_fails_without_owned_long_mask(monkeypatch):
    monkeypatch.setattr(wire.joint, "options", lambda: {"long_enabled": True})
    calls = []
    runner = wire.wrap_dynamic_realization(lambda obj: calls.append(1))
    with pytest.raises(RuntimeError, match="DYNAMIC_MASK_CONTEXT_MISSING"):
        runner(NS(outer_adapter=NS(_long_post_td_mask_enabled=False)))
    assert not calls


def test_selected_td_plan_includes_one_atomic_long_composite(monkeypatch, tmp_path):
    monkeypatch.setattr(dp, "load_options", lambda *args, **kwargs: _opts())
    monkeypatch.setattr(Parent, "td_target_plan",
                        lambda self, diag, folder: {
                            "status": "ACTIVE", "active_components": ["WORK_E_C", "SERV_E_C"],
                            "global_11d_evaluation_required": True,
                        })
    instance = object.__new__(adapter_mod.VisumAdapter)
    plan = instance.td_target_plan({}, tmp_path)
    assert plan["active_components"] == ["WORK_E_C", "SERV_E_C", long_td.GROUP]
    assert plan["targeted_long_component_count"] == 1
    assert plan["global_11d_evaluation_required"] is True
    assert (tmp_path / "TD_ACTIVE_COMPONENT_MASK.json").is_file()


def test_global_fallback_keeps_long_in_group_pool(monkeypatch, tmp_path):
    monkeypatch.setattr(dp, "load_options", lambda *args, **kwargs: _opts())
    monkeypatch.setattr(Parent, "td_target_plan",
                        lambda self, diag, folder: {
                            "status": "GLOBAL_IDP_FALLBACK", "active_components": [],
                            "global_11d_evaluation_required": True})
    instance = object.__new__(adapter_mod.VisumAdapter)
    plan = instance.td_target_plan({}, tmp_path)
    assert plan["status"] == "GLOBAL_IDP_FALLBACK"
    assert plan["active_components"] == []
    assert "LONG_COMPOSITE" in plan["long_composite_policy"]


def test_td_joint_requires_measured_count_if_long_in_pool(monkeypatch):
    import r1_15a2_td_joint_v24917 as joint
    counts = NS(linear={"WORK": ([0], [0], [0], [1.])}, Q_ref=1.)
    blend = NS(ref=NS(TARGETS={long_td.GROUP: {"matrix_nos": list(long_td.MATRIX_NOS)}},
                      GROUPS=[long_td.GROUP]), model=counts, measured=False,
               opts={"w_cnt": .6, "w_idp": .4},
               stacked=lambda out, matrices: (np.array([0.]), 0., {}))
    with pytest.raises(RuntimeError, match="FROZEN_PATH_COUNT_RESPONSE_FORBIDDEN"):
        joint.score_blend(blend, {}, {})


def test_v24917_scopes_one_long_target_without_modifying_sealed_finecdf(monkeypatch):
    import r1_15a2_finecdf_bridge_v24916 as bridge
    import r1_15a2_active_controller_patch_v24916p2c as active
    from types import SimpleNamespace as NS
    monkeypatch.setattr(wire.joint, "options", lambda: {
        "enabled": True, "long_enabled": True, "inner_mode": "DYNAMIC",
        "outer_isolates": False, "max_isolates": 0})
    # Monkeypatch saves old module attributes for exact cleanup, because
    # install() modifies dispatch by design and full pytest runs other modules.
    for mod, name in ((bridge, "load_reference"),
                      (bridge, "run_finecdf_inner"),
                      (active, "targeted_run_finecdf_inner")):
        monkeypatch.setattr(mod, name, getattr(mod, name))
    controller = NS(run_finecdf_inner=lambda *a: None,
                    _realize_finecdf_td=lambda *a: None)
    wire.install(controller, print_fn=lambda *a: None)
    cfg = {"coupled_demand": {"finecdf_td": {
        "active_components": ["WORK_E_C", "LONG_COMPOSITE"]}}}
    effective, selected, token = wire._scope_long_target(cfg)
    try:
        assert effective["coupled_demand"]["finecdf_td"].get("active_components") is None
        assert cfg["coupled_demand"]["finecdf_td"]["active_components"] == list(selected)
        from test_v24917_long_composite_td import ROOT, FINE
        reference, _, _ = bridge.load_reference(ROOT, FINE)
        assert "LONG_COMPOSITE" in reference.GROUPS
        assert set(reference.GROUPS) == {"WORK_E_C", "LONG_COMPOSITE"}
        assert "LONG_COMPOSITE" in reference.TARGETS
        assert reference.long_composite_td_contract["aggregate_target_points"] == 512
        assert len(reference.TARGETS["LONG_COMPOSITE"]["matrix_nos"]) == 5
    finally:
        wire._LONG_TARGET_CONTEXT.reset(token)


def test_long_target_rejects_school_and_unsafe_modes(monkeypatch):
    monkeypatch.setattr(wire.joint, "options", lambda: {
        "enabled": True, "long_enabled": True, "inner_mode": "DYNAMIC"})
    for targets in (["SCHOOL", "LONG_COMPOSITE"], ["LONG_COMPOSITE", "LONG_COMPOSITE"]):
        with pytest.raises(RuntimeError, match="TARGET_COMPONENT_SET_INVALID"):
            wire._scope_long_target({"coupled_demand": {
                "finecdf_td": {"active_components": targets}}})
    assert wire._LONG_TARGET_CONTEXT.get() is None
    monkeypatch.setattr(wire.joint, "options", lambda: {
        "enabled": True, "long_enabled": True, "inner_mode": "FROZEN_PATHS"})
    with pytest.raises(RuntimeError, match="TARGET_REQUIRES_DYNAMIC"):
        wire._scope_long_target({"coupled_demand": {
            "finecdf_td": {"active_components": ["LONG_COMPOSITE"]}}})
