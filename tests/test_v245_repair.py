"""Executable regressions for actual V244 bugs; no claim of live Visum testing."""
import copy
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

import r1_15a2_core as core
import r1_15a2_overnight_controller_v240 as trial
import r1_15a2_overnight_controller_v242 as coupled
import r1_15a2_finecdf_bridge_v242 as bridge
import r1_15a2_runtime_v1 as rt
import r1_15a2_two_mode_v238 as mode
from r1_15a2_controller_v22 import build_reference, ledger, diagnostic_hash
from r1_15a2_safety_v245 import adapter_config_scope, recovery_scope, final_artifact_name, validate_v245_config
from r1_15a2_supply import SupplyPolicy, SupplyContractError
from tests.synthetic_v22_adapter import SyntheticAdapter, synthetic_config
from test_two_mode_v238 import store, fill, authority, hierarchy, SEQS, profile, P, CODES, live_fixture, collect_two_modes

ROOT = Path(__file__).resolve().parents[1]


def config():
    return json.loads((ROOT/'R1_15A2_CONFIG_V2_4_5.json').read_text())


def test_actual_15_57_positive_zero_link_path_preserved_and_not_attributed(tmp_path):
    c=store(tmp_path,[profile(model=0)])
    try:
        c.add_parents('NATIVE_CW','C',[[15,57,1,2.085]],authority([2.085]))
        c.add_geometry('C',[[15,57,1,'','','','']])
        summary=c.build_route_evidence()
        row=c.db.execute('SELECT edge_ids,edge_count,geometry_kind FROM geometry').fetchone()
        assert row==(b'',0,'ZERO_LINK_INTERZONAL_NO_ADDVAL1_EFFECT')
        assert c.db.execute('SELECT SUM(volume) FROM volumes').fetchone()[0]==pytest.approx(2.085)
        assert c.db.execute('SELECT COUNT(*) FROM edge_postings').fetchone()[0]==0
        assert c.db.execute('SELECT COUNT(*) FROM profile_hits').fetchone()[0]==0
        assert summary['zero_link_paths_by_dseg'][0]['zero_link_volume']==pytest.approx(2.085)
        inc,_=c.incidence({'path_export_dsegs':['NATIVE_CW'],'mutable_dsegs':['NATIVE_CW']},[15,57])
        assert inc['q_current'].tolist()==[2.085]
        assert inc['path_link_coverage']==1.0 and inc['path_link_volume_coverage']==1.0
        assert inc['raw_all_path_link_volume_coverage']==0.0
        assert inc['incidence_nnz']==0
        assert inc['total_path_volume']==2.085
    finally:c.close()


def test_zero_link_routes_do_not_dilute_link_coverage_or_invent_collateral(tmp_path):
    c=store(tmp_path,[profile(model=600)])
    try:
        c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400],[1,2,3,100]],authority([600,400,100]))
        c.add_geometry('C',hierarchy()+[[1,2,3,'','','','']]);c.build_route_evidence()
        inc,_=c.incidence({'path_export_dsegs':['NATIVE_CW'],'mutable_dsegs':['NATIVE_CW']},[1,2])
        assert inc['path_count']==3 and inc['paths_with_link_rows']==2
        assert inc['total_path_volume']==1100 and inc['zero_link_path_volume']==100
        assert inc['path_link_coverage']==1.0
        assert inc['raw_all_path_link_coverage']==pytest.approx(2/3)
        # OD total is still 1100; zero-link routes contribute zero to traversal.
        assert inc['incidence_share'].tolist()==pytest.approx([600/1100])
        imp=c.impact([{'key':list(P),'delta':1}],0,600)
        assert imp['by_dseg']['NATIVE_CW']['volume']==600
        assert imp['by_dseg']['NATIVE_CW']['routes']==1
    finally:c.close()


def test_missing_geometry_is_not_zero_link(tmp_path):
    c=store(tmp_path)
    try:
        c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400]],authority([600,400]))
        with pytest.raises(SupplyContractError,match='COVERAGE'):
            c.add_geometry('C',[[1,2,1,'','','','']])
        with pytest.raises(SupplyContractError,match='UNEXPORTED'):
            c.build_route_evidence()
    finally:c.close()


