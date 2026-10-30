"""Real dynamic 11D producer -> separate composite -> guarded LONG Generation."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_dynamic_11d_files_v24917 as files
import r1_15a2_finecdf_bridge_v24916 as bridge
import r1_15a2_long_composite_diagnostic_v24917 as composite
import r1_15a2_long_distance_guard_v24917 as guard
import r1_15a2_parent_equivalence_v24917 as equivalence
from r1_15a2_dynamic_skim_v24916p2c import SCHEMA, REQUIRED_NATIVE_DSEGS, _hash
from r1_15a2_skim_v24916p2c import ordered_zone_hash
from r1_15a2_path_incidence_v24917 import matrix_values_hash
from test_v24917_long_osrm_support import make_adapter
from test_v24917_long_cache_generation import live, problem

ROOT = Path(__file__).resolve().parents[1]


def reference():
    cfg = json.loads((ROOT / 'R1_15A2_CONFIG_V2_4_9_15_PERF2.json').read_text())
    ref, _, sha = bridge.load_reference(ROOT, cfg['coupled_demand']['finecdf_td'])
    return ref, cfg, sha


def bind_diagnostic(adapter, epoch, matrices, rows=None):
    """Small live-source fixture with the real sealed target and metric math."""
    ref, cfg, sha = reference()
    adapter.cfg = dict(getattr(adapter, 'cfg', {}), coupled_demand=cfg['coupled_demand'])
    adapter._v24916_package_root = ROOT
    n = len(adapter.zones)
    native = epoch.family_distance['LONG']
    epoch.assignment_token = 'assignment-' + str(epoch.assignment_epoch)
    epoch.zone_order_sha256 = ordered_zone_hash(adapter.zones)
    epoch.family_hashes = {family: matrix_values_hash(native) for family in ('WORK', 'SERVICE', 'LONG', 'FOREIGN')}
    epoch.matrix_meta_by_dseg = {code: {'matrix_no': 700 + i, 'matrix_code': 'DIS', 'unit': 'km',
        'dseg_code': code, 'canonical_dseg': code, 'shape': [n, n], 'values_sha256': matrix_values_hash(native)}
        for i, code in enumerate(REQUIRED_NATIVE_DSEGS)}
    payload = {'schema': SCHEMA, 'epoch': epoch.epoch, 'assignment_epoch': epoch.assignment_epoch,
        'assignment_token': epoch.assignment_token, 'zone_order_sha256': epoch.zone_order_sha256,
        'operation_positions': list(range(31, 37)),
        'matrix_hashes': {k: v['values_sha256'] for k, v in epoch.matrix_meta_by_dseg.items()},
        'family_hashes': epoch.family_hashes}
    epoch.epoch_hash = _hash(payload)
    authority = {k: v for k, v in payload.items() if k != 'matrix_hashes'}
    authority.update(matrix_meta_by_dseg=epoch.matrix_meta_by_dseg, epoch_hash=epoch.epoch_hash,
        role='ACTIVE_TD_CALIBRATION_DISTANCE_AUTHORITY', source='VISUM_FRESH_ASSIGNMENT_PATHS_PRT_DIS',
        static_r1_osrm_dist_km_role='REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION')
    epoch.summary = lambda: copy.deepcopy(authority)
    adapter.v24916_dynamic_skims = NS(require_current=lambda: epoch)
    metric = bridge.DynamicFamilyMetrics(NS(dynamic_skim_epoch=epoch), ref)._evaluate_one(
        'LONG_COMPOSITE', native, matrices)
    metric.update(distance_authority='DYNAMIC_ASSIGNMENT_DIS_KM', dynamic_distance_family='LONG',
        dynamic_skim_epoch=epoch.epoch, dynamic_skim_epoch_hash=epoch.epoch_hash)
    record = composite.make_record(metric, epoch, ref, sha)
    rows = rows if rows is not None else [{'component': r['component']} for r in ref.COMPONENTS]
    summary = {'component_dist_summary_rows': rows, 'dynamic_distance_authority': epoch.summary(),
        composite.KEY: record,
        'dist_classification_matrix': {'code': 'VISUM_DYNAMIC_ASSIGNMENT_DIS_KM',
            'classification': 'DYNAMIC_ASSIGNMENT_PATH_VOLUME_WEIGHTED_DIS',
            'assignment_epoch': epoch.assignment_epoch, 'skim_epoch': epoch.epoch,
            'skim_epoch_hash': epoch.epoch_hash, 'zone_order_sha256': epoch.zone_order_sha256,
            'family_hashes': dict(epoch.family_hashes)}}
    return {'d11': {'summary': summary}, 'dynamic_skim_epoch': epoch.summary(),
            'dynamic_11d_reference_sha256': sha}


def harness():
    matrices = {no: np.array([[0., 2.], [3., 0.]]) for no in guard.MATRIX_NOS}
    adapter, live = make_adapter([[0., 85.], [220., 0.]], matrices=matrices)
    epoch = NS(family_distance={'LONG': np.array([[0., 120.], [150., 0.]])}, assignment_epoch=7, epoch=8)
    diag = bind_diagnostic(adapter, epoch, matrices)
    return adapter, live, epoch, matrices, diag


def test_17_atomic_rows_and_separate_composite_unlock_generation():
    adapter, _, epoch, matrices, diag = harness()
    assert len(diag['d11']['summary']['component_dist_summary_rows']) == 17
    assert 'LONG_COMPOSITE' not in {r['component'] for r in diag['d11']['summary']['component_dist_summary_rows']}
    proof = guard.capture(adapter, diag)
    assert proof['support_clean'] and proof['fine_cdf_verified'] and proof['long_generation_permitted']
    assert guard.decide(proof, proof, changed_long=True)['passes']


def test_verified_diagnostic_reaches_real_shared_cache_zonal_solver(live, monkeypatch):
    import r1_15a2_core as core
    import r1_15a2_long_cache_generation_v24917 as cache
    import r1_15a2_long_incidence_read_v24917 as reader
    import r1_15a2_long_school_generation_v24917 as generation
    from test_v24917_mobilityzone1 import authority, zones as mobility_rows
    adapter, state, profiles = live
    for no in guard.MATRIX_NOS:
        state.arrays[no] = np.array([[0., 10.], [20., 0.]])
    epoch = state.epoch
    epoch.epoch = 4
    epoch.family_distance = {'LONG': np.array([[0., 120.], [150., 0.]])}
    diag = bind_diagnostic(adapter, epoch, {no: state.arrays[no] for no in guard.MATRIX_NOS})
    reader.bind_after_assignment(adapter)
    proof = guard.capture(adapter, diag)
    assert proof['long_generation_permitted'], proof
    observed = cache.capture(adapter)
    monkeypatch.setattr(generation, 'ls_options', lambda: dict(generation.LS_DEFAULTS))
    state.arrays[9225] = np.zeros((2, 2))
    state.arrays[9226] = np.ones((2, 2))
    inc = {'variables': [], 'incidence': core.SparseOperator(
        np.array([], dtype=int), np.array([], dtype=int), np.array([]), 2, 0)}
    result = generation.design(adapter.visum, {'max_add_log_up': .5, 'max_add_log_down': .5},
        adapter.zones, inc, problem(profiles), {'predicted_change': np.zeros(2)},
        {'ADD_ATT_L': {'1': 1., '2': 1.}},
        {'longguard1_allow_long': proof['long_generation_permitted'], 'long_cache_incidence': observed,
         'long_mobility_authority': authority(mobility_rows()), 'max_iter': 2000})
    rows = generation.rows_at_scale(result, 1.)
    assert rows and {row['attr'] for row in rows} <= {'ADD_PROD_L', 'ADD_ATT_L'}
    assert any(row['proposed'] != row['current'] for row in rows)
    assert state.exports == 0 and state.writes == []


def test_real_inherited_overlay_publishes_composite_without_second_od_read(monkeypatch, tmp_path):
    # Launcher tests intentionally replace sys.modules. Patch the same current
    # module instances as the current adapter's real inherited method uses.
    import importlib
    files = importlib.import_module('r1_15a2_dynamic_11d_files_v24917')
    bridge = importlib.import_module('r1_15a2_finecdf_bridge_v24916')
    import r1_15a2_supply_visum as supply
    from r1_15a2_trial_adapter_v24917 import VisumAdapter
    ref, cfg, sha = reference()
    n = 2
    matrices = {int(r['matrix_no']): np.array([[0., 2.], [3., 0.]]) for r in ref.COMPONENTS}
    adapter, live = make_adapter([[0., 85.], [220., 0.]], matrices=matrices)
    epoch = NS(family_distance={'LONG': np.array([[0., 120.], [150., 0.]])}, assignment_epoch=7, epoch=8)
    original = bind_diagnostic(adapter, epoch, matrices)
    epoch.family_distance.update(WORK=np.array([[0., 20.], [30., 0.]]),
                                SERVICE=np.array([[0., 25.], [35., 0.]]))
    host = object.__new__(VisumAdapter)
    host.__dict__.update(adapter.__dict__)
    host.cfg, host._v24916_package_root = cfg, ROOT
    static = tmp_path / 'STATIC'; static.mkdir()
    for suffix in files.SUFFIXES.values():
        files.rt.write_csv(static / (files.rt.D11_PREFIX + suffix),
                           [{'component': 'WORK_E_C', 'bin_low': .1, 'bin_high': 1.}])
    summary_path = static / 'SUMMARY.json'; summary_path.write_text('{}')
    initial = {'d11': {'summary': {'component_dist_summary_rows': original['d11']['summary']['component_dist_summary_rows']},
                      'summary_path': str(summary_path)}, 'd12': {}}
    monkeypatch.setattr(files, 'new_short_folder', lambda: tmp_path / 'SHORT')
    monkeypatch.setattr(files.rt, 'assess_11d_idp_gate', lambda *a: {'passes': True})
    monkeypatch.setattr(supply.base, 'build_td_signals_from_11d', lambda *a: ({}, 'fixture'))
    evaluate = bridge.DynamicFamilyMetrics.evaluate
    def capturing(self, values):
        out = evaluate(self, values); files.record_metrics(self, out); return out
    monkeypatch.setattr(bridge.DynamicFamilyMetrics, 'evaluate', capturing)
    result = host._dynamic_11d_overlay(initial, tmp_path / 'RUN', 'AFTER')
    summary = result['d11']['summary']
    assert len(summary['component_dist_summary_rows']) == 17
    assert not any(r['component'] == 'LONG_COMPOSITE' for r in summary['component_dist_summary_rows'])
    assert summary[composite.KEY]['status'] == 'VERIFIED'
    assert result['v24917_dynamic_11d_files']['verified_metrics_reused']
    needed = {int(no) for t in ref.TARGETS.values() for no in t['matrix_nos']}
    assert sorted(live.lookups) == sorted(needed)
    assert json.loads(Path(result['d11']['summary_path']).read_text())[composite.KEY] == summary[composite.KEY]
    proof = guard.capture(host, result)
    assert proof['long_generation_permitted'], proof
    assert not live.writes


@pytest.mark.parametrize('damage', ['missing', 'legacy_row', 'epoch', 'assignment', 'token', 'zone', 'cl_hash',
    'family_hash', 'reference', 'target', 'matrix_scope', 'interval', 'points', 'nan', 'bool', 'value',
    'source_volume', 'source_shape', 'source_status'])
def test_missing_stale_or_forged_evidence_cannot_unlock(damage):
    adapter, _, epoch, matrices, diag = harness()
    record = diag['d11']['summary'][composite.KEY]
    if damage == 'missing': del diag['d11']['summary'][composite.KEY]
    elif damage == 'legacy_row':
        del diag['d11']['summary'][composite.KEY]
        diag['d11']['summary']['component_dist_summary_rows'].append(
            {'component': 'LONG_COMPOSITE', 'dynamic_fine_cdf_rmse': .01})
    elif damage == 'epoch': record['dynamic_skim_epoch_hash'] = '0' * 64
    elif damage == 'assignment': record['assignment_epoch'] += 1
    elif damage == 'token': record['assignment_token'] = 'other'
    elif damage == 'zone': record['zone_order_sha256'] = '0' * 64
    elif damage == 'cl_hash': record['native_cl_values_sha256'] = '0' * 64
    elif damage == 'family_hash': record['family_distance_sha256'] = '0' * 64
    elif damage == 'reference': record['reference_sha256'] = '0' * 64
    elif damage == 'target': record['target_sha256'] = '0' * 64
    elif damage == 'matrix_scope': record['matrix_nos'] = [9111]
    elif damage == 'interval': record['conditional_km'] = [80., 200.]
    elif damage == 'points': record['fine_points'] = 511
    elif damage == 'nan': record['fine_cdf_rmse'] = float('nan')
    elif damage == 'bool': record['fine_cdf_rmse'] = True
    elif damage == 'value': record['fine_cdf_rmse'] = .0001
    elif damage == 'source_volume': matrices[9111][0, 1] += 10.
    elif damage == 'source_shape': matrices[9111] = np.ones((1, 1))
    elif damage == 'source_status': record['status'] = 'UNVERIFIED'
    proof = guard.capture(adapter, diag)
    assert not proof['long_generation_permitted']
    assert not proof.get('fine_cdf_verified')


def test_valid_composite_still_rejects_short_osrm_support():
    adapter, live, _, _, diag = harness()
    live.distance[0, 1] = 79.
    proof = guard.capture(adapter, diag)
    assert proof['fine_cdf_verified'] and not proof['support_clean']
    assert not proof['long_generation_permitted']


def test_new_assignment_same_content_is_rollback_equivalent():
    adapter, _, epoch, matrices, before = harness()
    epoch.assignment_epoch += 1; epoch.epoch += 1
    after = bind_diagnostic(adapter, epoch, matrices)
    errors = []
    a = equivalence._dynamic_summary(before, errors, 'before')
    b = equivalence._dynamic_summary(after, errors, 'after')
    assert errors == []
    assert a == b


@pytest.mark.parametrize('field', ['fine_cdf_rmse', 'native_cl_values_sha256', 'dynamic_skim_epoch_hash'])
def test_rollback_composite_validation_never_hides_change(field):
    _, _, _, _, before = harness()
    after = copy.deepcopy(before)
    record = after['d11']['summary'][composite.KEY]
    record[field] = .001 if field == 'fine_cdf_rmse' else '0' * 64
    errors = []
    a = equivalence._dynamic_summary(before, errors, 'before')
    b = equivalence._dynamic_summary(after, errors, 'after')
    assert errors or a != b
