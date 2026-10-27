# -*- coding: utf-8 -*-
"""GENFIX1: parameter-only restoration must retain ownership of live demand.

These tests use separate parameter and assigned-demand states.  A cheap COM
parameter restore cannot repair the latter; the real rollback transaction must
execute and verify the parent recomputation before the block exits.
"""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import r1_15a2_step_search_v24917 as step
from test_v24917_step_search import harness, opts  # noqa: F401 (shared behavioral fixture)


@contextmanager
def _raises_contract_error(*, match):
    # Launcher tests deliberately reload runtime modules.  The guard and STEP1
    # may then retain different legitimate class objects with the same contract.
    # Assert the complete exception identity by module/name plus the error text,
    # rather than coupling the test to a collection-time Python class object.
    with pytest.raises(Exception, match=match) as caught:
        yield caught
    assert type(caught.value).__module__ == "r1_15a2_supply"
    assert type(caught.value).__name__ == "SupplyContractError"


def _contract_error(message):
    from r1_15a2_supply import SupplyContractError
    return SupplyContractError(message)


def _saved_result(harness):
    return json.loads((harness.folder / "GENERATION_BLOCK_RESULT.json").read_text(encoding="utf-8"))


def _assert_verified_parent(harness, trial_assignments):
    ad = harness.ad
    assert ad.g == ad.g0
    assert ad.vol_g == ad.g0
    assert ad.snapshot() == harness.state
    assert len(ad.assignments) == trial_assignments + 1
    assert sum("ROLLBACK" in path for path in ad.assignments) == 1
    assert ad.diags[-1] == "ROLLBACK"
    proof = json.loads((harness.folder / "ROLLBACK" / "ROLLBACK_VERIFICATION.json")
                       .read_text(encoding="utf-8"))
    assert proof["snapshot_equal"] and proof["diagnostic_equal"] and proof["passes"]


@pytest.mark.parametrize("next_preview", ["gate_exhausted", "no_rows", "exception"])
def test_rejected_assignment_then_unapplied_trial_recomputes_parent(harness, monkeypatch, next_preview):
    ad = harness.ad
    original_preview = ad.generation_preview
    pending_demand_seen = []

    def preview(context, scale):
        result = original_preview(context, scale)
        if not ad.assignments:
            return result
        # The first assigned trial was rejected by the real acceptance gate.
        # Parameters have already been reset, but demand is still that trial's.
        assert ad.g == ad.g0
        assert ad.vol_g != ad.g0
        pending_demand_seen.append(True)
        if next_preview == "exception":
            raise RuntimeError("preview failed after parameters-only restoration")
        if next_preview == "no_rows":
            return {"candidate_rows": []}
        result["summary"] = {"estimated_pa_delta_by_family": {
            "WORK": {"estimated_prod_delta": 1000.0, "estimated_att_delta": 1000.0,
                     "estimated_abs_gap": 50.0}}}
        return result

    monkeypatch.setattr(ad, "generation_preview", preview)
    if next_preview == "exception":
        with _raises_contract_error(match="NOT_A_PLATEAU:preview failed"):
            harness.run()
        rec = _saved_result(harness)
        assert rec["status"] == "FAILED"
        assert rec["failure_phase"] == "GENERATION_TRIAL"
        assert rec["attempts"][-1]["status"] == "FAILED"
        assert rec["search_complete"] is False and rec["stationarity_confirmed"] is False
    else:
        changed, state, diag, _value, rec = harness.run()
        assert changed is False
        assert state == harness.state and diag == harness.diag
        assert rec["status"] == "CONFIGURED_GENERATION_SEARCH_EXHAUSTED"
        expected = ("REJECTED_PRE_APPLY_GATE_ALL_SCALES" if next_preview == "gate_exhausted"
                    else "NO_PARAMETER_CANDIDATE")
        assert rec["attempts"][-1]["status"] == expected
    assert pending_demand_seen
    assert rec["attempts"][0]["status"] == "REJECTED"
    _assert_verified_parent(harness, trial_assignments=1)


