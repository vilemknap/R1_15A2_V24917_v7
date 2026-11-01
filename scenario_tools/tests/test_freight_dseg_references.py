import copy
import importlib.util
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'R1_2022_2025_CREATE_BIND_FREIGHT_DSEGS.py'
spec = importlib.util.spec_from_file_location('freight_refs_tested', SCRIPT)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


class Collection:
    def __init__(self, items):
        self.items = list(items)

    @property
    def GetAll(self):
        return list(self.items)


class Obj:
    def __init__(self, **attrs):
        self.attrs = attrs

    def AttValue(self, field):
        return self.attrs[field]

    def SetAttValue(self, field, value):
        self.attrs[field] = value


class Matrix(Obj):
    def __init__(self, no, code='', symbolic=False):
        super().__init__(NO=no, CODE=code, NAME='original name',
                         OBJECTTYPEREF='OBJECTTYPEREF_ZONE' if symbolic else 2,
                         MATRIXTYPE='MATRIXTYPE_DEMAND' if symbolic else 3,
                         DATASOURCETYPE='DataSourceTypeData' if symbolic else 1)

    def GetValues(self):
        raise AssertionError('Object creation must not read or copy OD values')

    def SetValues(self, *args):
        raise AssertionError('Object creation must not write OD values')


class DSeg(Obj):
    def __init__(self, code, mode, matrix=None):
        super().__init__(CODE=code, NAME='original ' + code)
        # Visum 2026 IDemandSegment has a Mode attribute/relation, but no
        # Python/COM .Mode property. Keep the mock on that actual interface.
        self._mode = mode
        self.matrix = matrix
        self.fail_get = False
        self.fail_set = False
        self.corrupt_set = False

    def AttValue(self, field):
        if field in (r'MODE\CODE', 'MODE'):
            return self._mode.AttValue('CODE')
        return super().AttValue(field)

    @property
    def ODMatrix(self):
        if self.fail_get:
            raise RuntimeError('ODMatrix getter unavailable')
        return self.matrix

    @ODMatrix.setter
    def ODMatrix(self, value):
        self.matrix = None if self.corrupt_set else value
        if self.fail_set:
            self.fail_set = False
            raise RuntimeError('binding changed then COM setter raised')


class Net:
    def __init__(self, symbolic=False):
        self.symbolic = symbolic
        l = Obj(CODE='L'); n = Obj(CODE='N')
        self.Modes = Collection([l, n])
        lnv = Matrix(7101, 'BASE_LNV'); nv = Matrix(7102, 'BASE_NV')
        self.Matrices = Collection([lnv, nv, Matrix(9896, 'R1_OA_CAL_2022_WORK')])
        self.DemandSegments = Collection([DSeg('LNV', l, lnv), DSeg('NV', n, nv)])
        self.Zones = SimpleNamespace(GetMultiAttValues=lambda *args: [(1000 + no, no) for no in range(681, 0, -1)])
        self.fail_add = None
        self.remove_fails = False
        self.calls = []

    def AddMatrix(self, no, obj, typ):
        assert (no, obj, typ) == (-1, 2, 3)
        mat = Matrix(max(m.attrs['NO'] for m in self.Matrices.items) + 1, symbolic=self.symbolic)
        self.Matrices.items.append(mat)
        self.calls.append(('AddMatrix', mat.attrs['NO']))
        if self.fail_add == 'matrix_after_create':
            raise RuntimeError('AddMatrix raised after creating an unreturned object')
        return mat

    def AddDemandSegment(self, code, mode):
        ds = DSeg(code, mode)
        self.DemandSegments.items.append(ds)
        self.calls.append(('AddDemandSegment', code))
        if self.fail_add == code:
            raise RuntimeError('DSeg added then COM raised')
        if self.fail_add == 'readback':
            ds.corrupt_set = True
        return ds

    def RemoveDemandSegment(self, ds):
        if self.remove_fails:
            raise RuntimeError('COM remove failed')
        self.DemandSegments.items.remove(ds)

    def RemoveMatrix(self, mat):
        if self.remove_fails:
            raise RuntimeError('COM remove failed')
        assert all(ds.matrix is not mat for ds in self.DemandSegments.items)
        self.Matrices.items.remove(mat)


