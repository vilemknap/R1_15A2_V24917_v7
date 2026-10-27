# -*- coding: utf-8 -*-
"""Regression gate for the live PERF2 launcher/adapter constructor API."""
from __future__ import annotations

import inspect

from r1_15a2_trial_adapter_v24915p1 import VisumAdapter as ParentAdapter
from r1_15a2_trial_adapter_v24915p2 import VisumAdapter as Perf2Adapter


def test_perf2_constructor_preserves_parent_control_argument():
    parent = inspect.signature(ParentAdapter.__init__)
    child = inspect.signature(Perf2Adapter.__init__)
    assert "control" in parent.parameters
    assert "control" in child.parameters
    assert child.parameters["control"].default is None


def test_perf2_constructor_accepts_launcher_positional_arity():
    sig = inspect.signature(Perf2Adapter.__init__)
    # Binding reproduces the live launcher expression:
    # VisumAdapter(visum, cfg, control)
    sig.bind(object(), object(), {}, object())


def test_perf2_constructor_forwards_control_to_parent(monkeypatch):
    import r1_15a2_trial_adapter_v24915p2 as module

    calls = {}
    sentinel_telemetry = object()

    def fake_parent_init(self, visum, cfg, control=None):
        calls["visum"] = visum
        calls["cfg"] = cfg
        calls["control"] = control
        self.telemetry = sentinel_telemetry

    class FakeManager:
        def __init__(self, cfg, telemetry=None):
            calls["manager_cfg"] = cfg
            calls["manager_telemetry"] = telemetry

    monkeypatch.setattr(module._PERF1, "__init__", fake_parent_init)
    monkeypatch.setattr(module, "CandidateReadbackManager", FakeManager)

    visum = object()
    cfg = {"performance": {}}
    control = object()
    module.VisumAdapter(visum, cfg, control)

    assert calls["visum"] is visum
    assert calls["cfg"] is cfg
    assert calls["control"] is control
    assert calls["manager_cfg"] is cfg
    assert calls["manager_telemetry"] is sentinel_telemetry
