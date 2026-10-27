"""MOBILITYZONE1 regression: real guard, adapter hooks, strict live authority."""
import copy
import math
from types import SimpleNamespace as NS
import pytest
import numpy as np

import r1_15a2_mobility_zone_v24917 as z
import r1_15a2_mobility_guard_v24917 as mg

OPTS={"enabled":True,"lo":.75,"hi":1.25}


def zones(ratios=(1.,1.),families=tuple(z.SPECS)):
    rows=[]
    for no,ratio in enumerate(ratios,1):
        row={"zone_no":no,"NOT_ZAHR":1.}
        for fam in families:
            attr,ref,fps=z.SPECS[fam]
            row[attr]=ref*ratio
            for a in fps: row[a]=10.*ratio
        row.update(ADD_ATT_L=1.,ADD_ATT_SCH=1.)
        rows.append(row)
    return rows


def authority(rows=None,families=tuple(z.SPECS),**kwargs):
    return z.capture(rows or zones(),OPTS,families,**kwargs)


def candidate(fam,c,p,no=1):
    return {"zone_no":no,"attr":z.SPECS[fam][0],"family":fam,"role":"PROD","current":c,"proposed":p}


def projection(fam,step,no=1):
    return {"zone_no":no,"family":fam,"role":"PROD","log_step":step,"base_margin_volume":50.}


def test_aggregate_passes_but_zonal_guard_rejects_compensation():
    rows=zones();cs=[candidate('WORK',1.,1.5,1),candidate('WORK',1.,.5,2)]
    assert mg.check_candidate(cs,rows,OPTS)['passes']
    assert not z.check_candidate(cs,authority(rows))['passes']


@pytest.mark.parametrize('fam',tuple(z.SPECS))
def test_canonical_reference_not_run_start(fam):
    a=authority(zones((2.,.5)))
    e=a['entries'][fam+'|1']; ref=z.SPECS[fam][1]
    assert e['reference_production']==pytest.approx(10.*len(z.SPECS[fam][2]))
    assert e['ratio_current']==2. and e['current']==ref*2.
    assert not a['target_satisfied']
    assert not z.check_candidate([candidate(fam,ref*2.,ref*2.1)],a)['passes']
    assert z.check_candidate([candidate(fam,ref*2.,ref*1.7)],a)['passes']


@pytest.mark.parametrize('fam',tuple(z.SPECS))
@pytest.mark.parametrize('step',[-1.,-.1,0.,.1,1.])
def test_projection_and_all_backtracking_scales_are_feasible(fam,step):
    a=authority(zones((1.2,.8)))
    out,_=z.guard_projection([projection(fam,step)],a)
    e=a['entries'][fam+'|1'];c=e['current']
    for scale in np.linspace(0,1,51):
        assert z.check_candidate([candidate(fam,c,c*math.exp(scale*out[0]['log_step']))],a)['passes']


def test_work_projection_clips_each_zone_without_modifying_attractions():
    rows=zones((1.2,.8));a=authority(rows)
    att={'zone_no':1,'family':'WORK','role':'ATT','log_step':.5}
    out,r=z.guard_projection([projection('WORK',.4,1),projection('WORK',-.4,2),att],a)
    assert 1.2*math.exp(out[0]['log_step'])==pytest.approx(1.25)
    assert .8*math.exp(out[1]['log_step'])==pytest.approx(.75)
    assert out[2]==att and r['rows_clipped']==2
    guarded,_=mg.guard(out,rows,OPTS)
    assert all(abs(g['log_step'])<=abs(p['log_step'])+1e-12 for g,p in zip(guarded[:2],out[:2]))


