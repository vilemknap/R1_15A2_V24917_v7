"""Regression, safety, exact numerics and production-code fake COM integration."""
from pathlib import Path
from types import SimpleNamespace
from collections import Counter
import copy
import importlib.util
import json
import math
import sqlite3
import numpy as np
import pytest

import r1_15a2_core as core
from r1_15a2_supply import SupplyPolicy, SupplyContractError
from r1_15a2_sequence_v23 import ActualSequenceRouteCollector,propose_sequence_supply
from r1_15a2_two_mode_v238 import (
    TwoModeRouteCollector,collect_two_modes,DEFAULT_SETTINGS,PROVISIONAL,
    RunControl,QuietControl,DesignStopRequested,bounded_rows,PARENT_COLUMNS,
    GEOMETRY_COLUMNS,read_matrix_authority,check_geometry_samples)
from r1_15a2_two_mode_adapter_v238 import VisumAdapter
from test_supply_v22 import A,P,B,C,T,profile,route_rows,links
from test_v237_15p_bounded_offdiag_stream import BoundedHierarchical

ROOT=Path(__file__).resolve().parents[1]
CODES=['NATIVE_CW','NATIVE_CS','NATIVE_CF','NATIVE_CL',
       'EXOG_EE_CW','EXOG_EE_CS','EXOG_EE_CF','EXOG_EE_CL',
       'NATIVE_CW_noT','NATIVE_CS_noT','EXOG_EE_CW_noT','EXOG_EE_CS_noT']
SEQS=((A,P,T),(A,B,C,T))


def hierarchy(seqs=SEQS,keys=((1,2,1),(1,2,2))):
    raw=[]
    for key,seq in zip(keys,seqs):
        raw.append([*key,'','','',''])
        for i,edge in enumerate(seq,1):raw.append(['','','',i,*edge])
    return raw


def authority(vol,diagonal=0):
    return {'matrix_no':9301,'matrix_total':sum(vol)+diagonal,'matrix_diagonal':diagonal,
            'matrix_interzonal':sum(vol),'matrix_sha256':'fake','matrix_shape':[2,2]}


def store(tmp_path,profiles=None,settings=None,name='cache.sqlite'):
    return TwoModeRouteCollector(profiles or [profile(model=600)],
        SupplyPolicy(min_geh=1,min_residual=1,max_candidates=8),
        'state',links(),tmp_path/name,
        dict(DEFAULT_SETTINGS,**(settings or {})),QuietControl(),
        duplicate_scope_policy='DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS')


def fill(store,codes=('NATIVE_CW',),volumes=((600,400),),mode='C',seqs=SEQS):
    for code,vols in zip(codes,volumes):
        store.add_parents(code,mode,[[1,2,i,v] for i,v in enumerate(vols,1)],authority(vols))
    store.add_geometry(mode,hierarchy(seqs))
    store.build_route_evidence()
    return store


def test_exact_supply_and_impact_equivalence_to_per_dseg_legacy(tmp_path):
    codes=('NATIVE_CW','NATIVE_CS');volumes=((600,400),(300,100))
    prof=[profile(model=900,obs=400)]
    c=store(tmp_path,prof);fill(c,codes,volumes)
    old=ActualSequenceRouteCollector(prof,c.policy,'state',links(),db_path=tmp_path/'old.sqlite')
    try:
        for code,v in zip(codes,volumes):
            pp,ll=route_rows(code,v,origin=1,dest=2);old.consume(pp,ll,{'code':code})
        assert c.flow==old.flow
        assert c.support==old.support
        assert c.market_counts==old.market_counts
        assert c.finish()['profile_parity']==old.finish()['profile_parity']
        a=propose_sequence_supply(c,links(),{k:0 for k in links()},c.policy)
        b=propose_sequence_supply(old,links(),{k:0 for k in links()},old.policy)
        assert a['candidates']
        assert len(a['candidates'])==len(b['candidates'])
        for new,prior in zip(a['candidates'],b['candidates']):
            assert new['changes']==prior['changes']
            # The first illustrative DSeg witness may differ with normalized ordering.
            # All numeric evidence and the actual selected/source sequences must agree.
            assert [{k:v for k,v in x.items() if k!='path_pair_example'} for x in new['bundles']] == [
                   {k:v for k,v in x.items() if k!='path_pair_example'} for x in prior['bundles']]
            assert all(b['path_pair_example'] for b in new['bundles'])
            for k in ('affected_routes','max_abs_path_seconds','by_cal_class',
                      'protected_cal_exposure_including_driver_overlap','collateral_to_support_ratio'):
                assert new['all_path_impact'][k]==prior['all_path_impact'][k]
        assert c.db.execute('SELECT COUNT(*) FROM geometry').fetchone()[0]==2
        assert c.db.execute('SELECT COUNT(*) FROM volumes').fetchone()[0]==4
        assert c.finish()['pathlink_geometry_full_identity_proven'] is False
    finally:c.close();old.close()