def test_com_stream_exception_after_parent_is_not_swallowed_as_zero_link(tmp_path):
    c=store(tmp_path)
    def broken():
        yield [15,57,1,'','','','']
        raise RuntimeError('INJECTED_COM_PAGE_FAILURE')
    try:
        c.add_parents('NATIVE_CW','C',[[15,57,1,2.085]],authority([2.085]))
        with pytest.raises(RuntimeError,match='COM_PAGE_FAILURE'):c.add_geometry('C',broken())
        assert not c.ready
    finally:c.close()


def test_full_12_dseg_export_preserves_zero_link_paths_in_both_modes(tmp_path):
    v,cfg,model_value,lists=live_fixture()
    original=lists.make
    def make(kind):
        obj=original(kind);old=obj.SetObjects
        def set_objects(*args):
            old(*args)
            if kind=='geometry':obj.raw=hierarchy(((),SEQS[1]))
        obj.SetObjects=set_objects
        return obj
    lists.make=make
    c=store(tmp_path,[profile(model=0)],settings={'sample_windows':[[1,2]],'page_size':2})
    try:
        s=collect_two_modes(v,c,cfg,tmp_path)
        assert s['dseg_complete_count']==12 and s['full_geometry_read_count']==2
        assert len(s['zero_link_paths_by_dseg'])==12
        assert all(r['passes'] for r in c.parity_rows)
        assert all(r['zero_link_paths']==1 for r in s['zero_link_paths_by_dseg'])
        assert all(x.unbounded_calls==0 for x in lists.instances)
    finally:c.close()


def test_collector_close_invalidates_cache_and_is_idempotent(tmp_path):
    c=store(tmp_path);fill(c);c.close();c.close()
    assert not c.ready and c._finished_proof is None
    with pytest.raises(SupplyContractError,match='NOT_READY'):c.finish()
    (tmp_path/'cache.sqlite').unlink()


def test_constructor_failure_closes_sql_connection(tmp_path,monkeypatch):
    closed=[]
    class Connection:
        def executescript(self,*a):raise OSError('SQLITE_SETUP_FAILURE')
        def close(self):closed.append(True)
    monkeypatch.setattr(mode.sqlite3,'connect',lambda *a,**k:Connection())
    with pytest.raises(OSError,match='SETUP'):store(tmp_path)
    assert closed==[True]


def test_repeated_cache_lifecycle_has_no_file_descriptor_growth(tmp_path):
    proc=Path('/proc/self/fd')
    before=len(list(proc.iterdir()))
    for i in range(30):
        c=store(tmp_path,name='loop%d.sqlite'%i);fill(c);c.close()
    del c;gc.collect()
    assert len(list(proc.iterdir()))<=before+1


def test_duplicate_build_does_not_double_count(tmp_path):
    c=store(tmp_path);fill(c)
    try:
        with pytest.raises(SupplyContractError,match='ALREADY_BUILT'):c.build_route_evidence()
        assert c.flow==[600]
    finally:c.close()


class Link:
    def __init__(self,adapter,key):self.adapter=adapter;self.key=key
    def AttValue(self,name):return self.adapter.state['a'][self.key]
    def SetAttValue(self,name,value):self.adapter.state['a'][self.key]=float(value)


class Zones:
    def __init__(self,adapter):self.adapter=adapter
    def GetMultiAttValues(self,attr):return [(1,1 if attr=='NO' else self.adapter.state['generation'])]
    def SetMultiAttValues(self,attr,pairs):self.adapter.state['generation']=float(list(pairs)[0][1])


