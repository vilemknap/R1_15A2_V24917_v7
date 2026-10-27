# -*- coding: utf-8 -*-
"""Fail-closed V2.4.9.15 COM-busy retry and safe-finalizer contract."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_supply import SupplyContractError, SupplyPolicy
import r1_15a2_runtime_v1 as rt
import r1_15a2_core as core
import r1_15a2_com_compat as com
import r1_15a2_overnight_controller_v242 as coupled
import r1_15a2_demand_continuation_v24914 as continuation
from r1_15a2_restart_v2494 import SCHEMA as RESTART_SCHEMA, SEMANTIC_FIELDS, RAW_VER_SHA_ROLE

RELEASE = "R1_15A2_V2_4_9_15_COM_BUSY_RETRY_SAFE_FINALIZER_20261019"
PARENT_RELEASE = "R1_15A2_V2_4_9_14_DEMAND_CONTINUATION_SUPPLY_READY_20261019"
PARENT_CONFIG_SHA256 = "0978519bed11bb9330d6d28bc4f5b6db0fe9e714e2d6b100499e7c641eadbade"
CONTRACT_FILE = "V24915_COM_BUSY_RETRY_SAFE_FINALIZER_CONTRACT.json"
CONTRACT_SHA256 = "aa3d8d27a3d04dab505d182d457fac70c44881aff11ed145dbacddb5027b5610"
CONTINUATION_AUTHORITY_FILE = "V24914_DEMAND_CONTINUATION_AUTHORITY.json"
CONTINUATION_AUTHORITY_SHA256 = "cc72705ea1e7618c3fbea3699cd3fe16b712ba9d2ef0407a0abded45a995ad29"
RUNTIME_MANIFEST_FILE = "V24915_RUNTIME_BUNDLE_MANIFEST.json"
RUNTIME_MANIFEST_SHA256 = "c8a388f7d2bbf9e8e427d7547f38e3ec5f5463c3caa87880d466d2d0a04fe615"
PACKAGE_REVISION = "V24915_COM_BUSY_RETRY_SAFE_FINALIZER_R1"
PARENT_PATH_IMPLEMENTATION_FILES = {'r1_15a2_two_mode_v238.py': '3722fabe5b90f7bb0367f840d466c3a6c9de6a6ddb483dda0ec7db8eed6c3d8a', 'r1_15a2_trial_adapter_v240.py': 'e0216130f66af3adaddbc6108945207d19b0af9e982747a27f95f36e0cad4015', 'r1_15a2_persistent_path_cache_v248.py': '78522a1a9d7bd4bcabfb360604fd9c0a6d3415e0d845d935e7c3084aeedb276c', 'r1_15a2_sequence_v23.py': '7116d9cedd4bcfe018873fd464055866e8b3783aeab718e52845d34661def3da', 'r1_15a2_supply.py': '9af418d483edffe2e22c931443adb2e33e5960508d04c343e0a386c47a2a103a', 'r1_15a2_core.py': 'f817aa114eae5a924116b8f73f7d3f22ae6b26742942b74d189a3d75bf6e30ed', 'r1_15a2_runtime_v1.py': 'ae9dba5c3c2925cc16d0e42f1c8b695ffa460bf0e3fd672ed0a41434d8b5cc62'}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parent(root: Path) -> Mapping[str, Any]:
    path = root / "R1_15A2_CONFIG_V2_4_9_14.json"
    _require(path.is_file(), "V24915_BUNDLED_V24914_CONFIG_MISSING")
    _require(rt.sha256_file(path) == PARENT_CONFIG_SHA256,
             "V24915_BUNDLED_V24914_CONFIG_HASH_MISMATCH")
    obj = rt.read_json(path)
    _require(obj.get("release") == PARENT_RELEASE, "V24915_PARENT_RELEASE_MISMATCH")
    return obj


def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    parent = copy.deepcopy(dict(_parent(root)))
    child = copy.deepcopy(dict(cfg))
    allowed = {
        "version", "release", "safety_gate_release", "package_revision",
        "runtime_bundle_manifest", "runtime_bundle_manifest_sha256",
        "guard_contract_file", "guard_contract_sha256", "implementation_files",
        "performance", "trial_calibration", "methodology", "com_resilience",
    }
    for key, value in parent.items():
        if key in allowed:
            continue
        _require(key in child and _canonical(child[key]) == _canonical(value),
                 "V24915_UNREVIEWED_CONFIG_DRIFT:" + key)

    pperf = copy.deepcopy(parent.get("performance", {}))
    cperf = copy.deepcopy(child.get("performance", {}))
    pcompat = pperf.get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    ccompat = cperf.get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    ccompat["target_release"] = pcompat.get("target_release")
    ccompat["predecessors"] = [
        r for r in ccompat.get("predecessors", [])
        if r.get("source_release") != PARENT_RELEASE
    ]
    _require(_canonical(pperf) == _canonical(cperf),
             "V24915_UNREVIEWED_PERFORMANCE_DRIFT")

    ptrial = copy.deepcopy(parent.get("trial_calibration", {}))
    ctrial = copy.deepcopy(child.get("trial_calibration", {}))
    ctrial.pop("v24915_com_busy_retry_safe_finalizer", None)
    _require(_canonical(ptrial) == _canonical(ctrial),
             "V24915_UNREVIEWED_TRIAL_DRIFT")

    pmethod = copy.deepcopy(parent.get("methodology", {}))
    cmethod = copy.deepcopy(child.get("methodology", {}))
    cmethod.pop("v24915_com_busy_retry_safe_finalizer", None)
    _require(_canonical(pmethod) == _canonical(cmethod),
             "V24915_UNREVIEWED_METHODOLOGY_DRIFT")

    pcom = copy.deepcopy(parent.get("com_resilience", {}))
    ccom = copy.deepcopy(child.get("com_resilience", {}))
    ccom.pop("scoped_policies", None)
    _require(_canonical(pcom) == _canonical(ccom),
             "V24915_GENERIC_COM_POLICY_DRIFT")


def preflight_v24915_deployment_files(package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    manifest_path = root / RUNTIME_MANIFEST_FILE
    _require(manifest_path.is_file(), "V24915_RUNTIME_MANIFEST_MISSING")
    _require(rt.sha256_file(manifest_path) == RUNTIME_MANIFEST_SHA256,
             "V24915_RUNTIME_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(manifest_path)
    _require(manifest.get("schema") == "R1_15A2_V24915_RUNTIME_BUNDLE_MANIFEST_V1",
             "V24915_RUNTIME_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE,
             "V24915_RUNTIME_MANIFEST_RELEASE_MISMATCH")
    failures = []
    checked = 0
    for row in manifest.get("files", []):
        rel = str(row.get("path", ""))
        path = root / rel
        if not rel or not path.is_file():
            failures.append({"path": rel, "reason": "MISSING"})
            continue
        checked += 1
        if int(path.stat().st_size) != int(row.get("size", -1)):
            failures.append({"path": rel, "reason": "SIZE_MISMATCH"})
            continue
        if rt.sha256_file(path) != row.get("sha256"):
            failures.append({"path": rel, "reason": "SHA256_MISMATCH"})
    _require(not failures, "V24915_RUNTIME_BUNDLE_INVALID:" +
             json.dumps(failures, sort_keys=True))
    return {
        "passes": True, "release": RELEASE, "package_revision": PACKAGE_REVISION,
        "manifest_path": str(manifest_path), "manifest_sha256": RUNTIME_MANIFEST_SHA256,
        "files_checked": checked, "failures": [],
    }


def _validate_retry_policy(cfg: Mapping[str, Any]) -> Mapping[str, Any]:
    policy = cfg.get("com_resilience", {}) or {}
    _require(com.com_retry_settings(policy) == (5, 0.05, 2.0, 0.8),
             "V24915_GENERIC_COM_RETRY_CHANGED")
    p = com.com_retry_budget_settings(policy, "bounded_path_export")
    f = com.com_retry_budget_settings(policy, "final_verification")
    _require(p == (48, 0.25, 1.7, 3.0, 120.0),
             "V24915_PATH_EXPORT_RETRY_POLICY_CHANGED")
    _require(f == (12, 0.25, 1.8, 3.0, 30.0),
             "V24915_FINAL_VERIFICATION_RETRY_POLICY_CHANGED")
    _require(policy.get("retry_scope") ==
             "TRANSIENT_RPC_CALL_REJECTED_OR_RETRY_LATER_ONLY",
             "V24915_RETRY_ELIGIBILITY_CHANGED")
    _require(policy.get("bounded_path_export_same_range_required") is True and
             policy.get("page_size_fallback_policy") ==
             "NONTRANSIENT_MEMORY_OR_RANGE_ERRORS_ONLY",
             "V24915_PATH_RANGE_OR_FALLBACK_POLICY_CHANGED")
    return {
        "generic": list(com.com_retry_settings(policy)),
        "bounded_path_export": list(p), "final_verification": list(f),
    }


def validate_v24915_runtime_bundle(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    deployment = preflight_v24915_deployment_files(root)
    mixed = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("r1_15a2_") or module is None:
            continue
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().parent != root:
            mixed.append({"module": name, "file": str(Path(filename).resolve())})
    _require(not mixed, "V24915_MIXED_RELEASE_MODULES:" + json.dumps(mixed, sort_keys=True))

    retry = _validate_retry_policy(cfg)
    authority = continuation.load_authority(root)
    _require(authority.get("authority_sha256") == CONTINUATION_AUTHORITY_SHA256,
             "V24915_CONTINUATION_AUTHORITY_RUNTIME_HASH_MISMATCH")
    runtime_descriptor = {
        "enabled": True, "accepted_count": 9, "next_outer_cycle": 6,
        "inherited_outer_cycles": 5, "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 0, "max_lineage_outer_cycle": 12,
        "bounded_inner_budget_stop_reasons": list(
            continuation.BOUNDED_INNER_BUDGET_STOP_REASONS),
    }
    validated = coupled._runtime_demand_continuation(
        {"runtime_demand_continuation": runtime_descriptor})
    _require(validated.get("next_outer_cycle") == 6 and
             validated.get("accepted_count") == 9,
             "V24915_CONTINUATION_RUNTIME_SMOKE_FAILED")
    smoke_cfg = copy.deepcopy(dict(cfg))
    smoke_cfg["runtime_acceptance_supply_cycle"] = 1
    smoke_cfg["runtime_acceptance_scope"] = "SUPPLY_ADDVAL1"
    policy = core.early_exploration_policy(smoke_cfg, "SUPPLY_ADDVAL1")
    _require(policy is not None and policy.get("scope") == "SUPPLY",
             "V24915_INHERITED_SUPPLY_POLICY_NOT_ACTIVE")
    supply_policy = SupplyPolicy.from_config(smoke_cfg)
    _require(abs(supply_policy.lattice - 0.5) <= 1e-12 and
             abs(supply_policy.max_step - 8.0) <= 1e-12,
             "V24915_INHERITED_SUPPLY_LIMITS_LOST")
    return {
        "passes": True, "release": RELEASE, "package_revision": PACKAGE_REVISION,
        "files_checked": deployment["files_checked"], "mixed_release_modules": [],
        "continuation_authority_sha256": CONTINUATION_AUTHORITY_SHA256,
        "continuation_start_outer_cycle": 6, "continuation_accepted_count": 9,
        "retry_policy": retry, "safe_transient_finalizer": True,
        "supply_policy_preserved": True,
    }


def validate_v24915_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    _validate_reviewed_delta(cfg, root)
    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V24915_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") == "2.4.9.15-com-busy-retry-safe-finalizer",
             "V24915_VERSION_IDENTITY_MISSING")
    _require(cfg.get("package_revision") == PACKAGE_REVISION,
             "V24915_PACKAGE_REVISION_MISSING")
    _require(cfg.get("runtime_bundle_manifest") == RUNTIME_MANIFEST_FILE and
             cfg.get("runtime_bundle_manifest_sha256") == RUNTIME_MANIFEST_SHA256,
             "V24915_RUNTIME_MANIFEST_NOT_PINNED")
    contract = root / CONTRACT_FILE
    _require(contract.is_file() and rt.sha256_file(contract) == CONTRACT_SHA256,
             "V24915_CONTRACT_HASH_MISMATCH")
    _require(cfg.get("guard_contract_file") == CONTRACT_FILE and
             cfg.get("guard_contract_sha256") == CONTRACT_SHA256,
             "V24915_CONTRACT_NOT_PINNED")
    authority_path = root / CONTINUATION_AUTHORITY_FILE
    _require(authority_path.is_file() and
             rt.sha256_file(authority_path) == CONTINUATION_AUTHORITY_SHA256,
             "V24915_CONTINUATION_AUTHORITY_HASH_MISMATCH")

    parent = _parent(root)
    for key in ("demand_continuation", "supply", "supply_route_choice_acceptance",
                "supply_route_choice_readiness", "early_exploration_acceptance",
                "geh20_transition_policy", "coupled_demand", "restart_authority"):
        _require(_canonical(cfg.get(key)) == _canonical(parent.get(key)),
                 "V24915_PARENT_POLICY_DRIFT:" + key)
    restart = cfg.get("restart_authority", {}) or {}
    _require(restart.get("mode") == "SEMANTIC_MODEL_STATE" and
             restart.get("schema") == RESTART_SCHEMA and
             restart.get("semantic_fields") == list(SEMANTIC_FIELDS) and
             restart.get("raw_ver_sha_role") == RAW_VER_SHA_ROLE and
             restart.get("raw_ver_sha_used_for_restart_acceptance") is False,
             "V24915_SEMANTIC_RESTART_CONTRACT_LOST")
    retry = _validate_retry_policy(cfg)

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V24915_CACHE_COMPAT_TARGET_CHANGED")
    rows = [r for r in compat.get("predecessors", [])
            if r.get("source_release") == PARENT_RELEASE]
    _require(len(rows) == 1 and rows[0].get("source_config_sha256s") ==
             [PARENT_CONFIG_SHA256], "V24915_V24914_PROVENANCE_NOT_PINNED")
    _require(rows[0].get("source_path_implementation_files") ==
             PARENT_PATH_IMPLEMENTATION_FILES,
             "V24915_V24914_PATH_PROVENANCE_CHANGED")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15.py", "R1_15A2_SUPPLY_FROM_CONVERGED_DEMAND_V2_4_9_15.py", "r1_15a2_safety_v24915.py",
        "r1_15a2_demand_continuation_v24914.py", "r1_15a2_com_compat.py",
        "r1_15a2_two_mode_v238.py", "r1_15a2_runtime_v1.py",
        "r1_15a2_overnight_controller_v240.py", "r1_15a2_overnight_controller_v242.py",
        "r1_15a2_finecdf_bridge_v242.py", "r1_15a2_supply_handoff_v24913.py",
        "r1_15a2_core.py", "r1_15a2_supply.py", "r1_15a2_sequence_v23.py",
        "r1_15a2_trial_adapter_v240.py", "r1_15a2_supply_visum.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V24915_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V24915_IMPLEMENTATION_HASH_MISMATCH:" + name)
    return {
        "passes": True, "parent_release": PARENT_RELEASE,
        "continuation_source": "V24912_A0009", "accepted_count_start": 9,
        "next_outer_cycle": 6, "max_lineage_outer_cycle": 12,
        "retry_policy": retry, "safe_transient_finalizer": True,
        "calibration_math_changed": False, "supply_policy_preserved": True,
        "real_visum_tested": False, "production_ready": False,
    }


__all__ = [
    "RELEASE", "PARENT_RELEASE", "PARENT_CONFIG_SHA256", "CONTRACT_FILE",
    "CONTRACT_SHA256", "CONTINUATION_AUTHORITY_FILE",
    "CONTINUATION_AUTHORITY_SHA256", "RUNTIME_MANIFEST_FILE",
    "RUNTIME_MANIFEST_SHA256", "PACKAGE_REVISION", "PARENT_PATH_IMPLEMENTATION_FILES",
    "preflight_v24915_deployment_files", "validate_v24915_config",
    "validate_v24915_runtime_bundle",
]
