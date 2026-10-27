from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import r1_15a2_demand_continuation_v24914 as continuation
import r1_15a2_overnight_controller_v242 as coupled
from r1_15a2_safety_v24914 import (
    validate_v24914_config,
    validate_v24914_runtime_bundle,
)
from r1_15a2_supply import SupplyContractError
from test_v245_workflow import setup_workflow

ROOT = Path(__file__).resolve().parents[1]


def _skip_if_v24915_supersedes_runtime_manifest():
    if (ROOT / "R1_15A2_CONFIG_V2_4_9_15.json").is_file():
        pytest.skip(
            "V24915 intentionally supersedes shared runtime files and owns its own exact manifest"
        )


def _runtime_descriptor(max_cycle=12):
    return {
        "enabled": True,
        "mode": "EXACT_SEMANTIC_A0009_LINEAGE_CONTINUATION",
        "accepted_count": 9,
        "next_outer_cycle": 6,
        "inherited_outer_cycles": 5,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 0,
        "max_lineage_outer_cycle": max_cycle,
        "bounded_inner_budget_stop_reasons": list(
            continuation.BOUNDED_INNER_BUDGET_STOP_REASONS),
        "continue_bounded_budget_without_accepted_change": True,
    }


def _accept_phase_budget_keyword(monkeypatch):
    original = coupled.run_finecdf_inner

    def wrapped(adapter, cfg, folder, control, package_root, phase_budget=None):
        return original(adapter, cfg, folder, control, package_root)

    monkeypatch.setattr(coupled, "run_finecdf_inner", wrapped)


def _full_verify_cfg(cfg, max_cycle=12):
    cfg["coupled_demand"].update(
        max_outer_cycles=max_cycle,
        min_stationary_cycles=2,
        supply_max_cycles=5,
    )
    cfg["coupled_demand"]["finecdf_td"] = {
        "progressive_schedule": [
            {
                "name": "FULL_VERIFY",
                "through_outer_cycle": max_cycle,
                "max_iterations": 35,
                "max_td_evaluations": 180,
                "allow_progress_continue": False,
            }
        ]
    }
    cfg["runtime_demand_continuation"] = _runtime_descriptor(max_cycle)
    return cfg


def test_static_authority_reproduces_verified_v24912_a0009_lineage():
    authority = continuation.load_authority(ROOT)
    assert authority["accepted_count"] == 9
    assert authority["next_outer_cycle"] == 6
    assert authority["max_lineage_outer_cycle"] == 12
    assert authority["source_terminal_status"] == (
        "DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED:MAX_ITERATIONS"
    )
    assert [row["cycle"] for row in authority["source_cycle_summary"]] == [1, 2, 3, 4, 5]
    assert authority["source_cycle_summary"][-1]["generation_changed"] is True
    assert authority["source_cycle_summary"][-1]["td_changed"] is True


def test_resolve_continuation_requires_exact_live_semantic_state(tmp_path):
    authority = continuation.load_authority(ROOT)
    source = tmp_path / authority["source_checkpoint_name"]
    source.write_bytes(b"semantic-authority-fixture")
    live = {
        "semantic_state_hash": authority["semantic_state_hash"],
        "semantic_hashes": dict(authority["semantic_hashes"]),
    }
    resolved = continuation.resolve_continuation(source, live, ROOT)
    assert resolved["enabled"] is True
    assert resolved["accepted_count"] == 9
    assert resolved["next_outer_cycle"] == 6
    assert resolved["raw_ver_sha_used_for_restart_acceptance"] is False

    wrong = json.loads(json.dumps(live))
    wrong["semantic_hashes"]["td_hash"] = "0" * 64
    with pytest.raises(SupplyContractError, match="LIVE_SEMANTIC_FIELDS_MISMATCH"):
        continuation.resolve_continuation(source, wrong, ROOT)


def test_bounded_budget_reason_whitelist_excludes_global_and_technical_stops():
    for reason in continuation.BOUNDED_INNER_BUDGET_STOP_REASONS:
        assert coupled._bounded_inner_budget_stop({"stop_reason": reason}) is True
    for reason in (
        "GLOBAL_USERSTOPREQUESTED",
        "GLOBAL_TIMEBUDGETREACHED",
        "TD_USER_STOP_FILE",
        "COM_ERROR",
        "ROLLBACK_FAILED",
        "LOCAL_PLATEAU_NOT_PROOF_OF_GLOBAL_OPTIMUM",
    ):
        assert coupled._bounded_inner_budget_stop({"stop_reason": reason}) is False