def test_fit_bounds_include_fixed_reference_before_solver():
    a=authority(zones((1.24,1.30)))
    bounds={('WORK','PROD',1):(-.5,.5),('SERVICE','PROD',2):(-.5,.5),
            ('WORK','ATT',1):(-.5,.5)}
    out,report=z.constrain_fit_bounds(bounds,a)
    assert out[('WORK','PROD',1)][1]==pytest.approx(math.log(1.25/1.24))
    assert out[('SERVICE','PROD',2)][1]==pytest.approx(0.0)
    assert out[('SERVICE','PROD',2)][0]<0.0
    assert out[('WORK','ATT',1)]==bounds[('WORK','ATT',1)]
    assert report['changed']==2


def test_fit_bounds_freeze_zero_reference_without_changing_other_zone():
    rows=zones();rows[0]['ADD_PROD_W']=0.
    for name in z.SPECS['WORK'][2]:rows[0][name]=0.
    a=authority(rows)
    bounds={('WORK','PROD',1):(-.1,.1),('WORK','PROD',2):(-.1,.1)}
    out,report=z.constrain_fit_bounds(bounds,a)
    assert ('WORK','PROD',1) not in out
    assert out[('WORK','PROD',2)]==bounds[('WORK','PROD',2)]
    assert report['frozen']==1


def test_long_reference_point_two_not_one_or_last_calibrated_value():
    a=authority();e=a['entries']['LONG|1']
    assert e['reference_coefficient']==.2
    assert z.check_candidate([candidate('LONG',.2,.25)],a)['passes']
    assert not z.check_candidate([candidate('LONG',.2,.251)],a)['passes']


def ls_payload():
    return {'steps':{'ADD_PROD_L':{1:math.log(1.5),2:math.log(1.5)},
                     'ADD_PROD_SCH':{1:math.log(1.5),2:-math.log(2)},
                     'ADD_ATT_SCH':{1:.1}},
            'current':{'ADD_PROD_L':{1:.2,2:.2},'ADD_PROD_SCH':{1:1.,2:1.},'ADD_ATT_SCH':{1:1.}},
            'effect_operator':{'keys':[['LONG','PROD',1],['LONG','PROD',2],['SCHOOL','PROD',1],['SCHOOL','PROD',2],['SCHOOL','ATT',1]],
                               'G':[[100.,200.,300.,400.,500.]]},'predicted_change':[999.], 'summary':{}}


def test_ls_projection_clips_long_zones_independently_and_recomputes_prediction():
    ls=ls_payload();out=z.guard_ls(ls,authority())
    assert out['steps']['ADD_PROD_L'][1]==out['steps']['ADD_PROD_L'][2]==pytest.approx(math.log(1.25))
    assert out['steps']['ADD_PROD_SCH'][1]==pytest.approx(math.log(1.25))
    assert out['steps']['ADD_PROD_SCH'][2]==pytest.approx(math.log(.75))
    assert out['steps']['ADD_ATT_SCH'][1]==.1
    want=600*math.log(1.25)+400*math.log(.75)+50
    assert out['predicted_change']==pytest.approx([want])
    assert ls['predicted_change']==[999.]


def test_independent_long_zone_steps_keep_distinct_values():
    ls=ls_payload();ls['steps']['ADD_PROD_L']={1:math.log(1.1),2:math.log(.9)}
    out=z.guard_ls(ls,authority())
    assert out['steps']['ADD_PROD_L'][1] == pytest.approx(math.log(1.1))
    assert out['steps']['ADD_PROD_L'][2] == pytest.approx(math.log(.9))
    assert out['steps']['ADD_PROD_L'][1] != out['steps']['ADD_PROD_L'][2]


def test_missing_ls_prediction_is_explicit_not_stale():
    ls=ls_payload();del ls['effect_operator']
    out=z.guard_ls(ls,authority())
    assert out['predicted_change'] is None and out['prediction_unavailable_after_guard']


def test_long_zone_at_cap_does_not_hold_other_zones_or_school():
    rows=zones();rows[0]['ADD_PROD_L']=.25
    for a in z.SPECS['LONG'][2]:rows[0][a]=12.5
    out=z.guard_ls(ls_payload(),authority(rows))
    assert out['steps']['ADD_PROD_L'][1]==0.0
    assert out['steps']['ADD_PROD_L'][2]>0.0
    assert out['steps']['ADD_PROD_SCH'][1]>0


