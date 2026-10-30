# -*- coding: utf-8 -*-
"""Scientific parity: finite roundoff tolerated, identity/decisions exact."""
import json
import math
import zipfile
from pathlib import Path

import pytest

from r1_15a2_diagfast_parity_v1 import compare_artifacts, DEFAULT_NUMERIC_ATOL, DEFAULT_NUMERIC_RTOL


def pair(tmp_path, filename, legacy, fast):
    a, b = tmp_path / 'LEGACY', tmp_path / 'FAST'
    a.mkdir(exist_ok=True)
    b.mkdir(exist_ok=True)
    (a / filename).write_text(legacy, encoding='utf-8')
    (b / filename).write_text(fast, encoding='utf-8')
    return compare_artifacts(a, b)


def test_json_decimal_roundoff_passes_with_audit_trail(tmp_path):
    a = json.dumps({'profile':'W_E_C', 'geh':20.123456789, 'share':0.234567891,
                    'matrix_no':9111, 'is_accepted':False})
    b = json.dumps({'profile':'W_E_C', 'geh':20.123456788, 'share':0.2345678911,
                    'matrix_no':9111, 'is_accepted':False})
    r = pair(tmp_path, 'summary.json', a, b)
    assert r['status'] == 'PARITY_PASS'
    assert r['tolerated_value_count'] == 2
    assert r['byte_equal_artifacts'] == 0
    assert r['equal_artifacts'] == 1
    assert r['artifacts'][0]['numeric_tolerance_accepted'] is True
    assert r['max_tolerated_abs_difference'] < 1e-8
    assert len(r['artifacts'][0]['tolerated_examples']) == 2
    assert r['numeric_rounding_used'] is False
    assert r['numeric_tolerance']['absolute'] == DEFAULT_NUMERIC_ATOL
    assert r['numeric_tolerance']['relative'] == DEFAULT_NUMERIC_RTOL


def test_large_volumes_use_relative_tolerance_but_not_unbounded(tmp_path):
    base = 'id;volume\na;1000000.000000\n'
    within = 'id;volume\na;1000000.000500\n'
    r = pair(tmp_path, 'flow.csv', base, within)
    assert r['status'] == 'PARITY_PASS'
    far = 'id;volume\na;1000000.002000\n'
    r = pair(tmp_path, 'flow.csv', base, far)
    assert r['status'] == 'PARITY_FAILED'
    assert r['failures'] == ['flow.csv']


@pytest.mark.parametrize('a,b', [
    ('0.0', '0.000000000001'),     # zero -> nonzero changes structural support
    ('0.000000000001', '0.0'),
    ('-0.00000000001', '+0.00000000001'), # sign flips can change guards
    ('0.0000000001', '0.0000000002'),     # huge relative near-zero drift
])
def test_support_sign_small_relative_drift_always_fail(tmp_path, a, b):
    r = pair(tmp_path, 'rows.csv', 'metric;volume\na;'+a+'\n',
             'metric;volume\na;'+b+'\n')
    assert r['status'] == 'PARITY_FAILED'


def test_integers_boolean_and_identifiers_are_exact(tmp_path):
    left = {'matrix_no':9111.0, 'num_zones':681,
            'counts':{'negative_cells':1, 'zones':681},
            'status':'PASS', 'verified': True, 'geh':12.25}
    for mutate in [
        {'matrix_no':9111.0000000001},
        {'num_zones':680},
        {'counts':{'negative_cells':2, 'zones':681}},
        {'status':'FAIL'},
        {'verified': False},
        {'geh':12.251},
    ]:
        right = dict(left, **mutate)
        r = pair(tmp_path, 'ids.json', json.dumps(left), json.dumps(right))
        assert r['status'] == 'PARITY_FAILED', mutate
    assert pair(tmp_path, 'ids.json', json.dumps(left), json.dumps(left))['status']=='PARITY_PASS'


