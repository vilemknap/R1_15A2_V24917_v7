"""Standalone file against native COM fakes; no calibrator needed to run it."""
import ast
import importlib
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest
from test_v24917_component_td_utilities import model, Matrix


class Attr:
    def __init__(self, **values): self.values=values; self.fail_once=None
    def AttValue(self, name): return self.values[name]
    def SetAttValue(self, name, value):
        self.values[name]=value
        if self.fail_once==name:
            self.fail_once=None
            raise RuntimeError('PARTIAL_CONTROL')


@pytest.fixture
def native(model):
    s=importlib.import_module('R1_STANDALONE_COMPONENT_TD_UTILITIES')
    m=model
    by_code={r['dstrat_code']: m.parameters[r['component']] for r in s.MAPPING}
    td=Attr(DSTRATSET=','.join(by_code))
    td.TripDistributionDStratParameters=lambda code:by_code[code]
    op=Attr(OPERATIONTYPE=46,ACTIVE=True);op.TripDistributionParameters=td
    ops=[op,Attr(OPERATIONTYPE=65,ACTIVE=True),Attr(OPERATIONTYPE=75,ACTIVE=True)]
    controls=[]
    ratios=dict(NATIVE_CW=1.2,NATIVE_CW_NOT=2.,NATIVE_CS=1.5,NATIVE_CS_NOT=3.,NATIVE_CL=1.8)
    for i,d in enumerate(s.REQUIRED_DSEGS):
        p=Attr(DSeg=d,UseExistingPaths=False,OnlyRelationsWithDemand=True)
        singles={name:Attr(Calculate=False,SaveToFile=True) for name in ('T0','TCur')}
        p.SingleSkimMatrixParameters=lambda name, ss=singles:ss[name]
        op=Attr(OPERATIONTYPE=104,ACTIVE=True);op.PrTSkimMatrixParameters=p
        ops.append(op);controls.append((p,singles))
        for j,code in enumerate(('DIS','TTC','TT0')):
            no=10100+3*i+j
            mat=Matrix(no,np.full((3,3),300. if code!='DIS' else 2.),code)
            mat.attrs['DSEGCODE']=d;m.mats[no]=mat
    m.v.Net.Matrices.GetAll=lambda:list(m.mats.values())
    ds=[]
    for d,no in s.FLOW_NOS.items():
        item=Attr(CODE=d);item.ODMatrix=m.mats[no];ds.append(item)
    m.v.Net.DemandSegments=NS(GetAll=lambda:ds)
    calls=[]
    def execute():
        assert [o.AttValue('ACTIVE') for o in ops[:2]]==[False,False]
        assert all(o.AttValue('ACTIVE') for o in ops[2:])
        for p,singles in controls:
            assert p.AttValue('UseExistingPaths') and not p.AttValue('OnlyRelationsWithDemand')
            assert all(x.AttValue('Calculate') and not x.AttValue('SaveToFile') for x in singles.values())
        for mat in m.mats.values():
            if mat.attrs['CODE']=='TTC':mat.values[:]=300.*ratios[mat.attrs['DSEGCODE']]
        calls.append('SKIMS_ONLY')
    m.v.Procedures=NS(Operations=NS(GetAll=lambda:ops),Execute=execute)
    return NS(s=s,m=m,ops=ops,controls=controls,calls=calls)


def assert_controls(e):
    assert all(o.AttValue('ACTIVE') for o in e.ops)
    for p,singles in e.controls:
        assert not p.AttValue('UseExistingPaths') and p.AttValue('OnlyRelationsWithDemand')
        assert all(not x.AttValue('Calculate') and x.AttValue('SaveToFile') for x in singles.values())


def test_standalone_creates_binds_refreshes_and_keeps_base_and_demand(native,tmp_path):
    e=native;s=e.s;m=e.m
    before={n:mat.values.copy() for n,mat in m.mats.items() if n<10000}
    rec=s.run(m.v,tmp_path)
    assert rec['status']=='UPDATED_REQUIRES_DOWNSTREAM_RECOMPUTE'
    assert e.calls==['SKIMS_ONLY'] and not rec['td_executed'] and not rec['assignment_executed']
    assert not rec['skim_proof']['assignment_epoch_certificate']
    assert m.mats[9700].values[0,1]==pytest.approx(12.)
    assert m.mats[9705].values[0,1]==pytest.approx(18.125)
    assert m.mats[9710].values[0,1]==pytest.approx(14.)
    for n,a in before.items():assert np.array_equal(m.mats[n].values,a)
    for r in s.MAPPING:assert s.ref_no(m.parameters[r['component']].raw)==r['utility_no']
    assert_controls(e)


