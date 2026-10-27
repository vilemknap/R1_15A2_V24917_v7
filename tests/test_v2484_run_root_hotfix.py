from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_4.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("v2484_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nested_prior_run_checkpoint_normalizes_to_project_base(tmp_path):
    module = load_launcher()
    project = tmp_path / "project"
    source = project / "R1_15A2_V2481_RUNS" / "RUN_1" / "CALIBRATION" / "CHECKPOINTS" / "ACCEPTED_B_0000.ver"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    base, mode = module._stable_project_base(source)
    assert base == project.resolve()
    assert mode == "PRIOR_RUN_TREE_NORMALIZED"


def test_plain_source_uses_source_parent(tmp_path):
    module = load_launcher()
    source = tmp_path / "project" / "ACCEPTED_B_0000.ver"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x")
    base, mode = module._stable_project_base(source)
    assert base == source.parent.resolve()
    assert mode == "SOURCE_PARENT"


def test_v2484_config_retains_cache_compatibility_and_zero_share_policy():
    module = load_launcher()
    cfg = module.load_config()
    assert module.RELEASE == "R1_15A2_V2_4_8_4_RUN_ROOT_HOTFIX_20261016"
    assert cfg["release"] == module.RELEASE
    compat = cfg["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
    assert compat["enabled"] is True
    assert compat["target_release"] == module.RELEASE
    assert {r["source_release"] for r in compat["predecessors"]} == {
        "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016",
        "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016",
    }
    assert cfg["two_mode"]["zero_share_residual_policy"]["enabled"] is True


def test_v2484_predecessor_cache_contract_path_is_still_authorized(tmp_path):
    from test_v2483_cache_compat import source_and_target
    from r1_15a2_persistent_path_cache_v248 import PersistentPathCacheManager
    from r1_15a2_two_mode_v238 import QuietControl
    from test_supply_v22 import links

    source, target, rows, snap, policy, manifest = source_and_target(tmp_path)
    release = "R1_15A2_V2_4_8_4_RUN_ROOT_HOTFIX_20261016"
    target["release"] = release
    target["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"]["target_release"] = release
    manager = PersistentPathCacheManager(target, QuietControl())
    result = manager.validate_manifest(manifest, snap, rows, links(), manifest["sqlite_schema"])
    assert result["mode"] == "EXPLICIT_PREDECESSOR_READ_COMPATIBILITY"
    assert result["target_release"] == release
