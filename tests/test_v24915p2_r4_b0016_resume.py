# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

import r1_15a2_demand_continuation_v24915r4 as r4
import r1_15a2_overnight_controller_coupled_v24915p2 as coupled
from r1_15a2_supply import SupplyContractError
from test_v245_workflow import setup_workflow, PLATEAU

ROOT = Path(__file__).resolve().parents[1]


def _entrypoint():
    path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py"
    spec = importlib.util.spec_from_file_location("v24915_perf2_r4_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_b0016_authority_is_exact_partial_cycle11_td_resume(tmp_path):
    authority = r4.load_authority(ROOT)
    assert authority["accepted_count"] == 16
    assert authority["inherited_outer_cycles"] == 10
    assert authority["next_outer_cycle"] == 11
    assert authority["max_lineage_outer_cycle"] == 12
    assert authority["resume_substep"] == "TD_FINECDF_V17"
    assert authority["resume_generation_completed"] is True
    assert authority["resume_generation_changed"] is True
    assert authority["resume_td_completed"] is False
    assert authority["source_restart_evidence"]["safe_restart_from_latest_accepted_checkpoint"] is True
    assert authority["generation_reference"]["cal_scale"] == pytest.approx(53.37788753559903)

    source = tmp_path / r4.EXPECTED_CHECKPOINT_NAME
    source.write_bytes(b"fixture")
    live = {
        "semantic_state_hash": authority["semantic_state_hash"],
        "semantic_hashes": copy.deepcopy(authority["semantic_hashes"]),
    }
    resolved = r4.resolve_continuation(source, live, ROOT)
    assert resolved["mode"] == "EXACT_SEMANTIC_B0016_PARTIAL_CYCLE11_TD_RESUME"
    assert resolved["accepted_count"] == 16
    assert resolved["resume_outer_cycle"] == 11
    assert resolved["resume_substep"] == "TD_FINECDF_V17"
    assert resolved["generation_reference_sha256"] == r4.EXPECTED_GENERATION_REFERENCE_SHA256

    bad = copy.deepcopy(live)
    bad["semantic_hashes"]["generation_hash"] = "0" * 64
    with pytest.raises(SupplyContractError, match="LIVE_SEMANTIC_FIELDS_MISMATCH"):
        r4.resolve_continuation(source, bad, ROOT)


def test_r4_runtime_descriptor_rejects_partial_resume_without_sealed_reference():
    raw = {
        "enabled": True,
        "accepted_count": 16,
        "next_outer_cycle": 11,
        "inherited_outer_cycles": 10,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 5,
        "max_lineage_outer_cycle": 12,
        "resume_substep": "TD_FINECDF_V17",
        "resume_outer_cycle": 11,
        "resume_generation_completed": True,
        "resume_generation_changed": True,
        "resume_td_completed": False,
        "resume_generation_record": {"search_complete": True},
    }
    with pytest.raises(SupplyContractError, match="GENERATION_REFERENCE_MISSING"):
        coupled._runtime_demand_continuation({"runtime_demand_continuation": raw})


def test_partial_cycle11_resume_skips_generation_once_and_preserves_accepted_count(tmp_path, monkeypatch):
    cfg, control, adapter = setup_workflow(tmp_path, monkeypatch)
    cfg["coupled_demand"].update(max_outer_cycles=12, min_stationary_cycles=2, supply_max_cycles=5)
    # Build a valid reference from the fixture, then freeze it into the continuation.
    reference = coupled.build_reference(
        adapter.diagnostics(tmp_path / "reference", "REFERENCE"),
        coupled._generation_counts_cfg(cfg),
    )
    cfg["runtime_demand_continuation"] = {
        "enabled": True,
        "mode": "EXACT_SEMANTIC_B0016_PARTIAL_CYCLE11_TD_RESUME",
        "accepted_count": 16,
        "next_outer_cycle": 11,
        "inherited_outer_cycles": 10,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 5,
        "max_lineage_outer_cycle": 12,
        "bounded_inner_budget_stop_reasons": [
            "MAX_ITERATIONS", "TD_EVALUATION_BUDGET", "TD_INNER_TIME_BUDGET"
        ],
        "resume_substep": "TD_FINECDF_V17",
        "resume_outer_cycle": 11,
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
        "semantic_state_hash": "b0016-fixture-state",
    }
    gen_calls = []
    td_calls = []

    def fake_generation(adapter0, cfg0, folder, control0, state, diag, anchors, gen_reference, policy, outer_cycle=None):
        gen_calls.append(outer_cycle)
        return False, state, diag, {}, {
            "status": "NO_CHANGE",
            "search_complete": True,
            "stationarity_confirmed": True,
        }

    def fake_td(adapter0, cfg0, folder, control0, state, diag, package_root, outer_cycle=None):
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

    monkeypatch.setattr(coupled, "_generation_update_once", fake_generation)
    monkeypatch.setattr(coupled, "_finecdf_td_once", fake_td)
    result = coupled.run_overnight_calibration_coupled(
        adapter, cfg, tmp_path / "r4-resume", control, ROOT
    )

    assert [row["cycle"] for row in result["demand_cycles"]] == [11, 12]
    assert gen_calls == [12]
    assert td_calls == [11, 12]
    first = result["demand_cycles"][0]
    assert first["generation_completed"] is True
    assert first["generation_changed"] is True
    assert first["generation"]["generation_replay_skipped"] is True
    assert first["resume_boundary"] == "POST_ACCEPTED_GENERATION_PRE_TD"
    assert result["partial_cycle_resume"]["generation_replayed"] is False
    assert result["accepted_count"] == 16
    assert result["generation_reference_source"] == "CONTINUATION_SEALED_REFERENCE"
    persisted = json.loads((tmp_path / "r4-resume" / "GENERATION_COUNTS_REFERENCE.json").read_text())
    assert persisted == reference
    assert result["supply_started"] is False


def test_sealed_idp_authority_overrides_stale_external_environment(monkeypatch):
    module = _entrypoint()
    monkeypatch.setenv("R1_IDP_AUTHORITY_DIR", str(ROOT / "stale_external_authority"))
    report = module._activate_sealed_idp_authority()
    assert report["status"] == "SEALED_IDP_AUTHORITY_ACTIVE"
    assert report["target_curve_sha256"] == module.SEALED_IDP_DIST_CURVES_SHA256
    assert report["previous_env_authority_dir"].endswith("stale_external_authority")
    assert os.environ["R1_IDP_AUTHORITY_DIR"] == str(module.SEALED_IDP_AUTHORITY_DIR)
    assert report["rows_per_component"]["SERV_noE_C"] == 512
    assert report["rows_per_component"]["SERV_noE_noC"] == 512
