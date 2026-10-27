"""TDROLLBACKFIX1: real diagnostic schemas, unchanged guards and verified continuation."""
import copy
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import r1_15a2_parent_equivalence_v24917 as eq
import r1_15a2_td_rollback_tolerant_v24917 as tr
import r1_15a2_multiblock as mb
from r1_15a2_supply import SupplyContractError
from r1_15a2_controller_v22 import atomic_json
from r1_15a2_dynamic_skim_v24916p2c import SCHEMA, REQUIRED_NATIVE_DSEGS, _hash
from test_v24917_genfix2 import diagnostics, ArrayAdapter
from test_v2490_td_soft_reference import SoftAdapter, Control, _restore, _soft_cfg

def dynamic_diag(epoch=1):
    d=diagnostics(); sha=lambda s: hashlib.sha256(s.encode()).hexdigest()
    meta={k:{'matrix_no':700+i,'matrix_code':'DIS','dseg_code':k,'canonical_dseg':k,
             'values_sha256':sha(k),'shape':[2,2],'unit':'km'} for i,k in enumerate(REQUIRED_NATIVE_DSEGS)}
    fam={k:sha(k) for k in ('WORK','SERVICE','LONG','FOREIGN')}
    payload={'schema':SCHEMA,'epoch':epoch,'assignment_epoch':epoch,'assignment_token':'assignment-%s'%epoch,
             'zone_order_sha256':sha('zones'),'operation_positions':list(range(31,37)),
             'matrix_hashes':{k:v['values_sha256'] for k,v in meta.items()},'family_hashes':fam}
    authority={k:v for k,v in payload.items() if k!='matrix_hashes'}
    authority.update(matrix_meta_by_dseg=meta,epoch_hash=_hash(payload),role='ACTIVE_TD_CALIBRATION_DISTANCE_AUTHORITY',
                     static_r1_osrm_dist_km_role='REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION',source='VISUM_FRESH_ASSIGNMENT_PATHS_PRT_DIS')
    s=d['d11']['summary']
    s['dynamic_distance_authority']=authority
    s['dist_classification_matrix']={'code':'VISUM_DYNAMIC_ASSIGNMENT_DIS_KM','classification':'DYNAMIC_ASSIGNMENT_PATH_VOLUME_WEIGHTED_DIS',
        'assignment_epoch':epoch,'skim_epoch':epoch,'skim_epoch_hash':authority['epoch_hash'],
        'zone_order_sha256':authority['zone_order_sha256'],'family_hashes':fam,'readback':{'nonfinite_cells':0,'negative_cells':0}}
    s['component_dist_summary_rows'][0].update(distance_authority='DYNAMIC_ASSIGNMENT_DIS_KM',dynamic_distance_family='WORK',
        dynamic_skim_epoch=epoch,dynamic_skim_epoch_hash=authority['epoch_hash'])
    d['dynamic_skim_epoch']=copy.deepcopy(authority)
    d['d11']['idp_gate']={'passes':True,'status':'PASS_ATOMIC_IDP_DYNAMIC_ASSIGNMENT_SKIM','dynamic_assignment_epoch':epoch,
        'dynamic_skim_epoch':epoch,'dynamic_skim_epoch_hash':authority['epoch_hash']}
    return d


def long_diagnostic():
    d = diagnostics()
    signals = mb.build_td_signals([], [], [], config={})
    d['signals'] = {k: v for k, v in signals.items() if k.startswith('LONG_')}
    return d


def rehash(d):
    authority = d['d11']['summary']['dynamic_distance_authority']
    payload = {k: authority[k] for k in ('schema','epoch','assignment_epoch','assignment_token',
               'zone_order_sha256','operation_positions','family_hashes')}
    payload['matrix_hashes'] = {k: authority['matrix_meta_by_dseg'][k]['values_sha256'] for k in REQUIRED_NATIVE_DSEGS}
    authority['epoch_hash'] = _hash(payload)
    cls = d['d11']['summary']['dist_classification_matrix']
    cls.update(assignment_epoch=authority['assignment_epoch'], skim_epoch=authority['epoch'],
               skim_epoch_hash=authority['epoch_hash'], family_hashes=copy.deepcopy(authority['family_hashes']),
               zone_order_sha256=authority['zone_order_sha256'])
    for r in d['d11']['summary']['component_dist_summary_rows']:
        r.update(dynamic_skim_epoch=authority['epoch'], dynamic_skim_epoch_hash=authority['epoch_hash'])
    d['dynamic_skim_epoch'] = copy.deepcopy(authority)
    d['d11']['idp_gate'].update(dynamic_skim_epoch=authority['epoch'], dynamic_assignment_epoch=authority['assignment_epoch'],
                              dynamic_skim_epoch_hash=authority['epoch_hash'])