def test_modes_never_share_geometry_but_ds_volumes_remain_distinct(tmp_path):
    c=store(tmp_path,[profile(model=1000)])
    try:
        for mode,code,seqs,vol in [('C','NATIVE_CW',SEQS,(600,400)),
                                 ('C_NOT','NATIVE_CW_noT',SEQS[::-1],(600,400))]:
            c.add_parents(code,mode,[[1,2,1,vol[0]],[1,2,2,vol[1]]],authority(vol))
            c.add_geometry(mode,hierarchy(seqs))
        c.build_route_evidence()
        assert c.flow==[1000]
        assert c.geometry_count==4 and c.route_count==4
        imp=c.impact([{'key':list(P),'delta':1}],0,1000)
        assert imp['by_dseg']['NATIVE_CW']['volume']==600
        assert imp['by_dseg']['NATIVE_CW_NOT']['volume']==400
        assert imp['max_abs_path_seconds']==10
    finally:c.close()


def test_zero_path_volumes_are_preserved_with_geometry(tmp_path):
    c=store(tmp_path)
    try:
        fill(c,('NATIVE_CW','EXOG_EE_CW'),((600,400),(0,0)))
        assert c.db.execute('SELECT COUNT(*) FROM volumes WHERE volume=0').fetchone()[0]==2
        assert c.parents['EXOG_EE_CW']['path_rows']==2
        assert c.parents['EXOG_EE_CW']['positive_volume_rows']==0
        assert c.route_count==2
        assert c.flow==[600]
        assert c.finish()['dseg_batches'][1]['path_coverage']==1
    finally:c.close()


def test_parent_order_can_differ_while_exact_keys_match(tmp_path):
    c=store(tmp_path,[profile(model=1200)])
    try:
        c.add_parents('NATIVE_CW','C',[[1,2,2,400],[1,2,1,600]],authority([600,400]))
        c.add_parents('NATIVE_CS','C',[[1,2,1,600],[1,2,2,400]],authority([600,400]))
        c.add_geometry('C',hierarchy());c.build_route_evidence()
        assert len({r['parent_keys_sha256'] for r in c.parents.values()})==1
        assert c.flow==[1200]
    finally:c.close()


@pytest.mark.parametrize('bad',[
    [[1,2,1,600],[1,2,1,400]],
    [[1,2,1,600],[1,3,2,400]],
    [[1,2,1,-1],[1,2,2,1001]],
    [[1,2,1,math.nan],[1,2,2,400]],
    [[1.2,2,1,600],[1,2,2,400]],
])
def test_invalid_or_differing_parent_sets_fail_closed(tmp_path,bad):
    c=store(tmp_path)
    try:
        c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400]],authority([600,400]))
        with pytest.raises((SupplyContractError,RuntimeError)):
            c.add_parents('NATIVE_CS','C',bad,authority([600,400]))
    finally:c.close()


def test_same_run_offdiag_not_total_parity_and_no_tolerance_relaxation(tmp_path):
    c=store(tmp_path)
    try:
        a=c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400]],authority([600,400],diagonal=700))
        assert a['passes'] is True and a['matrix_total']==1700
        with pytest.raises(SupplyContractError,match='PARITY_FAILED'):
            c.add_parents('NATIVE_CS','C',[[1,2,1,600],[1,2,2,400]],authority([650,400]))
    finally:c.close()


@pytest.mark.parametrize('damage,expected',[
    ('orphan','ORPHAN'),('missing','COVERAGE'),('repeat','REOPENED'),('gap','CONTIGUOUS'),
    ('broken','DISCONNECTED'),('unknown','LIVE_NETWORK'),('partial','PARTIAL')])
