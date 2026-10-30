"""Compare accelerated writes/parsing against the sealed production builder."""
import importlib.util
from pathlib import Path
import sqlite3
from types import MethodType

import pytest

import r1_15a2_path_store_build_v24917 as fast
from r1_15a2_supply import SupplyPolicy
from test_supply_v22 import A, P, B, C, T, links, profile
from test_two_mode_v238 import authority, hierarchy, SEQS, BoundedHierarchical
from test_two_mode_v238 import live_fixture, store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sealed():
    spec = importlib.util.spec_from_file_location('_path_build_sealed_oracle', ROOT / 'r1_15a2_two_mode_v238.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collector(sealed, tmp_path, name, optimized, settings=None, control=None):
    network = links()
    network[(16, 4, 2)] = dict(network[P])
    c = sealed.TwoModeRouteCollector(
        [profile(model=1000), profile(A, model=1400, ident='b'),
         profile(T, model=1400, role='VALIDATION', ident='v')],
        SupplyPolicy(min_geh=1, min_residual=1), 'state', network, tmp_path / name,
        dict(sealed.DEFAULT_SETTINGS, commit_routes=1, min_free_disk_gib=0, **(settings or {})),
        control=control)
    if optimized:
        c.add_parents = MethodType(fast.add_parents, c)
        c.add_geometry = MethodType(fast.add_geometry, c)
    return c


def add(c, code='NATIVE_CW', mode='C', values=None):
    values = values or [(1, 2, 1, 600.), (1, 2, 2, 400.)]
    ref = sum(v for o, d, ix, v in values if o != d)
    return c.add_parents(code, mode, values, authority([ref]))


def table_contents(c):
    tables = [r[0] for r in c.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {t: sorted(c.db.execute('SELECT * FROM ' + t)) for t in tables}


@pytest.mark.parametrize('format', ['hierarchy', 'flat', 'partial', 'serialized'])
def test_exact_database_hash_flow_and_supply_evidence(sealed, tmp_path, format):
    old = collector(sealed, tmp_path, 'old.sqlite', False)
    new = collector(sealed, tmp_path, 'new.sqlite', True)
    keys = [(1, 2, 1), (1, 2, 2), (2, 2, 1), (2, 3, 1)]
    seqs = [(A, P, (16, 4, 2), P, T), SEQS[1], (), ()]
    raw = hierarchy(seqs, keys)
    if format == 'flat':
        raw = [r for r in raw if r[3] != '' or tuple(r[:3]) in keys[2:]]
        cursor = -1
        for r in raw:
            if r[3] == 1 or r[3] == '':
                cursor += 1
            r[:3] = keys[cursor]
    elif format == 'partial':
        raw[1][:3] = [1, '', None]
        raw[2][:3] = [None, 2, '']
    elif format == 'serialized':
        raw = [[None if x == '' else str(x) for x in r] for r in raw]
    try:
        for c in (old, new):
            for mode in ('C', 'C_NOT'):
                for i in range(3):
                    vals = [(*k, v) for k, v in zip(keys, (600. + i, 400., 0., 0.25))]
                    add(c, mode + str(i), mode, list(reversed(vals)))
                obj = BoundedHierarchical(raw)
                rows = sealed.bounded_rows(obj, sealed.GEOMETRY_COLUMNS,
                    dict(c.settings, page_size=2), sealed.QuietControl(), 'TEST')
                c.add_geometry(mode, rows)
                assert obj.unbounded_calls == 0
            c.build_route_evidence()
        assert table_contents(old) == table_contents(new)
        assert old.parents == new.parents
        assert old.mode_audits == new.mode_audits
        assert old.path_structure_hash() == new.path_structure_hash()
        assert old.path_basis_hash() == new.path_basis_hash()
        assert old.path_basis_comparison_hash() == new.path_basis_comparison_hash()
        assert old.flow == new.flow
        assert old.evidence == new.evidence
        assert old.edge_max_multiplicity == new.edge_max_multiplicity
        assert old.support == new.support
        assert new._path_build_keymap is None
        summary = dict(new.summary); summary.pop('path_store_build')
        assert summary == old.summary
        assert new.db.execute('PRAGMA synchronous').fetchone()[0] == 2
        assert new.db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
        assert new.db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert list(new.db.execute('PRAGMA foreign_key_check')) == []
    finally:
        old.close(); new.close()


@pytest.mark.parametrize('damage', [
    'orphan', 'missing', 'repeat', 'gap', 'broken', 'unknown', 'partial',
    'child_missing', 'parent_missing', 'bad_schema', 'fraction', 'bool', 'nan',
    'zero_id', 'too_large_id', 'negative_id', 'row_budget', 'link_budget'])
def test_same_rejections_for_bad_geometry(sealed, tmp_path, damage):
    errors = []
    settings = {'max_geometry_rows_per_mode': 4} if damage == 'row_budget' else (
        {'max_links_per_path': 2} if damage == 'link_budget' else {})
    for optimized in (False, True):
        c = collector(sealed, tmp_path, str(optimized) + '.sqlite', optimized, settings)
        raw = hierarchy()
        if damage == 'orphan': raw = raw[1:]
        if damage == 'missing': raw = raw[:4]
        if damage == 'repeat': raw += hierarchy()[:4]
        if damage == 'gap': raw[2][3] = 3
        if damage == 'broken': raw[2][5] = 9
        if damage == 'unknown': raw[1][4] = 999
        if damage == 'partial': raw[2][0] = 8
        if damage == 'child_missing': raw[2][4] = None
        if damage == 'parent_missing': raw[0][0] = None
        if damage == 'bad_schema': raw[2].pop()
        if damage in ('fraction', 'bool', 'nan', 'zero_id', 'too_large_id', 'negative_id'):
            raw[1][4] = dict(fraction=12.5, bool=True, nan=float('nan'), zero_id=0,
                            too_large_id=2147483648, negative_id=-1)[damage]
        try:
            add(c)
            with pytest.raises(Exception) as exc:
                c.add_geometry('C', raw)
            errors.append((type(exc.value).__name__, str(exc.value)))
            assert not c.incidence_ready
            assert not c.mode_audits['C'].get('geometry_complete')
            assert c.db.execute("SELECT value FROM metadata WHERE key='structural_export_complete'").fetchone() is None
            if optimized:
                assert c._path_build_keymap is None
        finally:
            c.close()
    assert errors[0] == errors[1]


@pytest.mark.parametrize('damage', ['duplicate', 'missing', 'extra', 'negative', 'parity', 'budget', 'numeric'])
def test_same_parent_failures_and_no_stale_map(sealed, tmp_path, damage):
    errors = []
    for optimized in (False, True):
        c = collector(sealed, tmp_path, str(optimized) + '.sqlite', optimized)
        try:
            add(c)
            rows = [(1, 2, 1, 600.), (1, 2, 2, 400.)]
            if damage == 'duplicate': rows[1] = rows[0]
            if damage == 'missing': rows.pop()
            if damage == 'extra': rows[1] = (1, 2, 3, 400.)
            if damage == 'negative': rows[1] = (1, 2, 2, -1.)
            if damage == 'budget': c.settings['max_parent_rows_per_dseg'] = 1
            if damage == 'numeric': rows[1] = (1, 2, 2, float('inf'))
            with pytest.raises(Exception) as exc:
                c.add_parents('NATIVE_CS', 'C', rows, authority([2000 if damage == 'parity' else 1000]))
            errors.append((type(exc.value).__name__, str(exc.value)))
            if optimized:
                assert c._path_build_keymap is None
        finally:
            c.close()
    assert errors[0] == errors[1]


@pytest.mark.parametrize('external', [False, True])
def test_keymap_cache_detects_sql_changes(sealed, tmp_path, external):
    c = collector(sealed, tmp_path, 'cached.sqlite', True)
    try:
        add(c)
        add(c, 'NATIVE_CS')
        assert fast._stats(c)['keymap_cache_hits'] == 1
        db = sqlite3.connect(c.route_db_path) if external else c.db
        try:
            # Preserve references but change the official key set behind the cache.
            db.execute('UPDATE geometry SET path_index=3 WHERE path_index=2')
            db.commit()
        finally:
            if external: db.close()
        with pytest.raises(Exception, match='FULL_PARENT_KEYS_DIFFER'):
            add(c, 'NATIVE_CL')
        assert fast._stats(c)['keymap_sql_reads'] == 2
        assert c._path_build_keymap is None
    finally:
        c.close()


def test_sql_failure_rolls_back_active_flush_and_cannot_reopen(sealed, tmp_path):
    c = collector(sealed, tmp_path, 'failed.sqlite', True)
    try:
        add(c)
        c.db.execute("CREATE TRIGGER fail_hit BEFORE INSERT ON profile_hits BEGIN SELECT RAISE(ABORT,'INJECTED_WRITE_ERROR'); END")
        c.db.commit()
        with pytest.raises(sqlite3.IntegrityError, match='INJECTED_WRITE_ERROR'):
            c.add_geometry('C', hierarchy())
        assert not c.db.in_transaction
        assert c.db.execute('SELECT COUNT(*) FROM geometry WHERE edge_ids IS NOT NULL').fetchone()[0] == 0
        assert c._path_build_keymap is None
        with pytest.raises(Exception, match='PERSISTENT_MODE_STORE_NOT_COMPLETE'):
            sealed.TwoModeRouteCollector.open_existing(c.profiles, c.policy, links(), c.route_db_path)
    finally:
        c.close()


def test_install_preserves_class_alias_and_clears_map_on_close(sealed, tmp_path, monkeypatch):
    alias = sealed.TwoModeRouteCollector
    monkeypatch.setattr(fast.base, 'TwoModeRouteCollector', alias)
    assert fast.install()['installed']
    assert fast.install()['already']
    assert sealed.TwoModeRouteCollector is alias
    c = collector(sealed, tmp_path, 'installed.sqlite', False)
    add(c)
    assert c._path_build_keymap is not None
    c.close()
    assert c._path_build_keymap is None


def test_full_12_dseg_export_and_readonly_reopen(sealed, tmp_path):
    visum, cfg, model, lists = live_fixture()
    c = store(tmp_path, [profile(model=model)], settings={'sample_windows': [[1, 2]], 'page_size': 3})
    c.add_parents = MethodType(fast.add_parents, c)
    c.add_geometry = MethodType(fast.add_geometry, c)
    try:
        result = sealed.collect_two_modes(visum, c, cfg, tmp_path)
        assert result['full_geometry_read_count'] == 2
        assert result['dseg_complete_count'] == 12
        assert c.flow == [model]
        assert fast._stats(c)['keymap_sql_reads'] == 4
        assert fast._stats(c)['keymap_cache_hits'] == 10
        assert c._path_build_keymap is None
        assert all(x.unbounded_calls == 0 for x in lists.instances)
        reopened = sealed.TwoModeRouteCollector.open_existing(c.profiles, c.policy, links(), c.route_db_path)
        try:
            assert reopened.flow == c.flow
            assert reopened.path_basis_hash() == c.path_basis_hash()
            assert reopened.path_structure_hash() == c.path_structure_hash()
            assert reopened.read_only
        finally:
            reopened.close()
    finally:
        c.close()
