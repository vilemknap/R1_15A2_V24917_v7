"""Consecutive best restore proof over actual sealed execute/restore methods."""
import copy
import inspect
from pathlib import Path
from types import MethodType, SimpleNamespace as NS

import numpy as np
import pytest
import r1_15a2_finecdf_bridge_v24916 as bridge
import r1_15a2_dynamic_skim_v24916p2c as dyn
import r1_15a2_td_restore_v24917 as perf
import r1_15a2_td_numpy_v24917 as kernels
import r1_15a2_long_composite_td_v24917 as long_td
import r1_15a2_school_td_v24917 as school_td
from r1_15a2_candidate_readback_bundle_v24915p2 import CandidateReadbackManager
from r1_15a2_supply import canonical_hash, SupplyContractError


@pytest.fixture
def native(monkeypatch,tmp_path):
    mutable=tuple(range(9101,9116))+(9117,)
    state=NS(native_calls=0,reads=[],coeff={no:{'a':1.,'b':1.,'c':-.1} for no in mutable+(9116,)},
        arrays={},attrs={},matrix_codes={},dseg_matrix_numbers={},override_parameter=False,fail_native=False)
    attrs=('ADD_PROD_W','ADD_ATT_W','ADD_PROD_S','ADD_ATT_S','ADD_SALARY',
           'ZAHR_PROD_WORK','ZAHR_PROD_SERV','ZAHR_ATR_WORK','ZAHR_ATR_SERV')
    for attr in attrs+school_td.GENERATION_ATTRS+long_td.GENERATION_ATTRS+('ADD_PROD_L','ADD_ATT_L'):
        state.attrs[attr]=[1.,1.]
    class Zones:
        def GetMultiAttValues(self,attr):
            return list(enumerate([1,2] if attr=='NO' else state.attrs[attr],1))
    class Matrix:
        def __init__(self,no):self.no=no
        def GetValues(self):state.reads.append(self.no);return state.arrays[self.no].copy()
        def AttValue(self,attr):
            return {'NO':self.no,'CODE':state.matrix_codes.get(self.no,'M%d'%self.no)}[attr]
    class Op:
        def AttValue(self,attr):return {'OPERATIONTYPE':46,'ACTIVE':1}[attr]
    class TD:
        def AttValue(self,attr):assert attr=='DSTRATSET';return 'R1_MUTABLE'
    v=NS(Net=NS(Zones=Zones(),Links=NS(GetMultiAttValues=lambda _: [(1,2.)]),
                  Matrices=NS(ItemByKey=Matrix)))
    for no in mutable+(9001,9002,9697,9116):state.arrays[no]=np.array([[1.,2.],[3.,4.]])
    for i,d in enumerate(dyn.REQUIRED_NATIVE_DSEGS):state.arrays[701+i]=np.array([[0.,120.+i],[150.+i,0.]])
    codes=list(dyn.REQUIRED_NATIVE_DSEGS)+['EXOG_EE_'+d for d in dyn.REQUIRED_NATIVE_DSEGS]
    state.dseg_matrix_numbers={code:9300+i for i,code in enumerate(codes)}
    class DSeg:
        def __init__(self,code):self.code=code
        def AttValue(self,attr):return {'CODE':self.code}[attr]
        @property
        def ODMatrix(self):return Matrix(state.dseg_matrix_numbers[self.code])
    v.Net.DemandSegments=NS(GetAll=lambda:[DSeg(code) for code in codes],Count=len(codes))
    for i,_ in enumerate(codes):state.arrays[9300+i]=np.array([[0.,10.+i],[20.+i,0.]])
    rm=CandidateReadbackManager({},run_token='run',visum_session_token='session')
    outer=NS(zones=[1,2],visum=v,cfg={'path_export_dsegs':codes,'expected_zones':2},
             readback_manager=rm,last_gap_evidence={'gap':.001},_long_post_td_mask_enabled=True,
             v24917_ls={'active':True})
    outer._live_generation_matrices=lambda:{code:state.arrays[state.dseg_matrix_numbers[code]].copy() for code in codes}
    manager=outer.v24916_dynamic_skims=dyn.DynamicSkimManager(outer)
    rows={d:{'matrix_no_int':701+i,'matrix_code':'DIS','dseg_code':d} for i,d in enumerate(dyn.REQUIRED_NATIVE_DSEGS)}
    monkeypatch.setattr(dyn,'_native_dis_rows',lambda _:rows)
    b=object.__new__(bridge.NoDirectMatrixWriteTDAdapter)
    b.v=v;b.n=2;b.root=tmp_path;b.outer_adapter=outer;b.dynamic_skim_enabled=True
    b._v24917_frozen=False;b.zone_order=[1,2];b.ops=[Op()];b.td=TD();b.dynamic_eval_index=0
    b.td_index=1;b.ops[0].TripDistributionParameters=b.td
    v.Procedures=NS(Operations=NS(GetAll=lambda:b.ops))
    b.ref=NS(np=np,CONFIG={'parameter_readback_atol':1.e-8},MUTABLE_NOS=mutable,
             GROUPS=['WORK_E_C','SCHOOL','LONG_COMPOSITE'],
             sha_array=lambda a:canonical_hash(np.asarray(a).tolist()))
    b.protected_hashes={no:b.ref.sha_array(state.arrays[no]) for no in (9001,9697,9116)}
    b.generation_guard={attr:[[str(i),str(value)] for i,value in enumerate(state.attrs[attr],1)] for attr in attrs}
    b.addval_guard=canonical_hash([('1','2.0')])
    b.assert_isolated=lambda:None
    b._dynamic_realization_plan=lambda:{'selected_operation_positions':[1], 'dynamic_skim_operation_positions':[31,32,33,34,35,36]}
    b.read_abc=lambda:copy.deepcopy(state.coeff)
    def set_abc(self,abc):state.coeff=copy.deepcopy(abc);return self.read_abc()
    b.set_abc=MethodType(perf.invalidate_on_call(set_abc),b)
    def native_realization():
        state.native_calls+=1;b.dynamic_eval_index+=1
        rm.mark_assignment_started(reason='TEST_NATIVE_TD')
        if state.fail_native:
            rm.mark_assignment_failed('injected')
            raise RuntimeError('NATIVE_FAILED')
        for no in mutable:
            state.arrays[no]=np.array([[1.,2.],[3.,4.]])*state.coeff[no]['b']
        for i,code in enumerate(codes):state.arrays[state.dseg_matrix_numbers[code]]=np.array([[0.,10.+i],[20.+i,0.]])
        for i,_ in enumerate(dyn.REQUIRED_NATIVE_DSEGS):state.arrays[701+i]=np.array([[0.,120.+i],[150.+i,0.]])
        if state.override_parameter:state.coeff[9101]['b']+=.1
        rm.mark_assignment_completed({'gap':.001})
        epoch=manager.capture_after_execution(tmp_path/('EPOCH_%d'%state.native_calls),'native-'+str(state.native_calls),
                    [31,32,33,34,35,36],outer._live_generation_matrices())
        b.dynamic_skim_epoch=epoch
        return epoch
    b._execute_dynamic_realization=native_realization
    b.execute=MethodType(perf.invalidate_on_call(inspect.unwrap(bridge.NoDirectMatrixWriteTDAdapter.execute)),b)
    b.restore_state=MethodType(perf.wrap_restore(inspect.unwrap(bridge.NoDirectMatrixWriteTDAdapter.restore_state)),b)
    b.execute()
    expected={no:state.arrays[no].copy() for no in mutable};abc=b.read_abc()
    state.native_calls=0;state.reads=[]
    return b,state,abc,expected


