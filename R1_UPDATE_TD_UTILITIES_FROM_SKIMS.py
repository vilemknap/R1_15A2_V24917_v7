# -*- coding: utf-8 -*-
"""Run script step between Trip Generation and Trip Distribution.

Reads EXISTING TTC/TT0 matrices from the previous completed assignment/skims.
Never calls Procedures.Execute, computes skims, attaches COM or saves a version.
Requires the 16 utility matrices/references prepared by the one-time setup.
Only stdlib and NumPy required. Native T0/TCur must be computed upstream in the
feedback loop; values/identity are checked here, temporal freshness cannot be
certified by a matrix read alone. See RESULT.json for this explicit limitation.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import tempfile
import numpy as np

RELEASE = 'R1_TD_UTILITY_PROCSEQ_UPDATE_20261110'
class SupplyContractError(RuntimeError):
    pass

BASE_NO = 9002

LAMBDA = 0.5

RATIO_MAX = 4.0

def matrix_values_hash(a):
    return hashlib.sha256(np.ascontiguousarray(a, dtype='<f8').tobytes()).hexdigest()

def ordered_zone_hash(z):
    return hashlib.sha256(json.dumps(list(z), separators=(',', ':')).encode()).hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

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
    expected, aliases = {'OBJECTTYPEREF': (2, {'OBJECTTYPEREFZONE', 'ZONE', 'ZONES'}), 'MATRIXTYPE': (4, {'MATRIXTYPESKIM', 'SKIM'}), 'DATASOURCETYPE': (1, {'DATASOURCETYPEDATA', 'DATA'})}[field]
    token = ''.join((c for c in str(value).upper() if c.isalnum()))
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

def raise_if_busy(exc):
    if int(getattr(exc, 'hresult', 0) or 0) & 4294967295 in (2147549185, 2147549450):
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
                handle = (candidate, name, raw)
                break
            if handle is not None:
                break
        if handle is None:
            raise SupplyContractError('UTILITY_REFERENCE_UNREADABLE:' + row['component'])
        result[row['component']] = handle
    return result

def flag(obj, name):
    value = obj.AttValue(name)
    if value in (True, 1, -1, '1', 'true', 'True'):
        return True
    if value in (False, 0, '0', 'false', 'False'):
        return False
    raise SupplyContractError('INVALID_BOOL:' + name)

def time_bindings(visum):
    result = {d: {} for d in REQUIRED_DSEGS}
    for matrix in all_items(visum.Net.Matrices):
        code = str(matrix.AttValue('CODE')).strip().upper()
        if code not in ('TTC', 'TT0'): continue
        dseg = str(matrix.AttValue('DSEGCODE')).strip().upper()
        if dseg not in result: continue
        if code in result[dseg]: raise SupplyContractError('DUPLICATE_TIME_SKIM:' + dseg + ':' + code)
        no = int(matrix.AttValue('NO'))
        if no == BASE_NO or no in UTILITY_NOS: raise SupplyContractError('TIME_INPUT_OUTPUT_OVERLAP')
        for field in ('OBJECTTYPEREF', 'MATRIXTYPE', 'DATASOURCETYPE'):
            enum_id(matrix.AttValue(field), field)
        result[dseg][code] = no
    if any(set(pair) != {'TTC', 'TT0'} for pair in result.values()):
        raise SupplyContractError('MISSING_TIME_SKIMS_COMPUTE_T0_TCUR_AFTER_ASSIGNMENT')
    ids = [no for pair in result.values() for no in pair.values()]
    if len(set(ids)) != len(ids): raise SupplyContractError('TIME_BINDINGS_OVERLAP')
    return result


def read_inputs(visum, zone_order):
    if zones(visum) != zone_order: raise SupplyContractError('ZONE_ORDER_CHANGED')
    n = len(zone_order)
    bindings = time_bindings(visum)
    times = {}
    off = ~np.eye(n, dtype=bool)
    for dseg, binding in bindings.items():
        pair = tuple(np.array(visum.Net.Matrices.ItemByKey(binding[code]).GetValues(),
                              dtype=float, copy=True) for code in ('TTC', 'TT0'))
        if any(a.shape != (n,n) or not np.isfinite(a).all() for a in pair):
            raise SupplyContractError('INVALID_TIME_SKIM:' + dseg)
        if not np.any((pair[0] > 0) & (pair[1] > 0) & off):
            raise SupplyContractError('NO_VALID_TIME_PAIRS_COMPUTE_T0_TCUR:' + dseg)
        times[dseg] = pair
    weights = {}
    for ds in all_items(visum.Net.DemandSegments):
        dseg = str(ds.AttValue('CODE')).strip().upper()
        if dseg not in FLOW_NOS: continue
        if dseg in weights or int(ds.ODMatrix.AttValue('NO')) != FLOW_NOS[dseg]:
            raise SupplyContractError('WEIGHT_BINDING_CHANGED:' + dseg)
        a = np.array(ds.ODMatrix.GetValues(), dtype=float, copy=True)
        if a.shape != (n,n) or not np.isfinite(a).all() or np.any(a < 0):
            raise SupplyContractError('INVALID_WEIGHT_MATRIX:' + dseg)
        weights[dseg] = a
    if set(weights) != set(FLOW_NOS): raise SupplyContractError('MISSING_NATIVE_WEIGHT_BINDINGS')
    evidence = dict(bindings=bindings,
        time_hashes={d:[matrix_values_hash(a) for a in pair] for d,pair in times.items()},
        weight_hashes={d:matrix_values_hash(a) for d,a in weights.items()},
        zone_order_sha256=ordered_zone_hash(zone_order))
    return times, weights, evidence


def verify_refs(visum):
    handles = utility_handles(visum)
    for row in MAPPING:
        if ref_no(handles[row['component']][2]) != row['utility_no']:
            raise SupplyContractError('UTILITY_SETUP_REQUIRED:' + row['component'])


def run(visum, folder):
    folder = Path(folder); folder.mkdir(parents=True,exist_ok=True)
    report = dict(release=RELEASE, status='PREFLIGHT',
        source='EXISTING_TIME_SKIMS_PREVIOUS_ASSIGNMENT', freshness_certified=False,
        source_requirement='Native T0/TCur computed after the previous completed assignment',
        td_executed=False, assignment_executed=False, skims_executed=False,
        procedure_controls_changed=False, version_saved=False,
        utc=datetime.now(timezone.utc).isoformat())
    owned, old = [], {}
    try:
        z = zones(visum); n = len(z)
        base_obj = visum.Net.Matrices.ItemByKey(BASE_NO)
        for field in ('OBJECTTYPEREF','MATRIXTYPE','DATASOURCETYPE'):
            enum_id(base_obj.AttValue(field),field)
        base = array(base_obj.GetValues(),n)
        verify_refs(visum)
        for row in MAPPING:
            old[row['utility_no']] = array(metadata(visum,row,BASE_NO).GetValues(),n)
        times,weights,evidence = read_inputs(visum,z)
        wanted = targets(base,old,ratios(times,weights,n,RATIO_MAX),LAMBDA)
        report.update(input_evidence=evidence,base_sha256=matrix_values_hash(base),
                      lambda_value=LAMBDA,ratio_max=RATIO_MAX)
        for row in MAPPING:
            no = row['utility_no']
            if np.array_equal(old[no],wanted[no]): continue
            matrix = metadata(visum,row,BASE_NO)
            owned.append(no)  # A COM setter can modify values before raising.
            matrix.SetValues(wanted[no].tolist())
            if not np.array_equal(array(matrix.GetValues(),n),wanted[no]):
                raise SupplyContractError('UTILITY_WRITE_READBACK:' + str(no))
        verify_refs(visum)
        if not np.array_equal(np.array(base_obj.GetValues()),base):
            raise SupplyContractError('COMMON_BASE_CHANGED')
        if read_inputs(visum,z)[2] != evidence:
            raise SupplyContractError('SKIM_OR_WEIGHT_SOURCES_CHANGED_DURING_UPDATE')
        for row in MAPPING:
            no = row['utility_no']
            if not np.array_equal(array(metadata(visum,row,BASE_NO).GetValues(),n),wanted[no]):
                raise SupplyContractError('FINAL_UTILITY_READBACK:' + str(no))
        report.update(status='UPDATED_READY_FOR_FOLLOWING_TD',written_matrices=owned,
                      utility_hashes={str(no):matrix_values_hash(a) for no,a in wanted.items()})
        write_json(folder/'RESULT.json',report)
        return report
    except BaseException as original:
        errors=[]
        for no in reversed(owned):
            try:
                matrix=visum.Net.Matrices.ItemByKey(no)
                matrix.SetValues(old[no].tolist())
                if not np.array_equal(np.array(matrix.GetValues()),old[no]):raise RuntimeError('READBACK')
            except BaseException as exc:errors.append(str(no)+':'+repr(exc))
        report.update(status='RESTORE_UNVERIFIED' if errors else 'FAILED_INPUTS_RESTORED',
                      error=repr(original),restoration_errors=errors,written_matrices=owned)
        write_json(folder/'RESULT.json',report)
        if errors:raise SupplyContractError('UPDATE_ONLY_RESTORE_UNVERIFIED:'+';'.join(errors)) from original
        raise


def main():
    visum=globals().get('Visum')
    if visum is None:raise RuntimeError('Spustte ve Visumu jako Run script mezi TG a TD.')
    folder=Path(tempfile.mkdtemp(prefix='R1_TD_UTILITY_STEP_'))
    print('R1 TD utility step audit: '+str(folder))
    report=run(visum,folder)
    print(report['status']+'; upraveno matic: '+str(len(report['written_matrices'])))
    print('Pouzity existujici TTC/TT0 z predchoziho assignmentu; cerstvost neni certifikovana samotnym ctenim matic.')


if __name__=='__main__' or globals().get('Visum') is not None:
    main()
