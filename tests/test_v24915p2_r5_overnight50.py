# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

import r1_15a2_core as core
import r1_15a2_demand_continuation_v24915r4 as r4
import r1_15a2_demand_continuation_v24915r5 as r5
import r1_15a2_overnight_controller_coupled_v24915p2 as coupled
from r1_15a2_overnight_controller_v24915p2 import OvernightControl

ROOT = Path(__file__).resolve().parents[1]


def _entrypoint():
    path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py"
    spec = importlib.util.spec_from_file_location("v24915_perf2_r5_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_r5_config_extends_only_outer_and_global_runtime_budgets():
    cfg = _entrypoint().load_config()
    assert cfg["package_revision"] == "V24915_PERF2_R5_OVERNIGHT50_B0016_CONTINUATION"
    assert cfg["calibration_phases"][0]["max_cycles"] == 50
    assert cfg["coupled_demand"]["max_outer_cycles"] == 50
    assert cfg["coupled_demand"]["finecdf_td"]["progressive_schedule"][-1]["through_outer_cycle"] == 50
    assert cfg["performance"]["generation_step_schedule"][-1]["through_outer_cycle"] == 50
    assert cfg["trial_calibration"]["max_runtime_seconds"] == pytest.approx(64800.0)
    # Method/acceptance hard invariants stay unchanged.
    assert cfg["early_exploration_acceptance"]["through_outer_cycle"] == 12
    assert cfg["coupled_demand"]["min_stationary_cycles"] == 2
    assert cfg["coupled_demand"]["supply_max_cycles"] == 100
    assert cfg["coupled_demand"]["finecdf_td"]["max_runtime_seconds"] == pytest.approx(14400.0)


def test_cycle_50_is_covered_by_mature_generation_and_finecdf_stages():
    cfg = _entrypoint().load_config()
    gen = coupled._generation_step_for_cycle(cfg, 50)
    td = coupled._finecdf_budget_for_cycle(cfg, 50)
    assert gen["name"] == "DISTRIBUTION_FOCUS"
    assert gen["through_outer_cycle"] == 50
    assert td["name"] == "FULL_VERIFY"
    assert td["through_outer_cycle"] == 50
    # Cycle 51 remains fail-closed rather than silently extrapolated.
    with pytest.raises(Exception, match="SCHEDULE_DOES_NOT_COVER_OUTER_CYCLE"):
        coupled._generation_step_for_cycle(cfg, 51)
    with pytest.raises(Exception, match="SCHEDULE_DOES_NOT_COVER_OUTER_CYCLE"):
        coupled._finecdf_budget_for_cycle(cfg, 51)


def test_acceptance_is_not_relaxed_after_original_cycle_12_horizon():
    cfg = _entrypoint().load_config()
    c12 = copy.deepcopy(cfg)
    c12["runtime_acceptance_outer_cycle"] = 12
    assert core.early_exploration_policy(c12, "GENERATION") is not None
    c13 = copy.deepcopy(cfg)
    c13["runtime_acceptance_outer_cycle"] = 13
    assert core.early_exploration_policy(c13, "GENERATION") is None


def test_b0016_runtime_continuation_is_extended_without_rewriting_r4_authority(tmp_path):
    authority = r4.load_authority(ROOT)
    assert authority["max_lineage_outer_cycle"] == 12
    source = tmp_path / r4.EXPECTED_CHECKPOINT_NAME
    source.write_bytes(b"fixture")
    live = {
        "semantic_state_hash": authority["semantic_state_hash"],
        "semantic_hashes": copy.deepcopy(authority["semantic_hashes"]),
    }
    resolved = r5.resolve_b0016(source, live, ROOT)
    assert resolved["source_max_lineage_outer_cycle"] == 12
    assert resolved["max_lineage_outer_cycle"] == 50
    assert resolved["next_outer_cycle"] == 11
    assert resolved["resume_substep"] == "TD_FINECDF_V17"
    assert resolved["accepted_count"] == 16
    assert resolved["overnight_budget_extension"]["acceptance_thresholds_changed"] is False


def test_global_control_budget_is_18_hours(tmp_path):
    cfg = _entrypoint().load_config()
    control = OvernightControl(tmp_path, cfg)
    assert control.max_seconds == pytest.approx(64800.0)
