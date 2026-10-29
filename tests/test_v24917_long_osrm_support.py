"""LONG support uses fixed OSRM 9697, independently of native FineCDF skims."""
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_long_support_distance_v24917 as source
import r1_15a2_long_od_mask_v24917 as masks


def make_adapter(distance, zones=(11, 12), matrices=None):
    live = NS(distance=np.array(distance, dtype=float), zones=list(zones), code=source.MATRIX_CODE,
              no=9697, lookups=[], writes=[])
    class Matrix:
        def __init__(self, no): self.no = no
        def AttValue(self, attr):
            return {'NO': live.no, 'CODE': live.code}[attr]
        def GetValues(self):
            return live.distance if self.no == 9697 else matrices[self.no]
        def SetValues(self, *args): raise AssertionError('READ_ONLY_OSRM')
    class Matrices:
        def ItemByKey(self, no):
            live.lookups.append(no)
            if no != 9697 and (matrices is None or no not in matrices): raise KeyError(no)
            return Matrix(no)
    class Zones:
        def GetMultiAttValues(self, attr, active):
            assert attr == 'NO' and active is False
            return list(enumerate(live.zones, 1))
    adapter = NS(zones=list(zones), visum=NS(Net=NS(Matrices=Matrices(), Zones=Zones())),
                 com_retry_policy={'enabled': False})
    return adapter, live


def test_fixed_osrm_mask_does_not_require_native_assignment_epoch():
    adapter, live = make_adapter([[79.999, 80.], [200.001, 0.]])
    adapter.v24916_dynamic_skims = None
    result = masks.capture_current(adapter, {'dynamic_skim_epoch': {'epoch_hash': 'old'}})
    assert result['status'] == 'MASK_READY_NATIVE_FILTER_UNVERIFIED'
    assert result['source']['matrix_no'] == 9697
    assert result['source']['matrix_code'] == 'R1_OSRM_DIST_KM'
    assert result['source']['counts']['allowed_ge_min_km'] == 2
    assert result['source']['counts']['above_200_km_allowed'] == 1
    assert not result['source']['assignment_dependent']
    assert 'skim_epoch' not in result['source']
    assert live.lookups == [9697]
    assert not result['long_generation_permitted']  # source selection is not native enforcement


def test_source_is_owned_readonly_and_pinned_to_run():
    adapter, live = make_adapter([[0., 80.], [300., 0.]])
    distance, meta = source.read_current(adapter)
    assert not distance.flags.writeable and not np.shares_memory(distance, live.distance)
    source.read_current(adapter)
    live.distance[0, 1] = 79.
    with pytest.raises(ValueError, match='DISTANCE_CHANGED_DURING_RUN'):
        source.read_current(adapter)
    assert distance[0, 1] == 80.
    assert adapter._long_osrm_support_anchor == meta


@pytest.mark.parametrize('bad', [np.ones((2, 3)), [[0., -1.], [100., 0.]],
                                [[0., np.nan], [100., 0.]], [[0., np.inf], [100., 0.]]])
def test_invalid_osrm_distance_fails_closed(bad):
    adapter, _ = make_adapter(bad)
    with pytest.raises(ValueError, match='LONG_OSRM_DISTANCE'):
        source.read_current(adapter)
    assert not hasattr(adapter, '_long_osrm_support_anchor')


@pytest.mark.parametrize('field,value', [('code', 'DIS'), ('no', 9698), ('zones', [12, 11])])
def test_wrong_source_or_zone_axis_has_no_fallback(field, value):
    adapter, live = make_adapter([[0., 100.], [100., 0.]])
    setattr(live, field, value)
    result = masks.capture_current(adapter, {})
    assert result['status'] == 'INVALID_SOURCE'
    assert not result['long_generation_permitted']
    assert set(live.lookups) <= {9697}


def test_missing_osrm_matrix_never_uses_native_skim():
    adapter, _ = make_adapter([[0., 100.], [100., 0.]])
    def missing(no): raise KeyError(no)
    adapter.visum.Net.Matrices.ItemByKey = missing
    adapter.v24916_dynamic_skims = NS(require_current=lambda: NS(family_distance={'LONG': np.ones((2, 2))*200}))
    assert masks.capture_current(adapter, {})['status'] == 'INVALID_SOURCE'


