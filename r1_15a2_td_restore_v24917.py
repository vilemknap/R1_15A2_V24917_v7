"""One-use proof for a consecutive restore of the same native TD best state.

The first restore always runs the original native recomputation and comparison.
A subsequent request may reuse it only after new live content/source reads and
an unchanged completed assignment/skim binding. Missing evidence uses the
original restore; actual source/guard failures propagate to the transaction.
No rejected candidate or outer live acceptance is skipped.
"""
from __future__ import annotations

import functools
import math
from contextlib import contextmanager
from pathlib import Path
import time

import numpy as np
import r1_15a2_dynamic_skim_v24916p2c as dyn
import r1_15a2_finecdf_bridge_v24916 as bridge
import r1_15a2_long_composite_td_v24917 as long_td
import r1_15a2_school_td_v24917 as school_td
import r1_15a2_td_numpy_v24917 as kernels
import r1_15a2_snapshot_reads_v24917 as snapshot_reads
from r1_15a2_supply import canonical_hash, SupplyContractError

RELEASE = 'R1_V24917_TD_CONSECUTIVE_RESTORE_PROOF_REVIEW1_20261030'
_MISSING = object()


@contextmanager
def matrix_read_scope(adapter):
    """Share only post-execution reads within a single proof, never a write."""
    original = adapter.read_matrix
    previous = adapter.__dict__.get('read_matrix', _MISSING)
    arrays = {}
    def read(no):
        no = int(no)
        if no not in arrays:
            arrays[no] = original(no)
        return arrays[no]
    adapter.read_matrix = read
    try:
        yield
    finally:
        if previous is _MISSING:
            del adapter.read_matrix
        else:
            adapter.read_matrix = previous


def binding(adapter):
    outer = getattr(adapter, 'outer_adapter', None)
    manager = getattr(outer, 'v24916_dynamic_skims', None)
    rm = getattr(outer, 'readback_manager', None)
    if (not getattr(adapter, 'dynamic_skim_enabled', False)
            or getattr(adapter, '_v24917_frozen', False) or manager is None or rm is None
            or getattr(rm, 'assignment_in_progress', True)
            or getattr(rm, 'assignment_completed', False) is not True
            or kernels.SKIM_WEIGHT_SCOPE.get() is not None
            or getattr(outer, '_v24917_generation_reads', None) is not None
            or getattr(adapter, 'v', None) is not getattr(outer, 'visum', None)):
        return None
    if not all(isinstance(getattr(rm, name, None), str) and getattr(rm, name)
               for name in ('run_token', 'visum_session_token')):
        return None
    try:
        epoch = manager.require_current()
    except SupplyContractError:
        return None  # Native restore must refresh an unavailable/stale skim.
    if epoch is not getattr(adapter, 'dynamic_skim_epoch', None):
        return None
    plan = adapter._dynamic_realization_plan()
    if plan is None or set(epoch.matrix_meta_by_dseg) != set(dyn.REQUIRED_NATIVE_DSEGS):
        return None
    adapter.assert_isolated()
    live_zones = tuple(int(v) for _, v in adapter.v.Net.Zones.GetMultiAttValues('NO'))
    if live_zones != tuple(adapter.zone_order) or live_zones != tuple(outer.zones):
        raise SupplyContractError('TD_PERF_RESTORE_ZONE_ORDER_CHANGED')
    if dyn.ordered_zone_hash(live_zones) != epoch.zone_order_sha256:
        raise SupplyContractError('TD_PERF_RESTORE_ZONE_HASH_CHANGED')
    if epoch.assignment_epoch != rm.assignment_epoch:
        return None
    # Pin actual current procedure types/ACTIVE/DSTRATSET as well as the plan.
    operations = dyn._call(outer, lambda: snapshot_reads._operation_records(adapter.v),
                           'TD_RESTORE_OPERATION_SOURCES')
    position = adapter.td_index
    if (type(position) is not int or not 1 <= position <= len(operations)
            or operations[position - 1].operation_type != 46):
        raise SupplyContractError('TD_PERF_RESTORE_TD_OPERATION_CHANGED')
    live_td = dyn._call(outer,
        lambda: bridge.com.object_property(operations[position - 1].obj, 'TripDistributionParameters'),
        'TD_RESTORE_LIVE_TD_ROOT')
    live_dset = str(dyn._call(outer, lambda: live_td.AttValue('DSTRATSET'), 'TD_RESTORE_LIVE_DSTRATSET'))
    cached_dset = str(dyn._call(outer, lambda: adapter.td.AttValue('DSTRATSET'), 'TD_RESTORE_DSTRATSET'))
    if bridge.com.code_set(live_dset) != bridge.com.code_set(cached_dset):
        raise SupplyContractError('TD_PERF_RESTORE_TD_DSTRATSET_CHANGED')
    controls = [(op.position, op.operation_type, op.active, op.comment, op.name) for op in operations]
    payload = {'assignment_epoch': rm.assignment_epoch, 'mutation_epoch': rm.mutation_epoch,
        'run_token': rm.run_token, 'visum_session_token': rm.visum_session_token,
        'epoch': epoch.summary(), 'plan': plan, 'controls': controls,
        'dstratset': live_dset, 'groups': list(adapter.ref.GROUPS),
        'long_mask_enabled': getattr(outer, '_long_post_td_mask_enabled', False),
        'gap_evidence': getattr(outer, 'last_gap_evidence', None)}
    return {'epoch': epoch, 'manager': manager, 'readback': rm, 'td_root': live_td,
            'sha256': canonical_hash(payload)}


