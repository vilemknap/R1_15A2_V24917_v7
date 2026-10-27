# -*- coding: utf-8 -*-
"""Fail-closed overlay preflight for PERF2C single-pass exact snapshot."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError

RELEASE = "R1_15A2_V2_4_9_15_PERF2C_R2_SINGLE_PASS_EXACT_SNAPSHOT_SUPPLY_TEMP_HOTFIX_20261020"
PARENT_RELEASE = "R1_15A2_V2_4_9_15_PERF2_CANDIDATE_READBACK_BUNDLE_20261019"
PACKAGE_REVISION = "V24915_PERF2C_R2_SUPPLY_TEMP_SQLITE_HOTFIX"
MANIFEST_FILE = "V24915_PERF2C_OVERLAY_MANIFEST.json"
MANIFEST_SHA256 = "fd5eddfaf9104837958456712593837b041adc3fd72ed64722dd62c2a17f56b5"
CONTRACT_FILE = "V24915_PERF2C_SINGLE_PASS_EXACT_SNAPSHOT_CONTRACT.json"
CONTRACT_SHA256 = "2c396a29e4ce1fa6c3ac23b0ae9d6285dec6c6669f17db44c2c9fe047f4a1ae3"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def preflight_v24915p2c_overlay(package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    manifest_path = root / MANIFEST_FILE
    _require(manifest_path.is_file(), "V24915P2C_OVERLAY_MANIFEST_MISSING")
    _require(rt.sha256_file(manifest_path) == MANIFEST_SHA256,
             "V24915P2C_OVERLAY_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(manifest_path)
    _require(manifest.get("schema") == "R1_15A2_V24915_PERF2C_OVERLAY_MANIFEST_V1",
             "V24915P2C_OVERLAY_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE,
             "V24915P2C_OVERLAY_RELEASE_MISMATCH")
    _require(manifest.get("parent_release") == PARENT_RELEASE,
             "V24915P2C_OVERLAY_PARENT_MISMATCH")
    _require(manifest.get("package_revision") == PACKAGE_REVISION,
             "V24915P2C_OVERLAY_REVISION_MISMATCH")

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
        elif rt.sha256_file(path) != row.get("sha256"):
            failures.append({"path": rel, "reason": "SHA256_MISMATCH"})
    _require(not failures, "V24915P2C_OVERLAY_INVALID:" + json.dumps(failures, sort_keys=True))

    contract_path = root / CONTRACT_FILE
    _require(contract_path.is_file() and rt.sha256_file(contract_path) == CONTRACT_SHA256,
             "V24915P2C_CONTRACT_HASH_MISMATCH")
    contract = rt.read_json(contract_path)
    required_false = (
        "public_snapshot_schema_changed", "semantic_hashes_changed",
        "matrix_getvalues_semantics_changed", "cross_snapshot_cache",
        "cross_candidate_cache", "cross_assignment_cache", "new_mutation_epoch",
        "new_authority_token", "rollback_changed", "candidate_math_changed",
        "acceptance_changed", "assignment_changed", "continuation_changed",
        "overnight50_changed",
    )
    _require(all(contract.get(key) is False for key in required_false),
             "V24915P2C_CONTRACT_UNSAFE_FLAG")
    _require(contract.get("first_live_call_exact_shadow_parity") is True,
             "V24915P2C_FIRST_CALL_PARITY_NOT_REQUIRED")
    _require(contract.get("full_matrix_values_required") is True,
             "V24915P2C_FULL_MATRIX_READ_NOT_REQUIRED")
    return {
        "passes": True,
        "release": RELEASE,
        "parent_release": PARENT_RELEASE,
        "package_revision": PACKAGE_REVISION,
        "manifest_path": str(manifest_path),
        "manifest_sha256": MANIFEST_SHA256,
        "contract_path": str(contract_path),
        "contract_sha256": CONTRACT_SHA256,
        "files_checked": checked,
        "failures": [],
        "public_snapshot_schema_changed": False,
        "cross_call_cache": False,
        "first_call_exact_shadow_parity": True,
        "fallback_to_parent_snapshot": True,
    }


__all__ = [
    "RELEASE", "PARENT_RELEASE", "PACKAGE_REVISION", "MANIFEST_FILE",
    "MANIFEST_SHA256", "CONTRACT_FILE", "CONTRACT_SHA256",
    "preflight_v24915p2c_overlay",
]