def test_pure_mask_checks_source_hashes_and_thresholds():
    from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash
    d = np.array([[79.999, 80.], [200., 200.001]])
    args = dict(expected_values_sha256=matrix_values_hash(d),
                expected_zone_order_sha256=ordered_zone_hash([11, 12]))
    mask, summary = masks.build_osrm_support_mask(d, [11, 12], **args)
    np.testing.assert_array_equal(mask, [[False, True], [True, True]])
    assert not mask.flags.writeable and summary['above_200_km_permitted']
    with pytest.raises(ValueError, match='VALUES_HASH_MISMATCH'):
        masks.build_osrm_support_mask(d + 1., [11, 12], **args)
    with pytest.raises(ValueError, match='ZONE_ORDER_HASH_MISMATCH'):
        masks.build_osrm_support_mask(d, [12, 11], **args)


def test_directional_osrm_support_checks_symmetry_feasibility():
    adapter, _ = make_adapter([[0., 80.], [79.99, 0.]])
    d, meta = source.read_current(adapter)
    mask, _ = masks.build_osrm_support_mask(d, adapter.zones,
        expected_values_sha256=meta['values_sha256'], expected_zone_order_sha256=meta['zone_order_sha256'])
    margins = {no: {'production': [1., 0.], 'attraction': [0., 1.]} for no in masks.MATRIX_NOS}
    assert masks.check_restricted_pa_feasibility(mask, margins)['status'] == 'FEASIBLE'
    assert masks.check_restricted_pa_feasibility(mask, margins, symmetry_safe=True)['status'] == 'INFEASIBLE_PA'


@pytest.mark.parametrize('osrm,native,clean', [(79.999, 150., False), (80., 50., True), (99.999, 50., True)])
def test_live_guard_uses_osrm_not_native_distance_for_support(osrm, native, clean):
    import r1_15a2_long_distance_guard_v24917 as guard
    from r1_15a2_skim_v24916p2c import ordered_zone_hash
    matrices = {no: np.zeros((2, 2)) for no in guard.MATRIX_NOS}
    matrices[9111][0, 1] = 10.
    adapter, _ = make_adapter([[0., osrm], [201., 0.]], matrices=matrices)
    epoch = NS(family_distance={'LONG': np.array([[0., native], [201., 0.]])},
               matrix_meta_by_dseg={'NATIVE_CL': {'unit': 'km', 'values_sha256': 'native-hash'}},
               zone_order_sha256=ordered_zone_hash(adapter.zones), assignment_epoch=3,
               epoch=4, epoch_hash='current')
    adapter.v24916_dynamic_skims = NS(require_current=lambda: epoch)
    diag = {'dynamic_skim_epoch': {'epoch_hash': 'current'},
            'd11': {'summary': {'component_dist_summary_rows': [
                {'component': 'LONG_COMPOSITE', 'dynamic_fine_cdf_rmse': .1}]}}}
    proof = guard.capture(adapter, diag)
    assert proof['status'] == 'MEASURED'
    assert proof['support_clean'] is clean
    assert proof['support_distance_source']['matrix_no'] == 9697
    assert proof['epoch']['finecdf_native_cl_values_sha256'] == 'native-hash'
    if clean:
        assert proof['below_100_km'] == 10.  # diagnostic only, not a rejection
        assert proof['below_min_km'] == 0.
        assert guard.decide(proof, proof, changed_long=True)['passes']


def test_d4_factor_axis_and_exact_80_export(tmp_path):
    from tools.build_long_osrm_mask import read_d4, write_d4, build
    path = tmp_path / 'distance.mtx'
    # The D4 writer accepts numeric arrays; use half-distances and factor 2.
    write_d4(path, np.array([[0., 40.], [39., 100.]]), [3, 99], [])
    text = path.read_text(encoding='utf-8-sig').replace('* Factor\n1.00', '* Factor\n2.00')
    path.write_text(text, encoding='utf-8-sig')
    d, zones, _ = read_d4(path)
    np.testing.assert_array_equal(d, [[0., 80.], [78., 200.]])
    assert zones == [3, 99]
    report = build(path, tmp_path / 'out')
    assert report['exact_threshold_cells'] == 1
    assert report['export_readback_verified']
    exported, _, _ = read_d4(tmp_path / 'out' / report['output_file'])
    np.testing.assert_array_equal(exported, [[0., 1.], [0., 1.]])