def requested_state(adapter, abc, matrices):
    return canonical_hash({'abc': abc, 'matrices': {
        int(no): adapter.ref.sha_array(a) for no, a in matrices.items()}})


def matrix_source(adapter, matrix, expected_no=None):
    owner = adapter.outer_adapter
    no = bridge.com.exact_int(dyn._call(owner, lambda: matrix.AttValue('NO'),
                                       'TD_RESTORE_MATRIX_NO'), 'RESTORE_MATRIX_NO')
    if no <= 0 or (expected_no is not None and no != expected_no):
        raise SupplyContractError('TD_PERF_RESTORE_MATRIX_IDENTITY_CHANGED')
    code = dyn._call(owner, lambda: matrix.AttValue('CODE'), 'TD_RESTORE_MATRIX_CODE')
    return {'matrix_no': no, 'matrix_code': str(code)}


def demand_sources(adapter, expected_codes):
    """Strict metadata read, independent of the Generation array cache."""
    result = {}
    rows = dyn._call(adapter.outer_adapter,
        lambda: snapshot_reads._dseg_bindings(adapter.outer_adapter.visum), 'TD_RESTORE_DEMAND_SOURCES')
    for row in rows:
        code = row['norm_code']
        if code not in expected_codes:
            continue
        if code in result:
            raise SupplyContractError('TD_PERF_RESTORE_DUPLICATE_DEMAND_SOURCE:' + code)
        matrix = dyn._call(adapter.outer_adapter,
            lambda: bridge.com.object_property(row['object'], 'ODMatrix'), 'TD_RESTORE_OD_BINDING:' + code)
        result[code] = matrix_source(adapter, matrix, row['matrix_no'])
    if set(result) != expected_codes:
        raise SupplyContractError('TD_PERF_RESTORE_DEMAND_SOURCE_SCOPE_CHANGED')
    return result


