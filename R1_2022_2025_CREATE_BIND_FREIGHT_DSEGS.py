# -*- coding: utf-8 -*-
"""Create year-specific freight DSegs inside the R1_VARIANTY BASE VERSION.

Run with Scripts -> Run script file. Uses only the existing Visum/COM host.
Creates/reuses LNV_2022, NV_2022, LNV_2025, NV_2025 and their named DATA
matrix references. Missing matrices are EMPTY: load exported MTX separately.
Never writes OD values, changes procedures, runs assignment or saves .ver.
"""
from datetime import datetime
import csv
import json
import math
from pathlib import Path
import traceback
import uuid

DRY_RUN = False
CREATE_MISSING_MATRICES = True
SOURCE_DSEGS = {'LNV': 'LNV', 'NV': 'NV'}
YEARS = (2022, 2025)
EXPECTED_ZONES = 681
SCRIPT_ID = 'R1_FREIGHT_DSEGS_2022_2025_V2_MODEATTRFIX'


class ReferenceError(RuntimeError):
    pass


def text(value):
    return '' if value is None else str(value).strip()


def integer(value):
    if isinstance(value, bool):
        raise ReferenceError('INVALID_INTEGER:' + repr(value))
    try:
        x = float(value)
        if not math.isfinite(x) or x != int(x):
            raise ValueError()
        return int(x)
    except (ValueError, TypeError, OverflowError):
        raise ReferenceError('INVALID_INTEGER:' + repr(value))


def objects(collection):
    raw = collection.GetAll
    return list(raw() if callable(raw) else raw)


def code(obj):
    return text(obj.AttValue('CODE')).upper()


def index_by_code(collection):
    found = {}
    for obj in objects(collection):
        key = code(obj)
        if key in found:
            raise ReferenceError('DUPLICATE_OBJECT_CODE:' + key)
        found[key] = obj
    return found


def matrix_inventory(visum):
    result = {}
    for mat in objects(visum.Net.Matrices):
        no = integer(mat.AttValue('NO'))
        if no in result:
            raise ReferenceError('DUPLICATE_MATRIX_NO:' + str(no))
        result[no] = mat
    return result


def matrix_no(mat):
    return None if mat is None else integer(mat.AttValue('NO'))


def mode_code(ds):
    # Mode is a network attribute/relation, not an IDemandSegment COM
    # property. Visum 2026's generated wrapper therefore has no ds.Mode.
    errors = []
    for attribute in (r'MODE\CODE', 'MODE'):
        try:
            value = ds.AttValue(attribute)
            # Attribute references may return the referenced object rather
            # than its code. Never turn a COM object's repr into a mode code.
            if value is not None and not isinstance(value, str):
                value = value.AttValue('CODE')
            result = text(value).upper()
            if result:
                return result
        except Exception as exc:
            errors.append(attribute + ': ' + str(exc))
    raise ReferenceError('DSEG_MODE_UNREADABLE:' + code(ds) + '; ' + '; '.join(errors))


def dseg_state(ds):
    # An ODMatrix getter failure is an error, never proof of an empty binding.
    return {'code': code(ds), 'mode': mode_code(ds), 'matrix_no': matrix_no(ds.ODMatrix),
            'name': text(ds.AttValue('NAME'))}


def matrix_gate(mat, expected_code):
    if code(mat) != expected_code:
        raise ReferenceError('MATRIX_CODE_READBACK:' + expected_code)
    members = {'OBJECTTYPEREF': (2, {'OBJECTTYPEREFZONE', 'ZONE', 'ZONES'}),
               'MATRIXTYPE': (3, {'MATRIXTYPEDEMAND', 'DEMAND'}),
               'DATASOURCETYPE': (1, {'DATASOURCETYPEDATA', 'DATA'})}
    for field, (expected, aliases) in members.items():
        value = mat.AttValue(field)
        token = ''.join(c for c in text(value).upper() if c.isalnum())
        if token in aliases:
            continue
        if integer(value) != expected:
            raise ReferenceError('INCOMPATIBLE_MATRIX_' + field + ':' + expected_code)


def write_json(path, value):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(path)


