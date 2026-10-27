# -*- coding: utf-8 -*-
"""V2.4.8.9 TD realization and rollback-evidence safety contract."""
from __future__ import annotations

import copy
from r1_15a2_safety_v2488 import (
    RELEASE as V2488_RELEASE, _PATH_IMPLEMENTATION_MODULES,
    _SOURCE_CONFIG_DIGESTS as V2488_SOURCE_CONFIG_DIGESTS,
    validate_v2488_config,
)
from r1_15a2_supply import SupplyContractError

RELEASE = 'R1_15A2_V2_4_8_9_TD_REALIZATION_STABILIZATION_20261016'
V2488_CONFIG_SHA256 = '0d8af79ad2f3cd069f9413a32cd4f3ab4f4d56042ca3ecb66b4c74a1c7d57a03'
V2488_PATH_IMPLEMENTATION_FILES = {
    "r1_15a2_two_mode_v238.py": "a58980069e942b6782f6d906443e81922f81e6596eb5de5be456719f96ce15ad",
    "r1_15a2_trial_adapter_v240.py": "f55e7e4936bb93770fb7ff99d6a485a0695575f1e6c59ba44552e2163c857109",
    "r1_15a2_persistent_path_cache_v248.py": "78522a1a9d7bd4bcabfb360604fd9c0a6d3415e0d845d935e7c3084aeedb276c",
    "r1_15a2_sequence_v23.py": "91a3c65e7c38a56dbb560d5debe91235ae10637176de16f08b29ccd09ff5a983",
    "r1_15a2_supply.py": "c35e6440b63bbc9ba2ec060ef77543d420e0411b5b463dee8479171e0a46198e",
    "r1_15a2_core.py": "f8c46886dc5fead310812f053037e005bee3c4bb641aa9439f11f222fb9976d7",
    "r1_15a2_runtime_v1.py": "9b9169f08bb5fb1e4c42dbb74ccee2b9aecbb849f21fcb32cbb71a7055117844"
}


def _require(condition, code):
    if not condition:
        raise SupplyContractError(code)


def _validate_inherited_v2488_contract(cfg, package_root):
    inherited = copy.deepcopy(cfg)
    inherited["release"] = V2488_RELEASE
    inherited["safety_gate_release"] = V2488_RELEASE
    compat = inherited["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    compat["target_release"] = V2488_RELEASE
    compat["predecessors"] = [
        r for r in compat["predecessors"] if r.get("source_release") != V2488_RELEASE]
    return validate_v2488_config(inherited, package_root)


def validate_v2489_config(cfg, package_root=None):
    base = _validate_inherited_v2488_contract(cfg, package_root)
    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V2489_RELEASE_IDENTITY_MISSING")

    fine = cfg.get("coupled_demand", {}).get("finecdf_td", {})
    _require(fine.get("realization_backtracking_enabled") is True,
             "V2489_TD_REALIZATION_BACKTRACKING_DISABLED")
    _require(fine.get("realization_backtracking_scales") == [1.0, 0.5, 0.25, 0.125, 0.0625],
             "V2489_TD_REALIZATION_SCALES_CHANGED")
    _require(fine.get("realization_coordinate_system") == "B_LINEAR_LOG_NEG_C",
             "V2489_TD_REALIZATION_COORDINATES_CHANGED")
    _require(fine.get("realization_retry_policy") == "NATIVE_20B_IPF_NONCONVERGENCE_ONLY",
             "V2489_TD_REALIZATION_RETRY_POLICY_CHANGED")
    _require(fine.get("ipf_tolerance_policy") == "UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR",
             "V2489_IPF_TOLERANCE_RELAXATION_NOT_FORBIDDEN")
    _require(fine.get("realization_parent_policy") ==
             "RESTORE_ACCEPTED_PARENT_BC_BEFORE_EACH_ATTEMPT",
             "V2489_TD_PARENT_RESTORE_POLICY_CHANGED")
    _require(fine.get("next_generation_gate") ==
             "TD_REALIZATION_MUST_COMPLETE_BEFORE_NEXT_GENERATION",
             "V2489_NEXT_GENERATION_GATE_MISSING")
    _require(fine.get("realization_exhaustion_policy") == "FAIL_CLOSED_NOT_PLATEAU",
             "V2489_TD_EXHAUSTION_POLICY_CHANGED")

    td = cfg.get("td_realization_stabilization", {})
    _require(td.get("enabled") is True and td.get("ipf_tolerance_relaxed") is False,
             "V2489_TD_REALIZATION_CONTRACT_DISABLED")
    _require(td.get("acceptance_authority") ==
             "FULL_DOWNSTREAM_NATIVE_RECOMPUTE_PLUS_LIVE_12D_11D",
             "V2489_TD_ACCEPTANCE_AUTHORITY_CHANGED")
    rollback = cfg.get("rollback_evidence_stabilization", {})
    _require(rollback.get("enabled") is True,
             "V2489_ROLLBACK_EVIDENCE_STABILIZATION_DISABLED")
    _require(rollback.get("copy_policy") == "ATOMIC_SIBLING_TEMP_THEN_OS_REPLACE",
             "V2489_ROLLBACK_COPY_POLICY_CHANGED")
    _require(rollback.get("path_policy") ==
             "IN_PLACE_WHEN_SAFE_ELSE_RUN_ROOT_CENTRAL_SHORT_MIRROR",
             "V2489_ROLLBACK_MIRROR_POLICY_CHANGED")
    _require(rollback.get("rollback_state_verification_required") is True,
             "V2489_ROLLBACK_STATE_VERIFICATION_DISABLED")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V2489_CACHE_COMPAT_TARGET_CHANGED")
    predecessors = compat.get("predecessors")
    expected_sources = set(V2488_SOURCE_CONFIG_DIGESTS) | {V2488_RELEASE}
    _require(isinstance(predecessors, list) and
             {r.get("source_release") for r in predecessors} == expected_sources,
             "V2489_PREDECESSOR_SET_CHANGED")
    row = next((r for r in predecessors if r.get("source_release") == V2488_RELEASE), None)
    _require(row is not None and row.get("source_config_sha256s") == [V2488_CONFIG_SHA256],
             "V2489_V2488_CONFIG_PROVENANCE_NOT_PINNED")
    _require(row.get("source_path_implementation_files") == V2488_PATH_IMPLEMENTATION_FILES,
             "V2489_V2488_PATH_IMPLEMENTATION_NOT_PINNED")

    impl = cfg.get("implementation_files", {})
    required = (
        'R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_9.py', "r1_15a2_safety_v2489.py",
        "r1_15a2_overnight_controller_v242.py", "r1_15a2_runtime_v1.py",
        "r1_15a2_persistent_path_cache_v248.py", "r1_15a2_trial_adapter_v240.py",
    )
    for name in required:
        _require(isinstance(impl.get(name), str) and len(impl[name]) == 64,
                 "V2489_IMPLEMENTATION_HASH_MISSING:" + name)

    return {
        "passes": True,
        "base_contract": base,
        "td_realization": td,
        "rollback_evidence": rollback,
        "v2488_predecessor_pinned": True,
        "ipf_tolerance_relaxed": False,
        "next_generation_requires_td_realization": True,
    }


__all__ = ["validate_v2489_config"]
