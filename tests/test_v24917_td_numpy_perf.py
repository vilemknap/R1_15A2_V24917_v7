"""Exact target/skim parity and bounded COM/grid work; offline only."""
import inspect
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest
import r1_15a2_td_numpy_v24917 as perf
import r1_15a2_td_joint_v24917 as joint
import r1_15a2_dynamic_skim_v24916p2c as dyn
import r1_15a2_finecdf_bridge_v24916 as bridge
from r1_15a2_skim_v24916p2c import matrix_values_hash as legacy_hash
from r1_15a2_supply import SupplyContractError

ROOT = Path(__file__).resolve().parents[1]


def reference():
    fine = json.loads((ROOT/'R1_15A2_CONFIG_V2_4_9_15_PERF2.json').read_text())['coupled_demand']['finecdf_td']
    return bridge.load_reference(ROOT, fine)[0]


def metric_pair(n=7):
    ref = reference()
    rng = np.random.default_rng(3919)
    distances = {k: rng.uniform(0., 230., (n,n)) for k in ('WORK','SERVICE','LONG')}
    for a in distances.values():
        a.flat[:8] = [0., .1, 1., 79.99, 80., 100., 200., 200.01]
        a[1,1] = 150.
    matrices = {int(no): rng.uniform(.1, 10., (n,n)) for t in ref.TARGETS.values() for no in t['matrix_nos']}
    host = NS(dynamic_skim_epoch=NS(epoch=1, epoch_hash='one', family_distance=distances))
    class Legacy(bridge.DynamicFamilyMetrics):
        _evaluate_one = inspect.unwrap(bridge.DynamicFamilyMetrics._evaluate_one)
        evaluate = inspect.unwrap(bridge.DynamicFamilyMetrics.evaluate)
    class Fast(Legacy):
        _evaluate_one = perf._evaluate_one
        evaluate = perf.wrap_evaluate(Legacy.evaluate)
    return Legacy(host,ref), Fast(host,ref), matrices


def exact(a,b):
    assert a.keys() == b.keys()
    for key in a:
        assert a[key].keys() == b[key].keys()
        for name,value in a[key].items():
            if isinstance(value,np.ndarray): assert np.array_equal(value,b[key][name]),(key,name)
            else: assert value == b[key][name],(key,name)


def test_all_12_targets_every_output_exact_with_only_3_grid_preparations():
    old,new,m = metric_pair()
    expected=old.evaluate(m);actual=new.evaluate(m)
    assert len(actual)==12
    exact(expected,actual)
    assert new._td_perf_metrics_last == {'targets':12,'grid_preparations':3}
    assert new._td_perf_grid_scope is None


def test_grid_never_survives_flow_distance_epoch_or_target_changes():
    old,new,m = metric_pair()
    for change in ('initial','flow','distance_in_place','epoch','grid','target'):
        if change=='flow': m[9111][1,1] *= 2
        elif change=='distance_in_place': new.bridge.dynamic_skim_epoch.family_distance['LONG'][1,1]=175.
        elif change=='epoch':
            prev=new.bridge.dynamic_skim_epoch
            new.bridge.dynamic_skim_epoch=NS(epoch=2,epoch_hash='two',family_distance={k:v.copy() for k,v in prev.family_distance.items()})
        elif change=='grid':
            name='common_grid_atomic_km'
            new.ref.FINE_AUTHORITY[name]=list(new.ref.FINE_AUTHORITY[name])
            new.ref.FINE_AUTHORITY[name][1] *= 1.001
        elif change=='target': new.ref.TARGETS['WORK_E_C']['mean_km'] *= 1.1
        exact(old.evaluate(m),new.evaluate(m))
        assert new._td_perf_grid_scope is None


def test_empty_conditioned_mass_and_failed_calls_drop_grid_scope():
    old,new,m=metric_pair()
    for no in new.ref.TARGETS['LONG_COMPOSITE']['matrix_nos']: m[int(no)][:]=0.
    for obj in (old,new):
        with pytest.raises(SupplyContractError,match='NO_CONDITIONED_DEMAND'): obj.evaluate(m)
    assert new._td_perf_grid_scope is None
    for no in new.ref.TARGETS['LONG_COMPOSITE']['matrix_nos']: m[int(no)][:]=1.
    exact(old.evaluate(m),new.evaluate(m))