def test_geometry_hierarchy_is_strict(tmp_path,damage,expected):
    c=store(tmp_path)
    try:
        c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400]],authority([600,400]))
        raw=hierarchy()
        if damage=='orphan':raw=raw[1:]
        if damage=='missing':raw=raw[:4]
        if damage=='repeat':raw+=hierarchy()[:4]
        if damage=='gap':raw[2][3]=3
        if damage=='broken':raw[2][5]=9
        if damage=='unknown':raw[1][4]=999
        if damage=='partial':raw[2][0]=8
        with pytest.raises(SupplyContractError,match=expected):c.add_geometry('C',raw)
    finally:c.close()


def test_page_boundary_inside_a_path_is_preserved(tmp_path):
    c=store(tmp_path)
    try:
        c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400]],authority([600,400]))
        obj=BoundedHierarchical(hierarchy())
        settings=dict(DEFAULT_SETTINGS,page_size=2)
        rows=bounded_rows(obj,GEOMETRY_COLUMNS,settings,QuietControl(),'TEST')
        c.add_geometry('C',rows);c.build_route_evidence()
        assert c.flow==[600]
        assert obj.unbounded_calls==0
        assert len(obj._oleobj_.calls)==5
    finally:c.close()


def test_geometry_allows_flat_rows_and_arbitrary_parent_order(tmp_path):
    c=store(tmp_path)
    try:
        c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400]],authority([600,400]))
        pp,ll=route_rows(origin=1,dest=2)
        raw=[[r[k] for k in GEOMETRY_COLUMNS] for r in ll]
        raw=raw[3:]+raw[:3]
        c.add_geometry('C',raw);c.build_route_evidence()
        assert c.flow==[600]
    finally:c.close()


def test_repeated_edge_multiplicity_in_all_path_impact(tmp_path):
    back=(16,4,2);ln=dict(links());ln[back]=dict(ln[P])
    c=TwoModeRouteCollector([profile(model=1200)],SupplyPolicy(min_residual=1,min_geh=1),
         'state',ln,tmp_path/'r.sqlite')
    try:
        c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400]],authority([600,400]))
        c.add_geometry('C',hierarchy(((A,P,back,P,T),SEQS[1])))
        c.build_route_evidence()
        impact=c.impact([{'key':list(P),'delta':1}],0,1200)
        assert c.flow==[1200]
        assert impact['max_abs_path_seconds']==20
        assert impact['by_cal_class']['DRIVER_ON']['volume_weighted_signed_seconds']==12000
    finally:c.close()


def test_common_edge_signed_changes_cancel_in_impact(tmp_path):
    c=store(tmp_path);fill(c)
    try:
        a=c.impact([{'key':list(A),'delta':1},{'key':list(T),'delta':-1}],0,600)
        assert a['affected_routes']==0 and a['max_abs_path_seconds']==0
    finally:c.close()


def test_collateral_includes_exog_and_paths_outside_driver_market(tmp_path):
    c=store(tmp_path,[profile(model=600)])
    try:
        for code,raw,vol in [('NATIVE_CW',[[1,2,1,600],[1,2,2,400]],[600,400]),
                            ('EXOG_EE_CW',[[1,2,1,0],[1,2,2,200]],[0,200])]:
            c.add_parents(code,'C',raw,authority(vol))
        c.add_geometry('C',hierarchy());c.build_route_evidence()
        a=c.impact([{'key':list(B),'delta':1}],0,600)
        assert a['affected_routes']==2
        assert a['by_cal_class']['UNRELATED_TO_CAL']['volume']==600
        assert a['by_dseg']['EXOG_EE_CW']['volume']==200
    finally:c.close()


def test_validation_observation_value_not_used_in_design(tmp_path):
    designs=[]
    for i,obs in enumerate((1,1e8)):
        profiles=[profile(),profile(key=B,model=400,obs=obs,role='VALIDATION',ident='v')]
        c=store(tmp_path,profiles,name=str(i)+'.sqlite');fill(c)
        try:
            d=propose_sequence_supply(c,links(),{k:0 for k in links()},c.policy)
            designs.append([r['changes'] for r in d['candidates']])
            assert c.drivers==[0]
        finally:c.close()
    assert designs[0]==designs[1]


