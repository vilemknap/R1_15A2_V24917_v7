# -*- coding: utf-8 -*-
"""Release-level hard gates for V24915 PERF1 exact-safe acceleration."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import r1_15a2_overnight_controller_coupled_v24915p1 as coupled
from r1_15a2_safety_v24915p1 import (
    PARENT_RELEASE,
    RELEASE,
    validate_v24915p1_config,
    validate_v24915p1_runtime_bundle,
)
from r1_15a2_supply import canonical_hash
from test_v2490_td_soft_reference import (
    Control,
    SoftAdapter,
    _parent,
    _restore,
    _soft_cfg,
)

ROOT = Path(__file__).resolve().parents[1]


def _entrypoint():
    path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF1.py"
    spec = importlib.util.spec_from_file_location("v24915_perf1_user_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v24915_perf1_config_runtime_bundle_and_parent_are_hash_locked():
    cfg = _entrypoint().load_config()
    config_result = validate_v24915p1_config(cfg, ROOT)
    runtime_result = validate_v24915p1_runtime_bundle(cfg, ROOT)
    assert cfg["release"] == RELEASE
    assert config_result["parent_release"] == PARENT_RELEASE
    assert config_result["calibration_math_changed"] is False
    assert config_result["assignment_method_changed"] is False
    assert config_result["acceptance_changed"] is False
    assert config_result["phase_specific_procseq"] is True
    assert config_result["rollback_diagnostic_reuse_with_full_fallback"] is True
    assert config_result["duplicate_effective_candidate_elimination"] is True
    assert runtime_result["parent_deployment_intact"] is True
    assert runtime_result["files_checked"] >= 72
    assert runtime_result["real_visum_tested"] is False
    assert runtime_result["production_ready"] is False


def test_v24915_perf1_keeps_a0009_continuation_and_calibration_contract():
    cfg = _entrypoint().load_config()
    continuation = cfg["demand_continuation"]
    assert continuation["accepted_count"] == 9
    assert continuation["next_outer_cycle"] == 6
    assert continuation["mode"] == "EXACT_SEMANTIC_A0009_LINEAGE_CONTINUATION"
    feature = cfg["trial_calibration"]["v24915_perf1_exact_safe_acceleration"]
    assert feature == {
        "phase_specific_procseq": True,
        "rollback_diagnostic_reuse_with_full_fallback": True,
        "duplicate_effective_candidate_elimination": True,
        "candidate_parallelism": False,
        "assignment_method_changed": False,
        "acceptance_changed": False,
    }


def test_duplicate_effective_finecdf_candidates_are_not_recomputed(tmp_path, monkeypatch):
    adapter = SoftAdapter(always_reject=True)
    before = _parent(adapter)
    baseline = adapter.diagnostics(tmp_path / "base", "BASE")
    monkeypatch.setattr(coupled, "restore_td_parameters", _restore)
    monkeypatch.setattr(coupled, "diagnostic_hash", lambda d: canonical_hash(d))

    # Target equals the accepted parent.  Every configured scale therefore
    # produces the exact same parameter write signature.  PERF1 must evaluate
    # it once, preserve configured order, skip only exact duplicates, and then
    # execute the original verified-parent plateau rollback.
    rows, after, diag, gap, evidence = coupled._realize_finecdf_td(
        adapter,
        _soft_cfg((1.0, 0.5, 0.25)),
        tmp_path / "realization",
        Control(),
        before,
        baseline,
        [{"component": "WORK_E_C", "candidate_b": 0.0, "candidate_c": -0.1}],
    )
    assert rows == []
    assert gap is None
    assert after["state_hash"] == before["state_hash"]
    assert evidence["status"] == "SOFT_REFERENCE_PLATEAU"
    assert [row["status"] for row in evidence["attempts"]] == [
        "REJECTED_SOFT_REFERENCE_GUARD",
        "DUPLICATE_EFFECTIVE_CANDIDATE_SKIPPED",
        "DUPLICATE_EFFECTIVE_CANDIDATE_SKIPPED",
    ]
    # One unique trial plus the mandatory final rollback recomputation.
    assert len(adapter.assign_calls) == 2
