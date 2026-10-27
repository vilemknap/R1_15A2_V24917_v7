# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import replace
import copy

import pytest

from r1_15a2_candidate_readback_bundle_v24915p2 import (
    CandidateReadbackManager, bundle_hash,
)
from r1_15a2_trial_adapter_v24915p2 import VisumAdapter
from r1_15a2_supply import SupplyContractError, canonical_hash


def _cfg(enabled=True):
    return {
        "performance": {
            "v24915_perf2_candidate_readback_bundle": {
                "enabled": enabled,
                "shadow_parity_mode": True,
                "fallback_to_legacy": True,
                "require_exact_snapshot_parity": True,
            }
        }
    }


def _snapshot(tag="A"):
    payload = {
        "addval1": {"1:1:2": 0.0},
        "addval_hash": canonical_hash({"1:1:2": 0.0}),
        "fixed_link_hash": canonical_hash([{"link_no": 1}]),
        "matrix_hash": canonical_hash([{"matrix_no": 1, "sha256_float64_le": tag}]),
        "matrices": [{"matrix_no": 1, "rows": 2, "cols": 2, "sha256_float64_le": tag}],
        "dseg_map": {"C": 1},
        "dseg_hash": canonical_hash({"C": 1}),
        "generation_hash": canonical_hash({"A": {"1": 1.0}}),
        "generation_values": {"A": {"1": 1.0}},
        "td_values": [{"component": "WORK", "current_b": 0.0, "current_c": -0.1}],
        "td_hash": canonical_hash([{"component": "WORK", "current_b": 0.0, "current_c": -0.1}]),
        "operations_hash": canonical_hash([{"no": 1, "active": 1}]),
    }
    payload["state_hash"] = canonical_hash(payload)
    return payload


def _ready_manager(snapshot=None, profile=None):
    manager = CandidateReadbackManager(
        _cfg(), visum_session_token="SESSION", run_token="RUN")
    parent = "a" * 64
    candidate = "b" * 64
    manager.begin_candidate(
        accepted_parent_state_hash=parent,
        block="GENERATION",
        candidate_write_signature=candidate,
        parameter_evidence={"rows": 1},
        baseline_profile_rows=[{"profile_id": "P"}] if profile is not None else [])
    manager.mark_assignment_started(reason="TEST_ASSIGNMENT", procedure_plan={"mode": "TEST"})
    manager.mark_assignment_completed({"gap": 1e-5})
    source = copy.deepcopy(snapshot or _snapshot())
    bundle = manager.capture(
        snapshot_factory=lambda: copy.deepcopy(source),
        profile_factory=(lambda _rows: copy.deepcopy(profile)) if profile is not None else None)
    return manager, source, bundle


def test_bundle_capture_and_repeated_consumers_are_exact():
    manager, source, bundle = _ready_manager()
    assert bundle.complete is True
    assert bundle.payload_hash == bundle_hash(bundle)
    assert manager.snapshot_from_current() == source
    assert manager.snapshot_from_current() == source
    assert manager.telemetry_counts["BUNDLE_CAPTURE_TOTAL"] == 1
    assert manager.telemetry_counts["SNAPSHOT_FROM_BUNDLE"] == 2


@pytest.mark.parametrize("reason", [
    "GENERATION_WRITE", "TD_WRITE", "ADDVAL_WRITE", "ROLLBACK_WRITE",
    "PROCEDURES_EXECUTE", "LOADVERSION",
])
def test_any_mutation_invalidates_current_bundle(reason):
    manager, _source, _bundle = _ready_manager()
    old_epoch = manager.mutation_epoch
    manager.invalidate(reason, mutation=True)
    assert manager.current is None
    assert manager.mutation_epoch == old_epoch + 1
    with pytest.raises(SupplyContractError, match="BUNDLE_NOT_CURRENT"):
        manager.require_current()


def test_context_mismatch_rejects_stale_bundle():
    manager, _source, _bundle = _ready_manager()
    manager.context["block"] = "TD_FINECDF"
    with pytest.raises(SupplyContractError, match="BUNDLE_NOT_CURRENT"):
        manager.require_current()


def test_assignment_epoch_mismatch_rejects_bundle():
    manager, _source, _bundle = _ready_manager()
    manager.assignment_epoch += 1
    with pytest.raises(SupplyContractError, match="BUNDLE_NOT_CURRENT"):
        manager.require_current()


