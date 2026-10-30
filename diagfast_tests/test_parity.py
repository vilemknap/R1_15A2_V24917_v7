import json
import zipfile
from pathlib import Path
import pytest
from r1_15a2_diagfast_parity_v1 import compare_artifacts,parity_helper
import r1_15a2_diagfast_v1 as df
from fakes import make12


def test_artifact_diff_detects_tiny_numeric_and_order(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir()
    (a/'values.csv').write_text('key;value\nx;1.0000000000000002\ny;2\n')
    (b/'values.csv').write_text('key;value\nx;1.0000000000000000\ny;2\n')
    r=compare_artifacts(a,b,'OFFLINE_MOCK')
    assert r['status']=='PARITY_PASS'
    assert r['tolerated_value_count']==1
    assert r['equal_artifacts']==1 and r['byte_equal_artifacts']==0
    assert compare_artifacts(a,b,numeric_tolerance=False)['status']=='PARITY_FAILED' 
    (b/'values.csv').write_bytes((a/'values.csv').read_bytes())
    assert compare_artifacts(a,b)['status']=='PARITY_PASS'
    (b/'values.csv').write_text('key;value\ny;2\nx;1.0000000000000002\n')
    assert compare_artifacts(a,b)['status']=='PARITY_FAILED'


def test_path_timestamp_normalization_not_numbers(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir()
    for p,stamp in ((a,'today'),(b,'tomorrow')):
        (p/'summary.json').write_text(json.dumps({'timestamp':stamp,'path':str(p/'x'),'observed':123.456789}))
    assert compare_artifacts(a,b)['status']=='PARITY_PASS'
    (b/'summary.json').write_text(json.dumps({'timestamp':'later','path':str(b/'x'),'observed':124.000000}))
    assert compare_artifacts(a,b)['status']=='PARITY_FAILED'


def test_zip_payload_and_schema_missing_not_ignored(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir()
    for p,num in ((a,1),(b,2)):
        with zipfile.ZipFile(p/'evidence.zip','w') as z:z.writestr('data.json',json.dumps({'GEH':num}))
    r=compare_artifacts(a,b);assert r['status']=='PARITY_FAILED'
    assert r['failures']==['evidence.zip!/data.json']


def test_parity_helper_complete_12d_and_readonly_guard(tmp_path):
    workspace=tmp_path/'w';v,_,_,_=make12(workspace,extra=50)
    token=df.CONTEXT.set({'backend':'PARITY_AUDIT','seal':lambda:{'state':'same'},'parity_scope':'OFFLINE_MOCK'})
    try:r=parity_helper('12D',workspace,v)
    finally:df.CONTEXT.reset(token)
    assert r['status']=='PARITY_PASS' and r['state_unchanged']
    assert r['artifact_count']>=40
    assert (workspace/'DIAGFAST_12D_LEGACY_REFERENCE.zip').is_file()


def test_parity_helper_rejects_external_mutation(tmp_path):
    workspace=tmp_path/'w';v,_,_,_=make12(workspace,extra=1)
    n=[0]
    def seal():n[0]+=1;return n[0]
    token=df.CONTEXT.set({'backend':'PARITY_AUDIT','seal':seal,'parity_scope':'OFFLINE_MOCK'})
    try:
        with pytest.raises(df.DiagFastError,match='PARITY_FAILED'):parity_helper('12D',workspace,v)
    finally:df.CONTEXT.reset(token)
