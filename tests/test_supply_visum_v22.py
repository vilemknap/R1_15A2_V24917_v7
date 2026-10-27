"""COM-shaped stubs only. Operation type 101 follows PTV; Net.GAP remains SYNTHETIC_TEST_ONLY."""
from pathlib import Path
import copy
import numpy as np
import pytest
from conftest import FakeAttr,FakeCollection,FakeOperation,FakeVisum
from test_visum_and_master import make_visum
from test_supply_v22 import route_rows,profile,A,P,B,C,T
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import ActualRouteCollector,SupplyPolicy,SupplyContractError
from r1_15a2_supply_visum import assignment_only_operations,assignment_plan,VisumAdapter


class Matrix(FakeAttr):
    def __init__(self,no,values):
        super().__init__(NO=no,CODE='M'+str(no))
        self.values=np.array(values,dtype=float)
    def GetValues(self):return self.values.tolist()
    def AttValue(self,name):
        if name=='SUM':return float(self.values.sum())
        return super().AttValue(name)


def small_cfg():
    return {'supply':{'passenger_dsegs':['NATIVE_CW'],'freight_dsegs':['LNV','NV'],
            'assignment_operations':[{'no':3,'operation_type':101,'dseg_attribute':'DSEGSET','dseg_object_path':[]}],
            'gap_readback':{'object_path':['Net'],'attribute':'GAP','maximum_gap':1e-6},
            'component_matrix_nos':[9101]}}


def op_visum():
    ops=[FakeOperation(NO=1,OPERATIONTYPE=45,ACTIVE=1,NAME='TG'),
         FakeOperation(NO=2,OPERATIONTYPE=46,ACTIVE=1,NAME='TD'),
         FakeOperation(NO=3,OPERATIONTYPE=101,ACTIVE=1,NAME='Synthetic assignment',DSEGSET='NATIVE_CW,LNV,NV')]
    v=FakeVisum(operations=ops);v.Net.SetAttValue('GAP',1e-7)
    return v


def test_assignment_only_flags_and_restore_after_success():
    v=op_visum()
    with assignment_only_operations(v,small_cfg()):
        assert [x.AttValue('ACTIVE') for x in v.Procedures.Operations.items]==[0,0,1]
    assert [x.AttValue('ACTIVE') for x in v.Procedures.Operations.items]==[1,1,1]


def test_assignment_only_flags_restore_after_exception():
    v=op_visum()
    with pytest.raises(RuntimeError,match='EXEC_FAILED'):
        with assignment_only_operations(v,small_cfg()):raise RuntimeError('EXEC_FAILED')
    assert [x.AttValue('ACTIVE') for x in v.Procedures.Operations.items]==[1,1,1]


@pytest.mark.parametrize('defect',['unapproved','wrong_type','inactive','TG','no_gap','missing_freight'])
def test_assignment_plan_rejects_unqualified_execution(defect):
    v=op_visum();cfg=small_cfg()
    if defect=='unapproved':cfg['supply']['assignment_operations']=[]
    if defect=='wrong_type':cfg['supply']['assignment_operations'][0]['operation_type']=901
    if defect=='inactive':v.Procedures.Operations.items[2].SetAttValue('ACTIVE',0)
    if defect=='TG':cfg['supply']['assignment_operations']=[{'no':1,'operation_type':45}]
    if defect=='no_gap':cfg['supply']['gap_readback']['attribute']=None
    if defect=='missing_freight':v.Procedures.Operations.items[2].SetAttValue('DSEGSET','NATIVE_CW')
    assert not assignment_plan(v,cfg)['passes']
    with pytest.raises(SupplyContractError):
        with assignment_only_operations(v,cfg):pass


def state_visum():
    v=make_visum()
    for i,op in enumerate(v.Procedures.Operations.items,1):op.SetAttValue('NO',i)
    assignment=FakeOperation(NO=3,OPERATIONTYPE=101,ACTIVE=1,COMMENT='ASSIGNMENT',DSEGSET='NATIVE_CW,LNV,NV')
    v.Procedures.Operations=FakeCollection(v.Procedures.Operations.items+[assignment])
    mats=[Matrix(9101,[[0.,1000.],[0.,0.]]),Matrix(2,[[0.,30.],[0.,0.]]),Matrix(3,[[0.,50.],[0.,0.]])]
    v.Net.Matrices=FakeCollection(mats,{m.AttValue('NO'):m for m in mats})
    v.Net.DemandSegments=FakeCollection([FakeAttr(CODE=code,ODMatrix=mat) for code,mat in zip(['NATIVE_CW','LNV','NV'],mats)])
    v.Net.Links=FakeCollection([FakeAttr(NO=k[0],FROMNODENO=k[1],TONODENO=k[2],ADDVAL1=0.,CAPPRT=5000,LENGTH=1.,TYPENO=1,TSYSSET='C,C_noT',**{'T0_PRTSYS(C)':60.}) for k in [A,P,B,C,T,(11,2,1)]])
    v.Net.SetAttValue('GAP',1e-7)
    return v


def test_snapshot_preserves_direction_and_all_demand_matrices():
    adapter=VisumAdapter(state_visum(),small_cfg());snap=adapter.snapshot()
    assert '11|1|2' in snap['addval1'] and '11|2|1' in snap['addval1']
    assert {r['matrix_no'] for r in snap['matrices']}=={2,3,9101}
    assert len(snap['td_values'])==16


def test_snapshot_detects_nonrequested_freight_matrix_mutation():
    v=state_visum();adapter=VisumAdapter(v,small_cfg());before=adapter.snapshot()
    v.Net.Matrices.ItemByKey(2).values[0,1]+=5
    after=adapter.snapshot()
    assert before['matrix_hash']!=after['matrix_hash']