class TransactionAdapter(SyntheticAdapter):
    """Deterministic fixture exercising real parameter-restore/transaction code."""
    def __init__(self,cfg,control=None):
        super().__init__(cfg);self.control=control;self.zones=[1]
        self.visum=SimpleNamespace(Net=SimpleNamespace(Zones=Zones(self)))
        self.closed=False;self.fail_design=False;self.fail_assignment=False
        self.stop_on_mutation=False;self.bad_diag_after=False;self.ki_on_mutation=False
        self.idp_generation_cost=False;self.no_generation=False;self.no_supply=False
    def read_links(self):
        return {tuple(map(int,k.split('|'))):{'object':Link(self,k)} for k in self.state['a']}
    def assign(self,folder,*,supply_only):
        Path(folder).mkdir(parents=True,exist_ok=True)
        changed=self.state['generation']!=1.0 or any(self.state['a'].values())
        if changed and self.stop_on_mutation:
            (self.control.root/'STOP_REQUESTED').touch();self.stop_on_mutation=False
        if changed and self.ki_on_mutation:
            self.ki_on_mutation=False;raise KeyboardInterrupt('INJECTED_INTERRUPT')
        if self.control:self.control.checkpoint('FIXTURE_ASSIGNMENT')
        if changed and self.fail_assignment:raise RuntimeError('INJECTED_ASSIGNMENT_FAILURE')
        self.state['q']=1000*self.state['generation']
        return super().assign(folder,supply_only=supply_only)
    def diagnostics(self,folder,label='CURRENT'):
        if self.control:self.control.checkpoint('FIXTURE_DIAGNOSTICS')
        d=super().diagnostics(folder,label)
        if self.idp_generation_cost:
            row=d['d11']['summary']['component_dist_summary_rows'][0]
            row['mean_model_conditioned']-=100*(self.state['generation']-1)
            row['l1_distance_half']+=self.state['generation']-1
        return d
    def supply_design(self,*a,**k):
        if self.fail_design:raise RuntimeError('INJECTED_DESIGN_FAILURE')
        return {'candidates':[]} if self.no_supply else super().supply_design(*a,**k)
    def generation_preview(self,context,scale):
        if self.no_generation:return {'candidate_rows':[]}
        return super().generation_preview(context,scale)
    def close(self):self.closed=True


def synthetic_trial(tmp_path):
    cfg=synthetic_config();cfg.update(apply=False,production_apply=False,block_schedule=['SUPPLY_ADDVAL1'])
    cfg['trial_calibration']={'enabled':True,'max_runtime_seconds':1000,'progress_interval_seconds':0,
                             'max_cycles':2,'max_accepted_states':10,'max_trials_per_block':{'SUPPLY_ADDVAL1':2,'GENERATION':3}}
    ctl=trial.OvernightControl(tmp_path/'control',cfg)
    return cfg,ctl,TransactionAdapter(cfg,ctl)


def candidate_inputs(a,cfg):
    state=a.snapshot();diag=a.diagnostics(Path('.'));policy=SupplyPolicy.from_config(cfg)
    reference=build_reference(diag,cfg);anchors=dict(state['addval1'])
    value=ledger(diag,state,anchors,policy,reference,cfg)
    cand=a.supply_design(diag,Path('.'),state)['candidates'][0]
    return policy,state,diag,reference,anchors,value,cand


@pytest.mark.parametrize('failure',['stop','assignment','interrupt'])
def test_real_transaction_restores_parameters_after_interruption(tmp_path,failure):
    cfg,ctl,a=synthetic_trial(tmp_path);policy,before,diag,ref,anchors,value,cand=candidate_inputs(a,cfg)
    a.stop_on_mutation=failure=='stop';a.fail_assignment=failure=='assignment';a.ki_on_mutation=failure=='interrupt'
    args=(a,cfg,policy,'SUPPLY_ADDVAL1',cand,[],None,before,diag,value,anchors,ref,tmp_path/'trial',ctl)
    if failure=='assignment':
        ev,rolled,error=trial._evaluate_candidate(*args)
        assert ev is None and 'ASSIGNMENT_FAILURE' in error
    else:
        with pytest.raises(trial.UserStopRequested if failure=='stop' else KeyboardInterrupt):trial._evaluate_candidate(*args)
    assert a.snapshot()==before
    rb=json.loads((tmp_path/'trial/ROLLBACK/ROLLBACK_VERIFICATION.json').read_text())
    assert rb['passes'] is True
    assert a.restores==0


def test_generation_counts_policy_reaches_actual_adapter_gate_and_restores(tmp_path):
    cfg,ctl,a=synthetic_trial(tmp_path);a.idp_generation_cost=True
    original_cfg=a.cfg;cfg['idp_max_mean_degradation']=.005;cfg['idp_max_component_degradation']=.02
    before=a.snapshot();diag=a.diagnostics(tmp_path);gc_cfg=coupled._generation_counts_cfg(cfg)
    reference=build_reference(diag,gc_cfg);policy=SupplyPolicy.from_config(cfg)
    changed,after,d,lv,rec=coupled._generation_update_once(a,cfg,tmp_path/'generation',ctl,before,diag,before['addval1'],reference,policy)
    assert changed and a.state['generation']>1
    assert a.cfg is original_cfg
    accepted=rec['attempts'][0]['decision']
    assert accepted['idp_mean_degradation']>.005
    assert 'IDP_MEAN_DEGRADED' not in accepted['reasons']
    assert accepted['validation_used_for_design_or_acceptance'] is False