@pytest.mark.parametrize("after_rejected_assignment", [False, True])
def test_partial_generation_write_is_owned_before_apply_returns(harness, monkeypatch,
                                                               after_rejected_assignment):
    ad = harness.ad
    original_apply = ad.apply_generation
    original_preview = ad.generation_preview
    calls = []

    def apply(context, scale, folder):
        calls.append(scale)
        if after_rejected_assignment and len(calls) == 1:
            return original_apply(context, scale, folder)
        rows = original_preview(context, scale)["candidate_rows"]
        for row in rows[:2]:
            ad.g[str(row["zone_no"])] = row["proposed"]
        assert ad.g != ad.g0
        raise RuntimeError("partial COM generation write failed")

    monkeypatch.setattr(ad, "apply_generation", apply)
    with _raises_contract_error(match="NOT_A_PLATEAU:partial COM generation write failed"):
        harness.run()
    rec = _saved_result(harness)
    assert rec["status"] == "FAILED"
    assert rec["attempts"][-1]["status"] == "FAILED"
    assert len(calls) == 1 + int(after_rejected_assignment)
    _assert_verified_parent(harness, trial_assignments=int(after_rejected_assignment))


def test_parent_mismatch_is_reported_before_any_design(harness, monkeypatch):
    def forbidden_design(*_args, **_kwargs):
        pytest.fail("design ran against a changed accepted parent")

    monkeypatch.setattr(harness.ad, "generation_design", forbidden_design)
    harness.ad.g["1"] = 1.1
    with _raises_contract_error(match="V242_GENERATION_TRIAL_PARENT_CHANGED"):
        harness.run()
    rec = _saved_result(harness)
    assert rec["status"] == "FAILED" and rec["failure_phase"] == "BEFORE_DESIGN"
    assert rec["attempts"] == []
    assert harness.ad.assignments == []
    assert harness.ad.g["1"] == 1.1  # guard never silently adopts or overwrites unexpected state


@pytest.mark.parametrize("failure", ["exception", "interrupt", "solver", "projection"])
def test_design_failures_are_saved_and_original_errors_propagate(harness, monkeypatch, failure):
    sentinel = KeyboardInterrupt("design interrupted") if failure == "interrupt" else RuntimeError("design failed")

    def design(_diag, _folder):
        if failure in ("exception", "interrupt"):
            raise sentinel
        if failure == "solver":
            return {"result": SimpleNamespace(converged=False), "projection": None}
        return {"result": None, "projection": SimpleNamespace(family_summaries=[{"converged": False}])}

    monkeypatch.setattr(harness.ad, "generation_design", design)
    if failure in ("exception", "interrupt"):
        with pytest.raises(type(sentinel)) as caught:
            harness.run()
        assert caught.value is sentinel
        phase = "GENERATION_DESIGN"
    else:
        token = "SOLVER" if failure == "solver" else "PROJECTION"
        with _raises_contract_error(match="V245_GENERATION_%s_NOT_CONVERGED_NOT_A_PLATEAU" % token):
            harness.run()
        phase = "GENERATION_%s_CHECK" % token
    rec = _saved_result(harness)
    assert rec["status"] == "FAILED" and rec["failure_phase"] == phase
    assert rec["search_complete"] is False and rec["stationarity_confirmed"] is False
    assert harness.ad.assignments == [] and harness.ad.snapshot() == harness.state


def test_post_design_parent_mismatch_still_blocks_the_trial(harness, monkeypatch):
    original = harness.ad.generation_design

    def design(diag, folder):
        context = original(diag, folder)
        harness.ad.g["1"] = 1.1
        return context

    monkeypatch.setattr(harness.ad, "generation_design", design)
    with _raises_contract_error(match="V242_GENERATION_TRIAL_PARENT_CHANGED"):
        harness.run()
    rec = _saved_result(harness)
    assert rec["status"] == "FAILED"
    assert rec["attempts"][0]["status"] == "FAILED"
    assert harness.ad.assignments == []
    assert harness.ad.g["1"] == 1.1


@pytest.mark.parametrize("failure", ["plan_error", "plan_interrupt"])
def test_search_planning_failure_after_rejection_cannot_abandon_live_trial(harness, monkeypatch, failure):
    original = step.choose_scale
    sentinel = (KeyboardInterrupt("stop between generation trials") if failure == "plan_interrupt"
                else RuntimeError("next scale could not be planned"))

    def choose(model, *args, **kwargs):
        if model.measured is not None:
            assert harness.ad.vol_g != harness.ad.g0
            raise sentinel
        return original(model, *args, **kwargs)

    monkeypatch.setattr(step, "choose_scale", choose)
    with pytest.raises(type(sentinel)) as caught:
        harness.run()
    assert caught.value is sentinel
    rec = _saved_result(harness)
    assert rec["status"] == "FAILED" and rec["failure_phase"] == "GENERATION_SEARCH"
    assert rec["attempts"][0]["status"] == "REJECTED"
    _assert_verified_parent(harness, trial_assignments=1)


