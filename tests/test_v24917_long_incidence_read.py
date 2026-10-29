"""Real bounded-export pipeline against COM-shaped read-only fixtures."""
import copy
import hashlib
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_long_incidence_read_v24917 as reader
import r1_15a2_long_profile_incidence_v24917 as pure
from r1_15a2_skim_v24916p2c import ordered_zone_hash
from test_v24917_long_profile_incidence import _fixture, _link
from test_v237_15p_bounded_offdiag_stream import BoundedHierarchical
from test_supply_visum_v22 import OfficialList


def harness():
    paths, links, profiles, zones, final, components = _fixture()
    # A real repeated traversal must include the return link between visits.
    links = [links[0], _link(1, 2, 1, 2, 10, 2, 1),
             dict(links[1], Index=3), dict(links[2], Index=4)] + links[3:]
    final[0, 0] = components[9291][0, 0] = 0.
    for i, profile in enumerate(profiles):
        profile['countlocation_no'] = 9001 + i
    state = NS(arrays={**components, 9305: final, 9697: np.array([[0., 80.], [250., 0.]])},
               paths=paths, links=links, exports=0, on_export=lambda: None,
               profile_flow={(1, 2): 160., (2, 3): 80., (3, 2): 70.},
               link_no={(1, 2): 10, (2, 3): 20, (3, 2): 20},
               zone_order=list(zones), parent={'state_hash': 'accepted'}, matrix_reads=[])
    class Matrix:
        def __init__(self, no): self.no = no
        def GetValues(self):
            state.matrix_reads.append(self.no)
            return state.arrays[self.no].copy()
        def AttValue(self, attr):
            return {'NO': self.no, 'SUM': state.arrays[self.no].sum(),
                    'CODE': 'R1_OSRM_DIST_KM' if self.no == 9697 else 'M%d' % self.no}[attr]
        def SetValues(self, *args): raise AssertionError('READ_ONLY_NO_MATRIX_WRITES')
    class Zones:
        def GetMultiAttValues(self, attr, active):
            assert attr == 'NO' and active is False
            return list(enumerate(state.zone_order, 1))
    class Link:
        def __init__(self, key): self.key = key
        def AttValue(self, attr):
            if attr == 'NO': return state.link_no[self.key]
            assert attr == 'VOLVEH_DSEG(NATIVE_CL,AP)'
            return state.profile_flow[self.key]
    class DS:
        ODMatrix = Matrix(9305)
        def AttValue(self, attr):
            return {'CODE': 'NATIVE_CL', 'NAME': 'LONG', 'MODE': 'PrT'}[attr]
    def make_links():
        state.exports += 1
        raw = [[r[k] for k in reader.rt.PATHLINK_KEY_HEADERS + reader.rt.PATHLINK_EXTRA_ATTRS]
               for r in state.links]
        obj = BoundedHierarchical(raw)
        invoke = obj._oleobj_.Invoke
        called = False
        def changed(*args):
            nonlocal called
            if not called:
                called = True
                state.on_export()
            return invoke(*args)
        obj._oleobj_.Invoke = changed
        state.last_bounded = obj
        return obj
    visum = NS(Net=NS(Matrices=NS(ItemByKey=Matrix), Zones=Zones(),
                     Links=NS(ItemByKey=lambda fr, to: Link((fr, to))),
                     DemandSegments=NS(GetAll=[DS()])),
               Workbench=NS(Lists=NS(
                   CreatePrTPathList=lambda: OfficialList('paths', state.paths, state.links),
                   CreatePrTPathLinkList=make_links)))
    adapter = NS(visum=visum, zones=list(zones), com_retry_policy={'enabled': False},
                 cfg={'path_export_dsegs': ['NATIVE_CW'], 'mutable_dsegs': ['NATIVE_CW'],
                      'pathlink_page_size': 2, 'com_resilience': {'enabled': False},
                      'api_approved_observations': [
                          {'no': 9001, 'role': 'CALIBRATION', 'edge_key': [10, 1, 2], 'direction': 'DIRECTED'},
                          {'no': 9002, 'role': 'CALIBRATION', 'edge_key': [20, 2, 3], 'direction': 'BOTH'}]},
                 generation_guard_snapshot=lambda: copy.deepcopy(state.parent),
                 readback_manager=NS(assignment_completed=True, assignment_in_progress=False,
                                     assignment_epoch=3, mutation_epoch=5))
    state.epoch = NS(assignment_epoch=3, epoch_hash='skim3', assignment_token='assignment3',
                     zone_order_sha256=ordered_zone_hash(zones))
    adapter.v24916_dynamic_skims = NS(require_current=lambda: state.epoch)
    reader.bind_after_assignment(adapter)
    return adapter, state, profiles


