#!/usr/bin/env python3
"""Run all supported suites in separate processes (avoids conftest name collisions).

No Visum process is started. Requires Python plus the dependencies of the original
calibrator, numpy/scipy and pytest. Does not install packages or change options.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SUITES = (('main', 'tests'), ('diagfast', 'diagfast_tests'), ('audit_genfix2', 'genfix2_audit_tests'))


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--timeout',type=int,default=600,help='Hard limit per suite, seconds')
    args=parser.parse_args()
    out=(args.output or Path(tempfile.mkdtemp(prefix='R1_GENFIX2_CHECK_'))).resolve()
    out.mkdir(parents=True,exist_ok=True)
    records=[]
    # Some inherited launcher tests intentionally update these status outputs.
    preserve={name:(ROOT/name).read_bytes() for name in
              ('V24916_LAST_BOOTSTRAP_FAILURE.json','V24916_LAST_RUNS_LOCATION.txt') if (ROOT/name).is_file()}
    try:
        for name,folder in SUITES:
            env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',
                     PYTHONDONTWRITEBYTECODE='1',R1_AUDIT_EVIDENCE=str(out/'audit_evidence'))
            env['PYTHONPATH']=os.pathsep.join([str(ROOT),str(ROOT/'tests')]) if name!='diagfast' else str(ROOT)
            cmd=[sys.executable,'-m','pytest','-q','-p','no:cacheprovider',str(ROOT/folder)]
            start=time.monotonic()
            with (out/(name+'.log')).open('w',encoding='utf-8') as log:
                try:
                    process=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout)
                    rc=process.returncode
                except subprocess.TimeoutExpired:
                    rc=124
                    log.write('\nGENFIX2_TEST_TIMEOUT\n')
            record={'suite':name,'command':cmd,'returncode':rc,'seconds':round(time.monotonic()-start,3)}
            records.append(record)
            print(json.dumps(record),flush=True)
    finally:
        for name,payload in preserve.items(): (ROOT/name).write_bytes(payload)
    result={'release':'GENFIX2','offline_only':True,'live_visum_tested':False,'suites':records,
            'all_passed':len(records)==len(SUITES) and all(r['returncode']==0 for r in records),
            'output':str(out),'test_process_isolation':'REQUIRED_SEPARATE_CONFTEXTS'}
    (out/'CHECKS.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Evidence:',out,flush=True)
    return 0 if result['all_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
