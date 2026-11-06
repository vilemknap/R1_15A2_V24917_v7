"""Sixteen native TD inputs: a shared M9002 base plus owned skim corrections.

Setup is explicit; runtime never creates matrices or changes utility bindings.
Only these utility inputs may be written here, never demand/skim source matrices.
Their off-diagonals stay fixed during inner b/c and intrazonal searches.
"""
from collections import OrderedDict
import copy
import functools
from pathlib import Path

import numpy as np

import r1_15a2_core as core
import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt
import r1_15a2_snapshot_reads_v24917 as snapshot_reads
import r1_15a2_visum_parameters as vp
from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash
from r1_15a2_supply import SupplyContractError, canonical_hash

RELEASE = 'R1_COMPONENT_TD_UTILITIES_20261106'
SNAPSHOT_KEY = 'v24917_component_td_utilities'
SETUP_SCRIPT = 'R1_CREATE_COMPONENT_TD_UTILITIES.py'
MAPPING = tuple(dict(component=component, utility_no=9700 + i,
                     utility_code='R1_TD_U_' + component,
                     **reg) for i, (component, reg) in enumerate(mb.COMPONENT_REGISTRY.items()))
UTILITY_NOS = tuple(row['utility_no'] for row in MAPPING)
SOURCES = {'WORK': ('NATIVE_CW', 'NATIVE_CW_NOT'),
           'SERVICE': ('NATIVE_CS', 'NATIVE_CS_NOT'),
           'LONG': ('NATIVE_CL',),
           'SCHOOL': ('NATIVE_CW', 'NATIVE_CW_NOT')}
FLOW_NOS = {'NATIVE_CW': 9301, 'NATIVE_CW_NOT': 9302,
            'NATIVE_CS': 9303, 'NATIVE_CS_NOT': 9304}
REQUIRED_DSEGS = tuple(dict.fromkeys(d for ds in SOURCES.values() for d in ds))
UTIL_NAMES = ('UTILITYFUNCTION', 'UtilityFunction', 'UTILITYMATRIX', 'UtilityMatrix',
              'UTILITYMATRIXREF', 'IMPEDANCEMATRIX', 'IMPEDANCEMATRIXREF', 'SKIMMATRIXREF')
STATE = {}


def install():
    """Extend the native bridge without modifying the sealed reference source."""
    import r1_15a2_finecdf_bridge_v24916 as bridge
    cls = bridge.NoDirectMatrixWriteTDAdapter
    original = cls.guard_protected
    if getattr(original, '_component_utility_guard_owner', None) is not STATE:
        @functools.wraps(original)
        def guard_protected(self, full=False):
            original(self, full=full)
            if active_for(self.v):
                verify(self.v, self.read_matrix)
        guard_protected._component_utility_guard = True
        guard_protected._component_utility_guard_owner = STATE
        cls.guard_protected = guard_protected
    return {'installed': True, 'release': RELEASE, 'native_source_unchanged': True}


def active_for(visum):
    return STATE.get('visum') is visum and STATE.get('active') is True


def zones(visum):
    result = tuple(int(v) for _, v in visum.Net.Zones.GetMultiAttValues('NO'))
    if not result or len(set(result)) != len(result):
        raise SupplyContractError('TD_UTILITY_INVALID_ZONE_ORDER')
    return result


def array(values, n):
    a = np.array(values, dtype=np.float64, copy=True)
    if a.shape != (n, n) or not np.isfinite(a).all() or np.any(a < 0):
        raise SupplyContractError('TD_UTILITY_MATRIX_VALUES_INVALID')
    off = ~np.eye(n, dtype=bool)
    if np.any(a[off] <= 0):
        raise SupplyContractError('TD_UTILITY_OFFDIAGONAL_NONPOSITIVE')
    return a


def off_hash(a):
    owned = np.array(a, dtype=np.float64, copy=True)
    np.fill_diagonal(owned, 0.)
    return matrix_values_hash(owned)


def utility_handles(visum):
    """Resolve every native binding before changing any one of them."""
    state = vp.read_td_parameter_state(visum)
    result = {}
    for row in MAPPING:
        component = row['component']
        info = state['objects'].get(component)
        if not info or info.get('status') != 'OK':
            raise SupplyContractError('TD_UTILITY_STRATUM_UNREADABLE:' + component)
        found = None
        for obj in (info['dstrat'], info['grav']):
            for name in UTIL_NAMES:
                try:
                    value = obj.AttValue(name)
                except Exception:
                    continue
                found = (obj, name, value)
                break
            if found is not None:
                break
        if found is None:
            raise SupplyContractError('TD_UTILITY_REFERENCE_UNREADABLE:' + component)
        result[component] = found
    return result


