# -*- coding: utf-8 -*-
"""V2.4.8 persistent cross-run path epoch checkpoints."""
from __future__ import annotations

from pathlib import Path
import json
import sqlite3

import pytest

from r1_15a2_persistent_path_cache_v248 import (
    PersistentPathCacheManager, STORE_NAME, MANIFEST_NAME,
    sha256_file, cache_contract,
)
from r1_15a2_supply import SupplyPolicy, SupplyContractError
from r1_15a2_two_mode_v238 import (
    TwoModeRouteCollector, DEFAULT_SETTINGS, QuietControl, SCHEMA,
)
from test_supply_v22 import profile, links
from test_two_mode_v238 import authority, hierarchy

ROOT = Path(__file__).resolve().parents[1]


def cfg(tmp_path):
    implementation = {name: (str(i) * 64)[:64] for i, name in enumerate((
        "r1_15a2_two_mode_v238.py",
        "r1_15a2_trial_adapter_v240.py",
        "r1_15a2_persistent_path_cache_v248.py",
        "r1_15a2_sequence_v23.py",
        "r1_15a2_supply.py",
        "r1_15a2_core.py",
        "r1_15a2_runtime_v1.py",
    ), 1)}
    return {
        "release": "R1_15A2_V2_4_8_TEST",
        "config_sha256": "a" * 64,
        "implementation_files": implementation,
        "expected_zones": 2,
        "path_export_dsegs": ["NATIVE_CW"],
        "mutable_dsegs": ["NATIVE_CW"],
        "two_mode": dict(DEFAULT_SETTINGS),
        "supply": {
            "passenger_dsegs": ["NATIVE_CW"],
            "sequence": {
                "design_only_duplicate_scope_policy": "DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS",
                "max_unique_sequences": 100000,
                "max_pairs_per_market": 64,
            },
        },
        "performance": {
            "persistent_path_cache": {
                "enabled": True,
                "verify_sha256_on_restore": True,
                "sqlite_quick_check_on_restore": True,
                "allow_legacy_v247_import": True,
                "retain_epoch_checkpoints": 3,
            },
        },
        "runtime_persistent_path_cache_root": str(tmp_path / "persistent"),
        "runtime_legacy_path_cache_roots": [],
        "runtime_source_version_sha256": "b" * 64,
    }


def snapshot(state="state-origin", generation="gen-0", matrix="mat-0", add="add-0"):
    return {
        "state_hash": state,
        "fixed_link_hash": "fixed",
        "dseg_hash": "dseg",
        "operations_hash": "ops",
        "addval_hash": add,
        "matrix_hash": matrix,
        "generation_hash": generation,
        "td_hash": "td-0",
    }


def make_collector(manager, rows, snap):
    staging = manager.allocate_staging()
    policy = SupplyPolicy(min_geh=1, min_residual=1, max_candidates=8)
    collector = TwoModeRouteCollector(
        rows, policy, snap["state_hash"], links(), staging / STORE_NAME,
        dict(DEFAULT_SETTINGS), QuietControl(),
        duplicate_scope_policy="DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS")
    collector.add_parents(
        "NATIVE_CW", "C", [[1, 2, 1, 600], [1, 2, 2, 400]],
        authority([600, 400]))
    collector.add_geometry("C", hierarchy())
    collector.prepare_incidence_evidence()
    return staging, collector, policy


def publish(tmp_path):
    conf = cfg(tmp_path)
    manager = PersistentPathCacheManager(conf, QuietControl())
    rows = [profile(model=600, obs=1000, ident="obs-a")]
    snap = snapshot()
    staging, collector, policy = make_collector(manager, rows, snap)
    manifest, publication = manager.publish(
        staging, collector, snap, rows, links(), sequence_evidence_ready=False,
        source_version_sha256=conf["runtime_source_version_sha256"])
    return conf, manager, rows, snap, policy, manifest, publication


def test_publish_restore_and_read_only_reopen(tmp_path):
    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    assert publication["published"] is True
    cache_dir = Path(manifest["cache_dir"])
    assert (cache_dir / STORE_NAME).is_file()
    assert (cache_dir / MANIFEST_NAME).is_file()
    assert manifest["store_sha256"] == sha256_file(cache_dir / STORE_NAME)
    candidate = manager.find_candidate(snap)
    assert candidate is not None and candidate[0] == cache_dir
    manager.validate_manifest(manifest, snap, rows, links(), SCHEMA)
    validation = manager.validate_store(cache_dir, manifest)
    assert validation["integrity"]["result"] == "ok"
    reopened = TwoModeRouteCollector.open_existing(
        rows, policy, links(), cache_dir / STORE_NAME, DEFAULT_SETTINGS,
        QuietControl(),
        duplicate_scope_policy="DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS",
        read_only=True, require_profile_metadata=True)
    try:
        assert reopened.read_only is True
        assert reopened.path_basis_hash() == manifest["path_basis_hash"]
        assert reopened.path_basis_comparison_hash() == manifest["path_basis_comparison_hash"]
        with pytest.raises(sqlite3.OperationalError):
            reopened.db.execute("DELETE FROM metadata")
    finally:
        reopened.close()


