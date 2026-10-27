# -*- coding: utf-8 -*-
"""Independent verifier for R1 15A2 V2.4.8 persistent path-cache delivery."""
from __future__ import annotations
import argparse, compileall, hashlib, importlib.util, json, os, subprocess, sys, time
from pathlib import Path

RELEASE="R1_15A2_V2_4_8_PERSISTENT_PATH_CACHE_20261016"


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def atomic_json(path,value):
    path=Path(path); tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(tmp,path)


def verify(root,run_tests=False):
    root=Path(root).resolve(); started=time.monotonic(); errors=[]
    manifest_path=root/'MANIFEST_V248.json'
    if not manifest_path.is_file():
        return {'status':'FAILED','errors':['MANIFEST_V248.json missing']}
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('release')!=RELEASE:
        errors.append('MANIFEST_RELEASE_IDENTITY')
    for row in manifest.get('files',[]):
        path=root/row['path']
        if not path.is_file(): errors.append('MISSING:'+row['path']); continue
        if path.stat().st_size!=int(row['bytes']): errors.append('SIZE:'+row['path']); continue
        if sha256(path)!=row['sha256']: errors.append('SHA256:'+row['path'])
    config_result=launcher_result=benchmark=None
    try:
        sys.path.insert(0,str(root))
        from r1_15a2_safety_v248 import validate_v248_config
        raw=json.loads((root/'R1_15A2_CONFIG_V2_4_8.json').read_text(encoding='utf-8'))
        # Static config validation needs implementation hashes; the launcher adds
        # the authoritative current hashes, so use its loaded config for the hard gate.
        spec=importlib.util.spec_from_file_location(
            'verify_v248_launcher',root/'R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        loaded=module.load_config()
        config_result=validate_v248_config(loaded,root)
        perf=loaded.get('performance',{})
        persistent=perf.get('persistent_path_cache',{})
        epochs=perf.get('path_epochs',{})
        if loaded.get('release')!=module.RELEASE: errors.append('LAUNCHER_RELEASE_MISMATCH')
        if persistent.get('enabled') is not True: errors.append('PERSISTENT_CACHE_DISABLED')
        if epochs.get('cross_run_reuse')!='EXACT_ORIGIN_STATE_OR_EXPLICIT_ACCEPTED_STATE_BINDING_ONLY':
            errors.append('CROSS_RUN_POLICY_CHANGED')
        launcher_result={'release':loaded.get('release'),
                         'implementation_hash':loaded.get('implementation_hash'),
                         'implementation_file_count':len(loaded.get('implementation_files',{})),
                         'persistent_cache_policy':persistent,
                         'path_epoch_policy':epochs.get('policy')}
    except Exception as exc:
        errors.append('CONFIG_OR_LAUNCHER:%s:%s'%(type(exc).__name__,exc))
    try:
        benchmark=json.loads((root/'V248_PERSISTENT_CACHE_SYNTHETIC_BENCHMARK.json').read_text(encoding='utf-8'))
        if benchmark.get('status')!='PASS' or benchmark.get('enumeration_calls_total')!=1 or benchmark.get('restart_enumeration_calls')!=0:
            errors.append('PERSISTENT_CACHE_BENCHMARK_FAILED')
    except Exception as exc:
        errors.append('BENCHMARK:%s:%s'%(type(exc).__name__,exc))
    pycache=Path(os.environ.get('PYTHONPYCACHEPREFIX',root/'.verify_pycache'))
    old_env=os.environ.get('PYTHONPYCACHEPREFIX')
    old_prefix=sys.pycache_prefix
    os.environ['PYTHONPYCACHEPREFIX']=str(pycache)
    sys.pycache_prefix=str(pycache)
    try:
        compile_pass=compileall.compile_dir(str(root),quiet=1,force=True)
    finally:
        sys.pycache_prefix=old_prefix
        if old_env is None: os.environ.pop('PYTHONPYCACHEPREFIX',None)
        else: os.environ['PYTHONPYCACHEPREFIX']=old_env
    if not compile_pass: errors.append('COMPILEALL_FAILED')
    test_result=None
    if run_tests:
        proc=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','tests'],
            cwd=str(root),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=dict(os.environ,PYTHONPYCACHEPREFIX=str(pycache)))
        test_result={'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr}
        if proc.returncode: errors.append('PYTEST_FAILED')
    return {'schema':'R1_15A2_V248_PACKAGE_VERIFICATION_V1',
            'status':'PASS' if not errors else 'FAILED','release':RELEASE,
            'root':str(root),'manifest_sha256':sha256(manifest_path),
            'file_count':len(manifest.get('files',[])),'errors':errors,
            'config_validation':config_result,'launcher':launcher_result,
            'benchmark':benchmark,'compileall_pass':compile_pass,'tests':test_result,
            'real_visum_tested':False,'production_ready':False,
            'elapsed_seconds':round(time.monotonic()-started,3)}


if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default=str(Path(__file__).resolve().parent))
    ap.add_argument('--run-tests',action='store_true'); ap.add_argument('--out',default='V248_VERIFICATION_RESULT.json')
    args=ap.parse_args(); result=verify(args.root,args.run_tests)
    out=Path(args.out); out=out if out.is_absolute() else Path(args.root)/out
    atomic_json(out,result); print(json.dumps(result,indent=2,ensure_ascii=False))
    raise SystemExit(0 if result['status']=='PASS' else 1)