def test_adapter_config_scope_restored_on_exception():
    a=SimpleNamespace(cfg={'before':1});old=a.cfg
    with pytest.raises(RuntimeError):
        with adapter_config_scope(a,{'during':2}):
            assert a.cfg=={'during':2};raise RuntimeError('test')
    assert a.cfg is old


@pytest.mark.parametrize('failure',['design','trial','truncated'])
def test_supply_errors_and_budget_are_not_convergence(tmp_path,failure):
    cfg,ctl,a=synthetic_trial(tmp_path)
    a.fail_design=failure=='design';a.fail_assignment=failure=='trial'
    if failure=='truncated':
        cfg['trial_calibration']['max_trials_per_block']['SUPPLY_ADDVAL1']=1;a.flat=True
    result=trial.run_overnight_calibration(a,cfg,tmp_path/'run',ctl)
    assert result['status']!='CONVERGED_NO_ACCEPTED_IMPROVEMENT'
    assert result['stationarity_confirmed'] is False
    if failure in ('design','trial'):
        assert result['status'].startswith('FAILED')
        assert result['final_state_verified'] is False
        assert 'final_state_hash' not in result
    else:assert result['status']=='SEARCH_TRUNCATED_NO_CONVERGENCE_CLAIM'


def test_recovery_defers_stop_but_next_normal_checkpoint_still_stops(tmp_path):
    cfg,ctl,a=synthetic_trial(tmp_path)
    (ctl.root/'STOP_REQUESTED').touch()
    with recovery_scope(ctl,'TEST_ROLLBACK'):
        ctl.checkpoint('RESTORING')
        with recovery_scope(ctl,'NESTED'):ctl.checkpoint('STILL_RESTORING')
    assert ctl._recovery_depth==0
    with pytest.raises(trial.UserStopRequested):ctl.checkpoint('NEW_CANDIDATE')


def test_output_directory_created_by_actual_shared_execution_function(tmp_path):
    called=[]
    v=SimpleNamespace(Procedures=SimpleNamespace(Execute=lambda:called.append(True)))
    out=tmp_path/'one/two/three'
    rt.execute_procseq(v,out)
    assert called==[True] and 'END' in (out/'20_PROCSEQ_EXECUTION.txt').read_text()


def test_checkpoint_bad_save_does_not_overwrite_latest(tmp_path):
    cfg,ctl,a=synthetic_trial(tmp_path)
    first=trial._save_rotating_checkpoint(a,tmp_path/'run',0)
    pointer=(tmp_path/'run/LATEST_ACCEPTED_CHECKPOINT.json').read_bytes()
    def bad(path):Path(path).write_bytes(b'partial');raise OSError('DISK_FULL')
    a.save=bad
    with pytest.raises(OSError):trial._save_rotating_checkpoint(a,tmp_path/'run',1)
    assert (tmp_path/'run/LATEST_ACCEPTED_CHECKPOINT.json').read_bytes()==pointer
    assert hashlib.sha256(Path(first['path']).read_bytes()).hexdigest()==first['sha256']


def test_checkpoint_rotation_keeps_two_verified_slots(tmp_path):
    cfg,ctl,a=synthetic_trial(tmp_path)
    for i in range(7):cp=trial._save_rotating_checkpoint(a,tmp_path/'run',i)
    assert len(list((tmp_path/'run/CHECKPOINTS').glob('*.ver')))==2
    assert json.loads((tmp_path/'run/LATEST_ACCEPTED_CHECKPOINT.json').read_text())['checkpoint']==cp


@pytest.mark.parametrize('result,expected',[
    ({'final_state_hash':'unverified'},None),
    ({'final_state_verified':False,'final_state_hash':'bad','calibration_complete':True},None),
    ({'final_state_verified':True,'final_state_hash':'ok','calibration_complete':False},'FINAL_VERIFIED_PARTIAL_WORKING_COPY.ver'),
    ({'final_state_verified':True,'final_state_hash':'ok','calibration_complete':True},'FINAL_CALIBRATED_WORKING_COPY.ver'),
])
def test_final_artifact_requires_explicit_verified_state(result,expected):
    assert final_artifact_name(result)==expected