def test_foreign_and_synthetic_boundary_not_resident_envelope():
    rows=zones();rows[1]['NOT_ZAHR']=0.
    a=authority(rows)
    assert 'WORK|2' not in a['entries']
    c=candidate('WORK',1,2,2)
    assert z.check_candidate([c],a)['passes']
    r={'zone_no':1,'attr':'P09F4_PER_PRE_WORK_E_C','current':100,'proposed':200}
    assert z.check_candidate([r],a)['passes']


def test_live_fp_readback_uses_fixed_denominator_not_current_multiplier_only():
    before=zones();after=zones();a=authority(before)
    after[0]['FP_1_WORK_E_C']=20.
    p=z.check_live(a,after)
    assert not p['passes']
    assert any('FP_REFERENCE' in reason for row in p['violations'] for reason in row['reasons'])


def test_live_group_swap_cannot_hide_in_equal_family_sum():
    before=zones();after=zones();after[0]['FP_1_WORK_E_C']+=5;after[0]['FP_1_WORK_E_noC']-=5
    assert not z.check_live(authority(before),after)['passes']


def test_fixed_reference_remains_frozen_across_cycles():
    a=authority();rows=zones((1.1,1.2));b=authority(rows,anchor=a)
    assert b['entries']['WORK|1']['reference_fp']==a['entries']['WORK|1']['reference_fp']
    rows[0]['FP_1_WORK_E_C']+=1
    c=authority(rows,anchor=a)
    assert 'WORK' in c['unavailable'] and not c['target_satisfied']
    assert not z.check_candidate([candidate('WORK',1.1,1.2)],c)['passes']


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1.])
def test_bad_ls_data_defers_only_affected_family(value):
    rows=zones();rows[0]['FP_3_LONG_E_C']=value;a=authority(rows)
    assert 'LONG' in a['unavailable'] and 'WORK' not in a['unavailable']
    out=z.guard_ls(ls_payload(),a)
    assert all(s==0. for s in out['steps']['ADD_PROD_L'].values())
    assert out['steps']['ADD_PROD_SCH'][1]>0
    assert not z.check_candidate([candidate('LONG',.2,.21)],a)['passes']
    assert z.check_candidate([candidate('WORK',1.,1.1)],a)['passes']


def test_missing_positive_fp_coefficient_defers_family_not_fabricate_zero():
    rows=zones();del rows[0]['ADD_PROD_SCH'];a=authority(rows)
    assert 'SCHOOL' in a['unavailable'] and 'SCHOOL|1' not in a['entries']


@pytest.mark.parametrize('coefficient',[0.,1.])
def test_zero_work_production_is_safe_and_does_not_block_other_zones(coefficient):
    rows=zones();rows[0]['ADD_PROD_W']=coefficient
    for a in z.SPECS['WORK'][2]:rows[0][a]=0.
    a=authority(rows)
    assert not a['unavailable']
    assert z.check_live(a,rows)['passes']
    after=copy.deepcopy(rows);after[0]['FP_1_WORK_E_C']=1.
    assert not z.check_live(a,after)['passes']
    out,_=z.guard_projection([projection('WORK',.1,2)],a)
    assert out[0]['log_step']>.0


def test_known_zero_long_does_not_freeze_global_production():
    rows=zones()
    for attr in z.SPECS['LONG'][2]: rows[0][attr]=0.
    a=authority(rows);out=z.guard_ls(ls_payload(),a)
    assert out['steps']['ADD_PROD_L'][1]>0


def test_unknown_zero_long_base_is_frozen_not_divided_by_epsilon():
    rows=zones();rows[0]['ADD_PROD_L']=0.
    for attr in z.SPECS['LONG'][2]:rows[0][attr]=0.
    a=authority(rows);out=z.guard_ls(ls_payload(),a)
    assert out['steps']['ADD_PROD_L'][1]==0.0
    assert out['steps']['ADD_PROD_L'][2]>0.0