def test_epoch_change_during_metrics_is_never_published():
    _,new,m=metric_pair()
    original=new._evaluate_one
    def changed(*args):
        result=original(*args)
        new.bridge.dynamic_skim_epoch=NS(epoch=99,epoch_hash='different',family_distance=new.bridge.dynamic_skim_epoch.family_distance)
        return result
    new._evaluate_one=changed
    with pytest.raises(SupplyContractError,match='METRIC_EPOCH_CHANGED'): new.evaluate(m)
    assert new._td_perf_grid_scope is None


@pytest.mark.parametrize('values',[np.array([[0.,-0.],[1.e-300,1.e200]]),np.arange(20.).reshape(4,5).T,np.zeros((0,3))])
def test_blocked_hash_keeps_exact_hex_protocol(values):
    assert perf.matrix_values_hash(values)==legacy_hash(values)


def skim_fixture(monkeypatch):
    arrays={d:np.array([[-0.,10.+i],[120.+i,0.]]) for i,d in enumerate(dyn.REQUIRED_NATIVE_DSEGS)}
    reads=[]
    rows={d:{'matrix_no_int':701+i,'matrix_code':'DIS','dseg_code':d} for i,d in enumerate(arrays)}
    monkeypatch.setattr(dyn,'_native_dis_rows',lambda _:rows)
    def values(adapter,no,n,label):
        reads.append(no)
        return arrays[dyn.REQUIRED_NATIVE_DSEGS[no-701]].copy()
    monkeypatch.setattr(dyn,'_matrix_values',values)
    adapter=NS(zones=[1,2],readback_manager=NS(assignment_epoch=7))
    weights={d:np.array([[0.,float(i+1)],[0.,0.]]) for i,d in enumerate(perf.SKIM_WEIGHT_DSEGS)}
    return adapter,arrays,weights,reads


def test_all_skim_fields_and_epoch_sha_exact_with_8_hashes(monkeypatch):
    adapter,arrays,weights,reads=skim_fixture(monkeypatch)
    legacy=inspect.unwrap(dyn.DynamicSkimManager._read_epoch)
    a=dyn.DynamicSkimManager(adapter);b=dyn.DynamicSkimManager(adapter)
    expected=legacy(a,'token',[31,32,33,34,35,36],weights)
    calls=[];hash_fn=perf.matrix_values_hash
    monkeypatch.setattr(perf,'matrix_values_hash',lambda v:(calls.append(v),hash_fn(v))[1])
    actual=perf.read_epoch(b,'token',[31,32,33,34,35,36],weights)
    assert actual.summary()==expected.summary()
    assert len(calls)==8 and len(reads)==12  # Six native DIS per implementation.
    for field in ('matrices_by_dseg','family_distance'):
        for key,value in getattr(expected,field).items(): assert np.array_equal(value,getattr(actual,field)[key])
    assert actual.family_hashes['LONG']==actual.matrix_meta_by_dseg['NATIVE_CL']['values_sha256']
    assert not np.shares_memory(actual.family_distance['LONG'],actual.matrices_by_dseg['NATIVE_CL'])
    arrays['NATIVE_CL'][0,1]+=1.
    changed=perf.read_epoch(b,'new',[31,32,33,34,35,36],weights)
    assert changed.family_hashes['LONG'] != actual.family_hashes['LONG']


@pytest.mark.parametrize('fault',['missing','shape','nan','negative'])
def test_skim_weight_contract_remains_strict(monkeypatch,fault):
    adapter,_,weights,_=skim_fixture(monkeypatch)
    if fault=='missing': weights.pop('NATIVE_CW')
    elif fault=='shape': weights['NATIVE_CW']=np.ones((1,1))
    elif fault=='nan': weights['NATIVE_CW'][0,1]=np.nan
    else: weights['NATIVE_CW'][0,1]=-1.
    with pytest.raises(SupplyContractError,match='LIVE_DEMAND_'): perf.read_epoch(dyn.DynamicSkimManager(adapter),'token',[31],weights)


def weight_reader(monkeypatch, module=perf):
    reads=[]
    codes=list(dyn.REQUIRED_NATIVE_DSEGS)+['EXOG_EE_'+d for d in dyn.REQUIRED_NATIVE_DSEGS]
    class Matrix:
        def __init__(self,code):self.code=code
        def GetValues(self):reads.append(self.code);return np.array([[0.,1.],[2.,0.]])
    rows=[{'norm_code':d,'object':NS(ODMatrix=Matrix(d))} for d in codes]
    monkeypatch.setattr(module.rt,'selected_passenger_dsegs',lambda v,cfg:[r for r in rows if r['norm_code'] in cfg['path_export_dsegs']])
    return NS(cfg={'path_export_dsegs':codes,'expected_zones':2},visum=object()),reads