def test_repeat_smooths_again_without_accumulating_base(native,tmp_path):
    e=native;e.s.run(e.m.v,tmp_path);e.s.run(e.m.v,tmp_path)
    assert e.m.mats[9700].values[0,1]==pytest.approx(13.)
    assert e.m.mats[9002].values[0,1]==10.


def test_existing_input_write_failure_restores_all_old_arrays(native,tmp_path):
    e=native;e.s.run(e.m.v,tmp_path)
    old={n:e.m.mats[n].values.copy() for n in e.s.UTILITY_NOS}
    e.m.mats[9703].fail_once=True
    with pytest.raises(RuntimeError,match='PARTIAL_MATRIX_WRITE'):e.s.run(e.m.v,tmp_path)
    for n,a in old.items():assert np.array_equal(e.m.mats[n].values,a)
    assert_controls(e)


def test_first_update_failure_removes_only_its_created_matrices(native,tmp_path):
    e=native;initial=set(e.m.mats);old_add=e.m.v.Net.AddMatrix
    def add(*args):
        m=old_add(*args);setter=m.SetValues
        def write(a):
            setter(a)
            if args[0]==9704 and m.writes==2:raise RuntimeError('SECOND_WRITE_FAIL')
        m.SetValues=write
        return m
    e.m.v.Net.AddMatrix=add
    with pytest.raises(RuntimeError,match='SECOND_WRITE_FAIL'):e.s.run(e.m.v,tmp_path)
    assert set(e.m.mats)==initial
    assert all(p.raw=='Matrix([NO]=9002)' for p in e.m.parameters.values())


def test_partial_control_failure_restores_before_any_setup(native,tmp_path):
    e=native;e.controls[-1][1]['TCur'].fail_once='Calculate'
    with pytest.raises(RuntimeError,match='PARTIAL_CONTROL'):e.s.run(e.m.v,tmp_path)
    assert not e.calls and not set(e.s.UTILITY_NOS)&set(e.m.mats)
    assert_controls(e)


def test_collision_fails_before_skim_execution_or_writes(native,tmp_path):
    e=native;e.m.mats[9703]=Matrix(9703,e.m.base,'SOME_OTHER_MATRIX')
    with pytest.raises(e.s.SupplyContractError,match='COLLISION'):e.s.run(e.m.v,tmp_path)
    assert not e.calls and all(m.writes==0 for m in e.m.mats.values())


def test_no_project_imports_or_missing_external_dependencies():
    s=importlib.import_module('R1_STANDALONE_COMPONENT_TD_UTILITIES')
    tree=ast.parse(Path(s.__file__).read_text())
    imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
    assert all(not x.lower().startswith('r1') for x in imports)


def test_inactive_group_cannot_silently_skip_selected_skims(native,tmp_path):
    e=native;e.ops[2].SetAttValue('ACTIVE',False)
    e.s.run(e.m.v,tmp_path)
    assert e.calls==['SKIMS_ONLY'] and not e.ops[2].AttValue('ACTIVE')


@pytest.mark.parametrize('source', ['OBJECTTYPEREF_ZONE', '2', '2.0'])
def test_live_com_text_enums_are_converted_before_addmatrix(native,tmp_path,source):
    e=native
    base=e.m.mats[9002]
    base.attrs.update(OBJECTTYPEREF=source,MATRIXTYPE='MATRIXTYPE_SKIM',DATASOURCETYPE='DATASOURCETYPE_DATA')
    rec=e.s.run(e.m.v,tmp_path)
    assert rec['status']=='UPDATED_REQUIRES_DOWNSTREAM_RECOMPUTE'
    assert e.m.mats[9700].attrs['OBJECTTYPEREF']==2
    assert e.m.mats[9700].attrs['MATRIXTYPE']==4
