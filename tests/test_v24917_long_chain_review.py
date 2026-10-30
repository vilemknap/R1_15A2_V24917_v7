"""LONG identity, coherent live proof, fixed TD generation and atomic plans."""
import copy
from collections import Counter
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_long_composite_td_v24917 as long_td
import r1_15a2_long_post_td_mask_v24917 as mask
import r1_15a2_td_joint_runtime_v24917 as wire
from test_v24917_long_tg_td_unlock import _long_readback
from test_v24917_long_post_td_mask import harness
from test_v24917_long_composite_td import reference, proposal


@pytest.mark.parametrize('no', [9111, 9291, 9305, 9116])
def test_matrix_read_never_accepts_wrong_object_even_with_valid_shaped_values(no):
    reads = []
    matrix = NS(AttValue=lambda attr: 9116 if no != 9116 else 9111,
                GetValues=lambda: reads.append(1) or np.zeros((2, 2)))
    adapter = NS(visum=NS(Net=NS(Matrices=NS(ItemByKey=lambda n: matrix))),
                 com_retry_policy={'enabled': False})
    with pytest.raises(Exception, match='LONGMASK_MATRIX_IDENTITY_MISMATCH'):
        mask._read(adapter, no)
    assert reads == []


def test_wrong_matrix_object_cannot_reach_any_mask_write(tmp_path):
    adapter, state, operations, support, native = harness()
    matrices = adapter.visum.Net.Matrices
    original = matrices.ItemByKey
    matrices.ItemByKey = lambda no: original(9116 if no == 9111 else no)
    before = {no: a.copy() for no, a in state.arrays.items()}
    with pytest.raises(Exception, match='LONGMASK_MATRIX_IDENTITY_MISMATCH'):
        mask.apply_group(adapter, support, mask.MATRIX_NOS, tmp_path)
    assert state.writes == []
    for no, a in before.items():
        np.testing.assert_array_equal(state.arrays[no], a)


@pytest.mark.parametrize('fault', ['in_progress', 'missing_binding', 'wrong_assignment', 'wrong_zone_hash'])
def test_long_readiness_cannot_certify_pending_or_unbound_assignment(monkeypatch, fault):
    outer, bridge, _ = _long_readback(monkeypatch)
    if fault == 'in_progress': outer.readback_manager.assignment_in_progress = True
    elif fault == 'missing_binding': outer._long_incidence_assignment_binding = None
    elif fault == 'wrong_assignment': outer.readback_manager.assignment_epoch += 1
    else: outer.v24916_dynamic_skims.require_current().zone_order_sha256 = 'wrong'
    with pytest.raises((ValueError, RuntimeError)):
        long_td.live_readiness(bridge)


def test_readiness_uses_one_read_per_long_matrix_and_keeps_parity(monkeypatch):
    outer, bridge, arrays = _long_readback(monkeypatch)
    import r1_15a2_long_post_td_mask_v24917 as live_mask
    original = live_mask._read
    calls = []
    def read(adapter, no):
        calls.append(no)
        return original(adapter, no)
    monkeypatch.setattr(live_mask, '_read', read)
    result = long_td.live_readiness(bridge)
    expected = long_td.MATRIX_NOS + live_mask.COMPONENT_MATRICES + (9305,)
    assert Counter(calls) == Counter(expected)
    assert result['vehicle_volume'] == pytest.approx(float(arrays[9305].sum()))
    assert result['assignment_binding']['assignment_epoch'] == 77


@pytest.mark.parametrize('fault', ['mutation_epoch', 'assignment_epoch', 'support_identity'])
def test_change_during_long_readiness_invalidates_whole_proof(monkeypatch, fault):
    outer, bridge, _ = _long_readback(monkeypatch)
    import r1_15a2_long_post_td_mask_v24917 as live_mask
    import r1_15a2_long_support_distance_v24917 as live_support
    original = live_mask._read
    distance, source = live_support.read_current(outer)
    source_state = dict(source)
    monkeypatch.setattr(live_support, 'read_current', lambda a: (distance, dict(source_state)))
    def read(adapter, no):
        result = original(adapter, no)
        if no == 9305:
            if fault == 'mutation_epoch': outer.readback_manager.mutation_epoch += 1
            elif fault == 'assignment_epoch':
                outer.readback_manager.assignment_epoch += 1
                outer.v24916_dynamic_skims.require_current().assignment_epoch += 1
            else:
                source_state['values_sha256'] = 'changed'
        return result
    monkeypatch.setattr(live_mask, '_read', read)
    with pytest.raises(RuntimeError, match='STATE_CHANGED_DURING_READINESS'):
        long_td.live_readiness(bridge)


