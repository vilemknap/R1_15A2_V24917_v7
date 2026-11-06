# -*- coding: utf-8 -*-
"""Standalone Visum COM: setup + refresh 16 component TD utility matrices.

Requires only NumPy and the open Visum object. Run manually outside an executing
Procedure Sequence, after a completed assignment with stored native paths.
Refreshes T0/TCur from these paths; does NOT run TD, assignment or SaveVersion.
After success run the existing TD -> LONG mask -> downstream realization and
assignment/skims sequence. Do not run during a live calibration transaction.
"""
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
import hashlib
import json
import tempfile
import re
import numpy as np

BASE_NO = 9002
LAMBDA = 0.5
RATIO_MAX = 4.0
RELEASE = 'R1_STANDALONE_COMPONENT_TD_UTILITIES_20261106'
class SupplyContractError(RuntimeError):
    pass

def norm_code(value):
    return str(value).strip().upper()
core = SimpleNamespace(norm_code=norm_code)

def matrix_values_hash(a):
    return hashlib.sha256(np.ascontiguousarray(a, dtype='<f8').tobytes()).hexdigest()

def ordered_zone_hash(z):
    return hashlib.sha256(json.dumps(list(z), separators=(',', ':')).encode()).hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

MAPPING = ({'component': 'WORK_E_C', 'utility_no': 9700, 'utility_code': 'R1_TD_U_WORK_E_C', 'family': 'WORK', 'dstrat_code': '1_WORK_E_C', 'matrix_no': 9101}, {'component': 'WORK_E_noC', 'utility_no': 9701, 'utility_code': 'R1_TD_U_WORK_E_noC', 'family': 'WORK', 'dstrat_code': '1_WORK_E_noC', 'matrix_no': 9102}, {'component': 'WORK_noE_C', 'utility_no': 9702, 'utility_code': 'R1_TD_U_WORK_noE_C', 'family': 'WORK', 'dstrat_code': '1_WORK_noE_C', 'matrix_no': 9103}, {'component': 'WORK_noE_noC', 'utility_no': 9703, 'utility_code': 'R1_TD_U_WORK_noE_noC', 'family': 'WORK', 'dstrat_code': '1_WORK_noE_noC', 'matrix_no': 9104}, {'component': 'WORK_stud', 'utility_no': 9704, 'utility_code': 'R1_TD_U_WORK_stud', 'family': 'WORK', 'dstrat_code': '1_WORK_stud', 'matrix_no': 9105}, {'component': 'SERV_E_C', 'utility_no': 9705, 'utility_code': 'R1_TD_U_SERV_E_C', 'family': 'SERVICE', 'dstrat_code': '2_SERV_E_C', 'matrix_no': 9106}, {'component': 'SERV_E_noC', 'utility_no': 9706, 'utility_code': 'R1_TD_U_SERV_E_noC', 'family': 'SERVICE', 'dstrat_code': '2_SERV_E_noC', 'matrix_no': 9107}, {'component': 'SERV_noE_C', 'utility_no': 9707, 'utility_code': 'R1_TD_U_SERV_noE_C', 'family': 'SERVICE', 'dstrat_code': '2_SERV_noE_C', 'matrix_no': 9108}, {'component': 'SERV_noE_noC', 'utility_no': 9708, 'utility_code': 'R1_TD_U_SERV_noE_noC', 'family': 'SERVICE', 'dstrat_code': '2_SERV_noE_noC', 'matrix_no': 9109}, {'component': 'SERV_stud', 'utility_no': 9709, 'utility_code': 'R1_TD_U_SERV_stud', 'family': 'SERVICE', 'dstrat_code': '2_SERV_stud', 'matrix_no': 9110}, {'component': 'LONG_E_C', 'utility_no': 9710, 'utility_code': 'R1_TD_U_LONG_E_C', 'family': 'LONG', 'dstrat_code': '3_LONG_E_C', 'matrix_no': 9111}, {'component': 'LONG_E_noC', 'utility_no': 9711, 'utility_code': 'R1_TD_U_LONG_E_noC', 'family': 'LONG', 'dstrat_code': '3_LONG_E_noC', 'matrix_no': 9112}, {'component': 'LONG_noE_C', 'utility_no': 9712, 'utility_code': 'R1_TD_U_LONG_noE_C', 'family': 'LONG', 'dstrat_code': '3_LONG_noE_C', 'matrix_no': 9113}, {'component': 'LONG_noE_noC', 'utility_no': 9713, 'utility_code': 'R1_TD_U_LONG_noE_noC', 'family': 'LONG', 'dstrat_code': '3_LONG_noE_noC', 'matrix_no': 9114}, {'component': 'LONG_stud', 'utility_no': 9714, 'utility_code': 'R1_TD_U_LONG_stud', 'family': 'LONG', 'dstrat_code': '3_LONG_stud', 'matrix_no': 9115}, {'component': 'SCHOOL', 'utility_no': 9715, 'utility_code': 'R1_TD_U_SCHOOL', 'family': 'SCHOOL', 'dstrat_code': '5_SCHOOL', 'matrix_no': 9117})
UTILITY_NOS = (9700, 9701, 9702, 9703, 9704, 9705, 9706, 9707, 9708, 9709, 9710, 9711, 9712, 9713, 9714, 9715)
SOURCES = {'WORK': ('NATIVE_CW', 'NATIVE_CW_NOT'), 'SERVICE': ('NATIVE_CS', 'NATIVE_CS_NOT'), 'LONG': ('NATIVE_CL',), 'SCHOOL': ('NATIVE_CW', 'NATIVE_CW_NOT')}
FLOW_NOS = {'NATIVE_CW': 9301, 'NATIVE_CW_NOT': 9302, 'NATIVE_CS': 9303, 'NATIVE_CS_NOT': 9304}
REQUIRED_DSEGS = ('NATIVE_CW', 'NATIVE_CW_NOT', 'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CL')
UTIL_NAMES = ('UTILITYFUNCTION', 'UtilityFunction', 'UTILITYMATRIX', 'UtilityMatrix', 'UTILITYMATRIXREF', 'IMPEDANCEMATRIX', 'IMPEDANCEMATRIXREF', 'SKIMMATRIXREF')

