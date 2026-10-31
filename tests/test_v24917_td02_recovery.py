"""COM-shaped reproductions of TD startup/recovery after rejected TG/SupplyMix."""
import copy
import importlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


class Rejected(Exception):
    hresult = -2147418111

    def __init__(self):
        super().__init__(-2147418111, 'Volaný odmítl volání.', None, None)


@pytest.mark.parametrize('rejections', [1, 2])
def test_real_readonly_native16_constructor_retries_procedures_getter(tmp_path, monkeypatch, rejections):
    runtime = importlib.import_module('r1_15a2_td_joint_runtime_v24917')
    bridge = importlib.import_module('r1_15a2_finecdf_bridge_v24916')
    fix = importlib.import_module('r1_15a2_td09c_16or17_hotfix_v24916')
    com = importlib.import_module('r1_15a2_com_compat')
    cb = importlib.import_module('r1_15a2_combusy2_v24917')
    from test_v245_native_bridge import fixture
    ref, _, _, visum, cfg, control, _, matrices, executions = fixture(tmp_path)
    params = visum.Procedures.Operations.items[1].TripDistributionParameters
    params.SetAttValue('DSTRATSET', params.AttValue('DSTRATSET').replace('4_FOREIGN,', '').replace(',4_FOREIGN', ''))
    original = params.AttValue('DSTRATSET')
    before = {no: matrix.values.copy() for no, matrix in matrices.items()}
    class BusyVisum:
        rejected = 0
        def __getattr__(self, name):
            if name == 'Procedures' and self.rejected < rejections:
                self.rejected += 1
                raise Rejected()
            return getattr(visum, name)
    host = BusyVisum()
    monkeypatch.setattr(bridge.NoDirectMatrixWriteTDAdapter, '__init__', fix._compatible_init)
    monkeypatch.setattr(com, '_retry_budget', lambda p: (3 if p.get('enabled') else 1, 0., 1., 0., 10.))
    monkeypatch.setattr(cb, '_pump_sleep', lambda s: None)
    monkeypatch.setattr(runtime.joint, 'options', lambda: {'enabled': False})
    outer = NS(com_retry_policy={'enabled': True}, cfg=cfg)
    def inner(adapter, scoped, folder, ctl, root):
        obj = bridge.NoDirectMatrixWriteTDAdapter(host, ref, folder, ctl, outer_adapter=adapter)
        return {'scope': obj.td09c_scope, 'owner_preserved': obj.v is host}
    target = tmp_path/'inner'; target.mkdir()
    result = runtime.wrap_inner(inner)(outer, {}, target, control, tmp_path)
    assert result == {'scope': 'NATIVE16_FOREIGN_SEPARATE', 'owner_preserved': True}
    assert host.rejected == rejections and executions == []
    assert params.AttValue('DSTRATSET') == original
    for no, values in before.items():
        assert (matrices[no].values == values).all()


@pytest.mark.parametrize('kind', ['disabled', 'exhausted', 'structural'])
def test_constructor_retry_is_bounded_and_does_not_retry_structural_error(tmp_path, monkeypatch, kind):
    runtime = importlib.import_module('r1_15a2_td_joint_runtime_v24917')
    bridge = importlib.import_module('r1_15a2_finecdf_bridge_v24916')
    fix = importlib.import_module('r1_15a2_td09c_16or17_hotfix_v24916')
    com = importlib.import_module('r1_15a2_com_compat')
    cb = importlib.import_module('r1_15a2_combusy2_v24917')
    calls = []
    class Busy:
        @property
        def Procedures(self):
            calls.append(1)
            if kind == 'structural': raise ValueError('MISSING_PROCEDURE_COLLECTION')
            raise Rejected()
    monkeypatch.setattr(bridge.NoDirectMatrixWriteTDAdapter, '__init__', fix._compatible_init)
    monkeypatch.setattr(com, '_retry_budget', lambda p: (3 if p.get('enabled') else 1, 0., 1., 0., 10.))
    monkeypatch.setattr(cb, '_pump_sleep', lambda s: None)
    monkeypatch.setattr(runtime.joint, 'options', lambda: {'enabled': False})
    def inner(adapter, cfg, folder, control, root):
        bridge.NoDirectMatrixWriteTDAdapter(Busy(), NS(CONFIG={'expected_zone_count': 681}),
                                           folder, outer_adapter=adapter)
    outer = NS(com_retry_policy={'enabled': kind != 'disabled'})
    with pytest.raises(ValueError if kind == 'structural' else Rejected):
        runtime.wrap_inner(inner)(outer, {}, tmp_path, None, tmp_path)
    assert len(calls) == (3 if kind == 'exhausted' else 1)