def test_same_source_duplicate_only_excludes_drivers_not_observations(tmp_path):
    profiles=[profile(),profile(obs=1200,ident='b')]
    c=store(tmp_path,profiles)
    try:
        fill(c)
        assert c.drivers==[] and len(c.profiles)==2
        assert c.flow==[600,600]
    finally:c.close()


def _canonical_incidence(result):
    vars={(r['dseg_code'],r['origin'],r['destination']):{k:v for k,v in r.items() if k!='variable_index'} for r in result['variables']}
    ids=[(r['dseg_code'],r['origin'],r['destination']) for r in result['variables']]
    a=result['incidence']
    coefs={(int(r),ids[int(c)]):float(v) for r,c,v in zip(a.row_idx,a.col_idx,a.values)}
    return vars,coefs


@pytest.mark.parametrize('active',[[1,2],[1],[]])
def test_generation_sql_incidence_matches_original_numerical_core(tmp_path,active):
    prof=[profile(model=900),profile(key=B,model=500,role='VALIDATION',ident='v')]
    c=store(tmp_path,prof)
    fill(c,('NATIVE_CW','NATIVE_CS'),((600,400),(300,100)))
    pp=[];ll=[]
    for code,vol in [('NATIVE_CW',(600,400)),('NATIVE_CS',(300,100))]:
        p,l=route_rows(code,vol,origin=1,dest=2);pp+=p;ll+=l
    cfg={'path_export_dsegs':['NATIVE_CW','NATIVE_CS'],'mutable_dsegs':['NATIVE_CW','NATIVE_CS'],
        'mutable_relation_policy':'BOTH_ENDPOINTS_ACTUATABLE'}
    try:
        result,_=c.incidence(cfg,active)
        old=core.build_actual_path_incidence(pp,ll,prof,cfg['mutable_dsegs'],active)
        nv,nc=_canonical_incidence(result);ov,oc=_canonical_incidence(old)
        assert nv==ov and nc==oc
        canonical_base=lambda x: {(r['dseg_code'],r['origin'],r['destination']):
            {k:v for k,v in r.items() if k!='base_variable_index'} for r in x['projection_base_variables']}
        assert canonical_base(result)==canonical_base(old)
        for k in ('full_profile_model_from_paths','native_ws_profile_model_from_paths','mutable_profile_model_from_paths'):
            np.testing.assert_allclose(result[k],old[k],rtol=1e-14)
        for k in ('path_count','pathlink_count','paths_with_link_rows','path_link_coverage','total_path_volume','covered_path_volume','actuator_scope'):
            assert result[k]==old[k]
        assert result['provisional'] is True
    finally:c.close()


def test_cache_never_silently_replaced(tmp_path):
    c=store(tmp_path);c.close()
    with pytest.raises(SupplyContractError,match='MUST_BE_NEW'):
        store(tmp_path)


def test_stop_request_and_deadline_write_progress(tmp_path):
    clock=[10.]
    ctl=RunControl(tmp_path,dict(DEFAULT_SETTINGS,max_runtime_seconds=3),lambda:clock[0])
    clock[0]=14
    with pytest.raises(DesignStopRequested,match='TIME_BUDGET'):ctl.checkpoint('GEOMETRY')
    assert json.loads((tmp_path/'00_PROGRESS.json').read_text())['phase']=='GEOMETRY'
    (tmp_path/'STOP_REQUESTED').touch()
    with pytest.raises(DesignStopRequested,match='USER_STOP'):ctl.checkpoint()
    ctl.finish('STOPPED')
    assert json.loads((tmp_path/'00_PROGRESS.json').read_text())['phase']=='FINISHED'


class Collection:
    def __init__(self,items):self.GetAll=items;self.Count=len(items)


class Matrix:
    def __init__(self,no,vol,diag=200):
        self.no=no;self.a=np.array([[diag,sum(vol)],[0,0.]],dtype=float)
    def GetValues(self):return self.a.tolist()
    def AttValue(self,key):return {'NO':self.no,'SUM':self.a.sum(),'CODE':str(self.no)}[key]
    def SetValues(self,*args):raise AssertionError('MATRIX_WRITE')


