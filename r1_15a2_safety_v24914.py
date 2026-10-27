# -*- coding: utf-8 -*-
"""Fail-closed V2.4.9.14 demand-continuation and supply-readiness contract."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_supply import SupplyContractError, SupplyPolicy
import r1_15a2_runtime_v1 as rt
import r1_15a2_core as core
import r1_15a2_overnight_controller_v242 as coupled
import r1_15a2_demand_continuation_v24914 as continuation
from r1_15a2_restart_v2494 import SCHEMA as RESTART_SCHEMA, SEMANTIC_FIELDS, RAW_VER_SHA_ROLE

RELEASE = "R1_15A2_V2_4_9_14_DEMAND_CONTINUATION_SUPPLY_READY_20261019"
PARENT_RELEASE = "R1_15A2_V2_4_9_13_SUPPLY_ROUTE_CHOICE_READINESS_20261019"
PARENT_CONFIG_SHA256 = "508c4e13e91832239391dda52b8a4afd1cad98441c7fdea84cb1d70d5a8d1a88"
CONTRACT_FILE = "V24914_DEMAND_CONTINUATION_CONTRACT.json"
CONTRACT_SHA256 = "eca1a7941fae2246bebdd7a9be2fdb8c61ea4acbed6db68a38faa31192ba6b6b"
CONTINUATION_AUTHORITY_FILE = "V24914_DEMAND_CONTINUATION_AUTHORITY.json"
CONTINUATION_AUTHORITY_SHA256 = "cc72705ea1e7618c3fbea3699cd3fe16b712ba9d2ef0407a0abded45a995ad29"
RUNTIME_MANIFEST_FILE = "V24914_RUNTIME_BUNDLE_MANIFEST.json"
RUNTIME_MANIFEST_SHA256 = "a74113f77d5ab523ed8f4058467d5edbcddab9486214a292fea7a86fa48c8b24"
PACKAGE_REVISION = "V24914_DEMAND_CONTINUATION_R1"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parent(root: Path) -> Mapping[str, Any]:
    path = root / "R1_15A2_CONFIG_V2_4_9_13.json"
    _require(path.is_file(), "V24914_BUNDLED_V24913_CONFIG_MISSING")
    _require(rt.sha256_file(path) == PARENT_CONFIG_SHA256,
             "V24914_BUNDLED_V24913_CONFIG_HASH_MISMATCH")
    obj = rt.read_json(path)
    _require(obj.get("release") == PARENT_RELEASE, "V24914_PARENT_RELEASE_MISMATCH")
    return obj


def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    parent = copy.deepcopy(dict(_parent(root)))
    child = copy.deepcopy(dict(cfg))
    allowed = {
        "version", "release", "safety_gate_release", "package_revision",
        "runtime_bundle_manifest", "runtime_bundle_manifest_sha256",
        "guard_contract_file", "guard_contract_sha256", "implementation_files",
        "demand_continuation", "performance", "trial_calibration", "methodology",
    }
    for key, value in parent.items():
        if key in allowed:
            continue
        _require(key in child and _canonical(child[key]) == _canonical(value),
                 "V24914_UNREVIEWED_CONFIG_DRIFT:" + key)

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
             "V24914_UNREVIEWED_PERFORMANCE_DRIFT")

    ptrial = copy.deepcopy(parent.get("trial_calibration", {}))
    ctrial = copy.deepcopy(child.get("trial_calibration", {}))
    ctrial.pop("v24914_demand_continuation", None)
    _require(_canonical(ptrial) == _canonical(ctrial),
             "V24914_UNREVIEWED_TRIAL_DRIFT")

    pmethod = copy.deepcopy(parent.get("methodology", {}))
    cmethod = copy.deepcopy(child.get("methodology", {}))
    cmethod.pop("v24914_demand_continuation", None)
    _require(_canonical(pmethod) == _canonical(cmethod),
             "V24914_UNREVIEWED_METHODOLOGY_DRIFT")


def preflight_v24914_deployment_files(package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    manifest_path = root / RUNTIME_MANIFEST_FILE
    _require(manifest_path.is_file(), "V24914_RUNTIME_MANIFEST_MISSING")
    _require(rt.sha256_file(manifest_path) == RUNTIME_MANIFEST_SHA256,
             "V24914_RUNTIME_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(manifest_path)
    _require(manifest.get("schema") == "R1_15A2_V24914_RUNTIME_BUNDLE_MANIFEST_V1",
             "V24914_RUNTIME_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE,
             "V24914_RUNTIME_MANIFEST_RELEASE_MISMATCH")
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
    _require(not failures, "V24914_RUNTIME_BUNDLE_INVALID:" +
             json.dumps(failures, sort_keys=True))
    return {
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "manifest_path": str(manifest_path),
        "manifest_sha256": RUNTIME_MANIFEST_SHA256,
        "files_checked": checked,
        "failures": [],
    }


def validate_v24914_runtime_bundle(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    deployment = preflight_v24914_deployment_files(root)
    mixed = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("r1_15a2_") or module is None:
            continue
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().parent != root:
            mixed.append({"module": name, "file": str(Path(filename).resolve())})
    _require(not mixed, "V24914_MIXED_RELEASE_MODULES:" + json.dumps(mixed, sort_keys=True))

    authority = continuation.load_authority(root)
    _require(authority.get("authority_sha256") == CONTINUATION_AUTHORITY_SHA256,
             "V24914_CONTINUATION_AUTHORITY_RUNTIME_HASH_MISMATCH")
    runtime_descriptor = {
        "enabled": True,
        "accepted_count": 9,
        "next_outer_cycle": 6,
        "inherited_outer_cycles": 5,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 0,
        "max_lineage_outer_cycle": 12,
        "bounded_inner_budget_stop_reasons": list(
            continuation.BOUNDED_INNER_BUDGET_STOP_REASONS),
    }
    validated = coupled._runtime_demand_continuation(
        {"runtime_demand_continuation": runtime_descriptor})
    _require(validated.get("next_outer_cycle") == 6 and
             validated.get("accepted_count") == 9,
             "V24914_CONTINUATION_RUNTIME_SMOKE_FAILED")
    for reason in continuation.BOUNDED_INNER_BUDGET_STOP_REASONS:
        _require(coupled._bounded_inner_budget_stop({"stop_reason": reason}) is True,
                 "V24914_BOUNDED_REASON_NOT_ACTIVE:" + reason)
    for unsafe in ("GLOBAL_USERSTOPREQUESTED", "GLOBAL_TIMEBUDGETREACHED",
                   "TD_USER_STOP_FILE", "COM_ERROR", "ROLLBACK_FAILED"):
        _require(coupled._bounded_inner_budget_stop({"stop_reason": unsafe}) is False,
                 "V24914_UNSAFE_REASON_WOULD_CONTINUE:" + unsafe)

    smoke_cfg = copy.deepcopy(dict(cfg))
    smoke_cfg["runtime_acceptance_supply_cycle"] = 1
    smoke_cfg["runtime_acceptance_scope"] = "SUPPLY_ADDVAL1"
    policy = core.early_exploration_policy(smoke_cfg, "SUPPLY_ADDVAL1")
    _require(policy is not None and policy.get("scope") == "SUPPLY",
             "V24914_INHERITED_SUPPLY_POLICY_NOT_ACTIVE")
    supply_policy = SupplyPolicy.from_config(smoke_cfg)
    _require(abs(supply_policy.lattice - 0.5) <= 1e-12 and
             abs(supply_policy.max_step - 8.0) <= 1e-12,
             "V24914_INHERITED_SUPPLY_LIMITS_LOST")
    return {
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "files_checked": deployment["files_checked"],
        "mixed_release_modules": [],
        "continuation_authority_sha256": CONTINUATION_AUTHORITY_SHA256,
        "continuation_start_outer_cycle": 6,
        "continuation_accepted_count": 9,
        "bounded_inner_budget_reasons": list(
            continuation.BOUNDED_INNER_BUDGET_STOP_REASONS),
        "supply_policy_preserved": True,
    }


def validate_v24914_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    _validate_reviewed_delta(cfg, root)
    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V24914_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") == "2.4.9.14-demand-continuation-supply-ready",
             "V24914_VERSION_IDENTITY_MISSING")
    _require(cfg.get("package_revision") == PACKAGE_REVISION,
             "V24914_PACKAGE_REVISION_MISSING")
    _require(cfg.get("runtime_bundle_manifest") == RUNTIME_MANIFEST_FILE and
             cfg.get("runtime_bundle_manifest_sha256") == RUNTIME_MANIFEST_SHA256,
             "V24914_RUNTIME_MANIFEST_NOT_PINNED")

    contract = root / CONTRACT_FILE
    _require(contract.is_file() and rt.sha256_file(contract) == CONTRACT_SHA256,
             "V24914_CONTRACT_HASH_MISMATCH")
    _require(cfg.get("guard_contract_file") == CONTRACT_FILE and
             cfg.get("guard_contract_sha256") == CONTRACT_SHA256,
             "V24914_CONTRACT_NOT_PINNED")
    authority_path = root / CONTINUATION_AUTHORITY_FILE
    _require(authority_path.is_file() and
             rt.sha256_file(authority_path) == CONTINUATION_AUTHORITY_SHA256,
             "V24914_CONTINUATION_AUTHORITY_HASH_MISMATCH")

    d = cfg.get("demand_continuation", {}) or {}
    exact = {
        "enabled": True,
        "mode": "EXACT_SEMANTIC_A0009_LINEAGE_CONTINUATION",
        "authority_file": CONTINUATION_AUTHORITY_FILE,
        "authority_sha256": CONTINUATION_AUTHORITY_SHA256,
        "accepted_count": 9,
        "inherited_outer_cycles": 5,
        "next_outer_cycle": 6,
        "max_lineage_outer_cycle": 12,
        "inherited_stationary_cycle_streak": 0,
        "bounded_budget_counts_as_stationarity": False,
        "continue_bounded_budget_without_accepted_change": True,
    }
    for key, value in exact.items():
        _require(d.get(key) == value, "V24914_CONTINUATION_CONFIG_CHANGED:" + key)
    _require(tuple(d.get("bounded_inner_budget_stop_reasons", ())) ==
             continuation.BOUNDED_INNER_BUDGET_STOP_REASONS,
             "V24914_CONTINUATION_REASON_SET_CHANGED")
    _require(d.get("supply_unlock_criterion") ==
             "TWO_CONSECUTIVE_COMPLETE_SUCCESSFUL_CONFIGURED_TG_TD_SEARCHES_WITH_NO_CHANGE",
             "V24914_SUPPLY_UNLOCK_CRITERION_CHANGED")

    parent = _parent(root)
    for key in ("supply", "supply_route_choice_acceptance", "supply_route_choice_readiness",
                "early_exploration_acceptance", "geh20_transition_policy", "coupled_demand"):
        _require(_canonical(cfg.get(key)) == _canonical(parent.get(key)),
                 "V24914_PARENT_POLICY_DRIFT:" + key)

    restart = cfg.get("restart_authority", {}) or {}
    _require(restart.get("mode") == "SEMANTIC_MODEL_STATE" and
             restart.get("schema") == RESTART_SCHEMA and
             restart.get("semantic_fields") == list(SEMANTIC_FIELDS) and
             restart.get("raw_ver_sha_role") == RAW_VER_SHA_ROLE and
             restart.get("raw_ver_sha_used_for_restart_acceptance") is False,
             "V24914_SEMANTIC_RESTART_CONTRACT_LOST")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V24914_CACHE_COMPAT_TARGET_CHANGED")
    rows = [r for r in compat.get("predecessors", [])
            if r.get("source_release") == PARENT_RELEASE]
    _require(len(rows) == 1 and rows[0].get("source_config_sha256s") ==
             [PARENT_CONFIG_SHA256],
             "V24914_V24913_PROVENANCE_NOT_PINNED")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_14.py",
        "R1_15A2_SUPPLY_FROM_CONVERGED_DEMAND_V2_4_9_14.py",
        "r1_15a2_safety_v24914.py",
        "r1_15a2_demand_continuation_v24914.py",
        "r1_15a2_overnight_controller_v242.py",
        "r1_15a2_finecdf_bridge_v242.py",
        "r1_15a2_supply_handoff_v24913.py",
        "r1_15a2_core.py", "r1_15a2_supply.py", "r1_15a2_sequence_v23.py",
        "r1_15a2_trial_adapter_v240.py", "r1_15a2_supply_visum.py",
        "r1_15a2_runtime_v1.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V24914_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V24914_IMPLEMENTATION_HASH_MISMATCH:" + name)
    return {
        "passes": True,
        "parent_release": PARENT_RELEASE,
        "continuation_source": "V24912_A0009",
        "accepted_count_start": 9,
        "next_outer_cycle": 6,
        "max_lineage_outer_cycle": 12,
        "bounded_inner_budget_policy":
            "CONTINUE_OUTER_LOOP_SUPPLY_LOCKED_NO_STATIONARITY_CREDIT",
        "v24913_supply_policy_preserved": True,
        "real_visum_tested": False,
        "production_ready": False,
    }


__all__ = [
    "RELEASE", "PARENT_RELEASE", "PARENT_CONFIG_SHA256", "CONTRACT_FILE",
    "CONTRACT_SHA256", "CONTINUATION_AUTHORITY_FILE",
    "CONTINUATION_AUTHORITY_SHA256", "RUNTIME_MANIFEST_FILE",
    "RUNTIME_MANIFEST_SHA256", "PACKAGE_REVISION",
    "preflight_v24914_deployment_files", "validate_v24914_config",
    "validate_v24914_runtime_bundle",
]
