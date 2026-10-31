"""Larger native-search budgets and an honest per-profile prediction audit."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

import r1_15a2_demand_policy_v1 as dp
import r1_15a2_td_count_blend_v24917 as blend
import r1_15a2_step_search_v24917 as step
from test_v24917_step_search import harness, opts  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT/'tests/data/EFFECTIVE_CONFIG_RUN_20261025_175302.json').read_text())


def test_defaults_match_deployed_budget_options():
    o = dp.load_options(root=ROOT,environ={})
    for key,value in [('tg_max_trials',6),('td_realization_max_trials',5),
                      ('td_inner_max_evaluations',180),('td_inner_budget_multiplier',2.)]:
        assert o[key] == dp.DEFAULTS[key] == value


@pytest.mark.parametrize('cycle,evals,iters',[(1,56,8),(2,56,8),(3,120,20),(4,120,20),(5,180,35),(100,180,35)])
def test_effective_original_schedule_is_really_expanded(cycle,evals,iters):
    schedule = CFG['coupled_demand']['finecdf_td']['progressive_schedule']
    original = next(s for s in schedule if cycle <= s['through_outer_cycle'])
    before = copy.deepcopy(original)
    out = blend.search_budget(original,CFG,blend.options())
    assert (out['max_td_evaluations'],out['max_iterations']) == (evals,iters)
    assert original == before
    assert out['name'] == original['name']
    assert CFG['coupled_demand']['finecdf_td']['max_runtime_seconds'] == 14400.
    if cycle >= 5: assert out['allow_progress_continue'] is True


def test_old_explicit_small_budget_is_preserved():
    stage = {'max_td_evaluations':100,'max_iterations':30,'allow_progress_continue':False}
    out = blend.search_budget(stage,{}, {'td_inner_max_evaluations':40})
    assert out['max_td_evaluations'] == 40 and out['max_iterations'] == 8
    assert out['v24917_capped'] and out['allow_progress_continue']
    assert blend.search_budget({}, {}, {'td_inner_max_evaluations':180}) == {}


@pytest.mark.parametrize('factor',[0.,.9,4.1,float('nan'),float('inf'),True])
def test_invalid_multiplier_fails_closed(factor):
    with pytest.raises(RuntimeError,match='td_inner_budget_multiplier'):
        dp.validate({'td_inner_budget_multiplier':factor})


def test_environment_multiplier_is_validated(tmp_path):
    o = dp.load_options(root=tmp_path,environ={'R1_TD_INNER_BUDGET_MULTIPLIER':'1.5'})
    assert o['td_inner_budget_multiplier'] == 1.5


def test_six_real_generation_trials_share_one_verified_rollback(harness,monkeypatch):
    harness.cfg['backtracking_scales'] = [1.,.5,.25,.125,.0625,.03125]
    harness.cfg['trial_calibration'] = {'max_trials_per_block':{'GENERATION':6}}
    monkeypatch.setattr(harness.ad,'block_gate',lambda *args: {'accepted':False,'reasons':['TEST_REJECTION']})
    changed,state,diag,value,rec = harness.run()
    assert not changed and len(rec['attempts']) == rec['planned_trials'] == 6
    assert len(harness.ad.assignments) == 7
    assert harness.ad.snapshot() == harness.state
    audit = json.loads((harness.folder/'TRY_06/STEP1_PRED_AUDIT.json').read_text())
    assert audit['status'] == 'MEASURED_PREDICTION_COMPARISON'
    assert audit['mode'] == 'SECANT_MEASURED' and audit['new_com_reads'] == 0


def test_native_acceptance_still_stops_before_six_trials(harness):
    harness.cfg['backtracking_scales'] = [1.,.5,.25,.125,.0625,.03125]
    changed,state,diag,value,rec = harness.run()
    assert changed and len(rec['attempts']) < rec['planned_trials'] == 6


def base_row(model=950.):
    return {'countlocation_no':'920023','role':'CALIBRATION','observed':1000.,'model':model}


def test_audit_distinguishes_raw_rho_and_measured_secant():
    model = step.StepModel([base_row()],{'keys':['920023'],'delta_full':[100.]},rho=.5)
    first = model.prediction_audit(.5,[base_row(1100.)])
    r = first['profiles'][0]
    assert r['raw_proposal_delta'] == 50. and r['planner_model'] == 975.
    assert r['measured_model'] == 1100. and r['flow_prediction_error'] == 125.
    model.set_measured(.5,[base_row(1100.)])
    second = model.prediction_audit(.25,[base_row(940.)])
    r = second['profiles'][0]
    assert r['raw_proposal_delta'] == 25. and r['planner_model'] == 1025.
    assert r['flow_prediction_error'] == -85.
    assert second['mode'] == 'SECANT_MEASURED'
    assert second['previous_measurement_scale'] == .5
    assert second['native_stage_attribution'].startswith('UNIDENTIFIED')


def test_off_grid_final_preview_is_frozen_before_native_writes():
    calls = []
    def forbidden_after_write(scale):
        calls.append(scale)
        raise AssertionError('Must use the saved pre-write preview')
    model = step.StepModel([base_row()],None,predictor=forbidden_after_write)
    preview = {'genfix2_prediction':{'available':True,'keys':['920023'],'delta':[42.]},
               'genfix2_mobility':{'passes':True}}
    model.record_preview(.73125,preview)
    audit = model.prediction_audit(.73125,[base_row(1200.)])
    assert audit['profiles'][0]['planner_model'] == 992.
    assert calls == []


@pytest.mark.parametrize('change',['missing','duplicate','nan','observation','role'])
def test_unbound_or_invalid_measurements_are_not_reported_as_valid_forecasts(change):
    rows = [base_row(1000.)]
    if change == 'missing': rows = []
    if change == 'duplicate': rows *= 2
    if change == 'nan': rows[0]['model'] = float('nan')
    if change == 'observation': rows[0]['observed'] = 1100.
    if change == 'role': rows[0]['role'] = 'VALIDATION'
    model = step.StepModel([base_row()],{'keys':['920023'],'delta_full':[100.]})
    assert model.prediction_audit(.5,rows)['status'] == 'UNAVAILABLE'