def host(symbolic=False):
    return SimpleNamespace(Net=Net(symbolic))


def state(v):
    return {'matrices': sorted((m.attrs['NO'], copy.deepcopy(m.attrs)) for m in v.Net.Matrices.items),
            'dsegs': {ref.code(ds): ref.dseg_state(ds) for ds in v.Net.DemandSegments.items}}


@pytest.mark.parametrize('symbolic', [False, True])
def test_create_four_segments_and_independent_references_then_idempotent_rerun(tmp_path, symbolic):
    v = host(symbolic)
    before = state(v)
    result = ref.run(v, tmp_path / 'run1')
    assert result['status'] == 'PASS_CREATED_AND_VERIFIED'
    rows = result['plan']
    assert len({r['matrix_no'] for r in rows}) == 4
    assert {r['dseg'] for r in rows} == {'LNV_2022', 'NV_2022', 'LNV_2025', 'NV_2025'}
    dsegs = ref.index_by_code(v.Net.DemandSegments)
    for row in rows:
        ds = dsegs[row['dseg']]
        assert ref.code(ds.ODMatrix) == row['matrix_code']
        assert ref.mode_code(ds) == ('L' if row['kind'] == 'LNV' else 'N')
    assert all(ref.dseg_state(dsegs[key]) == old for key, old in before['dsegs'].items())
    assert all(next(m.attrs for m in v.Net.Matrices.items if m.attrs['NO'] == no) == attrs for no, attrs in before['matrices'])
    calls = list(v.Net.calls); complete = state(v)
    again = ref.run(v, tmp_path / 'run2')
    assert all(r['dseg_action'] == r['matrix_action'] == 'REUSE' for r in again['plan'])
    assert v.Net.calls == calls and state(v) == complete


def test_existing_loaded_matrices_are_reused_and_existing_empty_segment_is_bound(tmp_path):
    v = host(); mode = v.Net.Modes.items[0]
    mat = Matrix(12000, 'R1_LNV_2022_WORK', True)
    v.Net.Matrices.items.append(mat)
    ds = DSeg('LNV_2022', mode)
    v.Net.DemandSegments.items.append(ds)
    result = ref.run(v, tmp_path / 'run')
    assert ds.ODMatrix is mat and ds.AttValue('NAME') == 'original LNV_2022'
    assert mat.AttValue('NAME') == 'original name'
    assert result['plan'][0]['matrix_no'] == 12000
    assert result['plan'][0]['dseg_action'] == 'BIND_EMPTY'


@pytest.mark.parametrize('bad', ['source', 'mode', 'formula', 'duplicate', 'wrong_matrix', 'wrong_mode', 'getter', 'zones'])
def test_complete_preflight_blocks_all_writes_on_any_target_conflict(tmp_path, bad):
    v = host(); net = v.Net
    mat = Matrix(12000, 'R1_NV_2025_WORK', True)
    net.Matrices.items.append(mat)
    if bad == 'source':
        net.DemandSegments.items = net.DemandSegments.items[1:]
    elif bad == 'mode':
        net.Modes.items.pop()
    elif bad == 'formula':
        mat.attrs['DATASOURCETYPE'] = 'DataSourceTypeFormula'
    elif bad == 'duplicate':
        net.Matrices.items.append(Matrix(12001, mat.attrs['CODE']))
    elif bad in ('wrong_matrix', 'wrong_mode', 'getter'):
        ds = DSeg('NV_2025', net.Modes.items[0 if bad == 'wrong_mode' else 1],
                  net.Matrices.items[0] if bad == 'wrong_matrix' else None)
        ds.fail_get = bad == 'getter'
        net.DemandSegments.items.append(ds)
    else:
        net.Zones.GetMultiAttValues = lambda *args: [(n, n) for n in range(1, 681)]
    with pytest.raises((ref.ReferenceError, RuntimeError)):
        ref.run(v, tmp_path / 'run')
    assert not net.calls
    assert json.loads((tmp_path / 'run/00_STATUS.json').read_text())['status'] == 'FAILED_PREFLIGHT_NO_CHANGES'