class Segment:
    def __init__(self,code,i,vol):self.code=code;self.mode='C_noT' if 'noT' in code else 'C';self.ODMatrix=Matrix(9301+i,vol)
    def AttValue(self,key):return {'CODE':self.code,'MODE':self.mode,'NAME':self.code}[key]


class Lists:
    def __init__(self,volumes,damage=None):self.volumes=volumes;self.instances=[];self.damage=damage
    def make(self,kind):
        parent=self
        class LiveList(BoundedHierarchical):
            def __init__(self):super().__init__([]);self.kind=kind
            def SetObjects(self,zero,code,flt):
                assert zero==0 and flt==0
                self.code=code
                if kind=='parent':self.raw=[[1,2,j,v] for j,v in enumerate(parent.volumes[code],1)]
                else:
                    seqs=SEQS if 'noT' not in code else SEQS[::-1]
                    self.raw=hierarchy(seqs)
                    if parent.damage==code:self.raw[1][4]=999
        obj=LiveList();self.instances.append(obj);return obj
    @property
    def CreatePrTPathList(self):return self.make('parent')
    @property
    def CreatePrTPathLinkList(self):return self.make('geometry')


def live_fixture(damage=None):
    volumes={code:(60.+i,40.-i) for i,code in enumerate(CODES)}
    segs=[Segment(code,i,volumes[code]) for i,code in enumerate(CODES)]
    lists=Lists(volumes,damage)
    visum=SimpleNamespace(Net=SimpleNamespace(DemandSegments=Collection(segs)),
                         Workbench=SimpleNamespace(Lists=lists))
    cfg={'apply':False,'expected_zones':2,'supply':{'passenger_dsegs':CODES},
         'dseg_path_volume_relative_tolerance':0.01}
    model=sum(v[0] if 'noT' not in code else v[1] for code,v in volumes.items())
    return visum,cfg,model,lists


def test_full_live_adapter_export_12_volumes_two_full_geometries(tmp_path):
    v,cfg,model,lists=live_fixture()
    c=store(tmp_path,[profile(model=model)],settings={'sample_windows':[[1,2],[4,5]],'page_size':3})
    try:
        result=collect_two_modes(v,c,cfg,tmp_path)
        assert result['full_geometry_read_count']==2
        assert result['dseg_complete_count']==12
        assert result['path_rows']==24 and result['geometry_route_count']==4
        assert c.db.execute('SELECT COUNT(*) FROM volumes').fetchone()[0]==24
        assert c.flow[0]==model
        assert len([x for x in lists.instances if x.kind=='parent'])==12
        geoms=[x for x in lists.instances if x.kind=='geometry']
        assert len(geoms)==14 # 12 bounded sample lists + TWO full lists
        assert sum(any(first>5 for first,last in x._oleobj_.calls) for x in geoms)==2
        assert all(x.unbounded_calls==0 for x in lists.instances)
        assert c.finish()['apply_permitted'] is False
        assert all(p['passes'] for p in c.parity_rows)
    finally:c.close()


def test_sample_mismatch_stops_before_full_geometry(tmp_path):
    v,cfg,model,lists=live_fixture('NATIVE_CS')
    c=store(tmp_path,[profile(model=model)],settings={'sample_windows':[[1,2]],'page_size':3})
    try:
        with pytest.raises(SupplyContractError,match='SAMPLE_MISMATCH'):
            collect_two_modes(v,c,cfg,tmp_path)
        assert c.ready is False
        assert json.loads((tmp_path/'TWO_MODE_CACHE_AUDIT.json').read_text())['status']=='FAILED'
        assert not any(x.kind=='geometry' and len(x._oleobj_.calls)>1 for x in lists.instances)
    finally:c.close()


def test_export_apply_hard_lock(tmp_path):
    v,cfg,model,lists=live_fixture();cfg['apply']=True
    c=store(tmp_path,[profile(model=model)])
    try:
        with pytest.raises(SupplyContractError,match='FORBIDS_APPLY'):collect_two_modes(v,c,cfg,tmp_path)
        assert not lists.instances
    finally:c.close()


@pytest.mark.parametrize('method',['assign','apply_supply','apply_generation','apply_td','restore'])
def test_adapter_mutating_entrypoints_are_unconditionally_denied(method):
    obj=object.__new__(VisumAdapter)
    with pytest.raises(SupplyContractError,match='NO_ASSIGNMENT_APPLY_OR_RELOAD'):
        getattr(obj,method)('anything')


