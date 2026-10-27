from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "v2493_master_for_test",
    ROOT / "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
)
master = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(master)


def _cal_row(code, observed, model, weight=1.0):
    return {
        "role": "CALIBRATION",
        "countlocation_no": code,
        "observed": observed,
        "model": model,
        "profile_weight": weight,
    }


def test_weighted_mean_geh_is_explicit_and_legacy_default_is_preserved():
    rows = [_cal_row("A", 100.0, 121.0, 1.0), _cal_row("B", 400.0, 361.0, 3.0)]
    metrics = core.csd_metrics(rows)
    gehs = [core.geh(121.0, 100.0), core.geh(361.0, 400.0)]
    expected_geh = (gehs[0] + 3.0 * gehs[1]) / 4.0
    expected_geh2 = (gehs[0] ** 2 + 3.0 * gehs[1] ** 2) / 4.0
    assert metrics["objective_geh_mean_weighted"] == pytest.approx(expected_geh)
    assert metrics["objective_geh2_mean"] == pytest.approx(expected_geh2)
    assert core.csd_objective_value(metrics, {}) == pytest.approx(expected_geh2)
    cfg = {"csd_calibration_objective": {"metric": "WEIGHTED_MEAN_GEH"}}
    assert core.csd_objective_value(metrics, cfg) == pytest.approx(expected_geh)
    assert core.csd_objective_key(cfg) == "objective_geh_mean_weighted"


def test_profile_sums_are_labeled_diagnostic_not_unique_trip_totals():
    metrics = core.csd_metrics([_cal_row("A", 100.0, 90.0)])
    assert metrics["profile_sum_role"] == "DIAGNOSTIC_ONLY_PROFILE_PASSAGE_CHECKSUM"
    assert metrics["profile_sum_unique_trip_interpretation_allowed"] is False
    assert "not unique-trip" in metrics["profile_sum_note"]


def _long_summary(component, volume):
    return {
        "component": component,
        "conditioned_volume": volume,
        "total_volume": volume,
        "target_status": "NO_COMPONENT_TARGET",
    }


def _long_bins(component, first_share):
    return [
        {"component": component, "bin_low": 100.0, "bin_high": 110.0,
         "share_conditioned": first_share},
        {"component": component, "bin_low": 110.0, "bin_high": 120.0,
         "share_conditioned": 1.0 - first_share},
    ]


def test_global_long_mix_builds_one_calibratable_composite():
    components = [name for name, row in mb.COMPONENT_REGISTRY.items()
                  if row["family"] == "LONG"]
    summaries = []
    baselines = []
    total = 0.0
    first_numerator = 0.0
    for i, comp in enumerate(components, 1):
        volume = float(i * 100)
        share = 0.1 * i
        summaries.append(_long_summary(comp, volume))
        baselines.extend(_long_bins(comp, share))
        total += volume
        first_numerator += volume * share
    cfg = {
        "td": {
            "long_acceptance_mode": "GLOBAL_LONG_COMPOSITE",
            "component_policy": {"LONG": "AUTO"},
        }
    }
    authority = {
        "authority_id": "GLOBAL_LONG_TEST",
        "aggregate_cl_guard": {"bins": [
            {"bin_low": 100.0, "bin_high": 110.0, "target_share": 0.4},
            {"bin_low": 110.0, "bin_high": 120.0, "target_share": 0.6},
        ]},
        "component_targets": {},
    }
    signals = mb.build_td_signals(summaries, [], baselines, authority, cfg)
    composite = signals["LONG_COMPOSITE"]
    assert composite["calibratable"] is True
    assert composite["acceptance_role"] == "GLOBAL_LONG_MIX"
    assert composite["conditioned_volume"] == pytest.approx(total)
    first = next(row for row in composite["model_bins"] if row["bin_low"] == 100.0)
    assert first["model_share"] == pytest.approx(first_numerator / total)
    assert all(signals[c]["calibratable"] is False for c in components)


def test_long_native_components_collapse_to_global_acceptance_block():
    components = [name for name, row in mb.COMPONENT_REGISTRY.items()
                  if row["family"] == "LONG"]
    cfg = {"td": {"long_acceptance_mode": "GLOBAL_LONG_COMPOSITE"}}
    selected = mb.collapse_td_acceptance_components(
        ["WORK_E_C", *components, "SCHOOL", components[0]], cfg)
    assert selected == ["WORK_E_C", "LONG_COMPOSITE", "SCHOOL"]


def _metric_signal(value):
    return {
        "component": "LONG_COMPOSITE",
        "family": "LONG",
        "calibratable": True,
        "l1_half": value,
        "rmse_share": value,
        "mean_target": 150.0,
        "mean_delta": 150.0 * value,
        "conditioned_volume": 10000.0,
    }


