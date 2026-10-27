"""User/workflow acceptance with a declared synthetic native backend.

The production TG selection, TD integration, assignment transactions, checkpoint
publication, supply controller and final verifier execute unchanged. Only native
Visum numeric evaluation and its COM parameter access are fixture boundaries.
"""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
import r1_15a2_inplace_transaction_v239 as tx
import r1_15a2_overnight_controller_v242 as coupled
import r1_15a2_overnight_controller_v240 as trial
from r1_15a2_supply import canonical_hash
from test_v245_repair import ROOT, TransactionAdapter, synthetic_trial

PLATEAU='LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM'

class WorkflowAdapter(TransactionAdapter):
    def __init__(self,cfg,control=None):
        super().__init__(cfg,control)
        self.generation_design_calls=0;self.td_calls=0;self.supply_design_calls=0
        self.once_generation=True;self.fail_generation=False;self.fail_td=False
        self.td_reason=PLATEAU;self.td_change=True;self.mutate_final=False
        self.fail_supply=False;self.stop_after_td=False
    def generation_design(self,*args):
        self.generation_design_calls+=1
        if self.fail_generation:raise RuntimeError('INJECTED_GENERATION_DESIGN_FAILURE')
        return super().generation_design(*args)
    def generation_preview(self,context,scale):
        if self.once_generation and self.state['generation']>=1.03:return {'candidate_rows':[]}
        return super().generation_preview(context,scale)
    def supply_design(self,*args,**kwargs):
        self.supply_design_calls+=1
        if self.fail_supply:raise RuntimeError('INJECTED_SUPPLY_DESIGN_FAILURE')
        return super().supply_design(*args,**kwargs)
    def diagnostics(self,folder,label='CURRENT'):
        d=super().diagnostics(folder,label)
        if self.mutate_final and Path(folder).name=='FINAL_VERIFICATION':self.state['b']+=.01
        return d


def setup_workflow(tmp_path,monkeypatch):
    cfg,ctl,_=synthetic_trial(tmp_path)
    cfg['block_schedule']=['GENERATION','TD_FINECDF_V17','SUPPLY_ADDVAL1']
    cfg['coupled_demand']={'max_outer_cycles':5,'min_stationary_cycles':2,'supply_max_cycles':5}
    a=WorkflowAdapter(cfg,ctl)
    def native_inner(adapter,cfg,folder,control,package_root):
        adapter.td_calls+=1
        old=adapter.state['b']
        rows=[]
        if adapter.fail_td:
            adapter.state['b']+=.99
            raise RuntimeError('INJECTED_NATIVE_TD_ERROR_AFTER_PARAMETER_WRITE')
        if adapter.td_change and old==0:
            adapter.state['b']=.08
            rows=[{'component':'WORK_E_C','after_b':.08,'after_c':-.1}]
        if adapter.stop_after_td:(control.root/'STOP_REQUESTED').touch()
        return {'changed_rows':rows,'stop_reason':adapter.td_reason,
                'search_complete':adapter.td_reason==PLATEAU,
                'stationarity_confirmed':adapter.td_reason==PLATEAU,
                'backend':'SYNTHETIC_NATIVE_EVALUATOR_NOT_VISUM'}
    monkeypatch.setattr(coupled,'run_finecdf_inner',native_inner)
    def write_bc(visum,rows):
        assert visum is a.visum
        a.apply_td(rows)
        return [{'status':'OK'} for r in rows]
    monkeypatch.setattr(tx.vp,'apply_td_candidates',write_bc)
    return cfg,ctl,a


def execute(tmp_path,monkeypatch,**flags):
    cfg,ctl,a=setup_workflow(tmp_path,monkeypatch)
    for key,value in flags.items():setattr(a,key,value)
    result=coupled.run_overnight_calibration_coupled(a,cfg,tmp_path/'workflow',ctl,ROOT)
    return result,a,ctl


def test_actual_complete_coupled_generation_td_supply_workflow(tmp_path,monkeypatch):
    r,a,ctl=execute(tmp_path,monkeypatch)
    assert r['status']=='COMPLETED_CONFIGURED_DEMAND_AND_SUPPLY_SEARCH',r
    assert r['completed_demand_cycles']==3
    assert r['demand_cycles'][0]['generation_changed'] and r['demand_cycles'][0]['td_changed']
    assert r['stationary_cycle_streak']==2
    assert r['supply_started'] and a.supply_design_calls>1
    assert r['final_state_verified'] and r['calibration_complete']
    assert r['final_state_hash']==a.snapshot()['state_hash']
    assert r['accepted_count']>=3
    assert all(c['completed'] and c['generation_completed'] and c['td_completed'] for c in r['demand_cycles'])
    assert r['load_version_called'] is False and r['direct_od_matrix_writes'] is False
    assert len(a.assignments)>15 # trials, restores, adoption and downstream recomputations.
    logs=list((tmp_path/'workflow').rglob('ROLLBACK_VERIFICATION.json'))
    assert len(logs)>5 and all(json.loads(p.read_text())['passes'] for p in logs)
    assert json.loads((tmp_path/'workflow/RUN_STATUS.json').read_text())['final_state_verified']


