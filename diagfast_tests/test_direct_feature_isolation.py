# -*- coding: utf-8 -*-
"""Bounded-float inline DIAGFAST parity and per-helper fallback.

Material differences require reduced-feature parity or LEGACY; tiny finite
floating-point differences must not disable a validated FAST helper.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from r1_15a2_diagfast_direct_v2 import DirectGuard, _with_backend


def _fake(kind, fast_problem, calls):
    def helper(visum, out_dir, label, *args, **kwargs):
        cfg = kwargs.get('cfg') or (args[1] if kind == '11D' and len(args)>1
                                      else args[0] if args else {})
        mode = cfg.get('diagnostics_backend')
        features = dict(cfg.get('diagfast_v2') or {})
        calls.append((kind, mode, features, str(out_dir)))
        value = fast_problem(features) if mode == 'FAST_EXACT' else 1.0
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'values.csv').write_text('value\n%s\n' % value, encoding='utf-8')
        (out / 'summary.json').write_text(json.dumps({'science': value}), encoding='utf-8')
        return {'backend': mode, 'value': value, 'features': features}
    return helper


def _make_guard(tmp_path, bad11, bad12=None):
    calls = []
    rt = SimpleNamespace(
        run_11d=_fake('11D', bad11, calls),
        run_12d=_fake('12D', bad12 or (lambda _: 1.0), calls),
    )
    guard = DirectGuard(rt, inline_parity=1, log_dir=tmp_path,
                        print_fn=lambda *x: None).install()
    return rt, guard, calls


def test_numpy_11d_false_only_after_full_strict_reaudit(tmp_path):
    rt, guard, calls = _make_guard(tmp_path,
        lambda f: 1.0 if f.get('numpy_11d') is False else 1.02)
    x = rt.run_11d(None, tmp_path/'REAL', 'A0001', cfg={})
    assert x['value'] == 1.0 and x['backend'] == 'FAST_EXACT'
    assert x['features'] == {'numpy_11d': False}
    assert guard.feature_limits['11D'] == {'numpy_11d': False}
    assert guard.helper_mode == {'11D':'FAST_EXACT','12D':'FAST_EXACT'}
    assert guard.mode == 'FAST_EXACT'
    assert guard.counts['strict_feature_retry_passes'] == 1
    assert guard.counts['parity_pass'] == 1
    reports = [json.loads(p.read_text()) for p in tmp_path.glob('DIRECT_PARITY_*.json')]
    assert len(reports) == 2
    assert {r['status'] for r in reports} == {'PARITY_PASS','PARITY_FAILED'}
    assert [r['feature_limits'] for r in reports if r['status']=='PARITY_PASS'] == [{'numpy_11d':False}]
    bad = next(r for r in reports if r['status']=='PARITY_FAILED')
    assert bad['failures']==['summary.json','values.csv']
    # Further calls use the *certified* features, without rerunning the parity.
    before=len(calls)
    y=rt.run_11d(None,tmp_path/'REAL2','A0001',cfg={'diagfast_v2':{'bulk_11d_matrices':False}})
    assert len(calls)==before+1
    assert y['backend']=='FAST_EXACT' and y['value']==1.0
    assert y['features']=={'numpy_11d':False,'bulk_11d_matrices':False}


def test_unrepairable_11d_mismatch_falls_back_for_11d_only(tmp_path):
    rt,guard,calls=_make_guard(tmp_path,lambda f:1.02)
    result=rt.run_11d(None,tmp_path/'REAL','C1',cfg={})
    assert result['backend']=='LEGACY' and result['value']==1.0
    assert guard.helper_mode=={'12D':'FAST_EXACT','11D':'LEGACY'}
    assert guard.mode=='MIXED'
    assert guard.counts['fallbacks']==1
    assert guard.counts['strict_feature_retry_passes']==0
    x=rt.run_12d(None,tmp_path/'REAL12','C1',cfg={})
    assert x['backend']=='FAST_EXACT'
    assert guard.helper_mode['12D']=='FAST_EXACT'
    before=len(calls)
    x=rt.run_11d(None,tmp_path/'REAL3','C1',cfg={})
    assert x['backend']=='LEGACY' and len(calls)==before+1
    # Every attempted STRICT parity certificate was actually rejected.
    reports=[json.loads(p.read_text()) for p in tmp_path.glob('DIRECT_PARITY_*11D*.json')]
    assert len(reports)==4 and all(r['status']=='PARITY_FAILED' for r in reports)
    assert all(r['failures'] for r in reports)


def test_12d_bulk_disable_can_certify_without_switching_11d(tmp_path):
    rt,guard,calls=_make_guard(tmp_path,lambda f:1.0,
        lambda f:1.0 if f.get('bulk_12d_links') is False else 2.0)
    x=rt.run_12d(None,tmp_path/'REAL12','C1',cfg={})
    assert x['features']=={'bulk_12d_links':False}
    assert guard.feature_limits['12D']=={'bulk_12d_links':False}
    assert guard.helper_mode['11D']=='FAST_EXACT'
    assert guard.counts['fallbacks']==0


def test_source_configuration_not_mutated_by_retry(tmp_path):
    rt,guard,calls=_make_guard(tmp_path,
        lambda f:1.0 if f.get('numpy_11d') is False else 2.0)
    cfg={'diagnostics_backend':'LEGACY','diagfast_v2':{'bulk_11d_matrices':False},'science':'untouched'}
    rt.run_11d(None,tmp_path/'REAL','C1',cfg=cfg)
    assert cfg=={'diagnostics_backend':'LEGACY','diagfast_v2':{'bulk_11d_matrices':False},'science':'untouched'}
    assert guard.helper_mode['11D']=='FAST_EXACT'


def test_parity_pass_then_fast_runtime_failure_only_downgrades_helper(tmp_path):
    rt,guard,calls=_make_guard(tmp_path,lambda f:1.0)
    original=rt.run_11d.__wrapped__
    n=[0]
    def first_fast_real_call_fault(*a,**k):
        cfg=k.get('cfg',{})
        if cfg.get('diagnostics_backend')=='FAST_EXACT':
            n[0]+=1
            if n[0]==2: raise RuntimeError('FAST_RUNTIME_FAILURE_AFTER_PARITY')
        return original(*a,**k)
    guard.originals['11D']=first_fast_real_call_fault
    rt.run_11d=guard.wrap('11D')
    result=rt.run_11d(None,tmp_path/'REAL','C1',cfg={})
    assert result['backend']=='LEGACY'
    assert guard.helper_mode['11D']=='LEGACY'
    assert guard.helper_mode['12D']=='FAST_EXACT'
    assert guard.mode=='MIXED'


def test_feature_retry_cannot_turn_on_existing_disabled_feature():
    a,k = _with_backend('11D',[],{'cfg':{'science':4,'diagfast_v2':{'numpy_11d':False}}},
                        'FAST_EXACT',{'bulk_11d_countlocations':False})
    assert k['cfg']['diagfast_v2']=={'numpy_11d':False,'bulk_11d_countlocations':False}
    with pytest.raises(Exception,match='RETRY_MUST_ONLY_DISABLE'):
        _with_backend('11D',[],{},'FAST_EXACT',{'numpy_11d':True})


def test_one_ulp_csv_and_json_difference_is_audited_but_fast_kept(tmp_path):
    rt, guard, calls = _make_guard(tmp_path, lambda f: 1.0000000000000002)
    result = rt.run_11d(None, tmp_path/'REAL', 'C1', cfg={})
    assert result['backend'] == 'FAST_EXACT'
    assert guard.helper_mode['11D'] == 'FAST_EXACT'
    assert guard.mode == 'FAST_EXACT'
    assert guard.counts['strict_feature_retry_attempts'] == 0
    assert guard.counts['fallbacks'] == 0
    reports = [json.loads(p.read_text()) for p in tmp_path.glob('DIRECT_PARITY_*11D*.json')]
    assert len(reports) == 1
    r = reports[0]
    assert r['status'] == 'PARITY_PASS'
    assert r['byte_equal_artifacts'] == 0
    assert r['equal_artifacts'] == 2
    assert r['tolerated_artifacts'] == 2
    assert r['tolerated_value_count'] == 2
    assert r['numeric_tolerance']['absolute'] == 1e-3
    assert guard.certificate()['numeric_parity_relaxed'] is True