def ref_no(value):
    # Same existing Visum expression contract as IZPEN1; reject compound formulae.
    import re
    match = re.fullmatch(r'\s*Matrix\(\s*\[NO\]\s*=\s*(\d+)\s*\)\s*', str(value), re.I)
    if match:
        return int(match.group(1))
    return int(str(value)) if str(value).isdigit() else None


def enum_id(value, field):
    """Visum AttValue may return enum names; AddMatrix needs integer enums."""
    expected, aliases = {
        'OBJECTTYPEREF': (2, {'OBJECTTYPEREFZONE', 'ZONE', 'ZONES'}),
        'MATRIXTYPE': (4, {'MATRIXTYPESKIM', 'SKIM'}),
        'DATASOURCETYPE': (1, {'DATASOURCETYPEDATA', 'DATA'}),
    }[field]
    token = ''.join(c for c in str(value).upper() if c.isalnum())
    if token in aliases:
        return expected
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        number = float('nan')
    if isinstance(value, (bool, np.bool_)) or not np.isfinite(number) or number != expected:
        raise SupplyContractError('TD_UTILITY_INVALID_ENUM:' + field + ':' + str(value))
    return expected


def metadata(visum, row, base_no):
    matrix = visum.Net.Matrices.ItemByKey(row['utility_no'])
    base = visum.Net.Matrices.ItemByKey(base_no)
    if int(matrix.AttValue('NO')) != row['utility_no'] or str(matrix.AttValue('CODE')) != row['utility_code']:
        raise SupplyContractError('TD_UTILITY_NUMBER_OR_CODE_COLLISION:%s' % row['utility_no'])
    for name in ('MATRIXTYPE', 'OBJECTTYPEREF'):
        if enum_id(matrix.AttValue(name), name) != enum_id(base.AttValue(name), name):
            raise SupplyContractError('TD_UTILITY_MATRIX_TYPE_MISMATCH:%s' % row['utility_no'])
    enum_id(matrix.AttValue('DATASOURCETYPE'), 'DATASOURCETYPE')
    return matrix


def _remember(arrays):
    hashes = {str(no): matrix_values_hash(a) for no, a in arrays.items()}
    key = canonical_hash(hashes)
    registry = STATE.setdefault('registry', OrderedDict())
    if key not in registry:
        # Equal component inputs share an immutable Python copy, not a Visum object.
        shared, owned = {}, {}
        for no, a in arrays.items():
            sha = hashes[str(no)]
            if sha not in shared:
                shared[sha] = np.array(a, dtype=np.float64, copy=True)
                shared[sha].setflags(write=False)
            owned[no] = shared[sha]
        registry[key] = owned
    registry.move_to_end(key)
    while len(registry) > 8:
        registry.popitem(last=False)
    return {'matrices': hashes, 'values_sha256': key,
            'zone_order_sha256': STATE['zone_hash'], 'base_matrix_no': STATE['base_no'],
            'base_offdiagonal_sha256': STATE['base_off_hash'],
            'bindings': {r['component']: r['utility_no'] for r in MAPPING}}


def _validate_bindings(visum):
    handles = utility_handles(visum)
    for row in MAPPING:
        if ref_no(handles[row['component']][2]) != row['utility_no']:
            raise SupplyContractError('TD_UTILITY_BINDING_CHANGED:' + row['component'])


def read_live(visum, reader=None):
    if not active_for(visum):
        raise SupplyContractError('TD_COMPONENT_UTILITIES_NOT_ACTIVE_RUN_' + SETUP_SCRIPT)
    if zones(visum) != STATE['zones']:
        raise SupplyContractError('TD_UTILITY_ZONE_ORDER_CHANGED')
    _validate_bindings(visum)
    get = reader or (lambda no: visum.Net.Matrices.ItemByKey(no).GetValues())
    base = array(get(STATE['base_no']), len(STATE['zones']))
    if off_hash(base) != STATE['base_off_hash']:
        raise SupplyContractError('TD_UTILITY_COMMON_BASE_CHANGED')
    arrays = {}
    for row in MAPPING:
        metadata(visum, row, STATE['base_no'])
        a = array(get(row['utility_no']), len(STATE['zones']))
        arrays[row['utility_no']] = a
    return arrays, base