def test_real_producer_inactive_long_equal_to_itself():
    d=long_diagnostic()
    assert len(d['signals']) == 5
    assert all(math.isinf(v['objective']) for v in d['signals'].values())
    assert eq.compare_diagnostics(d, copy.deepcopy(d))['passes']
    assert all(math.isinf(v['objective']) for v in d['signals'].values())  # no mutation


@pytest.mark.parametrize('value',[float('nan'),float('-inf'),0.,100.])
def test_inactive_long_sentinel_may_not_hide_invalid_or_changed_objective(value):
    b=long_diagnostic();a=copy.deepcopy(b)
    a['signals']['LONG_E_C']['objective']=value
    assert not eq.compare_diagnostics(b,a)['passes']


@pytest.mark.parametrize('change',['calibratable','authority','reason','family','component','volume'])
def test_inactive_long_status_and_data_remain_protected(change):
    b=long_diagnostic();a=copy.deepcopy(b);s=a['signals']['LONG_E_C']
    if change=='calibratable':s['calibratable']=True
    elif change=='authority':s['authority_status']='ACTIVE_COMPONENT_DIST_TARGET'
    elif change=='reason':s['policy_reason']='ACTIVE'
    elif change=='family':s['family']='WORK'
    elif change=='component':s['component']='OTHER'
    else:s['total_volume']=10000.
    assert not eq.compare_diagnostics(b,a)['passes']


@pytest.mark.parametrize('domain',['signal','active_long','11d','count'])
def test_identical_nonfinite_metrics_are_not_valid_measurements(domain):
    b=diagnostics()
    if domain=='signal':b['signals']['WORK']['cdf_rmse']=float('inf')
    elif domain=='active_long':
        b=long_diagnostic();b['signals']['LONG_E_C']['calibratable']=True
    elif domain=='11d':b['d11']['summary']['component_dist_summary_rows'][0]['mean']=float('inf')
    else:b['d12']['rows'][0]['model']=float('nan')
    assert not eq.compare_diagnostics(b,copy.deepcopy(b))['passes']


def test_new_epoch_same_byte_content_and_metrics_is_equivalent():
    b=dynamic_diag(1);a=dynamic_diag(5);saved=copy.deepcopy(a)
    assert eq.compare_diagnostics(b,a)['passes']
    assert a == saved
    assert b['dynamic_skim_epoch']['epoch_hash'] != a['dynamic_skim_epoch']['epoch_hash']


@pytest.mark.parametrize('change',['matrix','family','zone','unit','shape','operation','readback','mean','status','unknown_epoch'])
def test_dynamic_semantics_are_not_waived_by_epoch_normalization(change):
    b=dynamic_diag(1);a=dynamic_diag(2);s=a['d11']['summary'];auth=s['dynamic_distance_authority']
    if change=='matrix':auth['matrix_meta_by_dseg']['NATIVE_CW']['values_sha256']='1'*64
    elif change=='family':auth['family_hashes']['WORK']='1'*64
    elif change=='zone':auth['zone_order_sha256']='1'*64
    elif change=='unit':auth['matrix_meta_by_dseg']['NATIVE_CW']['unit']='min'
    elif change=='shape':auth['matrix_meta_by_dseg']['NATIVE_CW']['shape']=[3,3]
    elif change=='operation':auth['operation_positions'][-1]=44
    elif change=='readback':s['dist_classification_matrix']['readback']['nonfinite_cells']=1
    elif change=='mean':s['component_dist_summary_rows'][0]['mean']+=1
    elif change=='status':s['final_status']='REVIEW_ERROR'
    else:s['unknown_epoch']=2;b['d11']['summary']['unknown_epoch']=1
    rehash(a)
    assert not eq.compare_diagnostics(b,a)['passes']


@pytest.mark.parametrize('change',['hash','top','component','classification','gate','missing_authority','no_top'])
def test_dynamic_epoch_must_be_internally_coherent(change):
    b=dynamic_diag(1);a=dynamic_diag(2);s=a['d11']['summary']
    if change=='hash':s['dynamic_distance_authority']['epoch_hash']='0'*64
    elif change=='top':a['dynamic_skim_epoch']['epoch']=1
    elif change=='component':s['component_dist_summary_rows'][0]['dynamic_skim_epoch']=1
    elif change=='classification':s['dist_classification_matrix']['skim_epoch']=1
    elif change=='gate':a['d11']['idp_gate']['passes']=False
    elif change=='missing_authority':s.pop('dynamic_distance_authority')
    else:a.pop('dynamic_skim_epoch')
    assert not eq.compare_diagnostics(b,a)['passes']