@pytest.mark.parametrize('change',['duplicate','mask','missing_zone','stale_coefficient'])
def test_live_parent_integrity_is_required(change):
    a=authority();new=zones()
    if change=='duplicate':new.append(copy.deepcopy(new[0]))
    elif change=='mask':new[0]['NOT_ZAHR']=0.
    elif change=='missing_zone':new.pop()
    else:new=zones((1.1,1.))
    if change=='stale_coefficient':assert not z.parent_unchanged(a,new)['passes']
    else:
        with pytest.raises(ValueError):z.parent_unchanged(a,new)


def test_disabled_guard_no_change():
    a=z.capture(zones(),dict(OPTS,enabled=False),tuple(z.SPECS))
    rows=[projection('WORK',2.)]
    assert z.guard_projection(rows,a)[0] is rows
    assert z.check_candidate([candidate('WORK',1,100)],a)['passes']


def test_enrich_reads_all_ls_attrs_using_strict_reader(monkeypatch):
    import r1_15a2_runtime_v1 as rt
    rows=zones();base=[{k:v for k,v in r.items() if not k.startswith('FP_3_') and k!='FP_5_SCHOOL'} for r in rows]
    calls=[]
    def read(visum,attr,zn,**kw):calls.append(attr);return [r[attr] for r in rows]
    monkeypatch.setattr(rt,'read_zone_attr_strict',read)
    ad=NS(v24917_ls={'active':True},visum=object(),zones=[1,2],zone_write_index_by_no={1:1,2:2},com_retry_policy={})
    enriched,fams,errors=z.enrich(ad,base)
    assert set(fams)==set(z.SPECS) and not errors
    assert set(calls)=={'ADD_PROD_L','ADD_PROD_SCH','FP_5_SCHOOL',*z.SPECS['LONG'][2]}
    assert enriched==rows


def test_unavailable_long_read_defers_long_only(monkeypatch):
    import r1_15a2_runtime_v1 as rt
    rows=zones()
    def read(visum,attr,zn,**kw):
        if attr=='FP_3_LONG_E_C':raise RuntimeError('COM unavailable')
        return [r[attr] for r in rows]
    monkeypatch.setattr(rt,'read_zone_attr_strict',read)
    ad=NS(v24917_ls={'active':True},visum=object(),zones=[1,2],zone_write_index_by_no={},com_retry_policy={})
    zr,fs,errs=z.enrich(ad,rows)
    a=z.capture(zr,OPTS,fs,errs)
    assert set(a['unavailable'])=={'LONG'}


def test_real_adapter_final_candidate_requires_zonal_proof():
    from r1_15a2_trial_adapter_v24917 import VisumAdapter
    ad=VisumAdapter.__new__(VisumAdapter);zr=zones()
    ctx={'_genfix2_mobility':{'zone_rows':zr,'options':OPTS},'_mobilityzone1':authority(zr)}
    design={'candidate_rows':[candidate('WORK',1,1.5,1),candidate('WORK',1,.5,2)]}
    p=ad._validate_mobility_plan(ctx,design)
    assert not p['passes'] and not p['mobilityzone1']['passes']


