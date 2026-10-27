# -*- coding: utf-8 -*-
"""V24916 PROFILE488 row-authority gate correction.

The sealed PERF2 runtime predates the current 488-row all-calibration authority
and still carries historical 498/462/36 expectations in two places:
  1) config-driven run_12d row gate;
  2) hard-coded 11D->12D cross-gate inside assess_11d_idp_gate().

This child overlay keeps those gates fail-closed but binds them to the active
PROFILE488 authority: 488 rows, all 488 CALIBRATION, 0 VALIDATION.
No 12D/11D metric formula, assignment, FlowBundle, dynamic skim, TG/TD search,
or acceptance guard is relaxed. This child release also seals the approved
read-only COM-busy snapshot retry and V24916-native TD09C 16/17 compatibility.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable, Mapping

import r1_15a2_fastcal_runtime_v24916p2c as base
import r1_15a2_com_busy_snapshot_hotfix_v24916 as combusy_hotfix
import r1_15a2_td09c_16or17_hotfix_v24916 as td09c_hotfix
from r1_15a2_safety_v24916p2c import build_safety_contract

RELEASE = "R1_15A2_V24916_PERF2C_FRESH0_DYNAMICSKIM1_FASTCAL1_PROFILE488FIX1_COMBUSY_TD09C16_20261023"
PACKAGE_REVISION = "V24916_DYNAMICSKIM1_FASTCAL1_PROFILE488FIX1_COMBUSY_TD09C16_20261023"
PROFILE488_GATE_SCHEMA = "R1_15A2_V24916_PROFILE488_ROW_GATE_FIX_V1"
INTEGRATED_HOTFIX_SCHEMA = "R1_15A2_V24916_COMBUSY_TD09C16_INTEGRATION_V1"
PROFILE488_GATE_CORRECTION = {
    "expected_12d_rows": 488,
    "expected_calibration_rows": 488,
    "expected_validation_rows": 0,
}
LEGACY_GATE = {"rows": 498, "calibration": 462, "validation": 36}

# Re-export launcher identity/isolation constants from FASTCAL1.
AUTHORITY_FILE = base.AUTHORITY_FILE
ISOLATION_SCHEMA = base.ISOLATION_SCHEMA
SOURCE_SEMANTIC_POLICY = base.SOURCE_SEMANTIC_POLICY
EXPECTED_BASELINE_SEMANTIC_STATE_HASH = base.EXPECTED_BASELINE_SEMANTIC_STATE_HASH
RUNS_ROOT_NAME = base.RUNS_ROOT_NAME
LOCK_NAME = base.LOCK_NAME
WORKSPACE_NAME = base.WORKSPACE_NAME
PRIVATE_CACHE_DIRNAME = base.PRIVATE_CACHE_DIRNAME


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _integrated_hotfix_payload() -> dict[str, Any]:
    return {
        "schema": INTEGRATED_HOTFIX_SCHEMA,
        "com_busy_snapshot_retry": combusy_hotfix.policy_payload(),
        "td09c_16_or_17_native_scope": td09c_hotfix.policy_payload(),
        "iofix4_import_audit": {
            "source_branch": "R1_15A2_PROFILE488_AGGRESSIVE_TGTD_V1_FIX1_IOFIX4_BASE_20261022",
            "decision": "CURRENT_V24916_IOFIX3_PATHFIX3_IS_STRICT_SUPERSET_NO_DOWNGRADE",
            "short_opaque_temp_names": True,
            "windows_extended_length_path_io": True,
            "critical_atomic_publication_retry": True,
            "telemetry_fail_open": True,
            "v24916_specific_evidence_writers_protected": True,
        },
        "calibration_formulas_changed": False,
        "assignment_method_changed": False,
        "dynamic_skim_method_changed": False,
        "flowbundle_targeting_changed": False,
        "profile488_authority_changed": False,
    }


def _policy_payload() -> dict[str, Any]:
    return {
        "schema": PROFILE488_GATE_SCHEMA,
        "enabled": True,
        "active_authority_rows": 488,
        "active_calibration_rows": 488,
        "active_validation_rows": 0,
        "historical_gate_replaced": dict(LEGACY_GATE),
        "gate_source": "ACTIVE_PROFILE488_COUNTLOCATION_AUTHORITY",
        "run_12d_gate_remains_fail_closed": True,
        "11d_to_12d_cross_gate_remains_fail_closed": True,
        "12d_metric_formula_changed": False,
        "11d_metric_formula_changed": False,
        "assignment_method_changed": False,
        "dynamic_skim_method_changed": False,
        "flowbundle_targeting_changed": False,
        "tg_td_search_policy_changed": False,
        "acceptance_guard_relaxed": False,
    }


def apply_active_runtime_delta(parent_cfg: Mapping[str, Any]) -> dict[str, Any]:
    cfg = base.apply_active_runtime_delta(parent_cfg)
    for key, value in PROFILE488_GATE_CORRECTION.items():
        cfg[key] = value
    cfg["v24916_profile488_gatefix1"] = _policy_payload()
    cfg["v24916_profile488_gatefix1_hash"] = _hash(cfg["v24916_profile488_gatefix1"])
    cfg["v24916_integrated_hotfixes"] = _integrated_hotfix_payload()
    cfg["v24916_integrated_hotfixes_hash"] = _hash(cfg["v24916_integrated_hotfixes"])
    identity = cfg.setdefault("v24916_release_identity", {})
    identity["release"] = RELEASE
    identity["package_revision"] = PACKAGE_REVISION
    identity["profile488_row_gate_fix"] = True
    identity["profile488_row_gate"] = [488, 488, 0]
    identity["com_busy_snapshot_retry"] = True
    identity["td09c_16_or_17_native_scope"] = True
    identity["iofix4_compatibility_audited"] = True
    build_safety_contract(cfg)
    return cfg


def validate_active_runtime_delta(child: Mapping[str, Any], parent: Mapping[str, Any]) -> dict[str, Any]:
    # First prove FASTCAL1/DYNAMICSKIM1 itself remains exactly valid.
    base_child = base.apply_active_runtime_delta(parent)
    base.validate_active_runtime_delta(base_child, parent)

    expected = apply_active_runtime_delta(parent)
    if dict(child) != expected:
        keys = sorted(set(expected) | set(child))
        bad = [k for k in keys if child.get(k) != expected.get(k)]
        raise RuntimeError("V24916_PROFILE488FIX1_CONFIG_DELTA_MISMATCH:" + ",".join(bad[:30]))

    for key, value in PROFILE488_GATE_CORRECTION.items():
        if int(child.get(key, -1)) != value:
            raise RuntimeError("V24916_PROFILE488FIX1_GATE_COUNT_MISMATCH:" + key)

    # Prove no inherited scientific/search policy changed apart from release
    # identity plus the three authority-count gates and this audit section.
    normalized = copy.deepcopy(dict(child))
    for key in PROFILE488_GATE_CORRECTION:
        if key in base_child:
            normalized[key] = base_child[key]
        else:
            normalized.pop(key, None)
    normalized.pop("v24916_profile488_gatefix1", None)
    normalized.pop("v24916_profile488_gatefix1_hash", None)
    normalized.pop("v24916_integrated_hotfixes", None)
    normalized.pop("v24916_integrated_hotfixes_hash", None)
    if isinstance(normalized.get("v24916_release_identity"), dict):
        normalized["v24916_release_identity"] = copy.deepcopy(base_child.get("v24916_release_identity", {}))
    if normalized != base_child:
        raise RuntimeError("V24916_PROFILE488FIX1_UNEXPECTED_PARENT_POLICY_CHANGE")

    safety = build_safety_contract(child)
    return {
        "schema": "R1_15A2_V24916_PROFILE488_GATEFIX1_CONFIG_AUDIT_V1",
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "profile488_runtime_gate_correction": copy.deepcopy(PROFILE488_GATE_CORRECTION),
        "run_12d_gate_fail_closed": True,
        "11d_cross_gate_fail_closed": True,
        "parent_fastcal1_validated": True,
        "scientific_formulas_changed": False,
        "search_policy_changed": False,
        "integrated_hotfixes": _integrated_hotfix_payload(),
        "safety_contract_hash": safety.contract_hash,
    }


def _profile488_assess_wrapper(parent_assess: Callable[..., dict[str, Any]]):
    """Wrap sealed assess_11d_idp_gate without mutating its source file.

    We independently validate the active 488/488/0 gate. Only after that proof
    do we present the sealed parent assessor with its historical gate tuple so
    that all *other* legacy IDP/read-only checks run unchanged. The returned
    evidence is rewritten back to the truthful active gate and explicitly marks
    the PROFILE488 adaptation.
    """
    def wrapped(meta, d12, cfg):
        expected = {
            "rows": int(cfg.get("expected_12d_rows", LEGACY_GATE["rows"])),
            "calibration": int(cfg.get("expected_calibration_rows", LEGACY_GATE["calibration"])),
            "validation": int(cfg.get("expected_validation_rows", LEGACY_GATE["validation"])),
        }
        if expected != {"rows": 488, "calibration": 488, "validation": 0}:
            return parent_assess(meta, d12, cfg)

        actual_gate = d12.get("row_gate", {}) if isinstance(d12, dict) else {}
        mismatch = [k for k, v in expected.items() if actual_gate.get(k) != v]

        # Run every sealed parent check. The only compatibility substitution is
        # the already-independently-proven row-count tuple.
        parent_d12 = copy.deepcopy(d12) if isinstance(d12, dict) else d12
        if isinstance(parent_d12, dict):
            parent_d12["row_gate"] = dict(LEGACY_GATE)
        decision = parent_assess(meta, parent_d12, cfg)
        decision = copy.deepcopy(decision)
        decision["mandatory_12d_row_gate"] = copy.deepcopy(actual_gate)
        decision["active_12d_row_gate_expected"] = copy.deepcopy(expected)
        decision["profile488_gate_adapter"] = PROFILE488_GATE_SCHEMA

        notices = list(decision.get("notices") or [])
        notices = [
            "LEGACY_11D_COUNT_ROWS_NOT_15A2_AUTHORITY_USE_ACTIVE_PROFILE488_12D"
            if x == "LEGACY_11D_COUNT_ROWS_NOT_15A2_AUTHORITY_USE_12D_498" else x
            for x in notices
        ]
        if not mismatch:
            notices.append("PROFILE488_12D_GATE_488_488_0_VALIDATED")
        decision["notices"] = notices

        failures = list(decision.get("failures") or [])
        # Parent row-count failures are artifacts of its historical tuple and
        # are valid to remove only because actual_gate was checked independently.
        failures = [f for f in failures if not str(f).startswith("12D_APPROVED_COUNT_AUTHORITY_NOT_PROVEN:")]
        for key in mismatch:
            failures.append("PROFILE488_12D_ACTIVE_AUTHORITY_NOT_PROVEN:" + key)
        decision["failures"] = failures
        decision["passes"] = not failures
        decision["status"] = (
            "PASS_IDP_ONLY_WITH_LEGACY_11D_ADVISORIES" if not failures and notices else
            "PASS_ATOMIC_IDP_READ_ONLY" if not failures else "FAIL_IDP_OR_READ_ONLY"
        )
        return decision

    wrapped._v24916_profile488_gatefix1 = True
    wrapped._v24916_parent_assess = parent_assess
    return wrapped


def activate_runtime_gate_overlay() -> dict[str, Any]:
    import r1_15a2_runtime_v1 as rt
    current = rt.assess_11d_idp_gate
    if getattr(current, "_v24916_profile488_gatefix1", False):
        return {
            "status": "ALREADY_ACTIVE",
            "schema": PROFILE488_GATE_SCHEMA,
            "gate": [488, 488, 0],
            "sealed_runtime_source_modified_on_disk": False,
        }
    rt.assess_11d_idp_gate = _profile488_assess_wrapper(current)
    return {
        "status": "ACTIVE",
        "schema": PROFILE488_GATE_SCHEMA,
        "gate": [488, 488, 0],
        "sealed_runtime_source_modified_on_disk": False,
        "patched_symbol": "r1_15a2_runtime_v1.assess_11d_idp_gate",
    }


__all__ = [
    "RELEASE", "PACKAGE_REVISION", "PROFILE488_GATE_SCHEMA", "INTEGRATED_HOTFIX_SCHEMA",
    "PROFILE488_GATE_CORRECTION", "AUTHORITY_FILE", "ISOLATION_SCHEMA",
    "SOURCE_SEMANTIC_POLICY", "EXPECTED_BASELINE_SEMANTIC_STATE_HASH",
    "RUNS_ROOT_NAME", "LOCK_NAME", "WORKSPACE_NAME", "PRIVATE_CACHE_DIRNAME",
    "apply_active_runtime_delta", "validate_active_runtime_delta", "_integrated_hotfix_payload",
    "activate_runtime_gate_overlay", "_profile488_assess_wrapper",
]