def test_actual_native_restore_then_one_proven_skip_and_exact_outputs(native):
    b,s,abc,expected=native
    b.restore_state(abc,expected)
    assert s.native_calls==1 and b._td_perf_restore_receipt is not None
    epoch=b.dynamic_skim_epoch
    actual=b.restore_state(abc,expected)
    assert s.native_calls==1 and b.dynamic_skim_epoch is epoch
    for no,a in expected.items():assert np.array_equal(actual[no],a)
    assert b._td_perf_restore_receipt is None
    assert b._td_perf_restore_audit['verified_reuses']==1
    b.restore_state(abc,expected)
    assert s.native_calls==2  # Reuse authority was consumed, never persistent.


@pytest.mark.parametrize('fault',['person_od','vehicle_od','utility','skim','cached_family','cached_skim','untracked_abc','mutation','new_epoch','session','run',
                                  'assignment_failed','assignment_in_progress','controls','frozen','set_abc'])
def test_changes_never_reuse_a_stale_native_proof(native,fault):
    b,s,abc,expected=native;b.restore_state(abc,expected)
    rm=b.outer_adapter.readback_manager
    if fault=='person_od':s.arrays[9101][0,1]+=1
    elif fault=='vehicle_od':s.arrays[9300][0,1]+=1
    elif fault=='utility':s.arrays[9002][0,1]+=1
    elif fault=='skim':s.arrays[701][0,1]+=1
    elif fault=='cached_family':b.dynamic_skim_epoch.family_distance['LONG'][0,1]+=1
    elif fault=='cached_skim':b.dynamic_skim_epoch.matrices_by_dseg['NATIVE_CW'][0,1]+=1
    elif fault=='untracked_abc':s.coeff[9101]['b']+=.1
    elif fault=='mutation':rm.invalidate('test')
    elif fault=='new_epoch':
        b.outer_adapter.v24916_dynamic_skims.current=None
    elif fault=='session':rm.visum_session_token='other'
    elif fault=='run':rm.run_token='other'
    elif fault=='assignment_failed':rm.mark_assignment_failed('test')
    elif fault=='assignment_in_progress':rm.assignment_in_progress=True
    elif fault=='controls':b._dynamic_realization_plan=lambda:{'selected_operation_positions':[1,2]}
    elif fault=='frozen':b._v24917_frozen=True
    else:b.set_abc(abc)
    b.restore_state(abc,expected)
    assert s.native_calls==2 and b._td_perf_restore_audit['verified_reuses']==0