def activate(visum, zone_order, base_no):
    STATE.clear()
    live_zones = zones(visum)
    if live_zones != tuple(zone_order) or base_no in UTILITY_NOS:
        raise SupplyContractError('TD_UTILITY_SOURCE_IDENTITY_INVALID')
    base = array(visum.Net.Matrices.ItemByKey(base_no).GetValues(), len(live_zones))
    STATE.update(active=True, visum=visum, zones=live_zones, base_no=base_no,
                 zone_hash=ordered_zone_hash(live_zones), base_off_hash=off_hash(base))
    try:
        arrays, _ = read_live(visum)
        for no, a in arrays.items():
            if not np.allclose(np.diag(a), np.diag(base), rtol=0, atol=1e-9):
                raise SupplyContractError('TD_UTILITY_DIAGONAL_NOT_COMMON_BASE:%s' % no)
        STATE['current'] = _remember(arrays)
    except BaseException:
        STATE.clear()
        raise
    return copy.deepcopy(STATE['current'])


def verify(visum, reader=None):
    arrays, base = read_live(visum, reader)
    hashes = {str(no): matrix_values_hash(a) for no, a in arrays.items()}
    if hashes != STATE['current']['matrices']:
        raise SupplyContractError('TD_UTILITY_UNOWNED_MATRIX_CHANGE')
    if any(not np.allclose(np.diag(a), np.diag(base), rtol=0, atol=1e-9) for a in arrays.values()):
        raise SupplyContractError('TD_UTILITY_DIAGONAL_NOT_COMMON_BASE')
    return copy.deepcopy(STATE['current'])


def extend_snapshot(snapshot, visum):
    if not active_for(visum):
        return snapshot
    out = dict(snapshot)
    out[SNAPSHOT_KEY] = verify(visum)
    out['state_hash'] = canonical_hash({k: v for k, v in out.items() if k != 'state_hash'})
    return out


def write_arrays(visum, target, adapter=None, *, allow_drift=False):
    """Own partial setters and restore all changed inputs on any failed write."""
    if set(target) != set(UTILITY_NOS):
        raise SupplyContractError('TD_UTILITY_WRITE_SCOPE_INVALID')
    before, base = read_live(visum)
    if not allow_drift and any(matrix_values_hash(a) != STATE['current']['matrices'][str(no)]
                               for no, a in before.items()):
        raise SupplyContractError('TD_UTILITY_UNOWNED_MATRIX_CHANGE')
    planned = {no: array(a, len(STATE['zones'])) for no, a in target.items()}
    if any(not np.array_equal(np.diag(a), np.diag(base)) for a in planned.values()):
        raise SupplyContractError('TD_UTILITY_DIAGONAL_SCOPE_MISMATCH')
    owned = []
    if adapter is not None:
        adapter.invalidate_candidate_readback('TD_COMPONENT_UTILITY_WRITE', mutation=True)
    try:
        for row in MAPPING:
            no = row['utility_no']
            if np.array_equal(before[no], planned[no]):
                continue
            matrix = metadata(visum, row, STATE['base_no'])
            owned.append(no)  # SetValues may change the matrix and then raise.
            matrix.SetValues(planned[no].tolist())
            back = array(matrix.GetValues(), len(STATE['zones']))
            if not np.array_equal(back, planned[no]):
                raise SupplyContractError('TD_UTILITY_WRITE_READBACK:%s' % no)
    except BaseException as original:
        errors = []
        for no in reversed(owned):
            try:
                matrix = visum.Net.Matrices.ItemByKey(no)
                matrix.SetValues(before[no].tolist())
                if not np.array_equal(np.array(matrix.GetValues()), before[no]):
                    raise RuntimeError('READBACK')
            except BaseException as exc:
                errors.append('%s:%r' % (no, exc))
        if errors:
            raise SupplyContractError('TD_UTILITY_RESTORE_UNVERIFIED:' + ';'.join(errors)) from original
        raise
    STATE['current'] = _remember(planned)
    return copy.deepcopy(STATE['current'])


