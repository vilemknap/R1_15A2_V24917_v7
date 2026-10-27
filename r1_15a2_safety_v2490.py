# -*- coding: utf-8 -*-
"""V2.4.9.0 soft-reference TD and tolerant-readback safety contract."""
from __future__ import annotations

import copy
from pathlib import Path

from r1_15a2_safety_v2488 import _SOURCE_CONFIG_DIGESTS as V2488_SOURCE_CONFIG_DIGESTS
from r1_15a2_safety_v2489 import (
    RELEASE as V2489_RELEASE,
    validate_v2489_config,
)
from r1_15a2_supply import SupplyContractError
import r1_15a2_runtime_v1 as rt

RELEASE = "R1_15A2_V2_4_9_0_TD_SOFT_REFERENCE_20261017"
V2489_CONFIG_SHA256 = "801a264a5cc5d1bce0cc5de58a6a827a18d0e616e00b8ebfb572e76038de33c3"
V2489_PATH_IMPLEMENTATION_FILES = {
    "r1_15a2_two_mode_v238.py": "a58980069e942b6782f6d906443e81922f81e6596eb5de5be456719f96ce15ad",
    "r1_15a2_trial_adapter_v240.py": "f55e7e4936bb93770fb7ff99d6a485a0695575f1e6c59ba44552e2163c857109",
    "r1_15a2_persistent_path_cache_v248.py": "78522a1a9d7bd4bcabfb360604fd9c0a6d3415e0d845d935e7c3084aeedb276c",
    "r1_15a2_sequence_v23.py": "91a3c65e7c38a56dbb560d5debe91235ae10637176de16f08b29ccd09ff5a983",
    "r1_15a2_supply.py": "c35e6440b63bbc9ba2ec060ef77543d420e0411b5b463dee8479171e0a46198e",
    "r1_15a2_core.py": "f8c46886dc5fead310812f053037e005bee3c4bb641aa9439f11f222fb9976d7",
    "r1_15a2_runtime_v1.py": "eed25b8dc78ca2c256b6d67a4893cdbb8acae4fb80f529ff10254054bb7c14f9",
}
V19_REL = "reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py"
V19_SHA256 = "fcdfa535940296e6cc793b6416c7c0a56c18aae8d5d20beddb064a170c673ff5"
V19_ID = "R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_V1_9_20261017"


def _require(condition, code):
    if not condition:
        raise SupplyContractError(code)


def _validate_inherited_v2489_contract(cfg, package_root):
    inherited = copy.deepcopy(cfg)
    inherited["release"] = V2489_RELEASE
    inherited["safety_gate_release"] = V2489_RELEASE
    inherited.setdefault("performance", {})["release"] = "V2.4.8"
    compat = inherited["performance"]["persistent_path_cache"][
        "explicit_predecessor_read_compatibility"]
    compat["target_release"] = V2489_RELEASE
    compat["predecessors"] = [
        r for r in compat["predecessors"]
        if r.get("source_release") != V2489_RELEASE]
    fine = inherited["coupled_demand"]["finecdf_td"]
    # Reconstruct the exact predecessor scientific contract only for inherited
    # validation. V2.4.9.0 itself remains bound to the hash-locked v1.9 source.
    fine["reference_script"] = "reference_v18/R1_BC_AUTO_DIST_ONLY_FINECDF_ADAPTIVE_v1_8.py"
    fine["reference_sha256"] = "abeb746ff49ac1f0e548e6b7945ec476e5c5e80897e6be1da6e2d42ae442d7d5"
    fine["reference_script_id"] = "R1_BC_AUTO_DIST_ONLY_FINECDF_ADAPTIVE_V1_8_20261016"
    fine["realization_retry_policy"] = "NATIVE_20B_IPF_NONCONVERGENCE_ONLY"
    fine["realization_exhaustion_policy"] = "FAIL_CLOSED_NOT_PLATEAU"
    tdreal = inherited.get("td_realization_stabilization", {})
    tdreal["retryable_error_class"] = "NATIVE_20B_IPF_NONCONVERGENCE_ONLY"
    tdreal["exhaustion_policy"] = "FAIL_CLOSED_NOT_STATIONARITY"
    return validate_v2489_config(inherited, package_root)


