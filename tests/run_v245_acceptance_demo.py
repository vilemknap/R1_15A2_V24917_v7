"""Reproduce V245 offline acceptance journeys; native calls are synthetic.
Usage: python tests/run_v245_acceptance_demo.py OUTPUT_DIRECTORY
Requires pytest, numpy and the test dependencies. Never connects to Visum.
"""
from pathlib import Path
import json
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_v245_workflow import execute
from test_v245_native_bridge import fixture
import r1_15a2_finecdf_bridge_v242 as bridge
from types import SimpleNamespace


def main(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    scenarios={
        'complete':{},
        'generation_failure':{'fail_generation':True},
        'td_failure_after_write':{'fail_td':True},
        'td_budget':{'td_reason':'TD_EVALUATION_BUDGET'},
        'supply_failure':{'fail_supply':True},
        'stop_after_td':{'td_reason':'GLOBAL_USERSTOPREQUESTED','stop_after_td':True},
    }
    report={'scope':'OFFLINE_REAL_PYTHON_CONTROLLERS_SYNTHETIC_NATIVE_BOUNDARIES',
            'live_visum_tested':False,'production_ready':False,'scenarios':{}}
    for name,flags in scenarios.items():
        with pytest.MonkeyPatch.context() as mp:
            result,a,ctl=execute(output/name,mp,**flags)
            report['scenarios'][name]={
                'status':result['status'],'accepted_count':result['accepted_count'],
                'completed_demand_cycles':result['completed_demand_cycles'],
                'supply_started':result['supply_started'],
                'final_state_verified':result['final_state_verified'],
                'calibration_complete':result['calibration_complete'],
                'assignment_fixture_calls':len(a.assignments),
                'final_state_hash':result.get('final_state_hash'),
                'load_version_called':result['load_version_called'],
                'direct_od_matrix_writes':result['direct_od_matrix_writes']}
    with pytest.MonkeyPatch.context() as mp:
        ref,path,sha,v,cfg,control,grav,mats,calls=fixture(output/'finecdf_fixture')
        mp.setattr(bridge,'load_reference',lambda root:(ref,path,sha))
        result=bridge.run_finecdf_inner(SimpleNamespace(visum=v),cfg,output/'finecdf_fixture/inner',control,ROOT)
        report['finecdf']={k:result[k] for k in ('stop_reason','search_complete','objective_start',
                'objective_final','objective_improvement','td_evaluations','changed_components','reference_sha256')}
        report['finecdf'].update(grid_nodes=512,fixture_zones=4,native_boundary='SYNTHETIC_ROW_NORMALIZED_RESPONSE_NOT_VISUM_MULTI',
                                real_681_zone_patch_preflight='NOT_EXECUTED_IN_THIS_FIXTURE')
    assert report['scenarios']['complete']['calibration_complete']
    assert all(not r['calibration_complete'] for n,r in report['scenarios'].items() if n!='complete')
    report['status']='PASS_OFFLINE_DEMONSTRATIONS'
    (output/'V245_ACCEPTANCE_DEMO_REPORT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    main(sys.argv[1])