def test_addval_write_expected_old_and_all_readback(tmp_path):
    v=state_visum();a=VisumAdapter(v,small_cfg());s=a.snapshot()
    a.baseline_addval={k:r['addval1'] for k,r in a.read_links().items()}
    a.supply_path_proof={'parent_hash':s['state_hash'],'assignment_path_hash':'synthetic-proof'}
    candidate={'parent_hash':s['state_hash'],'assignment_path_hash':'synthetic-proof','changes':[{'key':list(P),'expected_old':0.,'new':-1.}]}
    a.apply_supply(candidate,s,tmp_path)
    assert a.read_links()[P]['addval1']==-1
    with pytest.raises(SupplyContractError,match='STALE'):a.apply_supply(candidate,s,tmp_path)


def test_assignment_executes_no_tg_td_and_checks_gap(tmp_path):
    v=state_visum();a=VisumAdapter(v,small_cfg());calls=[]
    def execute():
        active=[r.AttValue('NO') for r in v.Procedures.Operations.items if r.AttValue('ACTIVE')]
        calls.append(active)
    v.Procedures.Execute=execute
    assert a.assign(tmp_path,supply_only=True)==pytest.approx(1e-7)
    assert calls==[[3]]
    v.Net.SetAttValue('GAP',.1)
    with pytest.raises(SupplyContractError,match='NOT_TIGHT'):a.assign(tmp_path,supply_only=True)
    assert all(x.AttValue('ACTIVE') for x in v.Procedures.Operations.items)


class OfficialList:
    def __init__(self,kind,pathrows,linkrows):self.kind=kind;self.pp=pathrows;self.ll=linkrows
    def AddKeyColumns(self):pass
    def AddColumn(self,col):pass
    def SetObjects(self,zero,code,allroutes):self.code=code
    def SaveToArray(self):
        if self.kind=='paths':
            return [[r['OrigZoneNo'],r['DestZoneNo'],r['Index'],r['Vol(AP)'],0,0,0,0,0,1] for r in self.pp]
        return [[r['OrigZoneNo'],r['DestZoneNo'],r['PathIndex'],r['Index'],r['LinkNo'],r['FromNodeNo'],r['ToNodeNo']] for r in self.ll]


def exporter_visum():
    v=state_visum();pp,ll=route_rows()
    lists=FakeAttr(CreatePrTPathList=lambda:OfficialList('paths',pp,ll),CreatePrTPathLinkList=lambda:OfficialList('links',pp,ll))
    v.Workbench=FakeAttr(Lists=lists)
    return v


def test_live_export_path_callback_uses_actual_order_and_all_volume(tmp_path):
    v=exporter_visum();cfg={'path_export_dsegs':['NATIVE_CW'],'mutable_dsegs':[],'require_all_path_export_dsegs':True}
    collector=ActualRouteCollector([profile()],SupplyPolicy(),'p',[A,P,B,C,T])
    inc,summary=rt.export_actual_paths_and_build_incidence(v,tmp_path,cfg,[profile()],[],route_batch_callback=collector.consume,build_incidence=False)
    assert inc is None and summary['dseg_path_volume_parity_passes']
    assert collector.finish()['profile_parity'][0]['actual_path_flow']==600
    assert (tmp_path/'03_PRT_PATHS_ALL.csv').exists()


def test_export_cannot_silently_drop_exog_dseg(tmp_path):
    cfg={'path_export_dsegs':['NATIVE_CW','EXOG_EE_CF'],'mutable_dsegs':[],'require_all_path_export_dsegs':True}
    with pytest.raises(RuntimeError,match='scope mismatch'):
        rt.export_actual_paths_and_build_incidence(exporter_visum(),tmp_path,cfg,[profile()],[],route_batch_callback=lambda *args:None,build_incidence=False)


def test_export_matrix_volume_parity_is_hard_gate(tmp_path):
    v=exporter_visum();v.Net.Matrices.ItemByKey(9101).values[0,1]=1500
    cfg={'path_export_dsegs':['NATIVE_CW'],'mutable_dsegs':[],'require_all_path_export_dsegs':True}
    collector=ActualRouteCollector([profile()],SupplyPolicy(),'p',[A,P,B,C,T])
    with pytest.raises(RuntimeError,match='matrix totals'):
        rt.export_actual_paths_and_build_incidence(v,tmp_path,cfg,[profile()],[],route_batch_callback=collector.consume,build_incidence=False)


def test_extra_aggregate_dseg_cannot_be_assigned_twice():
    v=op_visum();v.Procedures.Operations.items[2].SetAttValue('DSEGSET','NATIVE_CW,LNV,NV,R1_OA_CAL')
    assert not assignment_plan(v,small_cfg())['passes']


def test_gap_reader_is_probed_before_any_assignment():
    v=op_visum();c=small_cfg();c['supply']['gap_readback']['attribute']='NONEXISTENT'
    assert not assignment_plan(v,c)['passes']


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1.])
def test_matrix_fingerprint_rejects_invalid_cells(value):
    m=Matrix(1,[[1.,value],[0.,1.]])
    with pytest.raises(RuntimeError):rt._fingerprint_matrix_object(m,'x','test')


def test_raw_candidate_without_current_path_authority_is_rejected(tmp_path):
    v=state_visum();a=VisumAdapter(v,small_cfg());s=a.snapshot()
    a.baseline_addval={k:r['addval1'] for k,r in a.read_links().items()}
    candidate={'parent_hash':s['state_hash'],'changes':[{'key':list(P),'expected_old':0.,'new':-1.}]}
    with pytest.raises(SupplyContractError,match='ACTUAL_PATH_PROOF'):a.apply_supply(candidate,s,tmp_path)