def test_unknown_constructor_with_copied_readonly_marker_is_not_wrapped():
    cb = importlib.import_module('r1_15a2_combusy2_v24917')
    def unknown(*a, **k): raise Rejected()
    unknown._v24916_td09c_compat = True
    cls = type('UnknownTD', (), {'__init__': unknown})
    cb.install_td_constructor_retry(NS(NoDirectMatrixWriteTDAdapter=cls))
    assert cls.__init__ is unknown


@pytest.mark.parametrize('same_parent', [True, False])
def test_manual_reopen_error_never_retries_or_reads_parent(monkeypatch, same_parent):
    cb = importlib.import_module('r1_15a2_combusy2_v24917')
    com = importlib.import_module('r1_15a2_com_compat')
    from r1_15a2_supply import SupplyContractError
    calls, snapshots = [], []
    def block(*args):
        calls.append(1)
        if len(calls) > 1: return 'UNSAFE_RETRY'
        try: raise Rejected()
        except Rejected as exc:
            raise SupplyContractError('V24916_FINECDF_ROLLBACK_FAILED_MANUAL_REOPEN') from exc
    def snapshot():
        snapshots.append(1)
        return {'parent': 1} if same_parent else {'other': 2}
    monkeypatch.setattr(cb, '_pump_sleep', lambda s: None)
    with pytest.raises(SupplyContractError, match='MANUAL_REOPEN'):
        cb._wrap_block(block, com, 'TD', 1, 3)(NS(snapshot=snapshot), {}, Path('TD'),
                                             None, {'parent': 1})
    assert calls == [1] and snapshots == []


def test_manual_reopen_error_is_not_repeated_inside_rollback_wrapper(monkeypatch):
    cb = importlib.import_module('r1_15a2_combusy2_v24917')
    com = importlib.import_module('r1_15a2_com_compat')
    from r1_15a2_supply import SupplyContractError
    calls = []
    def restore():
        calls.append(1)
        if len(calls) > 1: return 'UNSAFE_RETRY'
        try: raise Rejected()
        except Rejected as exc:
            raise SupplyContractError('FAILED_MANUAL_RECOVERY_REQUIRED') from exc
    monkeypatch.setattr(cb, '_pump_sleep', lambda s: None)
    with pytest.raises(SupplyContractError, match='MANUAL_RECOVERY'):
        cb._wrap_rollback(restore, com, 900.)()
    assert calls == [1]


def install_restore_fixture(monkeypatch):
    iz = importlib.import_module('r1_15a2_intrazonal_penalty_v24917')
    tx = importlib.import_module('r1_15a2_inplace_transaction_v24915p2')
    ctrl = importlib.import_module('r1_15a2_overnight_controller_coupled_v24915p2_force100')
    acp = importlib.import_module('r1_15a2_active_controller_patch_v24916p2c')
    for module, name in [(ctrl, 'run_finecdf_inner'), (ctrl, '_realize_finecdf_td'),
                         (ctrl, '_finecdf_td_once'), (acp, 'targeted_run_finecdf_inner')]:
        monkeypatch.setattr(module, name, getattr(module, name))
    writes, impedance = [], []
    def restore(adapter, before, rows, folder=None):
        writes.append(copy.deepcopy(rows))
        return [{'component': r['component'], 'status': 'OK'} for r in rows]
    monkeypatch.setattr(tx, 'restore_td_parameters', restore)
    monkeypatch.setattr(ctrl, 'restore_td_parameters', restore)
    monkeypatch.setattr(iz, '_INSTALLED', {})
    monkeypatch.setattr(iz, 'restore_from_snapshot', lambda *a: impedance.append(a))
    iz.install(print_fn=lambda *a: None)
    before = {'td_values': [{'component': 'WORK_E_C', 'current_b': 1., 'current_c': -.5, 'status': 'OK'}],
              'td_hash': 'a'*64, 'operations_hash': 'b'*64, iz.BASE_KEY: 'parent-utility'}
    live = copy.deepcopy(before)
    reads = []
    def snapshot(): reads.append(1); return copy.deepcopy(live)
    adapter = NS(visum=object(), generation_guard_snapshot=snapshot)
    return tx, ctrl, before, live, adapter, writes, impedance, reads