def test_actual_bounded_export_parity_archive_and_no_model_writes(tmp_path):
    adapter, state, profiles = harness()
    cfg = copy.deepcopy(adapter.cfg)
    before = {no: a.copy() for no, a in state.arrays.items()}
    result = reader.read_current(adapter, profiles, tmp_path)
    assert state.exports == 1 and state.last_bounded.unbounded_calls == 0
    assert state.last_bounded._oleobj_.calls == [(1, 2), (3, 4), (5, 6), (7, 8)]
    assert result['source_status'] == 'CURRENT_ADAPTER_ASSIGNMENT_READ_AND_PARITY_CHECKED'
    assert result['profile_long_vehicle_flow'] == pytest.approx([160., 150.])
    assert not result['long_generation_permitted'] and not result['tg_sensitivity_verified']
    assert result['component_profile_vehicle_flow']['9291'] == pytest.approx([96., 70.])
    report = json.loads((tmp_path/'LONG_INCIDENCE_REPORT.json').read_text())
    assert report['maximum_osrm_km'] is None and report['minimum_osrm_km'] == 80.
    assert report['archive_sha256'] == hashlib.sha256((tmp_path/'LONG_INCIDENCE.npz').read_bytes()).hexdigest()
    with np.load(tmp_path/'LONG_INCIDENCE.npz', allow_pickle=False) as archive:
        assert archive['profile_identity'].tolist() == ['9001', '9002']
        reconstructed = np.bincount(archive['row'], weights=archive['value'], minlength=2)
        np.testing.assert_array_equal(reconstructed, archive['profile_flow'])
        np.testing.assert_array_equal(archive['component_vehicle_od'].sum(axis=0), archive['q_current'])
    for no, a in before.items(): np.testing.assert_array_equal(state.arrays[no], a)
    assert adapter.cfg == cfg  # CL never becomes a mutable W/S path segment
    assert not (tmp_path/'LONG_INCIDENCE_FAILURE.json').exists()


@pytest.mark.parametrize('change,reason', [
    (lambda a, s: setattr(a.readback_manager, 'mutation_epoch', 6), 'BINDING_STALE'),
    (lambda a, s: setattr(a.readback_manager, 'assignment_epoch', 4), 'EPOCH_MISMATCH'),
    (lambda a, s: setattr(a.readback_manager, 'assignment_in_progress', True), 'COMPLETED_ASSIGNMENT'),
    (lambda a, s: setattr(a, '_long_incidence_assignment_binding', None), 'BINDING_STALE'),
])
def test_stale_missing_or_in_progress_binding_rejected_before_export(tmp_path, change, reason):
    adapter, state, profiles = harness()
    change(adapter, state)
    with pytest.raises(ValueError, match=reason): reader.read_current(adapter, profiles, tmp_path)
    assert state.exports == 0