def test_payload_tampering_rejects_bundle():
    manager, _source, bundle = _ready_manager()
    # Nested data is deliberately hash-checked even though the dataclass is frozen.
    bundle.semantic_snapshot_payload["matrix_hash"] = "tampered"
    with pytest.raises(SupplyContractError, match="BUNDLE_NOT_CURRENT"):
        manager.require_current()


def test_capture_exception_never_publishes_partial_bundle():
    manager = CandidateReadbackManager(_cfg())
    manager.begin_candidate(
        accepted_parent_state_hash="a" * 64,
        block="GENERATION",
        candidate_write_signature="b" * 64)
    manager.mark_assignment_started(reason="TEST")
    manager.mark_assignment_completed({"gap": 0.0})
    with pytest.raises(RuntimeError, match="boom"):
        manager.capture(snapshot_factory=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert manager.current is None


def test_mutation_during_capture_is_fail_closed():
    manager = CandidateReadbackManager(_cfg())
    manager.begin_candidate(
        accepted_parent_state_hash="a" * 64,
        block="GENERATION",
        candidate_write_signature="b" * 64)
    manager.mark_assignment_started(reason="TEST")
    manager.mark_assignment_completed({"gap": 0.0})
    def factory():
        manager.invalidate("CONCURRENT_MUTATION", mutation=True)
        return _snapshot()
    with pytest.raises(SupplyContractError, match="MUTATED_DURING_CAPTURE"):
        manager.capture(snapshot_factory=factory)
    assert manager.current is None


class HarnessAdapter(VisumAdapter):
    def __init__(self, snapshots):
        self.cfg = _cfg()
        self.telemetry = None
        self.readback_manager = CandidateReadbackManager(
            self.cfg, visum_session_token="S", run_token="R")
        self.snapshots = [copy.deepcopy(x) for x in snapshots]
        self.legacy_calls = 0
        self.profile_calls = 0

    def legacy_snapshot_from_live_visum(self):
        self.legacy_calls += 1
        index = min(self.legacy_calls - 1, len(self.snapshots) - 1)
        return copy.deepcopy(self.snapshots[index])

    def _profile_payload_factory(self, rows):
        self.profile_calls += 1
        return {"passes": True, "profiles": len(rows), "signature_hash": "c" * 64}


def test_adapter_reduces_legacy_snapshot_reads_without_semantic_change():
    source = _snapshot()
    adapter = HarnessAdapter([source])
    adapter.begin_candidate_readback_context(
        source["state_hash"], "GENERATION", "b" * 64,
        baseline_profile_rows=[{"profile_id": "P"}])
    adapter.readback_manager.mark_assignment_started(reason="TEST")
    adapter.readback_manager.mark_assignment_completed({"gap": 0.0})
    assert adapter.snapshot() == source
    assert adapter.snapshot() == source
    assert adapter.snapshot() == source
    assert adapter.legacy_calls == 1
    assert adapter.profile_calls == 1


def test_diagnostics_invalidation_forces_fresh_semantic_capture():
    a = _snapshot("A")
    b = _snapshot("B")
    adapter = HarnessAdapter([a, b])
    adapter.begin_candidate_readback_context(a["state_hash"], "GENERATION", "b" * 64)
    adapter.readback_manager.mark_assignment_started(reason="TEST")
    adapter.readback_manager.mark_assignment_completed({"gap": 0.0})
    assert adapter.snapshot() == a
    adapter.invalidate_candidate_readback("DIAGNOSTICS_WRITE", mutation=True)
    assert adapter.snapshot() == b
    assert adapter.legacy_calls == 2


def test_diagnostics_reference_is_epoch_bound_and_hash_checked():
    manager, source, bundle = _ready_manager()
    diag = {"d12": {"rows": [1]}, "d11": {"summary": {"x": 1}}, "signals": {"s": 1}}
    manager.attach_diagnostics(diag)
    current = manager.require_current()
    assert current.diagnostics_reference["diagnostics_payload_hash"] == canonical_hash(diag)
    assert current.payload_hash == bundle_hash(current)
    assert current.snapshot() == source


def test_profile_payload_is_stored_for_rollback_proof():
    profile = {"passes": True, "profiles": 498, "signature_hash": "d" * 64}
    manager, _source, bundle = _ready_manager(profile=profile)
    assert bundle.profile_volume_payload == profile
