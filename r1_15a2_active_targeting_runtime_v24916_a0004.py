# -*- coding: utf-8 -*-
"""V24916 active FlowBundle/DIST_KM targeting over PROFILE488 A0004 recovery.

This is an additive search-space overlay.  The V24915 A0004 recovery parent,
its cycle-3 TD continuation, IOFIX1, telemetry fail-open behavior, assignment,
12D/11D diagnostics and acceptance rules remain authoritative.
"""
from __future__ import annotations
import copy, hashlib, json
from typing import Any, Mapping

from r1_15a2_safety_v24916p2c import build_safety_contract
from r1_15a2_active_targeting_runtime_v24916p2c import (
    V24916_ACTIVE_SECTION as _BASE_ACTIVE_SECTION,
    DEMAND_EVIDENCE_TARGETING as _BASE_DEMAND_EVIDENCE_TARGETING,
)

RELEASE = "R1_15A2_V24916_PERF2C_PROFILE488_A0004_CYCLE3_TD_RESUME_IOFIX1_ACTIVE_TARGETING_ONECLICK1_20261022"
PACKAGE_REVISION = "V24916_PROFILE488_A0004_CYCLE3_TD_RESUME_IOFIX1_ACTIVE_TARGETING_P2P3_PREFLIGHT_CACHEFIX1"
AUTHORITY_FILE = "V24916_A0004_LIVE_AUTHORITY.json"
LINEAGE_SCHEMA = "R1_15A2_V24916_PROFILE488_A0004_ACTIVE_TARGETING_LINEAGE_V1"
EXPECTED_PARENT_CHECKPOINT = "ACCEPTED_B_0004_d26d01d6f9a5.ver"
EXPECTED_PARENT_SEMANTIC_STATE_HASH = "c853dba4c29526903c5a16c496d5863e3506a12fcf5a5b8103ba3bb98cb2d97d"
EXPECTED_ACCEPTED_COUNT = 4
EXPECTED_OUTER_CYCLE = 3
EXPECTED_RESUME_SUBSTEP = "TD_FINECDF_V17"
EXPECTED_MAX_OUTER_CYCLES = 100
PROFILE488_GATE_CORRECTION = {
    "expected_12d_rows": 488,
    "expected_calibration_rows": 488,
    "expected_validation_rows": 0,
}

V24916_ACTIVE_SECTION = copy.deepcopy(_BASE_ACTIVE_SECTION)
V24916_ACTIVE_SECTION.update({
    "activation_stage": "P2P3_ACTIVE_ON_PROFILE488_A0004_CYCLE3_TD_RECOVERY",
    "acceptance_authority": "UNCHANGED_PARENT_A0004_RECOVERY_FRESH_ASSIGNMENT_PLUS_LIVE_12D_11D",
    "fresh_baseline_live_authority_required": False,
    "a0004_recovery_live_authority_required": True,
    "parent_iofix1_required": True,
    "parent_telemetry_failopen_required": True,
})

DEMAND_EVIDENCE_TARGETING = copy.deepcopy(_BASE_DEMAND_EVIDENCE_TARGETING)
DEMAND_EVIDENCE_TARGETING["state_binding"] = (
    "A0004_SEMANTIC_STATE_PLUS_ASSIGNMENT_PLUS_NEW_RECOVERY_PATH_EPOCH_PLUS_SKIM_PLUS_CONFIG"
)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()


