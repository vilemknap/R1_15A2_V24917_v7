from __future__ import annotations
import copy, math
import pytest
import r1_15a2_multiblock as mb


def cfg():
    return {
      'preserve_zero_add': True, 'add_min':0.0,'add_max':3.0,'min_add_log_step':1e-8,
      'explicit_excluded_zone_nos':[],
      'zahr': {'domestic_mask_attr':'NOT_ZAHR','domestic_threshold':0.5,'neighbour_attr':'ZAHR_SUSED','population_attr':'POP_ZP_2022','min':0.0,'max':10.0,'preserve_zero':True,'seed_floor':0.0,'explicit_excluded_zone_nos':[]},
      'salary': {'enabled':True,'income_attr':'AV_INCOME','salary_attr':'ADD_SALARY','work_attraction_attr':'ADD_ATT_W','formula_offset':1000.0,'formula_denominator':2700.0,'factor_floor':0.05,'salary_min':0.0,'salary_max':3.0,'max_abs_delta_per_block':0.04,'min_eligible_zones':2,'zone_add_ridge_lambda':1.0,'basis_ridge_lambda':0.2},
      'td': {'component_policy': {'WORK':'AUTO','SERVICE':'AUTO','SCHOOL':'AUTO','LONG':'AUTO'}, 'min_conditioned_volume':10,'school_min_conditioned_volume':10,'long_min_conditioned_volume':10,'min_l1_for_mutation':0.0,'mean_relative_deadband':0.0,'max_components_per_block':5,'b_shape_gain':0.4,'c_mean_gain':0.18,'c_tail_gain':0.12,'c_b_compensation':0.35,'max_abs_b_delta':0.08,'max_abs_c_delta':0.04,'long_b_gain_multiplier':0.25,'long_c_gain_multiplier':0.5,'long_max_abs_b_delta':0.02,'long_max_abs_c_delta':0.018,'b_min':0,'b_max':5,'c_min':-3,'c_max':0}
    }


def bins(model=(0.5,0.3,0.2), target=(0.3,0.5,0.2)):
    edges=[(0,1),(1,15),(25,100)]
    base=[]; cmp=[]
    for (lo,hi),m,t in zip(edges,model,target):
        base.append({'component':'WORK_E_C','bin_low':lo,'bin_high':hi,'share_conditioned':m})
        cmp.append({'component':'WORK_E_C','bin_low':lo,'bin_high':hi,'target_share':t})
    return base,cmp


def test_registry_is_component_level_16_curves():
    assert len(mb.COMPONENT_REGISTRY)==16
    assert {v['family'] for v in mb.COMPONENT_REGISTRY.values()}=={'WORK','SERVICE','LONG','SCHOOL'}
    assert mb.COMPONENT_REGISTRY['SCHOOL']['dstrat_code']=='5_SCHOOL'


def test_long_aggregate_authority_is_guard_only():
    summaries=[{'component':'LONG_E_C','target_status':'LONG_BASIS_PENDING_NOT_BACKEND_TARGET','conditioned_volume':1000}]
    sig=mb.build_td_signals(summaries,[],[],long_authority={'authority_id':'CL','aggregate_guard_bins':[1]},config=cfg())
    assert not sig['LONG_E_C']['calibratable']
    assert sig['LONG_E_C']['authority_status']=='NO_COMPONENT_LONG_AUTHORITY'


def test_explicit_long_component_authority_enables_only_matching_component():
    model=[{'component':'LONG_E_C','bin_low':100,'bin_high':110,'share_conditioned':0.7},{'component':'LONG_E_C','bin_low':110,'bin_high':120,'share_conditioned':0.3}]
    summaries=[{'component':'LONG_E_C','target_status':'LONG_BASIS_PENDING_NOT_BACKEND_TARGET','conditioned_volume':1000}]
    auth={'authority_id':'X','component_targets':{'LONG_E_C':{'status':'ACTIVE_LONG_COMPONENT_TARGET','bins':[{'bin_low':100,'bin_high':110,'target_share':0.5},{'bin_low':110,'bin_high':120,'target_share':0.5}]}}}
    sig=mb.build_td_signals(summaries,[],model,long_authority=auth,config=cfg())
    assert sig['LONG_E_C']['calibratable']
    assert not sig['LONG_E_noC']['calibratable']


def test_incomplete_bin_authority_fails_closed():
    base,cmp=bins()
    cmp=cmp[:-1]
    summaries=[{'component':'WORK_E_C','target_status':'ACTIVE_COMPONENT_DIST_TARGET','conditioned_volume':1000}]
    sig=mb.build_td_signals(summaries,cmp,base,config=cfg())['WORK_E_C']
    assert not sig['calibratable']
    assert sig['policy_reason']=='INCOMPLETE_OR_MISMATCHED_BIN_AUTHORITY'


def test_school_auto_needs_active_target():
    base=[{'component':'SCHOOL','bin_low':0,'bin_high':1,'share_conditioned':1.0}]
    cmp=[{'component':'SCHOOL','bin_low':0,'bin_high':1,'target_share':1.0}]
    off=mb.build_td_signals([{'component':'SCHOOL','target_status':'DIAGNOSTIC_ONLY','conditioned_volume':1000}],cmp,base,config=cfg())['SCHOOL']
    on=mb.build_td_signals([{'component':'SCHOOL','target_status':'ACTIVE_COMPONENT_DIST_TARGET','conditioned_volume':1000}],cmp,base,config=cfg())['SCHOOL']
    assert not off['calibratable'] and on['calibratable']


def _work_signal(model,target):
    base,cmp=bins(model,target)
    return mb.build_td_signals([{'component':'WORK_E_C','target_status':'ACTIVE_COMPONENT_DIST_TARGET','conditioned_volume':1000}],cmp,base,config=cfg())


