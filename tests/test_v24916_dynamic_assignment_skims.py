from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import r1_15a2_dynamic_skim_v24916p2c as dyn
from r1_15a2_dynamic_skim_v24916p2c import (
    DynamicSkimEpoch, DynamicSkimManager, _weighted_pair,
    active_native_skim_positions,
)
from r1_15a2_finecdf_bridge_v24916 import (
    DynamicFamilyMetrics, NoDirectMatrixWriteTDAdapter, load_reference,
)
from r1_15a2_active_targeting_runtime_v24916p2c import (
    V24916_ACTIVE_SECTION, DEMAND_EVIDENCE_TARGETING,
)
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]


def test_weighted_family_distance_responds_to_congested_reroute_volume():
    # Toll path remains short, no-toll path is longer.  When saturated-network
    # assignment shifts volume to the no-toll family, the effective WORK skim
    # must increase; a static OSRM matrix cannot represent this response.
    short = np.array([[0.0, 10.0], [10.0, 0.0]])
    long = np.array([[0.0, 18.0], [18.0, 0.0]])
    mostly_short = _weighted_pair(short, long,
                                  np.array([[0.0, 90.0], [90.0, 0.0]]),
                                  np.array([[0.0, 10.0], [10.0, 0.0]]))
    mostly_long = _weighted_pair(short, long,
                                 np.array([[0.0, 20.0], [20.0, 0.0]]),
                                 np.array([[0.0, 80.0], [80.0, 0.0]]))
    assert mostly_short[0, 1] == pytest.approx(10.8)
    assert mostly_long[0, 1] == pytest.approx(16.4)
    assert mostly_long[0, 1] > mostly_short[0, 1]


def _v19_reference():
    cfg = json.loads((ROOT / "R1_15A2_CONFIG_V2_4_9_15_PERF2.json").read_text(encoding="utf-8"))
    fine = cfg["coupled_demand"]["finecdf_td"]
    ref, _path, _sha = load_reference(ROOT, fine)
    return ref


def test_dynamic_family_metrics_exactly_match_v19_when_all_family_skims_are_equal():
    """Only the distance authority may change; FineCDF math must not."""
    ref = _v19_reference()
    n = int(ref.CONFIG["expected_zone_count"])
    distance = np.linspace(0.1, 199.9, n * n, dtype=np.float64).reshape(n, n)
    # Share one immutable flow array across all component matrix numbers.  This
    # keeps the test small while giving positive conditioned mass to every target.
    flow = np.ones((n, n), dtype=np.float64)
    matrix_nos = sorted({int(no) for t in ref.TARGETS.values() for no in t["matrix_nos"]})
    matrices = {no: flow for no in matrix_nos}

    expected = ref.Metrics(distance).evaluate(matrices)
    epoch = SimpleNamespace(
        epoch=11,
        epoch_hash="PARITY_EPOCH",
        family_distance={"WORK": distance, "SERVICE": distance, "LONG": distance},
    )
    actual = DynamicFamilyMetrics(SimpleNamespace(dynamic_skim_epoch=epoch), ref).evaluate(matrices)

    numeric_arrays = ("shares", "bin_volumes", "fine_model_cdf", "residual")
    numeric_scalars = (
        "fine_cdf_rmse", "fine_cdf_mae", "fine_cdf_ks", "fine_cdf_mean_signed",
        "model_cdf_at_first_idp_node", "target_cdf_at_first_idp_node",
        "zero_distance_share_diagnostic", "intrazonal_zero_distance_share_diagnostic",
        "offdiagonal_zero_distance_share_diagnostic", "mean_model_km",
        "mean_exact_distance_km_diagnostic", "mean_target_km", "mean_delta_km",
        "mean_relative_error", "l1_half", "rmse_share", "objective",
        "conditioned_volume_diagnostic", "total_volume_diagnostic",
        "conditioned_share_diagnostic",
    )
    assert set(actual) == set(expected)
    for key in expected:
        for name in numeric_arrays:
            assert np.allclose(actual[key][name], expected[key][name], rtol=0.0, atol=1e-14), (key, name)
        for name in numeric_scalars:
            assert actual[key][name] == pytest.approx(expected[key][name], rel=0.0, abs=1e-14), (key, name)
        assert actual[key]["mean_basis"] == expected[key]["mean_basis"]
        assert actual[key]["fine_points_used"] == expected[key]["fine_points_used"]
        assert actual[key]["distance_authority"] == "DYNAMIC_ASSIGNMENT_DIS_KM"


