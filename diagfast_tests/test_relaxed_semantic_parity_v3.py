# -*- coding: utf-8 -*-
"""New looser 0.1% DIAGFAST semantic parity with audited derivative SHA drift."""
import json
from pathlib import Path
import pytest
from r1_15a2_diagfast_parity_v1 import compare_artifacts
from r1_15a2_diagfast_direct_v2 import DirectGuard
from types import SimpleNamespace


def compare(tmp_path, left, right, filename='metrics.json', **kwargs):
    a,b=tmp_path/'L',tmp_path/'F'
    a.mkdir(exist_ok=True);b.mkdir(exist_ok=True)
    (a/filename).write_text(left,encoding='utf8')
    (b/filename).write_text(right,encoding='utf8')
    return compare_artifacts(a,b,**kwargs)


@pytest.mark.parametrize('reference,observed,passed', [
    (20.0, 20.019, True),      # GEH delta 0.019 / 0.1% envelope
    (20.0, 20.05, False),      # 0.25% is material
    (0.2345, 0.2341, True),    # abs 0.0004 is small
    (0.2345, 0.2325, False),   # abs 0.002 crosses tolerance
    (1e6, 1000500.0, True),   # 0.05% count-like FLOAT
    (1e6, 1002000.0, False),  # 0.2% materially different
    (0.0, 0.0000005, True),   # tiny floating zero noise
    (-0.0000004, 0.0000004, True),
    (0.0, 0.00005, False),    # real support difference
    (-0.01, 0.01, False),     # nontrivial sign change
])
def test_relaxed_diagnostic_floats(tmp_path,reference,observed,passed):
    r=compare(tmp_path,json.dumps({'GEH':reference}),json.dumps({'GEH':observed}))
    assert (r['status']=='PARITY_PASS') is passed
    if passed and reference!=observed:
        assert r['tolerated_value_count']==1


def test_derived_report_digest_only_ignored_when_numeric_payload_verified(tmp_path):
    a='a'*64;b='b'*64
    left={'GEH':20.0,'profile':'A','output_sha256':a}
    right={'GEH':20.019,'profile':'A','output_sha256':b}
    report=compare(tmp_path,json.dumps(left),json.dumps(right))
    assert report['status']=='PARITY_PASS'
    assert report['tolerated_derived_digest_count']==1
    assert report['tolerated_value_count']==1
    assert report['byte_equal_artifacts']==0
    item=report['artifacts'][0]
    assert item['tolerated_derived_digests'][0]['path']=='$.output_sha256'
    assert item['legacy_sha256']!=item['fast_sha256']
    assert report['numeric_tolerance']['source_model_and_cache_digests_exact']
    assert compare_artifacts(tmp_path/'L',tmp_path/'F', numeric_tolerance=False)['status']=='PARITY_FAILED'


@pytest.mark.parametrize('field', [
    'sha256','matrix_hash','path_basis_hash','source_ver_sha256',
    'checkpoint_sha256','state_hash','source_sha256','input_sha256',
    'TWO_MODE_PATH_STORE_sha256','authority_sha256'
])
def test_scientific_and_source_integrity_hashes_never_relaxed(tmp_path,field):
    left=json.dumps({'GEH':20.0,field:'a'*64})
    right=json.dumps({'GEH':20.0005,field:'b'*64})
    r=compare(tmp_path,left,right)
    assert r['status']=='PARITY_FAILED'
    assert r['failures']==['metrics.json']


@pytest.mark.parametrize('left,right',[
    ({'output_sha256':'a'*64},{'output_sha256':'b'*64}),
    ({'status':'PASS','output_sha256':'a'*64},{'status':'PASS','output_sha256':'b'*64}),
    ({'GEH':20.0,'output_sha256':'a'*64},
     {'GEH':21.0,'output_sha256':'b'*64}),
    ({'GEH':20.0,'output_sha256':'a'*64,'valid':True},
     {'GEH':20.0001,'output_sha256':'b'*64,'valid':False}),
])
def test_derived_digest_cannot_hide_missing_evidence_or_scientific_drift(tmp_path,left,right):
    assert compare(tmp_path,json.dumps(left),json.dumps(right))['status']=='PARITY_FAILED'


def test_csv_derived_digest_only_passes_with_numeric_science_column(tmp_path):
    a='0'*64;b='f'*64
    r=compare(tmp_path,'id;GEH;output_sha256\nA;20.0;'+a+'\n',
              'id;GEH;output_sha256\nA;20.005;'+b+'\n',filename='flow.csv')
    assert r['status']=='PARITY_PASS'
    assert r['tolerated_derived_digest_count']==1
    assert r['tolerated_value_count']==1


def test_ids_integer_counts_schema_and_status_still_exact(tmp_path):
    left={'matrix_no':9111, 'num_zones':681,'profile_count':248,
          'status':'PASS','accepted':False,'GEH':20.0}
    for key,value in [('matrix_no',9112),('num_zones',680),('profile_count',247),
                      ('status','FAIL'),('accepted',True)]:
        right=dict(left,**{key:value})
        assert compare(tmp_path,json.dumps(left),json.dumps(right))['status']=='PARITY_FAILED'


def test_parity_guard_certifies_relaxed_threshold_without_disabling_fallback(tmp_path):
    calls=[]
    def helper(v, out, label, *args, **kwargs):
        cfg=kwargs.get('cfg',{})
        mode=cfg.get('diagnostics_backend')
        value=20.019 if mode=='FAST_EXACT' else 20.0
        Path(out).mkdir(parents=True,exist_ok=True)
        (Path(out)/'metrics.json').write_text(json.dumps({'GEH':value,'output_sha256':
                                             ('f' if mode=='FAST_EXACT' else 'a')*64}))
        calls.append(mode)
        return {'GEH':value}
    rt=SimpleNamespace(run_11d=helper,run_12d=helper)
    guard=DirectGuard(rt,inline_parity=1,log_dir=tmp_path,print_fn=lambda *_:None).install()
    r=rt.run_11d(None,tmp_path/'ACTUAL','cycle2',cfg={})
    assert r['GEH']==20.019
    assert guard.helper_mode['11D']=='FAST_EXACT'
    assert guard.counts['fallbacks']==0
    report=[json.loads(p.read_text()) for p in tmp_path.glob('DIRECT_PARITY_*.json')]
    assert len(report)==1
    assert report[0]['tolerated_derived_digest_count']==1
    assert guard.certificate()['source_authority_and_manifest_sha_exact'] is True


def test_text_cosmetic_hash_mismatch_without_scientific_change_is_ignored(tmp_path):
    a,b=tmp_path/'L',tmp_path/'F'
    a.mkdir();b.mkdir()
    (a/'summary.txt').write_bytes(b'GEH=20.1 \r\nCOUNT=248  \r\n')
    (b/'summary.txt').write_bytes(b'GEH=20.1\nCOUNT=248\n\n')
    r=compare_artifacts(a,b)
    assert r['status']=='PARITY_PASS'
    assert r['byte_equal_artifacts']==1  # canonical report hash, not raw bytes
    (b/'summary.txt').write_text('GEH=20.2\nCOUNT=248\n')
    assert compare_artifacts(a,b)['status']=='PARITY_FAILED'