def test_descendant_state_requires_and_uses_explicit_binding(tmp_path):
    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    descendant = snapshot(state="state-descendant", generation="gen-1",
                          matrix="mat-1", add="add-1")
    assert manager.find_candidate(descendant) is None
    binding = manager.bind_state(
        descendant, manifest, reason="TG_ACCEPTED", phase="DEMAND")
    assert binding["origin_state_hash"] == snap["state_hash"]
    candidate = manager.find_candidate(descendant)
    assert candidate is not None
    cache_dir, loaded_binding = candidate
    assert loaded_binding["state_hash"] == descendant["state_hash"]
    manager.validate_manifest(manifest, descendant, rows, links(), SCHEMA)


def test_immutable_context_drift_rejects_binding_and_restore(tmp_path):
    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    drift = dict(snapshot(state="state-drift"), fixed_link_hash="changed")
    with pytest.raises(SupplyContractError, match="IMMUTABLE_CONTEXT_CHANGED"):
        manager.bind_state(drift, manifest, reason="BAD", phase="DEMAND")
    # A forged binding cannot pass the manifest contract either.
    path = manager._binding_path(drift["state_hash"])
    path.write_text(json.dumps({
        "schema": "R1_15A2_PERSISTENT_PATH_EPOCH_BINDING_V248",
        "state_hash": drift["state_hash"],
        "cache_dir": manifest["cache_dir"],
    }), encoding="utf-8")
    with pytest.raises(SupplyContractError, match="BINDING_MISMATCH|IMMUTABLE_CONTEXT"):
        manager.find_candidate(drift)


def test_store_tamper_is_detected_before_restore(tmp_path):
    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    store = Path(manifest["cache_dir"]) / STORE_NAME
    with store.open("r+b") as handle:
        handle.seek(-32, 2)
        data = handle.read(1)
        handle.seek(-1, 1)
        handle.write(bytes([data[0] ^ 0x01]))
    with pytest.raises(SupplyContractError, match="SQLITE|SHA256"):
        manager.validate_store(Path(manifest["cache_dir"]), manifest)


def test_profile_order_metadata_blocks_reordered_profiles(tmp_path):
    conf = cfg(tmp_path)
    manager = PersistentPathCacheManager(conf, QuietControl())
    rows = [profile(model=600, obs=1000, ident="obs-a"),
            profile(model=0, obs=1000, ident="obs-b")]
    snap = snapshot()
    staging = manager.allocate_staging()
    policy = SupplyPolicy(min_geh=1, min_residual=1, max_candidates=8)
    collector = TwoModeRouteCollector(
        rows, policy, snap["state_hash"], links(), staging / STORE_NAME,
        dict(DEFAULT_SETTINGS), QuietControl(),
        duplicate_scope_policy="DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS")
    collector.add_parents("NATIVE_CW", "C",
                          [[1, 2, 1, 600], [1, 2, 2, 400]], authority([600, 400]))
    collector.add_geometry("C", hierarchy())
    collector.prepare_incidence_evidence()
    manifest, _ = manager.publish(staging, collector, snap, rows, links(),
                                  sequence_evidence_ready=False)
    with pytest.raises(SupplyContractError, match="PROFILE_ORDER_CHANGED"):
        TwoModeRouteCollector.open_existing(
            list(reversed(rows)), policy, links(),
            Path(manifest["cache_dir"]) / STORE_NAME, DEFAULT_SETTINGS,
            QuietControl(),
            duplicate_scope_policy="DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS",
            read_only=True, require_profile_metadata=True)


def test_v248_config_and_launcher_are_hash_locked():
    import importlib.util
    launcher = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8.py"
    spec = importlib.util.spec_from_file_location("v248_launcher", launcher)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded = module.load_config()
    assert loaded["performance"]["release"] == "V2.4.8"
    assert loaded["performance"]["persistent_path_cache"]["enabled"] is True
    assert "r1_15a2_persistent_path_cache_v248.py" in loaded["implementation_files"]
    assert loaded["release"] == module.RELEASE