def content(adapter, bound, requested_abc, arrays=None, *, read_skims=False, verify_requested=True):
    # All reads below are after the completed native operation. Scope is closed
    # before any fallback recomputation or parameter mutation can occur.
    with matrix_read_scope(adapter):
        adapter.guard_protected(full=True)
        # The current operation may expose a replacement parameter object.
        # Read it with the original accessor, then restore only our Python
        # handle; no native parameter/control write occurs in this scope.
        cached_td = adapter.td
        adapter.td = bound['td_root']
        try:
            actual_abc = adapter.read_abc()
        finally:
            adapter.td = cached_td
        if verify_requested and set(actual_abc) != set(requested_abc):
            raise SupplyContractError('TD_PERF_RESTORE_PARAMETER_SCOPE_CHANGED')
        tolerance = float(adapter.ref.CONFIG['parameter_readback_atol'])
        for no in requested_abc if verify_requested else ():
            for parameter in ('a', 'b', 'c'):
                value = float(actual_abc[no][parameter])
                if (not math.isfinite(value)
                        or abs(value - float(requested_abc[no][parameter])) > tolerance):
                    raise SupplyContractError('TD_PERF_RESTORE_PARAMETER_CHANGED_M%d_%s' % (no, parameter))
        outputs = adapter.read_outputs() if arrays is None else arrays
        protected = {no: adapter.ref.sha_array(adapter.read_matrix(no)) for no in (9001, 9002, 9697, 9116)}
    generation = {}
    if school_td.GROUP in adapter.ref.GROUPS:
        generation['SCHOOL'] = school_td.generation_snapshot(adapter)
    if long_td.GROUP in adapter.ref.GROUPS:
        generation['LONG'] = long_td.generation_snapshot(adapter)
    flows = adapter.outer_adapter._live_generation_matrices()
    expected_codes = {bridge.rt.norm_code(x) for x in adapter.outer_adapter.cfg['path_export_dsegs']}
    if set(flows) != expected_codes:
        raise SupplyContractError('TD_PERF_RESTORE_DEMAND_SCOPE_CHANGED')
    sources = demand_sources(adapter, expected_codes)
    protected_sources = {}
    for no in (9001, 9002, 9697, 9116):
        matrix = dyn._call(adapter.outer_adapter, lambda: adapter.v.Net.Matrices.ItemByKey(no),
                           'TD_RESTORE_PROTECTED_SOURCE:%d' % no)
        protected_sources[no] = matrix_source(adapter, matrix, no)
    epoch = bound['epoch']
    skims, skim_sources = {}, {}
    live_rows = dyn._native_dis_rows(adapter.outer_adapter) if read_skims else None
    for dseg in dyn.REQUIRED_NATIVE_DSEGS:
        meta = epoch.matrix_meta_by_dseg[dseg]
        if read_skims:
            row = live_rows[dseg]
            no = int(row['matrix_no_int'])
            skim_sources[dseg] = {'matrix_no': no, 'matrix_code': str(row.get('matrix_code', 'DIS')),
                                  'dseg_code': str(row.get('dseg_code', dseg))}
            a = dyn._matrix_values(adapter.outer_adapter, no, len(adapter.zone_order), 'RESTORE:' + dseg)
            skims[dseg] = kernels.matrix_values_hash(a)
        else:
            # The original native restore just created this epoch. Verification
            # of a reuse request below re-reads the actual six DIS matrices.
            skims[dseg] = meta['values_sha256']
            skim_sources[dseg] = {key: meta[key] for key in ('matrix_no', 'matrix_code', 'dseg_code')}
    result = {'abc': actual_abc, 'outputs': {int(n): adapter.ref.sha_array(a) for n, a in outputs.items()},
        'protected': protected, 'generation': generation,
        'demand_sources': sources, 'protected_sources': protected_sources, 'skim_sources': skim_sources,
        'demand': {code: adapter.ref.sha_array(a) for code, a in flows.items()}, 'skims': skims,
        'cached_skims': {d: adapter.ref.sha_array(a) for d, a in epoch.matrices_by_dseg.items()},
        'cached_family_distance': {family: adapter.ref.sha_array(a) for family, a in epoch.family_distance.items()}}
    after = binding(adapter)
    if (after is None or after['epoch'] is not epoch or after['manager'] is not bound['manager']
            or after['readback'] is not bound['readback'] or after['sha256'] != bound['sha256']):
        raise SupplyContractError('TD_PERF_RESTORE_STATE_CHANGED_DURING_PROOF')
    return canonical_hash(result), outputs


