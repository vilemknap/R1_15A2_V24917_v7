"""Offline tests for the production TDLONG1 mask and feasibility module."""
from types import SimpleNamespace
import hashlib

import numpy as np
import pytest

import r1_15a2_long_od_mask_v24917 as tdlong
from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build(distance, zones=(10, 20, 30), **overrides):
    return tdlong.build_support_mask(
        distance, zones, unit="km",
        expected_values_sha256=matrix_values_hash(distance),
        expected_zone_order_sha256=ordered_zone_hash(zones),
        epoch_hash=_hash("epoch"), assignment_epoch=7, skim_epoch=9,
        diagnostic_epoch_hash=_hash("epoch"), diagnostic_assignment_epoch=7,
        **overrides)


def _marginals(p, a):
    return {no: {"production": list(p), "attraction": list(a)}
            for no in tdlong.MATRIX_NOS}


def test_mask_threshold_bands_hashes_and_input_immutability():
    distance = np.array([[0.0, 99.999, 100.0],
                         [100.001, 200.0, 200.001],
                         [500.0, 99.0, 150.0]])
    original = distance.copy()
    support = _build(distance)
    assert support.mask.sum() == 6
    assert support.counts == {
        "allowed_ge_100_km": 6,
        "below_100_km": 3,
        "km_100_to_200_inclusive": 4,
        "above_200_km_allowed": 2,
        "total_od_pairs": 9,
    }
    assert support.mask[0, 2] and support.mask[1, 1] and support.mask[1, 2]
    assert support.mask[2, 0]  # >200 km remains allowed
    assert np.array_equal(distance, original)
    assert not support.mask.flags.writeable
    assert len(support.mask_sha256_diagnostic_only) == 64
    assert support.summary()["mask_hash_role"] == "DIAGNOSTIC_ONLY_NOT_A_PROJECT_AUTHORITY"


@pytest.mark.parametrize("distance,unit,code", [
    (np.zeros((2, 3)), "km", "SHAPE_MISMATCH"),
    (np.array([[0.0, np.nan], [1.0, 2.0]]), "km", "NOT_FINITE_NONNEGATIVE"),
    (np.array([[0.0, np.inf], [1.0, 2.0]]), "km", "NOT_FINITE_NONNEGATIVE"),
    (np.array([[0.0, -0.1], [1.0, 2.0]]), "km", "NOT_FINITE_NONNEGATIVE"),
    (np.zeros((2, 2)), "m", "UNIT_NOT_KM"),
])
def test_mask_rejects_invalid_distance_contract(distance, unit, code):
    zones = (1, 2)
    with pytest.raises(ValueError, match=code):
        tdlong.build_support_mask(
            distance, zones, unit=unit,
            expected_values_sha256=matrix_values_hash(np.nan_to_num(distance, nan=0.0, posinf=0.0)),
            expected_zone_order_sha256=ordered_zone_hash(zones),
            epoch_hash=_hash("e"), assignment_epoch=1, skim_epoch=1,
            diagnostic_epoch_hash=_hash("e"), diagnostic_assignment_epoch=1)


def test_mask_rejects_zone_axis_and_hash_mismatches():
    with pytest.raises(ValueError, match="DUPLICATE_ZONE_ID"):
        tdlong.build_support_mask(
            np.zeros((3, 3)), (1, 1, 2), unit="km",
            expected_values_sha256=matrix_values_hash(np.zeros((3, 3))),
            expected_zone_order_sha256=ordered_zone_hash((1, 2, 3)),
            epoch_hash=_hash("e"), assignment_epoch=1, skim_epoch=1,
            diagnostic_epoch_hash=_hash("e"), diagnostic_assignment_epoch=1)
    with pytest.raises(ValueError, match="INVALID_ZONE_ID"):
        _build(np.zeros((2, 2)), zones=(1.0, 2.0))
    d = np.eye(2)
    zones = (1, 2)
    kwargs = dict(unit="km", expected_values_sha256=matrix_values_hash(d),
                  expected_zone_order_sha256=ordered_zone_hash(zones),
                  epoch_hash=_hash("e"), assignment_epoch=1, skim_epoch=2,
                  diagnostic_epoch_hash=_hash("e"), diagnostic_assignment_epoch=1)
    with pytest.raises(ValueError, match="VALUES_HASH_MISMATCH"):
        tdlong.build_support_mask(d + 1.0, zones, **kwargs)
    with pytest.raises(ValueError, match="DIAGNOSTIC_EPOCH_MISMATCH"):
        tdlong.build_support_mask(d, zones, **{**kwargs, "diagnostic_epoch_hash": _hash("old")})
    with pytest.raises(ValueError, match="DIAGNOSTIC_EPOCH_MISMATCH"):
        tdlong.build_support_mask(d, zones, **{**kwargs, "diagnostic_assignment_epoch": 0})