def test_binding_tamper_is_fail_closed(tmp_path):
    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    descendant = snapshot(state="state-descendant", generation="gen-1",
                          matrix="mat-1", add="add-1")
    manager.bind_state(descendant, manifest, reason="TG_ACCEPTED", phase="DEMAND")
    path = manager._binding_path(descendant["state_hash"])
    binding = json.loads(path.read_text(encoding="utf-8"))
    binding["path_basis_hash"] = "forged"
    path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(SupplyContractError, match="BINDING_MISMATCH:path_basis_hash"):
        manager.find_candidate(descendant)


def test_manifest_tamper_is_detected_before_restore(tmp_path):
    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    path = Path(manifest["cache_dir"]) / MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["path_structure_hash"] = "forged"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SupplyContractError, match="MANIFEST_HASH_MISMATCH"):
        manager.find_candidate(snap)


def test_adapter_restart_restores_without_com_path_enumeration(tmp_path, monkeypatch):
    import r1_15a2_trial_adapter_v240 as adapter_module
    from r1_15a2_trial_adapter_v240 import VisumAdapter

    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    conf["dseg_path_volume_relative_tolerance"] = 0.01

    adapter = VisumAdapter.__new__(VisumAdapter)
    adapter.cfg = conf
    adapter.control = QuietControl()
    adapter.telemetry = None
    adapter.policy = policy
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
    adapter.persistent_path_cache = PersistentPathCacheManager(conf, adapter.control)
    adapter.persistent_cache_manifest = None
    adapter.persistent_cache_restore_record = None
    adapter.read_links = lambda: {k: dict(v, object=object()) for k, v in links().items()}

    def forbidden_enumeration(*args, **kwargs):
        raise AssertionError("COM path enumeration must not run on authorized restart")

    monkeypatch.setattr(adapter_module, "collect_two_modes", forbidden_enumeration)
    collector, restored_links, record = adapter._build_cache(
        {"d12": {"rows": rows}}, tmp_path / "second-run", snap,
        build_sequence_evidence=False, allow_persistent_restore=True)
    try:
        assert collector.read_only is True
        assert record["status"] == "PERSISTENT_PATH_EPOCH_RESTORED"
        assert record["matched_by"] in ("STATE_BINDING", "ORIGIN_STATE_HASH")
        assert adapter.path_epoch_status()["persistent_cache_id"] == manifest["cache_id"]
        assert Path(record["cache_dir"]) == Path(manifest["cache_dir"])
        assert restored_links.keys() == links().keys()
    finally:
        adapter.close()


def test_retention_prunes_old_cache_and_rewrites_index(tmp_path):
    conf = cfg(tmp_path)
    conf["performance"]["persistent_path_cache"]["retain_epoch_checkpoints"] = 2
    conf["performance"]["persistent_path_cache"]["max_total_cache_gib"] = 1.0
    manager = PersistentPathCacheManager(conf, QuietControl())
    rows = [profile(model=600, obs=1000, ident="obs-a")]
    policy = SupplyPolicy(min_geh=1, min_residual=1, max_candidates=8)
    manifests = []
    for i in range(3):
        snap = snapshot(state="state-%d" % i, generation="gen-%d" % i,
                        matrix="mat-%d" % i, add="add-%d" % i)
        staging, collector, _ = make_collector(manager, rows, snap)
        manifest, publication = manager.publish(
            staging, collector, snap, rows, links(), sequence_evidence_ready=False)
        manifests.append(manifest)
    assert not Path(manifests[0]["cache_dir"]).exists()
    assert Path(manifests[1]["cache_dir"]).is_dir()
    assert Path(manifests[2]["cache_dir"]).is_dir()
    index = json.loads((manager.root / "PATH_EPOCH_INDEX.json").read_text(encoding="utf-8"))
    assert [e["cache_id"] for e in index["entries"]] == [
        manifests[1]["cache_id"], manifests[2]["cache_id"]]
    assert not manager._binding_path("state-0").exists()


def test_accepted_ver_checkpoint_records_path_epoch_lineage(tmp_path):
    import r1_15a2_overnight_controller_v240 as controller
    from tests.synthetic_v22_adapter import SyntheticAdapter, synthetic_config

    adapter = SyntheticAdapter(synthetic_config())
    adapter.path_epoch_status = lambda: {
        "enabled": True,
        "epoch": 3,
        "epoch_origin_state_hash": "origin",
        "live_state_hash": "accepted",
        "basis_hash": "basis",
        "comparison_basis_hash": "comparison",
        "persistent_cache_id": "EPOCH_TEST",
        "persistent_cache_dir": str(tmp_path / "cache"),
    }
    controller._save_rotating_checkpoint(adapter, tmp_path / "run", 2)
    latest = json.loads((tmp_path / "run" / "LATEST_ACCEPTED_CHECKPOINT.json").read_text())
    lineage = latest["path_epoch_checkpoint"]
    assert lineage["persistent_cache_id"] == "EPOCH_TEST"
    assert lineage["live_state_hash"] == "accepted"
    assert lineage["epoch"] == 3


