"""User-approved clipping: real executor/ACTIVE scoping with fake native COM."""
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_long_post_td_mask_v24917 as pm
from test_v24917_long_osrm_support import make_adapter


def harness():
    n = 3
    distance = np.array([[0., 79.999, 80.], [100., 0., 220.], [78., 250., 0.]])
    adapter, live = make_adapter(distance, zones=[11, 12, 13])
    state = NS(arrays={}, writes=[], events=[], factor=1., failure=None, failed=False,
               assigned=None, skims=None, invalidations=[])
    seed = np.arange(1., 10.).reshape(n, n)
    for no in pm.MATRIX_NOS + pm.COMPONENT_MATRICES:
        state.arrays[no] = seed * (1 + no % 5)
    state.arrays[pm.FINAL_MATRIX] = sum(state.arrays[no] for no in pm.COMPONENT_MATRICES)
    state.arrays[9116] = np.full((n, n), 17.)
    state.arrays[9101] = np.full((n, n), 5.)
    original_matrices = adapter.visum.Net.Matrices
    class Matrix:
        def __init__(self, no): self.no = no
        def GetValues(self): return state.arrays[self.no].copy()
        def SetValues(self, values, Add=False):
            # Real Visum 2026 COM expects ndarray rather than a nested Python
            # list. Simulate its strict array marshaller and explicit no-add.
            assert isinstance(values, np.ndarray), 'COM_EXPECTS_NUMPY_ARRAY'
            assert values.dtype == np.float64 and values.flags.c_contiguous
            assert Add is False, 'MATRIX_WRITE_MUST_REPLACE_NOT_ADD'
            state.writes.append(self.no)
            if state.failure == self.no and not state.failed and getattr(state, 'nonmutating', False):
                state.failed = True
                raise RuntimeError('COM_REJECTED_WITHOUT_MUTATION')
            state.arrays[self.no] = np.array(values, dtype=float, copy=True)
            if state.failure == self.no and not state.failed:
                state.arrays[self.no][0, 0] = 999.
                state.failed = True
                raise RuntimeError('COM_PARTIAL_MATRIX_WRITE')
    class Matrices:
        def ItemByKey(self, no):
            return original_matrices.ItemByKey(no) if no == 9697 else Matrix(no)
    adapter.visum.Net.Matrices = Matrices()
    class Operation:
        def __init__(self, kind, active=1):
            self.attrs = {'OPERATIONTYPE': kind, 'ACTIVE': active, 'NAME': 'OP', 'COMMENT': ''}
        def AttValue(self, attr): return self.attrs[attr]
        def SetAttValue(self, attr, value):
            assert attr == 'ACTIVE'  # no TD definition, strata or parameters changed
            self.attrs[attr] = value
    operations = [Operation(75), Operation(45), Operation(46), Operation(65),
                  Operation(101), Operation(103), Operation(65, 0)]
    adapter.visum.Procedures = NS(Operations=NS(GetAll=operations))
    adapter.cfg = {'supply': {'assignment_operations': [{'no': 5, 'operation_type': 101}]}}
    adapter._long_post_td_mask_enabled = True
    adapter.invalidate_candidate_readback = lambda reason, mutation: state.invalidations.append((reason, mutation))
    mask = distance >= 80.
    def native(visum, folder):
        for position, op in enumerate(operations, 1):
            if not op.attrs['ACTIVE'] or op.attrs['OPERATIONTYPE'] == 75: continue
            state.events.append(position)
            if position == 3:
                for no in pm.MATRIX_NOS:
                    state.arrays[no] = seed * (1 + no % 5) * state.factor
            elif position == 4:
                assert all(not state.arrays[no][~mask].any() for no in pm.MATRIX_NOS)
                for person, vehicle in zip(pm.MATRIX_NOS, pm.COMPONENT_MATRICES):
                    state.arrays[vehicle] = state.arrays[person] * .5
                    state.arrays[vehicle][2, 0] += 3.  # simulate 20B repairing reverse support
                state.arrays[pm.FINAL_MATRIX] = sum(state.arrays[no] for no in pm.COMPONENT_MATRICES)
            elif position == 5:
                assert all(not state.arrays[no][~mask].any() for no in pm.MATRIX_NOS + pm.COMPONENT_MATRICES)
                np.testing.assert_array_equal(state.arrays[pm.FINAL_MATRIX],
                                              sum(state.arrays[no] for no in pm.COMPONENT_MATRICES))
                state.assigned = state.arrays[pm.FINAL_MATRIX].copy()
            elif position == 6:
                state.skims = state.assigned.copy()
    return adapter, state, operations, mask, native