@pytest.mark.parametrize('change,reason', [
    (lambda a, s: s.arrays[9291].__setitem__((0, 1), 61.), 'OD_CHANGED_DURING_EXPORT'),
    (lambda a, s: s.profile_flow.__setitem__((1, 2), 161.), 'FLOW_CHANGED_DURING_EXPORT'),
    (lambda a, s: s.parent.update(state_hash='different'), 'MODEL_CHANGED_DURING_EXPORT'),
    (lambda a, s: s.arrays[9697].__setitem__((0, 1), 81.), 'DISTANCE_CHANGED_DURING_RUN'),
    (lambda a, s: setattr(a.readback_manager, 'mutation_epoch', 6), 'BINDING_STALE'),
    (lambda a, s: setattr(s.epoch, 'epoch_hash', 'newskim'), 'BINDING_STALE'),
    (lambda a, s: s.zone_order.reverse(), 'ZONE_ORDER_CHANGED'),
])
def test_drift_during_stream_discards_success_evidence(tmp_path, change, reason):
    adapter, state, profiles = harness()
    state.on_export = lambda: change(adapter, state)
    with pytest.raises(ValueError, match=reason): reader.read_current(adapter, profiles, tmp_path)
    assert not (tmp_path/'LONG_INCIDENCE_REPORT.json').exists()
    assert not (tmp_path/'LONG_INCIDENCE.npz').exists()
    assert json.loads((tmp_path/'LONG_INCIDENCE_FAILURE.json').read_text())['status'] == 'FAILED_READ_ONLY'


def test_component_od_path_od_profile_and_support_gates(tmp_path):
    for case, reason in [('component', 'COMPONENT_TO_FINAL_OD_MISMATCH'),
                         ('path', 'parity rejected'), ('profile', 'PROFILE_FLOW_PARITY_FAILED'),
                         ('support', 'OSRM_SUPPORT_NOT_APPLIED')]:
        adapter, state, profiles = harness()
        if case == 'component': state.arrays[9291][0, 1] += 1.
        if case == 'path': state.paths[0]['Vol(AP)'] -= 1.
        if case == 'profile': state.profile_flow[(1, 2)] += 1.
        if case == 'support': state.arrays[9697][0, 1] = 79.999
        with pytest.raises((ValueError, RuntimeError), match=reason):
            reader.read_current(adapter, profiles, tmp_path/case)
        assert not (tmp_path/case/'LONG_INCIDENCE_REPORT.json').exists()


def test_roster_scope_and_direction_cannot_be_substituted(tmp_path):
    adapter, state, profiles = harness()
    with pytest.raises(ValueError, match='PROFILE_SCOPE_MISMATCH'):
        reader.read_current(adapter, profiles[:1], tmp_path)
    profiles[1]['observation_direction'] = 'DIRECTED'
    with pytest.raises(ValueError, match='DIRECTION_AUTHORITY_MISMATCH'):
        reader.read_current(adapter, profiles, tmp_path)
    assert state.exports == 0


def test_export_is_fresh_each_call_and_previous_evidence_is_preserved(tmp_path):
    adapter, state, profiles = harness()
    reader.read_current(adapter, profiles, tmp_path/'first')
    before = (tmp_path/'first'/'LONG_INCIDENCE_REPORT.json').read_bytes()
    with pytest.raises(ValueError, match='FRESH_OUTPUT_DIRECTORY'):
        reader.read_current(adapter, profiles, tmp_path/'first')
    # end_candidate clears its own flag, not the recorded completed assignment.
    adapter.readback_manager.assignment_completed = False
    reader.read_current(adapter, profiles, tmp_path/'second')
    assert state.exports == 2
    assert (tmp_path/'first'/'LONG_INCIDENCE_REPORT.json').read_bytes() == before


def test_archive_failure_cannot_publish_pass(tmp_path, monkeypatch):
    adapter, _, profiles = harness()
    def fail(*args, **kwargs): raise OSError('DISK_FULL')
    monkeypatch.setattr(reader.np, 'savez_compressed', fail)
    with pytest.raises(OSError, match='DISK_FULL'): reader.read_current(adapter, profiles, tmp_path)
    assert not (tmp_path/'LONG_INCIDENCE_REPORT.json').exists()
    assert not list(tmp_path.glob('*.npz*'))


