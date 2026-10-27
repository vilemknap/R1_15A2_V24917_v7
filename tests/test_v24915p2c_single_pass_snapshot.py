# -*- coding: utf-8 -*-
"""Exact parity, read-count, and fail-safe tests for PERF2C snapshot V2."""
from __future__ import annotations

from collections import Counter
import copy
from pathlib import Path
from types import MethodType

import pytest

from conftest import FakeCollection
from test_supply_visum_v22 import state_visum, small_cfg
import r1_15a2_supply_visum as legacy_module
import r1_15a2_trial_adapter_v24915p2c as adapter_module
from r1_15a2_single_pass_snapshot_v24915p2c import single_pass_exact_snapshot


class CountingCollection(FakeCollection):
    def __init__(self, items, keys=None):
        super().__init__(items, keys)
        self.get_all_calls = 0
        self.item_by_key_calls = 0

    @property
    def GetAll(self):
        self.get_all_calls += 1
        return tuple(self.items)

    def ItemByKey(self, key):
        self.item_by_key_calls += 1
        return super().ItemByKey(key)


def _instrument_visum():
    visum = state_visum()
    counts = {
        "operation_attributes": Counter(),
        "dseg_attributes": Counter(),
        "matrix_attributes": Counter(),
        "matrix_getvalues": Counter(),
        "zone_getmulti": Counter(),
    }

    operations = list(visum.Procedures.Operations.items)
    for index, operation in enumerate(operations, 1):
        original = operation.AttValue

        def counted(name, _original=original, _index=index):
            counts["operation_attributes"][(int(_index), str(name).upper())] += 1
            return _original(name)

        object.__setattr__(operation, "AttValue", MethodType(lambda self, name, _fn=counted: _fn(name), operation))
    visum.Procedures.Operations = CountingCollection(operations)

    dsegs = list(visum.Net.DemandSegments.items)
    for index, dseg in enumerate(dsegs, 1):
        original = dseg.AttValue

        def counted(name, _original=original, _index=index):
            counts["dseg_attributes"][(int(_index), str(name).upper())] += 1
            return _original(name)

        object.__setattr__(dseg, "AttValue", MethodType(lambda self, name, _fn=counted: _fn(name), dseg))
    visum.Net.DemandSegments = CountingCollection(dsegs)

    matrices = list(visum.Net.Matrices.items)
    matrix_keys = {}
    for matrix in matrices:
        matrix_no = int(matrix.AttValue("NO"))
        matrix_keys[matrix_no] = matrix
        original_att = matrix.AttValue
        original_values = matrix.GetValues

        def counted_att(name, _original=original_att, _no=matrix_no):
            counts["matrix_attributes"][(int(_no), str(name).upper())] += 1
            return _original(name)

        def counted_values(_original=original_values, _no=matrix_no):
            counts["matrix_getvalues"][int(_no)] += 1
            return _original()

        object.__setattr__(matrix, "AttValue", MethodType(lambda self, name, _fn=counted_att: _fn(name), matrix))
        object.__setattr__(matrix, "GetValues", MethodType(lambda self, _fn=counted_values: _fn(), matrix))
    visum.Net.Matrices = CountingCollection(matrices, matrix_keys)

    original_zone_multi = visum.Net.Zones.GetMultiAttValues

    def counted_zone_multi(attribute):
        counts["zone_getmulti"][str(attribute).upper()] += 1
        return original_zone_multi(attribute)

    object.__setattr__(visum.Net.Zones, "GetMultiAttValues", MethodType(lambda self, attribute, _fn=counted_zone_multi: _fn(attribute), visum.Net.Zones))
    return visum, counts


def _runtime_cfg(tmp_path: Path):
    cfg = copy.deepcopy(small_cfg())
    cfg.update({
        "apply": False,
        "production_apply": False,
        "trial_calibration": {"enabled": True},
        "performance": {
            "persistent_path_cache": {"enabled": False},
            "v24915_perf2_candidate_readback_bundle": {
                "enabled": True,
                "shadow_parity_mode": True,
                "fallback_to_legacy": True,
                "require_exact_snapshot_parity": True,
            },
            "v24915_perf2c_single_pass_snapshot": {
                "enabled": True,
                "shadow_parity_once": True,
                "fallback_to_legacy": True,
            },
        },
        "runtime_persistent_path_cache_root": str(tmp_path / "cache"),
    })
    return cfg


