import importlib.util
import os
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / (
    'R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_'
    'FRESH100_TGTD100_ONLY_SEMFIX1_FRESHCACHE_NO_WALLCLOCK.py')


def _load():
    spec = importlib.util.spec_from_file_location('fresh100_freshcache_launcher', LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fresh_run_cache_root_is_run_isolated_and_not_global(tmp_path, monkeypatch):
    mod = _load()
    local = tmp_path / 'localappdata'
    run = tmp_path / 'project' / 'RUN_20261022_123456_000001'
    run.mkdir(parents=True)
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    root = mod._fresh_run_cache_root(run, tmp_path / 'project')
    assert root == local / 'R1_15A2_PATH_CACHE_V248_FRESH_RUNS' / run.name
    assert root != local / 'R1_15A2_PATH_CACHE_V248'
    assert not root.exists()


def test_existing_fresh_run_cache_root_fails_closed(tmp_path, monkeypatch):
    mod = _load()
    local = tmp_path / 'localappdata'
    run = tmp_path / 'project' / 'RUN_COLLISION'
    run.mkdir(parents=True)
    root = local / 'R1_15A2_PATH_CACHE_V248_FRESH_RUNS' / run.name
    root.mkdir(parents=True)
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    try:
        mod._fresh_run_cache_root(run, tmp_path / 'project')
    except RuntimeError as exc:
        assert str(exc).startswith('FRESH_RUN_PATH_CACHE_ROOT_ALREADY_EXISTS:')
    else:
        raise AssertionError('expected fail-closed collision')


def test_launcher_disables_all_cross_run_roots_statically():
    text = LAUNCHER.read_text(encoding='utf-8')
    assert 'cfg["runtime_legacy_path_cache_roots"] = []' in text
    assert 'FRESH_RUN_ISOLATED_NO_CROSS_RUN_RESTORE' in text
    assert 'fresh_path_enumeration_required": True' in text
    main_segment = text[text.index('def _main_impl'):]
    assert 'R1_15A2_PATH_CACHE_V248"' not in main_segment
