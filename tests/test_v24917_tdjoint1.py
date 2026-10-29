"""TDJOINT1 unit + native-evaluator seam regressions (offline, no live Visum)."""
from __future__ import annotations
import copy
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_td_joint_v24917 as j
import r1_15a2_td_joint_runtime_v24917 as wire
import r1_15a2_td_count_blend_v24917 as tb
import r1_15a2_demand_policy_v1 as dp
from r1_15a2_controller_v22 import atomic_json
from test_v24917_targeted_catchup import _blend_fixture

ROOT = Path(__file__).resolve().parents[1]


def make_blend(tmp_path, wc=.65, missing=False, dynamic=False):
    visum, cfg, zo, mats, live, inc, links = _blend_fixture()
    # Extend the inherited WORK-only fixture with real SERVICE attribution.
    inc["variables"].append({"family":"SERVICE","origin":1,"destination":2})
    inc["incidence"].row_idx.append(0)
    inc["incidence"].col_idx.append(1)
    inc["incidence"].values.append(7.)
    ref = NS(CONFIG={"max_fine_cdf_rmse_degradation": .01, "max_mean_error_degradation": .02},
             TARGETS={"WORK_E_C": {"matrix_nos": [9101]}, "SERV_E_C": {"matrix_nos": [9106]}},
             GROUPS=["WORK_E_C", "SERV_E_C"])
    outer = NS(cfg=cfg, v24917_last_incidence=None if missing else inc)
    bridge = NS(v=visum, outer_adapter=outer, zone_order=zo, root=tmp_path,
                read_matrix=lambda no: live[no], _v24917_frozen=not dynamic)
    blend = tb.Blend(bridge, ref, {"w_cnt":wc,"w_idp":1-wc,"joint_enabled":True})
    return blend, mats, live


def metric(j1=.04, j2=.06):
    return {"WORK_E_C": {"objective":j1,"residual":np.array([math.sqrt(j1)])},
            "SERV_E_C": {"objective":j2,"residual":np.array([math.sqrt(j2)])}}


@pytest.mark.parametrize('weight',[.35,.60,.65,1.0])
def test_reference_global_score_is_one_not_component_count(tmp_path, weight):
    b, mats, _ = make_blend(tmp_path, weight)
    m=metric(); before=copy.deepcopy(m)
    b.apply(m,mats)
    assert b.last_joint['objective']==pytest.approx(1.)
    assert b.last_joint['count_residual_copies']==1
    assert b.last_joint['w_cnt']==weight
    for k in m:
        assert m[k]['objective']==before[k]['objective']
        np.testing.assert_array_equal(m[k]['residual'],before[k]['residual'])


def test_global_count_contains_cross_component_interaction(tmp_path):
    b, mats, _ = make_blend(tmp_path)
    b.apply(metric(),mats)
    both={no:a.copy() for no,a in mats.items()}
    both[9101][0,1]+=10.; both[9106][0,1]+=12.
    out=metric(.041,.063)
    b.apply(out,both)
    dm=b.model.delta_for([9101,9106],both)
    expected=.65*b.model.Q(b.model.M_ref+dm)/b.model.Q_ref+.35*.104/.1
    assert b.last_joint['objective']==pytest.approx(expected)


@pytest.mark.parametrize('dynamic',[True,False])
def test_effective_mode_reporting(tmp_path,dynamic):
    b,mats,_=make_blend(tmp_path,dynamic=dynamic); b.apply(metric(),mats)
    assert b.last_joint['fresh_assignment_per_evaluation'] is dynamic
    assert b.last_joint['mode']==('DYNAMIC' if dynamic else 'FROZEN_PATHS')


def test_missing_incidence_is_not_survey_only_fallback(tmp_path):
    b,mats,_=make_blend(tmp_path,missing=True)
    with pytest.raises(RuntimeError,match='COUNT_INCIDENCE_MISSING'): b.apply(metric(),mats)


