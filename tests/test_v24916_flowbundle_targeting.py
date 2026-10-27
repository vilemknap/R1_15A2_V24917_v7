# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

import r1_15a2_com_compat as com
from r1_15a2_demand_evidence_v24916 import (
    build_generation_targets,
    build_supported_od,
    build_td_targeting,
    path_parity,
    target_projection_rows,
)
from r1_15a2_flowbundle_v24916 import (
    FlowBundleAdapter,
    SEALED_CONTRACT_ID,
    canonical_dseg,
    select_driver_profiles,
)


class FakeComError(RuntimeError):
    def __init__(self, message, hresult):
        super().__init__(message)
        self.hresult = hresult


class Obj:
    def __init__(self, **attrs):
        self.attrs = dict(attrs)

    def AttValue(self, name):
        key = str(name).upper()
        for attr, value in self.attrs.items():
            if str(attr).upper() == key:
                return value
        raise KeyError(name)


class Collection:
    def __init__(self, rows):
        self.rows = list(rows)

    def GetAll(self):
        return list(self.rows)


class Links:
    def __init__(self, rows):
        self.rows = {(
            int(row.attrs["NO"]), int(row.attrs["FROMNODENO"]), int(row.attrs["TONODENO"])
        ): row for row in rows}

    def ItemByKey(self, *args):
        if len(args) == 2:
            fr, to = (int(x) for x in args)
            matches = [obj for (_link_no, row_fr, row_to), obj in self.rows.items()
                       if row_fr == fr and row_to == to]
            if len(matches) == 1:
                return matches[0]
        raise KeyError(args)


class Matrix:
    def __init__(self, values, transient_failures=0):
        self.values = values
        self.transient_failures = int(transient_failures)
        self.get_values_calls = 0

    def GetValues(self):
        self.get_values_calls += 1
        if self.transient_failures > 0:
            self.transient_failures -= 1
            raise FakeComError("call was rejected by callee", com.RPC_E_CALL_REJECTED)
        return self.values


class FlowBundle:
    def __init__(self, matrices_by_link_dseg):
        self.matrices_by_link_dseg = dict(matrices_by_link_dseg)
        self.current_link = None
        self.current_dseg = None
        self.calls = []

    def Clear(self):
        self.calls.append(("Clear",))
        self.current_link = None

    @property
    def DemandSegments(self):
        return self.current_dseg

    @DemandSegments.setter
    def DemandSegments(self, value):
        self.calls.append(("DemandSegments", value))
        self.current_dseg = canonical_dseg(value)

    def CreateCondition(self, link, activity_set, complement, time_restricted, from_time, to_time):
        self.calls.append(("CreateCondition", link, activity_set, complement,
                           time_restricted, from_time, to_time))
        self.current_link = (
            int(link.attrs["NO"]), int(link.attrs["FROMNODENO"]), int(link.attrs["TONODENO"])
        )

    def ExecuteCurrentConditions(self):
        self.calls.append(("ExecuteCurrentConditions",))
        if self.current_link is None:
            raise RuntimeError("NO_CONDITION")

    def GetOrCreateFlowBundleMatrix(self, dseg_object):
        code = canonical_dseg(dseg_object.AttValue("CODE"))
        self.calls.append(("GetOrCreateFlowBundleMatrix", code))
        return self.matrices_by_link_dseg[(self.current_link, code)]


class Net:
    def __init__(self, links, dsegs, flowbundle):
        self.Links = Links(links)
        self.DemandSegments = Collection(dsegs)
        self.FlowBundle = flowbundle


class Visum:
    def __init__(self, links, dsegs, flowbundle):
        self.Net = Net(links, dsegs, flowbundle)


def cfg():
    return {
        "com_resilience": {
            "enabled": True,
            "max_attempts": 3,
            "initial_delay_seconds": 0.0,
            "backoff_factor": 2.0,
            "max_delay_seconds": 0.0,
        },
        "demand_evidence_targeting": {
            "flowbundle_target_dsegs": ["NATIVE_CW", "NATIVE_CS"],
            "flowbundle_optional_diagnostic_dsegs": ["EXOG_EE_CW"],
            "flowbundle": {
                "max_profiles": 10,
                "min_profile_geh": 10.0,
                "min_profile_abs_residual": 100.0,
                "min_od_volume": 0.01,
                "max_od_rows_per_profile": 20,
                "retained_volume_coverage": 0.90,
                "minimum_profile_coverage": 0.70,
            },
        },
    }


def profile(no=1001, family="CW", direction="DIRECTED"):
    row = {
        "countlocation_no": no,
        "role": "CALIBRATION",
        "active": 1,
        "primary_family": family,
        "observed": 1000.0,
        "model": 500.0,
        "geh": 20.0,
        "link_no": 77,
        "from_node_no": 1,
        "to_node_no": 2,
        "observation_direction": direction,
    }
    if direction == "BOTH":
        row.update(reverse_link_no=77, reverse_from_node_no=2, reverse_to_node_no=1)
    return row