class _SimulatedComError(Exception):
    hresult = -2147418111


def _break_failure_record_writes(harness, monkeypatch):
    original = harness.base.atomic_json

    def write(path, payload):
        if str(path).endswith("GENERATION_BLOCK_RESULT.json") and payload.get("status") == "FAILED":
            raise OSError("failure-record disk is full")
        return original(path, payload)

    monkeypatch.setattr(harness.base, "atomic_json", write)


def _assert_failure_record_error_attached(primary):
    errors = getattr(primary, "generation_failure_write_errors", [])
    assert errors
    assert all(item["path"].endswith("GENERATION_BLOCK_RESULT.json") for item in errors)
    assert any("OSError:failure-record disk is full" in item["error"] for item in errors)
    if callable(getattr(primary, "add_note", None)):
        assert any("GENERATION_FAILURE_RECORD_WRITE_FAILED" in note
                   for note in primary.__notes__)


@pytest.mark.parametrize("failure", ["com", "interrupt"])
def test_design_primary_error_survives_failure_record_io_error(harness, monkeypatch, failure):
    primary = (_SimulatedComError("COM disconnected in generation design") if failure == "com"
               else KeyboardInterrupt("stop generation design"))

    def design(*_args):
        raise primary

    monkeypatch.setattr(harness.ad, "generation_design", design)
    _break_failure_record_writes(harness, monkeypatch)
    with pytest.raises(type(primary)) as caught:
        harness.run()
    assert caught.value is primary
    _assert_failure_record_error_attached(primary)
    assert harness.ad.assignments == [] and harness.ad.snapshot() == harness.state


@pytest.mark.parametrize("failure", ["error", "interrupt"])
def test_dirty_demand_rollback_runs_when_planning_error_cannot_be_logged(harness, monkeypatch, failure):
    original = step.choose_scale
    primary = (RuntimeError("next step planning failed") if failure == "error"
               else KeyboardInterrupt("stop between assigned generation trials"))

    def choose(model, *args, **kwargs):
        if model.measured is not None:
            assert harness.ad.vol_g != harness.ad.g0
            raise primary
        return original(model, *args, **kwargs)

    monkeypatch.setattr(step, "choose_scale", choose)
    _break_failure_record_writes(harness, monkeypatch)
    with pytest.raises(type(primary)) as caught:
        harness.run()
    assert caught.value is primary
    _assert_failure_record_error_attached(primary)
    _assert_verified_parent(harness, trial_assignments=1)


def test_partial_apply_com_error_keeps_original_cause_when_failure_logging_fails(harness, monkeypatch):
    ad = harness.ad
    primary = _SimulatedComError("COM partial parameter write failed")

    def apply(context, scale, _folder):
        row = ad.generation_preview(context, scale)["candidate_rows"][0]
        ad.g[str(row["zone_no"])] = row["proposed"]
        raise primary

    monkeypatch.setattr(ad, "apply_generation", apply)
    _break_failure_record_writes(harness, monkeypatch)
    with _raises_contract_error(match="NOT_A_PLATEAU:COM partial parameter write failed") as caught:
        harness.run()
    assert caught.value.__cause__ is primary
    _assert_failure_record_error_attached(primary)
    _assert_failure_record_error_attached(caught.value)
    _assert_verified_parent(harness, trial_assignments=0)


def test_preapply_restore_error_survives_logging_failure_and_still_rolls_back(harness, monkeypatch):
    primary = _SimulatedComError("COM read failed after pre-apply restoration")
    original_guard = step.genstate.require_parent

    def require_parent(adapter, expected, folder, *, phase):
        if phase == "AFTER_PRE_APPLY_GATE_RESTORE":
            raise primary
        return original_guard(adapter, expected, folder, phase=phase)

    def apply(*_args):
        raise _contract_error("GENERATION_GATE:GENERATION_PA_GAP_WORK")

    monkeypatch.setattr(step.genstate, "require_parent", require_parent)
    monkeypatch.setattr(harness.ad, "apply_generation", apply)
    _break_failure_record_writes(harness, monkeypatch)
    with pytest.raises(_SimulatedComError) as caught:
        harness.run()
    assert caught.value is primary
    _assert_failure_record_error_attached(primary)
    _assert_verified_parent(harness, trial_assignments=0)

