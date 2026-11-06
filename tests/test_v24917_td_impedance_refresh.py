"""Native time skim freshness and TD-entry impedance feedback contract."""
import contextlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import r1_15a2_td_impedance_refresh_v24917 as fresh
import r1_15a2_intrazonal_penalty_v24917 as iz
from r1_15a2_supply import SupplyContractError


class Attr:
    def __init__(self, **values):
        self.values = values
        self.fail_once = None

    def AttValue(self, name):
        return self.values[name]

    def SetAttValue(self, name, value):
        self.values[name] = value
        if name == self.fail_once:
            self.fail_once = None
            raise RuntimeError('partial COM parameter write')


class Matrix:
    def __init__(self, values):
        self.a = np.array(values, dtype=float)
        self.writes = 0

    def GetValues(self):
        return self.a.copy()

    def SetValues(self, *args):
        self.writes += 1
        raise AssertionError('This helper must never write matrix values directly')


class Manager:
    def __init__(self, epoch):
        self.current = epoch

    def require_current(self):
        if self.current is None:
            raise SupplyContractError('STALE_OR_MISSING_EPOCH')
        return self.current


@pytest.fixture
def env(monkeypatch):
    dist = np.array([[0., 10.], [12., 0.]])
    matrices = {901: Matrix(dist), 902: Matrix([[0, 100], [100, 0]]),
                903: Matrix([[0, 100], [100, 0]]), 9001: Matrix(dist), 9002: Matrix(dist)}
    singles = {name: Attr(Calculate=False, SaveToFile=True) for name in ('T0', 'TCur')}
    params = Attr(DSeg='NATIVE_CW', UseExistingPaths=False, OnlyRelationsWithDemand=True)
    params.SingleSkimMatrixParameters = lambda name: singles[name]
    ops = [Attr(OPERATIONTYPE=t, ACTIVE=True) for t in (fresh.com.TD, fresh.com.GROUP,
                                                      fresh.com.ASSIGNMENT_PRT, fresh.com.SKIMS_PRT)]
    ops[-1].PrTSkimMatrixParameters = params
    def operation_rows(_):
        return [{'no': i, 'type': op.AttValue('OPERATIONTYPE'),
                 'active': int(op.AttValue('ACTIVE')), 'object': op} for i, op in enumerate(ops, 1)]
    monkeypatch.setattr(fresh.com, 'operation_rows', operation_rows)
    metadata = [dict(matrix_code_norm=code, dseg_code_norm='NATIVE_CW', matrix_no_int=no)
                for code, no in [('DIS', 901), ('TTC', 902), ('TT0', 903)]]
    monkeypatch.setattr(fresh, 'matrix_inventory', lambda *args: list(metadata))
    v = SimpleNamespace(Net=SimpleNamespace(Matrices=SimpleNamespace(ItemByKey=lambda no: matrices[no])))
    epoch = SimpleNamespace(assignment_epoch=7, assignment_token='A7', epoch=9,
        zone_order_sha256=fresh.ordered_zone_hash([1, 2]),
        matrix_meta_by_dseg={'NATIVE_CW': {'matrix_no': 901, 'values_sha256': fresh.matrix_values_hash(dist)}})
    manager = Manager(epoch)
    adapter = SimpleNamespace(visum=v, zones=[1, 2], v24916_dynamic_skims=manager)
    calls = []
    def execute(visum, folder):
        assert {r['no'] for r in operation_rows(v) if r['active']} == {2, 4}
        assert params.AttValue('UseExistingPaths') is True
        assert params.AttValue('OnlyRelationsWithDemand') is False
        assert all(s.AttValue('Calculate') is True and s.AttValue('SaveToFile') is False for s in singles.values())
        matrices[902].a = np.array([[0., 600.], [600., 0.]])
        matrices[903].a = np.array([[0., 300.], [300., 0.]])
        calls.append('NATIVE_REFERENCE_SKIMS_ONLY')
    monkeypatch.setattr(fresh.rt, 'execute_procseq', execute)
    return SimpleNamespace(adapter=adapter, matrices=matrices, params=params, singles=singles,
                           ops=ops, metadata=metadata, manager=manager, epoch=epoch,
                           calls=calls, execute=execute, operation_rows=operation_rows)