def test_downstream_acceptance_uses_composite_not_missing_long_authorities():
    long_components = [name for name, row in mb.COMPONENT_REGISTRY.items()
                       if row["family"] == "LONG"]
    cfg = {
        "csd_calibration_objective": {"metric": "WEIGHTED_MEAN_GEH"},
        "td": {
            "long_acceptance_mode": "GLOBAL_LONG_COMPOSITE",
            "min_selected_component_relative_improvement": 0.005,
            "max_selected_component_relative_degradation": 0.0,
            "max_nonselected_component_objective_degradation": 0.05,
            "max_cal_geh_relative_degradation": 0.005,
            "max_global_idp_mean_degradation": 0.01,
            "max_global_idp_component_degradation": 0.05,
        },
        "max_new_geh20": 0,
        "max_new_geh30": 0,
        "max_protected_to_warn": 3,
        "max_protected_to_hard": 0,
        "protected_geh": 5.0,
        "protected_warn_geh": 10.0,
        "protected_hard_geh": 30.0,
    }
    d12 = [_cal_row("A", 100.0, 110.0)]
    before = {"LONG_COMPOSITE": _metric_signal(0.20)}
    after = {"LONG_COMPOSITE": _metric_signal(0.10)}
    result = master.td_acceptance_decision(
        d12, d12, {}, {}, before, after, long_components, cfg)
    assert result["accepted"] is True
    assert result["selected_components"] == ["LONG_COMPOSITE"]
    assert result["long_component_collapse"]["enabled"] is True
    assert "SELECTED_TD_COMPONENT_AUTHORITY_MISSING" not in result["reasons"]
    assert result["cal_csd_objective_metric"] == "WEIGHTED_MEAN_GEH"


class RetryableCallRejected(Exception):
    def __init__(self, message="Volany odmitl volani."):
        super().__init__(com.RPC_E_CALL_REJECTED, message)
        self.hresult = com.RPC_E_CALL_REJECTED


def test_transient_com_call_is_retried_with_bounded_policy():
    state = {"calls": 0}
    sleeps = []

    def operation():
        state["calls"] += 1
        if state["calls"] < 3:
            raise RetryableCallRejected()
        return "OK"

    result = com.com_call_with_retry(
        operation,
        retry_policy={"enabled": True, "max_attempts": 3,
                      "initial_delay_seconds": 0.01, "backoff_factor": 2.0,
                      "max_delay_seconds": 0.1},
        sleep_fn=sleeps.append,
    )
    assert result == "OK"
    assert state["calls"] == 3
    assert sleeps == pytest.approx([0.01, 0.02])


def test_nontransient_com_error_is_not_retried():
    state = {"calls": 0}

    def operation():
        state["calls"] += 1
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        com.com_call_with_retry(
            operation,
            retry_policy={"enabled": True, "max_attempts": 5},
            sleep_fn=lambda _x: None,
        )
    assert state["calls"] == 1


def test_signature_fallback_is_separate_from_retry():
    class OneArgumentCollection:
        def __init__(self):
            self.calls = []

        def GetMultiAttValues(self, *args):
            self.calls.append(args)
            if len(args) == 2:
                raise TypeError("legacy signature")
            return [(1, 10.0)]

    coll = OneArgumentCollection()
    assert com.get_multi_att_values(
        coll, "X", {"enabled": True, "max_attempts": 4}) == [(1, 10.0)]
    assert coll.calls == [("X", False), ("X",)]


def test_cached_zone_keys_avoid_requerying_zone_no_during_write():
    class Zones:
        def __init__(self):
            self.values = {101: 1.0, 102: 2.0}
            self.no_reads = 0

        def GetMultiAttValues(self, attr, active_only=False):
            if attr == "NO":
                self.no_reads += 1
                raise AssertionError("Zone.NO must not be re-read")
            return sorted(self.values.items())

        def SetMultiAttValues(self, attr, rows, active_only=False):
            self.values.update({int(k): float(v) for k, v in rows})

    zones = Zones()
    visum = type("V", (), {"Net": type("N", (), {"Zones": zones})()})()
    got = rt.write_zone_attr(
        visum, "ADD", [1, 2], [3.0, 4.0], zone_indices={1: 101, 2: 102},
        retry_policy={"enabled": True, "max_attempts": 2})
    assert got == [3.0, 4.0]
    assert zones.no_reads == 0


def test_helper_retries_only_transient_com_failure(tmp_path):
    script = tmp_path / "helper.py"
    script.write_text("Visum.step()\n", encoding="utf-8")

    class FakeVisum:
        def __init__(self):
            self.calls = 0

        def step(self):
            self.calls += 1
            if self.calls == 1:
                raise RetryableCallRejected()

    visum = FakeVisum()
    workspace = tmp_path / "workspace"
    stage_log = tmp_path / "stage.log"
    rt.run_helper(
        script, visum, "TEST", workspace, stage_log,
        {"enabled": True, "helper_retry_enabled": True, "max_attempts": 2,
         "initial_delay_seconds": 0.0, "max_delay_seconds": 0.0},
    )
    assert visum.calls == 2
    assert "RETRYABLE_COM" in stage_log.read_text(encoding="utf-8")