def zones(visum):
    result = tuple((int(v) for _, v in visum.Net.Zones.GetMultiAttValues('NO')))
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

def ref_no(value):
    import re
    match = re.fullmatch('\\s*Matrix\\(\\s*\\[NO\\]\\s*=\\s*(\\d+)\\s*\\)\\s*', str(value), re.I)
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
        if ttc.shape != (n, n) or tt0.shape != (n, n) or (not np.isfinite(ttc).all()) or (not np.isfinite(tt0).all()):
            raise SupplyContractError('TD_UTILITY_TIME_MATRIX_INVALID:' + dseg)
        valid = (ttc > 0) & (tt0 > 0)
        r = np.ones((n, n))
        np.divide(ttc, tt0, out=r, where=valid)
        np.clip(r, 1.0, ratio_max, out=r)
        route[dseg] = (r, valid)
    result = {}
    for family, dsegs in SOURCES.items():
        if len(dsegs) == 1:
            result[family] = route[dsegs[0]][0].copy()
            continue
        numerator, denominator = (np.zeros((n, n)), np.zeros((n, n)))
        available = np.full((n, n), np.inf)
        for dseg in dsegs:
            r, valid = route[dseg]
            weights = np.asarray(flows[dseg], dtype=float)
            if weights.shape != (n, n) or not np.isfinite(weights).all() or np.any(weights < 0):
                raise SupplyContractError('TD_UTILITY_FLOW_WEIGHT_INVALID:' + dseg)
            w = np.where(valid, weights, 0.0)
            numerator += r * w
            denominator += w
            available = np.minimum(available, np.where(valid, r, np.inf))
        r = np.where(np.isfinite(available), available, 1.0)
        np.divide(numerator, denominator, out=r, where=denominator > 1e-12)
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
        new = (1.0 - lam) * old + lam * (base * family_ratios[row['family']])
        np.fill_diagonal(new, np.diag(base))
        result[no] = array(new, len(base))
    return result

