from pathlib import Path
import json
import r1_15a2_runtime_io_hotfix_profile488 as io

def test_replace_retries_transient_lock(tmp_path, monkeypatch):
    src=tmp_path/'a.tmp'; dst=tmp_path/'a.json'; src.write_text('x')
    real=io._REAL_REPLACE; calls={'n':0}
    def flaky(a,b):
        calls['n']+=1
        if calls['n']<4: raise PermissionError(13,'locked')
        return real(a,b)
    monkeypatch.setattr(io,'_REAL_REPLACE',flaky)
    monkeypatch.setattr(io.time,'sleep',lambda *_: None)
    io.replace_with_retry(src,dst,attempts=6)
    assert dst.read_text()=='x' and calls['n']==4

def test_critical_json_retry_and_readback(tmp_path, monkeypatch):
    real=io._REAL_REPLACE; calls={'n':0}
    def flaky(a,b):
        calls['n']+=1
        if calls['n']==1: raise PermissionError(13,'locked')
        return real(a,b)
    monkeypatch.setattr(io,'_REAL_REPLACE',flaky)
    monkeypatch.setattr(io.time,'sleep',lambda *_: None)
    p=tmp_path/'RUN_STATUS.json'; io.critical_atomic_json(p,{'ok':True})
    assert json.loads(p.read_text())=={'ok':True}

def test_critical_json_fails_closed_after_exhaustion(tmp_path, monkeypatch):
    p=tmp_path/'LATEST.json'; p.write_text('{"old":1}')
    monkeypatch.setattr(io,'_REAL_REPLACE',lambda a,b: (_ for _ in ()).throw(PermissionError(13,'locked')))
    monkeypatch.setattr(io.time,'sleep',lambda *_: None)
    try: io.critical_atomic_json(p,{'new':2})
    except PermissionError: pass
    else: raise AssertionError('must fail closed')
    assert json.loads(p.read_text())=={'old':1}

def test_activate_patches_critical_scopes():
    st=io.activate()
    import r1_15a2_controller_v22 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as txn
    import r1_15a2_two_mode_v238 as two
    import r1_15a2_persistent_path_cache_v248 as pc
    assert ctrl.atomic_json is io.critical_atomic_json
    assert txn.atomic_json is io.critical_atomic_json
    assert two.atomic_json is io.critical_atomic_json
    assert pc.atomic_json is io.critical_atomic_json
    assert st['status']=='ACTIVE'