def test_td_b_can_move_up_from_zero_and_scale_once():
    sig=_work_signal((0.6,0.2,0.2),(0.2,0.6,0.2))
    current={'WORK_E_C':{'current_b':0.0,'current_c':-0.1,'dstrat_code':'1_WORK_E_C'}}
    full=mb.design_td_candidates(sig,current,'WORK',cfg(),1.0)['candidate_rows'][0]
    half=mb.design_td_candidates(sig,current,'WORK',cfg(),0.5)['candidate_rows'][0]
    assert full['candidate_b']>0
    assert half['delta_b']==pytest.approx(full['raw_delta_b']*0.5)
    assert half['delta_c']==pytest.approx(full['raw_delta_c']*0.5)


def test_td_signed_shape_can_reduce_b():
    sig=_work_signal((0.1,0.7,0.2),(0.4,0.4,0.2))
    current={'WORK_E_C':{'current_b':0.5,'current_c':-0.1,'dstrat_code':'1_WORK_E_C'}}
    row=mb.design_td_candidates(sig,current,'WORK',cfg(),1.0)['candidate_rows'][0]
    assert row['delta_b']<0


def zones():
    out=[]
    for z,income in [(1,1000),(2,2000),(3,3000)]:
        out.append({'zone_no':z,'NOT_ZAHR':1,'ZAHR_SUSED':0,'POP_ZP_2022':100,'AV_INCOME':income,
        'ADD_PROD_W':1,'ADD_ATT_W':1,'ADD_SALARY':1,'ADD_PROD_S':1,'ADD_ATT_S':1,
        'ZAHR_PROD_WORK':1,'ZAHR_ATR_WORK':1,'ZAHR_PROD_SERV':1,'ZAHR_ATR_SERV':1})
    out.append({'zone_no':10,'NOT_ZAHR':0,'ZAHR_SUSED':1,'POP_ZP_2022':500,'AV_INCOME':1000,
        'ADD_PROD_W':1,'ADD_ATT_W':1,'ADD_SALARY':1,'ADD_PROD_S':1,'ADD_ATT_S':1,
        'ZAHR_PROD_WORK':1,'ZAHR_ATR_WORK':1,'ZAHR_PROD_SERV':1,'ZAHR_ATR_SERV':1})
    return out


def test_generation_maps_domestic_and_zahr_and_salary():
    proj=[]
    for z in (1,2,3):
        proj += [{'zone_no':z,'family':'WORK','role':'PROD','log_step':0.02,'base_margin_volume':100},
                 {'zone_no':z,'family':'WORK','role':'ATT','log_step':0.03,'base_margin_volume':100}]
    proj += [{'zone_no':10,'family':'SERVICE','role':'PROD','log_step':0.02,'base_margin_volume':100},
             {'zone_no':10,'family':'SERVICE','role':'ATT','log_step':0.02,'base_margin_volume':100}]
    d=mb.design_generation_candidates(proj,zones(),cfg(),1.0)
    attrs={r['attr'] for r in d['candidate_rows']}
    assert 'ADD_PROD_W' in attrs and 'ADD_ATT_W' in attrs and 'ADD_SALARY' in attrs
    assert 'ZAHR_PROD_SERV' in attrs and 'ZAHR_ATR_SERV' in attrs
    assert d['summary']['max_abs_effect_log_error'] < 1e-9


def test_generation_exclusion_and_inactive_zahr_are_skipped():
    c=cfg(); c['explicit_excluded_zone_nos']=[1]
    zs=zones(); zs[-1]['ZAHR_SUSED']=0
    proj=[{'zone_no':1,'family':'WORK','role':'PROD','log_step':0.02,'base_margin_volume':100},
          {'zone_no':10,'family':'SERVICE','role':'PROD','log_step':0.02,'base_margin_volume':100}]
    d=mb.design_generation_candidates(proj,zs,c,1.0)
    assert not d['candidate_rows']
    reasons={r['reason'] for r in d['skipped_rows']}
    assert {'EXPLICIT_EXCLUSION','ZAHR_FORMULA_BASE_INACTIVE'} <= reasons


def test_preserve_zero_and_seed_floor():
    c=cfg(); zs=zones(); zs[0]['ADD_PROD_W']=0
    proj=[{'zone_no':1,'family':'WORK','role':'PROD','log_step':0.02,'base_margin_volume':100}]
    d=mb.design_generation_candidates(proj,zs,c,1.0)
    assert not d['candidate_rows']
    c['preserve_zero_add']=False; c['add_seed_floor']=0.5
    d2=mb.design_generation_candidates(proj,zs,c,1.0)
    assert d2['candidate_rows'][0]['proposed']>0.5


def test_salary_not_used_when_add_att_is_zero():
    c=cfg(); zs=zones()
    for r in zs[:3]: r['ADD_ATT_W']=0
    proj=[{'zone_no':z,'family':'WORK','role':'ATT','log_step':0.03,'base_margin_volume':100} for z in (1,2,3)]
    d=mb.design_generation_candidates(proj,zs,c,1.0)
    assert 'ADD_SALARY' not in {r['attr'] for r in d['candidate_rows']}


def test_pa_summary_uses_only_implemented_rows():
    c=cfg(); zs=zones(); zs[0]['ADD_PROD_W']=0
    proj=[{'zone_no':1,'family':'WORK','role':'PROD','log_step':0.02,'base_margin_volume':100},
          {'zone_no':2,'family':'WORK','role':'ATT','log_step':0.02,'base_margin_volume':100}]
    d=mb.design_generation_candidates(proj,zs,c,1.0)
    t=d['summary']['estimated_pa_delta_by_family']['WORK']
    assert t['estimated_prod_delta']==0
    assert t['estimated_att_delta']>0