def test_active_skim_authority_requires_exactly_six_configured_native_operations(monkeypatch):
    def rows(count):
        return [
            {"no": i + 1, "active": 1, "type": dyn.com.SKIMS_PRT, "object": object()}
            for i in range(count)
        ]
    monkeypatch.setattr(dyn.com, "operation_rows", lambda _visum: rows(5))
    with pytest.raises(SupplyContractError, match="EXPECTED_6_ACTIVE_PRT_SKIMS_FOUND_5"):
        active_native_skim_positions(object())
    monkeypatch.setattr(dyn.com, "operation_rows", lambda _visum: rows(6))
    skim, groups = active_native_skim_positions(object())
    assert skim == [1, 2, 3, 4, 5, 6]
    assert groups == []


def test_dynamic_skim_epoch_rejects_stale_assignment_epoch():
    adapter = SimpleNamespace(readback_manager=SimpleNamespace(assignment_epoch=9))
    manager = DynamicSkimManager(adapter)
    manager.current = DynamicSkimEpoch(
        schema="X", epoch=2, assignment_epoch=8, assignment_token="T",
        zone_order_sha256="Z", operation_positions=(31, 32, 33, 34, 35, 36),
        matrices_by_dseg={}, matrix_meta_by_dseg={}, family_distance={}, family_hashes={},
        epoch_hash="E",
    )
    with pytest.raises(SupplyContractError, match="STALE_ASSIGNMENT_EPOCH:8!=9"):
        manager.require_current()


def test_finecdf_dynamic_realization_plan_is_td_to_assignment_plus_all_six_skims_not_generation():
    b = NoDirectMatrixWriteTDAdapter.__new__(NoDirectMatrixWriteTDAdapter)
    b.dynamic_skim_enabled = True
    b.td_index = 6
    b.inventory = [
        {"index": 5, "type": 45, "active": 1, "is_group": False},  # TG: excluded
        {"index": 6, "type": 46, "active": 1, "is_group": False},  # TD
        {"index": 7, "type": 65, "active": 1, "is_group": False},  # realization script
        {"index": 17, "type": 101, "active": 1, "is_group": False},
        {"index": 18, "type": 101, "active": 1, "is_group": False},
        {"index": 20, "type": 101, "active": 1, "is_group": False},
        {"index": 21, "type": 65, "active": 1, "is_group": False},  # post-assignment GEH: excluded
        {"index": 22, "type": 75, "active": 1, "is_group": True},
        {"index": 31, "type": 103, "active": 1, "is_group": False},
        {"index": 32, "type": 103, "active": 1, "is_group": False},
        {"index": 33, "type": 103, "active": 1, "is_group": False},
        {"index": 34, "type": 103, "active": 1, "is_group": False},
        {"index": 35, "type": 103, "active": 1, "is_group": False},
        {"index": 36, "type": 103, "active": 1, "is_group": False},
    ]
    b.outer_adapter = SimpleNamespace(cfg={"supply": {"assignment_operations": [
        {"no": 17, "operation_type": 101},
        {"no": 18, "operation_type": 101},
        {"no": 20, "operation_type": 101},
    ]}})
    plan = b._dynamic_realization_plan()
    selected = set(plan["selected_operation_positions"])
    assert 5 not in selected
    assert 6 in selected and 7 in selected
    assert {17, 18, 20} <= selected
    assert 21 not in selected
    assert {31, 32, 33, 34, 35, 36} <= selected
    assert 22 in selected
    assert plan["dynamic_skim_operation_positions"] == [31, 32, 33, 34, 35, 36]


def test_runtime_contract_replaces_static_osrm_with_fresh_assignment_skims():
    assert V24916_ACTIVE_SECTION["dynamic_assignment_skim_enabled"] is True
    assert V24916_ACTIVE_SECTION["static_r1_osrm_dist_km_role"] == "REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION"
    assert V24916_ACTIVE_SECTION["dynamic_skim_refresh_policy"] == "EVERY_TD_FINECDF_EVALUATION_AND_EVERY_FRESH_ASSIGNMENT"
    skim = DEMAND_EVIDENCE_TARGETING["skim"]
    assert skim["automatic_calculation"] is True
    assert skim["distance_code"] == "DIS"
    assert skim["assignment_epoch_binding_required"] is True
    assert len(skim["required_native_dsegs"]) == 6
    assert DEMAND_EVIDENCE_TARGETING["td"]["finecdf_distance_authority"] == "DYNAMIC_ASSIGNMENT_DIS_KM"
    assert DEMAND_EVIDENCE_TARGETING["td"]["fresh_assignment_and_skims_per_finecdf_evaluation"] is True