def test_readonly_save_is_json_never_saveversion(tmp_path):
    obj=object.__new__(VisumAdapter);obj.snapshot=lambda:{'state_hash':'s'}
    out=obj.save(tmp_path/'guard.ver')
    assert not (tmp_path/'guard.ver').exists()
    assert out['save_version_called'] is False
    assert Path(out['path']).suffix=='.json'


def test_entry_ignores_apply_environment_and_config(monkeypatch):
    spec=importlib.util.spec_from_file_location('entry','%s/R1_15A2_DESIGN_ONLY_TWO_MODE_V2_3_8.py'%ROOT)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    monkeypatch.setenv('R1_15A2_V237_APPLY','1')
    cfg=mod.load_config()
    assert cfg['apply'] is False and cfg['two_mode']['design_only'] is True
    assert len(cfg['api_approved_observations'])==498
    assert cfg['supply']['gap_readback']['maximum_gap']==0.005
    assert cfg['dseg_path_volume_relative_tolerance']==0.01


def test_adapter_full_supply_and_generation_cache_reuse(tmp_path,monkeypatch):
    import r1_15a2_two_mode_adapter_v238 as a
    v,cfg,model,lists=live_fixture()
    cfg.update(two_mode=dict(DEFAULT_SETTINGS,sample_windows=[[1,2]],page_size=3),
        path_export_dsegs=['NATIVE_CW','NATIVE_CS','NATIVE_CW_noT','NATIVE_CS_noT'],
        mutable_dsegs=['NATIVE_CW','NATIVE_CS','NATIVE_CW_noT','NATIVE_CS_noT'])
    obj=object.__new__(VisumAdapter)
    obj.visum=v;obj.cfg=cfg;obj.control=QuietControl();obj.cache=None;obj.cache_snapshot=None
    obj.policy=SupplyPolicy(min_geh=1,min_residual=1);obj.zones=[1,2];obj.actuatable_zones=[1,2]
    obj.baseline_addval={k:0. for k in links()};obj.read_links=links
    state={'state_hash':'test'};obj.snapshot=lambda:state
    diag={'d12':{'rows':[profile(model=model,obs=1000)]}}
    try:
        d=obj.supply_design(diag,tmp_path/'supply',state)
        assert d['candidates'] and d['provisional'] is True
        calls=len(lists.instances)
        monkeypatch.setattr(a.base,'path_guidance_design',lambda *args,**kw:kw['incidence_and_export'])
        incidence,exp=obj.generation_design(diag,tmp_path/'gen')
        assert len(lists.instances)==calls
        assert exp['source']=='SAME_RUN_TWO_MODE_SQLITE_CACHE_NO_COM_REEXPORT'
        assert incidence['provisional'] is True
        obj.snapshot=lambda:{'state_hash':'changed'}
        with pytest.raises(SupplyContractError,match='CACHE_STATE_MISMATCH'):
            obj.generation_design(diag,tmp_path/'gen2')
    finally:obj.close()


def test_controller_stop_does_not_continue_blocks_or_reload(tmp_path):
    from synthetic_v22_adapter import SyntheticAdapter,synthetic_config
    from r1_15a2_controller_v22 import run_calibration
    cfg=synthetic_config();cfg['apply']=False
    obj=SyntheticAdapter(cfg)
    obj.design_checkpoint=lambda phase: (_ for _ in ()).throw(DesignStopRequested('TEST_STOP'))
    r=run_calibration(obj,cfg,tmp_path)
    assert r['status']=='DESIGN_ONLY_STOPPED'
    assert len(r['blocks'])==1 and r['blocks'][0]['model_unchanged'] is True
    assert obj.restores==0 and obj.assignments==[]


@pytest.mark.parametrize('field,value',[
    ('max_runtime_seconds',float('nan')),('page_size',0),('page_size',True),
    ('page_size',2.5),('max_geometry_rows_per_mode',0),('commit_routes',0),
    ('design_only',False),('max_store_gib',0),('min_free_disk_gib',-1)])
def test_invalid_runtime_settings_are_rejected(tmp_path,field,value):
    from r1_15a2_two_mode_v238 import validated_settings
    with pytest.raises((RuntimeError,ValueError)):
        validated_settings({field:value})