def _sum_counter(counter, attribute):
    attribute = attribute.upper()
    return sum(value for (_key, name), value in counter.items() if name == attribute)


def test_single_pass_snapshot_is_exact_and_removes_only_proven_redundant_reads():
    legacy_visum, legacy_counts = _instrument_visum()
    optimized_visum, optimized_counts = _instrument_visum()
    cfg = small_cfg()

    legacy_adapter = legacy_module.VisumAdapter(legacy_visum, copy.deepcopy(cfg))
    optimized_adapter = legacy_module.VisumAdapter(optimized_visum, copy.deepcopy(cfg))

    legacy = legacy_adapter.snapshot()
    optimized = single_pass_exact_snapshot(optimized_adapter)

    assert optimized == legacy
    assert optimized["state_hash"] == legacy["state_hash"]
    assert sorted(optimized) == sorted(legacy)

    # Matrix values remain full and exact: one GetValues per matrix in both.
    assert sum(legacy_counts["matrix_getvalues"].values()) == len(legacy["matrices"])
    assert sum(optimized_counts["matrix_getvalues"].values()) == len(optimized["matrices"])

    # Legacy traverses Operations separately for TD and inventory; PERF2C once.
    assert legacy_visum.Procedures.Operations.get_all_calls == 2
    assert optimized_visum.Procedures.Operations.get_all_calls == 1
    for attribute in ("OPERATIONTYPE", "ACTIVE", "COMMENT"):
        assert _sum_counter(
            optimized_counts["operation_attributes"], attribute
        ) < _sum_counter(legacy_counts["operation_attributes"], attribute)

    # Snapshot does not consume DSeg NAME/MODE or matrix CODE/SUM. PERF2C stops
    # reading those unused values but preserves CODE and ODMatrix.NO identity.
    assert _sum_counter(legacy_counts["dseg_attributes"], "NAME") > 0
    assert _sum_counter(legacy_counts["dseg_attributes"], "MODE") > 0
    assert _sum_counter(optimized_counts["dseg_attributes"], "NAME") == 0
    assert _sum_counter(optimized_counts["dseg_attributes"], "MODE") == 0
    assert _sum_counter(legacy_counts["matrix_attributes"], "CODE") > 0
    assert _sum_counter(legacy_counts["matrix_attributes"], "SUM") > 0
    assert _sum_counter(optimized_counts["matrix_attributes"], "CODE") == 0
    assert _sum_counter(optimized_counts["matrix_attributes"], "SUM") == 0

    # Generation values are not weakened or cached across calls.
    assert optimized_counts["zone_getmulti"] == legacy_counts["zone_getmulti"]
    telemetry = optimized_adapter.last_perf2c_snapshot_telemetry
    assert telemetry["cross_call_cache"] is False
    assert telemetry["loader_calls"]["links"] == 1
    assert telemetry["loader_calls"]["dseg_bindings"] == 1
    assert telemetry["loader_calls"]["operation_records"] == 1
    assert telemetry["loader_calls"]["generation_values"] == 1
    assert telemetry["loader_calls"]["td_and_operations"] == 1


def test_per_call_context_does_not_reuse_live_state_across_snapshot_calls():
    visum, counts = _instrument_visum()
    adapter = legacy_module.VisumAdapter(visum, small_cfg())
    first = single_pass_exact_snapshot(adapter)
    matrix = visum.Net.Matrices.ItemByKey(9101)
    matrix.values[0, 1] += 5.0
    second = single_pass_exact_snapshot(adapter)
    assert first["matrix_hash"] != second["matrix_hash"]
    assert sum(counts["matrix_getvalues"].values()) == 2 * len(first["matrices"])


def test_adapter_first_call_shadow_parity_then_uses_single_pass(tmp_path):
    visum, _counts = _instrument_visum()
    adapter = adapter_module.VisumAdapter(visum, _runtime_cfg(tmp_path))
    first = adapter.legacy_snapshot_from_live_visum()
    assert adapter.last_perf2c_snapshot_parity["status"] == "EXACT_PARITY_PASS"
    second = adapter.legacy_snapshot_from_live_visum()
    assert second == first
    assert adapter._perf2c_runtime_disabled is False
    assert adapter.last_perf2c_snapshot_telemetry["cross_call_cache"] is False


