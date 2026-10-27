# -*- coding: utf-8 -*-
"""Fail-closed safety contract for V24915 PERF1 exact-safe acceleration."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import r1_15a2_runtime_v1 as rt
import r1_15a2_safety_v24915 as parent_safety
from r1_15a2_supply import SupplyContractError

RELEASE = "R1_15A2_V2_4_9_15_PERF1_EXACT_SAFE_ACCELERATION_20261019"
PARENT_RELEASE = parent_safety.RELEASE
PARENT_CONFIG_FILE = "R1_15A2_CONFIG_V2_4_9_15.json"
PARENT_CONFIG_SHA256 = "ef5669db1db24041499896c307fb05b548084334ad1a037f3650f641f6996be3"
CONTRACT_FILE = "V24915_PERF1_EXACT_SAFE_ACCELERATION_CONTRACT.json"
CONTRACT_SHA256 = "d74dc335cf3d43414527bc1beb6bbfeb1d4cfcbee400e10c68e59c09b9495375"
RUNTIME_MANIFEST_FILE = "V24915_PERF1_RUNTIME_BUNDLE_MANIFEST.json"
RUNTIME_MANIFEST_SHA256 = "a37ba6c3b436400d588f94c27a1001c677f4b53107dd2cb1e1ed69730f51ebd9"
PACKAGE_REVISION = "V24915_PERF1_EXACT_SAFE_ACCELERATION_R1"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parent(root: Path) -> Mapping[str, Any]:
    path = root / PARENT_CONFIG_FILE
    _require(path.is_file(), "V24915P1_PARENT_CONFIG_MISSING")
    _require(rt.sha256_file(path) == PARENT_CONFIG_SHA256,
             "V24915P1_PARENT_CONFIG_HASH_MISMATCH")
    cfg = rt.read_json(path)
    _require(cfg.get("release") == PARENT_RELEASE,
             "V24915P1_PARENT_RELEASE_MISMATCH")
    return cfg


def _expected_perf1() -> Mapping[str, Any]:
    return {
        "schema": "R1_15A2_V24915_PERF1_CONFIG_V1",
        "parent_release": PARENT_RELEASE,
        "calibration_math_changed": False,
        "phase_specific_procseq": {
            "enabled": True,
            "fallback_to_full": True,
            "preserve_active_groups": True,
            "safe_pre_td_skip_operation_types": [45, 75],
            "safe_post_assignment_skip_positions": [],
            "safe_post_assignment_operations": [{
                "position": 21, "operation_type": 65,
                "text_contains_any": ["12C", "COUNTLOCATION", "GEH", "COLOR"],
            }],
            "generation_plan": "ORIGINAL_ACTIVE_PREFIX_THROUGH_APPROVED_ASSIGNMENT",
            "td_plan": "FIRST_ACTIVE_TD_THROUGH_APPROVED_ASSIGNMENT",
            "supply_plan": "APPROVED_PRT_ASSIGNMENT_PLUS_ACTIVE_GROUPS",
        },
        "rollback_diagnostic_reuse": {
            "enabled": True,
            "expected_profiles": 498,
            "absolute_tolerance": 1e-6,
            "relative_tolerance": 1e-10,
            "max_reported_mismatches": 30,
            "fallback_to_full_diagnostics": True,
            "d12_proof": "498_PROFILE_12_PASSENGER_DSEG_DIRECTED_AP_BULK_SIGNATURE",
            "d11_proof": "EXACT_SEMANTIC_SNAPSHOT_INCLUDING_ALL_DEMAND_MATRIX_HASHES",
        },
        "duplicate_effective_candidate_elimination": {
            "enabled": True,
            "scope": "CANDIDATES_FROM_SAME_ACCEPTED_PARENT_ONLY",
            "identity": "EXACT_PARAMETER_WRITE_SIGNATURE",
            "candidate_order_changed": False,
        },
    }


def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    parent = copy.deepcopy(dict(_parent(root)))
    child = copy.deepcopy(dict(cfg))
    allowed = {
        "version", "release", "safety_gate_release", "package_revision",
        "runtime_bundle_manifest", "runtime_bundle_manifest_sha256",
        "guard_contract_file", "guard_contract_sha256", "implementation_files",
        "implementation_hash", "performance", "trial_calibration", "methodology",
        "config_path", "config_sha256",
    }
    for key, value in parent.items():
        if key in allowed:
            continue
        _require(key in child and _canonical(child[key]) == _canonical(value),
                 "V24915P1_UNREVIEWED_CONFIG_DRIFT:" + key)

    pperf = copy.deepcopy(parent.get("performance", {}))
    cperf = copy.deepcopy(child.get("performance", {}))
    _require(_canonical(cperf.pop("v24915_perf1", None)) ==
             _canonical(_expected_perf1()), "V24915P1_PERF_CONFIG_DRIFT")
    cperf["release"] = pperf.get("release")
    pcompat = pperf.get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    ccompat = cperf.get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    ccompat["target_release"] = pcompat.get("target_release")
    ccompat["predecessors"] = [
        row for row in ccompat.get("predecessors", [])
        if row.get("source_release") != PARENT_RELEASE
    ]
    _require(_canonical(cperf) == _canonical(pperf),
             "V24915P1_UNREVIEWED_PERFORMANCE_DRIFT")

    ptrial = copy.deepcopy(parent.get("trial_calibration", {}))
    ctrial = copy.deepcopy(child.get("trial_calibration", {}))
    feature = ctrial.pop("v24915_perf1_exact_safe_acceleration", None)
    _require(feature == {
        "phase_specific_procseq": True,
        "rollback_diagnostic_reuse_with_full_fallback": True,
        "duplicate_effective_candidate_elimination": True,
        "candidate_parallelism": False,
        "assignment_method_changed": False,
        "acceptance_changed": False,
    }, "V24915P1_TRIAL_FEATURE_CONTRACT_DRIFT")
    _require(_canonical(ctrial) == _canonical(ptrial),
             "V24915P1_UNREVIEWED_TRIAL_DRIFT")

    pmethod = copy.deepcopy(parent.get("methodology", {}))
    cmethod = copy.deepcopy(child.get("methodology", {}))
    note = cmethod.pop("v24915_perf1_exact_safe_acceleration", None)
    _require(note ==
             "ORCHESTRATION_ONLY; EVERY OPTIMIZED PATH HAS AN EXACT PROOF OR USES THE ORIGINAL FULL FALLBACK",
             "V24915P1_METHODOLOGY_NOTE_DRIFT")
    _require(_canonical(cmethod) == _canonical(pmethod),
             "V24915P1_UNREVIEWED_METHODOLOGY_DRIFT")


def preflight_v24915p1_deployment_files(package_root=None) -> Mapping[str, Any]:
    root = (Path(package_root).resolve() if package_root is not None
            else Path(__file__).resolve().parent)
    manifest_path = root / RUNTIME_MANIFEST_FILE
    _require(manifest_path.is_file(), "V24915P1_RUNTIME_MANIFEST_MISSING")
    _require(rt.sha256_file(manifest_path) == RUNTIME_MANIFEST_SHA256,
             "V24915P1_RUNTIME_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(manifest_path)
    _require(manifest.get("schema") ==
             "R1_15A2_V24915_PERF1_RUNTIME_BUNDLE_MANIFEST_V1",
             "V24915P1_RUNTIME_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE,
             "V24915P1_RUNTIME_MANIFEST_RELEASE_MISMATCH")
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
    _require(not failures, "V24915P1_RUNTIME_BUNDLE_INVALID:" +
             json.dumps(failures, sort_keys=True))
    return {
        "passes": True, "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "manifest_path": str(manifest_path),
        "manifest_sha256": RUNTIME_MANIFEST_SHA256,
        "files_checked": checked, "failures": [],
    }


def validate_v24915p1_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = (Path(package_root).resolve() if package_root is not None
            else Path(__file__).resolve().parent)
    _validate_reviewed_delta(cfg, root)
    _require(cfg.get("release") == RELEASE and
             cfg.get("safety_gate_release") == RELEASE,
             "V24915P1_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") == "2.4.9.15-perf1-exact-safe-acceleration",
             "V24915P1_VERSION_IDENTITY_MISSING")
    _require(cfg.get("package_revision") == PACKAGE_REVISION,
             "V24915P1_PACKAGE_REVISION_MISSING")
    _require(cfg.get("runtime_bundle_manifest") == RUNTIME_MANIFEST_FILE and
             cfg.get("runtime_bundle_manifest_sha256") == RUNTIME_MANIFEST_SHA256,
             "V24915P1_RUNTIME_MANIFEST_NOT_PINNED")
    contract = root / CONTRACT_FILE
    _require(contract.is_file() and rt.sha256_file(contract) == CONTRACT_SHA256,
             "V24915P1_CONTRACT_HASH_MISMATCH")
    _require(cfg.get("guard_contract_file") == CONTRACT_FILE and
             cfg.get("guard_contract_sha256") == CONTRACT_SHA256,
             "V24915P1_CONTRACT_NOT_PINNED")

    # Parent deployment remains independently verifiable and byte-identical.
    parent_preflight = parent_safety.preflight_v24915_deployment_files(root)
    _require(parent_preflight.get("passes") is True,
             "V24915P1_PARENT_DEPLOYMENT_NOT_INTACT")

    # Calibration policy and thresholds are inherited exactly.
    parent = _parent(root)
    for key in (
        "demand_continuation", "supply", "supply_route_choice_acceptance",
        "supply_route_choice_readiness", "early_exploration_acceptance",
        "geh20_transition_policy", "coupled_demand", "restart_authority",
        "shared_objective", "td", "generation", "acceptance",
    ):
        _require(_canonical(cfg.get(key)) == _canonical(parent.get(key)),
                 "V24915P1_CALIBRATION_POLICY_DRIFT:" + key)
    parent_safety._validate_retry_policy(cfg)

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V24915P1_CACHE_TARGET_RELEASE_MISMATCH")
    rows = [row for row in compat.get("predecessors", [])
            if row.get("source_release") == PARENT_RELEASE]
    _require(len(rows) == 1 and rows[0].get("source_config_sha256s") ==
             [PARENT_CONFIG_SHA256], "V24915P1_PARENT_CACHE_PROVENANCE_MISSING")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF1.py",
        "r1_15a2_safety_v24915p1.py",
        "r1_15a2_acceleration_v24915p1.py",
        "r1_15a2_trial_adapter_v24915p1.py",
        "r1_15a2_inplace_transaction_v24915p1.py",
        "r1_15a2_overnight_controller_v24915p1.py",
        "r1_15a2_overnight_controller_coupled_v24915p1.py",
        "r1_15a2_supply_handoff_v24915p1.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V24915P1_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V24915P1_IMPLEMENTATION_HASH_MISMATCH:" + name)
    return {
        "passes": True,
        "release": RELEASE,
        "parent_release": PARENT_RELEASE,
        "parent_config_sha256": PARENT_CONFIG_SHA256,
        "calibration_math_changed": False,
        "assignment_method_changed": False,
        "acceptance_changed": False,
        "phase_specific_procseq": True,
        "rollback_diagnostic_reuse_with_full_fallback": True,
        "duplicate_effective_candidate_elimination": True,
        "real_visum_tested": False,
        "production_ready": False,
    }


def validate_v24915p1_runtime_bundle(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = (Path(package_root).resolve() if package_root is not None
            else Path(__file__).resolve().parent)
    deployment = preflight_v24915p1_deployment_files(root)
    config = validate_v24915p1_config(cfg, root)
    mixed = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("r1_15a2_") or module is None:
            continue
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().parent != root:
            mixed.append({"module": name, "file": str(Path(filename).resolve())})
    _require(not mixed, "V24915P1_MIXED_RELEASE_MODULES:" +
             json.dumps(mixed, sort_keys=True))
    return {
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "files_checked": deployment["files_checked"],
        "mixed_release_modules": [],
        "parent_deployment_intact": True,
        "config_validation": config,
        "real_visum_tested": False,
        "production_ready": False,
    }


__all__ = [
    "RELEASE", "PARENT_RELEASE", "PARENT_CONFIG_SHA256", "CONTRACT_FILE",
    "CONTRACT_SHA256", "RUNTIME_MANIFEST_FILE", "RUNTIME_MANIFEST_SHA256",
    "PACKAGE_REVISION", "preflight_v24915p1_deployment_files",
    "validate_v24915p1_config", "validate_v24915p1_runtime_bundle",
]
