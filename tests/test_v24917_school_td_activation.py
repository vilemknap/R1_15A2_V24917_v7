"""SCHOOL IDP 512-point native b/c calibration alongside LONG and W/S.

The sealed V24916 bridge and V1.9 reference must never be modified.
No production/attraction or native OD matrices are edited by this suite.
"""
import copy
import math
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_demand_policy_v1 as dp
import r1_15a2_school_td_v24917 as school
import r1_15a2_td_joint_runtime_v24917 as wire
import r1_15a2_trial_adapter_v24917 as adapter_module
from r1_15a2_trial_adapter_v24916p2c_active import VisumAdapter as Parent

from test_v24917_long_composite_td import ROOT, FINE


@pytest.fixture
def ref():
    import r1_15a2_finecdf_bridge_v24916 as bridge
    return bridge.load_reference(ROOT, FINE)[0]


def test_school_source_exact_512_direct_idp_unmodified(ref):
    original = copy.deepcopy(ref.FINE_AUTHORITY)
    proof = school.reference_contract(ref)
    assert proof["matrix_no"] == 9117
    assert proof["dstrat_code"] == "5_SCHOOL"
    assert proof["target_points"] == 512
    assert proof["school_purpose"] == "DIRECT_PURPOSE"
    assert proof["school_generation_policy"] == "FIXED_ORIGINAL_AMDY_FORMULAS"
    assert proof["parameter_a_frozen"] is True
    assert proof["optimized_parameters"] == ["b", "c"]
    assert ref.FINE_AUTHORITY == original


def test_school_two_native_gravity_coordinates_do_not_mutate_generation(ref):
    abc = {n: {"a": 0.8 + n / 100000., "b": 1.1, "c": -0.15}
           for n in ref.BY_NO}
    space = ref.ParameterSpace(abc)
    trial = {k: v.copy() for k, v in space.x.items()}
    trial["SCHOOL"] += np.array([0.08, math.log(1.06)])
    changed = space.abc(trial)
    for n in abc:
        assert changed[n]["a"] == abc[n]["a"]
        if n == school.MATRIX_NO:
            assert changed[n]["b"] == pytest.approx(abc[n]["b"] + 0.08)
            assert changed[n]["c"] == pytest.approx(abc[n]["c"] * 1.06)
        else:
            assert changed[n] == pytest.approx(abc[n])
    assert set(school.reference_contract(ref)["optimized_parameters"]) == {"b", "c"}


@pytest.mark.parametrize("bad", ["missing_matrix", "dstrat", "grid", "cdf", "purpose"])
def test_wrong_school_source_never_unlocked(ref, bad):
    if bad == "missing_matrix":
        ref.TARGETS["SCHOOL"]["matrix_nos"] = [9118]
    elif bad == "dstrat":
        ref.BY_NO[9117]["dstrat_code"] = "ANOTHER"
    elif bad == "grid":
        ref.FINE_AUTHORITY["common_grid_atomic_km"][0] = -0.1
    elif bad == "cdf":
        ref.FINE_AUTHORITY["targets"]["SCHOOL"]["cdf"][47] = float("nan")
    elif bad == "purpose":
        ref.FINE_AUTHORITY["targets"]["SCHOOL"]["source"] = "MIXTURE"
    with pytest.raises(RuntimeError, match="TDSCHOOL_"):
        school.reference_contract(ref)


def _options(**changed):
    return dp.validate(dict(td_joint_enabled=True,
                            long_generation_enabled=True,
                            long_composite_td_enabled=True,
                            school_td_enabled=True,
                            td_inner_mode="DYNAMIC",
                            **changed))


def test_school_td_requires_joint_mode_and_non_disabled_policy():
    assert _options()["school_td_enabled"]
    with pytest.raises(RuntimeError, match="R1_SCHOOL_TD_REQUIRES_TDJOINT1"):
        dp.validate(dict(school_td_enabled=True, td_joint_enabled=False))
    with pytest.raises(RuntimeError, match="R1_SCHOOL_TD_REQUIRES_TD_POLICY"):
        dp.validate(dict(school_td_enabled=True, td_joint_enabled=True,
                         td_policy="OFF"))
    assert dp.validate({"school_td_enabled": False})["school_td_enabled"] is False


def test_targeted_ws_school_long_are_five_unique_groups(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter_module.long_opts, "load_options", lambda: _options())
    monkeypatch.setattr(Parent, "td_target_plan",
                        lambda self, diag, folder: {
                            "status": "ACTIVE",
                            "active_components": ["WORK_E_C", "SERV_E_C"]})
    instance = object.__new__(adapter_module.VisumAdapter)
    result = instance.td_target_plan({}, tmp_path)
    assert result["active_components"] == [
        "WORK_E_C", "SERV_E_C", "SCHOOL", "LONG_COMPOSITE"]
    assert result["school_td_target_count"] == 1
    assert result["targeted_long_component_count"] == 1
    assert (tmp_path / "TD_ACTIVE_COMPONENT_MASK.json").is_file()