def test_two_mode_stores_original_model_authorities_and_numerical_guards():
    new=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_8.json').read_text())
    old=json.loads((ROOT/'R1_15A2_CONFIG_V2_3_7.json').read_text())
    new.pop('version');new.pop('two_mode');old.pop('version')
    assert new==old
    assert (new['expected_12d_rows'],new['expected_calibration_rows'],new['expected_validation_rows'])==(498,462,36)


def test_geometry_mode_membership_change_is_rejected(tmp_path):
    v,cfg,model,_=live_fixture()
    v.Net.DemandSegments.GetAll[0].mode='C_noT'
    c=store(tmp_path,[profile(model=model)])
    try:
        with pytest.raises(SupplyContractError,match='MODE_MEMBERSHIP'):
            collect_two_modes(v,c,cfg,tmp_path)
    finally:c.close()


def test_removed_dseg_cannot_silently_reduce_scope(tmp_path):
    v,cfg,model,_=live_fixture();cfg['supply']['passenger_dsegs']=CODES[:-1]
    c=store(tmp_path,[profile(model=model)])
    try:
        with pytest.raises(SupplyContractError,match='12_PASSENGER'):
            collect_two_modes(v,c,cfg,tmp_path)
    finally:c.close()


def test_dseg_matrix_changes_during_export_rejected(tmp_path,monkeypatch):
    import r1_15a2_two_mode_v238 as module
    v,cfg,model,_=live_fixture()
    original=module.read_matrix_authority;counts=Counter()
    def read(ds,zones):
        counts[ds['code']]+=1
        out=original(ds,zones)
        if counts[ds['code']]>1:out['matrix_sha256']='changed'
        return out
    monkeypatch.setattr(module,'read_matrix_authority',read)
    c=store(tmp_path,[profile(model=model)],settings={'sample_windows':[[1,2]]})
    try:
        with pytest.raises(SupplyContractError,match='MATRIX_CHANGED_DURING'):
            collect_two_modes(v,c,cfg,tmp_path)
        assert c.ready is False
    finally:c.close()


def test_contiguity_not_destroyed_by_editability_holes(tmp_path):
    c=store(tmp_path,[profile(model=600,obs=100)])
    try:
        fill(c)
        ll=links();ll[B]['eligible']=False
        d=propose_sequence_supply(c,ll,{k:0. for k in ll},c.policy)
        for cand in d['candidates']:
            for b in cand['bundles']:
                source=[tuple(x) for x in b['source_sequence']]
                select=[tuple(x) for x in b['actual_contiguous_sequence']]
                assert any(source[k:k+len(select)]==select for k in range(len(source)))
                assert B not in select
    finally:c.close()


def test_failed_supply_never_triggers_legacy_generation_export(tmp_path):
    obj=object.__new__(VisumAdapter);obj.cache=None
    with pytest.raises(SupplyContractError,match='NO_DUPLICATE_COM_EXPORT'):
        obj.generation_design({},tmp_path)


def test_bounded_export_time_stop_never_unbounded_fallback(tmp_path):
    clock=[0.]
    ctl=RunControl(tmp_path,{'max_runtime_seconds':1},lambda:clock[0])
    obj=BoundedHierarchical(hierarchy())
    def input_rows():
        for row in bounded_rows(obj,GEOMETRY_COLUMNS,dict(DEFAULT_SETTINGS,page_size=2),ctl,'TEST'):
            clock[0]+=1
            yield row
    with pytest.raises(DesignStopRequested):list(input_rows())
    assert obj.unbounded_calls==0


def test_full_profile_parity_remains_hard_technical_gate(tmp_path):
    c=store(tmp_path,[profile(model=1000)])
    try:
        fill(c)
        with pytest.raises(SupplyContractError,match='PATH_TO_PROFILE_FLOW_PARITY'):
            c.finish()
    finally:c.close()


