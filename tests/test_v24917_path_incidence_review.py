"""Incidence integrity, independent numerical parity and bounded reuse proofs."""
import copy
import sqlite3

import numpy as np
import pytest

import r1_15a2_path_incidence_v24917 as common
import r1_15a2_long_cache_generation_v24917 as lc
import r1_15a2_long_zonal_fit_v24917 as lf
import r1_15a2_snapshot_reads_v24917 as snapshots
from r1_15a2_skim_v24916p2c import matrix_values_hash as reference_hash
from test_v24917_long_cache_generation import live
from test_v24917_long_zonal_fit import _inputs


@pytest.mark.parametrize('layout', ['C', 'F', 'slice', 'empty', 'extremes'])
def test_hash_protocol_exactly_matches_existing_authority(layout):
    rng = np.random.default_rng(99)
    a = rng.normal(size=(73, 115))
    if layout == 'F': a = np.asfortranarray(a)
    if layout == 'slice': a = a[::-2, ::3]
    if layout == 'empty': a = np.empty((2, 0))
    if layout == 'extremes':
        a = np.array([[0., -0., np.nextafter(0., 1.), -np.nextafter(0., 1.),
                       np.finfo(float).max, np.finfo(float).tiny, -1.], [1., 2., 3., 4., 5., 6., 7.]])
    assert common.matrix_values_hash(a) == reference_hash(a)


@pytest.mark.parametrize('fault', ['fraction', 'negative', 'out_of_range', 'short', 'nan', 'two_dimensional'])
def test_work_service_rejects_malformed_incidence_instead_of_truncating_or_filtering(fault):
    from test_v24917_targeted_catchup import synthetic_incidence, all_bounds
    import r1_15a2_zonal_count_fit_v24917 as zf
    inc, zones = synthetic_incidence(n_zones=6)
    op = inc['incidence']
    if fault == 'fraction': op.col_idx = op.col_idx.astype(float); op.col_idx[0] = .5
    elif fault == 'negative': op.row_idx[0] = -1
    elif fault == 'out_of_range': op.row_idx[0] = len(inc['profiles'])
    elif fault == 'short': op.values = op.values[:-1]
    elif fault == 'nan': op.values[0] = np.nan
    else: op.values = op.values.reshape(-1, 1)
    with pytest.raises(ValueError, match='PATH_INCIDENCE'):
        zf.build_problem(inc, zones, all_bounds(zones), {})


def test_long_rejects_fractional_sparse_index_and_duplicate_od():
    observed, ws, solution, zones, bounds = _inputs()
    observed['incidence'].row_idx = np.array([.9, 1.])
    with pytest.raises(ValueError, match='INDEX_INVALID'):
        lf.build_problem(observed, ws, solution, zones, bounds)
    observed, ws, solution, zones, bounds = _inputs()
    observed['variables'].append(copy.deepcopy(observed['variables'][0]))
    observed['vehicle_total'] += 200.
    observed['vehicle_production'][0] += 200.
    observed['vehicle_attraction'][0] += 200.
    observed['incidence'].n_cols += 1
    with pytest.raises(ValueError, match='DUPLICATE_OD'):
        lf.build_problem(observed, ws, solution, zones, bounds)


def test_long_numpy_effect_matches_scalar_with_repeated_entries_and_reordered_profiles():
    observed, ws, solution, zones, bounds = _inputs()
    rng = np.random.default_rng(59)
    op = observed['incidence']
    op.row_idx = rng.integers(0, 2, 1000)
    op.col_idx = rng.integers(0, 2, 1000)
    op.values = rng.uniform(0., 10., 1000)
    ws.profile_rows.reverse(); ws.target = ws.target[::-1]; ws.weight = ws.weight[::-1]
    p = lf.build_problem(observed, ws, solution, zones, bounds)
    scalar = np.zeros_like(p.G); through = np.zeros(2)
    row_of = {r['profile_index']: i for i, r in enumerate(ws.profile_rows)}
    k_of = {k: i for i, k in enumerate(p.var_keys)}
    for row, col, v in zip(op.row_idx, op.col_idx, op.values):
        i = row_of[row]; meta = observed['variables'][col]; through[i] += v
        scalar[i, k_of['LONG', 'PROD', meta['origin']]] += v
        scalar[i, k_of['LONG', 'ATT', meta['destination']]] += v
    norm = np.array([.5 * observed['vehicle_production' if role == 'PROD' else 'vehicle_attraction'][z-1]
                     / observed['vehicle_total'] for _, role, z in p.var_keys])
    scalar -= np.outer(through, norm)
    np.testing.assert_array_equal(p.G, scalar)


