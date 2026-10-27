# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from r1_15a2_demand_evidence_v24916 import (
    build_generation_targets, build_supported_od, build_td_targeting,
    path_parity, retain_flowbundle_coverage, target_projection_rows,
)
from r1_15a2_flowbundle_v24916 import FlowBundleAdapter, select_driver_profiles
from r1_15a2_skim_v24916 import (
    read_distance_authority, read_optional_skim_authority,
)
from r1_15a2_block_classifier_v24916 import classify_shadow_rows


def _cfg():
    return {
        "flowbundle": {
            "retained_volume_coverage": 0.9,
            "minimum_profile_coverage": 0.7,
        },
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
            "max_active_components_per_family": 1,
            "max_active_components_total": 2,
            "minimum_alignment_score": 0.0,
            "distance_bin_edges_km": [5, 10, 20, 30, 50],
        },
    }


def test_driver_selection_uses_only_underloaded_calibration_work_service_profiles():
    rows = [
        {"countlocation_no": 1, "role": "CALIBRATION", "primary_family": "CW",
         "observed": 1000, "model": 500, "geh": 20},
        {"countlocation_no": 2, "role": "CALIBRATION", "primary_family": "CS",
         "observed": 500, "model": 800, "geh": 30},
        {"countlocation_no": 3, "role": "VALIDATION", "primary_family": "CW",
         "observed": 1000, "model": 100, "geh": 40},
    ]
    selected = select_driver_profiles(rows, 10, 10.0, 100.0)
    assert [r["_v249_profile_id"] for r in selected] == ["1"]


def test_flowbundle_retention_is_volume_coverage_not_row_count():
    rows = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "flowbundle_volume": 80.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "flowbundle_volume": 15.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 4, "flowbundle_volume": 5.0},
    ]
    kept, audit = retain_flowbundle_coverage(rows, 0.9, 0.7)
    assert len(kept) == 2
    assert audit[0]["retained_coverage"] == pytest.approx(0.95)


def test_path_parity_checks_total_and_retained_od_plus_tail():
    fb = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "flowbundle_volume": 80.0, "flowbundle_total": 100.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "flowbundle_volume": 15.0, "flowbundle_total": 100.0},
    ]
    paths = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "path_profile_volume": 80.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "path_profile_volume": 15.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 4, "path_profile_volume": 5.0},
    ]
    result = path_parity(fb, paths, 0.001, 0.01, 0.001, 0.01)
    assert result["status"] == "PASS"
    assert result["rows"][0]["od_abs_l1"] == pytest.approx(0.0)
    assert result["rows"][0]["path_tail_volume"] == pytest.approx(5.0)


def test_equal_totals_but_wrong_od_distribution_falls_back():
    fb = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "flowbundle_volume": 80.0, "flowbundle_total": 100.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "flowbundle_volume": 20.0, "flowbundle_total": 100.0},
    ]
    paths = [
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "path_profile_volume": 20.0},
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 3, "path_profile_volume": 80.0},
    ]
    result = path_parity(fb, paths, 0.001, 0.01, 0.10, 1.0)
    assert result["rows"][0]["total_parity_passes"] == 1
    assert result["rows"][0]["od_parity_passes"] == 0
    assert result["status"] == "PATH_ONLY_FALLBACK"


def test_generation_targeting_is_signed_safe():
    variables = [{"dseg_code": "NATIVE_CW", "origin": 10, "destination": 20,
                  "path_count": 2}]
    supported = build_supported_od(variables)
    fb = [{"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 10,
           "destination": 20, "flowbundle_volume": 100.0, "residual": 50.0}]
    targets = build_generation_targets(fb, supported, _cfg())
    projection = [
        {"family": "WORK", "role": "PROD", "zone_no": 10,
         "log_step": 0.08, "guided_margin_delta": 8.0},
        {"family": "WORK", "role": "PROD", "zone_no": 99,
         "log_step": 0.08, "guided_margin_delta": 8.0},
        {"family": "WORK", "role": "PROD", "zone_no": 98,
         "log_step": -0.04, "guided_margin_delta": -4.0},
    ]
    out, audit = target_projection_rows(projection, targets, _cfg())
    by_zone = {r["zone_no"]: r for r in out}
    assert by_zone[10]["log_step"] == pytest.approx(0.08)
    assert by_zone[99]["log_step"] == pytest.approx(0.016)
    assert by_zone[98]["log_step"] == pytest.approx(-0.04)
    assert by_zone[98]["guided_margin_delta"] == pytest.approx(-4.0)
    assert audit["negative_or_zero_rows_unchanged"] == 1