def test_explicit_zero_count_weight_can_be_survey_only(tmp_path):
    b,mats,_=make_blend(tmp_path,wc=0.,missing=True); b.apply(metric(),mats)
    assert b.last_joint['objective']==pytest.approx(1.)


@pytest.mark.parametrize('mode',['empty','nan','shape'])
def test_invalid_linear_map_rejected(tmp_path,mode):
    b,mats,_=make_blend(tmp_path); b.apply(metric(),mats)
    a=b.model.linear['WORK']
    if mode=='empty': b.model.linear['WORK']=tuple(np.array([]) for _ in range(4))
    if mode=='nan': b.model.linear['WORK']=(a[0],a[1],a[2],np.full(len(a[3]),np.nan))
    if mode=='shape': b.model.linear['WORK']=(a[0],a[1],a[2],np.array([]))
    with pytest.raises(RuntimeError,match='COUNT_INCIDENCE'):
        j.validate_count_model(b.model,b.ref.TARGETS,b.ref.GROUPS,.65)


@pytest.mark.parametrize('raw',[{'td_joint_enabled':'maybe'},{'td_joint_outer_isolates':'maybe'},
                                 {'td_joint_max_isolates':-1},{'td_joint_max_isolates':3},
                                 {'td_joint_max_isolates':'1.5'}])
def test_joint_options_fail_closed(raw):
    with pytest.raises(RuntimeError): dp.validate(raw)


def test_options_feature_off_default_and_weights_independent(tmp_path):
    o=dp.load_options(tmp_path,environ={})
    assert not o['td_joint_enabled'] and o['td_count_weight']==.60
    o=dp.load_options(tmp_path,environ={'R1_TD_JOINT_ENABLED':'true','R1_TD_COUNT_WEIGHT':'.60'})
    assert o['td_joint_enabled'] and o['td_count_weight']==.60
    stored=json.loads((ROOT/'R1_RUN_OPTIONS.json').read_text())
    assert stored['td_joint_enabled'] and stored['td_count_weight']==.60
    assert stored['td_max_survey_degradation']==1.25


class Stop(Exception): pass
class Marginal(Exception): pass


def toy_runner(tmp_path, objective, budget=40, iterations=1, fail=None):
    groups=['WORK_E_C','SERV_E_C']
    names=groups+['SCHOOL']
    x={k:np.array([.5,-1.]) for k in names}
    space=NS(x=x,probe={k:np.array([.05,.06]) for k in groups},
             trust={k:np.array([.25,.2]) for k in groups},
             bounds={k:np.array([[0.,4.],[-5.,2.]]) for k in groups})
    cfg={'max_iterations':iterations,'max_stagnant_iterations':2,
         'trust_radius_min':.05,'trust_shrink_rejected':.5,
         'minimum_objective_improvement':1e-10,'minimum_relative_objective_improvement':.001,
         'max_fine_cdf_rmse_degradation':.03,'max_mean_error_degradation':.05,'mean_error_floor':.02}
    outer=NS()
    ad=NS(outer_adapter=outer,restores=[])
    ad.restore_state=lambda abc,mats:ad.restores.append(copy.deepcopy(abc))
    runner=NS(space=space,adapter=ad,log=NS(root=tmp_path,summary={},event=lambda *a:None),
              evaluations=0,best=None,baseline=None,seen=[],checkpoints=[])
    runner.checkpoint=lambda state:runner.checkpoints.append(state['label'])
    def evaluate(x,label):
        if runner.evaluations>=budget: raise Stop('TD_EVALUATION_BUDGET')
        runner.evaluations+=1; runner.seen.append((label,copy.deepcopy(x)))
        if fail and runner.evaluations==2: raise fail('injected')
        f=float(objective(x))
        met={k:{'objective':.1,'fine_cdf_rmse':.1,'mean_relative_error':.1} for k in names}
        abc={9101:{'a':1.,'b':float(x['WORK_E_C'][0]),'c':-math.exp(x['WORK_E_C'][1])},
             9106:{'a':1.,'b':float(x['SERV_E_C'][0]),'c':-math.exp(x['SERV_E_C'][1])}}
        return {'x':copy.deepcopy(x),'abc':abc,'matrices':{9101:np.ones((2,2))},'metrics':met,
                'label':label,'folder':str(tmp_path),'tdjoint':{
                    'objective':f,'parts':{'F':f},'metric':'NORMALIZED_GEH2_PLUS_FINECDF512_SURROGATE',
                    'mode':'FROZEN_PATHS','w_cnt':.65,'w_idp':.35,'linear_profile_coverage':{},
                    'fresh_assignment_per_evaluation':False}}
    runner.evaluate=evaluate
    ref=NS(CONFIG=cfg,GROUPS=groups,StopRequested=Stop,MarginalGuardError=Marginal,write_json=atomic_json)
    return runner,ref


