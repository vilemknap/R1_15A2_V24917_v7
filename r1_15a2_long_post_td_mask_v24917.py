"""User-approved LONG matrix multiplication with explicit loss of volume.

One native TD operation is retained for all its original strata. Execution is
paused after TD to clip 9111..9115, and before assignment to clip realized LONG
vehicle components and rebuild their aggregate. No P/A repair or normalization.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import functools

import numpy as np

from r1_15a2_long_distance_guard_v24917 import MATRIX_NOS, MIN_KM
from r1_15a2_long_profile_incidence_v24917 import COMPONENT_MATRICES, FINAL_MATRIX
from r1_15a2_long_support_distance_v24917 import read_current
from r1_15a2_skim_v24916p2c import matrix_values_hash
from r1_15a2_supply import SupplyContractError

_SCOPE = ContextVar('r1_long_mask_execution', default=None)


@contextmanager
def execution_scope(adapter):
    token = _SCOPE.set(adapter if getattr(adapter, '_long_post_td_mask_enabled', False) else None)
    try:
        yield
    finally:
        _SCOPE.reset(token)


def project(values, mask):
    """Exact elementwise multiplication; report actual marginal and total loss."""
    a = np.array(values, dtype=np.float64, copy=True)
    support = np.asarray(mask)
    if a.shape != support.shape or a.ndim != 2 or support.dtype != np.bool_:
        raise SupplyContractError('LONGMASK_SHAPE_OR_TYPE')
    if not np.isfinite(a).all() or np.any(a < 0):
        raise SupplyContractError('LONGMASK_INVALID_DEMAND')
    result = np.where(support, a, 0.)
    removed = a - result
    total = float(a.sum())
    return result, {'before_total': total, 'after_total': float(result.sum()),
                    'removed_total': float(removed.sum()),
                    'removed_share': float(removed.sum()) / total if total else 0.,
                    'removed_production_by_zone': removed.sum(axis=1).tolist(),
                    'removed_attraction_by_zone': removed.sum(axis=0).tolist(),
                    'pa_preserved': not bool(removed.any()), 'renormalized': False}


def _read(adapter, no):
    from r1_15a2_com_compat import com_call_with_retry
    retry = getattr(adapter, 'com_retry_policy', None) or {}
    obj = com_call_with_retry(lambda: adapter.visum.Net.Matrices.ItemByKey(no),
                             label='LONGMASK_MATRIX_%d' % no, retry_policy=retry)
    values = com_call_with_retry(obj.GetValues, label='LONGMASK_READ_%d' % no, retry_policy=retry)
    return obj, np.array(values, dtype=np.float64, copy=True)


def _invalidate(adapter):
    invalidate = getattr(adapter, 'invalidate_candidate_readback', None)
    if invalidate is not None:
        invalidate('LONG_POST_TD_MASK_MATRIX_WRITE', mutation=True)


def apply_group(adapter, mask, matrix_nos, folder, *, aggregate_no=None):
    """Validate the complete write plan, own partial writes, verify COM readback.

    On failure restore only this transformation's pre-write arrays and rethrow.
    The calibration transaction owner must then recompute its accepted parent.
    A successful call does not itself adopt or checkpoint a calibration state.
    """
    from r1_15a2_controller_v22 import atomic_json
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    expected = COMPONENT_MATRICES if aggregate_no is not None else MATRIX_NOS
    if tuple(matrix_nos) != tuple(expected) or aggregate_no not in (None, FINAL_MATRIX):
        raise SupplyContractError('LONGMASK_WRITE_SCOPE_NOT_AUTHORIZED')
    protected_obj, protected = _read(adapter, 9116)
    before, targets, objects, rows = {}, {}, {}, []
    for no in matrix_nos:
        obj, values = _read(adapter, int(no))
        target, record = project(values, mask)
        before[int(no)], targets[int(no)], objects[int(no)] = values, target, obj
        rows.append(dict(record, matrix_no=int(no), before_sha256=matrix_values_hash(values),
                         after_sha256=matrix_values_hash(target)))
    if aggregate_no is not None:
        obj, values = _read(adapter, aggregate_no)
        native_sum = np.sum([before[int(no)] for no in matrix_nos], axis=0)
        if values.shape != mask.shape or not np.allclose(values, native_sum, rtol=1e-10, atol=1e-6):
            raise SupplyContractError('LONGMASK_NATIVE_COMPONENT_AGGREGATE_PARITY')
        target = np.sum([targets[int(no)] for no in matrix_nos], axis=0)
        before[aggregate_no], targets[aggregate_no], objects[aggregate_no] = values, target, obj
    if protected.shape != mask.shape:
        raise SupplyContractError('LONGMASK_FOREIGN_SHAPE')
    report = {'policy': 'POST_TD_MULTIPLICATION_ACCEPT_VOLUME_LOSS',
              'minimum_km': MIN_KM, 'maximum_km': None, 'renormalized': False,
              'units': 'PERSON_TRIPS' if aggregate_no is None else 'VEHICLES',
              'zone_nos': list(adapter.zones), 'matrices': rows,
              'aggregate_rebuilt': aggregate_no, 'status': 'PLANNED'}
    atomic_json(folder / 'LONG_MASK_PLAN.json', report)
    owned = []
    try:
        for no in targets:
            if np.array_equal(before[no], targets[no]):
                continue
            owned.append(no)  # the COM write may mutate before raising
            _invalidate(adapter)
            objects[no].SetValues(targets[no].tolist())
            _, actual = _read(adapter, no)
            if not np.array_equal(actual, targets[no]):
                raise SupplyContractError('LONGMASK_READBACK_MISMATCH:%d' % no)
        _, foreign = _read(adapter, 9116)
        if not np.array_equal(foreign, protected):
            raise SupplyContractError('LONGMASK_FOREIGN_CHANGED')
        report.update(status='APPLIED_VERIFIED', written_matrix_nos=owned)
        atomic_json(folder / 'LONG_MASK_RESULT.json', report)
        return report
    except BaseException as exc:
        errors = []
        for no in reversed(owned):
            try:
                _invalidate(adapter)
                objects[no].SetValues(before[no].tolist())
                if not np.array_equal(_read(adapter, no)[1], before[no]):
                    raise SupplyContractError('RESTORE_READBACK')
            except BaseException as restore_exc:
                errors.append('%d:%r' % (no, restore_exc))
        try:
            if not np.array_equal(_read(adapter, 9116)[1], protected):
                errors.append('FROZEN_FOREIGN_CHANGED')
        except BaseException as check_exc:
            errors.append('FROZEN_FOREIGN_UNVERIFIED:' + repr(check_exc))
        report.update(status='PREMASK_RESTORED_CALIBRATION_PARENT_RECOMPUTE_REQUIRED' if not errors
                      else 'RESTORE_FAILED_MANUAL_REOPEN_REQUIRED', error=repr(exc), restore_errors=errors)
        try:
            atomic_json(folder / 'LONG_MASK_RESULT.json', report)
        except Exception as io_exc:
            if hasattr(exc, 'add_note'): exc.add_note('LONGMASK_EVIDENCE_FAILED:' + repr(io_exc))
        if errors:
            raise SupplyContractError('LONGMASK_RESTORE_FAILED_MANUAL_REOPEN_REQUIRED') from exc
        raise


def _verify_support(adapter, mask, matrix_nos):
    for no in matrix_nos:
        _, actual = _read(adapter, no)
        if (actual.shape != mask.shape or not np.isfinite(actual).all()
                or np.any(actual < 0) or np.any(actual[~mask] != 0)):
            raise SupplyContractError('LONGMASK_POST_ASSIGNMENT_SUPPORT_FAILED:%d' % no)



def _verify_assignment_scope(row, expected):
    """Fail closed on live partial/final PrT DSEGSET differences."""
    import re
    from r1_15a2_com_compat import object_property
    from r1_15a2_core import norm_code
    position = int(row['no'])
    try:
        params = object_property(row['object'], 'PrTAssignmentParameters')
        raw = params.AttValue('DSEGSET')
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError('EMPTY_DSEGSET')
        parts = [norm_code(p.strip("'\\\"")) for p in re.split(r'[,;{}\s]+', raw) if p.strip("'\\\"")]
        if not parts or len(parts) != len(set(parts)):
            raise ValueError('DUPLICATE_OR_EMPTY_DSEGSET')
    except Exception as exc:
        raise SupplyContractError('LONGMASK_ASSIGNMENT_DSEG_SCOPE_UNREADABLE:%d' % position) from exc
    if set(parts) != {norm_code(str(x)) for x in expected}:
        raise SupplyContractError('LONGMASK_ASSIGNMENT_DSEG_SCOPE_MISMATCH:%d' % position)


def execute_sequence(adapter, folder, original_execute):
    """Keep operation definitions/positions intact; scope only existing ACTIVE flags."""
    from r1_15a2_com_compat import operation_rows, TD, GROUP, ASSIGNMENT_PRT
    from r1_15a2_acceleration_v24915p1 import activate_operation_plan
    from r1_15a2_controller_v22 import atomic_json
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    distance, source = read_current(adapter)
    mask = distance >= MIN_KM
    inventory = operation_rows(adapter.visum)
    active = [row for row in inventory if row['active']]
    groups = {int(row['no']) for row in active if int(row['type']) == GROUP}
    leaves = [row for row in active if int(row['type']) != GROUP]
    td = [int(row['no']) for row in leaves if int(row['type']) == TD]
    assignments = [int(row['no']) for row in leaves if int(row['type']) == ASSIGNMENT_PRT]
    # Operation 20 alone is the approved *final* 14-DSeg count/GAP authority.
    # Native 09C also has three earlier, independently scoped PrT assignments
    # (17/18/19). They are execution prerequisites, NOT alternative final
    # authorities. A strict subset check against the final authority rejects
    # the approved live 09C sequence before its first baseline recomputation.
    rules = (getattr(adapter, 'cfg', {}) or {}).get('supply', {}).get('assignment_operations', [])
    approved = {int(rule['no']) for rule in rules}
    active_assignments = set(assignments)
    if assignments and (not approved or len(approved) != len(rules)
                        or not approved <= active_assignments
                        or any(int(rule.get('operation_type', -1)) != ASSIGNMENT_PRT
                               for rule in rules)):
        raise SupplyContractError('LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH')
    partial = active_assignments - approved
    if partial:
        # Audited R1 09C prerequisite scopes (V239/V240). Reject any additional
        # assignment, reordered final authority, missing active final 20 or
        # mutated live DSEGSET before toggling ACTIVE or writing any matrix.
        expected_partial = {
            17: {'LNV', 'NV'},
            18: {'NATIVE_CF', 'NATIVE_CL'},
            19: {'NATIVE_CS', 'NATIVE_CS_NOT', 'NATIVE_CW', 'NATIVE_CW_NOT'},
        }
        if approved != {20} or not partial <= set(expected_partial):
            raise SupplyContractError('LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH')
        by_no = {int(row['no']): row for row in leaves}
        for position in sorted(partial):
            if position >= 20:
                raise SupplyContractError('LONGMASK_ASSIGNMENT_AUTHORITY_MISMATCH')
            _verify_assignment_scope(by_no[position], expected_partial[position])
    if assignments:
        # An active final PrT operation must match its configured DSEGSET,
        # even in the supply-only path (where no partial 17-19 are active).
        by_no = {int(row['no']): row for row in leaves}
        for rule in rules:
            expected_final = rule.get('expected_dsegs', [])
            if not expected_final:
                if partial:
                    raise SupplyContractError('LONGMASK_FINAL_ASSIGNMENT_SCOPE_AUTHORITY_MISSING')
                # Legacy miniature unit-test harnesses omit DSEGSET authority;
                # real V24917 checks it in assignment_plan() before supply.
                continue
            _verify_assignment_scope(by_no[int(rule['no'])], expected_final)
    if len(td) > 1:
        raise SupplyContractError('LONGMASK_EXPECTED_ONE_UNIFIED_TD_OPERATION')
    boundary = min(assignments) if assignments else None
    if not td:
        _verify_support(adapter, mask, MATRIX_NOS + COMPONENT_MATRICES + (FINAL_MATRIX,))
        realization = [int(row['no']) for row in leaves if boundary is not None and int(row['no']) < boundary]
        if not realization:
            result = original_execute(adapter.visum, folder)
            _verify_support(adapter, mask, MATRIX_NOS + COMPONENT_MATRICES + (FINAL_MATRIX,))
            return result
        # SupplyMix cold recomputation can re-run 20A/20B on unchanged masked
        # person demand. Remove any repaired reverse support before assignment.
        phases = [('REALIZATION', realization),
                  ('ASSIGNMENT_SKIMS', [int(row['no']) for row in leaves if int(row['no']) >= boundary])]
    elif boundary is not None and boundary <= td[0]:
        raise SupplyContractError('LONGMASK_ASSIGNMENT_BEFORE_TD')
    elif boundary is None and any(int(row['no']) > td[0] for row in leaves):
        raise SupplyContractError('LONGMASK_DOWNSTREAM_WITHOUT_ASSIGNMENT')
    elif td:
        phases = [('THROUGH_TD', [int(row['no']) for row in leaves if int(row['no']) <= td[0]])]
    if td and boundary is not None:
        realization = [int(row['no']) for row in leaves if td[0] < int(row['no']) < boundary]
        if not realization:
            raise SupplyContractError('LONGMASK_REALIZATION_OPERATIONS_MISSING')
        phases += [('REALIZATION', realization),
                   ('ASSIGNMENT_SKIMS', [int(row['no']) for row in leaves if int(row['no']) >= boundary])]
    atomic_json(folder / 'LONG_MASK_EXECUTION_PLAN.json',
                {'source': source, 'phases': phases, 'td_operation_position': td[0] if td else None,
                 'final_assignment_authority': sorted(approved),
                 'validated_partial_assignments': sorted(partial),
                 'operation_definitions_unchanged': True, 'volume_loss_accepted': True})
    result = None
    for name, positions in phases:
        plan = {'selected_operation_positions': sorted(set(positions) | groups)}
        with activate_operation_plan(adapter.visum, plan):
            result = original_execute(adapter.visum, folder / name)
        read_current(adapter)  # fixed source/zone identity may not drift
        if name == 'THROUGH_TD':
            apply_group(adapter, mask, MATRIX_NOS, folder / 'MASK_PERSON_LONG')
        elif name == 'REALIZATION':
            apply_group(adapter, mask, COMPONENT_MATRICES, folder / 'MASK_VEHICLE_LONG',
                        aggregate_no=FINAL_MATRIX)
        else:
            _verify_support(adapter, mask, MATRIX_NOS + COMPONENT_MATRICES + (FINAL_MATRIX,))
    return result


def install(rt):
    old = rt.execute_procseq
    if not getattr(old, '_long_post_td_mask', False):
        @functools.wraps(old)
        def execute(visum, folder):
            adapter = _SCOPE.get()
            if adapter is None or adapter.visum is not visum:
                return old(visum, folder)
            return execute_sequence(adapter, folder, old)
        execute._long_post_td_mask = True
        rt.execute_procseq = execute
    import r1_15a2_finecdf_bridge_v24916 as bridge
    old_bridge = bridge.NoDirectMatrixWriteTDAdapter.execute
    if not getattr(old_bridge, '_long_post_td_scope', False):
        @functools.wraps(old_bridge)
        def execute_inner(self):
            with execution_scope(getattr(self, 'outer_adapter', None)):
                return old_bridge(self)
        execute_inner._long_post_td_scope = True
        bridge.NoDirectMatrixWriteTDAdapter.execute = execute_inner
    return {'installed': True, 'method': 'POST_TD_MULTIPLICATION_ACCEPT_VOLUME_LOSS',
            'minimum_km': MIN_KM, 'maximum_km': None, 'native_od_filter_required': False,
            'person_matrices': list(MATRIX_NOS), 'vehicle_matrices': list(COMPONENT_MATRICES),
            'vehicle_aggregate': FINAL_MATRIX}
