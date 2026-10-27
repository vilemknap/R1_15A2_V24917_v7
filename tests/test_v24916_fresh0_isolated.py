from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path

import pytest


def _load_launcher(root: Path):
    path = root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py"
    spec = importlib.util.spec_from_file_location("v24916_fresh0_isolated_launcher_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_fresh0_active_runtime_contract():
    parent = importlib.import_module(
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_NO_WALLCLOCK"
    )
    active = importlib.import_module("r1_15a2_active_targeting_runtime_v24916_fresh0isolated")
    base = parent.load_config("FULL")
    parent._bind_current_profile_authority(base)
    child = active.apply_active_runtime_delta(base)
    audit = active.validate_active_runtime_delta(child, base)
    assert audit["passes"] is True
    assert audit["accepted_count_start"] == 0
    assert audit["outer_cycle_start"] == 1
    assert audit["generation_targeting_enabled"] is True
    assert audit["td_mask_enabled"] is True
    assert audit["external_cache_read_allowed"] is False
    assert audit["persistent_path_cache_enabled"] is False
    assert audit["persistent_path_cache_reads_allowed"] is False
    assert audit["persistent_path_cache_writes_allowed"] is False
    assert audit["cross_run_cache_restore_allowed"] is False
    assert audit["within_run_path_basis_reuse_allowed"] is True
    iso = child["v24916_parallel_isolation"]
    assert iso["legacy_cache_import_allowed"] is False
    assert iso["shared_project_lock_allowed"] is False
    assert iso["shared_runs_root_allowed"] is False
    assert iso["shared_path_cache_root_allowed"] is False
    assert iso["persistent_path_cache_enabled"] is False
    assert iso["persistent_path_cache_reads_allowed"] is False
    assert iso["persistent_path_cache_writes_allowed"] is False
    assert child["performance"]["persistent_path_cache"]["enabled"] is False
    assert child["performance"]["persistent_path_cache"]["allow_legacy_v247_import"] is False
    assert child["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"]["enabled"] is False
    assert child["v24916_fresh_baseline"]["prior_lineage_resumed"] if "prior_lineage_resumed" in child["v24916_fresh_baseline"] else True
    assert child["v24916_fresh_baseline"]["accepted_count_start"] == 0
    assert child["v24916_fresh_baseline"]["outer_cycle_start"] == 1


def test_isolated_workspace_moves_parent_lock_off_v24915_project_root(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    source = tmp_path / "BASELINE.ver"
    source.write_bytes(b"x")
    layout = launcher._isolated_project_layout(source)
    project_base = Path(layout["project_base"])
    runs_root = Path(layout["parallel_isolation_workspace"])
    assert project_base == tmp_path
    assert runs_root == tmp_path / launcher.RUNS_ROOT_NAME
    shared_v24915_lock = tmp_path / ".R1_15A2_FULL_CALIBRATION.lock"
    v24916_effective_lock = project_base / launcher.LOCK_NAME
    assert v24916_effective_lock != shared_v24915_lock
    assert not shared_v24915_lock.exists()


def test_disabled_cache_sentinel_is_inside_current_run_and_starts_absent(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    workspace = tmp_path / launcher.RUNS_ROOT_NAME
    run = workspace / "RUN_20261022_123456_000001"
    run.mkdir(parents=True)
    cache = launcher._isolated_fresh_run_cache_root(run, tmp_path)
    assert cache == run / launcher.PRIVATE_CACHE_DIRNAME
    assert launcher.PRIVATE_CACHE_DIRNAME == "PC_OFF"
    assert not cache.exists()
    assert str(cache).startswith(str(run))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        assert not str(cache).lower().startswith(str(Path(local_appdata)).lower())


def test_existing_disabled_cache_sentinel_is_fail_closed(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    workspace = tmp_path / launcher.RUNS_ROOT_NAME
    run = workspace / "RUN_X"
    run.mkdir(parents=True)
    cache = run / launcher.PRIVATE_CACHE_DIRNAME
    cache.mkdir()
    with pytest.raises(RuntimeError, match="DISABLED_CACHE_SENTINEL_MUST_START_ABSENT"):
        launcher._isolated_fresh_run_cache_root(run, tmp_path)


def test_wrong_project_base_cannot_receive_private_cache(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    wrong = tmp_path / "R1_15A2_V24915_PERF2C_FRESH100_RUNS"
    run = wrong / "RUN_X"
    run.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="ISOLATED_PROJECT_BASE_MISMATCH"):
        launcher._isolated_fresh_run_cache_root(run, tmp_path)


def test_parent_freshcache_contract_forbids_cross_run_restore():
    parent = importlib.import_module(
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_NO_WALLCLOCK"
    )
    text = Path(parent.__file__).read_text(encoding="utf-8")
    assert "legacy_roots = []" in text
    assert 'cfg["runtime_legacy_path_cache_roots"] = []' in text
    assert '"cross_run_restore_allowed": False' in text
    assert '"legacy_import_allowed": False' in text
    assert '"fresh_path_enumeration_required": True' in text
    assert '"within_run_cache_reuse_allowed": True' in text


def test_launcher_uses_fresh_parent_not_a0004_recovery():
    root = Path(__file__).resolve().parents[1]
    text = (root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py").read_text(encoding="utf-8")
    assert "r1_15a2_fresh0_shortroot_parent_v24916" in text
    child = (root / "r1_15a2_fresh0_shortroot_parent_v24916.py").read_text(encoding="utf-8")
    assert "FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_CYCLE1_NO_WALLCLOCK" in child
    assert "R1_15A2_RESUME_PROFILE488_A0004" not in text
    assert "accepted_count_start=0" in text
    assert "outer_cycle_start=1" in text


def test_universal_fresh0_has_no_package_baked_semantic_hash():
    active = importlib.import_module("r1_15a2_active_targeting_runtime_v24916_fresh0isolated")
    assert active.EXPECTED_BASELINE_SEMANTIC_STATE_HASH is None
    assert active.SOURCE_SEMANTIC_POLICY == "CURRENT_OPEN_VER_IS_DYNAMIC_BASELINE_PROVENANCE_ONLY"
    parent = importlib.import_module(
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_NO_WALLCLOCK"
    )
    base = parent.load_config("FULL")
    parent._bind_current_profile_authority(base)
    child = active.apply_active_runtime_delta(base)
    iso = child["v24916_parallel_isolation"]
    assert iso["fixed_source_semantic_hash_required"] is False
    assert iso["source_semantic_state_hash_required"] is None
    assert child["v24916_fresh_baseline"]["fixed_source_semantic_hash_required"] is False




def test_universal_launcher_does_not_compare_to_fixed_semantic_hash():
    root = Path(__file__).resolve().parents[1]
    text = (root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py").read_text(encoding="utf-8")
    assert "V24916_FRESH0_WRONG_BASELINE_SEMANTIC_STATE" not in text
    assert "CURRENT_OPEN_VER_IS_DYNAMIC_BASELINE_PROVENANCE_ONLY" not in text  # imported constant, not duplicated literal
    assert "fixed_semantic_hash_required" in text
    assert "captured_semantic_state_hash" in text

def test_oneclick_bootstrap_exists_before_preflight_and_handoff(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    source = tmp_path / "BASELINE.ver"
    source.write_bytes(b"x")
    visum = SimpleNamespace(IO=SimpleNamespace(CurrentVersionFile=str(source)))
    monkeypatch.setattr(launcher.com, "bind_injected", lambda g: (visum, None))
    seen = {}

    def fake_preflight(v, workspace):
        bootstrap = Path(workspace) / launcher.BOOTSTRAP_FILE
        assert bootstrap.is_file()
        payload = __import__('json').loads(bootstrap.read_text(encoding='utf-8'))
        assert payload["status"] == "BOOTSTRAP_STARTED"
        assert payload["accepted_count_start"] == 0
        assert payload["outer_cycle_start"] == 1
        assert payload["external_cache_read_allowed"] is False
        seen["workspace"] = str(workspace)
        return ({
            "passes": True,
            "authority_hash": "abc",
            "source_semantic_state_hash": "a" * 64,
        }, {"passes": True})

    monkeypatch.setattr(launcher, "_run_live_preflight", fake_preflight)
    monkeypatch.setattr(launcher, "_install_runtime", lambda *a, **k: {"installed": True})
    monkeypatch.setattr(launcher.parent, "main", lambda mode: {"status": "RETURNED", "mode": mode})
    result = launcher.main()
    assert result == {"status": "RETURNED", "mode": "FULL"}
    workspace = Path(seen["workspace"])
    payload = __import__('json').loads((workspace / launcher.BOOTSTRAP_FILE).read_text(encoding='utf-8'))
    assert payload["status"] == "CALIBRATION_RETURNED"
    assert workspace.name == launcher.WORKSPACE_NAME


def test_oneclick_failure_is_recorded_without_touching_shared_v24915_root(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    import json
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    source = tmp_path / "BASELINE.ver"
    source.write_bytes(b"x")
    visum = SimpleNamespace(IO=SimpleNamespace(CurrentVersionFile=str(source)))
    monkeypatch.setattr(launcher.com, "bind_injected", lambda g: (visum, None))
    monkeypatch.setattr(launcher, "_run_live_preflight", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("PREFLIGHT_FAIL")))
    with pytest.raises(RuntimeError, match="PREFLIGHT_FAIL"):
        launcher.main()
    workspace = tmp_path / launcher.WORKSPACE_NAME
    payload = json.loads((workspace / launcher.BOOTSTRAP_FILE).read_text(encoding='utf-8'))
    assert payload["status"] == "FAILED"
    assert payload["exception"] == "PREFLIGHT_FAIL"
    assert not (tmp_path / ".R1_15A2_FULL_CALIBRATION.lock").exists()


def test_persistent_cache_manager_is_hard_disabled_without_any_root():
    parent = importlib.import_module(
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_FRESH100_PROFILE488_FRESHCACHE_SAVEFIX1_NO_WALLCLOCK"
    )
    active = importlib.import_module("r1_15a2_active_targeting_runtime_v24916_fresh0isolated")
    cache_mod = importlib.import_module("r1_15a2_persistent_path_cache_v248")
    base = parent.load_config("FULL")
    parent._bind_current_profile_authority(base)
    child = active.apply_active_runtime_delta(base)
    child.pop("runtime_persistent_path_cache_root", None)
    child["runtime_legacy_path_cache_roots"] = []
    manager = cache_mod.PersistentPathCacheManager(child, None)
    assert manager.enabled is False
    assert manager.root is None
    assert manager.legacy_roots == []
    assert manager.allow_legacy is False


def test_launcher_never_points_persistent_cache_to_localappdata_or_v24915_root():
    root = Path(__file__).resolve().parents[1]
    text = (root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py").read_text(encoding="utf-8")
    runtime_text = (root / "r1_15a2_active_targeting_runtime_v24916_fresh0isolated.py").read_text(encoding="utf-8")
    assert "PERSISTENT_PATH_CACHE_DISABLED" in text or "PRIVATE_CACHE_DIRNAME" in text
    assert '"persistent_path_cache_enabled": False' in runtime_text
    assert '"persistent_path_cache_reads_allowed": False' in runtime_text
    assert '"persistent_path_cache_writes_allowed": False' in runtime_text
    assert 'cfg["performance"]["persistent_path_cache"]["enabled"] = False' in runtime_text


def test_parallel_v24915_lock_can_exist_while_v24916_uses_private_lock(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    source = tmp_path / "BASELINE.ver"
    source.write_bytes(b"x")
    # Simulate the already-running V24915 process owning its normal project lock.
    shared_lock = tmp_path / ".R1_15A2_FULL_CALIBRATION.lock"
    shared_lock.write_text('{"owner":"V24915"}', encoding="utf-8")

    layout = launcher._isolated_project_layout(source)
    project_base = Path(layout["project_base"])
    private_lock = project_base / launcher.LOCK_NAME
    project_base.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(private_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        assert shared_lock.is_file()
        assert private_lock.is_file()
        assert private_lock != shared_lock
        assert private_lock.parent == project_base
    finally:
        private_lock.unlink(missing_ok=True)