def test_only_four_getvalues_and_normalized_configured_identity(monkeypatch):
    adapter,reads=weight_reader(monkeypatch)
    adapter.cfg['path_export_dsegs']=[d.lower() for d in adapter.cfg['path_export_dsegs']]
    out=perf.read_skim_weights(adapter)
    assert set(out)==set(perf.SKIM_WEIGHT_DSEGS) and reads==list(perf.SKIM_WEIGHT_DSEGS)


def test_outer_skim_scope_preserves_full_generation_reader_and_cleans_on_error(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as am
    current = am.td_numpy  # Launcher tests replace module instances in sys.modules.
    adapter,reads=weight_reader(monkeypatch, current)
    a=object.__new__(am.VisumAdapter);a.__dict__.update(adapter.__dict__)
    monkeypatch.setattr(am._V24916ActiveAdapter,'_live_generation_matrices',lambda self:{'ALL_12':np.ones((2,2))})
    assert 'ALL_12' in a._live_generation_matrices()
    with pytest.raises(RuntimeError):
        with current.skim_weight_scope(a):
            assert set(a._live_generation_matrices())==set(current.SKIM_WEIGHT_DSEGS)
            raise RuntimeError('fixture')
    assert 'ALL_12' in a._live_generation_matrices() and current.SKIM_WEIGHT_SCOPE.get() is None
    assert len(reads)==4


@pytest.mark.parametrize('poll',[0,1,2,3])
def test_budget_covers_both_coordinates_of_all_12_groups(poll):
    groups=['WORK_'+str(i) for i in range(5)]+['SERV_'+str(i) for i in range(5)]+['SCHOOL','LONG_COMPOSITE']
    x={k:np.array([1.,-1.]) for k in groups}
    space=NS(probe={k:[.1,.1] for k in groups},trust={k:[1.,1.] for k in groups},bounds={k:[[0.,4.],[-3.,0.]] for k in groups})
    trials=list(joint.balanced_coordinate_proposals(space,x,groups,{k:1 for k in groups},poll_index=poll))
    assert len(trials)==48
    assert {(k,axis) for k,axis,*_ in trials[:24]}=={(k,axis) for k in groups for axis in (0,1)}
    assert len({(k,axis,sign) for k,axis,sign,_ in trials})==48
    assert trials[0][1]==poll%2 and trials[0][2]==(1 if poll//2%2==0 else -1)


def test_clipped_signs_do_not_starve_a_coordinate():
    groups=['SCHOOL','LONG_COMPOSITE'];x={k:np.array([4.,0.]) for k in groups}
    space=NS(probe={k:[.1,.1] for k in groups},trust={k:[1.,1.] for k in groups},bounds={k:[[0.,4.],[-3.,0.]] for k in groups})
    trials=list(joint.balanced_coordinate_proposals(space,x,groups,{k:1 for k in groups}))
    assert {(k,axis) for k,axis,*_ in trials[:4]}=={(k,axis) for k in groups for axis in (0,1)}
    assert all(sign==-1 for _,_,sign,_ in trials)


def test_real_outer_refresh_enters_narrow_scope_and_rebinds_long(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as am
    current=am.td_numpy
    adapter,reads=weight_reader(monkeypatch,current)
    a=object.__new__(am.VisumAdapter);a.__dict__.update(adapter.__dict__)
    epoch=object();seen=[]
    def refresh(self,*args,**kwargs):
        seen.append(self._live_generation_matrices())
        return epoch
    monkeypatch.setattr(am._V24916ActiveAdapter,'_refresh_dynamic_skims_after_assignment',refresh)
    monkeypatch.setattr(am.long_incidence_read,'bind_after_assignment',lambda owner:seen.append(owner))
    assert a._refresh_dynamic_skims_after_assignment(Path('OUT'),'TD') is epoch
    assert set(seen[0])==set(current.SKIM_WEIGHT_DSEGS) and seen[1] is a
    assert len(reads)==4 and current.SKIM_WEIGHT_SCOPE.get() is None
