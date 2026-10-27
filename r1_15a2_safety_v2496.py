# -*- coding: utf-8 -*-
"""V2.4.9.6 early-exploration Pareto acceptance safety contract."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_supply import SupplyContractError
import r1_15a2_runtime_v1 as rt
from r1_15a2_restart_v2494 import SCHEMA as RESTART_SCHEMA, SEMANTIC_FIELDS, RAW_VER_SHA_ROLE

RELEASE = "R1_15A2_V2_4_9_6_EARLY_EXPLORATION_PARETO_ACCEPTANCE_20261018"
V2495_RELEASE = "R1_15A2_V2_4_9_5_GEH20_HYSTERESIS_SEVERITY_BUDGET_20261018"
V2495_CONFIG_SHA256 = "59bfa7013a8f141c559c4232031e1c0fb6979da4f54cec976bc05211be1d4e7c"
V2495_PATH_IMPLEMENTATION_FILES = {
    "r1_15a2_two_mode_v238.py": "3722fabe5b90f7bb0367f840d466c3a6c9de6a6ddb483dda0ec7db8eed6c3d8a",
    "r1_15a2_trial_adapter_v240.py": "e0216130f66af3adaddbc6108945207d19b0af9e982747a27f95f36e0cad4015",
    "r1_15a2_persistent_path_cache_v248.py": "78522a1a9d7bd4bcabfb360604fd9c0a6d3415e0d845d935e7c3084aeedb276c",
    "r1_15a2_sequence_v23.py": "91a3c65e7c38a56dbb560d5debe91235ae10637176de16f08b29ccd09ff5a983",
    "r1_15a2_supply.py": "98ecbb546fc510b491508e23eb4e1a26a217a480e0a2dafc3c203fe75f317af6",
    "r1_15a2_core.py": "8d94a93cd309141806451176f0aa55c3f510d7c1ab389066b649fbe687c5db32",
    "r1_15a2_runtime_v1.py": "ae9dba5c3c2925cc16d0e42f1c8b695ffa460bf0e3fd672ed0a41434d8b5cc62",
}

EXPECTED_EARLY_POLICY = {
    "enabled": True,
    "through_outer_cycle": 8,
    "mode": "NONMONOTONIC_PARETO_WITH_BEST_SO_FAR",
    "generation": {
        "minimum_positive_relative_improvement": 0.0,
        "positive_improvement_epsilon": 1e-12,
        "max_cal_relative_degradation_for_severity_tradeoff": 0.02,
        "min_severity20_relative_improvement": 0.01,
        "min_severity30_relative_improvement": 0.01,
        "min_geh20_count_reduction": 3,
        "min_geh30_count_reduction": 1,
    },
    "td": {
        "min_selected_relative_improvement": 0.0025,
        "max_cal_relative_degradation": 0.05,
        "min_benefit_cost_ratio": 1.5,
        "max_selected_component_relative_degradation": 0.20,
        "max_nonselected_component_relative_degradation": 0.20,
    },
    "severity": {
        "geh20_role": "DIAGNOSTIC_CONTINUOUS_PENALTY",
        "geh30_role": "DIAGNOSTIC_CONTINUOUS_PENALTY",
        "geh35_role": "WARNING",
        "geh40_role": "HARD_REJECT_NEW_CROSSING",
        "max_new_geh40": 0,
        "max_single_profile_geh_increase": 15.0,
        "absolute_geh_ceiling": 60.0,
        "protected_before_geh": 5.0,
        "protected_after_hard_geh": 20.0,
        "max_protected_catastrophic": 0,
        "severity_score_power": 2.0,
    },
    "best_so_far": {
        "enabled": True,
        "metric": "FIXED_REFERENCE_SHARED_OBJECTIVE",
        "minimum_improvement": 1e-8,
        "publish_dedicated_checkpoint": True,
    },
    "fallback_after_early_cycles": "V2495_GEH20_HYSTERESIS_BUDGET_AND_INHERITED_MONOTONIC_THRESHOLDS",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_parent_bytes(root: Path) -> Mapping[str, Any]:
    path = root / "R1_15A2_CONFIG_V2_4_9_5.json"
    _require(path.is_file(), "V2496_BUNDLED_V2495_CONFIG_MISSING")
    _require(rt.sha256_file(path) == V2495_CONFIG_SHA256,
             "V2496_BUNDLED_V2495_CONFIG_HASH_MISMATCH")
    cfg = rt.read_json(path)
    _require(cfg.get("release") == V2495_RELEASE,
             "V2496_BUNDLED_V2495_RELEASE_MISMATCH")
    return cfg


def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    baseline = copy.deepcopy(_validate_parent_bytes(root))
    candidate = copy.deepcopy(dict(cfg))
    allowed_top = {
        "version", "release", "safety_gate_release", "methodology",
        "implementation_files", "early_exploration_acceptance",
    }
    for key, old_value in baseline.items():
        if key in allowed_top:
            continue
        _require(key in candidate, "V2496_CONFIG_KEY_MISSING:" + key)
        new_value = candidate[key]
        if key == "performance":
            old_value = copy.deepcopy(old_value); new_value = copy.deepcopy(new_value)
            old_value.pop("release", None); new_value.pop("release", None)
            old_compat = old_value["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            new_compat = new_value["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            old_compat.pop("target_release", None); new_compat.pop("target_release", None)
            new_compat["predecessors"] = [
                row for row in new_compat.get("predecessors", [])
                if row.get("source_release") != V2495_RELEASE
            ]
        elif key == "trial_calibration":
            old_value = copy.deepcopy(old_value); new_value = copy.deepcopy(new_value)
            new_value.pop("v2496_early_exploration_acceptance", None)
        _require(_canonical(new_value) == _canonical(old_value),
                 "V2496_UNREVIEWED_CONFIG_DRIFT:" + key)


def validate_v2496_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    _validate_reviewed_delta(cfg, root)
    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V2496_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") ==
             "2.4.9.6-early-exploration-pareto-acceptance-tg-td-supply",
             "V2496_VERSION_IDENTITY_MISSING")

    _require(_canonical(cfg.get("early_exploration_acceptance", {})) ==
             _canonical(EXPECTED_EARLY_POLICY),
             "V2496_EARLY_EXPLORATION_POLICY_CHANGED")

    # Inherited methodological and runtime authorities remain exact.
    csd = cfg.get("csd_calibration_objective", {}) or {}
    _require(csd.get("metric") == "WEIGHTED_MEAN_GEH" and
             csd.get("unique_trip_interpretation_allowed") is False,
             "V2496_WEIGHTED_GEH_OR_PROFILE_SUM_CONTRACT_LOST")
    td = cfg.get("td", {}) or {}
    _require(td.get("long_acceptance_mode") == "GLOBAL_LONG_COMPOSITE" and
             td.get("long_composite_authority") == "AGGREGATE_CL_GUARD_GLOBAL_MIX",
             "V2496_LONG_COMPOSITE_CONTRACT_LOST")
    _require(float(td.get("max_cal_geh_relative_degradation", -1.0)) == 0.005,
             "V2496_POST_EXPLORATION_TD_GUARD_CHANGED")
    _require(float(cfg.get("min_cal_objective_relative_improvement", -1.0)) == 0.001,
             "V2496_POST_EXPLORATION_GENERATION_GUARD_CHANGED")
    _require(str(cfg.get("guidance_mode", "")).upper() == "SIGNED" and
             cfg.get("allow_signed_apply") is True,
             "V2496_SIGNED_GENERATION_CONTRACT_LOST")

    # V2.4.9.5 remains the exact fallback after cycle 8.
    policy = cfg.get("geh20_transition_policy", {}) or {}
    parent_policy = _validate_parent_bytes(root).get("geh20_transition_policy", {}) or {}
    _require(_canonical(policy) == _canonical(parent_policy),
             "V2496_V2495_FALLBACK_GEH20_POLICY_CHANGED")

    com = cfg.get("com_resilience", {}) or {}
    _require(com.get("bounded_path_export_retry_enabled") is True and
             com.get("bounded_path_export_same_range_required") is True and
             com.get("page_size_fallback_policy") == "NONTRANSIENT_MEMORY_OR_RANGE_ERRORS_ONLY",
             "V2496_PATH_EXPORT_RETRY_CONTRACT_LOST")
    restart = cfg.get("restart_authority", {}) or {}
    _require(restart.get("mode") == "SEMANTIC_MODEL_STATE" and
             restart.get("schema") == RESTART_SCHEMA and
             restart.get("semantic_fields") == list(SEMANTIC_FIELDS) and
             restart.get("raw_ver_sha_role") == RAW_VER_SHA_ROLE and
             restart.get("raw_ver_sha_used_for_restart_acceptance") is False,
             "V2496_SEMANTIC_RESTART_CONTRACT_LOST")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V2496_CACHE_COMPAT_TARGET_CHANGED")
    rows = [r for r in compat.get("predecessors", [])
            if r.get("source_release") == V2495_RELEASE]
    _require(len(rows) == 1 and
             rows[0].get("source_config_sha256s") == [V2495_CONFIG_SHA256],
             "V2496_V2495_CONFIG_PROVENANCE_NOT_PINNED")
    _require(rows[0].get("source_path_implementation_files") == V2495_PATH_IMPLEMENTATION_FILES,
             "V2496_V2495_PATH_IMPLEMENTATION_NOT_PINNED")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_6.py",
        "r1_15a2_safety_v2496.py", "r1_15a2_core.py",
        "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
        "r1_15a2_overnight_controller_v240.py",
        "r1_15a2_overnight_controller_v242.py",
        "r1_15a2_supply_visum.py", "r1_15a2_com_compat.py",
        "r1_15a2_two_mode_v238.py", "r1_15a2_runtime_v1.py",
        "r1_15a2_trial_adapter_v240.py", "r1_15a2_live_api_audit.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V2496_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V2496_IMPLEMENTATION_HASH_MISMATCH:" + name)

    return {
        "passes": True,
        "parent_release": V2495_RELEASE,
        "early_exploration_through_outer_cycle": 8,
        "generation_positive_improvement_floor": 0.0,
        "generation_nonmonotonic_cal_degradation_limit": 0.02,
        "td_cal_degradation_limit": 0.05,
        "td_minimum_benefit_cost_ratio": 1.5,
        "geh20_role": "DIAGNOSTIC_CONTINUOUS_PENALTY",
        "geh30_role": "DIAGNOSTIC_CONTINUOUS_PENALTY",
        "geh35_role": "WARNING",
        "geh40_role": "HARD_REJECT_NEW_CROSSING",
        "best_so_far_checkpoint": True,
        "v2495_fallback_after_cycle_8": True,
        "real_visum_tested": False,
        "production_ready": False,
    }


__all__ = [
    "RELEASE", "V2495_RELEASE", "V2495_CONFIG_SHA256",
    "V2495_PATH_IMPLEMENTATION_FILES", "EXPECTED_EARLY_POLICY",
    "validate_v2496_config",
]