def flags(operations): return [op.attrs['ACTIVE'] for op in operations]


def test_exact_multiplication_loses_volume_without_redistribution():
    source = np.array([[1., 2.], [3., 4.]])
    target, report = pm.project(source, np.array([[False, True], [False, True]]))
    np.testing.assert_array_equal(target, [[0., 2.], [0., 4.]])
    np.testing.assert_array_equal(source, [[1., 2.], [3., 4.]])
    assert report['removed_total'] == 4. and report['after_total'] == 6.
    assert report['removed_production_by_zone'] == [1., 3.]
    assert report['removed_attraction_by_zone'] == [4., 0.]
    assert not report['pa_preserved'] and not report['renormalized']


@pytest.mark.parametrize('bad', [np.full((3, 3), np.nan), -np.ones((3, 3)), np.ones((2, 2))])
def test_invalid_component_prevents_every_write(tmp_path, bad):
    adapter, state, _, mask, _ = harness()
    state.arrays[9115] = bad
    with pytest.raises(Exception, match='LONGMASK'):
        pm.apply_group(adapter, mask, pm.MATRIX_NOS, tmp_path)
    assert not state.writes


def test_person_transaction_scope_foreign_and_loss_report(tmp_path):
    adapter, state, _, mask, _ = harness()
    before = {no: values.copy() for no, values in state.arrays.items()}
    report = pm.apply_group(adapter, mask, pm.MATRIX_NOS, tmp_path)
    assert set(state.writes) == set(pm.MATRIX_NOS)
    assert report['status'] == 'APPLIED_VERIFIED' and report['maximum_km'] is None
    for row in report['matrices']:
        no = row['matrix_no']
        assert row['removed_total'] == before[no][~mask].sum()
        np.testing.assert_array_equal(state.arrays[no][mask], before[no][mask])
        assert not state.arrays[no][~mask].any()
    np.testing.assert_array_equal(state.arrays[9116], before[9116])
    np.testing.assert_array_equal(state.arrays[9101], before[9101])
    assert state.invalidations


def test_partial_write_restores_all_owned_matrices_and_propagates(tmp_path):
    adapter, state, _, mask, _ = harness()
    before = {no: values.copy() for no, values in state.arrays.items()}
    state.failure = 9113
    with pytest.raises(RuntimeError, match='COM_PARTIAL_MATRIX_WRITE'):
        pm.apply_group(adapter, mask, pm.MATRIX_NOS, tmp_path)
    for no in before: np.testing.assert_array_equal(state.arrays[no], before[no])
    assert state.writes == [9111, 9112, 9113, 9113, 9112, 9111]



def test_visum_2026_numpy_marshalling_is_explicit_and_no_add(tmp_path):
    adapter, state, _, mask, _ = harness()
    report = pm.apply_group(adapter, mask, pm.MATRIX_NOS, tmp_path)
    assert report['matrix_com_write'] == 'NUMPY_FLOAT64_C_CONTIGUOUS_ADD_FALSE'
    assert report['status'] == 'APPLIED_VERIFIED'
    assert state.writes == list(pm.MATRIX_NOS)


def test_com_write_rejected_without_mutation_does_not_attempt_false_restore(tmp_path):
    adapter, state, _, mask, _ = harness()
    before = {no: values.copy() for no, values in state.arrays.items()}
    state.failure = 9113
    state.nonmutating = True
    with pytest.raises(RuntimeError, match='COM_REJECTED_WITHOUT_MUTATION'):
        pm.apply_group(adapter, mask, pm.MATRIX_NOS, tmp_path)
    assert state.writes == [9111, 9112, 9113, 9112, 9111]
    for no, values in before.items():
        np.testing.assert_array_equal(state.arrays[no], values)
    import json
    record = json.loads((tmp_path / 'LONG_MASK_RESULT.json').read_text())
    assert record['failed_matrix_no'] == 9113
    assert record['status'] == 'PREMASK_RESTORED_CALIBRATION_PARENT_RECOMPUTE_REQUIRED'
    assert record['restore_readbacks'][0] == {'matrix_no': 9113,
                                              'status': 'UNCHANGED_NO_REWRITE'}


