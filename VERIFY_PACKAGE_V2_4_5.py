"""Read-only release verifier. --tests runs offline tests, never Visum.

Usage: python VERIFY_PACKAGE_V2_4_5.py [--tests] [--json /outside/package/report.json]
CP03 verifies the live path-length hotfix package; it does not execute Visum.
The manifest authenticates delivered bytes, not an executed real-network result.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
MANIFEST='PACKAGE_INVENTORY_V245_CP03.json'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def ignored(p):
    return any(x in ('__pycache__','.pytest_cache') for x in p.parts) or p.suffix in ('.pyc','.pyo')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests',action='store_true')
    parser.add_argument('--json',type=Path)
    args=parser.parse_args()
    report={'scope':'V245_CP03_DELIVERY_BYTES_AND_OPTIONAL_OFFLINE_TESTS','live_visum_tested':False,
            'production_ready':False,'package_root':str(ROOT),'errors':[]}
    started=time.monotonic()
    try:
        manifest=json.loads((ROOT/MANIFEST).read_text(encoding='utf-8'))
        expected=manifest['files']
        for rel,info in expected.items():
            path=ROOT/rel
            if not path.is_file():report['errors'].append('MISSING:'+rel)
            elif path.stat().st_size!=info['size'] or sha(path)!=info['sha256']:
                report['errors'].append('BYTE_MISMATCH:'+rel)
        actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and not ignored(p.relative_to(ROOT))}
        unexpected=actual-set(expected)-{MANIFEST}
        if unexpected:report['errors'].append('UNEXPECTED_FILES:'+','.join(sorted(unexpected)))
        report['expected_file_count']=len(expected)
        report['manifest_sha256']=sha(ROOT/MANIFEST)
        report['byte_integrity_pass']=not report['errors']
        # Do not execute even the configuration loader until all bytes match.
        if report['errors']:raise RuntimeError('PACKAGE_INTEGRITY_FAILED')
        spec=importlib.util.spec_from_file_location('verify_v245_launcher',ROOT/'R1_15A2_FULL_OVERNIGHT_COUPLED_V2_4_5.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        cfg=module.load_config()
        report['config_loaded']=True
        report['implementation_hash']=cfg['implementation_hash']
        report['cp03_live_hotfixes']=cfg.get('cp03_live_hotfixes',[])
        if set(report['cp03_live_hotfixes']) != {'SHORT_RUN_ROOT','SHORT_OS_TEMP_11D_12D_HELPER_WORKSPACES','ROLLBACK_STATE_EVIDENCE_BEFORE_DIAGNOSTICS'}:
            raise RuntimeError('CP03_HOTFIX_DECLARATION_MISSING')
        report['observation_rows']=len(cfg['api_approved_observations'])
        if report['observation_rows']!=498:raise RuntimeError('OBSERVATION_COUNT_CHANGED')
        if args.tests:
            command=[sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','tests']
            proc=subprocess.run(command,cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),
                                capture_output=True,text=True,timeout=300)
            report['test_command']=command
            report['test_returncode']=proc.returncode
            report['test_stdout']=proc.stdout
            report['test_stderr']=proc.stderr
            if proc.returncode:raise RuntimeError('OFFLINE_TESTS_FAILED')
        report['status']='PASS_OFFLINE_PACKAGE_VERIFIED'
    except BaseException as exc:
        report['status']='FAIL'
        report['errors'].append(type(exc).__name__+':'+str(exc))
    report['elapsed_seconds']=round(time.monotonic()-started,3)
    text=json.dumps(report,indent=2,ensure_ascii=True,allow_nan=False)
    if args.json:
        out=args.json.resolve()
        if out==ROOT or ROOT in out.parents:
            raise RuntimeError('VERIFIER_OUTPUT_MUST_BE_OUTSIDE_IMMUTABLE_PACKAGE')
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(text,encoding='utf-8')
    print(text)
    return 0 if report['status'].startswith('PASS') else 1

if __name__=='__main__':raise SystemExit(main())
