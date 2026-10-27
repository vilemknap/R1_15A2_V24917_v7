import importlib.util
from pathlib import Path

import pytest

import r1_15a2_demand_extension_b0018_v24915p2c3 as ext
from r1_15a2_safety_v24915p2c3 import (
    preflight_v24915p2c3_overlay, validate_v24915p2c3_config_delta,
)
import R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2C as perf2c

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "R1_15A2_DEMAND_EXTENSION_B0018_CYCLES16_25_V2_4_9_15_PERF2C_R3.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("perf2c_r3_extension_launcher_test", LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_r3_overlay_preflight_passes_and_is_b0018_only():
    report = preflight_v24915p2c3_overlay(ROOT)
    assert report["passes"] is True
    assert report["source_checkpoint"] == "ACCEPTED_B_0018_3d57d34487ba.ver"
    assert report["outer_cycles"] == [16, 25]
    assert report["outer_cycle_count"] == 10
    assert report["supply_locked_during_extension"] is True


def test_b0018_authority_is_self_consistent_and_resolves_16_to_25(tmp_path):
    auth = ext.load_authority(ROOT)
    source = tmp_path / ext.EXPECTED_CHECKPOINT_NAME
    source.write_bytes(b"fixture")
    live = {
        "semantic_state_hash": auth["semantic_state_hash"],
        "semantic_hashes": dict(auth["semantic_hashes"]),
    }
    assert ext.matches_b0016_live_semantic(live, ROOT) is True
    resolved = ext.resolve_b0016(source, live, ROOT)
    assert resolved["accepted_count"] == 18
    assert resolved["inherited_outer_cycles"] == 15
    assert resolved["next_outer_cycle"] == 16
    assert resolved["max_lineage_outer_cycle"] == 25
    assert resolved["inherited_stationary_cycle_streak"] == 0
    assert resolved["resume_substep"] == "GENERATION"
    assert resolved["b0018_demand_extension"]["outer_cycle_count"] == 10
    assert resolved["b0018_demand_extension"]["supply_locked"] is True


def test_wrong_semantic_is_not_accepted_and_never_falls_back(tmp_path):
    auth = ext.load_authority(ROOT)
    bad = {
        "semantic_state_hash": "0" * 64,
        "semantic_hashes": dict(auth["semantic_hashes"]),
    }
    assert ext.matches_b0016_live_semantic(bad, ROOT) is False
    with pytest.raises(Exception, match="REQUIRES_EXACT_B0018"):
        ext.resolve_a0009(tmp_path / "whatever.ver", bad, ROOT)


def test_extension_config_is_exact_reviewed_delta_and_supply_cannot_unlock():
    launcher = _load_launcher()
    base = perf2c._load_config_with_overlay("FULL")
    child = launcher._load_config_extension("FULL")
    assert validate_v24915p2c3_config_delta(child, base, ROOT)["passes"] is True
    assert child["coupled_demand"]["max_outer_cycles"] == 25
    assert child["coupled_demand"]["min_stationary_cycles"] == 11
    assert child["backtracking_scales"] == [1.0, 0.5, 0.25, 0.125, 0.0625]
    assert child["trial_calibration"]["max_trials_per_block"]["GENERATION"] == 5
    assert 25 - 16 + 1 == 10
    assert 10 < child["coupled_demand"]["min_stationary_cycles"]
    assert child["early_exploration_acceptance"]["through_outer_cycle"] == 12
    assert child["coupled_demand"]["finecdf_td"]["realization_backtracking_scales"] == \
        base["coupled_demand"]["finecdf_td"]["realization_backtracking_scales"]


def test_controller_wrapper_relabels_only_exact_completed_16_25_extension():
    launcher = _load_launcher()
    def original(*args, **kwargs):
        return {
            "status": "DEMAND_MAX_OUTER_CYCLES_REACHED_SUPPLY_LOCKED",
            "supply_started": False,
            "demand_cycles": [{"cycle": i} for i in range(16, 26)],
        }
    wrapped = launcher._wrap_controller(original)
    out = wrapped(None, None, None, None, None)
    assert out["status"] == "DEMAND_EXTENSION_16_25_COMPLETED_SUPPLY_LOCKED"
    assert out["demand_extension_complete"] is True
    assert out["demand_extension_outer_cycles"] == list(range(16, 26))
    assert out["supply_started"] is False
    assert out["next_outer_cycle"] == 26


def test_controller_wrapper_fails_closed_if_supply_starts():
    launcher = _load_launcher()
    def original(*args, **kwargs):
        return {"status": "X", "supply_started": True, "demand_cycles": []}
    with pytest.raises(RuntimeError, match="SUPPLY_STARTED_DURING_DEMAND_EXTENSION"):
        launcher._wrap_controller(original)(None, None, None, None, None)
