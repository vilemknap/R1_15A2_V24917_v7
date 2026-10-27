# -*- coding: utf-8 -*-
"""FASTCAL1 runtime policy overlay for V24916 DYNAMICSKIM1.

This child overlay deliberately changes *search aggressiveness / materiality*
only.  The scientific model, coefficient hard envelopes, Procedure Sequence,
assignment method, VDFs, P/A authority, dynamic skim method, 12D/11D
measurement, and protected-profile/severity guards remain unchanged.

Requested policy (2026-10-22):
- TG family common log cap: 10% / 6% / 3%
- TG zonal OD cap: 20% / 14% / 8% (monotone interpolation of requested 8-20%)
- TG tested backtracking scales: 6
- post-exploration CAL GEH materiality: 0.001% (=1e-5)
- normal TD selected-objective materiality: 0.05% (=5e-4)
- TD realization backtracking attempts: 7

The parent DYNAMICSKIM1 / fresh0 isolated policy remains physically unchanged
on disk; this module applies an auditable runtime delta after the parent gates.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

import r1_15a2_active_targeting_runtime_v24916_fresh0isolated as base
from r1_15a2_safety_v24916p2c import build_safety_contract

RELEASE = "R1_15A2_V24916_PERF2C_FRESH0_DYNAMICSKIM1_FASTCAL1_20261022"
PACKAGE_REVISION = "V24916_DYNAMICSKIM1_FASTCAL1_20261022"
FASTCAL_SCHEMA = "R1_15A2_V24916_FASTCAL1_RUNTIME_POLICY_V1"

# Re-export operational identity from the already-audited fresh0 isolated parent.
AUTHORITY_FILE = base.AUTHORITY_FILE
ISOLATION_SCHEMA = base.ISOLATION_SCHEMA
SOURCE_SEMANTIC_POLICY = base.SOURCE_SEMANTIC_POLICY
EXPECTED_BASELINE_SEMANTIC_STATE_HASH = base.EXPECTED_BASELINE_SEMANTIC_STATE_HASH
RUNS_ROOT_NAME = base.RUNS_ROOT_NAME
LOCK_NAME = base.LOCK_NAME
WORKSPACE_NAME = base.WORKSPACE_NAME
PRIVATE_CACHE_DIRNAME = base.PRIVATE_CACHE_DIRNAME

TG_BACKTRACKING_SCALES = [1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125]
TD_REALIZATION_BACKTRACKING_SCALES = [
    1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125, 0.015625,
]
TG_STAGE_POLICY = [
    {
        "name": "SIGNED_EXPLORE",
        "signed_max_family_global_log": 0.10,
        "max_add_log": 0.10,
        "salary_max_abs_delta_per_block": 0.10,
        "max_od_relative": 0.20,
    },
    {
        "name": "SIGNED_REFINE",
        "signed_max_family_global_log": 0.06,
        "max_add_log": 0.06,
        "salary_max_abs_delta_per_block": 0.06,
        "max_od_relative": 0.14,
    },
    {
        "name": "DISTRIBUTION_FOCUS",
        "signed_max_family_global_log": 0.03,
        "max_add_log": 0.03,
        "salary_max_abs_delta_per_block": 0.03,
        "max_od_relative": 0.08,
    },
]
POST_EXPLORATION_CAL_MIN_RELATIVE_IMPROVEMENT = 1.0e-5  # 0.001 %
TD_SELECTED_MIN_RELATIVE_IMPROVEMENT = 5.0e-4            # 0.05 %


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _policy_payload() -> dict[str, Any]:
    return {
        "schema": FASTCAL_SCHEMA,
        "enabled": True,
        "purpose": "FASTER_CALIBRATION_AGGRESSIVE_TG_TOLERANT_TD",
        "tg_common_log_caps": [0.10, 0.06, 0.03],
        "tg_zone_od_caps": [0.20, 0.14, 0.08],
        "tg_add_log_caps": [0.10, 0.06, 0.03],
        "tg_backtracking_scales": list(TG_BACKTRACKING_SCALES),
        "tg_max_trials": 6,
        "post_exploration_cal_min_relative_improvement": POST_EXPLORATION_CAL_MIN_RELATIVE_IMPROVEMENT,
        "post_exploration_cal_min_percent": 0.001,
        "td_selected_min_relative_improvement": TD_SELECTED_MIN_RELATIVE_IMPROVEMENT,
        "td_selected_min_percent": 0.05,
        "td_realization_backtracking_scales": list(TD_REALIZATION_BACKTRACKING_SCALES),
        "td_realization_backtracking_attempts": 7,
        "early_exploration_acceptance_unchanged": True,
        "td_inner_finecdf_predicted_step_threshold_unchanged": True,
        "hard_coefficient_envelopes_unchanged": True,
        "protected_profile_guards_unchanged": True,
        "severity_guards_unchanged": True,
        "dynamic_skim_method_unchanged": True,
        "assignment_method_unchanged": True,
    }


def _apply_fastcal_fields(cfg: dict[str, Any]) -> None:
    # TG: enlarge the effective stage limits.  max_add_log must be at least the
    # family-global log cap, otherwise the nonlinear centering layer would clip
    # the requested 10/6/3% family step back to the old 6/4/2% per-zone caps.
    perf = cfg.setdefault("performance", {})
    stages = perf.get("generation_step_schedule") or []
    if len(stages) != 3:
        raise RuntimeError("V24916_FASTCAL1_GENERATION_STAGE_COUNT_MISMATCH")
    for stage, policy in zip(stages, TG_STAGE_POLICY):
        if str(stage.get("name")) != policy["name"]:
            raise RuntimeError("V24916_FASTCAL1_GENERATION_STAGE_NAME_MISMATCH:" + str(stage.get("name")))
        stage["signed_max_family_global_log_up"] = policy["signed_max_family_global_log"]
        stage["signed_max_family_global_log_down"] = policy["signed_max_family_global_log"]
        stage["max_add_log_up"] = policy["max_add_log"]
        stage["max_add_log_down"] = policy["max_add_log"]
        stage["salary_max_abs_delta_per_block"] = policy["salary_max_abs_delta_per_block"]
        stage["max_od_relative_up"] = policy["max_od_relative"]
        stage["max_od_relative_down"] = policy["max_od_relative"]

    # Keep no-stage/fallback limits coherent with the late stage.
    late = TG_STAGE_POLICY[-1]
    cfg["max_add_log_up"] = late["max_add_log"]
    cfg["max_add_log_down"] = late["max_add_log"]
    cfg["max_od_relative_up"] = late["max_od_relative"]
    cfg["max_od_relative_down"] = late["max_od_relative"]
    cfg.setdefault("salary", {})["max_abs_delta_per_block"] = late["salary_max_abs_delta_per_block"]
    signed = cfg.setdefault("generation_signed_refinement", {})
    signed["max_family_global_log_up"] = late["signed_max_family_global_log"]
    signed["max_family_global_log_down"] = late["signed_max_family_global_log"]

    # More TG trial sizes.  Ordering and first three values are preserved; only
    # smaller fallbacks are appended so the aggressive trial is still tried first.
    cfg["backtracking_scales"] = list(TG_BACKTRACKING_SCALES)
    cfg.setdefault("trial_calibration", {}).setdefault("max_trials_per_block", {})["GENERATION"] = 6

    # After the existing early-exploration horizon, the core CAL gate falls back
    # to this materiality threshold.  1e-5 == 0.001%.
    cfg["min_cal_objective_relative_improvement"] = POST_EXPLORATION_CAL_MIN_RELATIVE_IMPROVEMENT

    # Normal (post-early-exploration) TD selected-objective materiality.
    cfg.setdefault("td", {})["min_selected_component_relative_improvement"] = TD_SELECTED_MIN_RELATIVE_IMPROVEMENT
    cfg.setdefault("td_soft_reference_policy", {})[
        "aggregate_selected_min_relative_improvement"] = TD_SELECTED_MIN_RELATIVE_IMPROVEMENT

    # Seven full downstream realization backtracks in the same B / log(-C)
    # coordinate system.  Native IPF tolerance remains untouched.
    fine = cfg.setdefault("coupled_demand", {}).setdefault("finecdf_td", {})
    fine["realization_backtracking_scales"] = list(TD_REALIZATION_BACKTRACKING_SCALES)

    # Effective-runtime provenance: the parent formulas/authorities are intact,
    # but search/acceptance materiality is intentionally changed by user policy.
    impl = list(cfg.get("implementation") or [])
    impl = [x for x in impl if x != "CALIBRATION_MATH_AND_ACCEPTANCE_THRESHOLDS_UNCHANGED"]
    if "CALIBRATION_FORMULAS_UNCHANGED_FASTCAL1_SEARCH_AND_MATERIALITY_OVERRIDE" not in impl:
        impl.append("CALIBRATION_FORMULAS_UNCHANGED_FASTCAL1_SEARCH_AND_MATERIALITY_OVERRIDE")
    cfg["implementation"] = impl

    cfg["v24916_fastcal1"] = _policy_payload()
    cfg["v24916_fastcal1_hash"] = _hash(cfg["v24916_fastcal1"])

    identity = cfg.setdefault("v24916_release_identity", {})
    identity["release"] = RELEASE
    identity["package_revision"] = PACKAGE_REVISION
    identity["parent_reviewed_config_unchanged"] = False
    identity["parent_files_modified_on_disk"] = False
    identity["runtime_search_policy_override"] = True
    identity["acceptance_materiality_override"] = True


def apply_active_runtime_delta(parent_cfg: Mapping[str, Any]) -> dict[str, Any]:
    cfg = base.apply_active_runtime_delta(parent_cfg)
    _apply_fastcal_fields(cfg)
    build_safety_contract(cfg)
    return cfg


def validate_active_runtime_delta(child: Mapping[str, Any], parent: Mapping[str, Any]) -> dict[str, Any]:
    # First independently prove the underlying fresh0/DYNAMICSKIM active overlay
    # is still valid against its sealed parent.
    base_child = base.apply_active_runtime_delta(parent)
    base.validate_active_runtime_delta(base_child, parent)

    expected = apply_active_runtime_delta(parent)
    if dict(child) != expected:
        keys = sorted(set(expected) | set(child))
        bad = [k for k in keys if child.get(k) != expected.get(k)]
        raise RuntimeError("V24916_FASTCAL1_CONFIG_DELTA_MISMATCH:" + ",".join(bad[:30]))

    # Hard scientific guards that FASTCAL1 is explicitly not allowed to touch.
    if child.get("early_exploration_acceptance") != base_child.get("early_exploration_acceptance"):
        raise RuntimeError("V24916_FASTCAL1_EARLY_EXPLORATION_POLICY_CHANGED")
    for key in (
        "idp_max_mean_degradation", "idp_max_component_degradation",
        "max_new_geh20", "max_new_geh30", "max_protected_to_warn", "max_protected_to_hard",
    ):
        if child.get(key) != base_child.get(key):
            raise RuntimeError("V24916_FASTCAL1_HARD_GUARD_CHANGED:" + key)
    if child.get("assignment") != base_child.get("assignment"):
        raise RuntimeError("V24916_FASTCAL1_ASSIGNMENT_POLICY_CHANGED")
    if child.get("v24916_flowbundle_skim_runtime") != base_child.get("v24916_flowbundle_skim_runtime"):
        raise RuntimeError("V24916_FASTCAL1_DYNAMIC_SKIM_RUNTIME_CHANGED")
    if child.get("demand_evidence_targeting") != base_child.get("demand_evidence_targeting"):
        raise RuntimeError("V24916_FASTCAL1_TARGETING_POLICY_CHANGED")

    safety = build_safety_contract(child)
    p = child["v24916_fastcal1"]
    if p != _policy_payload() or child.get("v24916_fastcal1_hash") != _hash(p):
        raise RuntimeError("V24916_FASTCAL1_POLICY_HASH_MISMATCH")

    return {
        "schema": "R1_15A2_V24916_FASTCAL1_CONFIG_DELTA_AUDIT_V1",
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "parent_files_modified_on_disk": False,
        "parent_active_overlay_validated": True,
        "calibration_formulas_changed": False,
        "tg_search_envelope_changed": True,
        "tg_trial_count_changed": True,
        "post_exploration_geh_materiality_changed": True,
        "td_selected_objective_materiality_changed": True,
        "td_realization_backtracking_changed": True,
        "early_exploration_policy_changed": False,
        "native_ipf_tolerance_changed": False,
        "dynamic_skim_method_changed": False,
        "assignment_method_changed": False,
        "hard_coefficient_envelopes_changed": False,
        "safety_contract_hash": safety.contract_hash,
        "fastcal_policy_hash": child["v24916_fastcal1_hash"],
    }


__all__ = [
    "RELEASE", "PACKAGE_REVISION", "FASTCAL_SCHEMA", "AUTHORITY_FILE", "ISOLATION_SCHEMA",
    "SOURCE_SEMANTIC_POLICY", "EXPECTED_BASELINE_SEMANTIC_STATE_HASH", "WORKSPACE_NAME",
    "RUNS_ROOT_NAME", "LOCK_NAME", "PRIVATE_CACHE_DIRNAME", "TG_BACKTRACKING_SCALES",
    "TD_REALIZATION_BACKTRACKING_SCALES", "TG_STAGE_POLICY",
    "POST_EXPLORATION_CAL_MIN_RELATIVE_IMPROVEMENT", "TD_SELECTED_MIN_RELATIVE_IMPROVEMENT",
    "apply_active_runtime_delta", "validate_active_runtime_delta",
]