def test_capture_current_binds_assignment_skim_values_and_zone_hash():
    zones = [11, 12]
    distance = np.array([[0.0, 100.0], [200.001, 0.0]])
    zone_sha = ordered_zone_hash(zones)
    values_sha = matrix_values_hash(distance)
    epoch_sha = _hash("bound-epoch")
    meta = {"NATIVE_CL": {"unit": "km", "values_sha256": values_sha}}
    epoch = SimpleNamespace(family_distance={"LONG": distance}, matrix_meta_by_dseg=meta,
                            zone_order_sha256=zone_sha, epoch_hash=epoch_sha,
                            assignment_epoch=8, epoch=9)
    adapter = SimpleNamespace(zones=zones,
                              v24916_dynamic_skims=SimpleNamespace(require_current=lambda: epoch))
    authority = {"assignment_epoch": 8, "epoch": 9, "epoch_hash": epoch_sha,
                 "zone_order_sha256": zone_sha,
                 "matrix_meta_by_dseg": {"NATIVE_CL": {"values_sha256": values_sha}}}
    result = tdlong.capture_current(adapter, {"dynamic_skim_epoch": authority})
    assert result["status"] == "MASK_READY_NATIVE_FILTER_UNVERIFIED"
    assert result["source"]["counts"]["above_200_km_allowed"] == 1
    assert result["long_generation_permitted"] is False
    stale = dict(authority, assignment_epoch=7)
    assert tdlong.capture_current(adapter, {"dynamic_skim_epoch": stale})["status"] == "INVALID_EPOCH"
    assert tdlong.capture_current(SimpleNamespace(zones=zones), {})["reason"] == "INVALID_EPOCH"


def test_restricted_pa_feasibility_and_per_component_audit():
    support = np.eye(3, dtype=bool)
    result = tdlong.check_restricted_pa_feasibility(
        support, _marginals([1, 2, 0], [1, 2, 0]), zone_nos=(10, 20, 30))
    assert result["status"] == "FEASIBLE"
    assert set(result["components"]) == {str(x) for x in range(9111, 9116)}
    assert all(row["feasible"] for row in result["components"].values())
    assert result["native_filter_verified"] is False


def test_hall_deficient_subset_has_deterministic_witness():
    # Every origin and destination has support, but origins 10 and 20 jointly
    # have only destination 10, whose attraction is insufficient.
    support = np.array([[1, 0, 0], [1, 0, 0], [0, 1, 1]], dtype=bool)
    bad = {"production": [4, 4, 2], "attraction": [5, 3, 2]}
    good = {"production": [0.2, 0.3, 0.5], "attraction": [0.5, 0.25, 0.25]}
    components = {no: (bad if no == 9111 else good) for no in tdlong.MATRIX_NOS}
    first = tdlong.check_restricted_pa_feasibility(support, components, zone_nos=(10, 20, 30))
    second = tdlong.check_restricted_pa_feasibility(support, components, zone_nos=(10, 20, 30))
    assert first["status"] == "INFEASIBLE_PA"
    row = first["components"]["9111"]
    assert row["reason"] == "INFEASIBLE_PA"
    assert row["mass_shortfall"] == pytest.approx(3.0)
    assert row["witness"]["origin_zones"] == [10, 20]
    assert row["witness"]["destination_zones"] == [10]
    assert row["witness"] == second["components"]["9111"]["witness"]
    assert all(first["components"][str(no)]["feasible"] for no in tdlong.MATRIX_NOS if no != 9111)


@pytest.mark.parametrize("support,p,a,reason", [
    (np.array([[0, 0], [0, 1]], bool), [1, 0], [1, 0], "INFEASIBLE_PA"),
    (np.array([[1, 0], [0, 0]], bool), [0, 1], [0, 1], "INFEASIBLE_PA"),
    (np.eye(2, dtype=bool), [1, 0], [0, 0], "UNEQUAL_TOTALS"),
])
def test_isolated_nodes_and_unequal_totals_are_not_treated_as_feasible(support, p, a, reason):
    result = tdlong.check_restricted_pa_feasibility(support, _marginals(p, a))
    assert result["status"] == "INFEASIBLE_PA"
    assert result["components"]["9111"]["reason"] == reason


