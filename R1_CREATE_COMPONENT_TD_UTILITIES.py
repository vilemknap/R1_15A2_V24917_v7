# -*- coding: utf-8 -*-
"""Run in the open Visum model: create/bind the 16 component TD utilities.

Requires the existing M9002 base. No procedure, assignment or version save runs.
Existing owned component matrices are preserved, including their corrections.
On failure, restore all owned parameter setters and remove only newly created
matrices. Run from the complete release folder, then save your model copy.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import r1_15a2_component_td_utilities_v24917 as utilities
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError

DRY_RUN = False
BASE_NO = 9002


def run(visum, folder, dry_run=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    zone_order = utilities.zones(visum)
    n = len(zone_order)
    numbers = {int(v) for _, v in visum.Net.Matrices.GetMultiAttValues('NO')}
    if BASE_NO not in numbers:
        raise SupplyContractError('TD_UTILITY_BASE_M9002_MISSING')
    base_obj = visum.Net.Matrices.ItemByKey(BASE_NO)
    object_type = utilities.enum_id(base_obj.AttValue('OBJECTTYPEREF'), 'OBJECTTYPEREF')
    matrix_type = utilities.enum_id(base_obj.AttValue('MATRIXTYPE'), 'MATRIXTYPE')
    utilities.enum_id(base_obj.AttValue('DATASOURCETYPE'), 'DATASOURCETYPE')
    base = utilities.array(base_obj.GetValues(), n)
    handles = utilities.utility_handles(visum)
    existing = {}
    # Complete all collision/reference/type checks before creating anything.
    for row in utilities.MAPPING:
        obj, attr, raw = handles[row['component']]
        if utilities.ref_no(raw) not in (BASE_NO, row['utility_no']):
            raise SupplyContractError('TD_UTILITY_SETUP_UNEXPECTED_PARENT:' + row['component'])
        if row['utility_no'] in numbers:
            matrix = utilities.metadata(visum, row, BASE_NO)
            values = utilities.array(matrix.GetValues(), n)
            if not np.array_equal(np.diag(values), np.diag(base)):
                raise SupplyContractError('TD_UTILITY_SETUP_EXISTING_DIAGONAL_MISMATCH:%s' % row['utility_no'])
            existing[row['utility_no']] = matrix
        elif utilities.ref_no(raw) == row['utility_no']:
            raise SupplyContractError('TD_UTILITY_SETUP_DANGLING_REFERENCE:' + row['component'])
    code_rows = visum.Net.Matrices.GetMultiAttValues('CODE')
    no_rows = visum.Net.Matrices.GetMultiAttValues('NO')
    if [k for k, _ in code_rows] != [k for k, _ in no_rows]:
        raise SupplyContractError('TD_UTILITY_SETUP_INVENTORY_ORDER_CHANGED')
    codes = {}
    for (_, code), (_, no) in zip(code_rows, no_rows):
        codes.setdefault(str(code), []).append(int(no))
    for row in utilities.MAPPING:
        found = codes.get(row['utility_code'], [])
        if found and found != [row['utility_no']]:
            raise SupplyContractError('TD_UTILITY_SETUP_CODE_COLLISION:' + row['utility_code'])
    report = {'release': utilities.RELEASE, 'dry_run': bool(dry_run), 'base_matrix_no': BASE_NO,
              'base_sha256': utilities.matrix_values_hash(base),
              'zone_order_sha256': utilities.ordered_zone_hash(zone_order),
              'mapping': [dict(row) for row in utilities.MAPPING], 'existing_preserved': sorted(existing),
              'assignment_executed': False, 'td_executed': False, 'version_saved': False,
              'status': 'PREFLIGHT_OK'}
    rt.write_json(folder / 'COMPONENT_TD_UTILITY_SETUP.json', report)
    if dry_run:
        return report
    created, changed = [], []
    try:
        for row in utilities.MAPPING:
            no = row['utility_no']
            if no in existing:
                continue
            created.append(no)  # AddMatrix itself may partially succeed.
            matrix = visum.Net.AddMatrix(no, object_type, matrix_type)
            matrix.SetAttValue('CODE', row['utility_code'])
            matrix.SetAttValue('NAME', 'R1 TD utility ' + row['component'] + ' = M9002 + native skim correction')
            utilities.metadata(visum, row, BASE_NO)
            matrix.SetValues(base.tolist())
            if not np.array_equal(utilities.array(matrix.GetValues(), n), base):
                raise SupplyContractError('TD_UTILITY_SETUP_COPY_READBACK:%s' % no)
        for row in utilities.MAPPING:
            handle = handles[row['component']]
            obj, attr, old = handle
            if utilities.ref_no(old) == row['utility_no']:
                continue
            changed.append(handle)
            obj.SetAttValue(attr, 'Matrix([NO]=%d)' % row['utility_no'])
            if utilities.ref_no(obj.AttValue(attr)) != row['utility_no']:
                raise SupplyContractError('TD_UTILITY_SETUP_BINDING_READBACK:' + row['component'])
        # Re-read fresh parameter handles; never trust the old COM accessor alone.
        live = utilities.utility_handles(visum)
        if any(utilities.ref_no(live[r['component']][2]) != r['utility_no'] for r in utilities.MAPPING):
            raise SupplyContractError('TD_UTILITY_SETUP_FINAL_BINDING_MISMATCH')
        if utilities.zones(visum) != zone_order or not np.array_equal(np.array(base_obj.GetValues()), base):
            raise SupplyContractError('TD_UTILITY_SETUP_BASE_OR_ZONES_CHANGED')
        report.update(status='CREATED_AND_BOUND', created=created, changed_bindings=len(changed))
        rt.write_json(folder / 'COMPONENT_TD_UTILITY_SETUP.json', report)
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
        # A failed binding restore must not leave a dangling reference by
        # removing its matrix; retain the staging objects and report explicitly.
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
        report.update(status='RESTORE_UNVERIFIED' if errors else 'FAILED_RESTORED',
                      error=repr(original), restoration_errors=errors)
        rt.write_json(folder / 'COMPONENT_TD_UTILITY_SETUP.json', report)
        if errors:
            raise SupplyContractError('TD_UTILITY_SETUP_RESTORE_UNVERIFIED:' + ';'.join(errors)) from original
        raise


def main():
    visum = globals().get('Visum')
    if visum is None:
        raise RuntimeError('Spustte ve Visumu: Scripts -> Run script file; zadne nove COM pripojeni se nevytvari.')
    folder = ROOT / 'COMPONENT_TD_UTILITY_SETUP_AUDIT'
    report = run(visum, folder, DRY_RUN)
    print('R1 komponentni utility TD: ' + report['status'])
    print('M9002 zustava spolecnym zakladem. M9700-9715 patri 16 nativnim komponentam; FOREIGN se nemeni.')
    print('Korekce TTC/TT0 obnovuje kalibrator pred TD, nikoli tento jednorazovy setup.')
    print('Ulozte kopii verze a kalibraci spustte launcherem z tohoto celeho balicku.')
    print('Audit: ' + str(folder))


if __name__ == '__main__' or globals().get('Visum') is not None:
    main()