def assert_restored(e):
    assert all(bool(op.AttValue('ACTIVE')) is True for op in e.ops)
    assert e.params.AttValue('UseExistingPaths') is False
    assert e.params.AttValue('OnlyRelationsWithDemand') is True
    assert all(s.AttValue('Calculate') is False and s.AttValue('SaveToFile') is True for s in e.singles.values())
    assert not any(m.writes for m in e.matrices.values())


def test_recalculates_time_skims_from_current_paths_and_restores_all_controls(env, tmp_path):
    ttc, tt0, proof = fresh.refresh(env.adapter, 'NATIVE_CW', tmp_path)
    assert env.calls == ['NATIVE_REFERENCE_SKIMS_ONLY']
    assert ttc[0, 1] == 600 and tt0[0, 1] == 300  # old, existing time skims were 100/100
    assert proof['status'] == 'FRESH_NATIVE_TIME_SKIMS' and proof['assignment_epoch'] == 7
    assert proof['matrix_bindings'] == {'DIS': 901, 'TTC': 902, 'TT0': 903}
    assert proof['ttc_sha256'] == fresh.matrix_values_hash(ttc)
    assert not proof['assignment_executed'] and not proof['td_executed']
    assert json.loads((tmp_path / 'IC_TIME_SKIM_PROOF.json').read_text()) == proof
    assert env.manager.require_current() is env.epoch
    assert_restored(env)


