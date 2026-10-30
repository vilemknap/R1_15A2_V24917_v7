# -*- coding: utf-8 -*-
"""SUPPLYMIX completion is separate from the coupled TG/TD search contract.

This is a fail-closed regression of the cycle-2 NO_COST_SAFE_CANDIDATE case:
a no-write SupplyMix failure suppresses stationary certification, but cannot
overwrite a successfully completed Generation search with search_complete=False.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

import r1_15a2_supply_mix_v24917 as sm
import r1_15a2_demand_policy_v1 as dp


@pytest.mark.parametrize("supply_status", (
    "NO_COST_SAFE_CANDIDATE",
    "DESIGN_FAILED_NO_WRITE",
    "TRIAL_FAILED_ROLLBACK_VERIFIED",
    "RECOVERED_FULL_RECOMPUTE_FROM_PARENT_PARAMETERS",
))
@pytest.mark.parametrize("original_generation_complete", (True, False))
def test_no_write_supplymix_incomplete_does_not_corrupt_generation_completion(
        monkeypatch, tmp_path, supply_status, original_generation_complete):
    state = {"state_hash": "unchanged-parent"}
    diag = {"d12": {"rows": []}}
    value = {"total": 1.2}
    policy = NS(last_generation_complete=True, last_generation_changed=False)
    monkeypatch.setitem(dp._ACTIVE, -20261030, {"policy": policy})
    monkeypatch.setattr(sm, "options", lambda: {
        "enabled": True, "start_cycle": 2, "every_n": 2,
    })
    def generation(*args, **kwargs):
        return False, state, diag, value, {
            "status": "GENERATION_CONFIGURED_SEARCH_RESULT",
            "search_complete": original_generation_complete,
            "stationarity_confirmed": original_generation_complete,
        }
    observed = []
    def no_write_supply(*args, **kwargs):
        observed.append(kwargs.get("outer_cycle", args[-2] if len(args) > 2 else None))
        return False, state, diag, value, {
            "status": supply_status,
            "search_complete": False,
            "stop_reason": "NO_COST_SAFE_PROVED_BRANCH",
            "stationarity_confirmed": False,
            "attempts": [],
        }
    monkeypatch.setattr(sm, "supply_block", no_write_supply)
    wrapped = sm._wrap_generation(generation, None, None, None)
    changed, st, dg, val, record = wrapped(
        object(), {}, tmp_path / "DEMAND_CYCLE_02_GENERATION", None,
        state, diag, None, None, None, outer_cycle=2)
    assert changed is False
    assert st is state and dg is diag and val is value
    assert observed == [2]
    assert record["v24917_supplymix"]["status"] == supply_status
    assert record["v24917_supplymix"]["search_complete"] is False
    assert record["v24917_supplymix_search_incomplete"] is True
    assert record["v24917_supplymix_incomplete_reason"] == "NO_COST_SAFE_PROVED_BRANCH"
    assert record["v24917_supplymix_tg_completion_preserved"] is True
    assert record["search_complete"] is original_generation_complete
    assert record["stationarity_confirmed"] is False
    assert policy.last_generation_complete is False

    # Exact logic used by the parent coupled controller:
    # no false termination on independent supply search incompleteness;
    # but no false stationary demand cycle, even when TG and TD finished.
    inner = {"search_complete": True}
    outer_search_complete = (
        record.get("search_complete") is True and
        inner.get("search_complete") is True
    )
    outer_stationary = (
        not changed and not False and
        record.get("stationarity_confirmed") is True
    )
    assert outer_search_complete is original_generation_complete
    assert outer_stationary is False


def test_supplymix_no_write_result_does_not_change_schedule_or_run_state(monkeypatch,tmp_path):
    state = {"state_hash": "unchanged"}
    diag = {"d12": {"rows": []}}
    value = {"total": 1.2}
    calls = []
    monkeypatch.setattr(sm, "options", lambda: {
        "enabled": True, "start_cycle": 2, "every_n": 2,
    })
    monkeypatch.setattr(sm, "supply_block", lambda *a,**k:
        calls.append("called") or (False, state, diag, value, {
            "status": "NO_COST_SAFE_CANDIDATE", "search_complete":False
        }))
    wrapped = sm._wrap_generation(
        lambda *a,**k: (False,state,diag,value,{
            "status":"GENERATION_COMPLETE", "search_complete":True,
            "stationarity_confirmed":True
        }), None,None,None)
    r1 = wrapped(None,{},tmp_path/"DEMAND_CYCLE_01_GENERATION",None,
                 state,diag,None,None,None,outer_cycle=1)
    assert calls == []
    assert r1[4]["search_complete"] is True
    assert "v24917_supplymix" not in r1[4]
    r2 = wrapped(None,{},tmp_path/"DEMAND_CYCLE_02_GENERATION",None,
                 state,diag,None,None,None,outer_cycle=2)
    assert calls == ["called"]
    assert r2[4]["search_complete"] is True
    assert r2[4]["stationarity_confirmed"] is False


def test_supplymix_successful_search_keeps_normal_generation_semantics(monkeypatch,tmp_path):
    state={"state_hash":"s"}
    diag={}
    value={"total":1.0}
    monkeypatch.setattr(sm,"options",lambda:{
        "enabled":True,"start_cycle":2,"every_n":2
    })
    monkeypatch.setattr(sm,"supply_block",lambda *a,**k:
        (False,state,diag,value,{"status":"NO_DRIVER_BRANCH","search_complete":True}))
    wrapped=sm._wrap_generation(
        lambda *a,**k:(False,state,diag,value,{
            "status":"GENERATION_COMPLETE",
            "search_complete":True,"stationarity_confirmed":True
        }),None,None,None)
    output=wrapped(None,{},tmp_path/"DEMAND_CYCLE_02_GENERATION",None,
                   state,diag,None,None,None,outer_cycle=2)
    assert output[4]["search_complete"] is True
    assert output[4]["stationarity_confirmed"] is True
    assert output[4].get("v24917_supplymix_search_incomplete") is None
