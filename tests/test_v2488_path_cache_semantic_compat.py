# -*- coding: utf-8 -*-
"""V2.4.8.8 persistent path-cache semantic compatibility regression tests."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from r1_15a2_persistent_path_cache_v248 import (
    PersistentPathCacheManager, cache_contract,
)
from r1_15a2_supply import SupplyContractError
from r1_15a2_two_mode_v238 import DEFAULT_SETTINGS, SCHEMA
from test_supply_v22 import profile, links
from test_v248_persistent_path_cache import cfg as base_cfg, snapshot

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "R1_15A2_V2_4_8_8_PATH_CACHE_SEMANTIC_COMPAT_20261016"
PATH_MODULES = {
    "r1_15a2_two_mode_v238.py",
    "r1_15a2_trial_adapter_v240.py",
    "r1_15a2_persistent_path_cache_v248.py",
    "r1_15a2_sequence_v23.py",
    "r1_15a2_supply.py",
    "r1_15a2_core.py",
    "r1_15a2_runtime_v1.py",
}


def released_cfg():
    launcher = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_8.py"
    spec = importlib.util.spec_from_file_location("v2488_launcher_test", launcher)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.load_config()


def small_cfg(tmp_path):
    cfg = base_cfg(tmp_path)
    cfg["release"] = RELEASE
    # Test-only target hashes; the compatibility mechanism only needs a complete
    # target implementation map and reviewed source map.
    cfg["config_sha256"] = "f" * 64
    cfg["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"] = {
        "enabled": True,
        "target_release": RELEASE,
        "allowed_contract_differences": [
            "config_sha256", "path_implementation_files", "contract_hash"],
        "policy": "READ_ONLY_EXACT_PATH_DATA_CONTRACT_FULL_SOURCE_IMPL_PIN_CONFIG_DIGEST_PROVENANCE_ONLY",
        "incompatible_candidate_policy":
            "REJECT_CACHE_AS_PERFORMANCE_MISS_THEN_LEGACY_OR_FRESH_ENUMERATION",
        "predecessors": [],
    }
    return cfg


def rows():
    return [profile(model=600, obs=1000, ident="obs-a")]


def make_manifest(contract, release="SOURCE_RELEASE"):
    return {"contract": copy.deepcopy(contract), "release": release,
            "origin_snapshot": {"fixed_link_hash": "fixed"}}


def test_config_digest_mismatch_alone_is_path_semantic_compatible(tmp_path):
    cfg = small_cfg(tmp_path)
    manager = PersistentPathCacheManager(cfg)
    snap = snapshot()
    expected = cache_contract(cfg, snap, rows(), links(), SCHEMA)
    actual = copy.deepcopy(expected)
    actual["config_sha256"] = "a" * 64
    # Old contract_hash necessarily differs because it included config_sha256.
    actual["contract_hash"] = "b" * 64
    result = manager.validate_manifest(
        make_manifest(actual, "SAME_PATH_CODE_OTHER_CONFIG"), snap, rows(), links(), SCHEMA)
    assert result["mode"] == "PATH_SEMANTIC_CONFIG_DIGEST_COMPATIBILITY"
    assert result["full_config_digest_is_provenance_only"] is True


def test_actual_deployed_v2482_zero_volume_release_is_reviewed(tmp_path):
    _, release_cfg = released_cfg()
    rule = next(r for r in release_cfg["performance"]["persistent_path_cache"]
                ["explicit_predecessor_read_compatibility"]["predecessors"]
                if r["source_release"] ==
                "R1_15A2_V2_4_8_2_ZERO_VOLUME_SUPPORT_HOTFIX_20261016")
    assert rule["source_config_sha256s"] == [
        "339dc5d273e780e2d6edf0785353483a7e1a03ed459875feacc15cb17c33d6ec"]
    assert set(rule["source_path_implementation_files"]) == PATH_MODULES


def test_reviewed_predecessor_full_implementation_map_allows_config_digest_drift(tmp_path):
    _, release_cfg = released_cfg()
    source = next(r for r in release_cfg["performance"]["persistent_path_cache"]
                  ["explicit_predecessor_read_compatibility"]["predecessors"]
                  if r["source_release"] ==
                  "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016")

    cfg = small_cfg(tmp_path)
    cfg["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"] = \
        copy.deepcopy(release_cfg["performance"]["persistent_path_cache"]
                      ["explicit_predecessor_read_compatibility"])
    manager = PersistentPathCacheManager(cfg)
    snap = snapshot()
    expected = cache_contract(cfg, snap, rows(), links(), SCHEMA)
    actual = copy.deepcopy(expected)
    actual["config_sha256"] = "0" * 64  # deliberately unknown provenance digest
    actual["contract_hash"] = "1" * 64
    actual["path_implementation_files"] = copy.deepcopy(
        source["source_path_implementation_files"])
    manifest = make_manifest(actual, source["source_release"])
    result = manager.validate_manifest(manifest, snap, rows(), links(), SCHEMA)
    assert result["mode"] == "EXPLICIT_PREDECESSOR_PATH_SEMANTIC_COMPATIBILITY"
    assert result["path_implementation_hashes_fully_pinned"] is True
    assert result["source_config_sha256_recognized"] is False


def test_path_semantic_change_still_fails_closed(tmp_path):
    _, release_cfg = released_cfg()
    source = release_cfg["performance"]["persistent_path_cache"] \
        ["explicit_predecessor_read_compatibility"]["predecessors"][0]
    cfg = small_cfg(tmp_path)
    cfg["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"] = \
        copy.deepcopy(release_cfg["performance"]["persistent_path_cache"]
                      ["explicit_predecessor_read_compatibility"])
    manager = PersistentPathCacheManager(cfg)
    snap = snapshot()
    actual = copy.deepcopy(cache_contract(cfg, snap, rows(), links(), SCHEMA))
    actual["path_export_dsegs"] = ["SOMETHING_ELSE"]
    actual["contract_hash"] = "2" * 64
    with pytest.raises(SupplyContractError, match="CONTRACT_MISMATCH:path_export_dsegs"):
        manager.validate_manifest(make_manifest(actual, RELEASE),
                                  snap, rows(), links(), SCHEMA)


def test_unreviewed_path_implementation_hash_still_fails_closed(tmp_path):
    _, release_cfg = released_cfg()
    source = release_cfg["performance"]["persistent_path_cache"] \
        ["explicit_predecessor_read_compatibility"]["predecessors"][0]
    cfg = small_cfg(tmp_path)
    cfg["performance"]["persistent_path_cache"]["explicit_predecessor_read_compatibility"] = \
        copy.deepcopy(release_cfg["performance"]["persistent_path_cache"]
                      ["explicit_predecessor_read_compatibility"])
    manager = PersistentPathCacheManager(cfg)
    snap = snapshot()
    actual = copy.deepcopy(cache_contract(cfg, snap, rows(), links(), SCHEMA))
    actual["path_implementation_files"] = copy.deepcopy(source["source_path_implementation_files"])
    actual["path_implementation_files"]["r1_15a2_two_mode_v238.py"] = "9" * 64
    actual["contract_hash"] = "3" * 64
    with pytest.raises(SupplyContractError, match="CONTRACT_MISMATCH:path_implementation_files"):
        manager.validate_manifest(make_manifest(actual, source["source_release"]),
                                  snap, rows(), links(), SCHEMA)


def _adapter_for_fallback(tmp_path, error_message):
    import r1_15a2_trial_adapter_v240 as module
    adapter = module.VisumAdapter.__new__(module.VisumAdapter)
    manifest = {
        "cache_id": "CACHE_X", "cache_dir": str(tmp_path / "cache"),
        "release": "OLD_RELEASE",
    }
    (tmp_path / "cache").mkdir()

    class Manager:
        enabled = True
        def find_candidate(self, snapshot):
            return Path(manifest["cache_dir"]), None
        def _load_manifest(self, cache_dir):
            return manifest
        def legacy_candidates(self, snapshot, schema):
            return []

    adapter.persistent_path_cache = Manager()
    adapter._open_persistent_cache = lambda *a, **k: (_ for _ in ()).throw(
        SupplyContractError(error_message))
    adapter.cfg = {
        "runtime_source_version_sha256": "a" * 64,
        "performance": {"persistent_path_cache": {
            "explicit_predecessor_read_compatibility": {
                "incompatible_candidate_policy":
                    "REJECT_CACHE_AS_PERFORMANCE_MISS_THEN_LEGACY_OR_FRESH_ENUMERATION"
            }
        }},
    }
    adapter.policy = SimpleNamespace()
    adapter.control = None
    return adapter


def test_contract_mismatch_is_rejected_as_performance_miss_then_falls_back(tmp_path):
    adapter = _adapter_for_fallback(
        tmp_path, "PERSISTENT_PATH_CACHE_CONTRACT_MISMATCH:path_implementation_files")
    folder = tmp_path / "design"
    result = adapter._try_persistent_restore(
        {"d12": {"rows": []}}, folder, {"state_hash": "state"}, {}, {}, {})
    assert result is None
    rejected = json.loads((folder / "PERSISTENT_PATH_CACHE_REJECTED.json").read_text())
    assert rejected["status"] == "INCOMPATIBLE_PERSISTENT_CACHE_REJECTED"
    assert rejected["fallback"] == "LEGACY_EXACT_STATE_IMPORT_OR_FRESH_ENUMERATION"
    no_match = json.loads((folder / "PERSISTENT_PATH_CACHE_RESTORE.json").read_text())
    assert no_match["status"] == "NO_AUTHORIZED_PERSISTENT_CACHE_MATCH"


def test_integrity_failure_is_not_softened(tmp_path):
    adapter = _adapter_for_fallback(tmp_path, "PERSISTENT_PATH_CACHE_SHA256_MISMATCH")
    with pytest.raises(SupplyContractError, match="SHA256_MISMATCH"):
        adapter._try_persistent_restore(
            {"d12": {"rows": []}}, tmp_path / "design",
            {"state_hash": "state"}, {}, {}, {})