def test_td_targeting_ignores_exog_and_selects_small_native_mask():
    fb = [
        {"dseg_code": "NATIVE_CW", "targeting_eligible": True,
         "flowbundle_volume": 100.0, "residual": 50.0, "distance_km": 12.0},
        {"dseg_code": "EXOG_EE_CW", "targeting_eligible": False,
         "flowbundle_volume": 99999.0, "residual": 99999.0, "distance_km": 99.0},
        {"dseg_code": "NATIVE_CS", "targeting_eligible": True,
         "flowbundle_volume": 80.0, "residual": 40.0, "distance_km": 25.0},
    ]
    components = [
        {"component": "WORK_E_C", "family": "WORK",
         "target_status": "ACTIVE_COMPONENT_DIST_TARGET",
         "l1_distance_half": 0.2, "rmse_share": 0.1,
         "mean_delta_model_minus_target": 2.0},
        {"component": "SERV_E_C", "family": "SERVICE",
         "target_status": "ACTIVE_COMPONENT_DIST_TARGET",
         "l1_distance_half": 0.3, "rmse_share": 0.1,
         "mean_delta_model_minus_target": 1.0},
    ]
    result = build_td_targeting(fb, components, _cfg())
    assert set(result["active_components"]) == {"WORK_E_C", "SERV_E_C"}
    assert result["family_pressure"]["WORK"]["evidence_mean_distance_km"] == pytest.approx(12.0)


class Matrix:
    def __init__(self, values):
        self.values = values
    def GetValues(self):
        return self.values


class Matrices:
    def __init__(self, mapping):
        self.mapping = dict(mapping)
    def ItemByKey(self, key):
        return self.mapping[int(key)]
    def GetMultiAttValues(self, attr, *args):
        attr = str(attr).upper()
        if attr == "NO":
            return [(i + 1, no) for i, no in enumerate(self.mapping)]
        if attr == "CODE":
            codes = {9697: "R1_OSRM_DIST_KM", 9871: "TTC", 9872: "TT0"}
            return [(i + 1, codes.get(no, "")) for i, no in enumerate(self.mapping)]
        raise KeyError(attr)


class Zones:
    def GetMultiAttValues(self, name, *args):
        assert str(name).upper() == "NO"
        return [(1, 10), (2, 30)]


def test_required_and_optional_skim_read_is_read_only_and_explicit():
    visum = SimpleNamespace(Net=SimpleNamespace(
        Matrices=Matrices({
            9697: Matrix([[0.0, 12.5], [12.5, 0.0]]),
            9871: Matrix([[0.0, 15.0], [15.0, 0.0]]),
            9872: Matrix([[0.0, 10.0], [10.0, 0.0]]),
        }), Zones=Zones()))
    distance = read_distance_authority(visum)
    assert distance.value(10, 30) == pytest.approx(12.5)
    optional = read_optional_skim_authority(
        visum, ["NATIVE_CW"], ["TTC", "TT0", "IMP"],
        {"NATIVE_CW": {"TTC": 9871, "TT0": 9872}})
    assert optional.status == "PASS_WITH_OPTIONAL_GAPS"
    assert optional.value("NATIVE_CW", "TTC", 10, 30) == pytest.approx(15.0)
    assert optional.value("NATIVE_CW", "IMP", 10, 30) is None
    summary = optional.to_summary()
    assert summary["calculation_performed"] is False
    assert summary["model_modified"] is False