def test_adapter_falls_back_permanently_when_optimized_read_fails(tmp_path, monkeypatch):
    visum, _counts = _instrument_visum()
    adapter = adapter_module.VisumAdapter(visum, _runtime_cfg(tmp_path))

    def fail(_adapter):
        raise RuntimeError("synthetic optimized failure")

    monkeypatch.setattr(adapter_module, "single_pass_exact_snapshot", fail)
    legacy = adapter.legacy_snapshot_from_live_visum()
    assert legacy["state_hash"]
    assert adapter._perf2c_runtime_disabled is True
    assert adapter.last_perf2c_snapshot_parity["status"] == "DISABLED_FALLBACK_TO_LEGACY"
    # A second call remains on untouched parent implementation; it does not
    # retry the failed optimized path.
    second = adapter.legacy_snapshot_from_live_visum()
    assert second == legacy


def test_adapter_parity_mismatch_returns_legacy_and_disables_optimization(tmp_path, monkeypatch):
    visum, _counts = _instrument_visum()
    adapter = adapter_module.VisumAdapter(visum, _runtime_cfg(tmp_path))
    original = adapter_module.single_pass_exact_snapshot

    def mismatch(instance):
        result = original(instance)
        result["state_hash"] = "0" * 64
        return result

    monkeypatch.setattr(adapter_module, "single_pass_exact_snapshot", mismatch)
    returned = adapter.legacy_snapshot_from_live_visum()
    assert returned["state_hash"] != "0" * 64
    assert adapter._perf2c_runtime_disabled is True
    assert adapter.last_perf2c_snapshot_parity["status"] == (
        "EXACT_PARITY_MISMATCH_FALLBACK_TO_LEGACY")


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0])
def test_single_pass_preserves_matrix_validity_gate(invalid):
    visum = state_visum()
    visum.Net.Matrices.ItemByKey(9101).values[0, 1] = invalid
    adapter = legacy_module.VisumAdapter(visum, small_cfg())
    with pytest.raises(RuntimeError):
        single_pass_exact_snapshot(adapter)

@pytest.mark.parametrize("mutation", [
    "ADDVAL1",
    "FIXED_LINK",
    "MATRIX",
    "GENERATION",
    "TD_PARAMETER",
    "OPERATION_RUNTIME_STATE",
    "DSEG_BINDING",
])
def test_exact_parity_is_preserved_across_each_semantic_state_domain(mutation):
    legacy_visum = state_visum()
    optimized_visum = state_visum()

    def apply(visum):
        if mutation == "ADDVAL1":
            visum.Net.Links.items[0].SetAttValue("ADDVAL1", 1.25)
        elif mutation == "FIXED_LINK":
            visum.Net.Links.items[0].SetAttValue("LENGTH", 2.5)
        elif mutation == "MATRIX":
            visum.Net.Matrices.ItemByKey(9101).values[0, 1] += 7.0
        elif mutation == "GENERATION":
            visum.Net.Zones.rows[0]["ADD_PROD_W"] = 1.75
        elif mutation == "TD_PARAMETER":
            params = visum.Procedures.Operations.items[1].TripDistributionParameters
            params.TripDistributionDStratParameters.ItemByKey(
                "1_WORK_E_C").SetAttValue("PARA_C", -0.25)
        elif mutation == "OPERATION_RUNTIME_STATE":
            # Change a non-TD operation so the full snapshot remains readable.
            visum.Procedures.Operations.items[-1].SetAttValue("ACTIVE", 0)
        elif mutation == "DSEG_BINDING":
            visum.Net.DemandSegments.items[0].ODMatrix = visum.Net.Matrices.ItemByKey(2)
        else:  # pragma: no cover
            raise AssertionError(mutation)

    apply(legacy_visum)
    apply(optimized_visum)
    legacy_adapter = legacy_module.VisumAdapter(legacy_visum, small_cfg())
    optimized_adapter = legacy_module.VisumAdapter(optimized_visum, small_cfg())
    legacy = legacy_adapter.snapshot()
    optimized = single_pass_exact_snapshot(optimized_adapter)
    assert optimized == legacy
    assert optimized["state_hash"] == legacy["state_hash"]