def setup_utilities(visum, folder, dry_run=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    zone_order = zones(visum)
    n = len(zone_order)
    numbers = {int(v) for _, v in visum.Net.Matrices.GetMultiAttValues('NO')}
    if BASE_NO not in numbers:
        raise SupplyContractError('TD_UTILITY_BASE_M9002_MISSING')
    base_obj = visum.Net.Matrices.ItemByKey(BASE_NO)
    object_type = enum_id(base_obj.AttValue('OBJECTTYPEREF'), 'OBJECTTYPEREF')
    matrix_type = enum_id(base_obj.AttValue('MATRIXTYPE'), 'MATRIXTYPE')
    enum_id(base_obj.AttValue('DATASOURCETYPE'), 'DATASOURCETYPE')
    base = array(base_obj.GetValues(), n)
    handles = utility_handles(visum)
    existing = {}
    for row in MAPPING:
        obj, attr, raw = handles[row['component']]
        if ref_no(raw) not in (BASE_NO, row['utility_no']):
            raise SupplyContractError('TD_UTILITY_SETUP_UNEXPECTED_PARENT:' + row['component'])
        if row['utility_no'] in numbers:
            matrix = metadata(visum, row, BASE_NO)
            values = array(matrix.GetValues(), n)
            if not np.array_equal(np.diag(values), np.diag(base)):
                raise SupplyContractError('TD_UTILITY_SETUP_EXISTING_DIAGONAL_MISMATCH:%s' % row['utility_no'])
            existing[row['utility_no']] = matrix
        elif ref_no(raw) == row['utility_no']:
            raise SupplyContractError('TD_UTILITY_SETUP_DANGLING_REFERENCE:' + row['component'])
    code_rows = visum.Net.Matrices.GetMultiAttValues('CODE')
    no_rows = visum.Net.Matrices.GetMultiAttValues('NO')
    if [k for k, _ in code_rows] != [k for k, _ in no_rows]:
        raise SupplyContractError('TD_UTILITY_SETUP_INVENTORY_ORDER_CHANGED')
    codes = {}
    for (_, code), (_, no) in zip(code_rows, no_rows):
        codes.setdefault(str(code), []).append(int(no))
    for row in MAPPING:
        found = codes.get(row['utility_code'], [])
        if found and found != [row['utility_no']]:
            raise SupplyContractError('TD_UTILITY_SETUP_CODE_COLLISION:' + row['utility_code'])
    report = {'release': RELEASE, 'dry_run': bool(dry_run), 'base_matrix_no': BASE_NO, 'base_sha256': matrix_values_hash(base), 'zone_order_sha256': ordered_zone_hash(zone_order), 'mapping': [dict(row) for row in MAPPING], 'existing_preserved': sorted(existing), 'assignment_executed': False, 'td_executed': False, 'version_saved': False, 'status': 'PREFLIGHT_OK'}
    write_json(folder / 'COMPONENT_TD_UTILITY_SETUP.json', report)
    if dry_run:
        return report
    created, changed = ([], [])
    try:
        for row in MAPPING:
            no = row['utility_no']
            if no in existing:
                continue
            created.append(no)
            matrix = visum.Net.AddMatrix(no, object_type, matrix_type)
            matrix.SetAttValue('CODE', row['utility_code'])
            matrix.SetAttValue('NAME', 'R1 TD utility ' + row['component'] + ' = M9002 + native skim correction')
            metadata(visum, row, BASE_NO)
            matrix.SetValues(base.tolist())
            if not np.array_equal(array(matrix.GetValues(), n), base):
                raise SupplyContractError('TD_UTILITY_SETUP_COPY_READBACK:%s' % no)
        for row in MAPPING:
            handle = handles[row['component']]
            obj, attr, old = handle
            if ref_no(old) == row['utility_no']:
                continue
            changed.append(handle)
            obj.SetAttValue(attr, 'Matrix([NO]=%d)' % row['utility_no'])
            if ref_no(obj.AttValue(attr)) != row['utility_no']:
                raise SupplyContractError('TD_UTILITY_SETUP_BINDING_READBACK:' + row['component'])
        live = utility_handles(visum)
        if any((ref_no(live[r['component']][2]) != r['utility_no'] for r in MAPPING)):
            raise SupplyContractError('TD_UTILITY_SETUP_FINAL_BINDING_MISMATCH')
        if zones(visum) != zone_order or not np.array_equal(np.array(base_obj.GetValues()), base):
            raise SupplyContractError('TD_UTILITY_SETUP_BASE_OR_ZONES_CHANGED')
        report.update(status='CREATED_AND_BOUND', created=created, changed_bindings=len(changed))
        write_json(folder / 'COMPONENT_TD_UTILITY_SETUP.json', report)
        return report
    except BaseException as original:
        errors = []
        for obj, attr, old in reversed(changed):
            try:
                obj.SetAttValue(attr, old)
                if obj.AttValue(attr) != old:
                    raise RuntimeError('BINDING_READBACK')
            except BaseException as exc:
                errors.append('BINDING:' + repr(exc))
        if not errors:
            current = {int(v) for _, v in visum.Net.Matrices.GetMultiAttValues('NO')}
            for no in reversed(created):
                if no not in current:
                    continue
                try:
                    visum.Net.RemoveMatrix(visum.Net.Matrices.ItemByKey(no))
                    if no in {int(v) for _, v in visum.Net.Matrices.GetMultiAttValues('NO')}:
                        raise RuntimeError('REMOVE_READBACK')
                except BaseException as exc:
                    errors.append('M%d:%r' % (no, exc))
        report.update(status='RESTORE_UNVERIFIED' if errors else 'FAILED_RESTORED', error=repr(original), restoration_errors=errors)
        write_json(folder / 'COMPONENT_TD_UTILITY_SETUP.json', report)
        if errors:
            raise SupplyContractError('TD_UTILITY_SETUP_RESTORE_UNVERIFIED:' + ';'.join(errors)) from original
        raise

def raise_if_busy(exc):
    if (int(getattr(exc, 'hresult', 0) or 0) & 0xffffffff) in (0x80010001, 0x8001010A):
        raise exc


def all_items(collection):
    member = collection.GetAll
    return list(member() if callable(member) else member)


def utility_handles(visum):
    required = {r['dstrat_code'].upper() for r in MAPPING}
    found = []
    for op in all_items(visum.Procedures.Operations):
        if int(op.AttValue('OPERATIONTYPE')) != 46 or not flag(op, 'ACTIVE'):
            continue
        params = op.TripDistributionParameters
        codes = {s.strip().upper() for s in str(params.AttValue('DSTRATSET')).split(',')}
        if required <= codes:
            found.append(params)
    if len(found) != 1:
        raise SupplyContractError('EXPECTED_ONE_ACTIVE_NATIVE_TD_OPERATION')
    result = {}
    for row in MAPPING:
        obj = found[0].TripDistributionDStratParameters(row['dstrat_code'])
        candidates = [obj]
        for name in ('GravitationParameters', 'GravityParameters', 'DistributionParameters'):
            try:
                candidates.append(getattr(obj, name))
            except Exception as exc:
                raise_if_busy(exc)
        handle = None
        for candidate in candidates:
            for name in UTIL_NAMES:
                try:
                    raw = candidate.AttValue(name)
                except Exception as exc:
                    raise_if_busy(exc)
                    continue
                handle = candidate, name, raw
                break
            if handle is not None:
                break
        if handle is None:
            raise SupplyContractError('UTILITY_REFERENCE_UNREADABLE:' + row['component'])
        result[row['component']] = handle
    return result


def flag(obj, name):
    value = obj.AttValue(name)
    if value in (True, 1, -1, '1', 'true', 'True'): return True
    if value in (False, 0, '0', 'false', 'False'): return False
    raise SupplyContractError('INVALID_BOOL:' + name)


@contextmanager
def settings(edits):
    planned = [(o, name, flag(o, name), bool(new)) for o, name, new in edits]
    owned = []
    try:
        for o, name, old, new in planned:
            if old == new: continue
            owned.append((o, name, old))
            o.SetAttValue(name, new)
            if flag(o, name) != new: raise SupplyContractError('CONTROL_READBACK:' + name)
        yield
    finally:
        errors = []
        for o, name, old in reversed(owned):
            try:
                o.SetAttValue(name, old)
                if flag(o, name) != old: raise RuntimeError('READBACK')
            except BaseException as exc:
                errors.append(name + ':' + repr(exc))
        if errors: raise SupplyContractError('CONTROL_RESTORE_UNVERIFIED:' + ';'.join(errors))


def skim_bindings(visum):
    result = {d: {} for d in REQUIRED_DSEGS}
    for matrix in all_items(visum.Net.Matrices):
        code = norm_code(matrix.AttValue('CODE'))
        if code not in ('DIS', 'TTC', 'TT0'): continue
        d = norm_code(matrix.AttValue('DSEGCODE'))
        if d not in result: continue
        if code in result[d]: raise SupplyContractError('DUPLICATE_SKIM:' + d + ':' + code)
        result[d][code] = int(matrix.AttValue('NO'))
    if any(set(b) != {'DIS', 'TTC', 'TT0'} for b in result.values()):
        raise SupplyContractError('MISSING_NATIVE_DIS_TTC_TT0')
    ids = [n for b in result.values() for n in b.values()]
    if len(ids) != len(set(ids)): raise SupplyContractError('SKIM_BINDINGS_OVERLAP')
    return result


def refresh_skims(visum, folder):
    zone_order = zones(visum); n = len(zone_order)
    bindings = skim_bindings(visum)
    def read(no):
        a = np.array(visum.Net.Matrices.ItemByKey(no).GetValues(), dtype=float, copy=True)
        if a.shape != (n, n) or not np.isfinite(a).all(): raise SupplyContractError('INVALID_SKIM:' + str(no))
        return a
    before = {d: matrix_values_hash(read(b['DIS'])) for d, b in bindings.items()}
    ops = all_items(visum.Procedures.Operations)
    matches = {d: [] for d in REQUIRED_DSEGS}
    for index, op in enumerate(ops):
        if not flag(op, 'ACTIVE') or int(op.AttValue('OPERATIONTYPE')) in (45, 46, 65, 75, 101): continue
        try:
            params = op.PrTSkimMatrixParameters
        except Exception as exc:
            raise_if_busy(exc)
            continue
        d = norm_code(params.AttValue('DSeg'))
        if d in matches: matches[d].append((index, params))
    if any(len(found) != 1 for found in matches.values()):
        raise SupplyContractError('EXPECTED_ONE_ACTIVE_SKIM_OPERATION_PER_NATIVE_DSEG')
    selected = {found[0][0] for found in matches.values()}
    edits = []
    for op_index, op in enumerate(ops):
        desired = True if int(op.AttValue('OPERATIONTYPE')) == 75 else op_index in selected
        edits.append((op, 'ACTIVE', desired))
    for found in matches.values():
        params = found[0][1]
        edits += [(params, 'UseExistingPaths', True), (params, 'OnlyRelationsWithDemand', False)]
        for name in ('T0', 'TCur'):
            single = params.SingleSkimMatrixParameters(name)
            edits += [(single, 'Calculate', True), (single, 'SaveToFile', False)]
    with settings(edits):
        visum.Procedures.Execute()
    if zones(visum) != zone_order or skim_bindings(visum) != bindings:
        raise SupplyContractError('SKIM_SOURCE_OR_ZONE_ORDER_CHANGED')
    if {d: matrix_values_hash(read(b['DIS'])) for d, b in bindings.items()} != before:
        raise SupplyContractError('DIS_CHANGED_DURING_TIME_REFRESH_RECOMPUTE_ASSIGNMENT_FIRST')
    values = {d: (read(b['TTC']), read(b['TT0'])) for d, b in bindings.items()}
    proof = dict(status='FRESH_TIME_SKIMS_FROM_EXISTING_NATIVE_PATHS', bindings=bindings,
                 zone_order_sha256=ordered_zone_hash(zone_order), dis_hashes=before,
                 time_hashes={d: [matrix_values_hash(a) for a in pair] for d, pair in values.items()},
                 controls_restored=True, assignment_executed=False,
                 assignment_epoch_certificate=False)
    write_json(Path(folder)/'TIME_SKIMS.json', proof)
    return values, proof


def run(visum, folder):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    z = zones(visum); base = array(visum.Net.Matrices.ItemByKey(BASE_NO).GetValues(), len(z))
    initial_nos = {int(v) for _, v in visum.Net.Matrices.GetMultiAttValues('NO')}
    handles = utility_handles(visum)
    old = {}
    for row in MAPPING:
        if row['utility_no'] in initial_nos:
            matrix = metadata(visum, row, BASE_NO)
            old[row['utility_no']] = array(matrix.GetValues(), len(z))
    # Dry setup verifies every collision/reference before native execution/writes.
    setup_utilities(visum, folder, dry_run=True)
    weights = {}
    for ds in all_items(visum.Net.DemandSegments):
        d = norm_code(ds.AttValue('CODE'))
        if d not in FLOW_NOS: continue
        if d in weights or int(ds.ODMatrix.AttValue('NO')) != FLOW_NOS[d]:
            raise SupplyContractError('WEIGHT_BINDING_CHANGED:' + d)
        weights[d] = np.array(ds.ODMatrix.GetValues(), dtype=float, copy=True)
    if set(weights) != set(FLOW_NOS): raise SupplyContractError('MISSING_NATIVE_WEIGHT_BINDINGS')
    times, proof = refresh_skims(visum, folder)
    family = ratios(times, weights, len(z), RATIO_MAX)
    previous = {r['utility_no']: old.get(r['utility_no'], base) for r in MAPPING}
    wanted = targets(base, previous, family, LAMBDA)
    try:
        setup_utilities(visum, folder)
        for row in MAPPING:
            matrix = metadata(visum, row, BASE_NO)
            no = row['utility_no']
            matrix.SetValues(wanted[no].tolist())
            if not np.array_equal(array(matrix.GetValues(), len(z)), wanted[no]):
                raise SupplyContractError('UTILITY_WRITE_READBACK:' + str(no))
        if zones(visum) != z or not np.array_equal(np.array(visum.Net.Matrices.ItemByKey(BASE_NO).GetValues()), base):
            raise SupplyContractError('COMMON_BASE_OR_ZONES_CHANGED')
        report = dict(status='UPDATED_REQUIRES_DOWNSTREAM_RECOMPUTE', release=RELEASE,
                      base_sha256=matrix_values_hash(base), lambda_value=LAMBDA, ratio_max=RATIO_MAX,
                      mapping=[dict(r) for r in MAPPING], skim_proof=proof,
                      utility_hashes={str(no): matrix_values_hash(a) for no, a in wanted.items()},
                      td_executed=False, assignment_executed=False, version_saved=False)
        write_json(folder/'RESULT.json', report)
        return report
    except BaseException as original:
        errors = []
        for obj, attr, raw in reversed(list(handles.values())):
            try:
                obj.SetAttValue(attr, raw)
                if obj.AttValue(attr) != raw: raise RuntimeError('BINDING_READBACK')
            except BaseException as exc: errors.append('BINDING:' + repr(exc))
        for no, a in old.items():
            try:
                matrix = visum.Net.Matrices.ItemByKey(no); matrix.SetValues(a.tolist())
                if not np.array_equal(np.array(matrix.GetValues()), a): raise RuntimeError('MATRIX_READBACK')
            except BaseException as exc: errors.append(str(no) + ':' + repr(exc))
        if not errors:
            current = {int(v) for _, v in visum.Net.Matrices.GetMultiAttValues('NO')}
            for no in UTILITY_NOS:
                if no in current and no not in initial_nos:
                    try:
                        visum.Net.RemoveMatrix(visum.Net.Matrices.ItemByKey(no))
                        if no in {int(v) for _, v in visum.Net.Matrices.GetMultiAttValues('NO')}: raise RuntimeError('REMOVE_READBACK')
                    except BaseException as exc: errors.append(str(no) + ':' + repr(exc))
        write_json(folder/'RESULT.json', dict(status='RESTORE_UNVERIFIED' if errors else 'FAILED_UTILITY_INPUTS_RESTORED',
                   error=repr(original), restoration_errors=errors, derived_time_skims_restored=False))
        if errors: raise SupplyContractError('STANDALONE_RESTORE_UNVERIFIED:' + ';'.join(errors)) from original
        raise


def main():
    visum = globals().get('Visum')
    if visum is None: raise RuntimeError('Spustte ve Visumu: Scripts -> Run script file')
    folder = Path(tempfile.mkdtemp(prefix='R1_TD_UTILITY_'))
    print('R1 TD utility audit: ' + str(folder))
    result = run(visum, folder)
    print(result['status'])
    print('Utility M9700-9715 aktualizovany. M9002 zachovana. Nyni prepocitejte TD a navazujici kroky vcetne LONG masky, assignmentu a skimu.')
    print('Tento skript spoustejte samostatne mimo prave bezici Procedure Sequence/kalibraci.')


if __name__ == '__main__' or globals().get('Visum') is not None:
    main()