def test_actual_generation_crash_is_not_a_completed_iteration(tmp_path,monkeypatch):
    r,a,_=execute(tmp_path,monkeypatch,fail_generation=True)
    assert r['status']=='FAILED' and r['completed_demand_cycles']==0
    assert r['accepted_count']==0 and not r['demand_converged'] and not r['supply_started']
    assert r['demand_cycles'][0]['status']=='FAILED'
    assert r['demand_cycles'][0]['generation_changed'] is None
    assert a.td_calls==0 and a.supply_design_calls==0
    assert not r['final_state_verified'] and 'final_state_hash' not in r


def test_actual_td_failure_restores_bc_after_accepted_generation(tmp_path,monkeypatch):
    r,a,_=execute(tmp_path,monkeypatch,fail_td=True)
    assert r['status']=='FAILED',r
    assert r['accepted_count']==1 and r['completed_demand_cycles']==0
    assert a.state['generation']==pytest.approx(1.03) and a.state['b']==0
    assert r['live_matches_last_accepted'] is True
    rb=json.loads(next((tmp_path/'workflow').rglob('ROLLBACK_ALL_TD_RESULT.json')).read_text())
    assert rb['passes'] and rb['direct_od_matrix_writes'] is False
    assert not r['supply_started']


@pytest.mark.parametrize('reason',['MAX_ITERATIONS','TD_EVALUATION_BUDGET','TD_INNER_TIME_BUDGET','TD_USER_STOP_FILE','GLOBAL_TIMEBUDGETREACHED'])
def test_td_budget_or_stop_retains_best_but_never_unlocks_supply(tmp_path,monkeypatch,reason):
    r,a,_=execute(tmp_path,monkeypatch,td_reason=reason)
    assert r['status'].startswith('DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED:'),r
    assert not r['supply_started'] and not r['demand_converged']
    assert r['completed_demand_cycles']==0 and not r['demand_cycles'][0]['completed']
    assert r['final_state_verified'] and not r['calibration_complete']
    assert a.state['b']==.08 and r['final_state_hash']==a.snapshot()['state_hash']


def test_nochange_requires_two_complete_cycles(tmp_path,monkeypatch):
    r,a,_=execute(tmp_path,monkeypatch,no_generation=True,td_change=False,no_supply=True)
    assert r['completed_demand_cycles']==2 and r['calibration_complete'],r
    assert a.td_calls==2 and a.generation_design_calls==2


def test_supply_failure_does_not_receive_completed_prefix(tmp_path,monkeypatch):
    r,a,_=execute(tmp_path,monkeypatch,fail_supply=True)
    assert r['demand_converged'] and r['supply_started']
    assert r['status']=='FAILED_SUPPLY:FAILED'
    assert not r['final_state_verified'] and not r['calibration_complete']
    assert 'final_state_hash' not in r


def test_stop_during_td_propagates_best_and_no_next_cycle(tmp_path,monkeypatch):
    r,a,_=execute(tmp_path,monkeypatch,stop_after_td=True,td_reason='GLOBAL_USERSTOPREQUESTED')
    assert r['final_state_verified'] and not r['calibration_complete'],r
    assert a.state['b']==.08 and a.td_calls==1 and not r['supply_started']


def test_final_read_only_diagnostics_mutation_is_detected(tmp_path,monkeypatch):
    r,a,_=execute(tmp_path,monkeypatch,mutate_final=True)
    assert r['status'].startswith('FAILED') and not r['final_state_verified'],r
    assert not r['calibration_complete'] and 'final_state_hash' not in r


def test_generation_trial_truncation_not_convergence(tmp_path,monkeypatch):
    cfg,ctl,a=setup_workflow(tmp_path,monkeypatch)
    cfg['trial_calibration']['max_trials_per_block']['GENERATION']=1
    a.no_generation=True
    r=coupled.run_overnight_calibration_coupled(a,cfg,tmp_path/'workflow',ctl,ROOT)
    assert r['status']=='FAILED' and 'TRUNCATED' in r['error']
    assert not r['supply_started'] and r['completed_demand_cycles']==0