def load_launcher():
    spec=importlib.util.spec_from_file_location('launcher_v245_test',ROOT/'R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_5.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def test_new_launcher_config_loads_and_seals_complete_implementation():
    mod=load_launcher();cfg=mod.load_config()
    assert cfg['release']=='R1_15A2_V2_4_5_FULL_CALIBRATION_REPAIR_20261016'
    assert len(cfg['implementation_hash'])==64
    assert cfg['coupled_demand']['min_stationary_cycles']==2
    assert cfg['supply']['gap_readback']['maximum_gap']==.005
    assert cfg['csd408_mapping_review_acknowledged'] is False
    assert cfg['city90_bidirectional_qa_acknowledged'] is False


@pytest.mark.parametrize('field,value',[('min_stationary_cycles',1),('min_stationary_cycles',True),('max_outer_cycles',0)])
def test_bad_stationary_config_is_rejected(field,value):
    cfg=config();cfg['coupled_demand'][field]=value
    with pytest.raises(SupplyContractError):validate_v245_config(cfg)


def test_fixed_numerical_authorities_unchanged():
    assert bridge._sha(ROOT/bridge.REF_REL)==bridge.REF_SHA256
    cfg=config()
    for rel,digest in cfg['supply']['fixed_input_hashes'].items():
        assert rt.sha256_file(ROOT/rel)==digest
    for pathkey,hashkey in [('12d_authority_csv','12d_authority_sha256'),('12d_city_authority_csv','12d_city_authority_sha256')]:
        assert rt.sha256_file(ROOT/cfg[pathkey])==cfg[hashkey]


def test_failed_status_never_authorizes_final_artifact_even_with_stale_flags():
    assert final_artifact_name({'status':'FAILED_SUPPLY:FAILED','final_state_verified':True,
                                'final_state_hash':'stale','calibration_complete':True}) is None


@pytest.mark.parametrize('fixed_code,fixed_no',[('EXOG_EE_CF',9406),('LNV',2),('NV',3),('NATIVE_CF',9116)])
def test_generation_cannot_silently_mutate_fixed_demand(tmp_path,fixed_code,fixed_no):
    import r1_15a2_controller_v22 as c
    cfg,ctl,a=synthetic_trial(tmp_path)
    before=a.snapshot();before['matrices'].append({'matrix_no':fixed_no,'sha256_float64_le':'fixed'})
    before['dseg_map'][fixed_code]=fixed_no
    after=copy.deepcopy(before)
    after['generation_values']['ADD_PROD_W']['1']=1.03
    after['matrices'][0]['sha256_float64_le']='changed-authorized'
    after['matrices'][1]['sha256_float64_le']='changed-forbidden'
    with pytest.raises(SupplyContractError,match='DEMAND_MUTATED_FIXED_MATRIX'):
        c.assert_freeze(before,after,'GENERATION',[{'attr':'ADD_PROD_W','zone_no':1,'current':1.,'proposed':1.03}],cfg=cfg)


@pytest.mark.parametrize('defect',['old_file','empty_file','partial_then_error'])
def test_saveversion_never_accepts_stale_or_partial_bytes(tmp_path,defect):
    path=tmp_path/'state.ver';calls=[]
    if defect=='old_file':path.write_bytes(b'OLD')
    def first(p):
        calls.append('first')
        Path(p).write_bytes(b'PARTIAL' if defect=='partial_then_error' else b'')
        if defect=='partial_then_error':raise RuntimeError('DISK_ERROR')
    def second(p):calls.append('fallback')
    v=SimpleNamespace(IO=SimpleNamespace(SaveVersion=first),SaveVersion=second)
    with pytest.raises(RuntimeError,match='SAVEVERSION_'):rt.save_version(v,path)
    assert 'fallback' not in calls
    if defect=='old_file':assert not calls and path.read_bytes()==b'OLD'


def test_saveversion_legacy_fallback_only_when_no_partial_output(tmp_path):
    path=tmp_path/'fresh.ver'
    def legacy(p):Path(p).write_bytes(b'FRESH')
    v=SimpleNamespace(IO=SimpleNamespace(),SaveVersion=legacy)
    result=rt.save_version(v,path)
    assert result['size']==5 and result['sha256']==hashlib.sha256(b'FRESH').hexdigest()