def test_probes_isolate_one_component_and_try_both_signs(tmp_path):
    r,ref=toy_runner(tmp_path,lambda x:1.)
    props=list(j.coordinate_proposals(r.space,r.space.x,ref.GROUPS,{k:1 for k in ref.GROUPS}))
    assert len(props)==8
    for key,axis,sign,x in props:
        assert sum(not np.array_equal(x[k],r.space.x[k]) for k in x)==1
        assert np.sign(x[key][axis]-r.space.x[key][axis])==sign
        np.testing.assert_array_equal(x['SCHOOL'],r.space.x['SCHOOL'])


def test_bounds_never_crossed_and_no_zero_probe(tmp_path):
    r,ref=toy_runner(tmp_path,lambda x:1.); r.space.x['WORK_E_C'][0]=0.
    props=list(j.coordinate_proposals(r.space,r.space.x,ref.GROUPS,{k:1 for k in ref.GROUPS}))
    assert len(props)==7
    assert all(x['WORK_E_C'][0]>=0 for *_,x in props)


def test_harmful_combination_rejected_good_single_retained(tmp_path):
    def objective(x):
        a=x['WORK_E_C'][0]-.5; b=x['SERV_E_C'][0]-.5
        return 1.-a-b+10000.*a*b
    r,ref=toy_runner(tmp_path,objective)
    reason=j.optimize(r,ref)
    assert reason=='MAX_ITERATIONS'
    assert j._score(r.best)==pytest.approx(.95)
    assert any('COMBINED' in label for label,_ in r.seen)
    assert sum(not np.array_equal(r.best['x'][k],r.baseline['x'][k]) for k in ref.GROUPS)==1
    assert r.adapter.restores[-1]==r.best['abc']
    assert not r.adapter.outer_adapter._tdjoint_stage['stationarity_confirmed']


def test_helpful_joint_candidate_measured_and_selected(tmp_path):
    r,ref=toy_runner(tmp_path,lambda x:1.-(x['WORK_E_C'][0]-.5)-(x['SERV_E_C'][0]-.5))
    j.optimize(r,ref)
    assert j._score(r.best)==pytest.approx(.9)
    assert 'COMBINED' in r.best['label']
    assert r.evaluations==10  # baseline + eight isolated probes + one combined


@pytest.mark.parametrize('budget',[1,2,5])
def test_partial_poll_budget_does_not_claim_stationarity(tmp_path,budget):
    r,ref=toy_runner(tmp_path,lambda x:1.-(x['WORK_E_C'][0]-.5),budget=budget)
    assert j.optimize(r,ref)=='TD_EVALUATION_BUDGET'
    assert r.evaluations==budget
    summary=r.adapter.outer_adapter._tdjoint_stage
    assert not summary['search_complete'] and summary['polls_completed']==0
    assert j._score(r.best)<=j._score(r.baseline)


def test_complete_min_radius_poll_certifies_only_configured_local_search(tmp_path):
    r,ref=toy_runner(tmp_path,lambda x:1.,budget=100,iterations=12)
    reason=j.optimize(r,ref)
    summary=r.adapter.outer_adapter._tdjoint_stage
    assert reason=='LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM'
    assert summary['search_complete'] and summary['stationarity_confirmed']
    assert summary['stationarity_scope']=='CONFIGURED_ACTIVE_COMPONENT_COORDINATE_POLL_NOT_GLOBAL'
    history=json.loads((tmp_path/'TDJOINT_SEARCH.json').read_text())['polls']
    assert history[-1]['polled_at_min_radius'] and history[-1]['complete_poll']
    assert history[-1]['native_rejections']==0