def apply_active_runtime_delta(base_cfg: Mapping[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(dict(base_cfg))
    # The uploaded A0004 recovery parent binds the new 488-row helper/authority
    # at runtime but still carries the legacy 498/462/36 row gate in its sealed
    # PERF2 config.  Correct only these three runtime gate counts in the child.
    # No parent source/config file is modified on disk.
    for key, value in PROFILE488_GATE_CORRECTION.items():
        cfg[key] = value
    cfg["v24916_release_identity"] = {
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "parent_release": "R1_15A2_V24915_PERF2C_PROFILE488_A0004_CYCLE3_TD_RECOVERY_IOFIX1_NO_WALLCLOCK_20261022",
        "parent_reviewed_config_unchanged": True,
        "parent_runtime_iofix1_preserved": True,
        "parent_telemetry_failopen_preserved": True,
    }
    cfg["v24916_flowbundle_skim_runtime"] = copy.deepcopy(V24916_ACTIVE_SECTION)
    cfg["demand_evidence_targeting"] = copy.deepcopy(DEMAND_EVIDENCE_TARGETING)
    cfg["v24916_lineage_context"] = {
        "schema": LINEAGE_SCHEMA,
        "enabled": True,
        "new_lineage": False,
        "continuation_from_parent": True,
        "parent_checkpoint": EXPECTED_PARENT_CHECKPOINT,
        "parent_semantic_state_hash": EXPECTED_PARENT_SEMANTIC_STATE_HASH,
        "accepted_count_start": EXPECTED_ACCEPTED_COUNT,
        "outer_cycle_start": EXPECTED_OUTER_CYCLE,
        "resume_substep": EXPECTED_RESUME_SUBSTEP,
        "resume_generation_completed": True,
        "resume_generation_changed": True,
        "resume_td_completed": False,
        "max_outer_cycles": EXPECTED_MAX_OUTER_CYCLES,
        "wall_clock_limit_disabled": True,
        "fresh_recovery_path_epoch_required": True,
        "cross_run_path_cache_restore_allowed": False,
        "generation_targeting_activation": "NEXT_GENERATION_SUBSTEP_AFTER_RESUMED_CYCLE3_TD",
        "td_targeting_activation": "RESUMED_CYCLE3_TD_AFTER_FRESH_RECOVERY_PATH_ENUMERATION",
        "supply_locked_until_parent_demand_convergence": True,
        "authority_file": AUTHORITY_FILE,
        "active_v24916_actuators": [
            "GENERATION_FLOWBUNDLE_TARGETING", "TD_COMPONENT_MASK"
        ],
        "parent_reviewed_fields_modified": False,
    }
    cfg["v24916_lineage_context_hash"] = _hash(cfg["v24916_lineage_context"])
    cfg["v24916_flowbundle_skim_runtime_hash"] = _hash(cfg["v24916_flowbundle_skim_runtime"])
    cfg["v24916_demand_evidence_targeting_hash"] = _hash(cfg["demand_evidence_targeting"])
    build_safety_contract(cfg)
    return cfg


def validate_active_runtime_delta(child: Mapping[str, Any], parent: Mapping[str, Any]) -> dict[str, Any]:
    expected = apply_active_runtime_delta(parent)
    if dict(child) != expected:
        keys = sorted(set(expected) | set(child))
        bad = [k for k in keys if child.get(k) != expected.get(k)]
        raise RuntimeError("V24916_A0004_ACTIVE_TARGETING_CONFIG_DELTA_MISMATCH:" + ",".join(bad[:20]))
    stripped = copy.deepcopy(dict(child))
    # Undo the explicit PROFILE488 gate correction before proving that every
    # other reviewed parent field is byte/semantic-equivalent to the parent cfg.
    for key in PROFILE488_GATE_CORRECTION:
        if key in parent:
            stripped[key] = parent[key]
        else:
            stripped.pop(key, None)
    for key in (
        "v24916_release_identity", "v24916_flowbundle_skim_runtime",
        "demand_evidence_targeting", "v24916_lineage_context",
        "v24916_lineage_context_hash", "v24916_flowbundle_skim_runtime_hash",
        "v24916_demand_evidence_targeting_hash",
    ):
        stripped.pop(key, None)
    if stripped != dict(parent):
        raise RuntimeError("V24916_A0004_ACTIVE_TARGETING_PARENT_REVIEWED_CONFIG_WAS_MODIFIED")
    safety = build_safety_contract(child)
    return {
        "schema": "R1_15A2_V24916_A0004_ACTIVE_TARGETING_CONFIG_DELTA_AUDIT_V1",
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "accepted_count_start": EXPECTED_ACCEPTED_COUNT,
        "outer_cycle_start": EXPECTED_OUTER_CYCLE,
        "resume_substep": EXPECTED_RESUME_SUBSTEP,
        "parent_reviewed_config_unchanged": True,
        "generation_targeting_enabled": True,
        "td_mask_enabled": True,
        "supply_targeting_enabled": False,
        "fresh_recovery_path_epoch_required": True,
        "cross_run_path_cache_restore_allowed": False,
        "parent_iofix1_preserved": True,
        "profile488_runtime_gate_correction": copy.deepcopy(PROFILE488_GATE_CORRECTION),
        "safety_contract_hash": safety.contract_hash,
    }


__all__ = [
    "RELEASE", "PACKAGE_REVISION", "AUTHORITY_FILE", "LINEAGE_SCHEMA",
    "EXPECTED_PARENT_CHECKPOINT", "EXPECTED_PARENT_SEMANTIC_STATE_HASH",
    "EXPECTED_ACCEPTED_COUNT", "EXPECTED_OUTER_CYCLE", "EXPECTED_RESUME_SUBSTEP",
    "EXPECTED_MAX_OUTER_CYCLES", "PROFILE488_GATE_CORRECTION",
    "V24916_ACTIVE_SECTION", "DEMAND_EVIDENCE_TARGETING",
    "apply_active_runtime_delta", "validate_active_runtime_delta",
]