def test_full_parent_checks_live_dynamic_manager(tmp_path):
    ad=ArrayAdapter();b=dynamic_diag(1);a=dynamic_diag(2);state=ad.snapshot()
    ad.v24916_dynamic_skims=NS(require_current=lambda:NS(summary=lambda:dynamic_diag(3)['dynamic_skim_epoch']))
    p=eq.verify_parent(ad,state,state,b,a)
    assert not p['passes'] and 'LIVE_DYNAMIC_SKIM_EPOCH_DIAGNOSTICS_MISMATCH' in p['parameter_differences']
    ad.v24916_dynamic_skims=NS(require_current=lambda:(_ for _ in ()).throw(RuntimeError('STALE_ASSIGNMENT')))
    assert not eq.verify_parent(ad,state,state,b,a)['passes']


def test_full_parent_success_is_persisted_and_returns_live_diag(tmp_path):
    ad=ArrayAdapter();before=ad.snapshot();baseline=dynamic_diag(1);ad.diag=dynamic_diag(2)
    ad.path_epoch_accepts=6
    ctrl=NS(_td_expected_freeze=lambda *a:None,atomic_json=atomic_json)
    def original(*args):
        atomic_json(tmp_path/'ROLLBACK_ALL_TD_RESULT.json',{'passes':True,'gap':.004,'snapshot_equal':True,'diagnostic_equal':True})
        return ad.snapshot(),copy.deepcopy(ad.diag)
    with eq.parent_scope(ad,before,tmp_path):
        ad.path_epoch_accepts=7
        state,diag=tr.wrap_rollback_td_all(original,ctrl)(ad,before,baseline,tmp_path,{})
    out=json.loads((tmp_path/'ROLLBACK_ALL_TD_RESULT.json').read_text())
    assert out['passes'] and out['legacy_result']['passes']
    assert out['parent_equivalence']['passes'] and out['next_generation_permitted']
    assert ad.path_epoch_accepts==6
    assert diag['dynamic_skim_epoch']['epoch']==2
    assert baseline['dynamic_skim_epoch']['epoch']==1


def test_failed_full_proof_overrides_legacy_pass_and_preserves_details(tmp_path):
    ad=ArrayAdapter();before=ad.snapshot();baseline=diagnostics();ad.diag['signals']['WORK']['cdf_rmse']=2.
    ctrl=NS(_td_expected_freeze=lambda *a:None,atomic_json=atomic_json)
    def original(*args):
        atomic_json(tmp_path/'ROLLBACK_ALL_TD_RESULT.json',{'passes':True,'gap':.004})
        return ad.snapshot(),copy.deepcopy(ad.diag)
    with pytest.raises(SupplyContractError,match='FULL_PARENT_PROOF_FAILED:signals.WORK.cdf_rmse') as err:
        tr.wrap_rollback_td_all(original,ctrl)(ad,before,baseline,tmp_path,{})
    out=json.loads((tmp_path/'ROLLBACK_ALL_TD_RESULT.json').read_text())
    assert out['passes'] is False and out['legacy_result']['passes'] is True
    assert out['next_generation_permitted'] is False
    assert Path(err.value.evidence_path).is_file()
    assert not err.value.parent_equivalence['passes']


def test_cached_equal_snapshot_does_not_waive_fresh_live_read(tmp_path):
    ad=ArrayAdapter();before=ad.snapshot();baseline=diagnostics()
    ad.generation_guard_snapshot=lambda:dict(before, generation_hash='CHANGED')
    ctrl=NS(_td_expected_freeze=lambda *a:None,atomic_json=atomic_json)
    with pytest.raises(SupplyContractError,match='LIVE_SNAPSHOT_NOT_EQUAL'):
        tr.wrap_rollback_td_all(lambda *args:(before,baseline),ctrl)(ad,before,baseline,tmp_path,{})