def sync_diagonal(visum, adapter=None):
    arrays, base = read_live(visum)
    for no, a in arrays.items():
        if matrix_values_hash(a) != STATE['current']['matrices'][str(no)]:
            raise SupplyContractError('TD_UTILITY_UNOWNED_MATRIX_CHANGE')
        np.fill_diagonal(a, np.diag(base))
    return write_arrays(visum, arrays, adapter)


def restore_from_snapshot(visum, snapshot, adapter=None):
    if not active_for(visum):
        return
    expected = snapshot.get(SNAPSHOT_KEY)
    key = (expected or {}).get('values_sha256')
    if not key or key not in STATE['registry']:
        raise SupplyContractError('TD_UTILITY_PARENT_NOT_IN_REGISTRY')
    arrays = STATE['registry'][key]
    restored = write_arrays(visum, arrays, adapter, allow_drift=True)
    if restored != expected or verify(visum) != expected:
        raise SupplyContractError('TD_UTILITY_PARENT_RESTORE_MISMATCH')


def ratios(time_values, flows, n, ratio_max):
    """Vehicle-flow-weighted route alternatives; no-demand cells use minimum valid ratio.

    Matches the existing native-family aggregation principle. NoC never means
    no-toll: the component names are not used to invent a route-choice rule.
    """
    if not np.isfinite(ratio_max) or ratio_max < 1:
        raise SupplyContractError('TD_UTILITY_RATIO_LIMIT_INVALID')
    route = {}
    for dseg in REQUIRED_DSEGS:
        ttc, tt0 = (np.array(a, dtype=float, copy=True) for a in time_values[dseg])
        if ttc.shape != (n, n) or tt0.shape != (n, n) or not np.isfinite(ttc).all() or not np.isfinite(tt0).all():
            raise SupplyContractError('TD_UTILITY_TIME_MATRIX_INVALID:' + dseg)
        valid = (ttc > 0) & (tt0 > 0)
        r = np.ones((n, n))
        np.divide(ttc, tt0, out=r, where=valid)
        np.clip(r, 1., ratio_max, out=r)
        route[dseg] = (r, valid)
    result = {}
    for family, dsegs in SOURCES.items():
        if len(dsegs) == 1:
            result[family] = route[dsegs[0]][0].copy()
            continue
        numerator, denominator = np.zeros((n, n)), np.zeros((n, n))
        available = np.full((n, n), np.inf)
        for dseg in dsegs:
            r, valid = route[dseg]
            weights = np.asarray(flows[dseg], dtype=float)
            if weights.shape != (n, n) or not np.isfinite(weights).all() or np.any(weights < 0):
                raise SupplyContractError('TD_UTILITY_FLOW_WEIGHT_INVALID:' + dseg)
            w = np.where(valid, weights, 0.)
            numerator += r * w
            denominator += w
            available = np.minimum(available, np.where(valid, r, np.inf))
        r = np.where(np.isfinite(available), available, 1.)
        np.divide(numerator, denominator, out=r, where=denominator > 1.e-12)
        result[family] = r
    return result


def targets(base, previous, family_ratios, lam):
    if not np.isfinite(lam) or not 0 < lam <= 1:
        raise SupplyContractError('TD_UTILITY_LAMBDA_INVALID')
    base = array(base, len(base))
    result = {}
    for row in MAPPING:
        no = row['utility_no']
        old = array(previous[no], len(base))
        new = (1. - lam) * old + lam * (base * family_ratios[row['family']])
        np.fill_diagonal(new, np.diag(base))
        result[no] = array(new, len(base))
    return result


def read_weights(adapter):
    """Read the four actual native OD bindings, without loading other demands."""
    rows = snapshot_reads._dseg_bindings(adapter.visum)
    result = {}
    for dseg, expected_no in FLOW_NOS.items():
        matches = [row for row in rows if row['norm_code'] == dseg]
        if len(matches) != 1 or int(matches[0].get('matrix_no') or -1) != expected_no:
            raise SupplyContractError('TD_UTILITY_WEIGHT_BINDING_CHANGED:' + dseg)
        matrix = matches[0]['object'].ODMatrix
        if int(matrix.AttValue('NO')) != expected_no:
            raise SupplyContractError('TD_UTILITY_WEIGHT_SOURCE_CHANGED:' + dseg)
        result[dseg] = np.array(matrix.GetValues(), dtype=float, copy=True)
    return result