@pytest.mark.parametrize('fault', ['negative_new_b', 'duplicate_parent', 'aliased_sixth_component'])
def test_shared_long_plan_rejects_invalid_domain_and_ambiguous_scope(reference, fault):
    before, after, parents, rows, registry = proposal(reference)
    if fault == 'negative_new_b':
        for row in rows:
            no = registry[row['component']]
            row['candidate_b'] = before[no]['b'] - 2.
    elif fault == 'duplicate_parent':
        parents.append(dict(parents[0]))
    else:
        alias = dict(rows[0], component='LONG_ALIAS')
        no = registry[rows[0]['component']]
        registry['LONG_ALIAS'] = no
        parents.append(dict(component='LONG_ALIAS', current_b=before[no]['b'], current_c=before[no]['c']))
        rows.append(alias)
    with pytest.raises(ValueError, match='TDLONG_COMPOSITE'):
        long_td.realization_groups(rows, parents, registry)


class Zones:
    def __init__(self):
        self.values = {a: {1: 10., 2: 0.} for a in long_td.GENERATION_ATTRS}
        self.values.update(ADD_PROD_L={1: .3, 2: .3}, ADD_ATT_L={1: 1., 2: 1.})
    def GetMultiAttValues(self, attr, *args):
        return [(9, 2 if attr == 'NO' else self.values[attr][2]),
                (3, 1 if attr == 'NO' else self.values[attr][1])]


def host():
    return NS(outer_adapter=NS(_long_post_td_mask_enabled=True, v24917_ls={'active': True}),
              zone_order=[1, 2], v=NS(Net=NS(Zones=Zones())), ref=NS(GROUPS=['LONG_COMPOSITE']))


@pytest.mark.parametrize('attr', long_td.GENERATION_ATTRS + ('ADD_PROD_L', 'ADD_ATT_L'))
def test_long_native_td_cannot_change_fixed_generation_or_coefficients(monkeypatch, attr):
    import r1_15a2_long_post_td_mask_v24917 as live_mask
    monkeypatch.setattr(wire.joint, 'options', lambda: {'long_enabled': True})
    bridge = host()
    def native(obj):
        assert live_mask._SCOPE.get() is obj.outer_adapter
        obj.v.Net.Zones.values[attr][1] += .1
    with pytest.raises(RuntimeError, match='TDLONG_COMPOSITE_FIXED_GENERATION_CHANGED'):
        wire.wrap_dynamic_realization(native)(bridge)
    assert live_mask._SCOPE.get() is None
    assert not hasattr(bridge, '_long_generation_freeze_proof')


def test_fixed_long_generation_remains_pinned_between_probes(monkeypatch):
    monkeypatch.setattr(wire.joint, 'options', lambda: {'long_enabled': True})
    bridge = host()
    calls = []
    run = wire.wrap_dynamic_realization(lambda obj: calls.append(1))
    run(bridge)
    assert bridge._long_generation_freeze_proof['status'] == 'VERIFIED_FIXED_LONG_GENERATION'
    bridge.v.Net.Zones.values['FA_3_LONG'][1] += 1.
    with pytest.raises(RuntimeError, match='FIXED_GENERATION_CHANGED'):
        run(bridge)
    assert len(calls) == 1


def outer_stage(reference, monkeypatch):
    import r1_15a2_multiblock as mb
    import r1_15a2_td_count_blend_v24917 as tb
    before, after, parents, rows, registry = proposal(reference)
    parents = [r for r in parents if r['component'] in mb.COMPONENT_REGISTRY]
    monkeypatch.setattr(wire.joint, 'options', lambda: {'enabled': True, 'outer_isolates': False})
    monkeypatch.setattr(tb, 'options', lambda: {'w_cnt': .6, 'w_idp': .4})
    ready = {'status': 'READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE'}
    monkeypatch.setattr(wire.long_td, 'require_live_ready', lambda *a, **k: ready)
    adapter = NS(_tdjoint_stage={'w_cnt': .6, 'w_idp': .4, 'final_abc': {str(n): a for n, a in after.items()},
        'entry_abc': {str(n): a for n, a in before.items()}, 'long_composite_live_readiness': ready})
    return adapter, {'td_values': parents}, rows


