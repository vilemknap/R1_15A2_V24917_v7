"""Separate, epoch-bound LONG FineCDF evidence; never an eighteenth 11D row.

The producer reuses the existing pure DynamicFamilyMetrics result. LONGGUARD1
verifies it against the current five arrays it already reads for support. No
additional COM read, demand write, target change or relaxed gate is introduced.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
import numpy as np

from r1_15a2_supply import canonical_hash

KEY = 'long_composite_dynamic'
SCHEMA = 'R1_V24917_LONG_COMPOSITE_DYNAMIC_DIAGNOSTIC_V1'
EXECUTION_KEYS = ('assignment_epoch', 'dynamic_skim_epoch', 'dynamic_skim_epoch_hash', 'assignment_token')


def _require(ok, code):
    if not ok:
        raise ValueError('LONG_COMPOSITE_DIAGNOSTIC_' + code)


def _same(a, b):
    return a == b and canonical_hash(a) == canonical_hash(b)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def target_contract(ref):
    from r1_15a2_long_distance_guard_v24917 import MATRIX_NOS, MIN_CDF_KM, MAX_CDF_KM
    target = ref.TARGETS['LONG_COMPOSITE']
    fine = ref.FINE_AUTHORITY['targets']['LONG_COMPOSITE']
    grid = np.asarray(ref.FINE_AUTHORITY['common_grid_%s_km' % fine['grid']], dtype=float)
    goal = np.asarray(fine['cdf'], dtype=float)
    _require(list(target['matrix_nos']) == list(MATRIX_NOS), 'MATRIX_SCOPE')
    _require(grid.shape == goal.shape == (512,) and np.isfinite(grid).all()
             and np.isfinite(goal).all() and np.all(np.diff(grid) > 0)
             and grid[0] == MIN_CDF_KM and grid[-1] == MAX_CDF_KM
             and target['edges'][0] == MIN_CDF_KM and target['edges'][-1] == MAX_CDF_KM,
             'TARGET_GRID')
    return grid, goal, canonical_hash({'grid_km': grid.tolist(), 'target_cdf': goal.tolist()})


def _binding(authority):
    meta = authority['matrix_meta_by_dseg']['NATIVE_CL']
    result = {
        'assignment_epoch': authority['assignment_epoch'], 'dynamic_skim_epoch': authority['epoch'],
        'dynamic_skim_epoch_hash': authority['epoch_hash'], 'assignment_token': authority['assignment_token'],
        'zone_order_sha256': authority['zone_order_sha256'], 'native_cl_matrix_no': meta['matrix_no'],
        'native_cl_values_sha256': meta['values_sha256'], 'family_distance_sha256': authority['family_hashes']['LONG']}
    _require(meta.get('unit') == 'km' and str(meta.get('matrix_code', '')).upper() == 'DIS', 'NATIVE_CL_UNIT_OR_CODE')
    for name in ('assignment_epoch', 'dynamic_skim_epoch', 'native_cl_matrix_no'):
        _require(type(result[name]) is int and result[name] > 0, 'INVALID_' + name.upper())
    for name in ('dynamic_skim_epoch_hash', 'zone_order_sha256', 'native_cl_values_sha256', 'family_distance_sha256'):
        _require(_sha(result[name]), 'INVALID_' + name.upper())
    _require(isinstance(result['assignment_token'], str) and bool(result['assignment_token']), 'ASSIGNMENT_TOKEN')
    return result


def make_record(metric, epoch, ref, reference_sha):
    from r1_15a2_long_distance_guard_v24917 import MATRIX_NOS, MIN_CDF_KM, MAX_CDF_KM
    _require(_sha(reference_sha), 'REFERENCE_SHA')
    grid, goal, target_sha = target_contract(ref)
    model = np.asarray(metric['fine_model_cdf'], dtype=float)
    _require(model.shape == goal.shape and np.isfinite(model).all()
             and np.all(model >= -1e-12) and np.all(model <= 1 + 1e-12)
             and np.all(np.diff(model) >= -1e-12) and abs(float(model[-1]) - 1.) < 1e-8, 'MODEL_CDF')
    actual_rmse = float(np.sqrt(np.mean((model - goal) ** 2)))
    _require(not isinstance(metric['fine_cdf_rmse'], bool)
             and math.isclose(float(metric['fine_cdf_rmse']), actual_rmse, rel_tol=1e-12, abs_tol=1e-12), 'RMSE')
    binding = _binding(epoch.summary())
    _require(metric.get('distance_authority') == 'DYNAMIC_ASSIGNMENT_DIS_KM'
             and metric.get('dynamic_distance_family') == 'LONG'
             and _same(metric.get('dynamic_skim_epoch'), binding['dynamic_skim_epoch'])
             and metric.get('dynamic_skim_epoch_hash') == binding['dynamic_skim_epoch_hash'], 'METRIC_EPOCH')
    record = {'schema': SCHEMA, 'status': 'VERIFIED', 'component': 'LONG_COMPOSITE',
        'matrix_nos': list(MATRIX_NOS), 'distance_authority': 'DYNAMIC_ASSIGNMENT_DIS_KM',
        'dynamic_distance_family': 'LONG', 'reference_sha256': reference_sha,
        'target_sha256': target_sha, 'fine_points': len(grid), 'conditional_km': [MIN_CDF_KM, MAX_CDF_KM],
        'fine_cdf_rmse': actual_rmse, 'conditioned_volume': float(metric['conditioned_volume_diagnostic']),
        'total_volume': float(metric['total_volume_diagnostic']), **binding}
    validate(record, epoch.summary(), reference_sha=reference_sha, target_sha=target_sha)
    return record


def validate(record, authority, *, reference_sha=None, target_sha=None):
    from r1_15a2_long_distance_guard_v24917 import MATRIX_NOS, MIN_CDF_KM, MAX_CDF_KM
    _require(isinstance(record, Mapping) and record.get('schema') == SCHEMA
             and record.get('status') == 'VERIFIED' and record.get('component') == 'LONG_COMPOSITE', 'SCHEMA_OR_STATUS')
    _require(_same(record.get('matrix_nos'), list(MATRIX_NOS)) and record.get('fine_points') == 512
             and _same(record.get('conditional_km'), [MIN_CDF_KM, MAX_CDF_KM])
             and record.get('distance_authority') == 'DYNAMIC_ASSIGNMENT_DIS_KM'
             and record.get('dynamic_distance_family') == 'LONG', 'METRIC_SCOPE')
    for key, expected in _binding(authority).items():
        _require(_same(record.get(key), expected), 'STALE_' + key.upper())
    for key, expected in (('reference_sha256', reference_sha), ('target_sha256', target_sha)):
        _require(_sha(record.get(key)) and (expected is None or record[key] == expected), key.upper())
    for key in ('fine_cdf_rmse', 'conditioned_volume', 'total_volume'):
        value = record.get(key)
        _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), 'NUMERIC_' + key.upper())
    _require(0 <= record['fine_cdf_rmse'] <= 1 and 0 < record['conditioned_volume']
             <= record['total_volume'] * (1 + 1e-12), 'MASS_OR_RMSE_RANGE')
    return float(record['fine_cdf_rmse'])


def verify_current(adapter, diag, epoch, matrices):
    """Require published evidence AND independently verify its current inputs.

    Arrays were already read by LONGGUARD1. Recomputing one NumPy target avoids
    trusting a bare verified flag or stale diagnostics under a reused epoch ID.
    """
    from types import SimpleNamespace
    from r1_15a2_finecdf_bridge_v24916 import load_reference, DynamicFamilyMetrics
    record = (((diag or {}).get('d11') or {}).get('summary') or {}).get(KEY)
    fine = (getattr(adapter, 'cfg', {}).get('coupled_demand') or {}).get('finecdf_td') or {}
    root = getattr(adapter, '_v24916_package_root', None)
    _require(root is not None and fine.get('reference_sha256'), 'REFERENCE_AUTHORITY_MISSING')
    ref, _, sha = load_reference(root, fine)
    _, _, target_sha = target_contract(ref)
    value = validate(record, epoch.summary(), reference_sha=sha, target_sha=target_sha)
    evaluator = DynamicFamilyMetrics(SimpleNamespace(dynamic_skim_epoch=epoch), ref)
    actual = evaluator._evaluate_one('LONG_COMPOSITE', epoch.family_distance['LONG'], matrices)
    for key, field in (('fine_cdf_rmse', 'fine_cdf_rmse'), ('conditioned_volume', 'conditioned_volume_diagnostic'),
                       ('total_volume', 'total_volume_diagnostic')):
        _require(math.isclose(record[key], float(actual[field]), rel_tol=1e-12, abs_tol=1e-10), 'CURRENT_INPUTS_' + key.upper())
    _require(adapter.v24916_dynamic_skims.require_current() is epoch, 'EPOCH_CHANGED_DURING_VERIFICATION')
    return value
