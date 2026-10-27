# -*- coding: utf-8 -*-
"""Independent verifier for R1 15A2 V2.4.8.2 CP12."""
from __future__ import annotations
import argparse, compileall, hashlib, importlib.util, json, os, subprocess, sys, time
from pathlib import Path
RELEASE='R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016'

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def atomic_json(path,value):
    path=Path(path); tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(tmp,path)

def verify(root,run_tests=False):
    root=Path(root).resolve(); started=time.monotonic(); errors=[]
    mp=root/'MANIFEST_V2482.json'
    if not mp.is_file(): return {'status':'FAILED','errors':['MANIFEST_V2482.json missing']}
    m=json.loads(mp.read_text(encoding='utf-8'))
    if m.get('release')!=RELEASE: errors.append('MANIFEST_RELEASE_IDENTITY')
    for row in m.get('files',[]):
        p=root/row['path']
        if not p.is_file(): errors.append('MISSING:'+row['path']); continue
        if p.stat().st_size!=int(row['bytes']): errors.append('SIZE:'+row['path']); continue
        if sha256(p)!=row['sha256']: errors.append('SHA256:'+row['path'])
    config_result=launcher_result=None
    try:
        sys.path.insert(0,str(root))
        from r1_15a2_safety_v2482 import validate_v2482_config
        spec=importlib.util.spec_from_file_location('verify_v2482_launcher',root/'R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_2.py')
        mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        cfg=mod.load_config(); config_result=validate_v2482_config(cfg,root)
        if cfg.get('release')!=RELEASE or mod.RELEASE!=RELEASE: errors.append('LAUNCHER_RELEASE_MISMATCH')
        pol=cfg.get('two_mode',{}).get('zero_share_residual_policy',{})
        if pol.get('enabled') is not True or float(pol.get('max_dseg_relative_volume',-1))!=0.01:
            errors.append('ZERO_SHARE_POLICY_NOT_LOCKED')
        launcher_result={'release':mod.RELEASE,'implementation_hash':cfg.get('implementation_hash'),'policy':pol}
    except Exception as exc:
        errors.append('CONFIG_OR_LAUNCHER:%s:%s'%(type(exc).__name__,exc))
    pycache=Path(os.environ.get('PYTHONPYCACHEPREFIX',root/'.verify_pycache'))
    old_env=os.environ.get('PYTHONPYCACHEPREFIX'); old_prefix=sys.pycache_prefix
    os.environ['PYTHONPYCACHEPREFIX']=str(pycache); sys.pycache_prefix=str(pycache)
    try: compile_pass=compileall.compile_dir(str(root),quiet=1,force=True)
    finally:
        sys.pycache_prefix=old_prefix
        if old_env is None: os.environ.pop('PYTHONPYCACHEPREFIX',None)
        else: os.environ['PYTHONPYCACHEPREFIX']=old_env
    if not compile_pass: errors.append('COMPILEALL_FAILED')
    test_result=None
    if run_tests:
        proc=subprocess.run([sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','tests'],cwd=str(root),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=dict(os.environ,PYTHONPYCACHEPREFIX=str(pycache)))
        test_result={'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr}
        if proc.returncode: errors.append('PYTEST_FAILED')
    return {'schema':'R1_15A2_V2482_PACKAGE_VERIFICATION_V1','status':'PASS' if not errors else 'FAILED','release':RELEASE,'root':str(root),'manifest_sha256':sha256(mp),'file_count':len(m.get('files',[])),'errors':errors,'config_validation':config_result,'launcher':launcher_result,'compileall_pass':compile_pass,'tests':test_result,'real_visum_tested':False,'production_ready':False,'elapsed_seconds':round(time.monotonic()-started,3)}

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default=str(Path(__file__).resolve().parent)); ap.add_argument('--run-tests',action='store_true'); ap.add_argument('--out',default='V2482_VERIFICATION_RESULT.json')
    a=ap.parse_args(); r=verify(a.root,a.run_tests); out=Path(a.out); out=out if out.is_absolute() else Path(a.root)/out; atomic_json(out,r); print(json.dumps(r,indent=2,ensure_ascii=False)); raise SystemExit(0 if r['status']=='PASS' else 1)