def test_only_frozen_sql_basis_reused_live_od_and_flows_read_each_time(live):
    adapter, state, _ = live
    queries = []; adapter.cache.db.set_trace_callback(queries.append)
    first = lc.capture(adapter)
    assert not first['basis_reused']
    first_groupings = sum('GROUP BY' in q for q in queries)
    for no in lc.longinc.COMPONENT_MATRICES + (9305,): state.arrays[no] *= 2.
    state.profile_flow = {k: 2*v for k, v in state.profile_flow.items()}
    second = lc.capture(adapter)
    assert second['basis_reused'] and sum('GROUP BY' in q for q in queries) == first_groupings == 2
    assert second['profile_long_vehicle_flow'] == pytest.approx(2*first['profile_long_vehicle_flow'])
    assert all(not a.flags.writeable for a in adapter.cache._v24917_long_basis[3].values())
    assert len(state.matrix_reads) >= 24  # independent before/after live sets remain


@pytest.mark.parametrize('external', [False, True])
def test_sql_revision_invalidates_basis_and_proposal(live, tmp_path, external):
    adapter, state, _ = live
    connection = None
    if external:
        path = tmp_path/'shared.sqlite'
        connection = sqlite3.connect(path); adapter.cache.db.backup(connection)
        adapter.cache.db = connection
    try:
        first = lc.capture(adapter)
        writer = sqlite3.connect(path) if external else adapter.cache.db
        writer.execute("UPDATE volumes SET volume=88 WHERE gid=1"); writer.commit()
        if external: writer.close()
        with pytest.raises(ValueError, match='PROPOSAL_STALE'): lc.require_current(adapter, first)
        state.profile_flow[(1, 2)] = 2*88*100/108
        second = lc.capture(adapter)
        assert not second['basis_reused']
        assert second['profile_long_vehicle_flow'][0] == pytest.approx(state.profile_flow[(1, 2)])
    finally:
        if connection is not None: connection.close()


def test_sql_mutation_during_last_live_read_cannot_publish_mixed_basis(live, monkeypatch):
    adapter, _, _ = live
    original = lc.reads._profile_flows
    count = [0]
    def changed(*args):
        count[0] += 1
        if count[0] == 2: adapter.cache.db.execute('UPDATE volumes SET volume=volume+1 WHERE gid=1')
        return original(*args)
    monkeypatch.setattr(lc.reads, '_profile_flows', changed)
    with pytest.raises(ValueError, match='STATE_CHANGED_DURING_CAPTURE'): lc.capture(adapter)


@pytest.mark.parametrize('fault', ['fractional_profile', 'fractional_multiplicity', 'intrazonal_profile'])
def test_corrupt_cached_path_hits_are_rejected(live, fault):
    adapter, _, _ = live
    if fault == 'fractional_profile':
        adapter.cache.db.execute('UPDATE profile_hits SET profile_index=.2 WHERE gid=1 AND profile_index=0')
    elif fault == 'fractional_multiplicity':
        adapter.cache.db.execute('UPDATE profile_hits SET multiplicity=1.5 WHERE gid=1')
    else:
        adapter.cache.db.executescript("INSERT INTO geometry VALUES(4,1,1,2); INSERT INTO volumes VALUES(4,'NATIVE_CL',5); INSERT INTO profile_hits VALUES(4,0,1);")
    with pytest.raises((ValueError, RuntimeError), match='LONG_CACHE'): lc.capture(adapter)


def test_profile_catalog_cannot_change_under_compiled_basis(live):
    adapter, _, _ = live
    lc.capture(adapter)
    adapter.cache.profiles.reverse()
    with pytest.raises(ValueError, match='PROFILE_IDENTITY_CHANGED'): lc.capture(adapter)