def test_iteration_limit_is_not_local_completion(tmp_path):
    r,ref=toy_runner(tmp_path,lambda x:1.,budget=100,iterations=2)
    assert j.optimize(r,ref)=='MAX_ITERATIONS'
    assert not r.adapter.outer_adapter._tdjoint_stage['stationarity_confirmed']


def test_unexpected_error_is_not_a_plateau(tmp_path):
    r,ref=toy_runner(tmp_path,lambda x:1.,fail=RuntimeError)
    with pytest.raises(RuntimeError,match='injected'): j.optimize(r,ref)


def test_native_margin_failure_restores_base_and_continues(tmp_path):
    r,ref=toy_runner(tmp_path,lambda x:1.,fail=Marginal)
    j.optimize(r,ref)
    assert len(r.adapter.restores)>=2
    report=json.loads((tmp_path/'TDJOINT_SEARCH.json').read_text())
    assert any(t['status']=='REJECTED_NATIVE_MARGIN' for t in report['polls'][0]['trials'])


@pytest.mark.parametrize('field,value',[('fine_cdf_rmse',.2),('mean_relative_error',.5),('objective',float('nan'))])
def test_guard_all_components_including_frozen(tmp_path,field,value):
    r,ref=toy_runner(tmp_path,lambda x:1.)
    base=r.evaluate(r.space.x,'B')['metrics']; after=copy.deepcopy(base)
    after['SCHOOL'][field]=value
    assert j.metric_guards(base,after,ref.CONFIG)


def test_wrap_inner_off_returns_exact_parent_object(monkeypatch):
    monkeypatch.setattr(j,'options',lambda:{'enabled':False})
    original={'old':1}; ad=NS()
    out=wire.wrap_inner(lambda *a,**k:original)(ad,{},'f',None,'root')
    assert out is original


def test_wrap_inner_corrects_frozen_mode_and_summary(tmp_path,monkeypatch):
    monkeypatch.setattr(j,'options',lambda:{'enabled':True})
    def original(ad,cfg,folder,*a,**k):
        ad._tdjoint_stage={'inner_root':str(Path(folder).resolve()),'metric':'JOINT',
            'objective_start':1.,'objective_final':.9,'objective_improvement':.1,
            'search_complete':False,'stationarity_confirmed':False,
            'fresh_assignment_and_skims_per_finecdf_evaluation':False}
        return {'stop_reason':'MAX_ITERATIONS','fresh_assignment_and_skims_per_finecdf_evaluation':True}
    out=wire.wrap_inner(original)(NS(),{},tmp_path,None,'root')
    assert out['objective_start']==1. and out['progress_continue']
    assert not out['fresh_assignment_and_skims_per_finecdf_evaluation']
    assert json.loads((tmp_path/'V24916_FINECDF_INNER_RESULT.json').read_text())==out


def test_wrap_inner_missing_stage_is_error(tmp_path,monkeypatch):
    monkeypatch.setattr(j,'options',lambda:{'enabled':True})
    with pytest.raises(RuntimeError,match='MISSING_OR_STALE'):
        wire.wrap_inner(lambda *a,**k:{})(NS(),{},tmp_path,None,'r')