@pytest.mark.parametrize('partial_setting_failure', [False, True])
def test_five_segments_use_one_native_execution_and_restore_every_setting(env, tmp_path, monkeypatch,
                                                                        partial_setting_failure):
    dsegs = ('NATIVE_CW', 'NATIVE_CW_NOT', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CL')
    controls = [(env.params, env.singles)]
    for index, dseg in enumerate(dsegs[1:], 1):
        params = Attr(DSeg=dseg, UseExistingPaths=False, OnlyRelationsWithDemand=True)
        singles = {name: Attr(Calculate=False, SaveToFile=True) for name in ('T0', 'TCur')}
        params.SingleSkimMatrixParameters = lambda name, s=singles: s[name]
        op = Attr(OPERATIONTYPE=fresh.com.SKIMS_PRT, ACTIVE=True)
        op.PrTSkimMatrixParameters = params
        env.ops.append(op)
        controls.append((params, singles))
        dis_no, ttc_no, tt0_no = (9100 + 3 * index + k for k in range(3))
        env.matrices[dis_no] = Matrix([[0, 10], [12, 0]])
        env.matrices[ttc_no] = Matrix([[0, 100], [100, 0]])
        env.matrices[tt0_no] = Matrix([[0, 100], [100, 0]])
        env.metadata += [dict(matrix_code_norm=code, dseg_code_norm=dseg, matrix_no_int=no)
                         for code, no in [('DIS', dis_no), ('TTC', ttc_no), ('TT0', tt0_no)]]
        env.epoch.matrix_meta_by_dseg[dseg] = dict(matrix_no=dis_no,
            values_sha256=fresh.matrix_values_hash(env.matrices[dis_no].a))
    calls = []
    def execute(visum, folder):
        calls.append('ONE_NATIVE_BATCH')
        assert {r['no'] for r in env.operation_rows(visum) if r['active']} == {2, 4, 5, 6, 7, 8}
        for params, singles in controls:
            assert params.AttValue('UseExistingPaths') is True
            assert params.AttValue('OnlyRelationsWithDemand') is False
            assert all(s.AttValue('Calculate') is True and s.AttValue('SaveToFile') is False for s in singles.values())
        for row in env.metadata:
            if row['matrix_code_norm'] == 'TTC':
                env.matrices[row['matrix_no_int']].a *= 2.
    monkeypatch.setattr(fresh.rt, 'execute_procseq', execute)
    if partial_setting_failure:
        controls[-1][1]['TCur'].fail_once = 'Calculate'
        with pytest.raises(RuntimeError, match='partial COM'):
            fresh.refresh_many(env.adapter, dsegs, tmp_path)
        assert not calls and env.manager.current is None
        assert not (tmp_path / 'IC_TIME_SKIM_PROOF.json').exists()
    else:
        values, proof = fresh.refresh_many(env.adapter, dsegs, tmp_path)
        assert calls == ['ONE_NATIVE_BATCH'] and set(values) == set(dsegs)
        assert len(proof['matrix_bindings_by_dseg']) == 5
        assert all(ttc[0, 1] == 200. and tt0[0, 1] == 100. for ttc, tt0 in values.values())
    for params, singles in controls:
        assert params.AttValue('UseExistingPaths') is False
        assert params.AttValue('OnlyRelationsWithDemand') is True
        assert all(s.AttValue('Calculate') is False and s.AttValue('SaveToFile') is True for s in singles.values())
    assert all(bool(op.AttValue('ACTIVE')) for op in env.ops)


@pytest.mark.parametrize('failure', ['missing_time', 'duplicate_time', 'stale_dis', 'wrong_zone_order', 'wrong_dseg', 'inactive_skim'])
def test_missing_or_stale_preflight_never_executes_native_procedure(env, tmp_path, failure):
    if failure == 'missing_time':
        env.metadata.pop()
    elif failure == 'duplicate_time':
        env.metadata.append(dict(env.metadata[1], matrix_no_int=999))
    elif failure == 'stale_dis':
        env.matrices[901].a[0, 1] += 1
    elif failure == 'wrong_zone_order':
        env.adapter.zones.reverse()
    elif failure == 'wrong_dseg':
        env.params.values['DSeg'] = 'NATIVE_CS'
    else:
        env.ops[-1].values['ACTIVE'] = False
    with pytest.raises(SupplyContractError):
        fresh.refresh(env.adapter, 'NATIVE_CW', tmp_path)
    assert not env.calls
    assert env.params.AttValue('UseExistingPaths') is False
    assert not any(m.writes for m in env.matrices.values())


@pytest.mark.parametrize('failure', ['native_execution', 'partial_setting', 'new_epoch', 'binding_change', 'dis_changed', 'nonfinite_time'])
def test_failure_restores_controls_invalidates_epoch_and_does_not_publish_success(env, tmp_path, monkeypatch, failure):
    if failure == 'partial_setting':
        env.singles['TCur'].fail_once = 'Calculate'
    else:
        def execute(*args):
            env.execute(*args)
            if failure == 'native_execution':
                raise RuntimeError('skim COM failure')
            if failure == 'new_epoch':
                env.manager.current = SimpleNamespace(assignment_epoch=8)
            elif failure == 'binding_change':
                env.metadata[1]['matrix_no_int'] = 999
            elif failure == 'dis_changed':
                env.matrices[901].a[0, 1] += 1
            elif failure == 'nonfinite_time':
                env.matrices[902].a[0, 1] = np.nan
        monkeypatch.setattr(fresh.rt, 'execute_procseq', execute)
    with pytest.raises((SupplyContractError, RuntimeError)):
        fresh.refresh(env.adapter, 'NATIVE_CW', tmp_path)
    assert env.manager.current is None and not (tmp_path / 'IC_TIME_SKIM_PROOF.json').exists()
    assert_restored(env)


def test_control_restore_failure_invalidates_epoch_and_never_certifies_fresh_skims(env, tmp_path, monkeypatch):
    original = env.params.SetAttValue
    def write(name, value):
        original(name, value)
        if name == 'UseExistingPaths' and value is False:
            raise RuntimeError('restore COM failure')
    monkeypatch.setattr(env.params, 'SetAttValue', write)
    with pytest.raises(SupplyContractError, match='SETTINGS_RESTORE_FAILED'):
        fresh.refresh(env.adapter, 'NATIVE_CW', tmp_path)
    assert env.manager.current is None and not (tmp_path / 'IC_TIME_SKIM_PROOF.json').exists()
    assert not any(m.writes for m in env.matrices.values())


def test_finite_no_path_time_cells_retain_existing_impedance_fallback_policy(env, tmp_path, monkeypatch):
    def execute(*args):
        env.execute(*args)
        env.matrices[902].a[1, 0] = -1.
        env.matrices[903].a[1, 0] = -1.
    monkeypatch.setattr(fresh.rt, 'execute_procseq', execute)
    ttc, tt0, _ = fresh.refresh(env.adapter, 'NATIVE_CW', tmp_path)
    base = np.array([[2., 5.], [6., 2.]])
    target = iz.congested_impedance(base, ttc, tt0, 'RATIO', 4.)
    assert target['U'][1, 0] == base[1, 0] and target['invalid_cells'] == 1


def test_low_count_ratio_no_longer_defers_impedance_refresh(monkeypatch):
    monkeypatch.setattr(iz, 'STATE', {'active': True, 'options': {
        'ic_enabled': True, 'ic_refresh_policy': 'EVERY_TD_STAGE', 'ic_start_model_obs_ratio': .8}})
    diag = {'d12': {'rows': [{'role': 'CALIBRATION', 'observed': 1000., 'model': 200.}]}}
    due = iz.congestion_due(diag, 2)
    assert due['due'] and due['reason'] == 'EVERY_TD_STAGE'
    assert iz.STATE['ic_start']['trigger'] == 'EVERY_TD_STAGE'


def test_required_refresh_cannot_silently_disable_itself(monkeypatch):
    monkeypatch.setattr(iz, 'STATE', {'active': False, 'reason': 'M9002_MISSING', 'options': {
        'ic_enabled': True, 'ic_refresh_policy': 'EVERY_TD_STAGE'}})
    with pytest.raises(iz.IZError, match='REQUIRED_BUT_INACTIVE'):
        iz.congestion_due({}, 2)


def test_activation_com_failure_preserves_required_policy(monkeypatch):
    monkeypatch.setattr(iz, 'STATE', {})
    monkeypatch.setattr(iz, '_zone_order', lambda *args: (_ for _ in ()).throw(RuntimeError('COM zones unreadable')))
    visum = SimpleNamespace(Net=SimpleNamespace(Matrices=SimpleNamespace(ItemByKey=lambda no: object())))
    result = iz.activate(visum, {'ic_enabled': True, 'ic_refresh_policy': 'EVERY_TD_STAGE', 'iz_matrix_no': 9002})
    assert result['active'] is False and iz.STATE['options']['ic_refresh_policy'] == 'EVERY_TD_STAGE'
    with pytest.raises(iz.IZError, match='REQUIRED_BUT_INACTIVE'):
        iz.congestion_due({}, 2)


def test_invalid_run_policy_is_not_replaced_with_defaults_on_activation(monkeypatch):
    monkeypatch.setattr(iz, 'iz_options', lambda: (_ for _ in ()).throw(RuntimeError('INVALID_OPTIONS')))
    with pytest.raises(RuntimeError, match='INVALID_OPTIONS'):
        iz.activate(object())


def test_refresh_policy_validation(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    assert dp.load_options(tmp_path, environ={})['ic_refresh_policy'] == 'EVERY_TD_STAGE'
    assert dp.validate({'ic_refresh_policy': 'LATE_PHASE', 'ic_utility_mode': 'COMMON'})['ic_refresh_policy'] == 'LATE_PHASE'
    with pytest.raises(RuntimeError, match='ic_refresh_policy'):
        dp.validate({'ic_refresh_policy': 'ANY_OLD_MATRIX'})


def test_fresh_native_times_actually_update_9002_and_preserve_reference_and_diagonal(env, tmp_path, monkeypatch):
    base = np.array([[2., 5.], [6., 2.]])
    env.matrices[9001].a = base.copy(); env.matrices[9002].a = base.copy()
    writes = []
    env.matrices[9002].SetValues = lambda values: (writes.append('M9002'), setattr(env.matrices[9002], 'a', np.asarray(values)))
    monkeypatch.setattr(iz, 'STATE', dict(active=True, matrix_no=9002, zone_order=[1, 2],
        base=base.copy(), osrm=base.copy(), base_diag=np.diag(base).copy(),
        zones=[], idx=np.array([], dtype=int), bases={iz.base_sha(base): base.copy()},
        options=dict(ic_refresh_policy='EVERY_TD_STAGE', ic_skim_dseg='NATIVE_CW',
                     ic_mode='RATIO', ic_lambda=.5, ic_ratio_max=4., ic_min_rel_change=.002,
                     iz_max_penalty_min=15.)))
    def snapshot():
        return {'state_hash': 'MOCK_STATE', iz.SNAPSHOT_KEY: {}, iz.BASE_KEY: iz.base_sha(iz.STATE['base'])}
    diag = {'d12': {'rows': [{'role': 'CALIBRATION', 'observed': 1000., 'model': 200.}]}}
    env.adapter.snapshot = snapshot
    env.adapter.diagnostics = lambda *args: diag
    assignments = []
    ctrl = SimpleNamespace(canonical_hash=lambda x: json.dumps(x, sort_keys=True),
        recovery_scope=lambda *args: contextlib.nullcontext(),
        _assign_candidate=lambda *args: assignments.append('FULL_DOWNSTREAM') or .001,
        _td_expected_freeze=lambda *args: None)
    state, _, rec = iz.congestion_feedback(ctrl, env.adapter, {}, tmp_path, None, snapshot(), diag)
    assert rec['status'] == 'APPLIED' and rec['fresh_time_skim_proof']['status'] == 'FRESH_NATIVE_TIME_SKIMS'
    assert env.matrices[9002].a[0, 1] == pytest.approx(7.5)  # fresh ratio 600/300, not stale 100/100
    assert env.matrices[9002].a[1, 0] == pytest.approx(9.)
    assert np.array_equal(np.diag(env.matrices[9002].a), np.diag(base))
    assert np.array_equal(env.matrices[9001].a, base)
    assert state[iz.BASE_KEY] == iz.base_sha(iz.STATE['base']) and assignments == ['FULL_DOWNSTREAM']
    assert env.calls == ['NATIVE_REFERENCE_SKIMS_ONLY'] and writes == ['M9002']


@pytest.mark.parametrize('status', ['APPLIED', 'CONVERGED_NO_WRITE', 'FAILED_ROLLED_BACK', 'SKIPPED_NO_DYNAMIC_SKIM_MANAGER'])
def test_required_refresh_is_a_gate_before_inner_search(tmp_path, monkeypatch, status):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as tx
    import r1_15a2_active_controller_patch_v24916p2c as acp
    for obj, name in ((ctrl, 'run_finecdf_inner'), (ctrl, '_realize_finecdf_td'), (ctrl, '_finecdf_td_once'),
                      (ctrl, 'restore_td_parameters'), (tx, 'restore_td_parameters'), (acp, 'targeted_run_finecdf_inner')):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    monkeypatch.setattr(iz, '_INSTALLED', {})
    monkeypatch.setattr(iz, 'STATE', {'active': True, 'zones': [], 'options': {
        'ic_enabled': True, 'ic_refresh_policy': 'EVERY_TD_STAGE'}})
    calls = []
    monkeypatch.setattr(ctrl, '_finecdf_td_once', lambda *args, **kwargs:
                        calls.append('INNER_TD') or (False, args[4], args[5], {}))
    monkeypatch.setattr(iz, 'congestion_feedback', lambda *args: (args[5], args[6], {
        'status': status, 'applied': status == 'APPLIED',
        'fresh_time_skim_proof': {'status': 'FRESH_NATIVE_TIME_SKIMS'}}))
    iz.install(print_fn=lambda *args: None)
    args = (None, {}, tmp_path, None, {'state_hash': 'PARENT'}, {}, 'root')
    if status in ('APPLIED', 'CONVERGED_NO_WRITE'):
        changed, *_ = ctrl._finecdf_td_once(*args, outer_cycle=2)
        assert changed is (status == 'APPLIED') and calls == ['INNER_TD']
    else:
        with pytest.raises(iz.IZError, match='REQUIRED_REFRESH_NOT_COMPLETED'):
            ctrl._finecdf_td_once(*args, outer_cycle=2)
        assert not calls