def test_failed_vehicle_com_write_identifies_929x_without_false_manual_reopen(tmp_path):
    adapter, state, _, mask, _ = harness()
    before = {no: values.copy() for no, values in state.arrays.items()}
    state.failure = pm.COMPONENT_MATRICES[0]
    state.nonmutating = True
    with pytest.raises(RuntimeError, match='COM_REJECTED_WITHOUT_MUTATION'):
        pm.apply_group(adapter, mask, pm.COMPONENT_MATRICES, tmp_path,
                       aggregate_no=pm.FINAL_MATRIX)
    import json
    record = json.loads((tmp_path / 'LONG_MASK_RESULT.json').read_text())
    assert record['failed_matrix_no'] == pm.COMPONENT_MATRICES[0]
    assert record['restore_errors'] == []
    assert record['status'] == 'PREMASK_RESTORED_CALIBRATION_PARENT_RECOMPUTE_REQUIRED'
    for no, values in before.items():
        np.testing.assert_array_equal(state.arrays[no], values)


def test_arbitrary_matrix_scope_rejected(tmp_path):
    adapter, state, _, mask, _ = harness()
    with pytest.raises(Exception, match='WRITE_SCOPE_NOT_AUTHORIZED'):
        pm.apply_group(adapter, mask, [9116], tmp_path)
    assert not state.writes


def test_vehicle_aggregate_is_rebuilt_from_masked_components(tmp_path):
    adapter, state, _, mask, _ = harness()
    pm.apply_group(adapter, mask, pm.COMPONENT_MATRICES, tmp_path, aggregate_no=pm.FINAL_MATRIX)
    np.testing.assert_array_equal(state.arrays[pm.FINAL_MATRIX], sum(state.arrays[no] for no in pm.COMPONENT_MATRICES))
    assert not state.arrays[pm.FINAL_MATRIX][~mask].any()


def test_bad_component_aggregate_parity_blocks_before_writes(tmp_path):
    adapter, state, _, mask, _ = harness()
    state.arrays[pm.FINAL_MATRIX][0, 0] += 1.
    with pytest.raises(Exception, match='NATIVE_COMPONENT_AGGREGATE_PARITY'):
        pm.apply_group(adapter, mask, pm.COMPONENT_MATRICES, tmp_path, aggregate_no=pm.FINAL_MATRIX)
    assert not state.writes


def test_one_unified_td_then_masks_before_realization_assignment_and_skims(tmp_path):
    adapter, state, operations, mask, native = harness()
    old_flags = flags(operations)
    foreign, work = state.arrays[9116].copy(), state.arrays[9101].copy()
    pm.execute_sequence(adapter, tmp_path, native)
    assert state.events == [2, 3, 4, 5, 6]  # each original active leaf exactly once
    assert flags(operations) == old_flags
    assert not state.assigned[~mask].any()
    np.testing.assert_array_equal(state.skims, state.assigned)
    np.testing.assert_array_equal(state.arrays[9116], foreign)
    np.testing.assert_array_equal(state.arrays[9101], work)


def test_frozen_inner_td_masks_only_person_outputs(tmp_path):
    adapter, state, operations, mask, native = harness()
    for i, op in enumerate(operations): op.attrs['ACTIVE'] = int(i in (0, 2))
    old_flags = flags(operations)
    pm.execute_sequence(adapter, tmp_path, native)
    assert state.events == [3]
    assert set(state.writes) == set(pm.MATRIX_NOS)
    assert flags(operations) == old_flags


def test_supply_only_assignment_never_writes_demand(tmp_path):
    adapter, state, operations, mask, native = harness()
    pm.execute_sequence(adapter, tmp_path / 'baseline', native)
    state.events.clear(); state.writes.clear()
    for i, op in enumerate(operations): op.attrs['ACTIVE'] = int(i in (0, 4, 5))
    old_flags = flags(operations)
    pm.execute_sequence(adapter, tmp_path / 'supply', native)
    assert state.events == [5, 6] and not state.writes
    assert flags(operations) == old_flags


