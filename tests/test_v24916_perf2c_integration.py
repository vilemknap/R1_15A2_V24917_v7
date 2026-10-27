from __future__ import annotations

import gc
import json
from pathlib import Path

import pytest

from r1_15a2_flowbundle_v24916p2c import (
    FlowBundleEvidenceIdentity,
    FlowBundleMatrixReducer,
    reduce_both_directions,
    reduce_directed,
    assert_reduced_parity,
    ordered_zone_hash,
)
from r1_15a2_skim_v24916p2c import seal_dist_km, require_same_skim_identity, shortest_imp_oracle_enabled
from r1_15a2_demand_evidence_v24916p2c import BoundedDemandEvidenceManager
from r1_15a2_demand_targeting_hooks_v24916p2c import (
    apply_generation_positive_damping,
    recompute_generation_post_target_summary,
    select_td_components,
)
from r1_15a2_safety_v24916p2c import build_safety_contract, assert_feature_off_exact
from r1_15a2_live_preflight_v24916p2c import run_read_only_preflight
from r1_15a2_procseq_guard_v24916p2c import guard_candidate_sequence
from r1_15a2_demand_targeting_integration_v24916p2c import DemandTargetingHooks

ROOT = Path(__file__).resolve().parents[1]
CFG = {
    "performance": {
        "v24916_flowbundle_skim": {
            "enabled": False, "shadow_mode": True,
            "generation_targeting_enabled": False, "td_mask_enabled": False,
            "combined_enabled": False, "supply_targeting_enabled": False,
            "shortest_imp_oracle_enabled": False, "cross_run_evidence_cache": False,
            "production_com_probing": False,
        }
    }
}


def identity(**overrides):
    base = dict(
        run_token="run",
        visum_session_token="session",
        semantic_state_hash="state",
        assignment_token="assignment",
        assignment_epoch=1,
        path_epoch=2,
        path_basis_hash="path",
        comparison_basis_hash="comparison",
        zone_order_hash=ordered_zone_hash([1, 2]),
        flowbundle_contract_hash="contract",
        dist_km_hash="dist",
        targeting_config_hash="cfg",
    )
    base.update(overrides)
    return FlowBundleEvidenceIdentity(**base)


def skim(values=((0.0, 1.0), (1.0, 0.0))):
    return seal_dist_km(matrix_no=9001, matrix_code="DIST_KM", unit="km", values=values, zone_nos=[1, 2], exact_expected_code="DIST_KM")


def test_feature_off_config_is_exact_and_safe():
    assert_feature_off_exact(CFG)
    c = build_safety_contract(CFG)
    assert c.contract_hash


def test_directed_reduction_total_and_tail_parity():
    r = reduce_directed([[0.0, 2.0], [3.0, 0.0]], [1, 2], top_k=1)
    assert r.total == 5.0
    assert r.retained_total + r.tail_total == pytest.approx(5.0)
    assert len(r.retained_od) == 1
    assert_reduced_parity(r, 5.0)


def test_both_is_exact_cellwise_sum():
    r = reduce_both_directions([[0, 2], [1, 0]], [[0, 3], [4, 0]], [10, 20], top_k=4)
    assert r.total == 10.0
    assert (10, 20, 5.0) in r.retained_od
    assert (20, 10, 5.0) in r.retained_od
    assert r.source_directions == ("FORWARD", "REVERSE")


def test_dimension_mismatch_fails_closed():
    with pytest.raises(ValueError, match="DIMENSION"):
        reduce_directed([[1.0]], [1, 2])


def test_nonfinite_and_negative_fail_closed():
    with pytest.raises(ValueError, match="NONFINITE"):
        reduce_directed([[0.0, float("inf")], [0.0, 0.0]], [1, 2])
    with pytest.raises(ValueError, match="NEGATIVE"):
        reduce_directed([[0.0, -1.0], [0.0, 0.0]], [1, 2])


def test_zone_order_hash_is_order_sensitive_and_unique():
    assert ordered_zone_hash([1, 2]) != ordered_zone_hash([2, 1])
    with pytest.raises(ValueError, match="DUPLICATE"):
        ordered_zone_hash([1, 1])


def test_dist_km_identity_is_sealed():
    a = skim()
    b = skim()
    require_same_skim_identity(a, b)
    assert a.unit == "km"
    assert a.n_zones == 2


def test_dist_km_code_unit_dimension_are_exact():
    with pytest.raises(ValueError, match="CODE_MISMATCH"):
        seal_dist_km(matrix_no=1, matrix_code="DIST", unit="km", values=[[0, 1], [1, 0]], zone_nos=[1, 2], exact_expected_code="DIST_KM")
    with pytest.raises(ValueError, match="UNIT_NOT_KM"):
        seal_dist_km(matrix_no=1, matrix_code="DIST_KM", unit="m", values=[[0, 1], [1, 0]], zone_nos=[1, 2])
    with pytest.raises(ValueError, match="DIMENSION"):
        seal_dist_km(matrix_no=1, matrix_code="DIST_KM", unit="km", values=[[0]], zone_nos=[1, 2])


