from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_6.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("v2486_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_source(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"immutable-source")
    return path


def test_single_prior_run_checkpoint_normalizes_to_project_base(tmp_path):
    module = load_launcher()
    project = tmp_path / "project"
    source = _write_source(project / "R1_15A2_V2481_RUNS" / "RUN_1" /
                           "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == project.resolve()
    assert layout["mode"] == "OUTERMOST_PRIOR_RUN_TREE_NORMALIZED"
    assert layout["detected_run_roots_nearest_first"] == [
        (project / "R1_15A2_V2481_RUNS").resolve()
    ]


def test_repeatedly_nested_failed_runs_choose_outermost_project_base(tmp_path):
    module = load_launcher()
    project = tmp_path / "project"
    outer = project / "R1_15A2_V2481_RUNS"
    inner = (outer / "RUN_OLD" / "CALIBRATION" / "CHECKPOINTS" /
             "R1_15A2_V2483_RUNS")
    source = _write_source(inner / "RUN_BAD" / "CALIBRATION" / "CHECKPOINTS" /
                           "ACCEPTED.ver")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == project.resolve()
    assert layout["outermost_run_root"] == outer.resolve()
    assert layout["detected_run_roots_nearest_first"] == [
        inner.resolve(), outer.resolve()
    ]
    assert module._stable_project_base(source) == (
        project.resolve(), "OUTERMOST_PRIOR_RUN_TREE_NORMALIZED")


def test_triple_nested_failed_runs_choose_outermost_project_base(tmp_path):
    module = load_launcher()
    project = tmp_path / "project"
    r1 = project / "R1_15A2_V2481_RUNS"
    r2 = r1 / "RUN_A" / "CALIBRATION" / "CHECKPOINTS" / "R1_15A2_V2483_RUNS"
    r3 = r2 / "RUN_B" / "CALIBRATION" / "CHECKPOINTS" / "R1_15A2_V2484_RUNS"
    source = _write_source(r3 / "RUN_C" / "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == project.resolve()
    assert layout["detected_run_roots_nearest_first"] == [
        r3.resolve(), r2.resolve(), r1.resolve()
    ]


def test_unrelated_runs_named_archive_without_run_child_is_not_normalized(tmp_path):
    module = load_launcher()
    source = _write_source(tmp_path / "R1_15A2_ARCHIVE_RUNS" / "models" / "model.ver")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == source.parent.resolve()
    assert layout["mode"] == "SOURCE_PARENT"
    assert layout["detected_run_roots_nearest_first"] == []


def test_postcondition_rejects_new_run_below_any_prior_run_tree(tmp_path):
    module = load_launcher()
    prior = tmp_path / "R1_15A2_V2481_RUNS"
    bad = prior / "RUN_X" / "CALIBRATION" / "CHECKPOINTS" / "R1_15A2_V2486_RUNS" / "RUN_NEW"
    bad.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="V2486_NEW_RUN_STILL_NESTED"):
        module._assert_new_run_is_not_nested(bad, [prior])
    good = tmp_path / "R1_15A2_V2486_RUNS" / "RUN_NEW"
    good.mkdir(parents=True)
    module._assert_new_run_is_not_nested(good, [prior])


def test_v2486_config_retains_zero_share_and_expands_read_compatibility():
    module = load_launcher()
    cfg = module.load_config()
    assert module.RELEASE == "R1_15A2_V2_4_8_6_UNIFIED_ROOT_SATURATION_20261016"
    assert cfg["release"] == module.RELEASE
    stable = cfg["performance"]["stable_project_root"]
    assert stable["enabled"] is True
    assert stable["reject_nested_new_run"] is True
    compat = cfg["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
    assert compat["enabled"] is True
    assert compat["target_release"] == module.RELEASE
    assert {r["source_release"] for r in compat["predecessors"]} == {
        "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016",
        "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016",
        "R1_15A2_V2_4_8_3_CACHE_COMPAT_HOTFIX_20261016",
        "R1_15A2_V2_4_8_4_RUN_ROOT_HOTFIX_20261016",
        "R1_15A2_V2_4_8_5_STABLE_PROJECT_ROOT_20261016",
        "R1_15A2_V2_4_8_5_GENERATION_SATURATION_HOTFIX_20261016",
    }
    assert cfg["two_mode"]["zero_share_residual_policy"]["enabled"] is True
    generation = cfg["generation_bound_constrained_projection"]
    assert generation["enabled"] is True
    assert generation["mode"] == "DIRECT_ACTUATOR_CAPACITY_CLIP_THEN_SAME_FAMILY_ROLE_ATTENUATION"


def test_v2486_v2481_predecessor_cache_contract_is_still_authorized(tmp_path):
    from test_v2483_cache_compat import source_and_target
    from r1_15a2_persistent_path_cache_v248 import PersistentPathCacheManager
    from r1_15a2_two_mode_v238 import QuietControl
    from test_supply_v22 import links

    source, target, rows, snap, policy, manifest = source_and_target(tmp_path)
    release = "R1_15A2_V2_4_8_6_UNIFIED_ROOT_SATURATION_20261016"
    target["release"] = release
    compat = target["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
    compat["target_release"] = release
    manager = PersistentPathCacheManager(target, QuietControl())
    result = manager.validate_manifest(manifest, snap, rows, links(), manifest["sqlite_schema"])
    assert result["mode"] == "EXPLICIT_PREDECESSOR_READ_COMPATIBILITY"
    assert result["target_release"] == release


def test_launcher_initialization_writes_run_at_outer_project_root(tmp_path, monkeypatch):
    module = load_launcher()
    project = tmp_path / "PROJECT"
    outer = project / "R1_15A2_V2481_RUNS"
    inner = outer / "RUN_OLD" / "CALIBRATION" / "CHECKPOINTS" / "R1_15A2_V2483_RUNS"
    source = _write_source(inner / "RUN_BAD" / "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
    source_before = source.read_bytes()
    visum = SimpleNamespace(IO=SimpleNamespace(CurrentVersionFile=str(source)))
    monkeypatch.setattr(module.com, "bind_injected", lambda _g: (visum, "TEST"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LOCALAPPDATA"))

    def stop_after_root(_visum, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"working-copy")
        raise RuntimeError("TEST_STOP_AFTER_RUN_ROOT_EVIDENCE")

    monkeypatch.setattr(module.rt, "save_version", stop_after_root)
    result = module._main_impl()
    assert result["status"] == "FULL_OVERNIGHT_FAILED"
    assert "TEST_STOP_AFTER_RUN_ROOT_EVIDENCE" in result["error"]
    runs = project / "R1_15A2_V2486_RUNS"
    run_dirs = [p for p in runs.iterdir() if p.is_dir() and p.name.startswith("RUN_")]
    assert len(run_dirs) == 1
    run = run_dirs[0]
    authority = json.loads((run / "RUN_ROOT_AUTHORITY.json").read_text(encoding="utf-8"))
    assert Path(authority["project_base"]) == project.resolve()
    assert authority["project_base_mode"] == "OUTERMOST_PRIOR_RUN_TREE_NORMALIZED"
    assert authority["normalization_depth"] == 2
    assert Path(authority["runs_root"]) == runs.resolve()
    assert authority["postcondition_new_run_outside_all_detected_prior_run_roots"] is True
    cache_location = json.loads((run / "PERSISTENT_PATH_CACHE_LOCATION.json").read_text(encoding="utf-8"))
    assert all(Path(p).parent == project.resolve() for p in cache_location["legacy_roots"])
    assert (inner / "RUN_BAD" / "CALIBRATION" / "CHECKPOINTS" / "R1_15A2_V2486_RUNS").exists() is False
    assert source.read_bytes() == source_before
    assert not (project / ".R1_15A2_FULL_CALIBRATION.lock").exists()