def test_csv_decimal_looking_identifier_and_missing_columns_fail(tmp_path):
    left = 'matrix_no;model\n9111.000000;123.456789000\n'
    right = 'matrix_no;model\n9111.0000000001;123.456789001\n'
    assert pair(tmp_path, 'm.csv', left, right)['status'] == 'PARITY_FAILED'
    right = 'matrix_no;other_model\n9111.000000;123.456789000\n'
    assert pair(tmp_path, 'm.csv', left, right)['status'] == 'PARITY_FAILED'
    right = 'matrix_no;model\n9111.000000;123.456789000\n9112.000000;0.0\n'
    assert pair(tmp_path, 'm.csv', left, right)['status'] == 'PARITY_FAILED'


def test_exact_binary_text_hash_and_json_type_difference_fail(tmp_path):
    assert pair(tmp_path, 'summary.txt', 'GEH=20.0000000000', 'GEH=20.0000000001')['status']=='PARITY_FAILED'
    assert pair(tmp_path, 'summary.json', '{"sha256":"abcde100"}',
                '{"sha256":"abcde101"}')['status']=='PARITY_FAILED'
    # A change of representation from float to int can indicate a schema drift.
    assert pair(tmp_path, 'summary.json', '{"measure":1.0}', '{"measure":1}')['status']=='PARITY_FAILED'
    assert pair(tmp_path, 'summary.json', '{"state_hash":1.000000}',
                '{"state_hash":1.0000000001}')['status']=='PARITY_FAILED'


def test_zip_recursion_applies_tolerance_only_to_numeric_payload(tmp_path):
    a,b=tmp_path/'L',tmp_path/'F'
    a.mkdir();b.mkdir()
    for folder, num in [(a,1.000000000000001),(b,1.0)]:
        with zipfile.ZipFile(folder/'nested.zip','w') as z:
            z.writestr('science.json',json.dumps({'GEH':num}))
            z.writestr('manifest.txt','MODEL=X')
    r=compare_artifacts(a,b)
    assert r['status']=='PARITY_PASS'
    assert r['tolerated_artifacts']==1
    with zipfile.ZipFile(b/'nested.zip','w') as z:
        z.writestr('science.json',json.dumps({'GEH':1.0}))
        z.writestr('manifest.txt','MODEL=Y')
    r=compare_artifacts(a,b)
    assert r['status']=='PARITY_FAILED'
    assert r['failures']==['nested.zip!/manifest.txt']


def test_nonfinite_and_missing_files_fail_but_identical_nan_is_preserved(tmp_path):
    r=pair(tmp_path,'science.json', '{"GEH":NaN, "share":Infinity}',
           '{"GEH":NaN, "share":Infinity}')
    assert r['status']=='PARITY_PASS'
    r=pair(tmp_path,'science.json', '{"GEH":NaN, "share":Infinity}',
           '{"GEH":0.0, "share":Infinity}')
    assert r['status']=='PARITY_FAILED'
    # compare map union: presence/absence never tolerated
    (tmp_path/'FAST'/'science.json').unlink()
    r=compare_artifacts(tmp_path/'LEGACY',tmp_path/'FAST')
    assert r['status']=='PARITY_FAILED'


def test_tolerance_can_be_explicitly_switched_off_for_forensics(tmp_path):
    left = '{"geh":1.0000000000000002}'
    right = '{"geh":1.0}'
    r = pair(tmp_path,'science.json',left,right)
    assert r['status']=='PARITY_PASS'
    strict=compare_artifacts(tmp_path/'LEGACY', tmp_path/'FAST',numeric_tolerance=False)
    assert strict['status']=='PARITY_FAILED'
    assert strict['exact_values_required'] is True


@pytest.mark.parametrize('atol,rtol', [(-1,1e-9), (1e-8,-1), (float('nan'),1e-9)])
def test_invalid_tolerances_are_never_accepted(tmp_path,atol,rtol):
    a,b=tmp_path/'L',tmp_path/'F'
    a.mkdir();b.mkdir()
    with pytest.raises(Exception,match='DIAGFAST_PARITY_INVALID_NUMERIC_TOLERANCE'):
        compare_artifacts(a,b,numeric_atol=atol,numeric_rtol=rtol)
