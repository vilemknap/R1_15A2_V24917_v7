# -*- coding: utf-8 -*-
"""Active V24916 Generation + TD targeting overlay for a fresh revised-EE lineage.

The certified V24915/PERF2C parent configuration is kept byte/methodology intact.
All V24916 settings are additive top-level namespaces tolerated by the parent
config drift gate.  Acceptance remains the parent fresh-assignment + 12D/11D
contract; FlowBundle/fresh assignment-path DIS skims only narrow candidate search.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

from r1_15a2_safety_v24916p2c import build_safety_contract

RELEASE = "R1_15A2_V24916_PERF2C_FRESH100_PROFILE488_FRESHCACHE_ACTIVE_TARGETING_P2P3_20261022"
PACKAGE_REVISION = "V24916_PERF2C_FRESH100_PROFILE488_FRESHCACHE_ACTIVE_TARGETING_P2P3"
AUTHORITY_FILE = "V24916_FRESH_BASELINE_LIVE_AUTHORITY.json"
FRESH_SCHEMA = "R1_15A2_V24916_FRESH100_PROFILE488_ACTIVE_TARGETING_RUNTIME_V1"

V24916_ACTIVE_SECTION = {
    "enabled": True,
    "activation_stage": "P2P3_ACTIVE_GENERATION_AND_TD_AFTER_LIVE_PREFLIGHT",
    "shadow_mode": False,
    "generation_targeting_enabled": True,
    "td_mask_enabled": True,
    "combined_enabled": True,
    "support_risk_gate_enabled": True,
    "supply_targeting_enabled": False,
    "shortest_imp_oracle_enabled": False,
    "targeted_augmentation_enabled": False,
    "cross_run_evidence_cache": False,
    "production_com_probing": False,
    "max_evidence_entries": 2,
    "flowbundle_top_k_od": 3000,
    "generation_outside_positive_factor": 0.20,
    "td_max_active_components": 4,
    "td_minimum_pressure": 0.0,
    "exact_zone_order_required": True,
    "exact_dist_km_identity_required": False,
    "dynamic_assignment_skim_enabled": True,
    "dynamic_distance_code": "DIS",
    "dynamic_distance_aggregation": "MEAN_OVER_ASSIGNMENT_PATH_VOLUME",
    "dynamic_skim_refresh_policy": "EVERY_TD_FINECDF_EVALUATION_AND_EVERY_FRESH_ASSIGNMENT",
    "static_r1_osrm_dist_km_role": "REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION",
    "full_matrix_retention_forbidden": True,
    "flowbundle_role": "ACTIVE_SEARCH_TARGETING_ONLY_NOT_ACCEPTANCE",
    "skim_role": "ACTIVE_TD_CALIBRATION_DISTANCE_AUTHORITY_FROM_FRESH_ASSIGNMENT",
    "acceptance_authority": "UNCHANGED_PARENT_FRESH_ASSIGNMENT_PLUS_LIVE_12D_11D",
    "post_r3a_parent_freeze_required_before_live_activation": False,
    "fresh_baseline_live_authority_required": True,
    "active_targeting_certified": True,
}

# Ported from the audited V24916 donor, with EXOG_EE kept diagnostic-only.
DEMAND_EVIDENCE_TARGETING = {
    "authority_role": "TARGETING_OBSERVABILITY_ONLY_PATH_INCIDENCE_REMAINS_NUMERICAL_AUTHORITY",
    "enabled": True,
    "flowbundle": {
        "active_link_toggle_allowed": False,
        "enabled": True,
        "fallback": "PATH_ONLY_PROFILE_LOCAL_THEN_GLOBAL",
        "max_od_rows_per_profile": 3000,
        "max_profiles": 12,
        "min_od_volume": 0.01,
        "min_profile_abs_residual": 300.0,
        "min_profile_geh": 10.0,
        "minimum_profile_coverage": 0.70,
        "od_parity_absolute_tolerance": 5.0,
        "od_parity_relative_tolerance": 0.10,
        "path_parity_absolute_tolerance": 2.0,
        "path_parity_relative_tolerance": 0.02,
        "retained_volume_coverage": 0.90,
        "runtime_method_probing": False,
        "sealed_com_contract": "PTV_VISUM_2026_FLOWBUNDLE_LINK_DSEG_V24916_V1",
    },
    "flowbundle_optional_diagnostic_dsegs": [
        "EXOG_EE_CW", "EXOG_EE_CW_noT", "EXOG_EE_CS", "EXOG_EE_CS_noT"
    ],
    "flowbundle_target_dsegs": [
        "NATIVE_CW", "NATIVE_CW_noT", "NATIVE_CS", "NATIVE_CS_noT"
    ],
    "generation": {
        "enabled": True,
        "maximum_target_zones_per_family_role": 120,
        "negative_signed_step_multiplier": 1.0,
        "non_target_step_multiplier": 0.20,
        "require_supported_od": True,
        "target_step_multiplier": 1.0,
        "zone_targeting_role": "POSITIVE_UNDERLOAD_REGULARIZATION_DAMPING_ONLY",
    },
    "skim": {
        "automatic_calculation": True,
        "calculation_source": "CONFIGURED_ACTIVE_VISUM_PRT_SKIM_PROCEDURES_AFTER_FRESH_ASSIGNMENT",
        "distance_code": "DIS",
        "required_native_dsegs": ["NATIVE_CW", "NATIVE_CW_noT", "NATIVE_CS", "NATIVE_CS_noT", "NATIVE_CL", "NATIVE_CF"],
        "finite_nonnegative_required": True,
        "static_r1_osrm_dist_km_role": "REFERENCE_ONLY",
        "assignment_epoch_binding_required": True,
        "optional_role": "SHADOW_DIAGNOSTIC_ONLY",
        "zone_order_hash_required": True,
    },
    "support_risk": {
        "baseline_policy": "MANDATORY_ENUMERATION_UNCHANGED",
        "candidate_induced_policy": "REJECT_ROLLBACK_NO_IMMEDIATE_REENUMERATION",
        "final_plateau_policy": "FRESH_ENUMERATION_PROOF_UNCHANGED",
        "min_volume": 1.0e-5,
        "skim_gap_role": "SHADOW_DIAGNOSTIC_NOT_HARD_TRIGGER",
    },
    "td": {
        "distance_bin_edges_km": [5, 10, 20, 30, 50, 75, 100],
        "enabled": True,
        "families": ["WORK", "SERVICE"],
        "finecdf_v19_algorithm_and_targets_unchanged": True,
        "finecdf_distance_authority": "DYNAMIC_ASSIGNMENT_DIS_KM",
        "fresh_assignment_and_skims_per_finecdf_evaluation": True,
        "global_11d_evaluation_required": True,
        "max_active_components_per_family": 2,
        "max_active_components_total": 4,
        "minimum_alignment_score": 0.0,
        "school_long_policy": "FROZEN_DURING_FLOWBUNDLE_TARGETED_PHASE",
    },
    "supply_enabled": False,
    "state_binding": "SEMANTIC_STATE_PLUS_ASSIGNMENT_PLUS_PATH_EPOCH_PLUS_SKIM_PLUS_CONFIG",
}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()


def apply_active_runtime_delta(base_cfg: Mapping[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(dict(base_cfg))
    cfg["v24916_release_identity"] = {
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "parent_release": str(base_cfg.get("release", "")),
        "parent_package_revision": str(base_cfg.get("package_revision", "")),
        "parent_reviewed_config_unchanged": True,
    }
    cfg["v24916_flowbundle_skim_runtime"] = copy.deepcopy(V24916_ACTIVE_SECTION)
    cfg["demand_evidence_targeting"] = copy.deepcopy(DEMAND_EVIDENCE_TARGETING)
    cfg["v24916_fresh_baseline"] = {
        "schema": FRESH_SCHEMA,
        "enabled": True,
        "new_lineage": True,
        "source_model": "CURRENT_OPEN_VISUM_VERSION",
        "accepted_count_start": 0,
        "outer_cycle_start": 1,
        "inherited_stationary_cycle_streak": 0,
        "inherited_checkpoint": False,
        "ignore_historical_adjacent_semantic_sidecar": True,
        "force_fresh_path_epoch": True,
        "historical_path_cache_restore_allowed": False,
        "supply_locked_until_new_demand_convergence": True,
        "baseline_revision_reason": "NEW_NETWORK_UPDATED_COUNTLOCATIONS_AND_EE_NEW_CALIBRATION_LINEAGE",
        "parent_fresh100_profile488_required": True,
        "parent_no_wallclock_required": True,
        "parent_freshcache_required": True,
        "authority_file": AUTHORITY_FILE,
        "active_v24916_actuators": ["GENERATION_FLOWBUNDLE_TARGETING", "TD_COMPONENT_MASK"],
        "parent_reviewed_fields_modified": False,
    }
    cfg["v24916_fresh_baseline_runtime_hash"] = _hash(cfg["v24916_fresh_baseline"])
    cfg["v24916_flowbundle_skim_runtime_hash"] = _hash(cfg["v24916_flowbundle_skim_runtime"])
    cfg["v24916_demand_evidence_targeting_hash"] = _hash(cfg["demand_evidence_targeting"])
    build_safety_contract(cfg)
    return cfg


def validate_active_runtime_delta(child: Mapping[str, Any], parent: Mapping[str, Any]) -> dict[str, Any]:
    expected = apply_active_runtime_delta(parent)
    if dict(child) != expected:
        keys = sorted(set(expected) | set(child))
        bad = [k for k in keys if child.get(k) != expected.get(k)]
        raise RuntimeError("V24916_ACTIVE_TARGETING_CONFIG_DELTA_MISMATCH:" + ",".join(bad[:20]))
    stripped = copy.deepcopy(dict(child))
    for key in (
        "v24916_release_identity", "v24916_flowbundle_skim_runtime",
        "demand_evidence_targeting", "v24916_fresh_baseline",
        "v24916_fresh_baseline_runtime_hash", "v24916_flowbundle_skim_runtime_hash",
        "v24916_demand_evidence_targeting_hash",
    ):
        stripped.pop(key, None)
    if stripped != dict(parent):
        raise RuntimeError("V24916_ACTIVE_TARGETING_PARENT_REVIEWED_CONFIG_WAS_MODIFIED")
    safety = build_safety_contract(child)
    return {
        "schema": "R1_15A2_V24916_ACTIVE_TARGETING_CONFIG_DELTA_AUDIT_V1",
        "passes": True,
        "release": RELEASE,
        "package_revision": PACKAGE_REVISION,
        "accepted_count_start": 0,
        "outer_cycle_start": 1,
        "parent_reviewed_config_unchanged": True,
        "generation_targeting_enabled": True,
        "td_mask_enabled": True,
        "supply_targeting_enabled": False,
        "force_fresh_path_epoch": True,
        "safety_contract_hash": safety.contract_hash,
    }


__all__ = [
    "RELEASE", "PACKAGE_REVISION", "AUTHORITY_FILE", "FRESH_SCHEMA",
    "V24916_ACTIVE_SECTION", "DEMAND_EVIDENCE_TARGETING",
    "apply_active_runtime_delta", "validate_active_runtime_delta",
]
