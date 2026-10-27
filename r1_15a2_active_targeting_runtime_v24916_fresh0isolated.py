# -*- coding: utf-8 -*-
"""V24916 fresh-cycle-1 active-targeting overlay with hard parallel-run isolation.

This module deliberately starts a new calibration lineage from the currently
opened PROFILE488 baseline (accepted_count=0, outer_cycle=1) while preserving
V24916 Generation FlowBundle targeting and TD component masking.  It adds only
runtime metadata/isolation policy on top of the already-audited active-targeting
configuration; the parent acceptance mathematics remains unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

import r1_15a2_active_targeting_runtime_v24916p2c as base
from r1_15a2_safety_v24916p2c import build_safety_contract

RELEASE = "R1_15A2_V24916_PERF2C_PROFILE488_FRESH0_UNIVERSAL_VER_ISOLATED_ACTIVE_TARGETING_IOFIX3_PATHFIX3_CACHE_DISABLED_20261022"
PACKAGE_REVISION = "V24916_PROFILE488_FRESH0_UNIVERSAL_VER_ISOLATED_ACTIVE_TARGETING_IOFIX3_PATHFIX3_CACHE_DISABLED"
AUTHORITY_FILE = "V24916_FRESH0_ISOLATED_LIVE_AUTHORITY.json"
ISOLATION_SCHEMA = "R1_15A2_V24916_FRESH0_UNIVERSAL_VER_PARALLEL_ISOLATION_PATHFIX3_V3"
SOURCE_SEMANTIC_POLICY = "CURRENT_OPEN_VER_IS_DYNAMIC_BASELINE_PROVENANCE_ONLY"
# Compatibility symbol retained for older diagnostics/tests.  A fresh universal
# start intentionally has no predeclared semantic hash.
EXPECTED_BASELINE_SEMANTIC_STATE_HASH = None
RUNS_ROOT_NAME = "R1_15A2_V16_RUNS"
LOCK_NAME = ".R1_15A2_V16.lock"
WORKSPACE_NAME = RUNS_ROOT_NAME  # compatibility alias
PRIVATE_CACHE_DIRNAME = "PC_OFF"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def apply_active_runtime_delta(parent_cfg: Mapping[str, Any]) -> dict[str, Any]:
    cfg = base.apply_active_runtime_delta(parent_cfg)
    cfg["v24916_release_identity"] = copy.deepcopy(cfg["v24916_release_identity"])
    cfg["v24916_release_identity"].update({
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "parallel_isolation": True,
        "parent_reviewed_config_unchanged": True,
    })
    cfg["v24916_fresh_baseline"] = copy.deepcopy(cfg["v24916_fresh_baseline"])
    cfg["v24916_fresh_baseline"].update({
        "authority_file": AUTHORITY_FILE,
        "baseline_revision_reason": "PROFILE488_NEW_LINEAGE_FROM_ANY_LIVE_VER_PASSING_STRUCTURAL_PREFLIGHT",
        "source_semantic_policy": SOURCE_SEMANTIC_POLICY,
        "fixed_source_semantic_hash_required": False,
        "parallel_v24915_interference_forbidden": True,
        "external_cache_read_allowed": False,
        "legacy_cache_roots_allowed": False,
        "persistent_path_cache_enabled": False,
        "within_run_path_basis_reuse_allowed": True,
        "isolated_workspace_required": True,
    })
    # Hard-disable the cross-run persistent path cache for this parallel branch.
    # The calibration still keeps the freshly enumerated path basis alive inside
    # the current run, but it never restores/publishes the V248 persistent store.
    cfg["performance"] = copy.deepcopy(cfg.get("performance", {}))
    cfg["performance"]["persistent_path_cache"] = copy.deepcopy(
        cfg["performance"].get("persistent_path_cache", {}))
    cfg["performance"]["persistent_path_cache"]["enabled"] = False
    cfg["performance"]["persistent_path_cache"]["allow_legacy_v247_import"] = False
    pred = copy.deepcopy(cfg["performance"]["persistent_path_cache"].get(
        "explicit_predecessor_read_compatibility", {}))
    pred["enabled"] = False
    pred["incompatible_candidate_policy"] = "NO_PERSISTENT_CACHE_READS_IN_THIS_RELEASE"
    cfg["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"] = pred

    cfg["v24916_parallel_isolation"] = {
        "schema": ISOLATION_SCHEMA,
        "enabled": True,
        "workspace_name": WORKSPACE_NAME,
        "runs_root_name": RUNS_ROOT_NAME,
        "lock_name": LOCK_NAME,
        "pathfix3_enabled": True,
        "short_temp_name_policy": "OPAQUE_FIXED_LENGTH_SIBLING",
        "windows_extended_length_python_io": True,
        "safe_logical_path_budget": 240,
        "accepted_count_start": 0,
        "outer_cycle_start": 1,
        "prior_lineage_resumed": False,
        "shared_project_lock_allowed": False,
        "shared_runs_root_allowed": False,
        "shared_path_cache_root_allowed": False,
        "cross_run_cache_restore_allowed": False,
        "legacy_cache_import_allowed": False,
        "external_cache_read_allowed": False,
        "persistent_path_cache_enabled": False,
        "persistent_path_cache_reads_allowed": False,
        "persistent_path_cache_writes_allowed": False,
        "private_cache_location": "DISABLED",
        "private_cache_dirname": PRIVATE_CACHE_DIRNAME,
        "private_cache_initial_state": "DISABLED",
        "fresh_path_enumeration_required": True,
        "within_run_path_basis_reuse_allowed": True,
        "parallel_v24915_supported_only_in_separate_visum_process": True,
        "source_semantic_policy": SOURCE_SEMANTIC_POLICY,
        "fixed_source_semantic_hash_required": False,
        "source_semantic_state_hash_required": None,
    }
    cfg["v24916_fresh_baseline_runtime_hash"] = _hash(cfg["v24916_fresh_baseline"])
    cfg["v24916_parallel_isolation_hash"] = _hash(cfg["v24916_parallel_isolation"])
    build_safety_contract(cfg)
    return cfg


def validate_active_runtime_delta(child: Mapping[str, Any], parent: Mapping[str, Any]) -> dict[str, Any]:
    expected = apply_active_runtime_delta(parent)
    if dict(child) != expected:
        keys = sorted(set(expected) | set(child))
        bad = [k for k in keys if child.get(k) != expected.get(k)]
        raise RuntimeError("V24916_FRESH0_ISOLATED_CONFIG_DELTA_MISMATCH:" + ",".join(bad[:20]))

    stripped = copy.deepcopy(dict(child))
    # The only reviewed-parent field this release is allowed to change is the
    # persistent-cache PERFORMANCE switch.  Normalize it back to the parent
    # value before proving all calibration/search mathematics are unchanged.
    stripped_perf = stripped.get("performance")
    parent_perf = dict(parent).get("performance")
    if isinstance(stripped_perf, dict) and isinstance(parent_perf, dict):
        stripped_perf["persistent_path_cache"] = copy.deepcopy(
            parent_perf.get("persistent_path_cache", {}))
    for key in (
        "v24916_release_identity", "v24916_flowbundle_skim_runtime",
        "demand_evidence_targeting", "v24916_fresh_baseline",
        "v24916_fresh_baseline_runtime_hash", "v24916_flowbundle_skim_runtime_hash",
        "v24916_demand_evidence_targeting_hash", "v24916_parallel_isolation",
        "v24916_parallel_isolation_hash",
    ):
        stripped.pop(key, None)
    if stripped != dict(parent):
        raise RuntimeError("V24916_FRESH0_ISOLATED_PARENT_REVIEWED_CONFIG_WAS_MODIFIED")

    isolation = child.get("v24916_parallel_isolation", {}) or {}
    required = {
        "accepted_count_start": 0,
        "outer_cycle_start": 1,
        "prior_lineage_resumed": False,
        "shared_project_lock_allowed": False,
        "shared_runs_root_allowed": False,
        "shared_path_cache_root_allowed": False,
        "cross_run_cache_restore_allowed": False,
        "legacy_cache_import_allowed": False,
        "external_cache_read_allowed": False,
        "persistent_path_cache_enabled": False,
        "persistent_path_cache_reads_allowed": False,
        "persistent_path_cache_writes_allowed": False,
        "fresh_path_enumeration_required": True,
        "within_run_path_basis_reuse_allowed": True,
    }
    for key, expected_value in required.items():
        if isolation.get(key) != expected_value:
            raise RuntimeError("V24916_FRESH0_ISOLATED_POLICY_DRIFT:" + key)

    safety = build_safety_contract(child)
    return {
        "schema": "R1_15A2_V24916_FRESH0_ISOLATED_CONFIG_DELTA_AUDIT_V1",
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "accepted_count_start": 0,
        "outer_cycle_start": 1,
        "parent_reviewed_config_unchanged": True,
        "generation_targeting_enabled": True,
        "td_mask_enabled": True,
        "supply_targeting_enabled": False,
        "parallel_isolation_enabled": True,
        "external_cache_read_allowed": False,
        "persistent_path_cache_enabled": False,
        "persistent_path_cache_reads_allowed": False,
        "persistent_path_cache_writes_allowed": False,
        "cross_run_cache_restore_allowed": False,
        "within_run_path_basis_reuse_allowed": True,
        "safety_contract_hash": safety.contract_hash,
    }


__all__ = [
    "RELEASE", "PACKAGE_REVISION", "AUTHORITY_FILE", "ISOLATION_SCHEMA",
    "SOURCE_SEMANTIC_POLICY", "EXPECTED_BASELINE_SEMANTIC_STATE_HASH", "WORKSPACE_NAME",
    "RUNS_ROOT_NAME", "LOCK_NAME", "PRIVATE_CACHE_DIRNAME", "apply_active_runtime_delta",
    "validate_active_runtime_delta",
]