def test_supplymix_cold_recompute_removes_repaired_support_before_assignment(tmp_path):
    adapter, state, operations, mask, native = harness()
    pm.execute_sequence(adapter, tmp_path / 'baseline', native)
    parent = {no: a.copy() for no, a in state.arrays.items()}
    state.events.clear(); state.writes.clear()
    for i, op in enumerate(operations): op.attrs['ACTIVE'] = int(i in (0, 3, 4, 5))
    pm.execute_sequence(adapter, tmp_path / 'supplymix', native)
    assert state.events == [4, 5, 6]
    assert not set(state.writes) & set(pm.MATRIX_NOS)
    for no in parent: np.testing.assert_array_equal(state.arrays[no], parent[no])


def test_parent_recomputation_reproduces_same_masked_state(tmp_path):
    adapter, state, operations, mask, native = harness()
    pm.execute_sequence(adapter, tmp_path / 'baseline', native)
    parent = {no: a.copy() for no, a in state.arrays.items()}
    state.factor = 1.1
    pm.execute_sequence(adapter, tmp_path / 'candidate', native)
    assert not np.array_equal(state.arrays[9111], parent[9111])
    state.factor = 1.
    pm.execute_sequence(adapter, tmp_path / 'rollback', native)
    for no in parent: np.testing.assert_array_equal(state.arrays[no], parent[no])


def test_execution_failure_restores_active_flags_and_stops_before_assignment(tmp_path):
    adapter, state, operations, mask, native = harness()
    old_flags = flags(operations)
    def fail(visum, folder):
        native(visum, folder)
        if Path(folder).name == 'REALIZATION': raise RuntimeError('NATIVE_FAILED')
    with pytest.raises(RuntimeError, match='NATIVE_FAILED'):
        pm.execute_sequence(adapter, tmp_path, fail)
    assert flags(operations) == old_flags
    assert state.assigned is None


def test_nested_scope_cleanup_and_unscoped_execution_is_unchanged(tmp_path, monkeypatch):
    import r1_15a2_finecdf_bridge_v24916 as bridge
    monkeypatch.setattr(bridge.NoDirectMatrixWriteTDAdapter, 'execute', bridge.NoDirectMatrixWriteTDAdapter.execute)
    adapter, state, _, _, native = harness()
    calls = []
    rt = NS(execute_procseq=lambda v, p: calls.append(p))
    pm.install(rt)
    with pytest.raises(RuntimeError):
        with pm.execution_scope(adapter):
            assert pm._SCOPE.get() is adapter
            with pm.execution_scope(NS()): assert pm._SCOPE.get() is None
            assert pm._SCOPE.get() is adapter
            raise RuntimeError('FAIL')
    assert pm._SCOPE.get() is None
    rt.execute_procseq(adapter.visum, tmp_path)
    assert calls == [tmp_path]


@pytest.mark.parametrize('entry', ['assign', 'assign_for_block'])
def test_real_v24917_assignment_entry_binds_the_installed_mask_executor(tmp_path, monkeypatch, entry):
    # Use current runtime instances: launcher tests can reload modules in-process.
    import r1_15a2_trial_adapter_v24917 as adapter_module
    import r1_15a2_long_post_td_mask_v24917 as current_mask
    import r1_15a2_finecdf_bridge_v24916 as bridge
    monkeypatch.setattr(bridge.NoDirectMatrixWriteTDAdapter, 'execute', bridge.NoDirectMatrixWriteTDAdapter.execute)
    model, state, operations, mask, native = harness()
    rt = NS(execute_procseq=native)
    current_mask.install(rt)
    def assign(self, folder, **kwargs):
        return rt.execute_procseq(self.visum, folder)
    def assign_for_block(self, folder, block):
        return rt.execute_procseq(self.visum, folder)
    monkeypatch.setattr(adapter_module._V24916ActiveAdapter, 'assign', assign)
    monkeypatch.setattr(adapter_module._V24916ActiveAdapter, 'assign_for_block', assign_for_block)
    adapter = adapter_module.VisumAdapter.__new__(adapter_module.VisumAdapter)
    adapter.__dict__.update(model.__dict__)
    before_flags = flags(operations)
    if entry == 'assign': adapter.assign(tmp_path, supply_only=False)
    else: adapter.assign_for_block(tmp_path, 'TD_FINECDF')
    assert state.events == [2, 3, 4, 5, 6]
    assert flags(operations) == before_flags
    assert not state.assigned[~mask].any()
    assert current_mask._SCOPE.get() is None