def test_native_17_parameter_stage_binds_to_outer_16_component_parent(reference, monkeypatch, tmp_path):
    import r1_15a2_intrazonal_penalty_v24917 as iz
    monkeypatch.setattr(iz, '_STAGE', {})
    adapter, before, rows = outer_stage(reference, monkeypatch)
    calls = []
    expected = (rows, {}, {}, 0., {})
    run = wire.wrap_realization(lambda *args: calls.append(1) or expected, NS())
    assert run(adapter, {}, tmp_path, None, before, {}, rows) is expected
    assert calls == [1]


@pytest.mark.parametrize('fault', ['stale_parent', 'missing_entry', 'missing_outer_parent'])
def test_stale_or_incomplete_long_inner_stage_stops_before_realization(reference, monkeypatch, tmp_path, fault):
    adapter, before, rows = outer_stage(reference, monkeypatch)
    if fault == 'stale_parent': before['td_values'][0]['current_b'] += .1
    elif fault == 'missing_entry': adapter._tdjoint_stage['entry_abc'].pop('9111')
    else: before['td_values'].pop()
    calls = []
    with pytest.raises(RuntimeError, match='TDLONG_COMPOSITE_STAGE_PARENT_MISMATCH'):
        wire.wrap_realization(lambda *args: calls.append(1), NS())(
            adapter, {}, tmp_path, None, before, {}, rows)
    assert calls == []


from test_v24917_long_cache_generation import live


def test_new_long_generation_proposal_requires_completed_assignment(live):
    import r1_15a2_long_cache_generation_v24917 as cache
    adapter, state, _ = live
    adapter.readback_manager.assignment_completed = False
    adapter.readback_manager.assignment_epoch += 1  # a failed new assignment cannot reuse the old stamp
    reads = list(state.matrix_reads)
    with pytest.raises(ValueError, match='EPOCH_MISMATCH|BINDING_STALE'):
        cache.capture(adapter)
    assert state.matrix_reads == reads


def test_ended_candidate_keeps_a_proven_completed_assignment_usable(monkeypatch):
    outer, bridge, _ = _long_readback(monkeypatch)
    outer.readback_manager.assignment_completed = False  # end_candidate, no model mutation
    assert long_td.live_readiness(bridge)['assignment_binding'] == outer._long_incidence_assignment_binding


def test_each_native_long_probe_publishes_its_completed_assignment_binding(monkeypatch):
    outer, ready_bridge, _ = _long_readback(monkeypatch)
    bridge = host()
    bridge.outer_adapter = outer
    bridge.dynamic_skim_enabled = True
    epoch = outer.v24916_dynamic_skims.require_current()
    monkeypatch.setattr(wire.joint, 'options', lambda: {'long_enabled': True})
    def native(obj):
        outer.readback_manager.assignment_epoch += 1
        outer.readback_manager.mutation_epoch += 1
        epoch.assignment_epoch = outer.readback_manager.assignment_epoch
        epoch.epoch_hash = 'skim-' + str(epoch.assignment_epoch)
        epoch.assignment_token = 'native-' + str(epoch.assignment_epoch)
        return epoch
    run = wire.wrap_dynamic_realization(native)
    for expected in (78, 79):
        assert run(bridge) is epoch
        assert outer._long_incidence_assignment_binding['assignment_epoch'] == expected
        assert long_td.live_readiness(ready_bridge)['assignment_epoch'] == expected


@pytest.mark.parametrize('fault', ['wrong_epoch_object', 'not_completed'])
def test_unproven_native_epoch_never_publishes_a_new_long_binding(monkeypatch, fault):
    outer, _, _ = _long_readback(monkeypatch)
    bridge = host()
    bridge.outer_adapter = outer
    bridge.dynamic_skim_enabled = True
    old = dict(outer._long_incidence_assignment_binding)
    epoch = outer.v24916_dynamic_skims.require_current()
    def native(obj):
        if fault == 'not_completed':
            outer.readback_manager.assignment_completed = False
            return epoch
        return NS(assignment_epoch=epoch.assignment_epoch)
    with pytest.raises((ValueError, RuntimeError), match='EPOCH_RESULT_MISMATCH|COMPLETED_ASSIGNMENT_REQUIRED'):
        wire.wrap_dynamic_realization(native)(bridge)
    assert outer._long_incidence_assignment_binding == old