@pytest.mark.parametrize('captured_numbers', [(9305,), lc.reads.MATRICES])
def test_snapshot_matrix_reads_are_shared_without_cross_phase_reuse(live, captured_numbers):
    adapter, state, _ = live
    def snapshot():
        for no in captured_numbers:
            snapshots._matrix_fingerprint(adapter.visum.Net.Matrices.ItemByKey(no))
        return copy.deepcopy(state.parent)
    adapter.generation_guard_snapshot = snapshot
    lc.capture(adapter)
    # Every matrix is still independently read BEFORE and AFTER, never twice per phase.
    assert all(state.matrix_reads.count(no) == 2 for no in lc.reads.MATRICES)


def test_snapshot_capture_discards_partial_attempt_and_restores_nested_scope(live, monkeypatch):
    adapter, _, _ = live
    count = [0]
    def attempt(ad):
        count[0] += 1
        snapshots._matrix_fingerprint(ad.visum.Net.Matrices.ItemByKey(9291 if count[0] == 1 else 9305))
        if count[0] == 1: raise RuntimeError('BUSY_PARTIAL_SNAPSHOT')
        return {'state_hash': 'success'}
    def retry(ad, label, fn):
        try: return fn()
        except RuntimeError: return fn()
    monkeypatch.setattr(snapshots, '_snapshot_once', attempt)
    monkeypatch.setattr(snapshots.combusy, '_read_retry', retry)
    with snapshots.capture_matrix_values(lc.reads.MATRICES) as outer:
        with snapshots.capture_matrix_values(lc.reads.MATRICES) as inner:
            snapshots.strict_snapshot(adapter)
            assert set(inner) == {9305} and not inner[9305].flags.writeable
        assert outer == {}
        snapshots._matrix_fingerprint(adapter.visum.Net.Matrices.ItemByKey(9291))
        assert set(outer) == {9291}
    assert snapshots._MATRIX_CAPTURE.get() is None


def test_pure_pathlink_fractional_link_no_is_not_rounded():
    from test_v24917_long_profile_incidence import _fixture
    import r1_15a2_long_profile_incidence_v24917 as pure
    paths, links, profiles, zones, final, components = _fixture()
    links[0]['LinkNo'] = 10.1
    with pytest.raises(ValueError, match='INVALID_OR_ORPHAN_PATHLINK'):
        pure.build_observed_long_incidence(paths, links, profiles, zones, final, components)


def test_large_valid_od_catalogue_does_not_fail_due_to_scalar_sum_roundoff():
    from r1_15a2_skim_v24916p2c import ordered_zone_hash
    observed, ws, solution, _, _ = _inputs()
    zones = list(range(1, 102))
    oi, di = np.nonzero(~np.eye(101, dtype=bool)); oi, di = oi[:10000], di[:10000]
    q = np.full(10000, 10000.7)
    observed.update(variables=[{'dseg_code': 'NATIVE_CL', 'family': 'LONG',
        'origin': int(o+1), 'destination': int(d+1), 'q_current': float(v)} for o, d, v in zip(oi, di, q)],
        vehicle_production=np.bincount(oi, weights=q, minlength=101),
        vehicle_attraction=np.bincount(di, weights=q, minlength=101), vehicle_total=float(q.sum()),
        zone_order_sha256=ordered_zone_hash(zones))
    observed['incidence'] = lc.core.SparseOperator(np.array([], dtype=int),
        np.array([], dtype=int), np.array([]), 2, len(q))
    bounds = {('LONG', role, z): (-.1, .1) for role in ('PROD', 'ATT') for z in zones}
    p = lf.build_problem(observed, ws, solution, zones, bounds)
    assert np.isfinite(p.G).all() and np.count_nonzero(p.G) == 0
    observed['vehicle_total'] -= 1.
    with pytest.raises(ValueError, match='MARGINS_INVALID'):
        lf.build_problem(observed, ws, solution, zones, bounds)


def test_snapshot_rejects_wrong_matrix_returned_by_lookup():
    from types import SimpleNamespace as NS
    from test_v24917_snapshot_reads_genfix1 import _adapter
    ad = _adapter()
    matrices = ad.visum.Net.Matrices
    original = matrices.ItemByKey(9101)
    matrices.keys[9101] = NS(GetValues=original.GetValues,
        AttValue=lambda attr: 9102 if attr == 'NO' else original.AttValue(attr))
    with pytest.raises(Exception, match='LOOKUP_IDENTITY_MISMATCH'):
        snapshots.strict_snapshot(ad)