def test_directional_support_and_symmetric_safe_intersection():
    support = np.array([[1, 1], [0, 1]], dtype=bool)
    margins = _marginals([1, 0], [0, 1])
    directed = tdlong.check_restricted_pa_feasibility(support, margins)
    symmetric = tdlong.check_restricted_pa_feasibility(support, margins, symmetry_safe=True)
    assert directed["status"] == "FEASIBLE"
    assert symmetric["status"] == "INFEASIBLE_PA"
    assert symmetric["support_policy"] == "BIDIRECTIONAL_INTERSECTION"


def test_component_axis_and_marginal_errors_are_structured():
    incomplete = {no: {"production": [1], "attraction": [1]} for no in tdlong.MATRIX_NOS[:-1]}
    assert tdlong.check_restricted_pa_feasibility(np.ones((1, 1), bool), incomplete)["reason"] == "LONG_COMPONENT_SET_MISMATCH"
    invalid = _marginals([1], [1]); invalid[9113]["production"] = [float("nan")]
    result = tdlong.check_restricted_pa_feasibility(np.ones((1, 1), bool), invalid)
    assert result["status"] == "INVALID_MARGINS"
    assert result["components"]["9113"]["reason"] == "INVALID_MARGINS"


def test_681_zone_feasibility_uses_pair_graph_not_profile_od_tensor():
    n = 681
    support = np.eye(n, dtype=bool)
    margins = _marginals(np.ones(n), np.ones(n))
    result = tdlong.check_restricted_pa_feasibility(support, margins)
    assert result["status"] == "FEASIBLE"
    assert result["allowed_pairs"] == n


def test_deferred_long_operator_recomputes_prediction_and_preserves_school():
    import r1_15a2_long_school_generation_v24917 as ls
    state = {"steps": {"ADD_PROD_L": {10: 0.1, 20: -0.1},
                       "ADD_ATT_L": {10: 0.05},
                       "ADD_PROD_SCH": {10: 0.02}, "ADD_ATT_SCH": {}},
             "effect_operator": {"keys": [["LONG", "PROD", 10], ["LONG", "PROD", 20],
                                          ["LONG", "ATT", 10], ["SCHOOL", "PROD", 10]],
                                 "G": [[100., 200., 300., 400.]]},
             "predicted_change": [999.], "summary": {"long_zone_steps": 2}}
    result = ls.defer_long(state, "UNVERIFIED_NATIVE_FILTER")
    assert result["steps"]["ADD_PROD_L"] == {10: 0.0, 20: 0.0}
    assert result["steps"]["ADD_ATT_L"] == {10: 0.0}
    assert result["steps"]["ADD_PROD_SCH"] == {10: 0.02}
    assert result["predicted_change"] == pytest.approx([8.0])
    assert result["summary"]["long_search_status"] == "LONG_SEARCH_INCOMPLETE"
    assert state["predicted_change"] == [999.]


def test_active_adapter_never_emits_unverified_long_rows():
    from r1_15a2_trial_adapter_v24917 import VisumAdapter
    rows = [{"family": "LONG", "attr": "ADD_PROD_L", "zone_no": 10},
            {"family": "SCHOOL", "attr": "ADD_PROD_SCH", "zone_no": 10}]
    assert VisumAdapter._without_unverified_long_rows(rows) == rows[1:]


def test_read_only_probe_reports_dstratset_but_never_claims_pair_filter(monkeypatch):
    import r1_15a2_tdlong1_probe_v24917 as probe

    class Params:
        def AttValue(self, attr):
            if attr == "DSTRATSET":
                return "3_LONG_E_C,3_LONG_E_noC,3_LONG_noE_C,3_LONG_noE_noC,3_LONG_stud"
            raise KeyError(attr)

    class Op:
        TripDistributionParameters = Params()
        def __init__(self, kind, active): self.kind, self.active = kind, active
        def AttValue(self, attr):
            return {"OPERATIONTYPE": self.kind, "ACTIVE": self.active,
                    "NAME": "Trip distribution", "COMMENT": "read only"}[attr]

    operations = SimpleNamespace(GetAll=(Op(46, 1), Op(17, 0)))
    visum = SimpleNamespace(Procedures=SimpleNamespace(Operations=operations))
    result = probe.inspect_read_only(visum)
    assert result["status"] == "UNVERIFIED_NATIVE_FILTER"
    assert result["native_filter_verified"] is False
    assert result["dstratset_is_pair_filter_evidence"] is False
    assert len(result["operations"]) == 1
    assert len(result["operations"][0]["long_components_present"]) == 5
    assert result["mutating_calls_made"] == []
