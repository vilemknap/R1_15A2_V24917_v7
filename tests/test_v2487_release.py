from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_7.py"
RELEASE = "R1_15A2_V2_4_8_7_LIVE_COEFFICIENT_AUTHORITY_20261016"


def load_launcher():
    spec = importlib.util.spec_from_file_location("v2487_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"immutable-source")
    return path


def test_v2487_config_uses_live_current_coefficient_authority():
    module = load_launcher()
    cfg = module.load_config()
    assert module.RELEASE == RELEASE
    assert cfg["release"] == RELEASE
    authority = cfg["generation_coefficient_authority"]
    assert authority["enabled"] is True
    assert authority["mode"] == "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP"
    assert authority["absolute_upper_bound"] is None
    assert authority["allow_current_above_legacy_max"] is True
    assert authority["allow_proposed_above_legacy_max"] is True
    assert cfg["add_max"] is None
    assert cfg["salary"]["salary_min"] is None
    assert cfg["salary"]["salary_max"] is None
    assert cfg["zahr"]["max"] is None
    generation = cfg["generation_bound_constrained_projection"]
    assert generation["legacy_absolute_upper_bounds_enforced"] is False
    assert generation["current_live_values_are_authority"] is True
    assert generation["outward_bound_policy"] == \
        "NO_GLOBAL_ABSOLUTE_MAX_CURRENT_VALUE_PLUS_RELATIVE_LOG_STEP"


def test_v2487_cache_compatibility_includes_v2486():
    module = load_launcher()
    cfg = module.load_config()
    compat = cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    assert compat["target_release"] == RELEASE
    releases = {row["source_release"] for row in compat["predecessors"]}
    assert "R1_15A2_V2_4_8_6_UNIFIED_ROOT_SATURATION_20261016" in releases
    assert len(releases) == 7


def test_v2487_stable_project_root_remains_outermost(tmp_path):
    module = load_launcher()
    project = tmp_path / "PROJECT"
    outer = project / "R1_15A2_V2481_RUNS"
    inner = outer / "RUN_A" / "CALIBRATION" / "CHECKPOINTS" / "R1_15A2_V2484_RUNS"
    source = _write(inner / "RUN_B" / "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
    layout = module._stable_project_layout(source)
    assert layout["project_base"] == project.resolve()
    assert layout["mode"] == "OUTERMOST_PRIOR_RUN_TREE_NORMALIZED"
    assert len(layout["detected_run_roots_nearest_first"]) == 2
    good = project / "R1_15A2_V2487_RUNS" / "RUN_NEW"
    good.mkdir(parents=True)
    module._assert_new_run_is_not_nested(good, layout["detected_run_roots_nearest_first"])
    bad = inner / "RUN_B" / "CALIBRATION" / "CHECKPOINTS" / "R1_15A2_V2487_RUNS" / "RUN_BAD"
    bad.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="V2487_NEW_RUN_STILL_NESTED"):
        module._assert_new_run_is_not_nested(bad, layout["detected_run_roots_nearest_first"])


def test_v2487_launcher_initializes_runs_at_project_root(tmp_path, monkeypatch):
    module = load_launcher()
    project = tmp_path / "PROJECT"
    outer = project / "R1_15A2_V2481_RUNS"
    source = _write(outer / "RUN_OLD" / "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED.ver")
    before = source.read_bytes()
    visum = SimpleNamespace(IO=SimpleNamespace(CurrentVersionFile=str(source)))
    monkeypatch.setattr(module.com, "bind_injected", lambda _g: (visum, "TEST"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LOCALAPPDATA"))

    def stop(_visum, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"working")
        raise RuntimeError("TEST_STOP_AFTER_ROOT")

    monkeypatch.setattr(module.rt, "save_version", stop)
    result = module._main_impl()
    assert result["status"] == "FULL_OVERNIGHT_FAILED"
    runs = project / "R1_15A2_V2487_RUNS"
    run = next(p for p in runs.iterdir() if p.is_dir())
    auth = json.loads((run / "RUN_ROOT_AUTHORITY.json").read_text(encoding="utf-8"))
    assert Path(auth["project_base"]) == project.resolve()
    assert auth["postcondition_new_run_outside_all_detected_prior_run_roots"] is True
    assert source.read_bytes() == before