def test_school_only_targeting_does_not_require_long(monkeypatch, tmp_path):
    opts = dict(_options(), long_composite_td_enabled=False)
    monkeypatch.setattr(adapter_module.long_opts, "load_options", lambda: opts)
    monkeypatch.setattr(Parent, "td_target_plan",
                        lambda self, diag, folder: {
                            "status": "ACTIVE", "active_components": ["WORK_stud"]})
    inst = object.__new__(adapter_module.VisumAdapter)
    p = inst.td_target_plan({}, tmp_path)
    assert p["active_components"] == ["WORK_stud", "SCHOOL"]
    assert "long_composite_policy" not in p


def test_global_fallback_has_school_policy_without_fake_mask(monkeypatch, tmp_path):
    monkeypatch.setattr(adapter_module.long_opts, "load_options", lambda: _options())
    monkeypatch.setattr(Parent, "td_target_plan",
                        lambda self, diag, folder: {
                            "status": "GLOBAL_IDP_FALLBACK", "active_components": []})
    inst = object.__new__(adapter_module.VisumAdapter)
    p = inst.td_target_plan({}, tmp_path)
    assert p["active_components"] == []
    assert "SCHOOL_9117" in p["school_td_policy"]
    assert "LONG_COMPOSITE" in p["long_composite_policy"]


def test_scope_rejects_unverified_school_and_duplicate(monkeypatch):
    monkeypatch.setattr(wire.joint, "options", lambda: {
        "enabled": True, "school_enabled": False, "long_enabled": True,
        "inner_mode": "DYNAMIC"})
    config = {"coupled_demand": {"finecdf_td": {
        "active_components": ["SCHOOL"]}}}
    with pytest.raises(RuntimeError, match="TDSCHOOL_TARGET_REQUEST_NOT_ENABLED"):
        wire._scope_long_target(config)
    monkeypatch.setattr(wire.joint, "options", lambda: {
        "enabled": True, "school_enabled": True, "long_enabled": True,
        "inner_mode": "DYNAMIC"})
    config["coupled_demand"]["finecdf_td"]["active_components"] = ["SCHOOL", "SCHOOL"]
    with pytest.raises(RuntimeError, match="TARGET_COMPONENT_SET_INVALID"):
        wire._scope_long_target(config)
    assert wire._LONG_TARGET_CONTEXT.get() is None


def test_school_target_context_source_reference_and_filtered_groups(monkeypatch):
    import r1_15a2_finecdf_bridge_v24916 as bridge
    import r1_15a2_active_controller_patch_v24916p2c as active
    monkeypatch.setattr(wire.joint, "options", lambda: {
        "enabled": True, "school_enabled": True, "long_enabled": True,
        "inner_mode": "DYNAMIC", "outer_isolates": False, "max_isolates": 0})
    for mod, name in ((bridge, "load_reference"),
                      (bridge, "run_finecdf_inner"),
                      (active, "targeted_run_finecdf_inner")):
        monkeypatch.setattr(mod, name, getattr(mod, name))
    ctrl = NS(run_finecdf_inner=lambda *a: None, _realize_finecdf_td=lambda *a: None)
    wire.install(ctrl, print_fn=lambda *a: None)
    cfg = {"coupled_demand": {"finecdf_td": {
        "active_components": ["WORK_stud", "SCHOOL", "LONG_COMPOSITE"]}}}
    scoped, selected, token = wire._scope_long_target(cfg)
    try:
        assert selected == tuple(cfg["coupled_demand"]["finecdf_td"]["active_components"])
        assert "active_components" not in scoped["coupled_demand"]["finecdf_td"]
        reference, path, sha = bridge.load_reference(ROOT, FINE)
        assert set(reference.GROUPS) == {"WORK_stud", "SCHOOL", "LONG_COMPOSITE"}
        assert reference.school_td_reference_contract["matrix_no"] == 9117
        assert reference.school_td_reference_contract["target_points"] == 512
        assert reference.FINE_AUTHORITY["targets"]["SCHOOL"]["source"] == "DIRECT_PURPOSE"
    finally:
        wire._LONG_TARGET_CONTEXT.reset(token)


def test_school_disabled_global_loader_never_silently_optimizes_school(monkeypatch):
    import r1_15a2_finecdf_bridge_v24916 as bridge
    import r1_15a2_active_controller_patch_v24916p2c as active
    monkeypatch.setattr(wire.joint, "options", lambda: {
        "enabled": True, "school_enabled": False, "long_enabled": True,
        "inner_mode": "DYNAMIC", "outer_isolates": False, "max_isolates": 0})
    for mod, name in ((bridge, "load_reference"),
                      (bridge, "run_finecdf_inner"),
                      (active, "targeted_run_finecdf_inner")):
        monkeypatch.setattr(mod, name, getattr(mod, name))
    ctrl = NS(run_finecdf_inner=lambda *a: None, _realize_finecdf_td=lambda *a: None)
    wire.install(ctrl, print_fn=lambda *a: None)
    ref, _, _ = bridge.load_reference(ROOT, FINE)
    assert "SCHOOL" not in ref.GROUPS
    assert ref.school_td_reference_contract is None
    assert "LONG_COMPOSITE" in ref.GROUPS
