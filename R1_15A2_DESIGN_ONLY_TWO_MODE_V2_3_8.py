# -*- coding: utf-8 -*-
"""Run from Visum Scripts > Execute script file, outside Procedure Sequence.

Experimental two-mode geometry sharing. This entrypoint NEVER enables APPLY,
executes assignment, or reloads a version. Full geometry identity is unproven.
All progress/errors go to files beside the .ver that was open at entry.
"""
from pathlib import Path
from datetime import datetime
import contextlib
import csv
import json
import os
import sys
import traceback

HERE=Path(__file__).resolve().parent
if globals().get('Visum') is not None or globals().get('COM') is not None:
    if getattr(sys,'_r1_15a2_calibration_busy',False):
        raise RuntimeError('ANOTHER_15A2_RUN_IS_ACTIVE')
    for name in list(sys.modules):
        if name.startswith('r1_15a2_'):
            del sys.modules[name]
sys.path.insert(0,str(HERE))

import r1_15a2_com_compat as com
import r1_15a2_live_api_audit as api_audit
import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp
from r1_15a2_two_mode_v238 import RunControl, PROVISIONAL, atomic_json
from r1_15a2_two_mode_adapter_v238 import VisumAdapter
from r1_15a2_controller_v22 import run_calibration
from r1_15a2_supply import canonical_hash

RELEASE='R1_15A2_V2_3_8_TWO_MODE_DESIGN_ONLY_20261016'


def load_config():
    path=HERE/'R1_15A2_CONFIG_V2_3_8.json'
    cfg=rt.read_json(path)
    cfg['apply']=False
    cfg['two_mode']['design_only']=True
    cfg['config_path']=str(path)
    cfg['config_sha256']=rt.sha256_file(path)
    cfg['implementation_hash']=canonical_hash({p.name:rt.sha256_file(p)
        for p in sorted(HERE.glob('*.py'))})
    for rel,target in ((cfg['tg_dependency_contract_file'],'tg_dependency_contract'),
                        (cfg['td']['long_authority_file'],'long_authority')):
        p=HERE/rel
        cfg[target]=rt.read_json(p);cfg[target+'_path']=str(p)
        cfg[target+'_sha256']=rt.sha256_file(p)
    cfg['api_approved_observations']=[]
    for fn in ('R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv','R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv'):
        with (HERE/'authorities'/fn).open(encoding='utf-8-sig',newline='') as h:
            for r in csv.DictReader(h):
                cfg['api_approved_observations'].append({'no':int(r['countlocation_no']),
                    'observed':float(r['observed_passenger_cars_O']),'role':r['role'],
                    'weight':float(r['live_weight']),
                    'edge_key':[int(r[k]) for k in ('current_link_no','current_from_node_no','current_to_node_no')],
                    'direction':r.get('observation_direction','DIRECTIONAL'),
                    'countlocation_code':r['countlocation_code'],'profile_id':r['profile_id'],
                    'period_basis':r['period_basis'],
                    'observed_scope':r.get('vehicle_scope_original',r.get('vehicle_scope'))})
    return cfg


def main():
    visum,_=com.bind_injected(globals())
    root,_=api_audit.project_output_root(visum)
    source_version=str(visum.IO.CurrentVersionFile)
    # Resolve ONCE at entry. This adapter uses JSON fingerprints, never SaveVersion.
    runs=root.parent/'R1_15A2_V2_3_8_RUNS'
    runs.mkdir(parents=True,exist_ok=True)
    folder=runs/('RUN_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    folder.mkdir()
    (runs/'LATEST_RUN.txt').write_text(str(folder),encoding='utf-8')
    (folder/'00_RELEASE.txt').write_text(RELEASE,encoding='utf-8')
    cfg=load_config()
    lock=runs/'DESIGN_RUN.lock'
    adapter=control=None
    have_lock=False
    result={'status':'STARTING','apply':False,'apply_permitted':False}
    with (folder/'CONSOLE_CAPTURE.log').open('w',encoding='utf-8') as console:
        with contextlib.redirect_stdout(console),contextlib.redirect_stderr(console):
            try:
                fd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY)
                with os.fdopen(fd,'w',encoding='utf-8') as h:
                    json.dump({'pid':os.getpid(),'run':str(folder)},h)
                have_lock=True
                sys._r1_15a2_calibration_busy=True
                control=RunControl(folder,cfg['two_mode'])
                rt.Visum=visum
                atomic_json(folder/'EFFECTIVE_CONFIG.json',cfg)
                control.checkpoint('LIVE_API_PREFLIGHT',force=True)
                def td_check():
                    state=vp.read_td_parameter_state(visum)
                    return {'passes':all(r['status']=='OK' for r in state['rows']),
                            'rows':state['rows'],'operation_rows':state['operation_rows']}
                report=api_audit.collect_live_api(visum,cfg,folder/'API_PREFLIGHT',extra_checks=(
                    ('TG_FORMULA_PARAMETER_BINDINGS',lambda:vp.audit_trip_generation_contract(visum,cfg)),
                    ('TD_COMPONENT_PARAMETER_BINDINGS',td_check),
                    ('PROCSEQ_TYPE_ORDER',lambda:rt.audit_procseq(visum,folder/'API_PREFLIGHT',cfg))))
                if report['required_failures']:
                    result={'status':'LIVE_API_PREFLIGHT_FAILED','apply':False,
                            'required_failures':report['required_failures']}
                else:
                    adapter=VisumAdapter(visum,cfg,control)
                    result=run_calibration(adapter,cfg,folder/'CALIBRATION',resume_from=None)
            except BaseException as exc:
                result={'status':'DESIGN_ONLY_STOPPED' if getattr(exc,'stop_design_run',False) else 'DESIGN_ONLY_FAILED',
                    'apply':False,'error':str(exc),'traceback':traceback.format_exc()}
            finally:
                result.update(release=RELEASE,apply=False,apply_permitted=False,
                    pathlink_geometry_full_identity_proven=False,geometry_identity=PROVISIONAL,
                    assignment_executed=False,calibration_parameter_writes=False,
                    automatic_reload=False,run_directory=str(folder),
                    loaded_version_file_at_start=source_version,save_version_called=False)
                if adapter is not None:
                    try:
                        result['final_state_matches_initial_snapshot']=(
                            adapter.initial_snapshot is not None and adapter.snapshot()==adapter.initial_snapshot)
                        if not result['final_state_matches_initial_snapshot']:
                            result['status']='DESIGN_ONLY_STATE_UNVERIFIED_MANUAL_REOPEN_REQUIRED'
                    except Exception as exc:
                        result.update(status='DESIGN_ONLY_STATE_UNVERIFIED_MANUAL_REOPEN_REQUIRED',
                                      final_state_check_error=str(exc))
                    finally:
                        adapter.close()
                atomic_json(folder/'00_RESULT.json',result)
                (folder/'00_FINAL_STATUS.txt').write_text(result['status']+'\n',encoding='utf-8')
                if control is not None:
                    control.finish(result['status'])
                if have_lock:
                    sys._r1_15a2_calibration_busy=False
                    lock.unlink(missing_ok=True)
    return result


if __name__=='__main__' or globals().get('Visum') is not None or globals().get('COM') is not None:
    main()
