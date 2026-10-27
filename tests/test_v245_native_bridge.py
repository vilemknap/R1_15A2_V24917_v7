"""Real v1.7 Runner/512-point metrics and V245 bridge on a COM-shaped fixture.

This is NOT a Visum Multi/equilibrium implementation. The 4-zone native response
is a deterministic row-normalized function, used only to exercise integration.
The actual 681-zone patch-authority preflight remains enabled in the delivery.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from conftest import FakeAttr,FakeOperation,FakeCollection,FakeVisum,FakeZones
from test_supply_visum_v22 import Matrix
from test_v245_repair import ROOT,config
import r1_15a2_finecdf_bridge_v242 as bridge
import r1_15a2_overnight_controller_v240 as trial
from r1_15a2_supply import SupplyContractError


def fixture(tmp_path):
    ref,path,sha=bridge.load_reference(ROOT)
    ref.CONFIG['expected_zone_count']=4
    ref.CONFIG['require_2022_patch_preflight']=False # fixture geometry, not real-model evidence.
    attrs=['ADD_PROD_W','ADD_ATT_W','ADD_PROD_S','ADD_ATT_S','ADD_SALARY',
           'ZAHR_PROD_WORK','ZAHR_PROD_SERV','ZAHR_ATR_WORK','ZAHR_ATR_SERV']
    zones=FakeZones([dict(NO=i,**{x:1. for x in attrs}) for i in range(1,5)])
    grav={r['dstrat_code']:FakeAttr(PARA_A=1.,PARA_B=0.,PARA_C=-.005 if r['family']=='LONG' else -.1) for r in ref.COMPONENTS}
    strata={k:FakeAttr(GravitationParameters=g) for k,g in grav.items()}
    td=FakeAttr(DSTRATSET=','.join(grav),TripDistributionDStratParameters=lambda code:strata[code])
    ops=[FakeOperation(OPERATIONTYPE=45,ACTIVE=1),FakeOperation(OPERATIONTYPE=46,ACTIVE=1,TripDistributionParameters=td),
         FakeOperation(OPERATIONTYPE=101,ACTIVE=1)]
    v=FakeVisum(operations=ops,zones=zones)
    d=np.array([[1,5,50,120],[5,1,70,150],[50,70,1,180],[120,150,180,1]],dtype=float)
    mats={n:Matrix(n,np.ones((4,4))) for n in list(ref.BY_NO)+[9001,9697]}
    mats[9697].values=d.copy()
    v.Net.Matrices=FakeCollection(mats.values(),mats)
    v.Net.Links=FakeAttr(GetMultiAttValues=lambda attr:[(1,0.),(2,0.)])
    executions=[]
    def execute():
        active=[i for i,o in enumerate(ops) if o.AttValue('ACTIVE')]
        assert active==[1],active
        assert '4_FOREIGN' not in td.AttValue('DSTRATSET').split(',')
        for r in ref.COMPONENTS:
            if r['matrix_no']==9116:continue
            g=grav[r['dstrat_code']]
            w=np.exp(g.AttValue('PARA_B')*np.log1p(d)+g.AttValue('PARA_C')*d)
            mats[r['matrix_no']].values=100*w/w.sum(axis=1,keepdims=True)
        executions.append('SYNTHETIC_NATIVE_RESPONSE')
    v.Procedures.Execute=execute
    cfg=config();cfg['coupled_demand']['finecdf_td'].update(max_iterations=2,max_td_evaluations=16,max_stagnant_iterations=2)
    control=trial.OvernightControl(tmp_path/'control',cfg)
    return ref,path,sha,v,cfg,control,grav,mats,executions


def test_actual_reference_runner_bridge_512_metrics_readback_restore(tmp_path,monkeypatch):
    ref,path,sha,v,cfg,control,grav,mats,calls=fixture(tmp_path)
    monkeypatch.setattr(bridge,'load_reference',lambda root:(ref,path,sha))
    foreign=mats[9116].values.copy(); original_set=v.Procedures.Operations.items[1].TripDistributionParameters.AttValue('DSTRATSET')
    r=bridge.run_finecdf_inner(SimpleNamespace(visum=v),cfg,tmp_path/'inner',control,ROOT)
    assert len(calls)>=4 and r['td_evaluations']>=3
    assert r['objective_final']<=r['objective_start']+1e-12
    assert r['reference_sha256']==bridge.REF_SHA256
    assert not r['direct_od_matrix_writes'] and r['generation_frozen'] and r['foreign_frozen']
    assert np.array_equal(foreign,mats[9116].values)
    assert [o.AttValue('ACTIVE') for o in v.Procedures.Operations.items]==[1,1,1]
    assert v.Procedures.Operations.items[1].TripDistributionParameters.AttValue('DSTRATSET')==original_set
    assert r['search_complete']==(r['stop_reason']=='LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM')
    metric_files=list((tmp_path/'inner').rglob('*.csv'))
    assert metric_files and (tmp_path/'inner/V242_FINECDF_INNER_RESULT.json').exists()
    assert all(len(t['cdf'])==512 for t in ref.FINE_AUTHORITY['targets'].values())


@pytest.mark.parametrize('failure',['generation_missing','addval_missing','nonfinite_bc'])
def test_bridge_rejects_unreadable_freeze_and_nonfinite_parameters(tmp_path,failure):
    ref,path,sha,v,cfg,control,grav,mats,calls=fixture(tmp_path)
    root=tmp_path/'bridge';root.mkdir()
    if failure=='generation_missing':
        original=v.Net.Zones.GetMultiAttValues
        def missing(attr):
            if attr=='ADD_SALARY':raise RuntimeError('MISSING_ATTR')
            return original(attr)
        v.Net.Zones.GetMultiAttValues=missing
    elif failure=='addval_missing':
        v.Net.Links.GetMultiAttValues=lambda attr:(_ for _ in ()).throw(RuntimeError('MISSING_LINK_ATTR'))
    else:grav['1_WORK_E_C'].SetAttValue('PARA_B',float('nan'))
    with pytest.raises(SupplyContractError):bridge.NoDirectMatrixWriteTDAdapter(v,ref,root,control)
    assert not calls


def test_native_execute_failure_always_restores_controls(tmp_path,monkeypatch):
    ref,path,sha,v,cfg,control,grav,mats,calls=fixture(tmp_path)
    monkeypatch.setattr(bridge,'load_reference',lambda root:(ref,path,sha))
    original=v.Procedures.Operations.items[1].TripDistributionParameters.AttValue('DSTRATSET')
    v.Procedures.Execute=lambda:(_ for _ in ()).throw(RuntimeError('NATIVE_COM_FAILED'))
    with pytest.raises(RuntimeError,match='NATIVE_COM_FAILED'):
        bridge.run_finecdf_inner(SimpleNamespace(visum=v),cfg,tmp_path/'inner',control,ROOT)
    assert [o.AttValue('ACTIVE') for o in v.Procedures.Operations.items]==[1,1,1]
    assert v.Procedures.Operations.items[1].TripDistributionParameters.AttValue('DSTRATSET')==original


def test_silent_failed_active_restore_detected(tmp_path):
    ref,path,sha,v,cfg,control,grav,mats,calls=fixture(tmp_path)
    root=tmp_path/'bridge';root.mkdir()
    b=bridge.NoDirectMatrixWriteTDAdapter(v,ref,root,control);b.isolate_td()
    op=v.Procedures.Operations.items[0];object.__setattr__(op,'SetAttValue',lambda attr,value:None)
    with pytest.raises(SupplyContractError,match='ACTIVE_READBACK'):b.restore_controls()
    assert b.controls_changed


def test_native_rollback_mismatch_is_not_hidden_by_direct_od_writes(tmp_path):
    ref,path,sha,v,cfg,control,grav,mats,calls=fixture(tmp_path)
    root=tmp_path/'bridge';root.mkdir()
    b=bridge.NoDirectMatrixWriteTDAdapter(v,ref,root,control);b.isolate_td()
    try:
        abc=b.read_abc();expected=b.execute()
        expected[9101][0,0]+=10
        with pytest.raises(SupplyContractError,match='RECOMPUTE_ROLLBACK_MATRIX_DIFFER'):
            b.restore_state(abc,expected)
    finally:b.restore_controls()