def outer_harness(tmp_path,monkeypatch,accept=None,iz=False):
    import r1_15a2_intrazonal_penalty_v24917 as ip
    monkeypatch.setattr(ip,'_STAGE',{'pending':True} if iz else {})
    monkeypatch.setattr(j,'options',lambda:{'enabled':True,'outer_isolates':True,'max_isolates':2})
    # Launch tests reload modules; patch the instance imported by realization.
    import r1_15a2_td_count_blend_v24917 as live_tb
    monkeypatch.setattr(live_tb,'options',lambda:{'w_cnt':.65,'w_idp':.35})
    rows=[{'component':'WORK_E_C','candidate_b':1.,'candidate_c':-1.},
          {'component':'SERV_E_C','candidate_b':2.,'candidate_c':-2.}]
    ad=NS(_tdjoint_stage={'w_cnt':.65,'w_idp':.35,
        'final_abc':{'9101':{'b':1.,'c':-1.},'9106':{'b':2.,'c':-2.}}})
    before={'state_hash':'PARENT'}; diag={'PARENT':True}; calls=[]
    def orig(adapter,cfg,folder,control,b,d,rs):
        assert b==before and d==diag
        if len(rs)==1: assert cfg['coupled_demand']['finecdf_td']['realization_backtracking_scales']==[1.]
        calls.append([x['component'] for x in rs])
        take=bool(accept and len(rs)==1 and rs[0]['component']==accept)
        return (rs if take else [], {'state_hash':'NEW'} if take else b, d,.001,
                {'status':'REALIZED' if take else 'SOFT_REFERENCE_PLATEAU','attempts':[]})
    ctrl=NS(atomic_json=atomic_json)
    args=(ad,{},tmp_path,NS(checkpoint=lambda *a,**k:None),before,diag,rows)
    return wire.wrap_realization(orig,ctrl),args,calls


def test_outer_ablation_after_verified_combined_plateau(tmp_path,monkeypatch):
    fn,args,calls=outer_harness(tmp_path,monkeypatch,accept='SERV_E_C')
    out=fn(*args)
    assert calls==[['WORK_E_C','SERV_E_C'],['SERV_E_C']]
    assert [r['component'] for r in out[0]]==['SERV_E_C']
    assert len(out[4]['tdjoint_attempt_groups'])==2


def test_outer_all_rejected_remains_parent_and_bounded(tmp_path,monkeypatch):
    fn,args,calls=outer_harness(tmp_path,monkeypatch)
    out=fn(*args)
    assert not out[0] and out[1]==args[4] and len(calls)==3
    assert out[4]['status']=='SOFT_REFERENCE_PLATEAU'


def test_outer_pending_penalty_uses_legacy_path_only(tmp_path,monkeypatch):
    fn,args,calls=outer_harness(tmp_path,monkeypatch,iz=True)
    fn(*args); assert len(calls)==1


def test_outer_weight_change_and_target_mismatch_block_before_write(tmp_path,monkeypatch):
    fn,args,calls=outer_harness(tmp_path,monkeypatch)
    args[0]._tdjoint_stage['w_cnt']=.6
    with pytest.raises(RuntimeError,match='WEIGHT_CHANGED'):fn(*args)
    assert not calls
    args[0]._tdjoint_stage['w_cnt']=.65
    args[-1][0]['candidate_b']=3.
    with pytest.raises(RuntimeError,match='TARGET_PLAN_MISMATCH'):fn(*args)
    assert not calls


def test_feature_off_keeps_original_realization_identity(tmp_path,monkeypatch):
    monkeypatch.setattr(j,'options',lambda:{'enabled':False})
    result=([],{}, {},None,{'legacy':True})
    got=wire.wrap_realization(lambda *a:result,NS())(NS(),{},tmp_path,None,{}, {}, [])
    assert got is result


def test_loader_keeps_sealed_authority_bytes_and_uses_joint_subclass(monkeypatch):
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_active_controller_patch_v24916p2c as acp
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    for module,name in [(bm,'load_reference'),(bm,'run_finecdf_inner'),(ctrl,'run_finecdf_inner'),
                        (ctrl,'_realize_finecdf_td'),(acp,'targeted_run_finecdf_inner')]:
        monkeypatch.setattr(module,name,getattr(module,name))
    monkeypatch.setattr(j,'options',lambda:{'enabled':True,'outer_isolates':True,'max_isolates':2})
    s=wire.install(ctrl,print_fn=lambda *a:None)
    fine={'reference_script':'reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py',
          'reference_sha256':'fcdfa535940296e6cc793b6416c7c0a56c18aae8d5d20beddb064a170c673ff5',
          'reference_script_id':'R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_V1_9_20261017'}
    ref,_,sha=bm.load_reference(ROOT,fine)
    assert ref.Runner.__name__=='JointRunner' and sha==fine['reference_sha256']
    assert s['outer_acceptance_modified'] is False
    assert getattr(acp.targeted_run_finecdf_inner,'_tdjoint1',False)


