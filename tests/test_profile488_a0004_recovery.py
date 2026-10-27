from pathlib import Path
import copy
import json

import r1_15a2_demand_continuation_profile488_a0004 as recovery
import r1_15a2_overnight_controller_coupled_v24915p2_force100 as coupled

ROOT = Path(__file__).resolve().parents[1]


def test_recovery_authority_hash_locked_and_valid():
    auth = recovery.load_authority(ROOT)
    assert auth["accepted_count"] == 4
    assert auth["next_outer_cycle"] == 3
    assert auth["resume_substep"] == "TD_FINECDF_V17"
    assert auth["resume_generation_completed"] is True
    assert auth["resume_td_completed"] is False
    assert auth["source_restart_evidence"]["rollback_verified"] is True


def test_recovery_resolved_descriptor_passes_parent_partial_cycle_contract(tmp_path):
    auth = recovery.load_authority(ROOT)
    cp = tmp_path / recovery.EXPECTED_CHECKPOINT_NAME
    cp.write_bytes(b"placeholder; semantic acceptance is not raw VER SHA")
    live = {
        "semantic_state_hash": auth["semantic_state_hash"],
        "semantic_hashes": copy.deepcopy(auth["semantic_hashes"]),
    }
    resolved = recovery.resolve_continuation(cp, live, ROOT)
    cfg = {"runtime_demand_continuation": resolved}
    checked = coupled._runtime_demand_continuation(cfg)
    assert checked["accepted_count"] == 4
    assert checked["next_outer_cycle"] == 3
    assert checked["resume_outer_cycle"] == 3
    assert checked["resume_generation_record"]["status"] == "ACCEPTED"
    assert checked["generation_reference"]["observation_hash"] == "0f0bb12af3f7e05db7f41e27c961e9462c963a86a00b7d29999e328db6aefc81"


def test_partial_cycle3_resume_skips_generation_and_starts_td(tmp_path, monkeypatch):
    from test_v245_workflow import setup_workflow, PLATEAU
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as force100

    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["coupled_demand"].update(max_outer_cycles=4, min_stationary_cycles=2, supply_max_cycles=5)
    reference = force100.build_reference(
        adapter.diagnostics(tmp_path / "reference", "REFERENCE"),
        force100._generation_counts_cfg(cfg),
    )
    cfg["runtime_demand_continuation"] = {
        "enabled": True,
        "mode": "EXACT_SEMANTIC_PROFILE488_A0004_PARTIAL_CYCLE3_TD_RESUME",
        "accepted_count": 4,
        "next_outer_cycle": 3,
        "inherited_outer_cycles": 2,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 0,
        "max_lineage_outer_cycle": 4,
        "bounded_inner_budget_stop_reasons": [
            "MAX_ITERATIONS", "TD_EVALUATION_BUDGET", "TD_INNER_TIME_BUDGET"
        ],
        "resume_substep": "TD_FINECDF_V17",
        "resume_outer_cycle": 3,
        "resume_generation_completed": True,
        "resume_generation_changed": True,
        "resume_td_completed": False,
        "resume_generation_record": {
            "status": "ACCEPTED",
            "search_complete": True,
            "stationarity_confirmed": False,
        },
        "generation_reference": reference,
        "generation_reference_sha256": "fixture-sealed-reference",
        "semantic_state_hash": "fixture-a0004-state",
    }
    gen_calls = []
    td_calls = []

    def fake_generation(adapter0, cfg0, folder, control0, state, diag, anchors,
                        gen_reference, policy, outer_cycle=None):
        gen_calls.append(outer_cycle)
        return False, state, diag, {}, {
            "status": "NO_CHANGE",
            "search_complete": True,
            "stationarity_confirmed": True,
        }

    def fake_td(adapter0, cfg0, folder, control0, state, diag, package_root,
                outer_cycle=None):
        td_calls.append(outer_cycle)
        return False, state, diag, {
            "status": "NO_CHANGE",
            "td_realization_complete": True,
            "inner": {
                "stop_reason": PLATEAU,
                "search_complete": True,
                "stationarity_confirmed": True,
                "progress_continue": False,
            },
        }

    monkeypatch.setattr(force100, "_generation_update_once", fake_generation)
    monkeypatch.setattr(force100, "_finecdf_td_once", fake_td)
    result = force100.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "resume", control, ROOT)

    assert [x["cycle"] for x in result["demand_cycles"]] == [3, 4]
    assert gen_calls == [4]
    assert td_calls == [3, 4]
    first = result["demand_cycles"][0]
    assert first["resume_boundary"] == "POST_ACCEPTED_GENERATION_PRE_TD"
    assert first["generation"]["generation_replay_skipped"] is True
    assert result["partial_cycle_resume"]["generation_replayed"] is False
    assert result["accepted_count"] == 4
    assert result["generation_reference_source"] == "CONTINUATION_SEALED_REFERENCE"