def test_shadow_classifier_never_becomes_actuator():
    class Skims:
        def value(self, dseg, code, origin, destination):
            values = {"TT0": 10.0, "TTC": 14.0, "AD1": 0.0, "IMP": 14.0}
            return values.get(code)
    rows = classify_shadow_rows([
        {"profile_id": "P", "dseg_code": "NATIVE_CW", "origin": 1,
         "destination": 2, "flowbundle_volume": 50.0, "residual": 10.0,
         "targeting_eligible": True}], Skims())
    assert rows[0]["shadow_class"] == "LIKELY_SUPPLY_OR_ROUTE_CHOICE_REVIEW"
    assert rows[0]["actuator"] is False
    assert rows[0]["objective_or_acceptance_term"] is False


class _Obj:
    def __init__(self, **attrs):
        self.attrs = attrs
    def AttValue(self, name):
        return self.attrs[str(name).upper()]


class _Collection:
    def __init__(self, rows):
        self.rows = list(rows)
    def GetAll(self):
        return list(self.rows)


class _Links:
    def __init__(self, link):
        self.link = link
    def ItemByKey(self, *args):
        assert len(args) == 2
        return self.link


class _FlowBundle:
    def __init__(self, matrix):
        self.matrix = matrix
        self.clear_calls = 0
        self.DemandSegments = None
        self.methods = []
    def Clear(self):
        self.clear_calls += 1
    def CreateCondition(self, *args):
        self.methods.append(("CreateCondition", len(args)))
    def ExecuteCurrentConditions(self):
        self.methods.append(("ExecuteCurrentConditions", 0))
    def GetOrCreateFlowBundleMatrix(self, arg):
        self.methods.append(("GetOrCreateFlowBundleMatrix", type(arg).__name__))
        return self.matrix


def test_flowbundle_uses_pinned_contract_without_probe_calls():
    link = _Obj(NO=77, FROMNODENO=1, TONODENO=2)
    dseg = _Obj(CODE="NATIVE_CW")
    flowbundle = _FlowBundle(Matrix([[0.0, 80.0], [20.0, 0.0]]))
    visum = SimpleNamespace(Net=SimpleNamespace(
        Links=_Links(link), DemandSegments=_Collection([dseg]),
        FlowBundle=flowbundle))
    cfg = {
        "com_resilience": {"max_attempts": 1},
        "path_export_dsegs": ["NATIVE_CW"],
        "demand_evidence_targeting": {"flowbundle": {
            "target_dsegs": ["NATIVE_CW"],
            "max_profiles": 5, "min_profile_geh": 10.0,
            "min_profile_abs_residual": 100.0, "min_od_volume": 0.01,
            "max_od_rows_per_profile": 10, "retained_volume_coverage": 0.9,
            "minimum_profile_coverage": 0.7,
            "demand_segment_mode": "code",
            "execution_method": "condition_current",
            "condition_set_mode": "none",
            "matrix_argument_mode": "object",
            "flowbundle_object_mode": "NET_FLOWBUNDLE",
            "link_item_key_mode": "TWO_KEY_FROM_TO",
        }},
    }
    profiles = [{
        "countlocation_no": 1001, "role": "CALIBRATION",
        "primary_family": "CW", "observed": 1000.0, "model": 500.0,
        "geh": 20.0, "link_no": 77, "from_node_no": 1, "to_node_no": 2,
    }]
    result = FlowBundleAdapter(visum, cfg).extract_snapshot(
        profiles, "STATE_HASH", [10, 30],
        distance_lookup=lambda o, d: 12.5 if o != d else 0.0)
    assert result.status == "ACTIVE"
    assert flowbundle.methods == [
        ("CreateCondition", 6),
        ("ExecuteCurrentConditions", 0),
        ("GetOrCreateFlowBundleMatrix", "_Obj"),
    ]