def audit(adapter, status, seconds):
    state = getattr(adapter, '_td_perf_restore_audit', None)
    if state is None:
        state = adapter._td_perf_restore_audit = {'release': RELEASE, 'native_restores': 0,
            'verified_reuses': 0, 'events': [], 'direct_od_matrix_writes': False,
            'outer_acceptance_skipped': False}
    state['native_restores' if status.startswith('NATIVE_') else 'verified_reuses'] += 1
    state['events'].append({'status': status, 'seconds': round(seconds, 6),
        'dynamic_eval_index': getattr(adapter, 'dynamic_eval_index', None)})
    bridge.rt.write_json(Path(adapter.root) / 'TD_PERF_RESTORE_AUDIT.json', state)


def wrap_restore(original):
    @functools.wraps(original)
    def restore(adapter, abc, matrices):
        started = time.monotonic()
        receipt = getattr(adapter, '_td_perf_restore_receipt', None)
        # Consume first: an exception or failed proof can never leave authority.
        adapter._td_perf_restore_receipt = None
        bound = binding(adapter)
        signature = requested_state(adapter, abc, matrices) if bound is not None else None
        if (receipt is not None and bound is not None and receipt['request'] == signature
                and receipt['bound']['epoch'] is bound['epoch']
                and receipt['bound']['manager'] is bound['manager']
                and receipt['bound']['readback'] is bound['readback']
                and receipt['bound']['sha256'] == bound['sha256']):
            fingerprint, live = content(adapter, bound, abc, read_skims=True, verify_requested=False)
            if fingerprint == receipt['content']:
                # Compare to the actual requested matrices too, preserving the
                # original per-cell rollback tolerance and fail-closed behavior.
                for no, expected in matrices.items():
                    if not np.allclose(live[int(no)], expected, rtol=1.e-10, atol=1.e-8, equal_nan=False):
                        raise SupplyContractError('TD_PERF_RESTORE_REQUESTED_MATRIX_DIFFER_M%d' % int(no))
                audit(adapter, 'VERIFIED_CONSECUTIVE_REUSE', time.monotonic() - started)
                return live
        result = original(adapter, abc, matrices)
        bound = binding(adapter)
        pending_receipt = None
        if bound is not None:
            signature = requested_state(adapter, abc, matrices)
            fingerprint, _ = content(adapter, bound, abc, result)
            pending_receipt = {'bound': bound, 'request': signature, 'content': fingerprint}
        audit(adapter, 'NATIVE_RESTORE_VERIFIED', time.monotonic() - started)
        # Publication is last: a failed forensic write cannot leave authority
        # for another restore even though the native computation completed.
        adapter._td_perf_restore_receipt = pending_receipt
        return result
    restore._td_perf_restore = True
    return restore


def invalidate_on_call(original):
    @functools.wraps(original)
    def call(adapter, *args, **kwargs):
        adapter._td_perf_restore_receipt = None
        return original(adapter, *args, **kwargs)
    call._td_perf_restore_invalidate = True
    return call


def install():
    cls = bridge.NoDirectMatrixWriteTDAdapter
    if not getattr(cls.restore_state, '_td_perf_restore', False):
        cls.restore_state = wrap_restore(cls.restore_state)
    for name in ('set_abc', 'execute'):
        original = getattr(cls, name)
        if not getattr(original, '_td_perf_restore_invalidate', False):
            setattr(cls, name, invalidate_on_call(original))
    return {'installed': True, 'release': RELEASE, 'reuse_scope': 'ONE_CONSECUTIVE_VERIFIED_RESTORE',
            'missing_evidence': 'ORIGINAL_NATIVE_RECOMPUTATION', 'outer_acceptance_changed': False}