def test_real_adapter_entry_points_bind_after_skims_and_export(tmp_path, monkeypatch):
    import r1_15a2_trial_adapter_v24917 as module
    fixture, state, profiles = harness()
    adapter = object.__new__(module.VisumAdapter)
    adapter.__dict__.update(vars(fixture))
    monkeypatch.setattr(module._V24916ActiveAdapter, '_refresh_dynamic_skims_after_assignment',
                        lambda self, *args, **kwargs: state.epoch)
    assert module.VisumAdapter._refresh_dynamic_skims_after_assignment(adapter, tmp_path, 'FULL') is state.epoch
    result = module.VisumAdapter.long_profile_incidence(adapter, {'d12': {'rows': profiles}}, tmp_path/'audit')
    assert result['assignment_binding']['assignment_epoch'] == 3
    monkeypatch.setattr(module._V24916ActiveAdapter, '_refresh_dynamic_skims_after_assignment',
                        lambda *args, **kwargs: None)
    module.VisumAdapter._refresh_dynamic_skims_after_assignment(adapter, tmp_path, 'FULL')
    assert adapter._long_incidence_assignment_binding is None


def test_pure_duplicate_export_rows_rejected_but_repeated_link_traversal_allowed():
    paths, links, profiles, zones, final, components = _fixture()
    assert pure.build_observed_long_incidence(paths, iter(links), profiles, zones, final, components)[
        'profile_long_vehicle_flow'][0] == 160.
    with pytest.raises(ValueError, match='DUPLICATE_PATH_KEY'):
        pure.build_observed_long_incidence(paths + [dict(paths[0], **{'Vol(AP)': 0.})],
                                          links, profiles, zones, final, components)
    with pytest.raises(ValueError, match='DUPLICATE_PROFILE_PATHLINK_POSITION'):
        pure.build_observed_long_incidence(paths, links + [links[0]], profiles, zones, final, components)


def test_positive_tiny_od_is_not_silently_dropped():
    paths, links, profiles, zones, final, components = _fixture()
    final[1, 0] = 1.e-7
    components[9291][1, 0] = 1.e-7
    components[9292][1, 0] = 0.
    paths[2]['Vol(AP)'] = 1.e-7
    result = pure.build_observed_long_incidence(paths, links, profiles, zones, final, components)
    assert len(result['variables']) == 2
    assert result['variables'][1]['q_current'] == 1.e-7
    assert result['incidence'].forward(np.ones(2))[1] == pytest.approx(100.0000001, abs=1.e-10)


def test_tiny_positive_od_still_requires_path_and_link_evidence():
    paths, links, profiles, zones, final, components = _fixture()
    final[1, 0] = components[9291][1, 0] = 1.e-7
    components[9292][1, 0] = 0.
    with pytest.raises(ValueError, match='PATH_TO_FINAL_OD_MISMATCH'):
        pure.build_observed_long_incidence(paths[:2], links[:4], profiles, zones, final, components)
    paths[2]['Vol(AP)'] = 1.e-7
    with pytest.raises(ValueError, match='POSITIVE_PATH_WITHOUT_LINKS'):
        pure.build_observed_long_incidence(paths, links[:4], profiles, zones, final, components)


def test_path_keys_and_even_tiny_negative_volumes_must_be_valid():
    paths, links, profiles, zones, final, components = _fixture()
    bad = [dict(paths[0], OrigZoneNo=1.4)] + paths[1:]
    with pytest.raises(RuntimeError, match='NONINTEGRAL_ID'):
        pure.build_observed_long_incidence(bad, links, profiles, zones, final, components)
    bad = [dict(paths[0], **{'Vol(AP)': -1.e-14})] + paths[1:]
    with pytest.raises(ValueError, match='INVALID_PATH_ROWS'):
        pure.build_observed_long_incidence(bad, links, profiles, zones, final, components)
