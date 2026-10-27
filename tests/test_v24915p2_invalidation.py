# -*- coding: utf-8 -*-
"""Prove invalidation occurs before every PERF2 side effect."""
from __future__ import annotations

import copy

import pytest

import r1_15a2_trial_adapter_v24915p2 as p2
from r1_15a2_candidate_readback_bundle_v24915p2 import CandidateReadbackManager
from r1_15a2_supply import canonical_hash


def _cfg():
    return {
        "performance": {
            "v24915_perf2_candidate_readback_bundle": {
                "enabled": True,
                "shadow_parity_mode": True,
                "fallback_to_legacy": True,
                "require_exact_snapshot_parity": True,
            },
            "v24915_perf1": {"phase_specific_procseq": {"enabled": False}},
        }
    }


def _snapshot():
    result = {
        "addval1": {"1:1:2": 0.0},
        "addval_hash": "1" * 64,
        "fixed_link_hash": "2" * 64,
        "matrices": [{"matrix_no": 1, "rows": 1, "cols": 1, "sha256_float64_le": "3" * 64}],
        "matrix_hash": "4" * 64,
        "dseg_map": {"C": 1},
        "dseg_hash": "5" * 64,
        "generation_values": {"A": {"1": 1.0}},
        "generation_hash": "6" * 64,
        "td_values": [{"component": "WORK", "current_b": 0.0, "current_c": -0.1}],
        "td_hash": "7" * 64,
        "operations_hash": "8" * 64,
    }
    result["state_hash"] = canonical_hash(result)
    return result


class BareAdapter(p2.VisumAdapter):
    def __init__(self):
        self.cfg = _cfg()
        self.telemetry = None
        self.readback_manager = CandidateReadbackManager(
            self.cfg, visum_session_token="S", run_token="R")


def _prime(adapter: BareAdapter):
    snap = _snapshot()
    adapter.begin_candidate_readback_context(
        snap["state_hash"], "GENERATION", "b" * 64)
    adapter.readback_manager.mark_assignment_started(reason="TEST")
    adapter.readback_manager.mark_assignment_completed({"gap": 0.0})
    adapter.readback_manager.capture(snapshot_factory=lambda: copy.deepcopy(snap))
    assert adapter.readback_manager.current is not None
    return snap, adapter.readback_manager.mutation_epoch


@pytest.mark.parametrize(
    "method_name,parent_name,args,expected_reason",
    [
        ("apply_generation", "apply_generation", ({}, 1.0, "folder"), "GENERATION_CANDIDATE_WRITE"),
        ("apply_td", "apply_td", ([],), "TD_CANDIDATE_WRITE"),
        ("apply_supply", "apply_supply", ({}, {}, "folder"), "SUPPLY_CANDIDATE_WRITE"),
        ("restore", "restore", ({}, {}), "LOADVERSION"),
    ],
)
def test_candidate_writes_invalidate_before_parent_side_effect(
        monkeypatch, method_name, parent_name, args, expected_reason):
    adapter = BareAdapter()
    _snap, old_epoch = _prime(adapter)
    observed = {}

    def parent_side_effect(self, *unused_args, **unused_kwargs):
        observed["current"] = self.readback_manager.current
        observed["epoch"] = self.readback_manager.mutation_epoch
        return "OK"

    monkeypatch.setattr(p2._PERF1, parent_name, parent_side_effect)
    result = getattr(adapter, method_name)(*args)
    assert result == "OK"
    assert observed["current"] is None
    assert observed["epoch"] == old_epoch + 1
    assert adapter.readback_manager.telemetry_counts["BUNDLE_INVALIDATE"] >= 1


def test_procedure_execute_invalidates_before_parent_execution(monkeypatch, tmp_path):
    adapter = BareAdapter()
    _snap, old_epoch = _prime(adapter)
    observed = {}

    def parent_execute(self, folder, block, plan):
        observed["current"] = self.readback_manager.current
        observed["in_progress"] = self.readback_manager.assignment_in_progress
        observed["epoch"] = self.readback_manager.mutation_epoch
        return 1.0e-5

    monkeypatch.setattr(p2._PERF1, "_execute_perf1_plan", parent_execute)
    gap = adapter._execute_perf1_plan(tmp_path, "GENERATION", {"mode": "TEST"})
    assert gap == 1.0e-5
    assert observed == {"current": None, "in_progress": True, "epoch": old_epoch + 1}
    assert adapter.readback_manager.assignment_completed is True
    assert adapter.readback_manager.assignment_in_progress is False


def test_failed_assignment_never_allows_bundle_capture(monkeypatch, tmp_path):
    adapter = BareAdapter()
    _prime(adapter)

    def parent_execute(self, folder, block, plan):
        assert self.readback_manager.current is None
        raise RuntimeError("VISUM EXECUTE FAILED")

    monkeypatch.setattr(p2._PERF1, "_execute_perf1_plan", parent_execute)
    with pytest.raises(RuntimeError, match="VISUM EXECUTE FAILED"):
        adapter._execute_perf1_plan(tmp_path, "GENERATION", {"mode": "TEST"})
    assert adapter.readback_manager.current is None
    assert adapter.readback_manager.assignment_completed is False
    assert adapter.readback_manager.can_capture() is False


def test_live_diagnostics_invalidates_before_helper_and_preserves_reference(monkeypatch, tmp_path):
    adapter = BareAdapter()
    _prime(adapter)
    observed = {}
    payload = {"d12": {"rows": [1]}, "d11": {"summary": {"ok": True}}, "signals": {}}

    def parent_diagnostics(self, folder, label="CURRENT"):
        observed["current"] = self.readback_manager.current
        observed["epoch"] = self.readback_manager.mutation_epoch
        return copy.deepcopy(payload)

    monkeypatch.setattr(p2._PERF1, "diagnostics", parent_diagnostics)
    result = adapter.diagnostics(tmp_path, "AFTER")
    assert result == payload
    assert observed["current"] is None
    assert adapter.readback_manager.pending_diagnostics_reference["diagnostics_payload_hash"] == canonical_hash(payload)
