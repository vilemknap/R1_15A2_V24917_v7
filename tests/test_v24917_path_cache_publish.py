"""Actual adapter export -> private SQLite -> atomic immutable publication."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import subprocess
import sys
import os

import pytest

import r1_15a2_path_cache_publish_v24917 as pub
import r1_15a2_path_store_build_v24917 as builder
import r1_15a2_two_mode_v238 as paths
from r1_15a2_trial_adapter_v24917 import VisumAdapter
from r1_15a2_supply import SupplyPolicy
from test_supply_v22 import profile, links, P
from test_two_mode_v238 import live_fixture


@pytest.fixture(autouse=True)
def isolate_patches(monkeypatch):
    cls = paths.TwoModeRouteCollector
    for name in ('__init__', 'close', 'add_parents', 'add_geometry'):
        monkeypatch.setattr(cls, name, getattr(cls, name))
    monkeypatch.setattr(cls, 'open_existing', cls.__dict__['open_existing'])
    monkeypatch.setattr(paths, 'bounded_rows', paths.bounded_rows)
    monkeypatch.setattr(pub, 'options', lambda: dict(pub.DEFAULTS, fast_staging=True))


def adapter(tmp_path, control=None):
    visum, cfg, model, lists = live_fixture()
    cfg.update(two_mode=dict(paths.DEFAULT_SETTINGS, page_size=3, sample_windows=[[1, 2]],
                             min_free_disk_gib=0), dseg_path_volume_relative_tolerance=.01)
    a = object.__new__(VisumAdapter)
    a.visum, a.cfg, a.control = visum, cfg, control or paths.QuietControl()
    a.policy = SupplyPolicy(min_geh=1, min_residual=1)
    a.persistent_path_cache = SimpleNamespace(enabled=False)
    a.cache = None
    a.cache_snapshot = None
    a.cache_live_snapshot = None
    a.path_epoch_index = 0
    a.path_epoch_history = []
    a.read_links = links
    a.snapshot = lambda: {'state_hash': 'parent', 'fixed_link_hash': 'fixed',
                         'dseg_hash': 'ds', 'operations_hash': 'ops'}
    def invalidate(*args, **kwargs):
        if a.cache is not None: a.cache.close()
        a.cache = None
    a.invalidate_cache = invalidate
    a._path_epoch_cfg = lambda: {'cleanup_obsolete_sqlite_after_verified_refresh': True,
                                 'retain_sqlite_stores': 1}
    diag = {'d12': {'rows': [profile(model=model)]}}
    return a, diag, lists


def build(a, diag, folder):
    return a._build_cache(diag, folder, a.snapshot(), allow_persistent_restore=False)


def previous_cache(a, tmp_path):
    old = tmp_path / 'OLD' / pub.STORE
    old.parent.mkdir(); old.write_bytes(b'previous verified cache')
    a.cache = SimpleNamespace(route_db_path=str(old), close=lambda: None)
    return old


def test_real_adapter_publication_and_supply_temp_writes(tmp_path):
    a, diag, lists = adapter(tmp_path)
    old = previous_cache(a, tmp_path)
    c, network, export = build(a, diag, tmp_path / 'CACHE')
    try:
        final = Path(c.route_db_path)
        assert final.parent.name.startswith('PATH_CACHE_')
        assert not old.exists()
        assert not list((tmp_path / 'CACHE').glob('.UNPUBLISHED*'))
        manifest = json.loads((final.parent / pub.MANIFEST).read_text())
        assert hashlib.sha256(final.read_bytes()).hexdigest() == manifest['store_sha256']
        assert manifest['semantic']['path_basis_hash'] == c.path_basis_hash()
        assert manifest['semantic']['counts']['volumes'] == 24
        assert c.read_only and c.incidence_ready
        assert all(obj.unbounded_calls == 0 for obj in lists.instances)
        assert c.summary['path_store_build']['journal_mode'] == 'MEMORY'
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            c.db.execute("UPDATE metadata SET value='bad' WHERE key='schema'")
        before = final.read_bytes()
        c.prepare_sequence_evidence()
        assert c.finish()['profile_parity'][0]['passes']
        impact = c.impact([{'key': P, 'delta': 1.}], 0, 1000.)
        assert impact['affected_routes'] > 0
        assert final.read_bytes() == before
        assert c.db.execute("SELECT name FROM sqlite_temp_master WHERE name='current_impact'").fetchone()
        epoch = json.loads((tmp_path / 'CACHE/PATH_EPOCH.json').read_text())
        assert epoch['obsolete_store_retention']['retired']
        assert epoch['path_cache_publication']['main_read_only']
    finally:
        c.close()


@pytest.mark.parametrize('damage', ['volume', 'blob', 'kind', 'profile', 'audit', 'parity', 'incomplete'])
def test_bad_staging_never_replaces_old_cache(tmp_path, monkeypatch, damage):
    original = pub._semantic
    def corrupt(c, codes):
        sql = {
            'volume': 'UPDATE volumes SET volume=volume+1 WHERE gid=1',
            'blob': "UPDATE geometry SET edge_ids=x'00000000' WHERE gid=1",
            'kind': "UPDATE geometry SET geometry_kind='WRONG' WHERE gid=1",
            'profile': 'UPDATE profile_hits SET multiplicity=multiplicity+1 WHERE gid=1',
            'audit': "UPDATE segments SET audit_json='{}' WHERE dseg='NATIVE_CW'",
            'incomplete': "DELETE FROM metadata WHERE key='structural_export_complete'",
        }
        if damage == 'parity': c.epoch_profiles[0]['model'] += 10000.
        else: c.db.execute(sql[damage]); c.db.commit()
        return original(c, codes)
    monkeypatch.setattr(pub, '_semantic', corrupt)
    a, diag, _ = adapter(tmp_path)
    old = previous_cache(a, tmp_path)
    with pytest.raises(Exception, match='PUBLICATION|PROFILE_FLOW_PARITY'):
        build(a, diag, tmp_path / 'CACHE')
    assert old.read_bytes() == b'previous verified cache'
    assert a.cache is None
    assert not list((tmp_path / 'CACHE').glob('.UNPUBLISHED*'))
    assert not list((tmp_path / 'CACHE').glob('PATH_CACHE_*/*sqlite'))


@pytest.mark.parametrize('phase', ['PATH_CACHE_PUBLICATION_CHECKS', 'PATH_CACHE_PUBLICATION_SHA256', 'PATH_CACHE_ATOMIC_RENAME'])
def test_stop_at_publish_boundaries_preserves_parent(tmp_path, phase):
    class Stop:
        def checkpoint(self, name='', **kw):
            if name == phase: raise paths.DesignStopRequested('INJECTED_STOP')
    a, diag, _ = adapter(tmp_path, Stop())
    old = previous_cache(a, tmp_path)
    with pytest.raises(Exception, match='INJECTED_STOP'):
        build(a, diag, tmp_path / 'CACHE')
    assert old.exists() and a.cache is None
    assert not list((tmp_path / 'CACHE').glob('.UNPUBLISHED*'))


def test_rename_failure_preserves_parent(tmp_path, monkeypatch):
    def fail(*args): raise OSError('INJECTED_RENAME_FAILURE')
    monkeypatch.setattr(pub.os, 'rename', fail)
    a, diag, _ = adapter(tmp_path)
    old = previous_cache(a, tmp_path)
    with pytest.raises(OSError, match='INJECTED_RENAME_FAILURE'):
        build(a, diag, tmp_path / 'CACHE')
    assert old.exists() and a.cache is None
    assert not list((tmp_path / 'CACHE').glob('.UNPUBLISHED*'))


def test_failure_after_rename_does_not_retire_parent(tmp_path, monkeypatch):
    def fail(*args): raise RuntimeError('INJECTED_REOPEN_FAILURE')
    monkeypatch.setattr(pub, '_readonly', fail)
    a, diag, _ = adapter(tmp_path)
    old = previous_cache(a, tmp_path)
    with pytest.raises(RuntimeError, match='INJECTED_REOPEN_FAILURE'):
        build(a, diag, tmp_path / 'CACHE')
    assert old.exists() and a.cache is None
    assert len(list((tmp_path / 'CACHE').glob('PATH_CACHE_*/' + pub.MANIFEST))) == 1


def test_live_parent_change_during_checks_blocks_rename(tmp_path, monkeypatch):
    original = pub._semantic
    a, diag, _ = adapter(tmp_path)
    old = previous_cache(a, tmp_path)
    def changed(*args):
        result = original(*args)
        a.snapshot = lambda: {'state_hash': 'CHANGED'}
        return result
    monkeypatch.setattr(pub, '_semantic', changed)
    with pytest.raises(Exception, match='LIVE_PARENT_CHANGED'):
        build(a, diag, tmp_path / 'CACHE')
    assert old.exists() and a.cache is None


def test_unpublished_structural_completion_cannot_be_reopened(tmp_path, monkeypatch):
    original = pub._semantic
    def inspect(c, codes):
        with pytest.raises(Exception, match='UNPUBLISHED_OPEN_FORBIDDEN'):
            paths.TwoModeRouteCollector.open_existing(c.profiles, c.policy, links(), c.route_db_path)
        return original(c, codes)
    monkeypatch.setattr(pub, '_semantic', inspect)
    a, diag, _ = adapter(tmp_path)
    c, _, _ = build(a, diag, tmp_path / 'CACHE')
    c.close()


@pytest.mark.parametrize('tamper', ['none', 'missing_manifest', 'manifest', 'bytes'])
def test_published_reopen_verifies_sha_and_supports_supply(tmp_path, tamper):
    a, diag, _ = adapter(tmp_path)
    c, network, _ = build(a, diag, tmp_path / 'CACHE')
    path, profiles, policy = Path(c.route_db_path), c.profiles, c.policy
    c.close()
    if tamper == 'missing_manifest': (path.parent / pub.MANIFEST).unlink()
    if tamper == 'manifest':
        m = json.loads((path.parent / pub.MANIFEST).read_text()); m['store_bytes'] += 1
        (path.parent / pub.MANIFEST).write_text(json.dumps(m))
    if tamper == 'bytes':
        with path.open('ab') as f: f.write(b'changed')
    if tamper != 'none':
        with pytest.raises(Exception, match='MANIFEST'):
            paths.TwoModeRouteCollector.open_existing(profiles, policy, network, path)
    else:
        reopened = paths.TwoModeRouteCollector.open_existing(profiles, policy, network, path)
        try:
            reopened.prepare_sequence_evidence()
            assert reopened.impact([{'key': P, 'delta': 1.}], 0, 1000.)['affected_routes'] > 0
            assert reopened.read_only
        finally:
            reopened.close()


def test_published_open_cannot_request_writable_main(tmp_path):
    a, diag, _ = adapter(tmp_path)
    c, network, _ = build(a, diag, tmp_path / 'CACHE')
    path, profiles, policy = Path(c.route_db_path), c.profiles, c.policy
    c.close()
    before = path.read_bytes()
    with pytest.raises(Exception, match='IS_IMMUTABLE'):
        paths.TwoModeRouteCollector.open_existing(profiles, policy, network, path, read_only=False)
    assert path.read_bytes() == before


def test_hard_process_exit_leaves_only_unpublished_orphan(tmp_path):
    script = r'''
import os,sys
from pathlib import Path
from types import SimpleNamespace
import r1_15a2_path_cache_publish_v24917 as p
import r1_15a2_path_store_build_v24917 as b
import r1_15a2_two_mode_v238 as paths
from test_supply_v22 import profile,links
from test_two_mode_v238 import authority,hierarchy
from r1_15a2_supply import SupplyPolicy
folder=Path(sys.argv[1]);folder.mkdir()
b.install();p.install()
a=SimpleNamespace(persistent_path_cache=SimpleNamespace(enabled=False))
s=p.BuildScope(a,folder,{'state_hash':'s'},dict(p.DEFAULTS,fast_staging=True))
p._SCOPE.set(s)
c=paths.TwoModeRouteCollector([profile()],SupplyPolicy(),'s',links(),folder/p.STORE)
c.add_parents('NATIVE_CW','C',[[1,2,1,600],[1,2,2,400]],authority([600,400]))
c.add_geometry('C',hierarchy());c.prepare_incidence_evidence()
os._exit(17)
'''
    root = Path(paths.__file__).resolve().parent
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=os.pathsep.join([str(root), str(root / 'tests')]))
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path / 'CRASH')], env=env,
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 17, result.stderr
    orphan, = (tmp_path / 'CRASH').glob('.UNPUBLISHED*/*.sqlite')
    pub.install()
    with pytest.raises(Exception, match='UNPUBLISHED_OPEN_FORBIDDEN'):
        paths.TwoModeRouteCollector.open_existing([], SupplyPolicy(), links(), orphan)
    assert not list((tmp_path / 'CRASH').glob('PATH_CACHE_*'))


def test_signed_zero_keeps_source_hash_but_verifies_sql_normalization(tmp_path, monkeypatch):
    a, diag, lists = adapter(tmp_path)
    for code, (first, second) in lists.volumes.items():
        lists.volumes[code] = (first + second, -0.)
    # Rebuild the fixture matrices and count profile to match this synthetic input.
    total = 0.
    for ds in a.visum.Net.DemandSegments.GetAll:
        if 'noT' not in ds.code: total += 100.
    diag['d12']['rows'][0]['model'] = total
    c, _, _ = build(a, diag, tmp_path / 'CACHE')
    try:
        assert c.read_only
        assert c._path_sql_volume_hashes['NATIVE_CW'] != c.parents['NATIVE_CW']['keys_and_volumes_sha256']
    finally:
        c.close()


def test_probe_size_is_pinned_for_real_adapter_export(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, 'options', lambda: dict(pub.DEFAULTS, fast_staging=True, page_probe=True))
    monkeypatch.setattr(pub.probe, 'benchmark', lambda *a, **kw: {'selected_page_size': 8192})
    a, diag, _ = adapter(tmp_path)
    c, _, _ = build(a, diag, tmp_path / 'CACHE')
    try:
        assert c.settings['page_size'] == 3
        assert c.settings['path_export_fixed_page_size'] == 8192
        assert all(s['fixed_page_size'] == 8192 for s in c.summary['path_export_pages'].values())
        assert c.read_only
    finally:
        c.close()


def test_probe_model_drift_blocks_entire_build(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, 'options', lambda: dict(pub.DEFAULTS, fast_staging=True, page_probe=True))
    a, diag, _ = adapter(tmp_path)
    old = previous_cache(a, tmp_path)
    def drift(*args, **kw):
        a.snapshot = lambda: {'state_hash': 'CHANGED'}
        return {'selected_page_size': 8192}
    monkeypatch.setattr(pub.probe, 'benchmark', drift)
    with pytest.raises(Exception, match='PATH_PAGE_PROBE_PARENT_CHANGED_AFTER'):
        build(a, diag, tmp_path / 'CACHE')
    assert old.exists() and not list((tmp_path / 'CACHE').glob('.UNPUBLISHED*'))


@pytest.mark.parametrize('value', [True, 'yes', 0, None, []])
def test_invalid_options_rejected(tmp_path, value, monkeypatch):
    # Fixture patches the normal loader; access its original source for validation.
    import importlib.util
    spec = importlib.util.spec_from_file_location('_path_pub_options', Path(pub.__file__))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    (tmp_path / 'R1_RUN_OPTIONS.json').write_text(json.dumps({'path_io': value}))
    with pytest.raises(ValueError): module.options(tmp_path)


def test_env_flags_override_options_without_editing_source(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('_path_pub_options', Path(pub.__file__))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    path = tmp_path / 'R1_RUN_OPTIONS.json'
    path.write_text(json.dumps({'path_io': {'fast_staging': False, 'page_probe': False}}))
    before = path.read_bytes()
    opts = module.options(tmp_path, environ={'R1_PATH_STORE_FAST_STAGING': '1', 'R1_PATH_EXPORT_PAGE_PROBE': 'true'})
    assert opts['fast_staging'] and opts['page_probe']
    assert path.read_bytes() == before


@pytest.mark.parametrize('value', ['yes', '2', 'invalid'])
def test_bad_env_flags_fail_before_build(tmp_path, value):
    import importlib.util
    spec = importlib.util.spec_from_file_location('_path_pub_options', Path(pub.__file__))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with pytest.raises(ValueError, match='INVALID_ENV_BOOLEAN'):
        module.options(tmp_path, environ={'R1_PATH_STORE_FAST_STAGING': value})