def test_real_sealed_runner_dynamic_metrics_blend_and_checkpoint(tmp_path):
    """Real v1.9 evaluate, parameter space, margins and NPZ checkpoint; fake native TD only."""
    import r1_15a2_finecdf_bridge_v24916 as bm
    fine={'reference_script':'reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py',
          'reference_sha256':'fcdfa535940296e6cc793b6416c7c0a56c18aae8d5d20beddb064a170c673ff5',
          'reference_script_id':'R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_V1_9_20261017'}
    ref,_,_=bm.load_reference(ROOT,fine)
    # This test constructs its own reference instance. No installed-class globals.
    if ref.Runner.__name__=='JointRunner': ref.Runner=ref.Runner.__bases__[0]
    ref.GROUPS=['WORK_E_C','SERV_E_C']
    ref.CONFIG.update(max_iterations=1,max_td_evaluations=20,save_versions=False)
    visum,cfg,zo,mats,live,inc,_=_blend_fixture()
    inc['variables'].append({'family':'SERVICE','origin':1,'destination':2})
    inc['incidence'].row_idx.append(0);inc['incidence'].col_idx.append(1);inc['incidence'].values.append(7.)
    seed=np.array([[20.,10.,1.],[10.,20.,1.],[1.,1.,20.]])
    for n in ref.MUTABLE_NOS: live[n+100]=seed*.5
    live[9221]=seed*2.5;live[9222]=seed*2.5;live[9225]=seed*.5;live[9226]=seed*3
    dist=np.array([[1.,5.,40.],[10.,2.,30.],[30.,50.,3.]])
    epoch=NS(epoch=1,epoch_hash='frozen',family_distance={
        'WORK':dist,'SERVICE':dist,'LONG':np.array([[110.,130.,190.],[130.,140.,160.],[150.,160.,120.]])})
    class Native:
        def __init__(self):
            self.entry_abc={n:{'a':1.,'b':1.,'c':-1.} for n in ref.BY_NO}
            self.current=copy.deepcopy(self.entry_abc);self.protected={9697:dist}
            self.v=visum;self.outer_adapter=NS(cfg=cfg,v24917_last_incidence=inc)
            self.zone_order=zo;self.root=tmp_path;self._v24917_frozen=True
            self.dynamic_skim_epoch=epoch;self.ops=[NS(AttValue=lambda _:0)];self.td_index=1
            self.executions=0;self.restores=0
        def set_abc(self,abc):self.current=copy.deepcopy(abc);return self.current
        def read_abc(self):return copy.deepcopy(self.current)
        def read_matrix(self,no):return live[no]
        def execute(self):
            self.executions+=1
            out={n:seed.copy() for n in ref.MUTABLE_NOS}
            for n in (9101,9106):
                d=.5*(self.current[n]['b']-1.)+.1*math.log(-self.current[n]['c'])
                out[n][:2,:2]+=np.array([[d,-d],[-d,d]])
            return out
        def guard_protected(self,full=False):
            assert self.current[9116]==self.entry_abc[9116]
            for n in self.current:
                assert self.current[n]['a']==1.
                if n not in (9101,9106):assert self.current[n]==self.entry_abc[n]
        def restore_state(self,abc,matrices):
            self.restores+=1;self.set_abc(abc);self.execute();self.guard_protected(True)
        def write_matrix(self,*a):raise AssertionError('DIRECT_OD_WRITE')
    native=Native()
    blend=tb.Blend(native,ref,{'w_cnt':.65,'w_idp':.35,'joint_enabled':True})
    class Metrics:
        def __init__(self,*a):
            self.impl=bm.DynamicFamilyMetrics(native,ref)
            self.impl._v24917_blend_state=blend
        def evaluate(self,arrays):
            # Calling each real per-target evaluator avoids any process-level
            # wrapper installed by unrelated legacy tests.
            out={k:self.impl._evaluate_one(k,epoch.family_distance[self.impl._family(k)],arrays)
                 for k in ref.TARGETS}
            return blend.apply(out,arrays)
    ref.Metrics=Metrics
    runner=j.make_runner(ref.Runner,ref)(native,ref.Log(tmp_path))
    assert runner.optimize()=='MAX_ITERATIONS'
    assert runner.baseline['tdjoint']['objective']==pytest.approx(1.)
    assert len(runner.best['metrics'])==12
    assert (tmp_path/'BEST_STATE.json').is_file()
    assert native.restores>=1 and native.executions>=runner.evaluations
    assert runner.best['tdjoint']['count_residual_copies']==1


