"""Reproducible synthetic TD kernels benchmark; no Visum/COM, no live speed claim."""
from __future__ import annotations
import argparse
import inspect
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace as NS
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import r1_15a2_dynamic_skim_v24916p2c as dyn
import r1_15a2_finecdf_bridge_v24916 as bridge
import r1_15a2_td_numpy_v24917 as fast
from r1_15a2_skim_v24916p2c import matrix_values_hash as legacy_hash


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--zones',type=int,default=681)
    parser.add_argument('--repetitions',type=int,default=5)
    args=parser.parse_args()
    fine=json.loads((ROOT/'R1_15A2_CONFIG_V2_4_9_15_PERF2.json').read_text())['coupled_demand']['finecdf_td']
    ref,_,sha=bridge.load_reference(ROOT,fine)
    n=args.zones;rng=np.random.default_rng(20261030)
    distances={k:rng.uniform(.1,220.,(n,n)) for k in ('WORK','SERVICE','LONG')}
    flow=rng.uniform(0.,10.,(n,n));flow[flow<3.]=0.
    matrices={int(no):flow for t in ref.TARGETS.values() for no in t['matrix_nos']}
    host=NS(dynamic_skim_epoch=NS(epoch=1,epoch_hash='synthetic',family_distance=distances))
    class Legacy(bridge.DynamicFamilyMetrics):
        _evaluate_one=inspect.unwrap(bridge.DynamicFamilyMetrics._evaluate_one)
        evaluate=inspect.unwrap(bridge.DynamicFamilyMetrics.evaluate)
    class Optimized(Legacy):
        _evaluate_one=fast._evaluate_one
        evaluate=fast.wrap_evaluate(Legacy.evaluate)
    old,new=Legacy(host,ref),Optimized(host,ref)
    timings={k:[] for k in ('metrics_old','metrics_new','hash_old','hash_new','skims_old','skims_new')}
    def timed(key,fn):
        start=time.perf_counter();result=fn();timings[key].append(time.perf_counter()-start);return result
    for repeat in range(args.repetitions):
        for name,obj in (('old',old),('new',new)) if repeat%2==0 else (('new',new),('old',old)):
            out=timed('metrics_'+name,lambda:obj.evaluate(matrices))
            if name=='old':expected=out
            else:actual=out
        for key in expected:
            for field,value in expected[key].items():
                candidate=actual[key][field]
                assert np.array_equal(value,candidate) if isinstance(value,np.ndarray) else value==candidate,(key,field)
        for name,fn in (('old',legacy_hash),('new',fast.matrix_values_hash)):
            value=timed('hash_'+name,lambda:fn(distances['WORK']))
            if name=='old':expected_hash=value
            else:assert value==expected_hash
    # Full six-DIS capture kernels, including ownership copies, weighted-family
    # matrices, validation and all epoch metadata. Native reads are mocked only
    # here; this benchmark cannot measure actual COM transport or assignment.
    skim_arrays={d:distances['LONG'] if d=='NATIVE_CL' else distances['WORK'] for d in dyn.REQUIRED_NATIVE_DSEGS}
    rows={d:{'matrix_no_int':701+i,'matrix_code':'DIS','dseg_code':d} for i,d in enumerate(dyn.REQUIRED_NATIVE_DSEGS)}
    adapter=NS(zones=list(range(1,n+1)),readback_manager=NS(assignment_epoch=1))
    weights={d:flow for d in fast.SKIM_WEIGHT_DSEGS}
    original_rows,original_values=dyn._native_dis_rows,dyn._matrix_values
    try:
        dyn._native_dis_rows=lambda _:rows
        dyn._matrix_values=lambda adapter,no,n,label:skim_arrays[dyn.REQUIRED_NATIVE_DSEGS[no-701]].copy()
        old_read=inspect.unwrap(dyn.DynamicSkimManager._read_epoch)
        for repeat in range(args.repetitions):
            for name,fn in (('old',old_read),('new',fast.read_epoch)) if repeat%2==0 else (('new',fast.read_epoch),('old',old_read)):
                manager=dyn.DynamicSkimManager(adapter)
                epoch=timed('skims_'+name,lambda:fn(manager,'synthetic',[31,32,33,34,35,36],weights))
                if name=='old':old_epoch=epoch
                else:new_epoch=epoch
            assert old_epoch.summary()==new_epoch.summary()
            for field in ('matrices_by_dseg','family_distance'):
                for key,a in getattr(old_epoch,field).items():assert np.array_equal(a,getattr(new_epoch,field)[key])
    finally:
        dyn._native_dis_rows, dyn._matrix_values=original_rows,original_values
    medians={k:statistics.median(v) for k,v in timings.items()}
    result={'scope':'SYNTHETIC_NUMPY_ONLY_NOT_END_TO_END_VISUM','zones':n,'cells':n*n,
        'reference_sha256':sha,'all_outputs_exact':True,'all_skim_fields_and_epoch_hash_exact':True,
        'metrics_grid_preparations':{'before':len(ref.TARGETS),'after':new._td_perf_metrics_last['grid_preparations']},
        'full_skim_hashes':{'before':10,'after':8},'native_dis_reads':6,
        'seconds':timings,'median_seconds':medians,
        'speedup':{label:medians[label+'_old']/medians[label+'_new'] for label in ('metrics','hash','skims')},
        'com_transport_measured':False,'live_visum_tested':False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
