"""Reproducible OFFLINE state-machine demo, not a Visum assignment benchmark."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from synthetic_v22_adapter import SyntheticAdapter,synthetic_config
from r1_15a2_controller_v22 import run_calibration


def main(output):
    output=Path(output)
    cfg=synthetic_config();adapter=SyntheticAdapter(cfg)
    result=run_calibration(adapter,cfg,output/'transactions')
    assert result['accepted_count']==3,result
    assert result['blocks'][0]['selected_trial']==2,result
    report={'scope':'SYNTHETIC_CONTROLLER_WITH_DETERMINISTIC_STUB_NOT_VISUM_NOT_DIAL_B',
            'live_visum_tested':False,'accepted_blocks':result['accepted_count'],
            'supply_selected_trial':result['blocks'][0]['selected_trial'],
            'final_addval1':adapter.state['a'],'final_q':adapter.state['q'],'final_b':adapter.state['b'],
            'assignment_stub_calls':len(adapter.assignments),'verified_restores':adapter.restores,
            'accepted_ledgers':[b['ledger'] for b in result['blocks'] if b.get('status')=='ACCEPTED'],
            'status':result['status']}
    (output/'DEMO_REPORT.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python tests/run_v22_synthetic_controller_demo.py OUTPUT_DIRECTORY')
    main(sys.argv[1])