def test_legacy_v247_exact_state_is_imported_without_com_enumeration(tmp_path, monkeypatch):
    import r1_15a2_trial_adapter_v240 as adapter_module
    from r1_15a2_trial_adapter_v240 import VisumAdapter

    conf = cfg(tmp_path)
    conf["dseg_path_volume_relative_tolerance"] = 0.01
    legacy_root = tmp_path / "legacy-runs"
    legacy_dir = legacy_root / "RUN_OLD" / "CALIBRATION" / "GENERATION_CACHE"
    legacy_dir.mkdir(parents=True)
    conf["runtime_legacy_path_cache_roots"] = [str(legacy_root)]
    rows = [profile(model=600, obs=1000, ident="obs-a")]
    snap = snapshot()
    policy = SupplyPolicy(min_geh=1, min_residual=1, max_candidates=8)
    legacy = TwoModeRouteCollector(
        rows, policy, snap["state_hash"], links(), legacy_dir / STORE_NAME,
        dict(DEFAULT_SETTINGS), QuietControl(),
        duplicate_scope_policy="DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS")
    legacy.add_parents("NATIVE_CW", "C", [[1, 2, 1, 600], [1, 2, 2, 400]],
                       authority([600, 400]))
    legacy.add_geometry("C", hierarchy())
    legacy.prepare_incidence_evidence()
    legacy.close()

    adapter = VisumAdapter.__new__(VisumAdapter)
    adapter.cfg = conf; adapter.control = QuietControl(); adapter.telemetry = None
    adapter.policy = policy; adapter.visum = object()
    adapter.cache = None; adapter.cache_links = None; adapter.cache_snapshot = None
    adapter.cache_live_snapshot = None; adapter.initial_snapshot = None
    adapter.path_epoch_index = 0; adapter.path_epoch_accepts = 0
    adapter.path_epoch_refresh_counts = {"DEMAND": 0, "SUPPLY": 0}
    adapter.path_epoch_plateau_verified = None; adapter.path_epoch_history = []
    adapter.supply_path_proof = None
    adapter.persistent_path_cache = PersistentPathCacheManager(conf, adapter.control)
    adapter.persistent_cache_manifest = None; adapter.persistent_cache_restore_record = None
    adapter.read_links = lambda: {k: dict(v, object=object()) for k, v in links().items()}
    adapter.snapshot = lambda: snap
    monkeypatch.setattr(adapter_module, "collect_two_modes",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("legacy import must avoid COM enumeration")))
    collector, _, record = adapter._build_cache(
        {"d12": {"rows": rows}}, tmp_path / "new-run", snap,
        allow_persistent_restore=True)
    try:
        assert record["matched_by"] == "LEGACY_EXACT_STATE_IMPORT"
        assert record["legacy_profile_flow_gate"]["passes"] is True
        assert Path(record["cache_dir"]).is_dir()
        assert collector.read_only is True
    finally:
        adapter.close()


def test_read_only_reopen_allows_temp_schema_but_main_database_stays_read_only(tmp_path):
    """Persistent cache main file is immutable; Supply may use local TEMP joins."""
    from r1_15a2_supply_temp_sqlite_hotfix_v24915p2c2 import activate_supply_temp_sqlite_hotfix
    activate_supply_temp_sqlite_hotfix()
    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    cache_dir = Path(manifest["cache_dir"])
    reopened = TwoModeRouteCollector.open_existing(
        rows, policy, links(), cache_dir / STORE_NAME, DEFAULT_SETTINGS,
        QuietControl(),
        duplicate_scope_policy="DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS",
        read_only=True, require_profile_metadata=True)
    try:
        assert reopened.read_only is True
        # URI mode=ro must still protect the persistent main database.
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            reopened.db.execute("DELETE FROM metadata")
        # Supply impact() requires only a connection-local scratch table.
        reopened.db.execute("CREATE TEMP TABLE r1_supply_temp_test(gid INTEGER PRIMARY KEY, delta REAL)")
        reopened.db.execute("INSERT INTO r1_supply_temp_test VALUES(1, 2.5)")
        assert reopened.db.execute(
            "SELECT gid,delta FROM r1_supply_temp_test").fetchone() == (1, 2.5)
        reopened.db.execute("DROP TABLE temp.r1_supply_temp_test")
    finally:
        reopened.close()