def validate_v2490_config(cfg, package_root=None):
    base = _validate_inherited_v2489_contract(cfg, package_root)
    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V2490_RELEASE_IDENTITY_MISSING")

    fine = cfg.get("coupled_demand", {}).get("finecdf_td", {})
    _require(fine.get("reference_script") == V19_REL,
             "V2490_FINECDF_V19_PATH_CHANGED")
    _require(fine.get("reference_sha256") == V19_SHA256 and
             fine.get("reference_script_id") == V19_ID,
             "V2490_FINECDF_V19_AUTHORITY_CHANGED")
    if package_root is not None:
        ref = Path(package_root) / V19_REL
        _require(ref.is_file() and rt.sha256_file(ref) == V19_SHA256,
                 "V2490_FINECDF_V19_FILE_HASH_MISMATCH")
    _require(fine.get("survey_reference_role") ==
             "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT" and
             fine.get("exact_curve_match_required") is False,
             "V2490_SURVEY_SOFT_REFERENCE_DISABLED")
    _require(fine.get("realization_retry_policy") ==
             "NATIVE_20B_IPF_NONCONVERGENCE_OR_SOFT_ACCEPTANCE_BACKTRACK",
             "V2490_TD_RETRY_POLICY_CHANGED")
    _require(fine.get("ipf_tolerance_policy") ==
             "UNCHANGED_NEVER_RELAXED_BY_CALIBRATOR",
             "V2490_IPF_TOLERANCE_POLICY_CHANGED")
    _require(fine.get("realization_exhaustion_policy") ==
             "SOFT_ACCEPTANCE_EXHAUSTION_IS_VERIFIED_PARENT_PLATEAU; NATIVE_IPF_EXHAUSTION_FAILS_CLOSED",
             "V2490_TD_EXHAUSTION_POLICY_CHANGED")
    atol = fine.get("realization_parameter_atol")
    rtol = fine.get("realization_parameter_rtol")
    _require(isinstance(atol, (int, float)) and not isinstance(atol, bool) and
             0.0 <= float(atol) <= 1.0e-8,
             "V2490_TD_PARAMETER_ATOL_TOO_WIDE")
    _require(isinstance(rtol, (int, float)) and not isinstance(rtol, bool) and
             0.0 <= float(rtol) <= 1.0e-10,
             "V2490_TD_PARAMETER_RTOL_TOO_WIDE")

    soft = cfg.get("td_soft_reference_policy", {})
    _require(soft.get("enabled") is True and
             soft.get("survey_reference_role") ==
             "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT" and
             soft.get("exact_curve_match_required") is False,
             "V2490_SOFT_REFERENCE_POLICY_DISABLED")
    _require(soft.get("native_ipf_tolerance_relaxed") is False,
             "V2490_NATIVE_IPF_TOLERANCE_RELAXED")
    expected_soft = {
        "aggregate_selected_min_relative_improvement": 0.005,
        "selected_component_max_relative_degradation": 0.05,
        "nonselected_component_max_relative_degradation": 0.05,
        "global_idp_mean_max_absolute_degradation": 0.01,
        "global_idp_component_max_absolute_degradation": 0.05,
        "inner_min_relative_improvement": 0.001,
    }
    for key, expected in expected_soft.items():
        _require(abs(float(soft.get(key, -999.0)) - expected) <= 1e-15,
                 "V2490_SOFT_REFERENCE_THRESHOLD_CHANGED:" + key)

    td = cfg.get("td", {})
    _require(td.get("acceptance_policy") ==
             "AGGREGATE_SELECTED_IMPROVEMENT_WITH_BOUNDED_COMPONENT_TRADEOFF",
             "V2490_TD_ACCEPTANCE_POLICY_CHANGED")
    _require(td.get("survey_reference_role") ==
             "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT" and
             td.get("exact_curve_match_required") is False,
             "V2490_TD_EXACT_FIT_REINTRODUCED")
    _require(abs(float(td.get("min_selected_component_relative_improvement")) - 0.005) <= 1e-15,
             "V2490_TD_AGGREGATE_IMPROVEMENT_CHANGED")
    _require(abs(float(td.get("max_selected_component_relative_degradation")) - 0.05) <= 1e-15 and
             abs(float(td.get("max_nonselected_component_objective_degradation")) - 0.05) <= 1e-15,
             "V2490_TD_COMPONENT_TRADEOFF_CHANGED")
    # Network/observation guards are deliberately NOT relaxed by the soft survey policy.
    _require(abs(float(td.get("max_cal_geh2_relative_degradation")) - 0.005) <= 1e-15,
             "V2490_CAL_COUNTS_GUARD_CHANGED")

    freeze = cfg.get("td_parameter_freeze_policy", {})
    _require(freeze.get("enabled") is True and
             freeze.get("comparison") ==
             "EXACT_FROZEN_CONTEXT_AND_METADATA__NUMERIC_B_C_ONLY",
             "V2490_TD_FREEZE_POLICY_CHANGED")
    _require(float(freeze.get("absolute_tolerance")) == float(atol) and
             float(freeze.get("relative_tolerance")) == float(rtol),
             "V2490_TD_FREEZE_TOLERANCE_INCONSISTENT")
    _require(freeze.get("unrequested_change_above_tolerance") == "FAIL_CLOSED",
             "V2490_TD_UNREQUESTED_CHANGE_NOT_FAIL_CLOSED")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V2490_CACHE_COMPAT_TARGET_CHANGED")
    predecessors = compat.get("predecessors")
    expected_sources = set(V2488_SOURCE_CONFIG_DIGESTS) | {
        "R1_15A2_V2_4_8_8_PATH_CACHE_SEMANTIC_COMPAT_20261016", V2489_RELEASE}
    _require(isinstance(predecessors, list) and
             {r.get("source_release") for r in predecessors} == expected_sources,
             "V2490_PREDECESSOR_SET_CHANGED")
    row = next((r for r in predecessors if r.get("source_release") == V2489_RELEASE), None)
    _require(row is not None and row.get("source_config_sha256s") == [V2489_CONFIG_SHA256],
             "V2490_V2489_CONFIG_PROVENANCE_NOT_PINNED")
    _require(row.get("source_path_implementation_files") == V2489_PATH_IMPLEMENTATION_FILES,
             "V2490_V2489_PATH_IMPLEMENTATION_NOT_PINNED")

    impl = cfg.get("implementation_files", {})
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_0.py",
        "r1_15a2_safety_v2490.py", "r1_15a2_overnight_controller_v242.py",
        "r1_15a2_finecdf_bridge_v242.py", V19_REL,
        "r1_15a2_runtime_v1.py", "r1_15a2_persistent_path_cache_v248.py",
    )
    for name in required:
        _require(isinstance(impl.get(name), str) and len(impl[name]) == 64,
                 "V2490_IMPLEMENTATION_HASH_MISSING:" + name)

    return {
        "passes": True,
        "base_contract": base,
        "survey_reference_role": soft["survey_reference_role"],
        "exact_curve_match_required": False,
        "soft_reference_thresholds": expected_soft,
        "td_parameter_freeze": freeze,
        "native_ipf_tolerance_relaxed": False,
        "v2489_predecessor_pinned": True,
    }


__all__ = ["validate_v2490_config"]