@pytest.mark.parametrize('attr',['ADD_PROD_W','FP_5_SCHOOL','FA_5_SCHOOL','FP_3_LONG_E_C','FA_3_LONG','ADD_PROD_L','ADD_ATT_L'])
def test_actual_generation_change_fails_closed_before_skip(native,attr):
    b,s,abc,expected=native;b.restore_state(abc,expected)
    s.attrs[attr][0]+=.1
    with pytest.raises((SupplyContractError,RuntimeError),match='GENERATION|generation'):b.restore_state(abc,expected)
    assert s.native_calls==1 and b._td_perf_restore_receipt is None


@pytest.mark.parametrize('no',[9001,9697,9116])
def test_protected_change_cannot_be_hidden_by_reuse(native,no):
    b,s,abc,expected=native;b.restore_state(abc,expected);s.arrays[no][0,1]+=1.
    with pytest.raises(SupplyContractError,match='PROTECTED_MATRIX_CHANGED'):b.restore_state(abc,expected)
    assert s.native_calls==1 and b._td_perf_restore_receipt is None


def test_native_parameter_override_after_recompute_does_not_certify_best(native):
    b,s,abc,expected=native;s.override_parameter=True
    with pytest.raises(SupplyContractError,match='RESTORE_PARAMETER_CHANGED'):b.restore_state(abc,expected)
    assert b._td_perf_restore_receipt is None


def test_failed_native_restore_cannot_leave_receipt(native):
    b,s,abc,expected=native;b.restore_state(abc,expected)
    b.set_abc(abc);s.fail_native=True
    with pytest.raises(RuntimeError,match='NATIVE_FAILED'):b.restore_state(abc,expected)
    assert b._td_perf_restore_receipt is None


