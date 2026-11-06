"""Refresh the existing PrT time skims before a TD impedance feedback step.

Only the configured reference DSeg's existing skim operation is executed.
No assignment, TG, TD, matrix creation or direct matrix-value writes occur here.
All temporary procedure/skim controls are restored and read back on every exit.
"""
from contextlib import contextmanager
from pathlib import Path

import numpy as np

import r1_15a2_acceleration_v24915p1 as perf
import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_runtime_v1 as rt
from r1_15a2_skim_v24916 import matrix_inventory
from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash
from r1_15a2_supply import SupplyContractError

RELEASE = 'R1_V24917_TD_IMPEDANCE_FRESH_SKIMS_20261106'


def _flag(obj, name):
    return bool(com.active_bool(obj.AttValue(name)))


@contextmanager
def _settings(edits):
    # Finish every read before the first write. Register ownership before a
    # setter that can mutate and then raise; restore all owned fields anyway.
    planned = [(obj, name, _flag(obj, name), bool(value)) for obj, name, value in edits]
    owned = []
    try:
        for obj, name, old, new in planned:
            if old == new:
                continue
            owned.append((obj, name, old))
            obj.SetAttValue(name, new)
            if _flag(obj, name) != new:
                raise SupplyContractError('IC_SKIM_SETTING_READBACK:' + name)
        yield
    finally:
        errors = []
        for obj, name, old in reversed(owned):
            try:
                obj.SetAttValue(name, old)
                if _flag(obj, name) != old:
                    raise RuntimeError('READBACK')
            except Exception as exc:
                errors.append(name + ':' + str(exc))
        if errors:
            raise SupplyContractError('IC_SKIM_SETTINGS_RESTORE_FAILED:' + ';'.join(errors))


def _bindings(visum, dseg, retry):
    rows = matrix_inventory(visum, retry)
    result = {}
    for code in ('DIS', 'TTC', 'TT0'):
        hits = [r for r in rows if r.get('matrix_code_norm') == code
                and core.norm_code(r.get('dseg_code_norm', '')) == dseg
                and r.get('matrix_no_int') is not None]
        if len(hits) != 1:
            raise SupplyContractError('IC_SKIM_BINDING_%s_%s_FOUND_%d' % (code, dseg, len(hits)))
        result[code] = int(hits[0]['matrix_no_int'])
    if len(set(result.values())) != 3:
        raise SupplyContractError('IC_SKIM_MATRIX_BINDINGS_OVERLAP')
    return result


def _read(visum, no, count, *, nonnegative=True):
    values = np.array(visum.Net.Matrices.ItemByKey(no).GetValues(), dtype=np.float64, copy=True)
    if values.shape != (count, count) or not np.isfinite(values).all() or (nonnegative and np.any(values < 0)):
        raise SupplyContractError('IC_SKIM_MATRIX_INVALID:' + str(no))
    return values


def refresh(adapter, dseg, folder):
    """Return native TTC/TT0 and evidence bound to the current assignment epoch."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    manager = getattr(adapter, 'v24916_dynamic_skims', None)
    if manager is None:
        raise SupplyContractError('IC_CURRENT_ASSIGNMENT_SKIM_MANAGER_REQUIRED')
    epoch = manager.require_current()
    zones = tuple(int(z) for z in adapter.zones)
    if ordered_zone_hash(zones) != epoch.zone_order_sha256:
        raise SupplyContractError('IC_SKIM_ZONE_ORDER_CHANGED')
    dseg = core.norm_code(dseg)
    meta = epoch.matrix_meta_by_dseg.get(dseg)
    if not meta:
        raise SupplyContractError('IC_CURRENT_DIS_EVIDENCE_REQUIRED:' + dseg)
    retry = getattr(adapter, 'com_retry_policy', None)
    bindings = _bindings(adapter.visum, dseg, retry)
    if bindings['DIS'] != int(meta['matrix_no']):
        raise SupplyContractError('IC_CURRENT_DIS_BINDING_CHANGED')
    if matrix_values_hash(_read(adapter.visum, bindings['DIS'], len(zones))) != meta['values_sha256']:
        raise SupplyContractError('IC_DIS_NOT_FROM_CURRENT_ASSIGNMENT')

    operations = com.operation_rows(adapter.visum)
    matches = []
    for row in operations:
        if not row['active'] or row['type'] != com.SKIMS_PRT:
            continue
        params = row['object'].PrTSkimMatrixParameters
        if core.norm_code(params.AttValue('DSeg')) == dseg:
            matches.append((row, params))
    if len(matches) != 1:
        raise SupplyContractError('IC_ACTIVE_REFERENCE_SKIM_OPERATION_FOUND_%d:%s' % (len(matches), dseg))
    row, params = matches[0]
    edits = [(params, 'UseExistingPaths', True), (params, 'OnlyRelationsWithDemand', False)]
    for name in ('T0', 'TCur'):
        single = params.SingleSkimMatrixParameters(name)
        edits.extend([(single, 'Calculate', True), (single, 'SaveToFile', False)])
    selected = [int(row['no'])] + [int(r['no']) for r in operations if r['active'] and r['type'] == com.GROUP]
    plan = {'block': 'TD_IMPEDANCE_SKIM_REFRESH', 'mode': 'EXISTING_PATH_SKIMS_ONLY',
            'selected_operation_positions': sorted(set(selected)), 'skim_dseg': dseg,
            'matrix_bindings': bindings, 'assignment_epoch': int(epoch.assignment_epoch),
            'assignment_token': str(epoch.assignment_token)}
    rt.write_json(folder / 'IC_TIME_SKIM_PLAN.json', plan)
    try:
        with _settings(edits):
            with perf.activate_operation_plan(adapter.visum, plan) as applied:
                rt.write_json(folder / 'IC_TIME_SKIM_PLAN_ACTIVE.json', applied)
                rt.execute_procseq(adapter.visum, folder)
        if manager.require_current() is not epoch:
            raise SupplyContractError('IC_ASSIGNMENT_EPOCH_CHANGED_DURING_SKIM_REFRESH')
        if _bindings(adapter.visum, dseg, retry) != bindings:
            raise SupplyContractError('IC_TIME_SKIM_BINDINGS_CHANGED_AFTER_EXECUTION')
        if matrix_values_hash(_read(adapter.visum, bindings['DIS'], len(zones))) != meta['values_sha256']:
            raise SupplyContractError('IC_DIS_CHANGED_WITHOUT_NEW_ASSIGNMENT_EPOCH')
        # Keep the existing impedance method's explicit no-path-cell policy:
        # finite nonpositive times are filtered there and retain the OSRM base.
        ttc = _read(adapter.visum, bindings['TTC'], len(zones), nonnegative=False)
        tt0 = _read(adapter.visum, bindings['TT0'], len(zones), nonnegative=False)
    except BaseException:
        # Native skim execution can partially replace derived results. Do not
        # let any caller reuse the old epoch as a current diagnostic authority.
        manager.current = None
        raise
    proof = dict(plan, status='FRESH_NATIVE_TIME_SKIMS', controls_restored=True,
                 ttc_sha256=matrix_values_hash(ttc), tt0_sha256=matrix_values_hash(tt0),
                 zone_order_sha256=epoch.zone_order_sha256, source='VISUM_EXISTING_ASSIGNMENT_PATHS',
                 assignment_executed=False, td_executed=False)
    rt.write_json(folder / 'IC_TIME_SKIM_PROOF.json', proof)
    return ttc, tt0, proof
