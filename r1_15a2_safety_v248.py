# -*- coding: utf-8 -*-
"""Persistent path-cache safety contract for R1 15A2 V2.4.8."""
from __future__ import annotations

from r1_15a2_safety_v247 import (
    adapter_config_scope, final_artifact_name, recovery_scope,
    stationary_td_result, validate_v247_config,
)
from r1_15a2_supply import SupplyContractError


def validate_v248_config(cfg, package_root=None):
    base = validate_v247_config(cfg, package_root)
    perf = cfg.get("performance", {})
    if perf.get("release") != "V2.4.8":
        raise SupplyContractError("V248_RELEASE_IDENTITY_MISSING")
    if perf.get("search_semantics") != \
            "PERSISTENT_PATH_EPOCH_ADAPTIVE_EXPLICIT_NOT_BITWISE_IDENTICAL":
        raise SupplyContractError("V248_SEARCH_SEMANTICS_NOT_ACKNOWLEDGED")
    persistent = perf.get("persistent_path_cache", {})
    required_true = (
        "enabled", "publication_required", "verify_sha256_on_restore",
        "sqlite_quick_check_on_restore", "sqlite_full_integrity_check_on_publish",
        "accepted_state_binding_required_for_descendant_reuse",
        "allow_legacy_v247_import", "legacy_import_requires_exact_origin_state",
        "legacy_import_requires_all_profile_flow_parity",
    )
    for key in required_true:
        if persistent.get(key) is not True:
            raise SupplyContractError("V248_PERSISTENT_CACHE_REQUIRED_FLAG:" + key)
    if persistent.get("root_policy") != \
            "LOCALAPPDATA_UNSYNCED_WITH_PROJECT_FALLBACK":
        raise SupplyContractError("V248_PERSISTENT_CACHE_ROOT_POLICY_CHANGED")
    if persistent.get("persistent_store_mode") != \
            "IMMUTABLE_READ_ONLY_AFTER_PUBLICATION":
        raise SupplyContractError("V248_PERSISTENT_STORE_MODE_CHANGED")
    if persistent.get("latest_pointer_publish_order") != \
            "STORE_THEN_MANIFEST_THEN_BINDING_THEN_INDEX":
        raise SupplyContractError("V248_PERSISTENT_PUBLICATION_ORDER_CHANGED")
    retain = persistent.get("retain_epoch_checkpoints")
    if isinstance(retain, bool) or not isinstance(retain, int) or not 1 <= retain <= 8:
        raise SupplyContractError("V248_PERSISTENT_RETENTION_OUT_OF_RANGE")
    total_gib = persistent.get("max_total_cache_gib")
    if isinstance(total_gib, bool) or not isinstance(total_gib, (int, float)) or not 1.0 <= float(total_gib) <= 128.0:
        raise SupplyContractError("V248_PERSISTENT_TOTAL_CACHE_GIB_OUT_OF_RANGE")
    epochs = perf.get("path_epochs", {})
    if epochs.get("initial_epoch_source") != \
            "AUTHORIZED_PERSISTENT_CACHE_OR_FRESH_ENUMERATION":
        raise SupplyContractError("V248_INITIAL_EPOCH_SOURCE_CHANGED")
    if epochs.get("cross_run_reuse") != \
            "EXACT_ORIGIN_STATE_OR_EXPLICIT_ACCEPTED_STATE_BINDING_ONLY":
        raise SupplyContractError("V248_CROSS_RUN_REUSE_POLICY_CHANGED")
    if epochs.get("persistent_epoch_checkpoint_after_every_successful_enumeration") is not True:
        raise SupplyContractError("V248_EPOCH_CHECKPOINT_REQUIRED")
    if epochs.get("legacy_import_policy") != \
            "EXACT_ORIGIN_STATE_PLUS_ALL_PROFILE_FLOW_PARITY":
        raise SupplyContractError("V248_LEGACY_IMPORT_POLICY_CHANGED")
    if epochs.get("persistent_cache_read_only_during_calibration") is not True:
        raise SupplyContractError("V248_PERSISTENT_CACHE_MUST_BE_READ_ONLY")
    if epochs.get("intrazonal_positive_od_policy") != \
            "NO_NETWORK_PATH_REQUIRED_EXCLUDED_FROM_PATH_SUPPORT_GAP":
        raise SupplyContractError("V2481_INTRAZONAL_PATH_POLICY_MISSING")
    if epochs.get("obsolete_store_windows_lock_policy") != \
            "DEFER_CLEANUP_AFTER_VERIFIED_REFRESH_NOT_FATAL":
        raise SupplyContractError("V2481_WINDOWS_SQLITE_RETIRE_POLICY_MISSING")
    if cfg.get("trial_calibration", {}).get("v248_persistent_path_cache_policy") != \
            "HASHED_SQLITE_PLUS_STATE_BINDINGS_FAIL_CLOSED":
        raise SupplyContractError("V248_TRIAL_PERSISTENT_POLICY_MISSING")
    implementation = cfg.get("implementation_files", {})
    for name in ("r1_15a2_persistent_path_cache_v248.py",
                 "r1_15a2_safety_v248.py"):
        value = implementation.get(name)
        if not isinstance(value, str) or len(value) != 64:
            raise SupplyContractError("V248_IMPLEMENTATION_HASH_MISSING:" + name)
    return {
        "passes": True,
        "base_contract": base,
        "persistent_path_cache": True,
        "retained_epoch_checkpoints": retain,
        "max_total_cache_gib": float(total_gib),
        "cross_run_reuse": epochs["cross_run_reuse"],
        "legacy_import": epochs["legacy_import_policy"],
    }


__all__ = [
    "adapter_config_scope", "final_artifact_name", "recovery_scope",
    "stationary_td_result", "validate_v248_config",
]