def load_controller():
    path=Path(__file__).resolve().parents[1]/'r1_15a2_overnight_controller_coupled_v24915p2_force100.py'
    spec=importlib.util.spec_from_file_location('_tdrollbackfix1_controller_test',path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DynamicAdapter(SoftAdapter):
    def __init__(self):
        super().__init__(always_reject=True)
        self.epoch=1
        self.v24917_status={}
        self.v24916_dynamic_skims=NS(require_current=lambda:NS(summary=lambda:dynamic_diag(self.epoch)['dynamic_skim_epoch']))
    def assign(self,folder,*,supply_only):
        value=super().assign(folder,supply_only=supply_only)
        self.epoch+=1
        return value
    def diagnostics(self,folder,label):
        d=dynamic_diag(self.epoch)
        d['signals'].update(long_diagnostic()['signals'])
        return d


def test_real_active_td_dispatch_rejects_rolls_back_then_runs_next_cycle(tmp_path,monkeypatch):
    import r1_15a2_active_controller_patch_v24916p2c as active
    import r1_15a2_demand_policy_v1 as dp
    c=load_controller();active.install(c)
    c._rollback_td_all=tr.wrap_rollback_td_all(c._rollback_td_all,c)
    monkeypatch.setattr(c,'restore_td_parameters',_restore)
    def inner(*a,**kw):
        return {'changed_rows':[{'component':'WORK_E_C','after_b':.2,'after_c':-.4}],
                'stop_reason':'MAX_ITERATIONS','progress_continue':True,'search_complete':False}
    monkeypatch.setattr(active,'targeted_run_finecdf_inner',inner)
    policy=dp.DemandPolicy(dp.validate({'td_policy':'ALWAYS'}))
    policy.last_generation_complete=True
    wrapped=dp.wrap_td(c._finecdf_td_once,policy,c)
    ad=DynamicAdapter();cfg=_soft_cfg((1.,.5));state=ad.snapshot();diag=ad.diagnostics(tmp_path,'BASE')
    for cycle in (1,2):
        changed,state,diag,rec=wrapped(ad,cfg,tmp_path/str(cycle),Control(),state,diag,tmp_path,outer_cycle=cycle)
        assert not changed and rec['status']=='FINECDF_TD_PLATEAU'
        assert rec['td_realization_complete'] and rec['inner']['progress_continue']
        assert state==ad.snapshot() and ad.b==0 and ad.c==-.1
        assert not policy.stop_due()
    assert len(ad.assign_calls)==6  # two candidates + verified restore, twice
    assert ad.epoch==7
    assert len(list(tmp_path.rglob('TDROLLBACKFIX1_PARENT_PROOF.json')))==2


def test_safetyfix1_score_failure_and_fixed_rollback_continue_together(tmp_path,monkeypatch):
    import r1_15a2_active_controller_patch_v24916p2c as active
    import r1_15a2_demand_policy_v1 as dp
    import r1_15a2_trial_adapter_v24917 as ta
    import r1_15a2_td_count_blend_v24917 as blend
    c=load_controller();active.install(c);c._rollback_td_all=tr.wrap_rollback_td_all(c._rollback_td_all,c)
    monkeypatch.setattr(c,'restore_td_parameters',_restore)
    monkeypatch.setattr(active,'targeted_run_finecdf_inner',lambda *a,**kw:{'changed_rows':[
        {'component':'WORK_E_C','after_b':.2,'after_c':-.4}],'search_complete':True,'stop_reason':'LOCAL_PLATEAU'})
    monkeypatch.setattr(ta._V24916ActiveAdapter,'block_gate',lambda *a,**kw:{'accepted':True,'reasons':[]})
    monkeypatch.setattr(blend,'outer_decision',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('SCORE_READ_FAILED')))
    ad=DynamicAdapter()
    gate=ta.VisumAdapter.__new__(ta.VisumAdapter)
    gate.v24917_status=ad.v24917_status
    gate.cfg={}
    ad.block_gate=gate.block_gate
    policy=dp.DemandPolicy(dp.validate({'td_policy':'ALWAYS'}));policy.last_generation_complete=True
    wrapped=dp.wrap_td(c._finecdf_td_once,policy,c)
    state=ad.snapshot();diag=ad.diagnostics(tmp_path,'BASE')
    changed,after,d,rec=wrapped(ad,_soft_cfg((1.,.5)),tmp_path,Control(),state,diag,tmp_path,outer_cycle=1)
    assert not changed and after==state and rec['td_realization_complete']
    assert rec['inner']['progress_continue'] and not rec['inner']['search_complete']
    assert 'TD_SHARED_OBJECTIVE_UNAVAILABLE' in rec['incomplete_search_reasons']
    assert ad.v24917_status['td_blend_outer_failures']==2 and not policy.stop_due()
