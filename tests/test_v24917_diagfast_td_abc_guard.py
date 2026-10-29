"""Execute the live DIAGFAST state seal against COM-shaped read-only fixtures."""
import ast
import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def td_model(tmp_path, monkeypatch):
    from test_v24916_td09c_native16_compat import _prepare
    def create(scope='NATIVE16'):
        values = _prepare(tmp_path, monkeypatch, scope)
        ref, path, sha, visum, cfg, control, grav, mats, calls, outer = values
        parity = importlib.import_module('r1_15a2_diagfast_parity_v1')
        profile = parity.df.Profile('TD_ABC_REGRESSION', 'LEGACY')
        guarded = parity.df.ReadOnlyProxy(visum, profile, cfg.get('com_resilience', {}))
        return parity, visum, guarded, grav, mats, calls, cfg
    return create


@pytest.mark.parametrize('scope,expected', [('NATIVE16', 'NATIVE16_FOREIGN_SEPARATE'), ('FULL17', 'FULL17')])
def test_full_guard_reads_native16_and_frozen_foreign_without_writes(td_model, scope, expected):
    parity, v, guarded, grav, mats, calls, cfg = td_model(scope)
    before_params = {code: dict(g._attrs) for code, g in grav.items()}
    before_matrices = {no: mat.values.copy() for no, mat in mats.items()}
    before_ops = [dict(op._attrs) for op in v.Procedures.Operations.items]
    first = parity._read_full_td_abc_guard(guarded)
    assert first == parity._read_full_td_abc_guard(guarded)
    assert first['td_source_scope'] == expected
    assert len(first['td_full_abc_hash']) == len(first['td_foreign_abc_hash']) == 64
    assert {code: dict(g._attrs) for code, g in grav.items()} == before_params
    assert [dict(op._attrs) for op in v.Procedures.Operations.items] == before_ops
    for no, mat in mats.items(): np.testing.assert_array_equal(mat.values, before_matrices[no])
    assert calls == []


@pytest.mark.parametrize('code', ['1_WORK_E_C', '4_FOREIGN'])
@pytest.mark.parametrize('parameter', ['PARA_A', 'PARA_B', 'PARA_C'])
def test_guard_detects_changes_to_each_native_and_foreign_parameter(td_model, code, parameter):
    parity, v, guarded, grav, mats, calls, cfg = td_model()
    before = parity._read_full_td_abc_guard(guarded)
    # Change only the fixture, never the guarded production API.
    grav[code].SetAttValue(parameter, grav[code].AttValue(parameter) + .125)
    after = parity._read_full_td_abc_guard(guarded)
    assert before['td_full_abc_hash'] != after['td_full_abc_hash']
    assert (before['td_foreign_abc_hash'] != after['td_foreign_abc_hash']) == (code == '4_FOREIGN')
    assert not calls


def test_unreadable_frozen_foreign_cannot_be_sealed(td_model):
    from r1_15a2_supply import SupplyContractError
    parity, v, guarded, grav, mats, calls, cfg = td_model()
    grav['4_FOREIGN'].SetAttValue('PARA_A', float('nan'))
    with pytest.raises(SupplyContractError, match='FOREIGN_ABC_READONLY_PREFLIGHT_FAILED'):
        parity._read_full_td_abc_guard(guarded)
    assert not calls


def test_nonfinite_native_parameter_cannot_be_sealed(td_model):
    parity, v, guarded, grav, mats, calls, cfg = td_model()
    grav['1_WORK_E_C'].SetAttValue('PARA_B', float('nan'))
    with pytest.raises(parity.df.DiagFastError, match='ABC_READ_FAILED:1_WORK_E_C'):
        parity._read_full_td_abc_guard(guarded)
    assert not calls


def test_capture_state_reaches_full_td_guard(td_model, monkeypatch, tmp_path):
    parity, v, guarded, grav, mats, calls, cfg = td_model()
    supply = importlib.import_module('r1_15a2_supply_visum')
    monkeypatch.setattr(supply, 'VisumAdapter', lambda *a: SimpleNamespace(snapshot=lambda: {'state_hash':'same'}))
    v.IO = SimpleNamespace(CurrentVersionFile=str(tmp_path/'fixture.ver'))
    monkeypatch.setattr(parity.df, 'reference_namespace', lambda *a: {
        'OSRM_MATRIX_CODE':'DIST',
        'find_matrix_by_code':lambda visum, code: visum.Net.Matrices.ItemByKey(9697),
        'find_time_matrix':lambda visum:(None, None),
        'read_matrix_values':lambda mat:(mat.GetValues(), {}),
    })
    sealed = parity.capture_state(v, cfg)
    assert sealed['td_full_abc_hash'] == parity._read_full_td_abc_guard(guarded)['td_full_abc_hash']
    assert sealed['td_source_scope'] == 'NATIVE16_FOREIGN_SEPARATE'
    assert sealed['state_hash'] == 'same'
    assert len(sealed['classification_hash']) == 64
    assert not calls


def project_import_audit():
    """Resolve project imports recursively, including imports inside functions."""
    manifest = json.loads((ROOT/'V24917_RUNTIME_MANIFEST.json').read_text())
    pending = [p for p in manifest['required_files'] if p.endswith('.py')]
    visited, edges, missing = set(), [], []
    while pending:
        path = pending.pop()
        if path in visited: continue
        visited.add(path)
        tree = ast.parse((ROOT/path).read_text('utf-8-sig'), filename=path)
        compile(tree, path, 'exec')
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for name in names:
                if not name.startswith(('r1_15a2_', 'R1_15A2_')): continue
                target = name.replace('.', '/') + '.py'
                edge = {'source':path, 'line':node.lineno, 'module':name, 'target':target}
                edges.append(edge)
                if not (ROOT/target).is_file(): missing.append(edge)
                elif target not in visited: pending.append(target)
    return {'files':len(visited), 'project_imports':len(edges), 'missing':missing}


def test_runtime_and_deferred_project_imports_resolve():
    assert project_import_audit()['missing'] == []
