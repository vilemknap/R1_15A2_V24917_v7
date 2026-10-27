# -*- coding: utf-8 -*-
"""Fail-closed fault injection for CandidateReadbackBundle."""
from __future__ import annotations

from dataclasses import replace
import copy

import pytest

from r1_15a2_candidate_readback_bundle_v24915p2 import (
    CandidateReadbackManager, bundle_hash,
)
from r1_15a2_supply import SupplyContractError, canonical_hash


def _cfg(*, fallback=True):
    return {
        "performance": {
            "v24915_perf2_candidate_readback_bundle": {
                "enabled": True,
                "fallback_to_legacy": fallback,
                "require_exact_snapshot_parity": True,
            }
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


def _ready(*, profile_rows=False):
    manager = CandidateReadbackManager(
        _cfg(), visum_session_token="SESSION", run_token="RUN")
    manager.begin_candidate(
        accepted_parent_state_hash="a" * 64,
        block="GENERATION",
        candidate_write_signature="b" * 64,
        baseline_profile_rows=[{"profile_id": "P"}] if profile_rows else [])
    manager.mark_assignment_started(reason="TEST")
    manager.mark_assignment_completed({"gap": 0.0})
    return manager


@pytest.mark.parametrize("fault", [
    RuntimeError("RPC_E_CALL_REJECTED"),
    RuntimeError("MATRIX_GETVALUES_EXCEPTION"),
    RuntimeError("BULK_LINK_READ_EXCEPTION"),
    RuntimeError("GENERATION_READ_EXCEPTION"),
    RuntimeError("TD_SNAPSHOT_EXCEPTION"),
    RuntimeError("OPERATION_INVENTORY_EXCEPTION"),
])
def test_snapshot_fault_never_publishes_partial_bundle(fault):
    manager = _ready()
    with pytest.raises(RuntimeError, match=str(fault)):
        manager.capture(snapshot_factory=lambda: (_ for _ in ()).throw(fault))
    assert manager.current is None
    assert manager.readback_epoch == 0


def test_profile_fault_never_publishes_partial_bundle():
    manager = _ready(profile_rows=True)
    with pytest.raises(RuntimeError, match="PROFILE READ FAILED"):
        manager.capture(
            snapshot_factory=_snapshot,
            profile_factory=lambda rows: (_ for _ in ()).throw(RuntimeError("PROFILE READ FAILED")))
    assert manager.current is None
    assert manager.readback_epoch == 0


@pytest.mark.parametrize("key", [
    "state_hash", "matrix_hash", "generation_hash", "td_hash", "operations_hash",
])
def test_missing_required_snapshot_hash_is_fail_closed(key):
    manager = _ready()
    payload = _snapshot()
    payload.pop(key)
    with pytest.raises(SupplyContractError, match="SNAPSHOT_KEYS_MISSING"):
        manager.capture(snapshot_factory=lambda: payload)
    assert manager.current is None


def test_invalid_required_snapshot_hash_is_fail_closed():
    manager = _ready()
    payload = _snapshot()
    payload["matrix_hash"] = "short"
    with pytest.raises(SupplyContractError, match="SNAPSHOT_HASH_INVALID:matrix_hash"):
        manager.capture(snapshot_factory=lambda: payload)
    assert manager.current is None


def test_mutation_during_profile_capture_is_fail_closed():
    manager = _ready(profile_rows=True)

    def profile(_rows):
        manager.invalidate("CONCURRENT_COM_WRITE", mutation=True)
        return {"passes": True}

    with pytest.raises(SupplyContractError, match="MUTATED_DURING_CAPTURE"):
        manager.capture(snapshot_factory=_snapshot, profile_factory=profile)
    assert manager.current is None


def test_session_run_parent_candidate_block_and_epoch_are_all_bound():
    dimensions = (
        ("visum_session_token", "OTHER"),
        ("run_token", "OTHER"),
        ("mutation_epoch", 999),
        ("assignment_epoch", 999),
    )
    for attr, value in dimensions:
        manager = _ready()
        manager.capture(snapshot_factory=_snapshot)
        setattr(manager, attr, value)
        with pytest.raises(SupplyContractError, match="BUNDLE_NOT_CURRENT"):
            manager.require_current()

    for field, value in (
        ("accepted_parent_state_hash", "c" * 64),
        ("candidate_write_signature", "d" * 64),
        ("block", "TD_FINECDF"),
    ):
        manager = _ready()
        manager.capture(snapshot_factory=_snapshot)
        manager.context[field] = value
        with pytest.raises(SupplyContractError, match="BUNDLE_NOT_CURRENT"):
            manager.require_current()


def test_payload_tamper_is_detected_even_if_dataclass_is_frozen():
    manager = _ready()
    bundle = manager.capture(snapshot_factory=_snapshot)
    bundle.semantic_snapshot_payload["addval1"]["1:1:2"] = 999.0
    assert bundle.payload_hash != bundle_hash(bundle)
    with pytest.raises(SupplyContractError, match="BUNDLE_NOT_CURRENT"):
        manager.require_current()


def test_mark_assignment_failed_clears_authority_and_blocks_capture():
    manager = _ready()
    manager.mark_assignment_failed("RPC_E_CALL_REJECTED")
    assert manager.current is None
    assert manager.can_capture() is False
    with pytest.raises(SupplyContractError, match="CAPTURE_NOT_READY"):
        manager.capture(snapshot_factory=_snapshot)


def test_diagnostics_reference_is_cryptographically_bound():
    manager = _ready()
    manager.capture(snapshot_factory=_snapshot)
    diagnostics = {"d12": {"rows": [1]}, "d11": {"x": 2}, "signals": {"y": 3}}
    manager.attach_diagnostics(diagnostics)
    current = manager.require_current()
    assert current.diagnostics_reference["diagnostics_payload_hash"] == canonical_hash(diagnostics)
    assert current.diagnostics_reference["d12_hash"] == canonical_hash(diagnostics["d12"])
    assert current.payload_hash == bundle_hash(current)