def test_failed_startup_unchanged_bc_still_restores_impedance_and_recomputes(tmp_path, monkeypatch):
    tx, ctrl, before, live, adapter, writes, impedance, reads = install_restore_fixture(monkeypatch)
    folder = tmp_path/'ROLLBACK_AFTER_TD_FAILURE'
    diag = {'proof': 'parent'}
    recomputes = []
    monkeypatch.setattr(ctrl, '_assign_candidate', lambda *a: recomputes.append(a) or .001)
    monkeypatch.setattr(ctrl, '_td_parent_state_equivalent', lambda *a: True)
    monkeypatch.setattr(ctrl, 'diagnostic_hash', lambda d: d['proof'])
    adapter.snapshot = lambda: copy.deepcopy(before)
    adapter.diagnostics = lambda *a: copy.deepcopy(diag)
    result = inspect.unwrap(ctrl._rollback_td_all)(adapter, before, diag, folder, {})
    assert result == (before, diag)
    assert writes == [] and reads == [1] and len(impedance) == len(recomputes) == 1
    audit = json.loads((folder/'ROLLBACK_PARAMETER_READBACK.json').read_text())
    assert audit[0]['status'] == 'OK' and audit[0]['write_skipped'] is True
    assert json.loads((folder/'ROLLBACK_ALL_TD_RESULT.json').read_text())['passes'] is True


@pytest.mark.parametrize('damage', ['b', 'scope', 'hash', 'status', 'nan'])
def test_bc_skip_requires_fresh_complete_same_scope_readback(tmp_path, monkeypatch, damage):
    tx, _, before, live, adapter, writes, impedance, reads = install_restore_fixture(monkeypatch)
    if damage == 'b': live['td_values'][0]['current_b'] = 2.
    elif damage == 'scope': live['operations_hash'] = 'changed'
    elif damage == 'hash': live['td_hash'] = 'changed'
    elif damage == 'status': live['td_values'][0]['status'] = 'UNREADABLE'
    else: live['td_values'][0]['current_c'] = float('nan')
    tx.restore_td_parameters(adapter, before, [{'component': 'WORK_E_C'}], tmp_path/'ROLLBACK_AFTER_TD_FAILURE')
    assert len(writes) == len(impedance) == 1 and reads == [1]


def test_other_restore_scopes_keep_original_parameter_writes(tmp_path, monkeypatch):
    tx, _, before, _, adapter, writes, impedance, reads = install_restore_fixture(monkeypatch)
    tx.restore_td_parameters(adapter, before, [{'component': 'WORK_E_C'}], tmp_path/'NORMAL_BACKTRACK')
    assert len(writes) == len(impedance) == 1 and reads == []


def test_failed_live_read_never_claims_unchanged_td(tmp_path, monkeypatch):
    tx, _, before, _, adapter, writes, impedance, _ = install_restore_fixture(monkeypatch)
    def busy(): raise Rejected()
    adapter.generation_guard_snapshot = busy
    with pytest.raises(Rejected):
        tx.restore_td_parameters(adapter, before, [{'component': 'WORK_E_C'}], tmp_path/'ROLLBACK_AFTER_TD_FAILURE')
    assert writes == impedance == []


def test_missing_readback_audit_is_not_reported_as_verified_skip(tmp_path, monkeypatch):
    tx, _, before, _, adapter, writes, impedance, _ = install_restore_fixture(monkeypatch)
    def fail(*a): raise OSError('READBACK_AUDIT_DISK_FULL')
    monkeypatch.setattr(tx, 'atomic_json', fail)
    with pytest.raises(OSError, match='DISK_FULL'):
        tx.restore_td_parameters(adapter, before, [{'component': 'WORK_E_C'}], tmp_path/'ROLLBACK_AFTER_TD_FAILURE')
    assert writes == impedance == []


@pytest.mark.parametrize('damage', ['duplicate', 'missing', 'bool', 'parent_bool', 'hash_bool'])
def test_invalid_parent_parameter_evidence_cannot_skip_writes(tmp_path, monkeypatch, damage):
    tx, _, before, live, adapter, writes, impedance, _ = install_restore_fixture(monkeypatch)
    if damage == 'duplicate':
        before['td_values'].append(copy.deepcopy(before['td_values'][0]));live.update(copy.deepcopy(before))
    elif damage == 'missing':
        del before['operations_hash'];del live['operations_hash']
    elif damage == 'parent_bool':
        before['td_values'][0]['current_b'] = True
    elif damage == 'hash_bool':
        before['operations_hash'] = live['operations_hash'] = True
    else:
        before['td_values'][0]['current_b'] = True;live.update(copy.deepcopy(before))
    tx.restore_td_parameters(adapter, before, [{'component': 'WORK_E_C'}], tmp_path/'ROLLBACK_AFTER_TD_FAILURE')
    assert len(writes) == len(impedance) == 1
