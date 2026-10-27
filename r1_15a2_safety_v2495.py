# -*- coding: utf-8 -*-
"""V2.4.9.5 GEH20 hysteresis and bounded severity-budget safety contract."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_supply import SupplyContractError
import r1_15a2_runtime_v1 as rt
from r1_15a2_restart_v2494 import SCHEMA as RESTART_SCHEMA, SEMANTIC_FIELDS, RAW_VER_SHA_ROLE

RELEASE = "R1_15A2_V2_4_9_5_GEH20_HYSTERESIS_SEVERITY_BUDGET_20261018"
V2494_RELEASE = "R1_15A2_V2_4_9_4_PATH_EXPORT_RETRY_SEMANTIC_RESTART_20261018"
V2494_CONFIG_SHA256 = "deb888c4a201a085062193216657598fa9a2ecab7bf59ecef5343eab4b192258"
V2494_PATH_IMPLEMENTATION_FILES = {
    "r1_15a2_two_mode_v238.py": "3722fabe5b90f7bb0367f840d466c3a6c9de6a6ddb483dda0ec7db8eed6c3d8a",
    "r1_15a2_trial_adapter_v240.py": "e0216130f66af3adaddbc6108945207d19b0af9e982747a27f95f36e0cad4015",
    "r1_15a2_persistent_path_cache_v248.py": "78522a1a9d7bd4bcabfb360604fd9c0a6d3415e0d845d935e7c3084aeedb276c",
    "r1_15a2_sequence_v23.py": "91a3c65e7c38a56dbb560d5debe91235ae10637176de16f08b29ccd09ff5a983",
    "r1_15a2_supply.py": "98ecbb546fc510b491508e23eb4e1a26a217a480e0a2dafc3c203fe75f317af6",
    "r1_15a2_core.py": "79543d7203d9b16039924fe761590cf58fdc7428117fcecc0bb6bb5d69da3449",
    "r1_15a2_runtime_v1.py": "ae9dba5c3c2925cc16d0e42f1c8b695ffa460bf0e3fd672ed0a41434d8b5cc62",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_parent_bytes(root: Path) -> Mapping[str, Any]:
    path = root / "R1_15A2_CONFIG_V2_4_9_4.json"
    _require(path.is_file(), "V2495_BUNDLED_V2494_CONFIG_MISSING")
    _require(rt.sha256_file(path) == V2494_CONFIG_SHA256,
             "V2495_BUNDLED_V2494_CONFIG_HASH_MISMATCH")
    cfg = rt.read_json(path)
    _require(cfg.get("release") == V2494_RELEASE,
             "V2495_BUNDLED_V2494_RELEASE_MISMATCH")
    return cfg


def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    baseline = copy.deepcopy(_validate_parent_bytes(root))
    candidate = copy.deepcopy(dict(cfg))
    allowed_top = {
        "version", "release", "safety_gate_release", "methodology",
        "implementation_files", "geh20_transition_policy",
    }
    for key, old_value in baseline.items():
        if key in allowed_top:
            continue
        _require(key in candidate, "V2495_CONFIG_KEY_MISSING:" + key)
        new_value = candidate[key]
        if key == "performance":
            old_value = copy.deepcopy(old_value); new_value = copy.deepcopy(new_value)
            old_value.pop("release", None); new_value.pop("release", None)
            old_compat = old_value["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            new_compat = new_value["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            old_compat.pop("target_release", None); new_compat.pop("target_release", None)
            new_compat["predecessors"] = [
                row for row in new_compat.get("predecessors", [])
                if row.get("source_release") != V2494_RELEASE
            ]
        _require(_canonical(new_value) == _canonical(old_value),
                 "V2495_UNREVIEWED_CONFIG_DRIFT:" + key)


def validate_v2495_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    _validate_reviewed_delta(cfg, root)

    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V2495_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") ==
             "2.4.9.5-geh20-hysteresis-severity-budget-tg-td-supply",
             "V2495_VERSION_IDENTITY_MISSING")

    # Preserve the full V2.4.9.4 methodology and runtime contracts.
    csd = cfg.get("csd_calibration_objective", {}) or {}
    _require(csd.get("metric") == "WEIGHTED_MEAN_GEH" and
             csd.get("unique_trip_interpretation_allowed") is False,
             "V2495_WEIGHTED_GEH_OR_PROFILE_SUM_CONTRACT_LOST")
    td = cfg.get("td", {}) or {}
    _require(td.get("long_acceptance_mode") == "GLOBAL_LONG_COMPOSITE" and
             td.get("long_composite_authority") == "AGGREGATE_CL_GUARD_GLOBAL_MIX",
             "V2495_LONG_COMPOSITE_CONTRACT_LOST")
    _require(float(td.get("max_cal_geh_relative_degradation", -1.0)) == 0.005,
             "V2495_TD_CAL_GEH_GUARD_CHANGED")
    _require(str(cfg.get("guidance_mode", "")).upper() == "SIGNED" and
             cfg.get("allow_signed_apply") is True,
             "V2495_SIGNED_GENERATION_CONTRACT_LOST")

    # The reviewed change: GEH20 is no longer a discontinuous zero-tolerance wall.
    policy = cfg.get("geh20_transition_policy", {}) or {}
    expected_policy = {
        "mode": "HYSTERESIS_BUDGET",
        "threshold": 20.0,
        "hysteresis_low": 19.5,
        "hysteresis_high": 20.5,
        "max_new_geh30": 0,
        "generation": {
            "max_material_new_geh20": 3,
            "max_single_profile_geh_increase": 2.0,
            "max_total_new_geh20_excess": 2.0,
        },
        "td": {
            "max_material_new_geh20": 1,
            "max_single_profile_geh_increase": 1.0,
            "max_total_new_geh20_excess": 0.75,
        },
        "legacy_max_new_geh20_role": "IGNORED_WHEN_HYSTERESIS_BUDGET_ENABLED",
        "continuous_penalty_role": "DEFERRED_NOT_IMPLEMENTED_IN_V2495",
    }
    _require(_canonical(policy) == _canonical(expected_policy),
             "V2495_GEH20_HYSTERESIS_BUDGET_CONTRACT_CHANGED")
    _require(cfg.get("max_new_geh20") == 0,
             "V2495_LEGACY_MAX_NEW_GEH20_FIELD_CHANGED")
    _require(cfg.get("max_new_geh30") == 0 and
             cfg.get("max_protected_to_warn") == 3 and
             cfg.get("max_protected_to_hard") == 0,
             "V2495_OTHER_PROFILE_GUARDS_CHANGED")

    com = cfg.get("com_resilience", {}) or {}
    _require(com.get("bounded_path_export_retry_enabled") is True and
             com.get("bounded_path_export_same_range_required") is True and
             com.get("page_size_fallback_policy") == "NONTRANSIENT_MEMORY_OR_RANGE_ERRORS_ONLY",
             "V2495_V2494_PATH_EXPORT_RETRY_CONTRACT_LOST")
    restart = cfg.get("restart_authority", {}) or {}
    _require(restart.get("mode") == "SEMANTIC_MODEL_STATE" and
             restart.get("schema") == RESTART_SCHEMA and
             restart.get("semantic_fields") == list(SEMANTIC_FIELDS) and
             restart.get("raw_ver_sha_role") == RAW_VER_SHA_ROLE and
             restart.get("raw_ver_sha_used_for_restart_acceptance") is False,
             "V2495_V2494_SEMANTIC_RESTART_CONTRACT_LOST")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V2495_CACHE_COMPAT_TARGET_CHANGED")
    rows = [r for r in compat.get("predecessors", [])
            if r.get("source_release") == V2494_RELEASE]
    _require(len(rows) == 1 and
             rows[0].get("source_config_sha256s") == [V2494_CONFIG_SHA256],
             "V2495_V2494_CONFIG_PROVENANCE_NOT_PINNED")
    _require(rows[0].get("source_path_implementation_files") == V2494_PATH_IMPLEMENTATION_FILES,
             "V2495_V2494_PATH_IMPLEMENTATION_NOT_PINNED")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_5.py",
        "r1_15a2_safety_v2495.py", "r1_15a2_core.py",
        "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
        "r1_15a2_com_compat.py", "r1_15a2_two_mode_v238.py",
        "r1_15a2_runtime_v1.py", "r1_15a2_trial_adapter_v240.py",
        "r1_15a2_overnight_controller_v240.py", "r1_15a2_live_api_audit.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V2495_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V2495_IMPLEMENTATION_HASH_MISMATCH:" + name)

    return {
        "passes": True,
        "parent_release": V2494_RELEASE,
        "geh20_transition_mode": "HYSTERESIS_BUDGET",
        "generation_material_new_geh20_limit": 3,
        "td_material_new_geh20_limit": 1,
        "new_geh30_limit": 0,
        "continuous_penalty": "DEFERRED",
        "path_export_retry_retained": True,
        "semantic_restart_retained": True,
        "real_visum_tested": False,
        "production_ready": False,
    }


__all__ = [
    "RELEASE", "V2494_RELEASE", "V2494_CONFIG_SHA256",
    "V2494_PATH_IMPLEMENTATION_FILES", "validate_v2495_config",
]