def test_driver_selection_excludes_validation_overload_and_non_work_service():
    rows = [
        profile(1, "CW"),
        dict(profile(2, "CW"), role="VALIDATION"),
        dict(profile(3, "CS"), observed=400.0, model=800.0),
        dict(profile(4, "CL"), observed=1000.0, model=100.0),
    ]
    selected = select_driver_profiles(rows, 10, 10.0, 100.0)
    assert [row["_v24916_profile_id"] for row in selected] == ["1"]


def test_sealed_contract_directed_call_order_and_transient_retry():
    link = Obj(NO=77, FROMNODENO=1, TONODENO=2)
    dseg = Obj(CODE="NATIVE_CW")
    matrix = Matrix([[0.0, 80.0], [20.0, 0.0]], transient_failures=1)
    fb = FlowBundle({((77, 1, 2), "NATIVE_CW"): matrix})
    adapter = FlowBundleAdapter(Visum([link], [dseg], fb), cfg())

    result = adapter.extract_snapshot([profile()], "STATE", [10, 30])

    assert result.status == "ACTIVE"
    assert result.contract.contract_id == SEALED_CONTRACT_ID
    assert sum(row["flowbundle_volume"] for row in result.rows) == pytest.approx(100.0)
    assert matrix.get_values_calls == 2
    assert len(adapter.retry_events) == 1
    names = [call[0] for call in fb.calls]
    assert names == [
        "Clear", "DemandSegments", "CreateCondition", "ExecuteCurrentConditions",
        "GetOrCreateFlowBundleMatrix", "Clear",
    ]
    condition = next(call for call in fb.calls if call[0] == "CreateCondition")
    assert condition[2:] == (None, False, False, 0, 0)
    assert not any(name in names for name in ("Execute", "CreateActivityTypeSet", "CreateRouteTrafficTypeSet"))


def test_non_transient_error_is_not_retried_and_falls_back_locally():
    class BadMatrix(Matrix):
        def GetValues(self):
            self.get_values_calls += 1
            raise TypeError("wrong signature")

    link = Obj(NO=77, FROMNODENO=1, TONODENO=2)
    dseg = Obj(CODE="NATIVE_CW")
    matrix = BadMatrix([[0.0]])
    fb = FlowBundle({((77, 1, 2), "NATIVE_CW"): matrix})
    adapter = FlowBundleAdapter(Visum([link], [dseg], fb), cfg())

    result = adapter.extract_snapshot([profile()], "STATE", [10, 30])

    assert result.status == "PATH_ONLY_FALLBACK"
    assert matrix.get_values_calls == 1
    assert adapter.retry_events == []
    assert any(row["targeting_mode"] == "PATH_ONLY_PROFILE_FALLBACK"
               for row in result.profile_status)


def test_both_scope_is_exact_sum_of_two_directional_matrices():
    forward = Obj(NO=77, FROMNODENO=1, TONODENO=2)
    reverse = Obj(NO=77, FROMNODENO=2, TONODENO=1)
    dseg = Obj(CODE="NATIVE_CW")
    fb = FlowBundle({
        ((77, 1, 2), "NATIVE_CW"): Matrix([[0.0, 40.0], [10.0, 0.0]]),
        ((77, 2, 1), "NATIVE_CW"): Matrix([[0.0, 20.0], [30.0, 0.0]]),
    })
    adapter = FlowBundleAdapter(Visum([forward, reverse], [dseg], fb), cfg())

    result = adapter.extract_snapshot([profile(direction="BOTH")], "STATE", [10, 30])

    assert result.status == "ACTIVE"
    by_od = {(row["origin"], row["destination"]): row["flowbundle_volume"]
             for row in result.rows}
    assert by_od == {(10, 30): pytest.approx(60.0), (30, 10): pytest.approx(40.0)}
    assert result.profile_status[-1]["condition_count"] == 2
    assert [call[0] for call in fb.calls].count("CreateCondition") == 2


def test_exog_is_extracted_but_never_targeting_eligible():
    link = Obj(NO=77, FROMNODENO=1, TONODENO=2)
    native = Obj(CODE="NATIVE_CW")
    exog = Obj(CODE="EXOG_EE_CW")
    fb = FlowBundle({
        ((77, 1, 2), "NATIVE_CW"): Matrix([[0.0, 80.0], [20.0, 0.0]]),
        ((77, 1, 2), "EXOG_EE_CW"): Matrix([[0.0, 10.0], [5.0, 0.0]]),
    })
    adapter = FlowBundleAdapter(Visum([link], [native, exog], fb), cfg())

    result = adapter.extract_snapshot([profile()], "STATE", [10, 30])

    assert {row["dseg_role"] for row in result.rows} == {
        "TARGET_NATIVE", "DIAGNOSTIC_EXOG_EE"
    }
    assert all(row["targeting_eligible"] == 0 for row in result.rows
               if row["dseg_role"] == "DIAGNOSTIC_EXOG_EE")


