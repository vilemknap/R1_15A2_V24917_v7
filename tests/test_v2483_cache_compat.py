# -*- coding: utf-8 -*-
"""V2.4.8.3 exact predecessor persistent-cache compatibility gates."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import importlib.util

import pytest

from r1_15a2_persistent_path_cache_v248 import PersistentPathCacheManager
from r1_15a2_supply import SupplyPolicy, SupplyContractError
from r1_15a2_two_mode_v238 import QuietControl
from r1_15a2_trial_adapter_v240 import VisumAdapter
from test_supply_v22 import profile, links
from test_v248_persistent_path_cache import cfg, snapshot, make_collector

ROOT = Path(__file__).resolve().parents[1]
SOURCE_RELEASE = "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016"
TARGET_RELEASE = "R1_15A2_V2_4_8_3_CACHE_COMPAT_HOTFIX_20261016"
ALLOWED = (
    "r1_15a2_two_mode_v238.py",
    "r1_15a2_trial_adapter_v240.py",
    "r1_15a2_persistent_path_cache_v248.py",
)


def source_and_target(tmp_path):
    source = cfg(tmp_path)
    source["release"] = SOURCE_RELEASE
    source["config_sha256"] = "1" * 64
    rows = [profile(model=600, obs=1000, ident="obs-a")]
    snap = snapshot()
    source_manager = PersistentPathCacheManager(source, QuietControl())
    staging, collector, policy = make_collector(source_manager, rows, snap)
    manifest, _ = source_manager.publish(
        staging, collector, snap, rows, links(), sequence_evidence_ready=False,
        source_version_sha256=source["runtime_source_version_sha256"])

    target = deepcopy(source)
    target["release"] = TARGET_RELEASE
    target["config_sha256"] = "2" * 64
    source_hashes = {name: source["implementation_files"][name] for name in ALLOWED}
    for i, name in enumerate(ALLOWED, 7):
        target["implementation_files"][name] = (str(i) * 64)[:64]
    target["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"] = {
            "enabled": True,
            "target_release": TARGET_RELEASE,
            "allowed_contract_differences": [
                "config_sha256", "path_implementation_files", "contract_hash"],
            "predecessors": [{
                "source_release": SOURCE_RELEASE,
                "source_config_sha256": source["config_sha256"],
                "source_path_implementation_files": source_hashes,
            }],
            "policy": "READ_ONLY_EXACT_PREDECESSOR_STORE_WITH_ALL_NONCONSUMER_CONTRACT_FIELDS_EXACT",
        }
    target["dseg_path_volume_relative_tolerance"] = 0.01
    return source, target, rows, snap, policy, manifest


def make_adapter(target, policy):
    adapter = VisumAdapter.__new__(VisumAdapter)
    adapter.cfg = target
    adapter.control = QuietControl()
    adapter.telemetry = None
    adapter.policy = policy
    adapter.visum = object()
    adapter.cache = None
    adapter.cache_links = None
    adapter.cache_snapshot = None
    adapter.cache_live_snapshot = None
    adapter.initial_snapshot = None
    adapter.path_epoch_index = 0
    adapter.path_epoch_accepts = 0
    adapter.path_epoch_refresh_counts = {"DEMAND": 0, "SUPPLY": 0}
    adapter.path_epoch_plateau_verified = None
    adapter.path_epoch_history = []
    adapter.supply_path_proof = None
    adapter.persistent_path_cache = PersistentPathCacheManager(target, adapter.control)
    adapter.persistent_cache_manifest = None
    adapter.persistent_cache_restore_record = None
    adapter.read_links = lambda: {k: dict(v, object=object()) for k, v in links().items()}
    return adapter


def test_exact_predecessor_cache_restores_without_com_enumeration(tmp_path, monkeypatch):
    import r1_15a2_trial_adapter_v240 as adapter_module

    source, target, rows, snap, policy, manifest = source_and_target(tmp_path)
    adapter = make_adapter(target, policy)

    def forbidden_enumeration(*args, **kwargs):
        raise AssertionError("known predecessor cache must restore without COM enumeration")

    monkeypatch.setattr(adapter_module, "collect_two_modes", forbidden_enumeration)
    collector, _, record = adapter._build_cache(
        {"d12": {"rows": rows}}, tmp_path / "target-run", snap,
        allow_persistent_restore=True)
    try:
        assert collector.read_only is True
        assert record["status"] == "PERSISTENT_PATH_EPOCH_RESTORED"
        assert record["contract_validation"]["mode"] == "EXPLICIT_PREDECESSOR_READ_COMPATIBILITY"
        assert record["contract_validation"]["source_release"] == SOURCE_RELEASE
        assert record["contract_validation"]["target_release"] == TARGET_RELEASE
        assert Path(record["cache_dir"]) == Path(manifest["cache_dir"])
    finally:
        adapter.close()


def test_predecessor_compatibility_rejects_unlisted_module_drift(tmp_path):
    source, target, rows, snap, policy, manifest = source_and_target(tmp_path)
    target["implementation_files"]["r1_15a2_supply.py"] = "f" * 64
    manager = PersistentPathCacheManager(target, QuietControl())
    with pytest.raises(SupplyContractError, match="PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH"):
        manager.validate_manifest(manifest, snap, rows, links(), manifest["sqlite_schema"])


def test_v2483_launcher_locks_predecessor_rules_and_zero_share_policy():
    launcher = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_3.py"
    spec = importlib.util.spec_from_file_location("v2483_launcher", launcher)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded = module.load_config()
    compat = loaded["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    assert loaded["release"] == TARGET_RELEASE == module.RELEASE
    assert compat["enabled"] is True
    assert {r["source_release"] for r in compat["predecessors"]} == {
        "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016",
        "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016",
    }
    assert loaded["two_mode"]["zero_share_residual_policy"]["enabled"] is True