def feedback(ctrl, adapter, cfg, folder, control, state, diag, options):
    """Replace only component corrections; M9002 is never a congestion target."""
    from r1_15a2_td_impedance_refresh_v24917 import refresh_many
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    verify(adapter.visum)
    manager = getattr(adapter, 'v24916_dynamic_skims', None)
    if manager is None:
        raise SupplyContractError('TD_UTILITY_CURRENT_ASSIGNMENT_REQUIRED')
    epoch = manager.require_current()
    values, proof = refresh_many(adapter, REQUIRED_DSEGS, folder / 'FRESH_TIME_SKIMS')
    flows = read_weights(adapter)
    if manager.require_current() is not epoch:
        raise SupplyContractError('TD_UTILITY_ASSIGNMENT_CHANGED_DURING_PREPARATION')
    old, base = read_live(adapter.visum)
    family = ratios(values, flows, len(base), float(options['ic_ratio_max']))
    new = targets(base, old, family, float(options['ic_lambda']))
    off = ~np.eye(len(base), dtype=bool)
    relative = {str(no): float(np.max(np.abs(new[no][off] - old[no][off]) / np.maximum(old[no][off], 1.e-9), initial=0.))
                for no in UTILITY_NOS}
    rec = {'release': RELEASE, 'applied': False, 'fresh_time_skim_proof': proof,
           'utility_mode': 'COMPONENT', 'base_matrix_no': STATE['base_no'],
           'base_offdiagonal_sha256': STATE['base_off_hash'],
           'formula': 'MSA(previous, M9002 * clipped_native_TTC_over_TT0)',
           'lambda': float(options['ic_lambda']), 'max_rel_change_by_matrix': relative,
           'mapping': [dict(row) for row in MAPPING], 'family_sources': dict(SOURCES),
           'time_valid_cells': {d: int(((ttc > 0) & (tt0 > 0)).sum()) for d, (ttc, tt0) in values.items()},
           'weight_hashes': {d: matrix_values_hash(a) for d, a in flows.items()}}
    if max(relative.values()) < float(options['ic_min_rel_change']):
        rec['status'] = 'CONVERGED_NO_WRITE'
        rt.write_json(folder / 'COMPONENT_TD_UTILITIES.json', rec)
        return state, diag, rec
    try:
        if hasattr(adapter, 'begin_candidate_readback_context'):
            signature = canonical_hash({str(no): matrix_values_hash(a) for no, a in new.items()})
            adapter.begin_candidate_readback_context(state['state_hash'], 'TD_FINECDF', signature,
                parameter_evidence={'component_td_utilities': True})
        written = write_arrays(adapter.visum, new, adapter)
        with ctrl.recovery_scope(control, 'COMPONENT_TD_UTILITIES_RECOMPUTE'):
            gap = ctrl._assign_candidate(adapter, folder / 'FULL_DOWNSTREAM_RECOMPUTE', 'TD_FINECDF')
        after = adapter.snapshot()
        ctrl._td_expected_freeze(state, after, [], cfg, folder / 'TD_PARAMETER_FREEZE_AUDIT.json')
        after_diag = adapter.diagnostics(folder / 'DIAGNOSTICS', 'AFTER_COMPONENT_TD_UTILITIES')
        if adapter.snapshot() != after:
            raise SupplyContractError('TD_UTILITY_DIAGNOSTICS_CHANGED_MODEL')
        verify(adapter.visum)
    except BaseException as exc:
        # The existing recovery owner restores utility arrays, b/c and common
        # penalties, then proves the fully recomputed accepted parent.
        rec.update(status='FAILED_ROLLED_BACK', error=repr(exc)[:2000])
        rt.write_json(folder / 'COMPONENT_TD_UTILITIES.json', rec)
        rb_state, rb_diag = ctrl._rollback_td_all(adapter, state, diag, folder / 'ROLLBACK', cfg)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)) or exc.__class__.__name__ in (
                'UserStopRequested', 'TimeBudgetReached', 'StopRequested'):
            raise
        return rb_state, rb_diag, rec
    if hasattr(adapter, 'accepted_state_changed'):
        rec['path_epoch_transition'] = adapter.accepted_state_changed(
            after, after_diag, reason='COMPONENT_TD_UTILITY_REFRESH', phase='DEMAND')
    rec.update(status='APPLIED', applied=True, gap=gap, utility_state=written)
    rt.write_json(folder / 'COMPONENT_TD_UTILITIES.json', rec)
    return after, after_diag, rec