def test_dry_run_and_missing_matrix_policy_do_not_change_model(tmp_path):
    v = host(); before = state(v)
    result = ref.run(v, tmp_path / 'dry', dry_run=True)
    assert result['status'] == 'DRY_RUN_PASS' and not v.Net.calls and state(v) == before
    with pytest.raises(ref.ReferenceError, match='TARGET_MATRIX_MISSING'):
        ref.run(v, tmp_path / 'strict', create_missing=False)
    assert not v.Net.calls and state(v) == before


@pytest.mark.parametrize('failure', ['NV_2022', 'NV_2025', 'readback', 'partial_bind'])
def test_partial_mutation_is_rolled_back_and_verified(tmp_path, failure):
    v = host()
    if failure == 'partial_bind':
        ds = DSeg('NV_2025', v.Net.Modes.items[1]); ds.fail_set = True
        v.Net.DemandSegments.items.append(ds)
    else:
        v.Net.fail_add = failure
    before = state(v)
    with pytest.raises((RuntimeError, ref.ReferenceError)):
        ref.run(v, tmp_path / 'run')
    assert state(v) == before
    assert json.loads((tmp_path / 'run/00_STATUS.json').read_text())['status'] == 'FAILED_ROLLBACK_VERIFIED'


@pytest.mark.parametrize('failure', ['remove', 'unreturned_matrix'])
def test_unverified_rollback_is_reported_without_success(tmp_path, failure):
    v = host()
    if failure == 'remove':
        v.Net.fail_add = 'NV_2022'; v.Net.remove_fails = True
    else:
        v.Net.fail_add = 'matrix_after_create'
    with pytest.raises(RuntimeError):
        ref.run(v, tmp_path / 'run')
    status = json.loads((tmp_path / 'run/00_STATUS.json').read_text())
    assert status['status'] == 'FAILED_ROLLBACK_UNVERIFIED_CANCEL_BASE_EDIT' and status['rollback_errors']


def test_script_runs_with_existing_com_host_and_never_creates_another_visum(tmp_path, monkeypatch):
    script = tmp_path / SCRIPT.name; script.write_bytes(SCRIPT.read_bytes())
    v = host()
    runpy.run_path(str(script), init_globals={'COM': v})
    audit, = tmp_path.glob('R1_FREIGHT_2022_2025_AUDIT/RUN_*/00_STATUS.json')
    assert json.loads(audit.read_text())['status'] == 'PASS_CREATED_AND_VERIFIED'
    with pytest.raises(ref.ReferenceError, match='RUN_INSIDE_VISUM'):
        ref.main()


def test_matrix_metadata_setter_partial_failure_rolls_back_owned_matrix(tmp_path):
    v = host(); before = state(v); original = v.Net.AddMatrix
    def add(*args):
        mat = original(*args)
        def write(field, value):
            mat.attrs[field] = value
            raise RuntimeError('matrix CODE changed then COM raised')
        mat.SetAttValue = write
        return mat
    v.Net.AddMatrix = add
    with pytest.raises(RuntimeError, match='CODE changed'):
        ref.run(v, tmp_path / 'run')
    assert state(v) == before
    assert json.loads((tmp_path / 'run/00_STATUS.json').read_text())['status'] == 'FAILED_ROLLBACK_VERIFIED'


def test_rollback_preserves_unrelated_new_demand_segment(tmp_path):
    v = host(); original = v.Net.AddDemandSegment
    def add(*args):
        original(*args)
        v.Net.DemandSegments.items.append(DSeg('OTHER_USER_SEGMENT', v.Net.Modes.items[0]))
        raise RuntimeError('concurrent unrelated edit')
    v.Net.AddDemandSegment = add
    with pytest.raises(RuntimeError):
        ref.run(v, tmp_path / 'run')
    assert set(ref.index_by_code(v.Net.DemandSegments)) == {'LNV', 'NV', 'OTHER_USER_SEGMENT'}
    assert json.loads((tmp_path / 'run/00_STATUS.json').read_text())['status'] == 'FAILED_ROLLBACK_UNVERIFIED_CANCEL_BASE_EDIT'