def test_real_adapter_readback_rejects_zonal_violation_even_when_aggregate_passes(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as admod
    before=zones();after=zones((1.5,.5))
    ad=admod.VisumAdapter.__new__(admod.VisumAdapter)
    ad.cfg={};ad.visum=object();ad.zones=[1,2];ad.zone_write_index_by_no={};ad.com_retry_policy={};ad.v24917_status={}
    ad._genfix2_mobility_parent={'zone_rows':before,'options':OPTS}
    ad._mobilityzone1_parent=authority(before,families=('WORK','SERVICE'))
    monkeypatch.setattr(admod._V24916ActiveAdapter,'block_gate',lambda *a,**k:{'accepted':True,'reasons':[]})
    monkeypatch.setattr(admod.supply_visum.base,'zone_state_rows',lambda *a,**k:(after,[]))
    monkeypatch.setattr(admod.longguard,'capture',lambda *a,**k:{})
    monkeypatch.setattr(admod.longguard,'decide',lambda *a,**k:{'passes':True,'reasons':[]})
    out=ad.block_gate('GENERATION',{}, {},[candidate('WORK',1,1.5)])
    assert not out['accepted'] and not out['mobility_guard_live']['mobilityzone1']['passes']


@pytest.mark.parametrize('ratio,newratio,passes',[(1.8,1.7,True),(1.8,1.9,False),(.4,.5,True),(.4,.3,False),(1.,.7,False)])
def test_live_existing_violation_may_recover_but_never_worsen(ratio,newratio,passes):
    a=authority(zones((ratio,1.)));after=zones((newratio,1.))
    assert z.check_live(a,after)['passes']==passes


def test_raw_solver_summary_never_masquerades_as_guarded_forecast():
    ls=ls_payload();ls['summary']={'long_zone_steps':2,'linear_ratio_after_ws_and_ls':1.2}
    out=z.guard_ls(ls,authority())
    assert out['summary']['raw_solver_long_zone_steps']==ls['steps']['ADD_PROD_L']
    assert out['summary']['long_zone_steps']==2
    assert out['summary']['linear_ratio_after_ws_and_ls'] is None


def test_actual_apply_checks_stale_ls_parent_before_any_write(monkeypatch,tmp_path):
    import r1_15a2_trial_adapter_v24917 as a17
    ad=a17.VisumAdapter.__new__(a17.VisumAdapter)
    ad.cfg={};ad.visum=object();ad.zones=[1,2];ad.zone_write_index_by_no={};ad.com_retry_policy={}
    old=zones();new=zones((1.1,1.))
    ad.generation_preview=lambda *args:{'genfix2_mobility':{'passes':True}}
    monkeypatch.setattr(a17.supply_visum.base,'zone_state_rows',lambda *args,**kw:(new,[]))
    monkeypatch.setattr(a17.zguard,'enrich',lambda *args:(new,list(z.SPECS),{}))
    writes=[]
    monkeypatch.setattr(a17._V24916ActiveAdapter,'apply_generation',lambda *args: writes.append(1))
    with pytest.raises(Exception,match='MOBILITYZONE1_STALE_PARENT'):
        ad.apply_generation({'_mobilityzone1':authority(old)},1.,tmp_path)
    assert not writes


def test_actual_apply_rejects_unverified_optional_read_before_first_write(monkeypatch,tmp_path):
    import r1_15a2_trial_adapter_v24917 as a17
    ad=a17.VisumAdapter.__new__(a17.VisumAdapter)
    ad.cfg={};ad.visum=object();ad.zones=[1,2];ad.zone_write_index_by_no={};ad.com_retry_policy={}
    old=zones();ad.generation_preview=lambda *a:{'genfix2_mobility':{'passes':True}}
    monkeypatch.setattr(a17.supply_visum.base,'zone_state_rows',lambda *a,**kw:(old,[]))
    monkeypatch.setattr(a17.zguard,'enrich',lambda *a:(old,list(z.SPECS),{'LONG':'COM busy'}))
    writes=[];monkeypatch.setattr(a17._V24916ActiveAdapter,'apply_generation',lambda *a: writes.append(1))
    with pytest.raises(Exception,match='MOBILITYZONE1_LIVE_READ_UNAVAILABLE'):
        ad.apply_generation({'_mobilityzone1':authority(old)},1.,tmp_path)
    assert not writes


def test_guard_module_cannot_mutate_visum_or_reload_version():
    import ast, pathlib
    tree=ast.parse(pathlib.Path(z.__file__).read_text())
    called={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not called & {'LoadVersion','SetValues','SetAttValue','SetMultiAttValues','Dispatch','DispatchEx'}