def preflight(visum, create_missing):
    pairs = list(visum.Net.Zones.GetMultiAttValues('NO', False))
    numbers = [integer(value) for _, value in pairs]
    if len(numbers) != EXPECTED_ZONES or set(numbers) != set(range(1, EXPECTED_ZONES + 1)):
        raise ReferenceError('EXPECTED_681_ZONES_NO_1_TO_681')
    mats = matrix_inventory(visum)
    dsegs = index_by_code(visum.Net.DemandSegments)
    modes = index_by_code(visum.Net.Modes)
    sources = {}
    for kind, source_code in SOURCE_DSEGS.items():
        ds = dsegs.get(source_code.upper())
        if ds is None:
            raise ReferenceError('SOURCE_DSEG_MISSING:' + source_code)
        state = dseg_state(ds)
        if state['mode'] not in modes:
            raise ReferenceError('SOURCE_MODE_MISSING:' + state['mode'])
        sources[kind] = (state, modes[state['mode']])
    rows = []
    for year in YEARS:
        for kind in ('LNV', 'NV'):
            ds_code = kind + '_' + str(year)
            mat_code = 'R1_' + kind + '_' + str(year) + '_WORK'
            matches = [mat for mat in mats.values() if code(mat) == mat_code]
            if len(matches) > 1:
                raise ReferenceError('DUPLICATE_MATRIX_CODE:' + mat_code)
            mat = matches[0] if matches else None
            if mat is not None:
                matrix_gate(mat, mat_code)
            elif not create_missing:
                raise ReferenceError('TARGET_MATRIX_MISSING:' + mat_code)
            ds = dsegs.get(ds_code)
            if ds is not None:
                state = dseg_state(ds)
                if state['mode'] != sources[kind][0]['mode']:
                    raise ReferenceError('EXISTING_DSEG_MODE_CONFLICT:' + ds_code)
                if state['matrix_no'] is not None and state['matrix_no'] != matrix_no(mat):
                    raise ReferenceError('EXISTING_DSEG_MATRIX_CONFLICT:' + ds_code)
            rows.append({'year': year, 'kind': kind, 'dseg': ds_code, 'matrix_code': mat_code,
                         'source_dseg': sources[kind][0]['code'], 'mode': sources[kind][0]['mode'],
                         'matrix_no': matrix_no(mat), 'matrix_action': 'REUSE' if mat is not None else 'CREATE_EMPTY',
                         'dseg_action': 'CREATE_AND_BIND' if ds is None else ('BIND_EMPTY' if ds.ODMatrix is None else 'REUSE')})
    return rows, mats, dsegs, sources


def rollback(visum, mats_before, dsegs_before, touched, states_before, created_matrix_nos, new_dseg_codes):
    failures = []
    def attempt(label, action):
        try:
            action()
        except Exception as exc:
            failures.append(label + ': ' + str(exc))
    # Restore only existing empty bindings touched by this invocation.
    for key, ds in reversed(touched):
        attempt('RESTORE_BINDING:' + key, lambda ds=ds: setattr(ds, 'ODMatrix', None))
    try:
        current = index_by_code(visum.Net.DemandSegments)
        for key in sorted((set(current) - set(dsegs_before)) & new_dseg_codes):
            attempt('REMOVE_NEW_DSEG:' + key, lambda key=key: visum.Net.RemoveDemandSegment(current[key]))
        current_mats = matrix_inventory(visum)
        for no in reversed(created_matrix_nos):
            if no not in current_mats:
                continue
            attempt('REMOVE_NEW_MATRIX:' + str(no), lambda no=no: visum.Net.RemoveMatrix(current_mats[no]))
        if set(index_by_code(visum.Net.DemandSegments)) != set(dsegs_before):
            failures.append('DSEG_INVENTORY_NOT_RESTORED')
        if set(matrix_inventory(visum)) != set(mats_before):
            failures.append('MATRIX_INVENTORY_NOT_RESTORED')
        for key, state in states_before.items():
            if dseg_state(dsegs_before[key]) != state:
                failures.append('DSEG_STATE_NOT_RESTORED:' + key)
    except Exception as exc:
        failures.append('ROLLBACK_READBACK_FAILED:' + str(exc))
    return failures