def test_shortest_imp_is_hard_disabled():
    assert shortest_imp_oracle_enabled({}) is False
    with pytest.raises(RuntimeError, match="NOT_CERTIFIED"):
        shortest_imp_oracle_enabled({"shortest_imp_oracle_enabled": True})


def test_strong_identity_changes_for_every_critical_axis():
    base = identity()
    fields = {
        "assignment_epoch": 2,
        "path_epoch": 3,
        "path_basis_hash": "other",
        "comparison_basis_hash": "other",
        "zone_order_hash": ordered_zone_hash([2, 1]),
        "dist_km_hash": "other",
        "targeting_config_hash": "other",
    }
    for key, value in fields.items():
        assert identity(**{key: value}).identity_hash != base.identity_hash


def test_evidence_manager_exact_identity_and_lru():
    mgr = BoundedDemandEvidenceManager(max_entries=1)
    red = reduce_directed([[0, 2], [3, 0]], [1, 2], top_k=2)
    i1 = identity()
    s1 = mgr.publish(identity=i1, flowbundles={"p": red}, skim_identity=skim(), target_payload={"zones": [1]})
    assert mgr.require_current(i1).payload_hash == s1.payload_hash
    i2 = identity(path_epoch=99)
    mgr.publish(identity=i2, flowbundles={"p": red}, skim_identity=skim(), target_payload={})
    assert mgr.get(i1) is None
    assert mgr.get(i2) is not None


def test_evidence_tamper_fails_closed():
    mgr = BoundedDemandEvidenceManager()
    red = reduce_directed([[0, 2], [3, 0]], [1, 2])
    i = identity()
    snap = mgr.publish(identity=i, flowbundles={"p": red}, skim_identity=skim(), target_payload={})
    object.__setattr__(snap, "payload_hash", "bad")
    with pytest.raises(RuntimeError, match="HASH_MISMATCH"):
        mgr.require_current(i)


def test_generation_targeting_preserves_order_and_sign():
    rows = [
        {"zone_no": 3, "delta": 2.0, "family": "WORK"},
        {"zone_no": 1, "delta": -1.0, "family": "WORK"},
        {"zone_no": 2, "delta": 4.0, "family": "SERV"},
        {"zone_no": 4, "delta": 0.0, "family": "SERV"},
    ]
    out, audit = apply_generation_positive_damping(rows, {2}, outside_positive_factor=0.25)
    assert [r["zone_no"] for r in out] == [3, 1, 2, 4]
    assert [r["delta"] for r in out] == [0.5, -1.0, 4.0, 0.0]
    assert audit.sign_flip_count == 0
    assert audit.order_preserved


def test_generation_targeting_rejects_bad_factor():
    with pytest.raises(ValueError, match="OUT_OF_RANGE"):
        apply_generation_positive_damping([], [], outside_positive_factor=1.1)


def test_post_target_summary_is_recomputed_from_actual_rows():
    rows = [{"zone_no": 1, "delta": 1.0, "family": "WORK"}, {"zone_no": 2, "delta": -0.25, "family": "WORK"}]
    summary = recompute_generation_post_target_summary(rows)
    assert summary["delta_sum"] == pytest.approx(0.75)
    assert summary["summary_source"] == "ACTUAL_POST_TARGET_ROWS"
    assert summary["by_family"]["WORK"]["count"] == 2


def test_td_mask_work_service_only_bounded_and_ordered():
    comps = ["LONG_E_C", "WORK_A", "SERV_A", "SCHOOL", "WORK_B", "SERV_B"]
    pressure = {"LONG_E_C": 100, "WORK_A": 2, "SERV_A": 4, "SCHOOL": 99, "WORK_B": 3, "SERV_B": 1}
    selected, audit = select_td_components(comps, pressure, max_active_components=2)
    assert selected == ["SERV_A", "WORK_B"]
    assert "LONG_E_C" in audit.frozen_components
    assert "SCHOOL" in audit.frozen_components
    assert audit.input_order_preserved


def test_td_mask_nonfinite_fails():
    with pytest.raises(ValueError, match="NONFINITE"):
        select_td_components(["WORK_A"], {"WORK_A": float("nan")}, max_active_components=1)


def test_procseq_guard_rejects_unknown_active_script():
    r = guard_candidate_sequence([{"index": 1, "type": "SCRIPT", "active": True, "id": "display-only"}])
    assert not r.passes
    r2 = guard_candidate_sequence([{"index": 1, "type": "SCRIPT", "active": True, "id": "approved"}], allowed_script_ids=["approved"])
    assert r2.passes


