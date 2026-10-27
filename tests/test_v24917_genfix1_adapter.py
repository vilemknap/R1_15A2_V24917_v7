"""GENFIX1 integration: full reads, uncached parent checks, and entry point."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_v17_full_read_uses_strict_snapshot(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as a17
    adapter = a17.VisumAdapter.__new__(a17.VisumAdapter)
    events = []
    monkeypatch.setattr(adapter, "_sync_readback_telemetry", lambda: None)
    monkeypatch.setattr(adapter, "_record_snapshot_event", lambda *a, **k: events.append((a, k)))
    expected = {"state_hash": "exact", "generation_values": {"ADD_PROD_W": {"1": 1.0}}}
    calls = []
    monkeypatch.setattr(a17.snapshot_reads, "strict_snapshot", lambda ad: calls.append(ad) or expected)
    assert adapter.legacy_snapshot_from_live_visum() is expected
    assert calls == [adapter]
    assert adapter.last_perf2c_snapshot_parity["unsafe_legacy_fallback"] is False
    assert adapter.last_perf2c_snapshot_parity["transient_read_errors_use_defaults"] is False
    assert events[-1][0] == ("V24917_STRICT_FULL_SNAPSHOT",)


def test_generation_guard_bypasses_candidate_and_penalty_caches(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as a17
    adapter = a17.VisumAdapter.__new__(a17.VisumAdapter)
    adapter.visum = object()
    payload = {"state_hash": "live", "matrix_hash": "changed-matrix"}
    before = copy.deepcopy(payload)
    monkeypatch.setattr(adapter, "legacy_snapshot_from_live_visum", lambda: payload)
    monkeypatch.setattr(adapter, "snapshot", lambda: pytest.fail("Candidate bundle must not be consulted"))
    monkeypatch.setattr(a17.izpen, "active", lambda: True)
    monkeypatch.setattr(a17.izpen, "extend_snapshot", lambda *a: pytest.fail("Penalty cache must not be consulted"))
    monkeypatch.setattr(a17.izpen, "STATE", {"zones": [611], "base": np.eye(2)})
    monkeypatch.setattr(a17.izpen, "read_penalty", lambda v: np.array([2.5]))
    result = adapter.generation_guard_snapshot()
    assert result[a17.izpen.SNAPSHOT_KEY] == {"611": 2.5}
    assert result[a17.izpen.BASE_KEY] == a17.izpen.base_sha(np.eye(2))
    assert payload == before


def test_generation_guard_without_iz_preserves_snapshot_schema(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as a17
    adapter = a17.VisumAdapter.__new__(a17.VisumAdapter)
    payload = {"state_hash": "live"}
    monkeypatch.setattr(adapter, "legacy_snapshot_from_live_visum", lambda: payload)
    monkeypatch.setattr(a17.izpen, "active", lambda: False)
    assert adapter.generation_guard_snapshot() is payload


def _launcher():
    spec = importlib.util.spec_from_file_location("genfix1_test_launcher", ROOT / "01_SPUSTIT_V24917_GENFIX1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_genfix1_launcher_preserves_preflight_entry_and_injected_session(monkeypatch):
    launcher = _launcher()
    parent = SimpleNamespace(main=lambda: "completed")
    live = object()
    monkeypatch.setattr(launcher, "load_parent", lambda: parent)
    launcher.Visum = live
    assert launcher.main() == "completed"
    assert parent.Visum is live and parent.COM is None
    assert launcher.PARENT_LAUNCHER == "01_SPUSTIT_V24917_PREFLIGHTIOFIX1.py"


def test_genfix1_launcher_supports_com_injection(monkeypatch):
    launcher = _launcher()
    parent = SimpleNamespace(main=lambda: "completed")
    live = object()
    monkeypatch.setattr(launcher, "load_parent", lambda: parent)
    launcher.COM = live
    assert launcher.main() == "completed"
    assert parent.COM is live and parent.Visum is None


def test_genfix1_launcher_without_visum_fails_before_loading_parent(monkeypatch):
    launcher = _launcher()
    monkeypatch.setattr(launcher, "load_parent", lambda: pytest.fail("No model was provided"))
    with pytest.raises(RuntimeError, match="NO_INJECTED_VISUM"):
        launcher.main()
