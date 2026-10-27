from __future__ import annotations
import importlib.util, json, pathlib, sys
import pytest
from conftest import FakeAttr, FakeCollection, FakeDstratCollection, FakeOperation, FakeVisum, FakeZones
import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('master_v21',ROOT/'R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py')
master=importlib.util.module_from_spec(spec); spec.loader.exec_module(master)


def make_visum():
    tg_objs={}
    for comp,reg in mb.COMPONENT_REGISTRY.items():
        if reg['family'] not in ('WORK','SERVICE'): continue
        if reg['family']=='WORK':
            prod='[ADD_PROD_W]*X*[NOT_ZAHR]+[POP_ZP_2022]*[ZAHR_PROD_WORK]*[ZAHR_SUSED]'
            att='[ADD_ATT_W]*X*(1+[AV_INCOME]*[ADD_SALARY])*[NOT_ZAHR]+[POP_ZP_2022]*[ZAHR_ATR_WORK]*[ZAHR_SUSED]'
        else:
            prod='[ADD_PROD_S]*X*[NOT_ZAHR]+[POP_ZP_2022]*[ZAHR_PROD_SERV]*[ZAHR_SUSED]'
            att='[ADD_ATT_S]*X*[NOT_ZAHR]+[POP_ZP_2022]*[ZAHR_ATR_SERV]*[ZAHR_SUSED]'
        tg_objs[reg['dstrat_code']]=FakeAttr(DEMANDSTRATUMCODE=reg['dstrat_code'],PRODUCTIONFUNCTION=prod,ATTRACTIONFUNCTION=att)
    td_objs={reg['dstrat_code']:FakeAttr(DEMANDSTRATUMCODE=reg['dstrat_code'],PARA_B=0.0,PARA_C=-0.1) for reg in mb.COMPONENT_REGISTRY.values()}
    tg_params=FakeAttr(DSTRATSET=','.join(tg_objs),TripGenerationDStratParameters=FakeDstratCollection(list(tg_objs.values()),tg_objs))
    td_params=FakeAttr(DSTRATSET=','.join(td_objs),TripDistributionDStratParameters=FakeDstratCollection(list(td_objs.values()),td_objs))
    ops=[FakeOperation(OPERATIONTYPE=45,ACTIVE=1,COMMENT='TG',TripGenerationParameters=tg_params),FakeOperation(OPERATIONTYPE=46,ACTIVE=1,COMMENT='TD',TripDistributionParameters=td_params)]
    required=['NO','ADD_PROD_W','ADD_ATT_W','ADD_SALARY','ADD_PROD_S','ADD_ATT_S','ZAHR_PROD_WORK','ZAHR_ATR_WORK','ZAHR_PROD_SERV','ZAHR_ATR_SERV','NOT_ZAHR','ZAHR_SUSED','POP_ZP_2022','AV_INCOME','NUM_PM_SMEAR']
    rows=[]
    for z in range(1,682):
        r={k:1.0 for k in required}; r['NO']=z; r['AV_INCOME']=1000+(z%10)*100; r['POP_ZP_2022']=100
        rows.append(r)
    return FakeVisum(operations=ops,zones=FakeZones(rows))


def config():
    c=json.loads((ROOT/'R1_15A2_CONFIG_V2_1.json').read_text())
    c['tg_dependency_contract']=json.loads((ROOT/'authorities/R1_TG_PARAMETER_DEPENDENCY_CONTRACT_V2_1.json').read_text())
    return c


def test_package_is_self_contained_and_default_dry_run():
    cfg=master.load_config()
    assert cfg['apply'] is False
    for p in ['r1_15a2_core.py','r1_15a2_runtime_v1.py','r1_15a2_multiblock.py','r1_15a2_visum_parameters.py',
              'helpers/R1_11D_V1_3_COMPONENT_DIST_BEHAVIOR_DIAGNOSTICS.py','helpers/R1_12D_CSD2022_GEH_FORENSIC_444_PROCSEQ_EMBEDDED.py']:
        assert (ROOT/p).is_file()