@pytest.mark.parametrize('seed',range(4))
def test_randomized_generation_including_zero_paths_and_both_scope(tmp_path,seed):
    rng=np.random.default_rng(seed)
    data={code:[float(x) for x in rng.integers(0,10,6)] for code in ('NATIVE_CW','NATIVE_CS')}
    data['NATIVE_CW'][0]=0
    # Three OD markets, two explicit saved alternatives each.
    keys=[(o,d,ix) for o,d in ((1,2),(2,1),(2,3)) for ix in (1,2)]
    pp=[];ll=[]
    for code,vs in data.items():
        for j,(o,d,ix) in enumerate(keys):
            pp.append({'dseg_code':code,'OrigZoneNo':o,'DestZoneNo':d,'Index':ix,'Vol(AP)':vs[j]})
            for n,e in enumerate(SEQS[ix-1],1):
                ll.append(dict(zip(['dseg_code',*GEOMETRY_COLUMNS],(code,o,d,ix,n,*e))))
    prof=[profile(model=1)]
    ref=core.build_actual_path_incidence(pp,ll,prof,mutable_dsegs=list(data),actuatable_zone_nos=[1,2])
    prof[0]['model']=float(ref['full_profile_model_from_paths'][0])
    c=store(tmp_path,prof)
    try:
        for code,vs in data.items():c.add_parents(code,'C',[[*k,v] for k,v in zip(keys,vs)],authority(vs))
        c.add_geometry('C',hierarchy([SEQS[k[2]-1] for k in keys],keys));c.build_route_evidence()
        actual,_=c.incidence({'path_export_dsegs':list(data),'mutable_dsegs':list(data)},[1,2])
        ref=core.build_actual_path_incidence(pp,ll,prof,mutable_dsegs=list(data),actuatable_zone_nos=[1,2])
        assert _canonical_incidence(actual)==_canonical_incidence(ref)
        for k in ('path_count','pathlink_count','total_path_volume','covered_path_volume','actuator_scope'):
            assert actual[k]==ref[k]
    finally:c.close()


def test_city_both_directions_exact_supply_and_generation_equivalence(tmp_path):
    reverse=lambda e:(e[0],e[2],e[1])
    seqs=SEQS+tuple(tuple(reverse(e) for e in reversed(seq)) for seq in SEQS)
    keys=((1,2,1),(1,2,2),(2,1,1),(2,1,2))
    ls=links()
    ls.update({reverse(k):dict(v) for k,v in links().items()})
    prof=[dict(profile(model=950,obs=400),observation_direction='BOTH',
               reverse_link_no=P[0],reverse_from_node_no=P[2],reverse_to_node_no=P[1])]
    pol=SupplyPolicy(min_geh=1,min_residual=1)
    new=TwoModeRouteCollector(prof,pol,'state',ls,tmp_path/'both.sqlite',
                             DEFAULT_SETTINGS,QuietControl())
    old=ActualSequenceRouteCollector(prof,pol,'state',ls,db_path=tmp_path/'old_both.sqlite')
    pp=[];ll=[]
    try:
        for code,vs in (('NATIVE_CW',(600,400,200,100)),('NATIVE_CS',(100,40,50,20))):
            new.add_parents(code,'C',[[*k,v] for k,v in zip(keys,vs)],authority(vs))
            curp=[];curl=[]
            for key,seq,v in zip(keys,seqs,vs):
                o,d,ix=key
                curp.append({'dseg_code':code,'OrigZoneNo':o,'DestZoneNo':d,'Index':ix,'Vol(AP)':v})
                for n,e in enumerate(seq,1):
                    curl.append(dict(zip(['dseg_code',*GEOMETRY_COLUMNS],(code,o,d,ix,n,*e))))
            old.consume(curp,curl,{'code':code})
            pp.extend(curp);ll.extend(curl)
        new.add_geometry('C',hierarchy(seqs,keys));new.build_route_evidence()
        assert new.flow==old.flow==[950.0]
        assert new.finish()['profile_parity']==old.finish()['profile_parity']
        assert new.support==old.support
        inc,_=new.incidence({'path_export_dsegs':['NATIVE_CW','NATIVE_CS'],
                            'mutable_dsegs':['NATIVE_CW','NATIVE_CS']},[1,2])
        ref=core.build_actual_path_incidence(pp,ll,prof,mutable_dsegs=['NATIVE_CW','NATIVE_CS'],
                                             actuatable_zone_nos=[1,2])
        assert _canonical_incidence(inc)==_canonical_incidence(ref)
        assert inc['full_profile_model_from_paths']==ref['full_profile_model_from_paths']
    finally:new.close();old.close()