def test_continuation_starts_at_cycle6_with_accepted_count9_and_continues_budget(tmp_path, monkeypatch):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    _accept_phase_budget_keyword(monkeypatch)
    _full_verify_cfg(cfg, max_cycle=7)
    adapter.td_reason = "MAX_ITERATIONS"

    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "continuation", control, ROOT
    )

    assert [row["cycle"] for row in result["demand_cycles"]] == [6, 7]
    assert result["lineage_outer_cycle_start"] == 6
    assert result["inherited_outer_cycles"] == 5
    assert result["accepted_count"] == 11
    assert result["demand_cycles"][0]["status"] == (
        "PROGRESS_CONTINUE_DEMAND_ACCEPTED_BUDGET"
    )
    assert result["demand_cycles"][1]["status"] == (
        "BOUNDED_SEARCH_CONTINUE_DEMAND_NO_ACCEPTED_CHANGE"
    )
    assert result["stationary_cycle_streak"] == 0
    assert result["status"] == "DEMAND_MAX_OUTER_CYCLES_REACHED_SUPPLY_LOCKED"
    assert result["continuation_required"] is True
    assert result["next_outer_cycle"] == 8
    assert result["supply_started"] is False
    assert result["final_state_verified"] is True
    assert [row["cycle"] for row in result["bounded_budget_continuations"]] == [6, 7]


def test_continuation_requires_two_complete_unchanged_cycles_before_supply(tmp_path, monkeypatch):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    _accept_phase_budget_keyword(monkeypatch)
    _full_verify_cfg(cfg, max_cycle=7)
    adapter.no_generation = True
    adapter.td_change = False
    adapter.no_supply = True

    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "stationary", control, ROOT
    )

    assert [row["cycle"] for row in result["demand_cycles"]] == [6, 7]
    assert all(row["completed"] for row in result["demand_cycles"])
    assert all(row["joint_stationary"] for row in result["demand_cycles"])
    assert result["demand_converged"] is True
    assert result["demand_converged_cycle"] == 7
    assert result["stationary_cycle_streak"] == 2
    assert result["accepted_count"] == 9
    assert result["supply_started"] is True
    assert result["calibration_complete"] is True
    authority = json.loads(
        (tmp_path / "stationary" / "DEMAND_CONVERGED.json").read_text(encoding="utf-8")
    )
    assert authority["cycle"] == 7
    assert authority["stationary_cycle_streak"] == 2


def test_global_time_budget_remains_terminal_and_never_unlocks_supply(tmp_path, monkeypatch):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    _accept_phase_budget_keyword(monkeypatch)
    _full_verify_cfg(cfg, max_cycle=8)
    adapter.td_reason = "GLOBAL_TIMEBUDGETREACHED"

    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "global-stop", control, ROOT
    )

    assert len(result["demand_cycles"]) == 1
    assert result["demand_cycles"][0]["cycle"] == 6
    assert result["status"] == (
        "DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED:GLOBAL_TIMEBUDGETREACHED"
    )
    assert result["supply_started"] is False
    assert result["demand_converged"] is False
    assert result["final_state_verified"] is True


def test_without_runtime_continuation_inherited_budget_behavior_is_unchanged(tmp_path, monkeypatch):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["coupled_demand"].update(max_outer_cycles=3, min_stationary_cycles=2)
    adapter.td_reason = "MAX_ITERATIONS"

    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "legacy", control, ROOT
    )

    assert result["demand_cycles"][0]["cycle"] == 1
    assert result["status"] == "DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED:MAX_ITERATIONS"
    assert result["supply_started"] is False


def _launcher_module():
    path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_14.py"
    spec = importlib.util.spec_from_file_location("v24914_user_entrypoint", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_v24914_config_runtime_bundle_and_v24913_supply_policy_are_hash_locked():
    _skip_if_v24915_supersedes_runtime_manifest()
    module = _launcher_module()
    cfg = module.load_config()
    config_result = validate_v24914_config(cfg, ROOT)
    runtime_result = validate_v24914_runtime_bundle(cfg, ROOT)
    assert cfg["release"] == module.RELEASE
    assert config_result["next_outer_cycle"] == 6
    assert config_result["accepted_count_start"] == 9
    assert config_result["v24913_supply_policy_preserved"] is True
    assert runtime_result["passes"] is True
    assert runtime_result["continuation_start_outer_cycle"] == 6
    assert runtime_result["supply_policy_preserved"] is True
