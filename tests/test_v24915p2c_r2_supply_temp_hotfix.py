# -*- coding: utf-8 -*-
"""Focused regression gates for PERF2C R2 Supply TEMP-schema hotfix."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C as full_launcher
import r1_15a2_safety_v24915p2c as safety

ROOT = Path(__file__).resolve().parents[1]
SUPPLY_LAUNCHER = ROOT / "R1_15A2_SUPPLY_ONLY_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C_R2.py"


def _load_supply_launcher():
    spec = importlib.util.spec_from_file_location("perf2c_r2_supply_launcher_test", SUPPLY_LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_r2_release_identifies_supply_temp_hotfix():
    assert "PERF2C_R2" in safety.RELEASE
    assert safety.PACKAGE_REVISION == "V24915_PERF2C_R2_SUPPLY_TEMP_SQLITE_HOTFIX"


def test_supply_only_launcher_delegates_only_to_verified_supply_mode(monkeypatch):
    module = _load_supply_launcher()
    seen = []

    def fake_main(mode="FULL"):
        seen.append(mode)
        return {"status": "SYNTHETIC"}

    monkeypatch.setattr(module.perf2c, "main", fake_main)
    result = module.main()
    assert result == {"status": "SYNTHETIC"}
    assert seen == ["SUPPLY_ONLY"]


def test_full_launcher_still_uses_full_mode_entrypoint_contract():
    # R2 adds a separate Supply-only entrypoint; the existing full launcher is
    # not repurposed and therefore cannot silently skip Demand.
    assert callable(full_launcher.main)
    assert full_launcher.RELEASE == safety.RELEASE


def test_reopened_read_only_cache_executes_real_supply_impact_with_temp_join(tmp_path):
    from pathlib import Path
    from r1_15a2_supply_temp_sqlite_hotfix_v24915p2c2 import activate_supply_temp_sqlite_hotfix
    from r1_15a2_two_mode_v238 import TwoModeRouteCollector, DEFAULT_SETTINGS, QuietControl
    from r1_15a2_persistent_path_cache_v248 import STORE_NAME
    from test_v248_persistent_path_cache import publish, links
    from test_supply_v22 import P

    activate_supply_temp_sqlite_hotfix()
    conf, manager, rows, snap, policy, manifest, publication = publish(tmp_path)
    cache_dir = Path(manifest["cache_dir"])
    reopened = TwoModeRouteCollector.open_existing(
        rows, policy, links(), cache_dir / STORE_NAME, DEFAULT_SETTINGS,
        QuietControl(),
        duplicate_scope_policy="DIAGNOSTIC_EXCLUDE_CONFLICTED_DRIVERS",
        read_only=True, require_profile_metadata=True)
    try:
        reopened.prepare_sequence_evidence()
        impact = reopened.impact([{"key": list(P), "delta": 1.0}], 0, 600.0)
        assert impact["affected_routes"] > 0
        assert impact["counterfactual_flow_prediction"] is False
        assert reopened.summary["persistent_cache_main_database_mode"] == "URI_MODE_RO"
        assert reopened.summary["persistent_cache_main_database_writable"] is False
    finally:
        reopened.close()


def test_supply_only_handoff_discovers_demand_convergence_above_checkpoint(tmp_path):
    import json
    from r1_15a2_supply_handoff_v24915p2 import (
        CRITERION, discover_demand_convergence_authority,
    )

    run = tmp_path / "RUN_TEST"
    calibration = run / "CALIBRATION"
    checkpoint_dir = calibration / "CHECKPOINTS"
    checkpoint_dir.mkdir(parents=True)
    checkpoint = checkpoint_dir / "ACCEPTED_B_0018_deadbeef.ver"
    checkpoint.write_bytes(b"synthetic")
    authority = {
        "cycle": 15,
        "state_hash": "7" * 64,
        "diagnostic_hash": "a" * 64,
        "stationary_cycle_streak": 2,
        "criterion": CRITERION,
        "global_optimum_proven": False,
        "calibration_quality_proven": False,
    }
    (calibration / "DEMAND_CONVERGED.json").write_text(
        json.dumps(authority), encoding="utf-8")
    found = discover_demand_convergence_authority(checkpoint)
    assert found["authority"] == authority
    assert found["path"] == str(calibration / "DEMAND_CONVERGED.json")