def run(visum, audit_dir, dry_run=False, create_missing=True):
    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=False)
    result = {'script': SCRIPT_ID, 'status': 'FAILED_PREFLIGHT_NO_CHANGES', 'dry_run': dry_run,
              'matrix_values_modified': False, 'external_mtx_loaded': False,
              'procedures_modified': False, 'assignment_run': False, 'version_saved': False}
    started = False
    touched = []
    created_matrix_nos = []
    try:
        rows, mats, dsegs, sources = preflight(visum, create_missing)
        # Record target/source metadata before any COM mutation.
        protected_codes = set(SOURCE_DSEGS.values()) | {r['dseg'] for r in rows if r['dseg'] in dsegs}
        states = {key: dseg_state(dsegs[key]) for key in protected_codes}
        new_dseg_codes = {r['dseg'] for r in rows if r['dseg'] not in dsegs}
        result['plan'] = rows
        write_json(audit_dir / 'PLAN.json', result)
        if not dry_run:
            started = True
            for row in rows:
                mat = mats.get(row['matrix_no'])
                if mat is None:
                    mat = visum.Net.AddMatrix(-1, 2, 3)
                    new_no = matrix_no(mat)
                    if new_no is None or new_no in mats or new_no in created_matrix_nos:
                        raise ReferenceError('ADD_MATRIX_DID_NOT_RETURN_A_NEW_OBJECT')
                    created_matrix_nos.append(new_no)
                    mat.SetAttValue('CODE', row['matrix_code'])
                    mat.SetAttValue('NAME', 'R1 ' + row['kind'] + ' ' + str(row['year']) + ' freight data reference')
                    matrix_gate(mat, row['matrix_code'])
                ds = dsegs.get(row['dseg'])
                if ds is None:
                    ds = visum.Net.AddDemandSegment(row['dseg'], sources[row['kind']][1])
                    if code(ds) != row['dseg'] or mode_code(ds) != row['mode']:
                        raise ReferenceError('ADD_DSEG_RETURNED_WRONG_OBJECT:' + row['dseg'])
                    ds.SetAttValue('NAME', 'R1 ' + row['kind'] + ' ' + str(row['year']) + ' freight aggregate')
                    ds.ODMatrix = mat
                elif ds.ODMatrix is None:
                    touched.append((row['dseg'], ds))  # Own a setter that may mutate and then raise.
                    ds.ODMatrix = mat
                if code(ds) != row['dseg'] or mode_code(ds) != row['mode'] or matrix_no(ds.ODMatrix) != matrix_no(mat):
                    raise ReferenceError('DSEG_BINDING_READBACK_FAILED:' + row['dseg'])
                row['matrix_no'] = matrix_no(mat)
            # Verify sources and the complete four-target plan after all writes.
            preflight(visum, False)
            for key in SOURCE_DSEGS.values():
                if dseg_state(dsegs[key]) != states[key]:
                    raise ReferenceError('SOURCE_DSEG_CHANGED:' + key)
        with (audit_dir / 'MATRIX_DSEG_MAPPING.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        result['status'] = 'DRY_RUN_PASS' if dry_run else 'PASS_CREATED_AND_VERIFIED'
        write_json(audit_dir / '00_STATUS.json', result)
    except Exception:
        result['error'] = traceback.format_exc()
        if started:
            failures = rollback(visum, mats, dsegs, touched, states, created_matrix_nos, new_dseg_codes)
            result['rollback_errors'] = failures
            result['status'] = 'FAILED_ROLLBACK_UNVERIFIED_CANCEL_BASE_EDIT' if failures else 'FAILED_ROLLBACK_VERIFIED'
        write_json(audit_dir / '00_STATUS.json', result)
        print(result['status'], audit_dir)
        raise
    print(result['status'], audit_dir)
    return result


def main():
    visum = globals().get('Visum')
    if visum is None:
        visum = globals().get('COM')
    if visum is None:
        raise ReferenceError('RUN_INSIDE_VISUM_BASE_VERSION_WITH_EXISTING_VISUM_OR_COM')
    audit = Path(__file__).resolve().parent / 'R1_FREIGHT_2022_2025_AUDIT' / ('RUN_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    return run(visum, audit, DRY_RUN, CREATE_MISSING_MATRICES)


if __name__ == '__main__' or 'Visum' in globals() or 'COM' in globals():
    main()