def test_two_level_parity_detects_equal_total_but_wrong_od_distribution():
    fb = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "flowbundle_volume": 80.0, "flowbundle_total": 100.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "flowbundle_volume": 15.0, "flowbundle_total": 100.0},
    ]
    path = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "path_profile_volume": 20.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "path_profile_volume": 75.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 4, "path_profile_volume": 5.0},
    ]
    result = path_parity(fb, path, 0.01, 1.0, 0.10, 5.0)
    assert result["rows"][0]["total_parity_passes"] == 1
    assert result["rows"][0]["od_parity_passes"] == 0
    assert result["decision"] == "PATH_ONLY_FALLBACK"


def test_tail_bucket_prevents_false_failure_for_truncated_flowbundle_detail():
    fb = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "flowbundle_volume": 80.0, "flowbundle_total": 100.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "flowbundle_volume": 15.0, "flowbundle_total": 100.0},
    ]
    path = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "path_profile_volume": 80.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "path_profile_volume": 15.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 9,
         "destination": 10, "path_profile_volume": 5.0},
    ]
    result = path_parity(fb, path, 0.01, 1.0, 0.01, 1.0)
    assert result["status"] == "PASS"
    assert result["rows"][0]["tail_abs_diff"] == pytest.approx(0.0)


def evidence_cfg():
    return {
        "flowbundle": {"retained_volume_coverage": 0.9, "minimum_profile_coverage": 0.7},
        "generation": {
            "enabled": True,
            "require_supported_od": True,
            "target_step_multiplier": 1.0,
            "non_target_step_multiplier": 0.2,
            "maximum_target_zones_per_family_role": 20,
        },
        "td": {
            "enabled": True,
            "families": ["WORK", "SERVICE"],
            "max_active_components_per_family": 2,
            "max_active_components_total": 4,
            "minimum_alignment_score": 0.0,
            "distance_bin_edges_km": [5, 10, 20, 30, 50],
        },
    }


def test_signed_safe_generation_only_damps_positive_non_targets():
    supported = build_supported_od([
        {"dseg_code": "NATIVE_CW", "origin": 10, "destination": 20, "path_count": 1}
    ])
    targets = build_generation_targets([
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 10,
         "destination": 20, "flowbundle_volume": 100.0, "residual": 50.0}
    ], supported, evidence_cfg())
    rows = [
        {"family": "WORK", "role": "PROD", "zone_no": 10, "log_step": 0.08},
        {"family": "WORK", "role": "PROD", "zone_no": 99, "log_step": 0.08},
        {"family": "WORK", "role": "PROD", "zone_no": 98, "log_step": -0.08},
    ]
    out, audit = target_projection_rows(rows, targets, evidence_cfg())
    by_zone = {row["zone_no"]: row for row in out}
    assert by_zone[10]["log_step"] == pytest.approx(0.08)
    assert by_zone[99]["log_step"] == pytest.approx(0.016)
    assert by_zone[98]["log_step"] == pytest.approx(-0.08)
    assert audit["negative_rows_unchanged"] == 1
    assert audit["sign_flip_possible"] is False


def test_td_targeting_excludes_school_and_long_and_obeys_caps():
    flow = [
        {"dseg_code": "NATIVE_CW", "flowbundle_volume": 100.0,
         "residual": 50.0, "distance_km": 12.0},
        {"dseg_code": "NATIVE_CS", "flowbundle_volume": 100.0,
         "residual": 50.0, "distance_km": 22.0},
    ]
    components = []
    for name, family, l1 in [
        ("WORK_A", "WORK", 0.9), ("WORK_B", "WORK", 0.8), ("WORK_C", "WORK", 0.7),
        ("SERV_A", "SERVICE", 0.9), ("SERV_B", "SERVICE", 0.8), ("SERV_C", "SERVICE", 0.7),
        ("SCHOOL", "SCHOOL", 99.0), ("LONG_A", "LONG", 99.0),
    ]:
        components.append({
            "component": name, "family": family,
            "target_status": "ACTIVE_COMPONENT_DIST_TARGET",
            "l1_distance_half": l1, "rmse_share": 0.1,
            "mean_delta_model_minus_target": 1.0,
        })
    result = build_td_targeting(flow, components, evidence_cfg())
    assert len(result["active_components"]) == 4
    assert sum(name.startswith("WORK") for name in result["active_components"]) == 2
    assert sum(name.startswith("SERV") for name in result["active_components"]) == 2
    assert not any(name.startswith("SCHOOL") or name.startswith("LONG")
                   for name in result["active_components"])
    assert result["global_11d_evaluation_required"] is True
