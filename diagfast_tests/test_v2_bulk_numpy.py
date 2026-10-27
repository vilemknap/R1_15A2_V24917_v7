"""DIAGFAST V2: bitwise NumPy parity, interp cache parity, bulk probe fallbacks."""
import math
import random
from types import SimpleNamespace

import numpy as np
import pytest

import r1_15a2_diagfast_v1 as df
import r1_15a2_diagfast_v2 as v2
from fakes import make12, Matrix, Coll, Attr, add_matrices


def same(a, b, path='root'):
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
        assert a.hex() == b.hex(), (path, a, b)
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        assert a.keys() == b.keys(), (path, a.keys() ^ b.keys())
        return all(same(a[k], b[k], path + '.' + str(k)) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        assert len(a) == len(b), (path, len(a), len(b))
        return all(same(x, y, '%s[%d]' % (path, i)) for i, (x, y) in enumerate(zip(a, b)))
    assert type(a) is type(b) and a == b, (path, a, b)
    return True


def envs(tmp_path, n=None):
    ref = df.reference_namespace('11D', tmp_path)
    fast = df.reference_namespace('11D', tmp_path)
    if n is not None:
        ref['EXPECTED_ZONE_COUNT'] = n
        fast['EXPECTED_ZONE_COUNT'] = n
    p = df.Profile('11D', 'FAST_EXACT')
    df.configure_namespace(fast, '11D', 'FAST_EXACT', p)
    return ref, fast, p


def compute12(env, v):
    probes = []
    manifest = env['load_manifest']()
    idx = env['read_link_index'](v, probes)
    cls = env['read_countlocations'](v)
    qa = env['verify_live_authority'](manifest, cls, idx)
    rows = env['build_detail_rows'](v, manifest, idx, cls)
    pairs, actions = env['add_pair_and_diag'](rows)
    return rows, pairs, actions, probes, qa


def fast12(tmp_path):
    e = df.reference_namespace('12D', tmp_path)
    p = df.Profile('12D', 'FAST_EXACT')
    df.configure_namespace(e, '12D', 'FAST_EXACT', p)
    return e, p


# --------------------------------------------------------------------------
# NumPy exact sums
# --------------------------------------------------------------------------

@pytest.mark.parametrize('seed', list(range(12)))
def test_numpy_bitwise_random_edge_matrices(tmp_path, seed):
    rng = random.Random(seed)
    k = rng.randint(2, 33)
    choices_d = [0.0, -0.0, 1.0, 5.0, 15.0, 25.0, 50.0, 100.0, 100.0000001, 99.9999999,
                 110.0, 150.0, 200.0, 200.0000001, float('nan'), float('inf'), -3.0]
    d = [[rng.choice(choices_d + [rng.uniform(-5, 240)]) for _ in range(k)] for _ in range(k)]
    vals = [[rng.choice([0.0, -0.0, -1e-9, 1e-300, rng.uniform(0, 1e4), rng.uniform(-3, 3),
                         float('nan'), float('inf'), float('-inf'), 7])
             for _ in range(k)] for _ in range(k)]
    ref, fast, p = envs(tmp_path, n=k)
    md, mv = Matrix(9001, d), Matrix(9101, vals)
    rc = ref['load_class_matrix'](md)
    fc = fast['load_class_matrix'](md)
    same([list(r) for r in rc[0]], [list(r) for r in fc[0]])
    same(rc[1], fc[1])
    same(list(ref['matrix_total'](mv)), list(fast['matrix_total'](mv)))
    for bins, low, high in ((ref['DIST_BINS_0_100'], 0.0, 100.0),
                            (ref['LONG_BINS_100_200'], 100.0, 200.0),
                            (ref['TIME_BINS_DIAG'], 0.0, None),
                            (ref['TIME_BINS_DIAG'], None, None)):
        same(ref['compute_matrix_distribution'](mv, rc[0], bins, low, high),
             fast['compute_matrix_distribution'](mv, fc[0], bins, low, high))
    assert p.counts.get('v2_numpy_fast:compute_matrix_distribution', 0) >= 4


def test_numpy_681_dense_bitwise(tmp_path):
    n = 681
    rng = np.random.default_rng(20261024)
    dist = (rng.uniform(0, 230, size=(n, n))).tolist()
    dem = (rng.gamma(2.0, 3.0, size=(n, n)) * (rng.random((n, n)) > 0.1)).tolist()
    dem[3][7] = float('nan'); dem[5][9] = -2.0; dem[6][1] = -0.0
    ref, fast, p = envs(tmp_path)
    md, mv = Matrix(9001, dist), Matrix(9101, dem)
    rc = ref['load_class_matrix'](md); fc = fast['load_class_matrix'](md)
    same(list(ref['matrix_total'](mv)), list(fast['matrix_total'](mv)))
    for bins, low, high in ((ref['DIST_BINS_0_100'], 0.0, 100.0), (ref['LONG_BINS_100_200'], 100.0, 200.0)):
        same(ref['compute_matrix_distribution'](mv, rc[0], bins, low, high),
             fast['compute_matrix_distribution'](mv, fc[0], bins, low, high))


@pytest.mark.parametrize('bad', [None, '1.5', True, 'x'])
def test_numpy_non_float_cells_use_reference(tmp_path, bad):
    ref, fast, p = envs(tmp_path, n=2)
    vals = [[1.0, bad], [2.0, 3.0]]
    cl = [[1.0, 2.0], [3.0, 4.0]]
    assert ref['matrix_total'](Matrix(9101, vals)) == fast['matrix_total'](Matrix(9101, vals))
    same(ref['compute_matrix_distribution'](Matrix(9101, vals), cl, ref['DIST_BINS_0_100'], 0.0, 100.0),
         fast['compute_matrix_distribution'](Matrix(9101, vals), cl, fast['DIST_BINS_0_100'], 0.0, 100.0))
    assert p.counts.get('v2_numpy_reference_fallback:matrix_total', 0) >= 1


def test_numpy_shape_errors_keep_reference_messages(tmp_path):
    ref, fast, p = envs(tmp_path)
    with pytest.raises(fast['Step11dError'], match='681x681'):
        fast['load_class_matrix'](Matrix(9001, [[1.0, 2.0], [3.0, 4.0]]))
    with pytest.raises(fast['Step11dError'], match='Matrix dimension mismatch for 9101'):
        fast['compute_matrix_distribution'](Matrix(9101, [[1.0]]), [[1.0], [2.0]], fast['DIST_BINS_0_100'])


def test_numpy_disabled_by_env_restores_reference(tmp_path, monkeypatch):
    monkeypatch.setenv(v2.DISABLE_ENV, 'numpy_11d')
    ref, fast, p = envs(tmp_path, n=2)
    assert fast['matrix_total'](Matrix(9101, [[1.0, 2.0], [3.0, 4.0]])) == (10.0, 0, 0)
    assert not any(k.startswith('v2_numpy') for k in p.counts)
    assert p.notes['v2_features']['numpy_11d'] is False


# --------------------------------------------------------------------------
# interp x-grid cache and curve_stats memo
# --------------------------------------------------------------------------

def test_interp_cache_bitwise_on_embedded_authority(tmp_path):
    ref, fast, p = envs(tmp_path)
    auth = ref['_extract_embedded_authority'](tmp_path / 'auth')
    curves, _ = ref['load_component_curves'](auth / 'R1_IDP_DIST_KM_TARGET_CURVES_V1.csv')
    long_curves, _ = ref['load_long_basis'](auth / 'R1_IDP_LONG_DIST_KM_BASIS_V1.csv')
    for pts in list(curves.values()) + list(long_curves.values()):
        for bins in (ref['DIST_BINS_0_100'], ref['LONG_BINS_100_200'], ref['TIME_BINS_DIAG']):
            same(ref['curve_stats'](pts, bins), fast['curve_stats'](pts, bins))
            same(ref['curve_stats'](pts, bins), fast['curve_stats'](pts, bins))   # memo hit
    assert p.counts.get('v2_curve_stats_memo_hits', 0) > 0


def test_interp_cache_random_points_and_edges(tmp_path):
    ref, fast, p = envs(tmp_path)
    rng = random.Random(5)
    for trial in range(40):
        n = rng.randint(1, 40)
        xs = sorted({round(rng.uniform(0, 300), rng.choice([0, 1, 3, 9])) for _ in range(n)})
        pts = [(x, rng.uniform(0, 2)) for x in xs]
        if rng.random() < 0.2 and len(pts) > 2:
            pts.insert(1, (pts[1][0], 0.5))          # duplicate x grid point
        probes = [pts[0][0], pts[-1][0], pts[0][0] - 1, pts[-1][0] + 1] + \
                 [x for x, _ in pts] + [rng.uniform(-10, 310) for _ in range(30)]
        for x in probes:
            same(ref['interp'](pts, x), fast['interp'](pts, x))
    assert fast['interp']([], 1.0) == 0.0


# --------------------------------------------------------------------------
# 12D bulk links / countlocations
# --------------------------------------------------------------------------

def test_12d_v2_exact_with_sparse_scalar_budget(tmp_path):
    v, legacy, m, c = make12(tmp_path, extra=500)
    expected = compute12(legacy, v)
    legacy_calls = c['AttValue']
    c.clear()
    v.Net.Links.counter.clear()
    e, p = fast12(tmp_path)
    assert compute12(e, v) == expected
    assert p.notes['identity_backend'] == 'V2_BULK_COLUMNS_PROBE_VERIFIED'
    assert p.fallbacks == []
    assert c['AttValue'] <= 60 < legacy_calls          # probe reads only
    assert 'GetAll' not in v.Net.Links.counter


def _swap_bulk(coll, attr, transform):
    original = coll.GetMultiAttValues

    def patched(name, *rest):
        rows = original(name, *rest)
        return transform(rows) if name == attr else rows
    coll.GetMultiAttValues = patched


@pytest.mark.parametrize('fault', ['type_float', 'bulk_fails_scalar_ok', 'bulk_ok_scalar_fails'])
def test_12d_link_probe_mismatch_falls_back_exactly(tmp_path, fault):
    v, legacy, m, c = make12(tmp_path, extra=40)
    expected = compute12(legacy, v)
    links = v.Net.Links
    if fault == 'type_float':
        _swap_bulk(links, 'NUMLANES', lambda rows: [(i, float(x)) for i, x in rows])
    elif fault == 'bulk_fails_scalar_ok':
        original = links.GetMultiAttValues
        links.GetMultiAttValues = lambda a, *r: (_ for _ in ()).throw(KeyError(a)) if a == 'LENGTH' else original(a, *r)
    else:
        for o in links.items:
            o.a.setdefault('ROUTENO', 'X')
        # scalar ROADNO fails on every object, bulk still returns a column
        for o in links.items:
            o.a['ROADNO'] = KeyError('ROADNO')
        _swap_bulk(links, 'ROADNO', lambda rows: [(i, 'R1') for i, _x in rows])
        expected = compute12(legacy, v)
    e, p = fast12(tmp_path)
    assert compute12(e, v) == expected
    assert [f['from'] for f in p.fallbacks] == ['V2_12D_LINKS']


def test_12d_countlocation_probe_mismatch_falls_back(tmp_path):
    v, legacy, m, c = make12(tmp_path, extra=5)
    expected = compute12(legacy, v)
    _swap_bulk(v.Net.CountLocations, 'R1_WEIGHT', lambda rows: [(i, str(x)) for i, x in rows])
    e, p = fast12(tmp_path)
    assert compute12(e, v) == expected
    assert 'V2_12D_COUNTLOCATIONS' in [f['from'] for f in p.fallbacks]


def test_12d_countlocation_malformed_bulk_is_data_error(tmp_path):
    v, legacy, m, c = make12(tmp_path, extra=5)
    original = v.Net.CountLocations.GetMultiAttValues
    v.Net.CountLocations.GetMultiAttValues = lambda a, *r: [(1, 2), (1, 3)] if a == 'NO' else original(a, *r)
    e, p = fast12(tmp_path)
    with pytest.raises(df.DiagFastError):
        compute12(e, v)
    assert p.fallbacks == []


def test_12d_late_fault_is_not_swallowed(tmp_path):
    v, legacy, m, c = make12(tmp_path, extra=5)
    e, p = fast12(tmp_path)
    probes = []
    manifest = e['load_manifest']()
    idx = e['read_link_index'](v, probes)
    cls = e['read_countlocations'](v)
    # an attribute never preloaded whose bulk read disagrees with scalar
    _swap_bulk(v.Net.CountLocations, 'R1_DIR', lambda rows: [(i, 1.5) for i, _x in rows])
    with pytest.raises(v2.BulkLateFault):
        e['att'](cls[0], ['R1_DIR'], 'default')


def test_12d_disabled_features_use_v1(tmp_path, monkeypatch):
    monkeypatch.setenv(v2.DISABLE_ENV, 'bulk_12d_links,bulk_12d_countlocations')
    v, legacy, m, c = make12(tmp_path, extra=30)
    expected = compute12(legacy, v)
    e, p = fast12(tmp_path)
    assert compute12(e, v) == expected
    assert p.notes['identity_backend'] == 'BULK_KEY_JOIN_VALIDATED_ITEMBYKEY'


# --------------------------------------------------------------------------
# 11D bulk countlocations / matrices
# --------------------------------------------------------------------------

def v11(tmp_path, extra=30):
    v, legacy, m, c = make12(tmp_path, extra=extra)
    return v


def test_11d_countlocation_rows_exact(tmp_path):
    v = v11(tmp_path)
    ref, fast, p = envs(tmp_path)
    expected = ref['countlocation_rows'](v)
    assert fast['countlocation_rows'](v) == expected
    assert len(expected) == 488
    assert p.fallbacks == []
    assert p.counts['v2_order_scalar_reads'] == 3


def test_11d_countlocation_order_mismatch_falls_back(tmp_path):
    v = v11(tmp_path)
    ref, fast, p = envs(tmp_path)
    expected = ref['countlocation_rows'](v)
    coll = v.Net.CountLocations
    original = coll.GetMultiAttValues
    n = len(coll.items)
    # row ids now reverse the container order: bulk position != GetAll position
    coll.GetMultiAttValues = lambda a, *r: [(2 * n - i, x) for i, x in original(a, *r)]
    assert fast['countlocation_rows'](v) == expected
    assert [f['from'] for f in p.fallbacks] == ['V2_11D_COUNTLOCATIONS']


def test_11d_parallel_from_to_links_fall_back(tmp_path):
    v = v11(tmp_path, extra=3)
    first = v.Net.Links.items[0]
    clone = Attr(dict(first.a, NO=first.a['NO'] + 777777))
    v.Net.Links.items.append(clone)
    ref, fast, p = envs(tmp_path)
    expected = ref['countlocation_rows'](v)
    assert fast['countlocation_rows'](v) == expected
    assert [f['from'] for f in p.fallbacks] == ['V2_11D_COUNTLOCATIONS']


def test_11d_link_type_mismatch_falls_back(tmp_path):
    v = v11(tmp_path, extra=3)
    ref, fast, p = envs(tmp_path)
    expected = ref['countlocation_rows'](v)
    _swap_bulk(v.Net.Links, 'VOLVEH_DSEG(NATIVE_CW,AP)', lambda rows: [(i, str(x)) for i, x in rows])
    assert fast['countlocation_rows'](v) == expected
    assert [f['from'] for f in p.fallbacks] == ['V2_11D_COUNTLOCATIONS']


def test_11d_matrix_catalog_exact_and_duplicate_code(tmp_path):
    v = SimpleNamespace(Net=SimpleNamespace())
    add_matrices(v, n=3, with_time=True)
    ref, fast, p = envs(tmp_path, n=3)
    for code in ('R1_OSRM_DIST_KM', 'R1_OSRM_TIME_MIN', 'missing', ' r1_osrm_dist_km '):
        a = ref['find_matrix_by_code'](v, code)
        b = fast['find_matrix_by_code'](v, code)
        assert (a is None) == (b is None)
        if a is not None:
            assert b.AttValue('NO') == a.AttValue('NO')
    inv_ref = [ref['matrix_inventory_row'](ref['matrix_by_no'](v, no), no) for no in (9001, 9002, 9101, 9999)]
    inv_fast = [fast['matrix_inventory_row'](fast['matrix_by_no'](v, no), no) for no in (9001, 9002, 9101, 9999)]
    same(inv_ref, inv_fast)
    assert ref['find_time_matrix'](v)[1] == fast['find_time_matrix'](v)[1]
    # duplicate CODE: first-in-GetAll semantics must use the reference scan
    v.Net.Matrices.items.insert(0, Matrix(9500, [[1.0]], code='R1_OSRM_DIST_KM'))
    ref2, fast2, p2 = envs(tmp_path, n=3)
    assert fast2['find_matrix_by_code'](v, 'R1_OSRM_DIST_KM').AttValue('NO') == 9500
    assert p2.counts.get('v2_duplicate_matrix_code_reference') == 1


def test_11d_matrix_probe_mismatch_disables_catalog(tmp_path):
    v = SimpleNamespace(Net=SimpleNamespace())
    add_matrices(v, n=3, with_time=False)
    _swap_bulk(v.Net.Matrices, 'NUMROWS', lambda rows: [(i, float(x)) for i, x in rows])
    ref, fast, p = envs(tmp_path, n=3)
    same(ref['matrix_inventory_row'](ref['matrix_by_no'](v, 9101), 9101),
         fast['matrix_inventory_row'](fast['matrix_by_no'](v, 9101), 9101))
    assert [f['from'] for f in p.fallbacks] == ['V2_11D_MATRICES']


def test_v2_release_caches(tmp_path):
    ref, fast, p = envs(tmp_path, n=2)
    fast['matrix_total'](Matrix(9101, [[1.0, 2.0], [3.0, 4.0]]))
    v2.release(fast)
    assert fast['_diagfast_v2_curve_memo'] == {}
    assert fast['_diagfast_v2_interp_cache'] == {}


def test_bulk_retain_prunes_after_full_validation():
    items = [Attr(NO=i, X=float(i)) for i in range(50)]
    coll = Coll(items)
    prof = df.Profile('T', 'FAST_EXACT')
    bulk = v2.BulkCollection(coll, prof, 'T')
    ids = bulk.strict_column('NO', verify=False)
    rids = sorted(ids)
    bulk.set_probe(rids[3], items[3])
    bulk.retain([rids[0], rids[10]])
    seen = []
    col = bulk.strict_column('X', on_full=lambda full: seen.append(len(full)))
    assert seen == [50]
    assert set(col) == {rids[0], rids[10], rids[3]}
    assert col[rids[10]] == 10.0


def test_11d_unretained_link_key_uses_exact_scalar_object(tmp_path):
    v = v11(tmp_path, extra=3)
    for cl in v.Net.CountLocations.items:               # numeric text: not retained in bulk
        cl.a['FROMNODENO'] = str(cl.a['FROMNODENO'])
    ref, fast, p = envs(tmp_path)
    expected = ref['countlocation_rows'](v)
    assert fast['countlocation_rows'](v) == expected
    assert p.counts.get('v2_link_rows_outside_retained_scalar', 0) >= 1
    assert p.fallbacks == []


def test_frozen_fault_never_degrades_to_default():
    items = [Attr(NO=i, A='x') for i in range(5)]
    coll = Coll(items)
    bulk = v2.BulkCollection(coll, df.Profile('T', 'FAST_EXACT'), 'T')
    ids = bulk.strict_column('NO', verify=False)
    bulk.set_probe(sorted(ids)[0], items[0])
    bulk.frozen = True
    original = coll.GetMultiAttValues
    coll.GetMultiAttValues = lambda a, *r: [(i, 'y') for i, _ in original(a, *r)] if a == 'A' else original(a, *r)
    row = v2.BulkRow(bulk, sorted(ids)[1])
    for _ in range(2):                                   # first and any later request
        with pytest.raises(v2.BulkLateFault):
            row.AttValue('A')
    with pytest.raises(v2.BulkLateFault):
        row.AttValue('NO_SUCH_COLUMN_AFTER_FAULT')


def test_unretained_row_is_hard_error():
    items = [Attr(NO=i, A=float(i)) for i in range(5)]
    coll = Coll(items)
    bulk = v2.BulkCollection(coll, df.Profile('T', 'FAST_EXACT'), 'T')
    ids = sorted(bulk.strict_column('NO', verify=False))
    bulk.set_probe(ids[0], items[0])
    bulk.retain([ids[0]])
    with pytest.raises(v2.BulkLateFault, match='ROW_NOT_RETAINED'):
        v2.BulkRow(bulk, ids[4]).AttValue('A')