def test_numeric_string_matrix_enums_are_accepted(tmp_path):
    v = host()
    mat = Matrix(12000, 'R1_LNV_2022_WORK')
    mat.attrs.update(OBJECTTYPEREF='2', MATRIXTYPE='3.0', DATASOURCETYPE='1')
    v.Net.Matrices.items.append(mat)
    assert ref.run(v, tmp_path / 'run')['status'] == 'PASS_CREATED_AND_VERIFIED'


@pytest.mark.parametrize('bad_api', ['matrix', 'dseg'])
def test_add_returning_an_existing_object_does_not_modify_or_remove_it(tmp_path, bad_api):
    v = host(); before = state(v)
    if bad_api == 'matrix':
        v.Net.AddMatrix = lambda *args: v.Net.Matrices.items[0]
    else:
        v.Net.AddDemandSegment = lambda *args: v.Net.DemandSegments.items[0]
    with pytest.raises(ref.ReferenceError, match='(NEW_OBJECT|WRONG_OBJECT)'):
        ref.run(v, tmp_path / 'run')
    assert state(v) == before
    assert json.loads((tmp_path / 'run/00_STATUS.json').read_text())['status'] == 'FAILED_ROLLBACK_VERIFIED'


def test_com_getter_failure_during_recovery_still_records_unverified_rollback(tmp_path):
    v = host()
    class BrokenDuringBinding(DSeg):
        broken = False
        def AttValue(self, field):
            if self.broken and field == 'CODE':
                raise RuntimeError('COM CODE getter unavailable')
            return super().AttValue(field)
        @DSeg.ODMatrix.setter
        def ODMatrix(self, value):
            self.matrix = value
            self.broken = True
    v.Net.DemandSegments.items.append(BrokenDuringBinding('NV_2025', v.Net.Modes.items[1]))
    with pytest.raises(RuntimeError, match='CODE getter unavailable'):
        ref.run(v, tmp_path / 'run')
    status = json.loads((tmp_path / 'run/00_STATUS.json').read_text())
    assert status['status'] == 'FAILED_ROLLBACK_UNVERIFIED_CANCEL_BASE_EDIT'


def test_live_2026_interface_without_mode_property_creates_and_verifies_all_targets(tmp_path):
    v = host()
    assert not hasattr(v.Net.DemandSegments.items[0], 'Mode')
    result = ref.run(v, tmp_path / 'run')
    assert result['status'] == 'PASS_CREATED_AND_VERIFIED'
    assert [r['mode'] for r in result['plan']] == ['L', 'N', 'L', 'N']


@pytest.mark.parametrize('reference_object', [False, True])
def test_direct_mode_attribute_when_qualified_attribute_is_unavailable(tmp_path, reference_object):
    v = host()
    for ds in v.Net.DemandSegments.items:
        original = ds.AttValue
        def read(field, original=original, source_mode=ds._mode):
            if field == r'MODE\CODE':
                raise AttributeError('Qualified attribute not exposed')
            if field == 'MODE' and reference_object:
                return source_mode
            return original(field)
        ds.AttValue = read
    assert ref.run(v, tmp_path / 'run')['status'] == 'PASS_CREATED_AND_VERIFIED'


def test_unreadable_mode_attributes_never_guess_a_mode_or_create_objects(tmp_path):
    v = host(); ds = v.Net.DemandSegments.items[0]; original = ds.AttValue
    def read(field):
        if field in (r'MODE\CODE', 'MODE'):
            raise RuntimeError('Mode attributes unavailable')
        return original(field)
    ds.AttValue = read
    with pytest.raises(ref.ReferenceError, match='DSEG_MODE_UNREADABLE'):
        ref.run(v, tmp_path / 'run')
    assert not v.Net.calls
    assert json.loads((tmp_path / 'run/00_STATUS.json').read_text())['status'] == 'FAILED_PREFLIGHT_NO_CHANGES'