def test_request_within_original_tolerance_still_gets_native_verification(native):
    b,s,abc,expected=native;b.restore_state(abc,expected)
    near={n:a.copy() for n,a in expected.items()};near[9101][0,0]+=1.e-10
    b.restore_state(abc,near)
    assert s.native_calls==2
    bad={n:a.copy() for n,a in expected.items()};bad[9101][0,0]+=.1
    with pytest.raises(SupplyContractError,match='RECOMPUTE_ROLLBACK_MATRIX_DIFFER'):b.restore_state(abc,bad)
    assert b._td_perf_restore_receipt is None


def test_proof_drift_during_read_and_cleanup_never_reuses(native,monkeypatch):
    b,s,abc,expected=native;b.restore_state(abc,expected)
    original=b.read_matrix
    def drift(no):
        out=original(no)
        if no==9002:b.outer_adapter.readback_manager.invalidate('during-proof')
        return out
    monkeypatch.setattr(b,'read_matrix',drift)
    with pytest.raises(SupplyContractError,match='STATE_CHANGED_DURING_PROOF'):b.restore_state(abc,expected)
    assert b.read_matrix is drift and b._td_perf_restore_receipt is None


def test_post_execution_read_scope_reads_each_matrix_once_and_restores_method(native):
    b,s,_,_=native
    original=b.read_matrix;start=len(s.reads)
    with perf.matrix_read_scope(b):
        a=b.read_matrix(9697);c=b.read_matrix(9697)
        assert a is c
    assert s.reads[start:]==[9697] and b.read_matrix==original
    s.arrays[9697][0,1]+=1
    assert b.read_matrix(9697)[0,1]!=a[0,1]


@pytest.mark.parametrize('fail_controls',[False,True])
def test_real_inner_owner_skips_second_restore_and_still_runs_control_cleanup(native,monkeypatch,tmp_path,fail_controls):
    import json
    b,s,abc,expected=native
    root=Path(__file__).resolve().parents[1]
    fine=json.loads((root/'R1_15A2_CONFIG_V2_4_9_15_PERF2.json').read_text())['coupled_demand']['finecdf_td']
    ref,path,sha=bridge.load_reference(root,fine)
    b.ref=ref
    b.protected_hashes={no:ref.sha_array(s.arrays[no]) for no in (9001,9697,9116)}
    cleanup=[]
    b.entry_abc=copy.deepcopy(abc)
    b.isolate_td=lambda:None
    def restore_controls():
        cleanup.append('RESTORE_ACTIVE_DSTRATSET')
        if fail_controls:raise SupplyContractError('CONTROL_RESTORE_FAILED')
    b.restore_controls=restore_controls
    class Runner:
        def __init__(self,adapter,log):
            self.adapter=adapter;self.evaluations=1
            self.best=self.baseline={'abc':abc,'matrices':expected,'metrics':{'WORK_E_C':{'objective':.1}}}
        def optimize(self):
            self.adapter.restore_state(abc,expected)  # Optimizer's verified native best.
            return 'MAX_ITERATIONS'
    ref.Runner=Runner
    ref.write_diagnostics=lambda *args,**kwargs:None  # Orthogonal CSV formatting.
    monkeypatch.setattr(bridge,'load_reference',lambda root,fine_cfg=None:(ref,path,sha))
    monkeypatch.setattr(bridge,'NoDirectMatrixWriteTDAdapter',lambda *args,**kwargs:b)
    control=NS(remaining=lambda:1000.,checkpoint=lambda *args,**kwargs:None)
    call=lambda:inspect.unwrap(bridge.run_finecdf_inner)(b.outer_adapter,{'coupled_demand':{'finecdf_td':{
        'max_td_evaluations':2,'max_iterations':1}}},tmp_path/'INNER',control,root)
    if fail_controls:
        with pytest.raises(SupplyContractError,match='CONTROL_RESTORE_FAILED'):call()
    else:
        result=call()
        assert result['status']=='COMPLETED_BEST_STATE_RETAINED' and not result['search_complete']
    assert cleanup==['RESTORE_ACTIVE_DSTRATSET']
    assert s.native_calls==1 and b._td_perf_restore_audit['verified_reuses']==1
