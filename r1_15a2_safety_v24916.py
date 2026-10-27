# -*- coding: utf-8 -*-
"""Fail-closed V2.4.9.16 FlowBundle/skim rebase safety contract."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

import r1_15a2_com_compat as com
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError

RELEASE = "R1_15A2_V2_4_9_16_FLOWBUNDLE_SKIM_TARGETING_REBASE_20261019"
PARENT_RELEASE = "R1_15A2_V2_4_9_15_COM_BUSY_RETRY_SAFE_FINALIZER_20261019"
PARENT_CONFIG_FILE = "R1_15A2_CONFIG_V2_4_9_15.json"
PARENT_CONFIG_SHA256 = "ef5669db1db24041499896c307fb05b548084334ad1a037f3650f641f6996be3"
PARENT_ZIP_SHA256 = "5ba9c2baec1c433534c9aac49d92cb8f450f12f8a78d1f9f1db82cc5987ba716"
CONTRACT_FILE = "V24916_FLOWBUNDLE_SKIM_TARGETING_REBASE_CONTRACT.json"
CONTRACT_SHA256 = "88e2215ccf920e28a67eb8ad4314b5ef1862d598ba91ca7f58a1f868176e1d0f"
RUNTIME_MANIFEST_FILE = "V24916_RUNTIME_BUNDLE_MANIFEST.json"
PACKAGE_REVISION = "V24916_FLOWBUNDLE_SKIM_TARGETING_REBASE_R1"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parent(root: Path) -> Mapping[str, Any]:
    path = root / PARENT_CONFIG_FILE
    _require(path.is_file(), "V24916_PARENT_CONFIG_MISSING")
    _require(rt.sha256_file(path) == PARENT_CONFIG_SHA256,
             "V24916_PARENT_CONFIG_HASH_MISMATCH")
    cfg = rt.read_json(path)
    _require(cfg.get("release") == PARENT_RELEASE, "V24916_PARENT_RELEASE_MISMATCH")
    return cfg


def _normalized_performance(parent, child):
    p = copy.deepcopy(parent)
    c = copy.deepcopy(child)
    pcompat = p.get("persistent_path_cache", {}).get("explicit_predecessor_read_compatibility", {})
    ccompat = c.get("persistent_path_cache", {}).get("explicit_predecessor_read_compatibility", {})
    ccompat["target_release"] = pcompat.get("target_release")
    ccompat["predecessors"] = [
        row for row in ccompat.get("predecessors", [])
        if row.get("source_release") != PARENT_RELEASE]
    return p, c


def validate_v24916_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    parent = copy.deepcopy(dict(_parent(root)))
    child = copy.deepcopy(dict(cfg))
    _require(child.get("release") == RELEASE and child.get("safety_gate_release") == RELEASE,
             "V24916_RELEASE_IDENTITY_MISSING")
    _require(child.get("version") == "2.4.9.16-flowbundle-skim-targeting-rebase",
             "V24916_VERSION_IDENTITY_MISSING")
    _require(child.get("package_revision") == PACKAGE_REVISION,
             "V24916_PACKAGE_REVISION_MISSING")
    contract = root / CONTRACT_FILE
    _require(contract.is_file() and rt.sha256_file(contract) == CONTRACT_SHA256,
             "V24916_CONTRACT_HASH_MISMATCH")
    _require(child.get("guard_contract_file") == CONTRACT_FILE and
             child.get("guard_contract_sha256") == CONTRACT_SHA256,
             "V24916_CONTRACT_NOT_PINNED")

    allowed = {
        "version", "release", "safety_gate_release", "package_revision",
        "runtime_bundle_manifest", "runtime_bundle_manifest_sha256",
        "guard_contract_file", "guard_contract_sha256", "implementation_files",
        "performance", "trial_calibration", "methodology",
        "demand_evidence_targeting",
    }
    for key, value in parent.items():
        if key in allowed:
            continue
        _require(key in child and _canonical(child[key]) == _canonical(value),
                 "V24916_UNREVIEWED_CONFIG_DRIFT:" + key)

    pperf, cperf = _normalized_performance(parent.get("performance", {}),
                                           child.get("performance", {}))
    _require(_canonical(pperf) == _canonical(cperf),
             "V24916_UNREVIEWED_PERFORMANCE_DRIFT")
    ptrial = copy.deepcopy(parent.get("trial_calibration", {}))
    ctrial = copy.deepcopy(child.get("trial_calibration", {}))
    ctrial.pop("v24916_flowbundle_skim_targeting_rebase", None)
    _require(_canonical(ptrial) == _canonical(ctrial),
             "V24916_UNREVIEWED_TRIAL_DRIFT")
    pmethod = copy.deepcopy(parent.get("methodology", {}))
    cmethod = copy.deepcopy(child.get("methodology", {}))
    cmethod.pop("v24916_flowbundle_skim_targeting_rebase", None)
    _require(_canonical(pmethod) == _canonical(cmethod),
             "V24916_UNREVIEWED_METHODOLOGY_DRIFT")
    _require(_canonical(parent.get("com_resilience")) == _canonical(child.get("com_resilience")),
             "V24916_COM_RETRY_POLICY_DRIFT")

    evidence = child.get("demand_evidence_targeting", {}) or {}
    _require(evidence.get("enabled") in (True, False), "V24916_DEMAND_EVIDENCE_SWITCH_INVALID")
    _require(evidence.get("supply_enabled") is False, "V24916_SUPPLY_TARGETING_FORBIDDEN")
    _require(evidence.get("authority_role") ==
             "TARGETING_OBSERVABILITY_ONLY_PATH_INCIDENCE_REMAINS_NUMERICAL_AUTHORITY",
             "V24916_PATH_INCIDENCE_AUTHORITY_LOST")
    _require(evidence.get("skim", {}).get("optional_role") == "SHADOW_DIAGNOSTIC_ONLY",
             "V24916_OPTIONAL_SKIM_ROLE_CHANGED")
    _require(evidence.get("shadow_classifier", {}).get("supply_writes") is False,
             "V24916_SHADOW_CLASSIFIER_SUPPLY_WRITE_FORBIDDEN")
    _require(evidence.get("support_risk", {}).get("skim_gap_role") ==
             "SHADOW_DIAGNOSTIC_NOT_HARD_TRIGGER",
             "V24916_SKIM_HARD_ENUMERATION_TRIGGER_FORBIDDEN")
    _require(com.com_retry_settings(child.get("com_resilience")) == (5, 0.05, 2.0, 0.8),
             "V24916_GENERIC_COM_RETRY_CHANGED")
    _require(child.get("coupled_demand", {}).get("finecdf_td", {}).get(
             "reference_script_id") == parent.get("coupled_demand", {}).get(
             "finecdf_td", {}).get("reference_script_id"),
             "V24916_FINECDF_V19_REFERENCE_CHANGED")
    _require(_canonical(child.get("supply")) == _canonical(parent.get("supply")),
             "V24916_SUPPLY_CONFIG_DRIFT")
    _require(_canonical(child.get("supply_route_choice_acceptance")) ==
             _canonical(parent.get("supply_route_choice_acceptance")),
             "V24916_SUPPLY_ACCEPTANCE_DRIFT")
    return {
        "passes": True, "release": RELEASE, "parent_release": PARENT_RELEASE,
        "parent_config_sha256": PARENT_CONFIG_SHA256,
        "parent_zip_sha256": PARENT_ZIP_SHA256,
        "supply_delta": "ZERO", "com_retry_policy_preserved": True,
        "finecdf_v19_preserved": True,
    }


def preflight_v24916_deployment_files(package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    path = root / RUNTIME_MANIFEST_FILE
    _require(path.is_file(), "V24916_RUNTIME_MANIFEST_MISSING")
    cfg = rt.read_json(root / "R1_15A2_CONFIG_V2_4_9_16.json")
    expected = str(cfg.get("runtime_bundle_manifest_sha256", ""))
    _require(expected and expected != "PENDING_BUILD", "V24916_RUNTIME_MANIFEST_NOT_PINNED")
    _require(rt.sha256_file(path) == expected, "V24916_RUNTIME_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(path)
    _require(manifest.get("schema") == "R1_15A2_V24916_RUNTIME_BUNDLE_MANIFEST_V1",
             "V24916_RUNTIME_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE, "V24916_RUNTIME_MANIFEST_RELEASE_MISMATCH")
    failures = []
    for row in manifest.get("files", []):
        rel = str(row.get("path", "")); candidate = root / rel
        if not rel or not candidate.is_file():
            failures.append({"path": rel, "reason": "MISSING"}); continue
        if candidate.stat().st_size != int(row.get("size", -1)):
            failures.append({"path": rel, "reason": "SIZE_MISMATCH"}); continue
        if rt.sha256_file(candidate) != row.get("sha256"):
            failures.append({"path": rel, "reason": "SHA256_MISMATCH"})
    _require(not failures, "V24916_RUNTIME_BUNDLE_INVALID:" + json.dumps(failures, sort_keys=True))
    return {"passes": True, "files_checked": len(manifest.get("files", [])),
            "manifest_sha256": expected, "failures": []}


def validate_v24916_runtime_bundle(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    validate_v24916_config(cfg, root)
    deployment = preflight_v24916_deployment_files(root)
    mixed = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("r1_15a2_") or module is None:
            continue
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().parent != root:
            mixed.append({"module": name, "file": str(Path(filename).resolve())})
    _require(not mixed, "V24916_MIXED_RELEASE_MODULES:" + json.dumps(mixed, sort_keys=True))
    return {"passes": True, "release": RELEASE,
            "files_checked": deployment["files_checked"],
            "mixed_release_modules": [], "supply_policy_preserved": True,
            "real_visum_tested": False, "production_ready": False}


def _operation_script_path(op: Any) -> str:
    # SCRIPTFILE is the canonical PTV operation attribute.  Avoid broad
    # expected-error probing in the active runtime.
    try:
        exists = getattr(op, "AttrExists", None)
        if callable(exists) and not bool(exists("SCRIPTFILE")):
            return ""
    except Exception:
        pass
    try:
        return str(op.AttValue("SCRIPTFILE") or "").strip()
    except Exception:
        return ""


def audit_external_run_scripts(visum: Any, cfg: Mapping[str, Any], folder=None) -> Mapping[str, Any]:
    allow = cfg.get("procedure_sequence_external_scripts", {}) or {}
    allowed_names = {str(k): str(v).lower() for k, v in (allow.get("allowed_sha256_by_basename", {}) or {}).items()}
    rows = []
    failures = []
    for index, op in enumerate(rt.get_all(visum.Procedures.Operations), 1):
        try:
            typ = int(round(float(op.AttValue("OPERATIONTYPE"))))
            active = bool(int(round(float(op.AttValue("ACTIVE")))))
        except Exception:
            continue
        if typ != com.EXECUTE_SCRIPT or not active:
            continue
        raw = _operation_script_path(op)
        path = Path(raw) if raw else None
        exists = bool(path and path.is_file())
        digest = rt.sha256_file(path) if exists else ""
        basename = path.name if path else ""
        expected = allowed_names.get(basename, "")
        allowed = bool(expected and digest.lower() == expected)
        row = {"operation_index": index, "operation_type": typ, "active": int(active),
               "script_path": raw, "basename": basename, "exists": int(exists),
               "sha256": digest, "expected_sha256": expected,
               "allowed": int(allowed)}
        rows.append(row)
        if not allowed:
            failures.append(row)
    result = {"schema": "R1_15A2_EXTERNAL_PROCSEQ_SCRIPT_AUDIT_V24916",
              "passes": not failures, "active_script_count": len(rows),
              "rows": rows, "failures": failures}
    if folder is not None:
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        rt.write_json(folder / "PROCEDURE_SEQUENCE_EXTERNAL_SCRIPT_AUDIT.json", result)
        rt.write_csv(folder / "PROCEDURE_SEQUENCE_EXTERNAL_SCRIPT_AUDIT.csv", rows)
    _require(not failures, "V24916_EXTERNAL_PROCSEQ_SCRIPT_NOT_ALLOWLISTED:" +
             json.dumps(failures, sort_keys=True))
    return result


__all__ = ["RELEASE", "validate_v24916_config", "validate_v24916_runtime_bundle",
           "preflight_v24916_deployment_files", "audit_external_run_scripts"]