def launcher_module():
    spec=importlib.util.spec_from_file_location('v245_user_entrypoint',ROOT/'R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_5.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def setup_launcher(tmp_path,monkeypatch,**flags):
    cfg,ctl,a=setup_workflow(tmp_path,monkeypatch)
    project=tmp_path/'project with spaces \u017elu\u0165ou\u010dk\u00fd';project.mkdir()
    source=project/'SOURCE.ver';source.write_bytes(b'ORIGINAL_USER_FILE_MUST_NOT_CHANGE')
    a.visum.IO=SimpleNamespace(CurrentVersionFile=str(source))
    a.visum.Procedures=SimpleNamespace()
    m=launcher_module();monkeypatch.setattr(m,'Visum',a.visum,raising=False)
    monkeypatch.setattr(m,'load_config',lambda:cfg)
    monkeypatch.setattr(m.api_audit,'project_output_root',lambda visum:(project/'diagnostics',None))
    monkeypatch.setattr(m.api_audit,'collect_live_api',lambda *args,**kw:{'required_failures':[]})
    def construct(visum,cfg,control):
        a.control=control
        return a
    monkeypatch.setattr(m,'VisumAdapter',construct)
    def native_save(visum,path):
        cp=a.save(path);visum.IO.CurrentVersionFile=str(path);return cp
    monkeypatch.setattr(m.rt,'save_version',native_save)
    for key,value in flags.items():setattr(a,key,value)
    return m,a,source


def test_user_entrypoint_real_controller_start_to_final_file(tmp_path,monkeypatch):
    m,a,source=setup_launcher(tmp_path,monkeypatch)
    r=m.main()
    assert r['status']=='COMPLETED_CONFIGURED_DEMAND_AND_SUPPLY_SEARCH',r
    assert r['source_file_unchanged'] and source.read_bytes()==b'ORIGINAL_USER_FILE_MUST_NOT_CHANGE'
    assert Path(r['final_accepted_version']['path']).name=='FINAL_CALIBRATED_WORKING_COPY.ver'
    assert Path(r['final_accepted_version']['path']).is_file()
    assert a.closed and not getattr(sys,'_r1_15a2_calibration_busy',False)
    assert not (source.parent/'.R1_15A2_FULL_CALIBRATION.lock').exists()
    assert json.loads((Path(r['run_directory'])/'00_RESULT.json').read_text())['calibration_complete']


def test_user_entrypoint_budget_saves_partial_not_final_calibrated(tmp_path,monkeypatch):
    m,a,source=setup_launcher(tmp_path,monkeypatch,td_reason='TD_EVALUATION_BUDGET')
    r=m.main()
    assert Path(r['final_accepted_version']['path']).name=='FINAL_VERIFIED_PARTIAL_WORKING_COPY.ver'
    assert not (Path(r['run_directory'])/'FINAL_CALIBRATED_WORKING_COPY.ver').exists()
    assert r['final_state_verified'] and not r['calibration_complete']


def test_user_entrypoint_failure_never_saves_final(tmp_path,monkeypatch):
    m,a,source=setup_launcher(tmp_path,monkeypatch,fail_generation=True)
    r=m.main()
    assert r['status']=='FAILED' and 'final_accepted_version' not in r
    assert not list(Path(r['run_directory']).glob('FINAL*.ver'))
    assert r['source_file_unchanged'] and a.closed


def test_launcher_final_status_disk_error_still_releases_lock_and_busy(tmp_path,monkeypatch):
    m,a,source=setup_launcher(tmp_path,monkeypatch)
    original=m.atomic_json
    def disk_error(path,value):
        if Path(path).name=='00_RESULT.json':raise OSError('INJECTED_FINAL_DISK_FAILURE')
        return original(path,value)
    monkeypatch.setattr(m,'atomic_json',disk_error)
    with pytest.raises(OSError,match='FINAL_DISK'):m.main()
    assert a.closed and not getattr(sys,'_r1_15a2_calibration_busy',False)
    assert not (source.parent/'.R1_15A2_FULL_CALIBRATION.lock').exists()


def test_existing_other_run_lock_is_not_deleted(tmp_path,monkeypatch):
    m,a,source=setup_launcher(tmp_path,monkeypatch)
    lock=source.parent/'.R1_15A2_FULL_CALIBRATION.lock';lock.write_text('ANOTHER_PROCESS')
    r=m.main()
    assert r['status']=='FULL_OVERNIGHT_FAILED'
    assert lock.read_text()=='ANOTHER_PROCESS' and not a.saves


def test_launcher_prioritizes_current_release_and_restores_sys_path(tmp_path,monkeypatch):
    old=list(sys.path)
    monkeypatch.setattr(sys,'path',[str(tmp_path/'old release'),str(ROOT)]+[p for p in old if p!=str(ROOT)])
    expected=list(sys.path)
    m=launcher_module()
    assert sys.path[0]==str(ROOT)
    with pytest.raises(RuntimeError,match='NO_INJECTED_VISUM'):m.main()
    assert sys.path==expected


def test_launcher_restores_both_global_visum_references(tmp_path,monkeypatch):
    m,a,source=setup_launcher(tmp_path,monkeypatch)
    old_rt=object();old_base=object()
    monkeypatch.setattr(m.rt,'Visum',old_rt,raising=False)
    monkeypatch.setattr(m.supply_runtime.base,'Visum',old_base,raising=False)
    ctor=m.VisumAdapter
    def construct(*args):
        m.supply_runtime.base.Visum=a.visum
        return ctor(*args)
    monkeypatch.setattr(m,'VisumAdapter',construct)
    assert m.main()['calibration_complete']
    assert m.rt.Visum is old_rt and m.supply_runtime.base.Visum is old_base