def test_read_only_preflight_pass_and_fail():
    s = skim()
    zh = ordered_zone_hash([1, 2])
    ok = run_read_only_preflight(
        config=CFG,
        zone_nos=[1, 2],
        expected_zone_order_hash=zh,
        skim_identity=s,
        dseg_roles={"C": "TARGET_NATIVE"},
        required_native_dsegs=["C"],
        flowbundle_contract_hash="x",
        expected_flowbundle_contract_hash="x",
        reverse_link_proof={"passes": True, "method": "EXACT"},
    )
    assert ok.passes
    bad = run_read_only_preflight(
        config=CFG,
        zone_nos=[2, 1],
        expected_zone_order_hash=zh,
        skim_identity=s,
        dseg_roles={"C": "EXOG"},
        required_native_dsegs=["C"],
        flowbundle_contract_hash="x",
        expected_flowbundle_contract_hash="y",
    )
    assert not bad.passes


def test_controller_hooks_are_exact_noop_when_feature_off():
    class A:
        pass
    hooks = DemandTargetingHooks(A(), CFG)
    rows = [{"zone_no": 2, "delta": 1.0}]
    out, audit = hooks.before_generation_apply(rows, [2])
    assert out == rows
    assert audit["status"] == "FEATURE_OFF"
    comps, audit2 = hooks.before_finecdf_active_set(["WORK_A"], {"WORK_A": 99})
    assert comps == ["WORK_A"]
    assert audit2["status"] == "FEATURE_OFF"


def test_full_matrices_are_not_owned_by_reduced_payload():
    matrix = [[0.0, 2.0], [3.0, 0.0]]
    red = reduce_directed(matrix, [1, 2])
    matrix[0][1] = 999.0
    assert red.total == 5.0
    assert not hasattr(red, "matrix")

from r1_15a2_finecdf_target_hook_v24916p2c import build_targeted_active_set, assert_all_17_restored


def test_finecdf_feature_off_preserves_all_parent_components():
    comps = [f"WORK_{i}" for i in range(5)] + [f"SERV_{i}" for i in range(5)] + [f"LONG_{i}" for i in range(5)] + ["SCHOOL", "OTHER"]
    selected, audit = build_targeted_active_set(comps, {}, enabled=False, max_active_components=4)
    assert selected == comps
    assert audit["status"] == "FEATURE_OFF"


def test_td_rollback_all_components_exact():
    before = {f"C{i}": (float(i), -float(i)) for i in range(17)}
    assert_all_17_restored(before, dict(before))
    after = dict(before); after["C3"] = (99.0, -3.0)
    with pytest.raises(AssertionError, match="NOT_EXACT"):
        assert_all_17_restored(before, after)

from r1_15a2_runtime_manifest_v24916p2c import verify_runtime_manifest


def test_runtime_manifest_passes():
    report = verify_runtime_manifest(ROOT)
    assert report["passes"]
    assert report["rows"]


def test_fresh0_isolated_launcher_is_the_only_numbered_entrypoint():
    launchers = sorted(ROOT.glob("00_*.py"))
    assert [p.name for p in launchers] == ["00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py"]
    text = launchers[0].read_text(encoding="utf-8")
    assert "r1_15a2_fresh0_shortroot_parent_v24916" in text
    child = (ROOT / "r1_15a2_fresh0_shortroot_parent_v24916.py").read_text(encoding="utf-8")
    assert "FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_CYCLE1_NO_WALLCLOCK" in child
    assert "R1_15A2_RESUME_PROFILE488_A0004" not in text
    assert "external_cache_read_allowed=False" in text
    assert "accepted_count_start=0" in text
    assert "outer_cycle_start=1" in text

from r1_15a2_demand_support_v24916p2c import build_generation_target_zones_with_order, build_td_component_pressure


def test_generation_target_zones_use_positive_residual_and_explicit_order():
    red = reduce_directed([[0, 8], [2, 0]], [1, 2], top_k=4)
    target = build_generation_target_zones_with_order({"p": red}, {"p": 10.0}, [1, 2], max_zones=1)
    assert len(target.zone_nos) == 1
    assert target.zone_nos[0] in {1, 2}
    none = build_generation_target_zones_with_order({"p": red}, {"p": -1.0}, [1, 2])
    assert none.zone_nos == ()


def test_td_pressure_excludes_long_school_and_diagnostic():
    pressure = build_td_component_pressure(
        {"WORK": 2, "SERV": 3},
        {"WORK_A": .5, "SERV_A": .25, "LONG_A": 100, "SCHOOL": 100, "SERV_DIAG": 100},
        {"WORK_A": "WORK", "SERV_A": "SERV", "LONG_A": "LONG", "SCHOOL": "SCHOOL", "SERV_DIAG": "SERV"},
        diagnostic_only_components=["SERV_DIAG"],
    )
    assert dict(pressure.pressure_by_component) == {"SERV_A": .75, "WORK_A": 1.0}
    assert "SERV_DIAG" in pressure.diagnostic_only_components