def test_count_model_uses_both_signs_and_excludes_validation(tmp_path):
    b,mats,_=make_blend(tmp_path)
    b.model.O[1]=100.  # second profile is overpredicted, first is underpredicted
    b.apply(metric(),mats)
    r=b.model.q(b.model.M_ref)
    assert r[0]<0 and r[1]>0
    visum,cfg,zo,_,_,inc,_=_blend_fixture()
    cfg['api_approved_observations'][1]['role']='VALIDATION'
    model=tb.CountModel(visum,cfg,zo,inc)
    assert len(model.profiles)==1


def test_references_and_protected_source_still_byte_identical():
    import hashlib
    base=json.loads((ROOT/'DIAGFAST_V1_BASE_MANIFEST.json').read_text())['files']
    assert len(base)==1059
    assert all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h for n,h in base.items())


@pytest.mark.parametrize('previous',[None,'0.65'])
@pytest.mark.parametrize('fail',[False,True])
def test_weight_launcher_scopes_environment_and_restores(tmp_path,monkeypatch,previous,fail):
    import os
    if previous is None: monkeypatch.delenv('R1_TD_COUNT_WEIGHT',raising=False)
    else: monkeypatch.setenv('R1_TD_COUNT_WEIGHT',previous)
    spec=importlib.util.spec_from_file_location('test_weight_launcher',ROOT/'02_SPUSTIT_V24917_TDJOINT1_60_40.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    token=object();mod.Visum=token
    calls=[]
    def main():
        calls.append((dp.load_options(ROOT)['td_count_weight'],parent.Visum))
        if fail: raise RuntimeError('injected')
        return 123
    parent=NS(main=main)
    monkeypatch.setattr(mod,'load_parent',lambda:parent)
    if fail:
        with pytest.raises(RuntimeError,match='injected'):mod.main()
    else: assert mod.main()==123
    assert calls==[(.60,token)]
    assert os.environ.get('R1_TD_COUNT_WEIGHT')==previous

@pytest.mark.parametrize('mode',['accept_isolated','reject_all','broken_rollback'])
def test_real_controller_realization_and_rollback_order(tmp_path,monkeypatch,mode):
    """Real outer interpolation/freeze/rollback; native COM and decisions scripted."""
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_intrazonal_penalty_v24917 as iz
    from r1_15a2_supply import canonical_hash
    from test_v2490_td_soft_reference import _soft_cfg, Control
    class Adapter:
        def __init__(self):
            self.bc={'WORK_E_C':(1.,-.1),'SERV_E_C':(2.,-.2)}
            self.assignments=[];self.restores=[];self.gates=[];self.result_token=0
            self._tdjoint_stage={'w_cnt':.65,'w_idp':.35,'final_abc':{
                '9101':{'a':1.,'b':1.2,'c':-.12},'9106':{'a':1.,'b':2.2,'c':-.22}}}
        def snapshot(self):
            rows=[{'component':k,'current_b':v[0],'current_c':v[1],'status':'OK'} for k,v in sorted(self.bc.items())]
            s={'td_values':rows,'td_hash':canonical_hash(rows),'fixed_link_hash':'F','dseg_hash':'D',
               'operations_hash':'O','addval_hash':'A','generation_hash':'G','addval1':{},'matrices':[], 'dseg_map':{}}
            return dict(s,state_hash=canonical_hash(s))
        def apply_td(self,rows):
            for r in rows:self.bc[r['component']]=(r['candidate_b'],r['candidate_c'])
        def assign(self,folder,*,supply_only):
            self.assignments.append(copy.deepcopy(self.bc));return .001
        def diagnostics(self,folder,label):
            return {'d12':{'rows':[]},'d11':{'summary':{}},'signals':{},'token':self.result_token}
        def parameter_persistence(self,*a):pass
        def block_gate(self,block,before,after,rows):
            self.gates.append(copy.deepcopy(rows))
            accepted=mode=='accept_isolated' and len(rows)==1 and rows[0]['component']=='SERV_E_C'
            return {'accepted':accepted,'reasons':[] if accepted else ['SOFT_REFERENCE_TRADEOFF_GUARD']}
    ad=Adapter();before=ad.snapshot();diag=ad.diagnostics(None,'BASE')
    def restore(adapter,parent,rows,folder=None):
        adapter.bc={r['component']:(r['current_b'],r['current_c']) for r in parent['td_values']}
        adapter.restores.append(copy.deepcopy(adapter.bc))
        if mode=='broken_rollback' and 'PLATEAU_ROLLBACK' in str(folder):adapter.result_token=1
    monkeypatch.setattr(ctrl,'restore_td_parameters',restore)
    monkeypatch.setattr(ctrl,'diagnostic_hash',canonical_hash)
    monkeypatch.setattr(j,'options',lambda:{'enabled':True,'outer_isolates':True,'max_isolates':2})
    # Launch tests reload modules; patch the instance imported by realization.
    import r1_15a2_td_count_blend_v24917 as live_tb
    monkeypatch.setattr(live_tb,'options',lambda:{'w_cnt':.65,'w_idp':.35})
    monkeypatch.setattr(iz,'_STAGE',{})
    rows=[{'component':'WORK_E_C','candidate_b':1.2,'candidate_c':-.12},
          {'component':'SERV_E_C','candidate_b':2.2,'candidate_c':-.22}]
    # Other tests install process-global TDROLLBACK1 decorators into the
    # imported controller.  This fixture targets the original realized TD
    # algorithm; unwrap any independently installed runtime adapters so the
    # test is reproducible both alone and in the full suite.
    import inspect
    monkeypatch.setattr(ctrl, '_rollback_td_all', inspect.unwrap(ctrl._rollback_td_all))
    run=wire.wrap_realization(inspect.unwrap(ctrl._realize_finecdf_td),ctrl)
    if mode=='broken_rollback':
        with pytest.raises(Exception,match='ROLLBACK_NOT_IDENTICAL'):
            run(ad,_soft_cfg(),tmp_path,Control(),before,diag,rows)
        assert len(ad.gates)==3 # no isolated write before successful full rollback
        assert not (tmp_path/'ISOLATED_01_SERV_E_C').exists()
        return
    got=run(ad,_soft_cfg(),tmp_path,Control(),before,diag,rows)
    assert [len(r) for r in ad.gates[:3]]==[2,2,2]
    assert ad.assignments[3]=={'WORK_E_C':(1.,-.1),'SERV_E_C':(2.,-.2)}
    assert ad.assignments[4]['WORK_E_C']==(1.,-.1) # verified parent before isolated SERVICE
    if mode=='accept_isolated':
        assert len(ad.gates)==4 and [r['component'] for r in got[0]]==['SERV_E_C']
    else:
        assert len(ad.gates)==5 and not got[0] and got[1]==before
        assert ad.snapshot()==before and ad.diagnostics(None,'FINAL')==diag
