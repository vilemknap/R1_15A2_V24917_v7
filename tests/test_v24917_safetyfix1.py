"""SAFETYFIX1 regressions: reject unsafe TD trials, continue valid run; honest evidence."""
from __future__ import annotations
from types import SimpleNamespace
import pytest


def test_td_outer_error_rejects_only_trial_and_next_trial_can_pass(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as ta
    import r1_15a2_td_count_blend_v24917 as blend
    parent = ta.VisumAdapter.__mro__[1]
    monkeypatch.setattr(parent, 'block_gate', lambda *a, **kw: {'accepted': True, 'reasons': [], 'policy': 'PARENT'})
    def fail(*a, **kw): raise RuntimeError('joint count read unavailable')
    monkeypatch.setattr(blend, 'outer_decision', fail)
    adapter=ta.VisumAdapter.__new__(ta.VisumAdapter)
    adapter.cfg = {}; adapter.v24917_status={}
    first=adapter.block_gate('TD_FINECDF_SOFT_REFERENCE',{}, {}, [])
    assert first['accepted'] is False
    assert 'V24917_TD_SHARED_OBJECTIVE_UNAVAILABLE' in first['reasons']
    assert 'REJECT_CURRENT_TRIAL' in first['v24917_td_blend_recovery']
    assert adapter.v24917_status['td_blend_outer_failures']==1
    # A fresh valid calculation must be allowed in the same run.
    monkeypatch.setattr(blend, 'outer_decision', lambda decision,*args,**kw: dict(decision, v24917_td_joint_ok=True))
    second=adapter.block_gate('TD_FINECDF_SOFT_REFERENCE',{}, {}, [])
    assert second['accepted'] is True and second['v24917_td_joint_ok']
    # All other block gates keep their established parent semantics.
    other=adapter.block_gate('SUPPLY_ADDVAL1',{}, {}, [])
    assert other['accepted'] is True


def _targets():
    return [{'component':n,'family':f,'target_status':'ACTIVE_COMPONENT_DIST_TARGET',
             'l1_distance_half':l1,'rmse_share':.05,'mean_delta_model_minus_target':1.}
            for f, nn in [('WORK',[('WORK_E_C',.1),('WORK_noE_noC',.4)]),
                          ('SERVICE',[('SERV_E_C',.7),('SERV_E_noC',.3)])]
            for n,l1 in nn]


def _cfg():
    return {'td':{'families':['WORK','SERVICE'],'distance_bin_edges_km':[5.,20.],
                  'max_active_components_per_family':1,'max_active_components_total':2,
                  'minimum_alignment_score':0.}}


def test_no_flowbundle_evidence_uses_global_survey_not_alphabetical_targeting():
    from r1_15a2_demand_evidence_v24916 import build_td_targeting
    from r1_15a2_active_demand_evidence_v24917 import safe_td_target_plan
    plan=safe_td_target_plan(build_td_targeting([], _targets(), _cfg()))
    assert plan['status']=='GLOBAL_IDP_FALLBACK'
    assert plan['reason']=='NO_POSITIVE_FLOWBUNDLE_EVIDENCE'
    assert plan['active_components']==[]
    assert plan['global_11d_evaluation_required']
    assert all(r['alignment_score']==0 for r in plan['alignment_rows'])


def test_one_family_without_evidence_is_not_falsely_selected():
    from r1_15a2_demand_evidence_v24916 import build_td_targeting
    from r1_15a2_active_demand_evidence_v24917 import safe_td_target_plan
    flow=[{'family':'WORK','targeting_eligible':True,'flowbundle_volume':100.,
           'residual':20.,'distance_km':10.},
          {'family':'SERVICE','targeting_eligible':True,'flowbundle_volume':100.,
           'residual':0.,'distance_km':10.}]
    plan=safe_td_target_plan(build_td_targeting(flow,_targets(),_cfg()))
    assert plan['status']=='ACTIVE'
    assert plan['active_components']==['WORK_noE_noC']
    assert plan['targeting_evidence_families']==['WORK']


def test_zero_11d_error_never_masquerades_as_positive_component_evidence():
    from r1_15a2_demand_evidence_v24916 import build_td_targeting
    from r1_15a2_active_demand_evidence_v24917 import safe_td_target_plan
    flow=[{'family':'WORK','targeting_eligible':True,'flowbundle_volume':100.,
           'residual':20.,'distance_km':10.}]
    targets=[dict(t, l1_distance_half=0, rmse_share=0, mean_delta_model_minus_target=0) for t in _targets()]
    plan=safe_td_target_plan(build_td_targeting(flow,targets,_cfg()))
    assert plan['active_components']==[] and plan['status']=='GLOBAL_IDP_FALLBACK'
    assert plan['reason']=='NO_POSITIVE_ALIGNED_COMPONENT'


class FakeRPC(RuntimeError):
    hresult=-2147418111


class FakeZones:
    def __init__(self, fail_count=0, exception=None):
        self.fail_count=fail_count;self.exception=exception; self.calls=[]
    def GetMultiAttValues(self,attr,*args):
        self.calls.append(attr)
        if self.fail_count>0:
            self.fail_count-=1
            raise self.exception or FakeRPC('call was rejected by callee')
        return [(1,1.0)]


def fake_visum(zones): return SimpleNamespace(Net=SimpleNamespace(Zones=zones))


def test_long_school_transient_com_retries_and_recovers(monkeypatch):
    import r1_15a2_long_school_generation_v24917 as ls
    import r1_15a2_com_compat as com
    monkeypatch.setattr(com.time,'sleep',lambda s: None)
    z=FakeZones(fail_count=2)
    probe=ls.availability(fake_visum(z))
    assert probe['available'] is True
    assert len(z.calls)==6  # first attr 3 calls + remaining three attrs


def test_long_school_exhausted_com_defers_instead_of_missing(monkeypatch):
    import r1_15a2_long_school_generation_v24917 as ls
    import r1_15a2_com_compat as com
    monkeypatch.setattr(com.time,'sleep',lambda s: None)
    z=FakeZones(fail_count=100)
    status=ls.activate(fake_visum(z))
    assert status['active'] is False
    assert status['reason']=='TRANSIENT_COM_EXHAUSTED'
    assert status['evidence_complete'] is False
    assert len(z.calls)==4


def test_long_school_confirmed_missing_is_distinct_and_nontransient_unknown_is_deferred():
    import r1_15a2_long_school_generation_v24917 as ls
    a=ls.activate(fake_visum(FakeZones(fail_count=1,exception=KeyError('ADD_PROD_L'))))
    assert a['reason']=='ATTRIBUTES_MISSING' and a['evidence_complete']
    b=ls.activate(fake_visum(FakeZones(fail_count=1,exception=OSError('COM busy / RPC_E_CALL_REJECTED'))))
    assert b['reason']=='ATTRIBUTE_READ_UNVERIFIED' and not b['evidence_complete']


def test_long_school_invalid_options_not_masked_by_defaults(monkeypatch):
    import r1_15a2_long_school_generation_v24917 as ls
    import r1_15a2_demand_policy_v1 as dp
    monkeypatch.setattr(dp,'load_options',lambda: (_ for _ in ()).throw(RuntimeError('invalid run options')))
    with pytest.raises(RuntimeError,match='invalid run options'):
        ls.ls_options()


def test_deferred_long_school_cannot_increment_stationarity_but_generation_continues():
    import r1_15a2_demand_policy_v1 as dp
    opt=dp.validate({})
    policy=dp.DemandPolicy(opt)
    policy.streak=1
    adapter=SimpleNamespace(v24917_status={'ls_incomplete_current_cycle':True})
    def generation(*a,**kw):return True,None,None,None,{'search_complete':True,'stationarity_confirmed':True}
    controller=SimpleNamespace(UserStopRequested=RuntimeError)
    wrapped=dp.wrap_generation(generation,policy,controller)
    out=wrapped(adapter,{},None,None,None,None,None,None,None,outer_cycle=1)
    assert out[0] is True
    assert out[4]['ls_search_incomplete'] and not out[4]['stationarity_confirmed']
    assert policy.last_generation_complete is False and policy.streak==0
    policy.note_td(1,True,False,{'inner':{'search_complete':True}})
    assert not policy.stop_due()


def test_td_outer_unavailable_marks_progress_continue_not_stationary(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    policy=dp.DemandPolicy(dp.validate({'td_policy':'ALWAYS','stop_when_stationary_cycles':2}))
    policy.last_generation_changed=False; policy.last_generation_complete=True; policy.streak=1
    adapter=SimpleNamespace(v24917_status={})
    baseline={'state_hash':'same'}
    def one_td(*args,**kwargs):
        adapter.v24917_status['td_outer_incomplete_cycle']=True
        return False,baseline,{}, {'inner':{'search_complete':True,'stop_reason':'LOCAL_PLATEAU'},'td_realization_complete':True}
    from r1_15a2_controller_v22 import atomic_json
    ctrl=SimpleNamespace(atomic_json=atomic_json)
    wrapped=dp.wrap_td(one_td,policy,ctrl)
    changed,state,diag,rec=wrapped(adapter,{},tmp_path,None,baseline,{},None,outer_cycle=2)
    assert changed is False and state is baseline
    assert rec['inner']['progress_continue'] is True
    assert rec['inner']['search_complete'] is False
    assert policy.streak==0 and not policy.stop_due()
    assert (tmp_path/'TD_FINECDF_BLOCK_RESULT.json').is_file()


def test_production_publish_proxy_sanitizes_td_plan_without_mutating_sealed_builder():
    from r1_15a2_active_demand_evidence_v24917 import _PublishProxy
    class Manager:
        def publish(self, **kw): return kw
    raw={'status':'ACTIVE','active_components':['WORK_E_C'],
         'family_pressure':{'WORK':{'evidence_weight':0.}},
         'alignment_rows':[{'component':'WORK_E_C','family':'WORK','alignment_score':0.}]}
    epoch=SimpleNamespace(summary=lambda: {'epoch_hash':'HASH'})
    builder=SimpleNamespace(_v24917_epoch=epoch)
    result=_PublishProxy(Manager(),builder).publish(target_payload={'td_targets':raw})
    assert result['target_payload']['td_targets']['status']=='GLOBAL_IDP_FALLBACK'
    assert result['target_payload']['td_targets']['active_components']==[]
    assert result['skim_identity'].epoch_hash=='HASH'
    assert raw['status']=='ACTIVE' and raw['active_components']==['WORK_E_C']


def test_nonfinite_flowbundle_not_positive_evidence():
    from r1_15a2_active_demand_evidence_v24917 import safe_td_target_plan
    plan={'status':'ACTIVE','active_components':['WORK_E_C'],
          'family_pressure':{'WORK':{'evidence_weight':float('inf')}},
          'alignment_rows':[{'component':'WORK_E_C','family':'WORK','alignment_score':float('inf')}]}
    result=safe_td_target_plan(plan)
    assert result['status']=='GLOBAL_IDP_FALLBACK'


def test_ls_unverified_forces_next_outer_cycle_even_with_complete_td(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    from r1_15a2_controller_v22 import atomic_json
    opts=dp.validate({'td_policy':'ALWAYS'})
    policy=dp.DemandPolicy(opts)
    policy.last_generation_changed=False
    policy.last_generation_complete=False
    adapter=SimpleNamespace(v24917_status={'ls_incomplete_current_cycle':True})
    parent={'state_hash':'same'}
    def td(*a,**kw): return False,parent,{}, {'inner':{'search_complete':True},'td_realization_complete':True}
    wrapped=dp.wrap_td(td,policy,SimpleNamespace(atomic_json=atomic_json))
    _,_,_,rec=wrapped(adapter,{},tmp_path,None,parent,{},None,outer_cycle=1)
    assert rec['inner']['progress_continue'] and rec['inner']['stop_reason']=='LONG_SCHOOL_DESIGN_UNVERIFIED'
    assert 'LONG_SCHOOL_DESIGN_UNVERIFIED' in rec['incomplete_search_reasons']
    assert policy.streak==0
