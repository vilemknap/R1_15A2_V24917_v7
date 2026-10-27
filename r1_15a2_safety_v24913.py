# -*- coding: utf-8 -*-
"""Fail-closed V2.4.9.13 supply route-choice readiness contract."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_supply import SupplyContractError, SupplyPolicy
import r1_15a2_runtime_v1 as rt
import r1_15a2_core as core
from r1_15a2_restart_v2494 import SCHEMA as RESTART_SCHEMA, SEMANTIC_FIELDS, RAW_VER_SHA_ROLE

RELEASE = "R1_15A2_V2_4_9_13_SUPPLY_ROUTE_CHOICE_READINESS_20261019"
PARENT_RELEASE = "R1_15A2_V2_4_9_12_GUARD_POLICY_REBASE_20261018"
PARENT_CONFIG_SHA256 = "9972a5ce4334b79481ea9bc5c272ca1d5c674c3b2298e841128eafe2b3db4c48"
CONTRACT_FILE = "V24913_SUPPLY_ROUTE_CHOICE_CONTRACT.json"
CONTRACT_SHA256 = "641697f7751002abf2bce2636db1e4762640b45ce37d9d901b63bc7961b1895c"
RUNTIME_MANIFEST_FILE = "V24913_RUNTIME_BUNDLE_MANIFEST.json"
RUNTIME_MANIFEST_SHA256 = "b5b825a9c13c018eb32d01c934f569139674df9340c7cdfde13e5cef56bb4f9d"
PACKAGE_REVISION = "V24913_SUPPLY_READY_R1"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parent(root: Path) -> Mapping[str, Any]:
    path = root / "R1_15A2_CONFIG_V2_4_9_12.json"
    _require(path.is_file(), "V24913_BUNDLED_V24912_CONFIG_MISSING")
    _require(rt.sha256_file(path) == PARENT_CONFIG_SHA256,
             "V24913_BUNDLED_V24912_CONFIG_HASH_MISMATCH")
    obj = rt.read_json(path)
    _require(obj.get("release") == PARENT_RELEASE, "V24913_PARENT_RELEASE_MISMATCH")
    return obj


def _validate_reviewed_delta(cfg: Mapping[str, Any], root: Path) -> None:
    parent = copy.deepcopy(dict(_parent(root)))
    child = copy.deepcopy(dict(cfg))
    allowed = {
        "version", "release", "safety_gate_release", "package_revision",
        "runtime_bundle_manifest", "runtime_bundle_manifest_sha256",
        "guard_contract_file", "guard_contract_sha256", "implementation_files",
        "supply", "supply_route_choice_acceptance", "supply_route_choice_readiness",
        "performance", "trial_calibration",
    }
    for key, value in parent.items():
        if key in allowed:
            continue
        _require(key in child and _canonical(child[key]) == _canonical(value),
                 "V24913_UNREVIEWED_CONFIG_DRIFT:" + key)

    pperf = copy.deepcopy(parent.get("performance", {}))
    cperf = copy.deepcopy(child.get("performance", {}))
    pperf.get("first_sufficient", {}).pop("supply_min_relative_improvement", None)
    cperf.get("first_sufficient", {}).pop("supply_min_relative_improvement", None)
    pcompat = pperf.get("persistent_path_cache", {}).get("explicit_predecessor_read_compatibility", {})
    ccompat = cperf.get("persistent_path_cache", {}).get("explicit_predecessor_read_compatibility", {})
    pcompat.pop("target_release", None); ccompat.pop("target_release", None)
    ccompat["predecessors"] = [r for r in ccompat.get("predecessors", [])
                              if r.get("source_release") != PARENT_RELEASE]
    _require(_canonical(pperf) == _canonical(cperf), "V24913_UNREVIEWED_PERFORMANCE_DRIFT")

    ptrial = copy.deepcopy(parent.get("trial_calibration", {}))
    ctrial = copy.deepcopy(child.get("trial_calibration", {}))
    ptrial.get("max_trials_per_block", {}).pop("SUPPLY_ADDVAL1", None)
    ctrial.get("max_trials_per_block", {}).pop("SUPPLY_ADDVAL1", None)
    ctrial.pop("v24913_supply_route_choice_readiness", None)
    _require(_canonical(ptrial) == _canonical(ctrial), "V24913_UNREVIEWED_TRIAL_DRIFT")


def preflight_v24913_deployment_files(package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    manifest_path = root / RUNTIME_MANIFEST_FILE
    _require(manifest_path.is_file(), "V24913_RUNTIME_MANIFEST_MISSING")
    _require(rt.sha256_file(manifest_path) == RUNTIME_MANIFEST_SHA256,
             "V24913_RUNTIME_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(manifest_path)
    _require(manifest.get("schema") == "R1_15A2_V24913_RUNTIME_BUNDLE_MANIFEST_V1",
             "V24913_RUNTIME_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE, "V24913_RUNTIME_MANIFEST_RELEASE_MISMATCH")
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
    _require(not failures, "V24913_RUNTIME_BUNDLE_INVALID:" + json.dumps(failures, sort_keys=True))
    return {"passes": True, "release": RELEASE, "package_revision": PACKAGE_REVISION,
            "manifest_path": str(manifest_path), "manifest_sha256": RUNTIME_MANIFEST_SHA256,
            "files_checked": checked, "failures": []}


def validate_v24913_runtime_bundle(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    deployment = preflight_v24913_deployment_files(root)
    mixed = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("r1_15a2_") or module is None:
            continue
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().parent != root:
            mixed.append({"module": name, "file": str(Path(filename).resolve())})
    _require(not mixed, "V24913_MIXED_RELEASE_MODULES:" + json.dumps(mixed, sort_keys=True))

    smoke_cfg = copy.deepcopy(dict(cfg))
    smoke_cfg["runtime_acceptance_supply_cycle"] = 1
    smoke_cfg["runtime_acceptance_scope"] = "SUPPLY_ADDVAL1"
    policy = core.early_exploration_policy(smoke_cfg, "SUPPLY_ADDVAL1")
    _require(policy is not None and policy.get("scope") == "SUPPLY",
             "V24913_SUPPLY_POLICY_NOT_ACTIVE")
    rows = [{"countlocation_no": "V24913_PREFLIGHT", "role": "CALIBRATION",
             "observed": 100.0, "model": 100.0, "profile_weight": 1.0}]
    severity = core.severity_transition_guard(rows, rows, smoke_cfg, "SUPPLY_ADDVAL1")
    _require(severity.get("passes") is True and
             severity.get("mode") == "EARLY_EXPLORATION_BASELINE_RELATIVE_SEVERITY_V24912",
             "V24913_SUPPLY_POLICY_SMOKE_FAILED")
    supply_policy = SupplyPolicy.from_config(smoke_cfg)
    _require(abs(supply_policy.lattice - 0.5) <= 1e-12,
             "V24913_HALF_ADDVAL_LATTICE_NOT_ACTIVE")
    return {"passes": True, "release": RELEASE, "package_revision": PACKAGE_REVISION,
            "files_checked": deployment["files_checked"], "mixed_release_modules": [],
            "supply_policy_scope": policy, "half_addval_lattice": True,
            "branch_local_backtracking": True}


def validate_v24913_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    _validate_reviewed_delta(cfg, root)
    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V24913_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") == "2.4.9.13-supply-route-choice-readiness",
             "V24913_VERSION_IDENTITY_MISSING")
    _require(cfg.get("package_revision") == PACKAGE_REVISION,
             "V24913_PACKAGE_REVISION_MISSING")
    _require(cfg.get("runtime_bundle_manifest") == RUNTIME_MANIFEST_FILE and
             cfg.get("runtime_bundle_manifest_sha256") == RUNTIME_MANIFEST_SHA256,
             "V24913_RUNTIME_MANIFEST_NOT_PINNED")
    contract = root / CONTRACT_FILE
    _require(contract.is_file() and rt.sha256_file(contract) == CONTRACT_SHA256,
             "V24913_SUPPLY_CONTRACT_HASH_MISMATCH")
    _require(cfg.get("guard_contract_file") == CONTRACT_FILE and
             cfg.get("guard_contract_sha256") == CONTRACT_SHA256,
             "V24913_SUPPLY_CONTRACT_NOT_PINNED")

    supply = cfg.get("supply", {}) or {}
    exact = {
        "lattice": 0.5, "max_step": 8.0, "max_cumulative": 15.0,
        "absolute_min": -100.0, "absolute_max": 100.0,
        "max_bundle_equivalent_seconds": 360.0, "max_edges": 30,
        "max_candidates": 40, "max_driver_profiles": 80,
        "min_geh": 5.0, "min_residual": 100.0,
        "min_attribution_coverage": 0.90, "min_path_coverage": 0.90,
        "min_path_volume_coverage": 0.95,
    }
    for key, value in exact.items():
        _require(float(supply.get(key)) == float(value), "V24913_SUPPLY_LIMIT_CHANGED:" + key)
    seq = supply.get("sequence", {}) or {}
    _require(seq.get("sequence_cap_schedule") == [12, 8, 4, 2, 1],
             "V24913_SEQUENCE_CAP_SCHEDULE_CHANGED")
    _require(seq.get("step_units_schedule") == [16, 8, 4, 2, 1],
             "V24913_STEP_LADDER_CHANGED")
    _require(int(cfg.get("trial_calibration", {}).get("max_trials_per_block", {}).get("SUPPLY_ADDVAL1", 0)) == 40,
             "V24913_SUPPLY_TRIAL_BUDGET_CHANGED")

    acceptance = cfg.get("supply_route_choice_acceptance", {}) or {}
    scoped = acceptance.get("supply", {}) or {}
    severity = acceptance.get("severity", {}) or {}
    _require(acceptance.get("enabled") is True and int(acceptance.get("through_supply_cycle", 0)) == 100,
             "V24913_SUPPLY_ACCEPTANCE_HORIZON_CHANGED")
    _require(float(scoped.get("max_severity20_relative_degradation")) == 0.20 and
             float(scoped.get("max_severity30_relative_degradation")) == 0.25 and
             int(scoped.get("max_geh40_net_count_increase")) == 20,
             "V24913_SUPPLY_SEVERITY_BUDGET_CHANGED")
    _require(float(scoped.get("max_idp_mean_degradation")) == 0.02 and
             float(scoped.get("max_idp_component_degradation")) == 0.08,
             "V24913_SUPPLY_IDP_BUDGET_CHANGED")
    _require(float(severity.get("max_single_profile_geh_increase")) == 20.0 and
             float(severity.get("max_high_geh_increase")) == 15.0,
             "V24913_SUPPLY_CATASTROPHIC_GUARD_CHANGED")
    _require(acceptance.get("shared_objective_must_improve") is True and
             acceptance.get("demand_hashes_frozen") is True,
             "V24913_SUPPLY_MONOTONICITY_OR_FREEZE_CHANGED")

    restart = cfg.get("restart_authority", {}) or {}
    _require(restart.get("mode") == "SEMANTIC_MODEL_STATE" and
             restart.get("schema") == RESTART_SCHEMA and
             restart.get("semantic_fields") == list(SEMANTIC_FIELDS) and
             restart.get("raw_ver_sha_role") == RAW_VER_SHA_ROLE and
             restart.get("raw_ver_sha_used_for_restart_acceptance") is False,
             "V24913_SEMANTIC_RESTART_CONTRACT_LOST")
    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V24913_CACHE_COMPAT_TARGET_CHANGED")
    rows = [r for r in compat.get("predecessors", []) if r.get("source_release") == PARENT_RELEASE]
    _require(len(rows) == 1 and rows[0].get("source_config_sha256s") == [PARENT_CONFIG_SHA256],
             "V24913_V24912_PROVENANCE_NOT_PINNED")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_13.py",
        "R1_15A2_SUPPLY_FROM_CONVERGED_DEMAND_V2_4_9_13.py",
        "r1_15a2_safety_v24913.py", "r1_15a2_supply_handoff_v24913.py",
        "r1_15a2_core.py", "r1_15a2_supply.py", "r1_15a2_sequence_v23.py",
        "r1_15a2_overnight_controller_v240.py", "r1_15a2_overnight_controller_v242.py",
        "r1_15a2_trial_adapter_v240.py", "r1_15a2_supply_visum.py",
        "r1_15a2_runtime_v1.py",
    )
    for name in required:
        digest = impl.get(name)
        _require(isinstance(digest, str) and len(digest) == 64,
                 "V24913_IMPLEMENTATION_HASH_MISSING:" + name)
        _require((root / name).is_file() and rt.sha256_file(root / name) == digest,
                 "V24913_IMPLEMENTATION_HASH_MISMATCH:" + name)
    return {"passes": True, "parent_release": PARENT_RELEASE,
            "supply_policy": "V24913_SUPPLY_ROUTE_CHOICE_BASELINE_RELATIVE",
            "supply_lattice_seconds": 5.0, "supply_step_ladder_seconds": [80,40,20,10,5],
            "real_visum_supply_tested": False, "production_ready": False}


__all__ = ["RELEASE", "PARENT_RELEASE", "PARENT_CONFIG_SHA256", "CONTRACT_FILE",
           "CONTRACT_SHA256", "RUNTIME_MANIFEST_FILE", "RUNTIME_MANIFEST_SHA256",
           "PACKAGE_REVISION", "preflight_v24913_deployment_files",
           "validate_v24913_config", "validate_v24913_runtime_bundle"]