def test_strict_zone_reader_rejects_blank():
    v=make_visum(); v.Net.Zones.rows[1]['ADD_PROD_W']=''
    with pytest.raises(RuntimeError): rt.read_zone_attr_strict(v,'ADD_PROD_W',[1,2,3])


def test_tg_contract_audit_passes_and_detects_missing_token():
    v=make_visum(); c=config()
    assert vp.audit_trip_generation_contract(v,c)['passes']
    tgop=v.Procedures.Operations.items[0]
    obj=tgop.TripGenerationParameters.TripGenerationDStratParameters.ItemByKey('1_WORK_E_C')
    obj.SetAttValue('ATTRACTIONFUNCTION','[ADD_ATT_W]')
    result=vp.audit_trip_generation_contract(v,c)
    assert not result['passes']
    assert any('1_WORK_E_C' in x for x in result['failures'])


def test_td_read_apply_readback_and_persistence():
    v=make_visum()
    state=vp.read_td_parameter_state(v); assert len(state['objects'])==16
    rows=vp.apply_td_candidates(v,[{'component':'WORK_E_C','candidate_b':0.2,'candidate_c':-0.3}])
    assert rows[0]['status']=='OK'
    live=vp.verify_td_persistence(v,[{'component':'WORK_E_C','candidate_b':0.2,'candidate_c':-0.3}])
    assert live[0]['status']=='OK'


def test_block_scopes_include_component_matrices():
    c=config()
    assert set(master.block_matrix_scope(c,'TD_COMPONENT_LONG')[1])=={9111,9112,9113,9114,9115}
    assert master.block_matrix_scope(c,'TD_COMPONENT_SCHOOL')[1]==[9117]


def test_rollback_snapshot_comparison_detects_change():
    before=[{'component':'WORK_E_C','current_b':0,'current_c':-0.1,'status':'OK'}]
    after=[{'component':'WORK_E_C','current_b':0.1,'current_c':-0.1,'status':'OK'}]
    assert master.compare_td_snapshot(before,before)[0]['same']==1
    assert master.compare_td_snapshot(before,after)[0]['same']==0


def test_source_contains_no_direct_matrix_write():
    text='\n'.join((ROOT/f).read_text(encoding='utf-8') for f in ['R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py','r1_15a2_core.py','r1_15a2_multiblock.py','r1_15a2_runtime_v1.py','r1_15a2_visum_parameters.py'])
    forbidden=['.SetValues(', '.SetValuesToResultMatrix(', '.SetValuesRaw(']
    assert not any(x in text for x in forbidden)

def test_connect_visum_binds_injected_global(monkeypatch):
    v=make_visum()
    monkeypatch.setitem(master.__dict__,'Visum',v)
    got,source=master.connect_visum()
    assert got is v and rt.Visum is v and 'injected' in source


def test_inactive_tg_operation_fails_contract():
    v=make_visum(); v.Procedures.Operations.items[0].SetAttValue('ACTIVE',0)
    result=vp.audit_trip_generation_contract(v,config())
    assert not result['passes']
    assert 'SELECTED_TRIP_GENERATION_OPERATION_INACTIVE' in result['failures']


def test_inactive_td_operation_fails_read():
    v=make_visum(); v.Procedures.Operations.items[1].SetAttValue('ACTIVE',0)
    with pytest.raises(RuntimeError,match='inactive'):
        vp.read_td_parameter_state(v)


def test_formula_token_requires_bracketed_attribute():
    v=make_visum(); c=config()
    obj=v.Procedures.Operations.items[0].TripGenerationParameters.TripGenerationDStratParameters.ItemByKey('1_WORK_E_C')
    obj.SetAttValue('PRODUCTIONFUNCTION','MY_ADD_PROD_W_BACKUP+[ZAHR_PROD_WORK]+[NOT_ZAHR]+[ZAHR_SUSED]')
    result=vp.audit_trip_generation_contract(v,c)
    assert not result['passes']
    row=next(x for x in result['rows'] if x['dstrat_code']=='1_WORK_E_C')
    assert 'ADD_PROD_W' in row['missing_production_tokens']
