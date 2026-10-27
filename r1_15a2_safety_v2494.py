# -*- coding: utf-8 -*-
"""V2.4.9.4 path-export retry and semantic restart safety contract."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_supply import SupplyContractError
import r1_15a2_runtime_v1 as rt
from r1_15a2_restart_v2494 import SCHEMA as RESTART_SCHEMA, SEMANTIC_FIELDS, RAW_VER_SHA_ROLE

RELEASE = "R1_15A2_V2_4_9_4_PATH_EXPORT_RETRY_SEMANTIC_RESTART_20261018"
V2493_RELEASE = "R1_15A2_V2_4_9_3_METHOD_AND_COM_CORRECTIONS_20261018"
V2493_CONFIG_SHA256 = "35b6397a562c9f40cd12e9cb1f429a31ef9120a92a86d0b0bde6a665ed0e974d"
V2493_PATH_IMPLEMENTATION_FILES = {
    "r1_15a2_two_mode_v238.py": "a58980069e942b6782f6d906443e81922f81e6596eb5de5be456719f96ce15ad",
    "r1_15a2_trial_adapter_v240.py": "f55e7e4936bb93770fb7ff99d6a485a0695575f1e6c59ba44552e2163c857109",
    "r1_15a2_persistent_path_cache_v248.py": "78522a1a9d7bd4bcabfb360604fd9c0a6d3415e0d845d935e7c3084aeedb276c",
    "r1_15a2_sequence_v23.py": "91a3c65e7c38a56dbb560d5debe91235ae10637176de16f08b29ccd09ff5a983",
    "r1_15a2_supply.py": "98ecbb546fc510b491508e23eb4e1a26a217a480e0a2dafc3c203fe75f317af6",
    "r1_15a2_core.py": "79543d7203d9b16039924fe761590cf58fdc7428117fcecc0bb6bb5d69da3449",
    "r1_15a2_runtime_v1.py": "f035c4109f928c6008368d7d5b3c1ec77123c02d7672ccbef7bc90dae91a9f00",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_parent_bytes(root: Path) -> Mapping[str, Any]:
    path = root / "R1_15A2_CONFIG_V2_4_9_3.json"
    _require(path.is_file(), "V2494_BUNDLED_V2493_CONFIG_MISSING")
    _require(rt.sha256_file(path) == V2493_CONFIG_SHA256,
             "V2494_BUNDLED_V2493_CONFIG_HASH_MISMATCH")
    cfg = rt.read_json(path)
    _require(cfg.get("release") == V2493_RELEASE,
             "V2494_BUNDLED_V2493_RELEASE_MISMATCH")
    return cfg


def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    baseline = copy.deepcopy(_validate_parent_bytes(root))
    candidate = copy.deepcopy(dict(cfg))
    allowed_top = {
        "version", "release", "safety_gate_release", "methodology",
        "implementation_files", "com_resilience", "restart_authority",
    }
    for key, old_value in baseline.items():
        if key in allowed_top:
            continue
        _require(key in candidate, "V2494_CONFIG_KEY_MISSING:" + key)
        new_value = candidate[key]
        if key == "performance":
            old_value = copy.deepcopy(old_value); new_value = copy.deepcopy(new_value)
            old_value.pop("release", None); new_value.pop("release", None)
            old_compat = old_value["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            new_compat = new_value["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
            old_compat.pop("target_release", None); new_compat.pop("target_release", None)
            new_compat["predecessors"] = [
                row for row in new_compat.get("predecessors", [])
                if row.get("source_release") != V2493_RELEASE
            ]
        _require(_canonical(new_value) == _canonical(old_value),
                 "V2494_UNREVIEWED_CONFIG_DRIFT:" + key)


def validate_v2494_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    _validate_reviewed_delta(cfg, root)

    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V2494_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") ==
             "2.4.9.4-path-export-retry-semantic-restart-tg-td-supply",
             "V2494_VERSION_IDENTITY_MISSING")

    # Preserve all V2.4.9.3 methodological corrections.
    csd = cfg.get("csd_calibration_objective", {}) or {}
    _require(csd.get("metric") == "WEIGHTED_MEAN_GEH" and
             csd.get("unique_trip_interpretation_allowed") is False,
             "V2494_WEIGHTED_GEH_OR_PROFILE_SUM_CONTRACT_LOST")
    td = cfg.get("td", {}) or {}
    _require(td.get("long_acceptance_mode") == "GLOBAL_LONG_COMPOSITE" and
             td.get("long_composite_authority") == "AGGREGATE_CL_GUARD_GLOBAL_MIX",
             "V2494_LONG_COMPOSITE_CONTRACT_LOST")
    _require(str(cfg.get("guidance_mode", "")).upper() == "SIGNED" and
             cfg.get("allow_signed_apply") is True,
             "V2494_SIGNED_GENERATION_CONTRACT_LOST")

    com = cfg.get("com_resilience", {}) or {}
    expected_core = {
        "enabled": True,
        "max_attempts": 5,
        "initial_delay_seconds": 0.05,
        "backoff_factor": 2.0,
        "max_delay_seconds": 0.8,
        "helper_retry_enabled": True,
        "zone_identity_cache": True,
        "zone_readback_tolerance": 1.0e-7,
        "retryable_hresult": [-2147418111, -2147417846],
        "retry_scope": "TRANSIENT_RPC_CALL_REJECTED_OR_RETRY_LATER_ONLY",
        "bounded_path_export_retry_enabled": True,
        "bounded_path_export_same_range_required": True,
        "page_size_fallback_policy": "NONTRANSIENT_MEMORY_OR_RANGE_ERRORS_ONLY",
        "raw_ole_invoke_without_retry_forbidden_in_active_path_export": True,
    }
    _require(_canonical(com) == _canonical(expected_core),
             "V2494_COM_PATH_EXPORT_RETRY_CONTRACT_CHANGED")

    restart = cfg.get("restart_authority", {}) or {}
    expected_restart = {
        "mode": "SEMANTIC_MODEL_STATE",
        "schema": RESTART_SCHEMA,
        "semantic_fields": list(SEMANTIC_FIELDS),
        "raw_ver_sha_role": RAW_VER_SHA_ROLE,
        "raw_ver_sha_used_for_restart_acceptance": False,
        "cross_release_snapshot_state_hash_comparison_allowed": False,
        "optional_adjacent_semantic_sidecar": True,
        "require_working_copy_semantic_identity": True,
        "checkpoint_semantic_sidecar": True,
        "require_source_unchanged_during_run": True,
    }
    _require(_canonical(restart) == _canonical(expected_restart),
             "V2494_SEMANTIC_RESTART_CONTRACT_CHANGED")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V2494_CACHE_COMPAT_TARGET_CHANGED")
    rows = [r for r in compat.get("predecessors", [])
            if r.get("source_release") == V2493_RELEASE]
    _require(len(rows) == 1 and
             rows[0].get("source_config_sha256s") == [V2493_CONFIG_SHA256],
             "V2494_V2493_CONFIG_PROVENANCE_NOT_PINNED")
    _require(rows[0].get("source_path_implementation_files") == V2493_PATH_IMPLEMENTATION_FILES,
             "V2494_V2493_PATH_IMPLEMENTATION_NOT_PINNED")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_4.py",
        "r1_15a2_safety_v2494.py", "r1_15a2_restart_v2494.py",
        "r1_15a2_com_compat.py", "r1_15a2_two_mode_v238.py",
        "r1_15a2_runtime_v1.py", "r1_15a2_trial_adapter_v240.py",
        "r1_15a2_overnight_controller_v240.py", "r1_15a2_live_api_audit.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V2494_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V2494_IMPLEMENTATION_HASH_MISMATCH:" + name)

    return {
        "passes": True,
        "parent_release": V2493_RELEASE,
        "path_export_retry": "SAME_RANGE_TRANSIENT_ONLY",
        "page_size_fallback": "NONTRANSIENT_MEMORY_OR_RANGE_ONLY",
        "restart_authority": "SEMANTIC_MODEL_STATE",
        "raw_ver_sha_role": RAW_VER_SHA_ROLE,
        "real_visum_tested": False,
        "production_ready": False,
    }


__all__ = [
    "RELEASE", "V2493_RELEASE", "V2493_CONFIG_SHA256",
    "V2493_PATH_IMPLEMENTATION_FILES", "validate_v2494_config",
]
