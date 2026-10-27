# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import pytest

import r1_15a2_com_compat as com
from r1_15a2_com_busy_snapshot_hotfix_v24916 import activate, policy_payload
from r1_15a2_supply_visum import VisumAdapter as SupplyAdapter
from r1_15a2_trial_adapter_v24915p2c import VisumAdapter as Perf2cAdapter
from tests.test_supply_visum_v22 import small_cfg, state_visum


class Busy(RuntimeError):
    hresult = com.RPC_E_CALL_REJECTED


class TryLater(RuntimeError):
    hresult = com.RPC_E_SERVERCALL_RETRYLATER


class NetIntermittent:
    def __init__(self, inner, *, property_name="Links", times=2, exception_type=Busy):
        self.inner = inner
        self.property_name = property_name
        self.times = times
        self.exception_type = exception_type
        self.calls = 0

    def __getattr__(self, name):
        if name == self.property_name:
            self.calls += 1
            if self.calls <= self.times:
                raise self.exception_type("Volany odmitl volani.")
        return getattr(self.inner, name)


def cfg():
    result = copy.deepcopy(small_cfg())
    result["com_resilience"] = {
        "enabled": True,
        "max_attempts": 5,
        "initial_delay_seconds": 0.0,
        "backoff_factor": 1.0,
        "max_delay_seconds": 0.0,
        "max_elapsed_seconds": 10.0,
        "scoped_policies": {
            "startup_snapshot_read": {
                "max_attempts": 5,
                "initial_delay_seconds": 0.0,
                "max_delay_seconds": 0.0,
                "backoff_factor": 1.0,
                "max_elapsed_seconds": 10.0,
            }
        },
    }
    return result


def test_v24916_combusy_retry_bulk_links_transient_then_passes():
    activate()
    visum = state_visum()
    adapter = SupplyAdapter(visum, cfg())
    reference = adapter.read_links()
    proxy = NetIntermittent(visum.Net, property_name="Links", times=2)
    visum.Net = proxy
    actual = adapter.read_links()
    assert actual == reference
    assert proxy.calls >= 3
    assert adapter.r1_com_busy_read_retry_events[0]["label"] == "SUPPLY_VISUM_READ_LINKS"


def test_v24916_combusy_retry_preserves_legacy_snapshot_hashes():
    activate()
    visum = state_visum()
    adapter = SupplyAdapter(visum, cfg())
    reference = adapter.snapshot()
    proxy = NetIntermittent(
        visum.Net, property_name="Matrices", times=2, exception_type=TryLater
    )
    visum.Net = proxy
    actual = adapter.snapshot()
    assert actual == reference
    assert proxy.calls >= 3


def test_v24916_combusy_retry_preserves_perf2c_exact_shadow_parity():
    activate()
    visum = state_visum()
    runtime = cfg()
    runtime.update(
        {
            "apply": False,
            "production_apply": False,
            "trial_calibration": {"enabled": True},
            "performance": {
                "persistent_path_cache": {"enabled": False},
                "v24915_perf2c_single_pass_snapshot": {
                    "enabled": True,
                    "shadow_parity_once": True,
                    "fallback_to_legacy": True,
                },
            },
        }
    )
    adapter = Perf2cAdapter(visum, runtime)
    first = adapter.legacy_snapshot_from_live_visum()
    assert adapter.last_perf2c_snapshot_parity["status"] == "EXACT_PARITY_PASS"
    proxy = NetIntermittent(visum.Net, property_name="Matrices", times=1)
    visum.Net = proxy
    actual = adapter.legacy_snapshot_from_live_visum()
    assert actual == first
    assert adapter._perf2c_runtime_disabled is False
    assert any(
        event["label"] == "PERF2C_SINGLE_PASS_SNAPSHOT"
        for event in adapter.r1_com_busy_read_retry_events
    )


def test_v24916_combusy_nontransient_error_is_not_retried():
    activate()
    visum = state_visum()
    adapter = SupplyAdapter(visum, cfg())

    class Permanent(ValueError):
        def __init__(self, _message):
            super().__init__("PERMANENT_SCHEMA_ERROR")

    proxy = NetIntermittent(
        visum.Net, property_name="Links", times=50, exception_type=Permanent
    )
    visum.Net = proxy
    with pytest.raises(Permanent):
        adapter.read_links()
    assert proxy.calls == 1


def test_v24916_combusy_policy_is_read_only_and_bounded():
    payload = policy_payload()
    assert payload["execution"] == "READ_ONLY_TRANSIENT_COM_RPC_ONLY"
    assert payload["visum_writes_added"] is False
    assert payload["calibration_math_changed"] is False
    assert payload["default_retry"]["max_attempts"] == 64
    assert payload["default_retry"]["max_elapsed_seconds"] == 75.0
