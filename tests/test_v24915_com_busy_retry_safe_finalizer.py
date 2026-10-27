# -*- coding: utf-8 -*-
"""V24915 regression gates for long VISUM COM-busy periods and safe finalization."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import r1_15a2_com_compat as com
import r1_15a2_overnight_controller_v242 as coupled
from test_v245_workflow import setup_workflow


class RetryableCallRejected(Exception):
    def __init__(self, message="Volany odmitl volani."):
        super().__init__(com.RPC_E_CALL_REJECTED, message)
        self.hresult = com.RPC_E_CALL_REJECTED


class _TypeInfo:
    def GetTypeAttr(self):
        return SimpleNamespace(cFuncs=1)

    def GetFuncDesc(self, index):
        assert index == 0
        return SimpleNamespace(memid=17, invkind=1)

    def GetNames(self, memid):
        assert memid == 17
        return ("SaveToArray", "FirstObject", "LastObject")


class _OLE:
    def __init__(self, failures):
        self.failures = int(failures)
        self.calls = []

    def Invoke(self, memid, lcid, kind, as_method, first, last):
        self.calls.append((int(first), int(last)))
        if self.failures > 0:
            self.failures -= 1
            raise RetryableCallRejected()
        return [[1, 2, 3]]


def _policy(path_attempts=6, final_attempts=5):
    return {
        "enabled": True,
        "max_attempts": 2,
        "initial_delay_seconds": 0.0,
        "backoff_factor": 2.0,
        "max_delay_seconds": 0.0,
        "scoped_policies": {
            "bounded_path_export": {
                "enabled": True,
                "max_attempts": path_attempts,
                "max_elapsed_seconds": 120.0,
                "initial_delay_seconds": 0.0,
                "backoff_factor": 2.0,
                "max_delay_seconds": 0.0,
            },
            "final_verification": {
                "enabled": True,
                "max_attempts": final_attempts,
                "max_elapsed_seconds": 30.0,
                "initial_delay_seconds": 0.0,
                "backoff_factor": 2.0,
                "max_delay_seconds": 0.0,
            },
        },
    }


def test_bounded_path_export_uses_long_scope_but_exact_same_range():
    ole = _OLE(failures=4)
    events = []
    got = com.bounded_ole_invoke_with_retry(
        ole, 17, 1, 22786049, 22788096,
        retry_policy=_policy(path_attempts=6),
        label="REPRESENTATIVE_GEOMETRY",
        sleep_fn=lambda _: None,
        on_retry=events.append,
    )
    assert got == [[1, 2, 3]]
    assert ole.calls == [(22786049, 22788096)] * 5
    assert len(events) == 4
    assert all(not row["exhausted"] for row in events)


def test_generic_com_scope_does_not_inherit_long_path_budget():
    calls = []

    def rejected():
        calls.append(1)
        raise RetryableCallRejected()

    with pytest.raises(RetryableCallRejected):
        com.com_call_with_retry(
            rejected, retry_policy=_policy(path_attempts=8),
            sleep_fn=lambda _: None,
        )
    assert len(calls) == 2


def test_elapsed_lease_is_a_hard_bound_and_emits_terminal_event():
    now = [0.0]
    calls = []
    exhausted = []

    def clock():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    def rejected():
        calls.append(1)
        raise RetryableCallRejected()

    policy = {
        "enabled": True,
        "max_attempts": 100,
        "max_elapsed_seconds": 0.25,
        "initial_delay_seconds": 0.2,
        "backoff_factor": 1.0,
        "max_delay_seconds": 0.2,
    }
    with pytest.raises(RetryableCallRejected):
        com.com_call_with_retry(
            rejected, retry_policy=policy, sleep_fn=sleep,
            clock_fn=clock, on_exhausted=exhausted.append,
        )
    assert len(calls) == 2
    assert len(exhausted) == 1
    assert exhausted[0]["exhausted"] is True
    assert exhausted[0]["exhausted_by_elapsed"] is True
    assert exhausted[0]["next_attempt"] is None


def _run_primary_failure_with_final_snapshot_failures(tmp_path, monkeypatch, failures, *, nontransient=False):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["com_resilience"] = _policy(final_attempts=3)
    original_snapshot = adapter.snapshot
    state = {"remaining": 0}

    def snapshot():
        if state["remaining"] > 0:
            state["remaining"] -= 1
            if nontransient:
                raise RuntimeError("NONTRANSIENT_FINAL_SNAPSHOT_FAILURE")
            raise RetryableCallRejected()
        return original_snapshot()

    def fail_generation(*args, **kwargs):
        state["remaining"] = int(failures)
        raise RuntimeError("PRIMARY_GENERATION_FAILURE")

    adapter.snapshot = snapshot
    adapter.generation_design = fail_generation
    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "workflow", control, tmp_path,
    )
    return result


def test_final_snapshot_transient_retries_can_prove_accepted_state_intact(tmp_path, monkeypatch):
    result = _run_primary_failure_with_final_snapshot_failures(
        tmp_path, monkeypatch, failures=2,
    )
    assert result["status"] == "FAILED"
    assert result["error"] == "PRIMARY_GENERATION_FAILURE"
    assert result["live_matches_last_accepted"] is True
    assert result["safe_restart_from_latest_accepted_checkpoint"] is True
    assert result["manual_reopen_required"] is False
    assert len(result["final_verification_com_retry_events"]) == 2


def test_final_snapshot_transient_exhaustion_preserves_checkpoint_not_manual_reopen(tmp_path, monkeypatch):
    result = _run_primary_failure_with_final_snapshot_failures(
        tmp_path, monkeypatch, failures=20,
    )
    assert result["status"] == (
        "FAILED_TRANSIENT_COM_FINAL_VERIFICATION_UNAVAILABLE_"
        "RESTART_FROM_LATEST_ACCEPTED_CHECKPOINT"
    )
    assert result["primary_status_before_final_verification"] == "FAILED"
    assert result["live_matches_last_accepted"] is None
    assert result["final_verification_transient"] is True
    assert result["safe_restart_from_latest_accepted_checkpoint"] is True
    assert result["manual_reopen_required"] is False
    assert result["restart_checkpoint"] == result["latest_accepted_checkpoint"]
    assert result["final_verification_com_retry_events"][-1]["exhausted"] is True


def test_nontransient_final_snapshot_failure_remains_manual_reopen(tmp_path, monkeypatch):
    result = _run_primary_failure_with_final_snapshot_failures(
        tmp_path, monkeypatch, failures=1, nontransient=True,
    )
    assert result["status"] == "FAILED_FINAL_VERIFICATION_MANUAL_REOPEN_REQUIRED"
    assert result["manual_reopen_required"] is True
    assert result["safe_restart_from_latest_accepted_checkpoint"] is False
    assert result["final_verification_error_type"] == "RuntimeError"
