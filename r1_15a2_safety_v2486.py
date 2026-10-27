# -*- coding: utf-8 -*-
"""V2.4.8.6 unified stable-root and generation-saturation safety contract.

Retains the V2.4.8 persistent-cache and zero-share contracts, requires the
outermost prior-run-tree normalization, and locks the bound-constrained
Generation projection introduced after the real V2.4.8.4 saturation failure.
"""
from __future__ import annotations

from r1_15a2_safety_v248 import *  # noqa: F401,F403
from r1_15a2_safety_v248 import validate_v248_config
from r1_15a2_supply import SupplyContractError

RELEASE = "R1_15A2_V2_4_8_6_UNIFIED_ROOT_SATURATION_20261016"
_SOURCE_RULES = {
    "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016":
        "5c7417c7cf33dd6426c4eda3937a5e84e4c17f8798403fca8333099948ccbf02",
    "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016":
        "724e98e85bf1b9a2391b34b33eb525e268440082f5ae59b4b629417b38b8de4f",
    "R1_15A2_V2_4_8_3_CACHE_COMPAT_HOTFIX_20261016":
        "d4629fdf4ccc0ddf3b48fa2f35db42c9079ae7bfff1943a025a13cc56a377be8",
    "R1_15A2_V2_4_8_4_RUN_ROOT_HOTFIX_20261016":
        "4137a6e922147cb1810d9249d835a995fa211723de29ed2098bfb90555c1695d",
    "R1_15A2_V2_4_8_5_STABLE_PROJECT_ROOT_20261016":
        "709d0eb18d65fdb5cc02a24cdeaf199f53dda63af143f34fb2eda15fbaa55613",
    "R1_15A2_V2_4_8_5_GENERATION_SATURATION_HOTFIX_20261016":
        "3315c25d3e9f0a1cd6088d47bc9276358ab24c3be4e127906a03da6758a8508f",
}
_ALLOWED_CACHE_MODULES = {
    "r1_15a2_two_mode_v238.py",
    "r1_15a2_trial_adapter_v240.py",
    "r1_15a2_persistent_path_cache_v248.py",
}


def _require(condition, code):
    if not condition:
        raise SupplyContractError(code)


def validate_v2486_config(cfg, package_root=None):
    base = validate_v248_config(cfg, package_root)
    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V2486_RELEASE_IDENTITY_MISSING")

    stable = cfg.get("performance", {}).get("stable_project_root", {})
    _require(stable.get("enabled") is True, "V2486_STABLE_PROJECT_ROOT_DISABLED")
    _require(stable.get("selection") == "PARENT_OF_OUTERMOST_QUALIFYING_R1_15A2_*_RUNS_ANCESTOR",
             "V2486_PROJECT_ROOT_SELECTION_CHANGED")
    _require(stable.get("qualifying_child_prefix") == "RUN_",
             "V2486_RUN_TREE_QUALIFIER_CHANGED")
    _require(stable.get("reject_nested_new_run") is True,
             "V2486_NESTED_RUN_POSTCONDITION_DISABLED")
    _require(stable.get("plain_source_fallback") == "SOURCE_PARENT",
             "V2486_PLAIN_SOURCE_FALLBACK_CHANGED")
    _require(stable.get("source_version_remains_immutable_authority") is True,
             "V2486_SOURCE_AUTHORITY_CHANGED")

    zero = cfg.get("two_mode", {}).get("zero_share_residual_policy", {})
    _require(zero.get("enabled") is True, "V2486_ZERO_SHARE_RESIDUAL_POLICY_DISABLED")
    _require(zero.get("action") == "EXCLUDE_FROM_GUIDANCE_PRESERVE_BASE_MARGINS",
             "V2486_ZERO_SHARE_RESIDUAL_ACTION_CHANGED")
    _require(zero.get("requires_existing_geometry") is True and
             zero.get("requires_path_volume_parity_pass") is True,
             "V2486_ZERO_SHARE_SAFETY_GATE_MISSING")
    _require(zero.get("acceptance_authority") == "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
             "V2486_ZERO_SHARE_ACCEPTANCE_AUTHORITY_CHANGED")
    limit = zero.get("max_dseg_relative_volume")
    base_limit = cfg.get("dseg_path_volume_relative_tolerance")
    _require(not isinstance(limit, bool) and isinstance(limit, (int, float)) and
             0.0 < float(limit) <= float(base_limit),
             "V2486_ZERO_SHARE_RESIDUAL_TOLERANCE_INVALID")

    generation = cfg.get("generation_bound_constrained_projection", {})
    _require(generation.get("enabled") is True,
             "V2486_GENERATION_BOUND_CONSTRAINT_DISABLED")
    _require(generation.get("mode") ==
             "DIRECT_ACTUATOR_CAPACITY_CLIP_THEN_SAME_FAMILY_ROLE_ATTENUATION",
             "V2486_GENERATION_BOUND_CONSTRAINT_MODE_CHANGED")
    _require(generation.get("preserve_spatial_pattern") is True,
             "V2486_GENERATION_SPATIAL_PATTERN_NOT_LOCKED")
    tol = generation.get("relative_balance_tolerance")
    _require(not isinstance(tol, bool) and isinstance(tol, (int, float)) and
             0.0 < float(tol) <= 1.0e-6,
             "V2486_GENERATION_BALANCE_TOLERANCE_INVALID")
    _require(generation.get("outward_bound_policy") == "CLIP_TO_EXACT_FEASIBLE_LOG_EFFECT",
             "V2486_GENERATION_BOUND_POLICY_CHANGED")
    _require(generation.get("role_balance_policy") ==
             "ATTENUATE_ONLY_LARGER_IMPLEMENTABLE_PA_SIDE",
             "V2486_GENERATION_ROLE_BALANCE_POLICY_CHANGED")
    _require(generation.get("opposite_sign_policy") ==
             "FAIL_CLOSED_UNCHANGED_GENERATION_GATE",
             "V2486_GENERATION_OPPOSITE_SIGN_POLICY_CHANGED")
    _require(generation.get("acceptance_authority") ==
             "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
             "V2486_GENERATION_ACCEPTANCE_AUTHORITY_CHANGED")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("enabled") is True and compat.get("target_release") == RELEASE,
             "V2486_PREDECESSOR_CACHE_COMPATIBILITY_DISABLED")
    _require(compat.get("policy") ==
             "READ_ONLY_EXACT_PREDECESSOR_STORE_WITH_ALL_NONCONSUMER_CONTRACT_FIELDS_EXACT",
             "V2486_PREDECESSOR_CACHE_POLICY_CHANGED")
    _require(compat.get("allowed_contract_differences") ==
             ["config_sha256", "path_implementation_files", "contract_hash"],
             "V2486_ALLOWED_CONTRACT_DIFFERENCES_CHANGED")
    predecessors = compat.get("predecessors")
    _require(isinstance(predecessors, list) and len(predecessors) == len(_SOURCE_RULES),
             "V2486_PREDECESSOR_RULE_COUNT_INVALID")
    seen = set()
    for row in predecessors:
        _require(isinstance(row, dict), "V2486_PREDECESSOR_RULE_INVALID")
        source_release = row.get("source_release")
        _require(source_release in _SOURCE_RULES and
                 row.get("source_config_sha256") == _SOURCE_RULES[source_release],
                 "V2486_PREDECESSOR_IDENTITY_CHANGED")
        impl = row.get("source_path_implementation_files")
        _require(isinstance(impl, dict) and set(impl) == _ALLOWED_CACHE_MODULES and
                 all(isinstance(value, str) and len(value) == 64 for value in impl.values()),
                 "V2486_PREDECESSOR_MODULE_HASH_SET_INVALID")
        seen.add(source_release)
    _require(seen == set(_SOURCE_RULES), "V2486_PREDECESSOR_RULE_MISSING")

    impl = cfg.get("implementation_files", {})
    required_impl = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_6.py",
        "r1_15a2_safety_v2486.py",
        "r1_15a2_multiblock.py",
        "r1_15a2_persistent_path_cache_v248.py",
        "r1_15a2_trial_adapter_v240.py",
        "r1_15a2_two_mode_v238.py",
    )
    for name in required_impl:
        _require(isinstance(impl.get(name), str) and len(impl[name]) == 64,
                 "V2486_IMPLEMENTATION_HASH_MISSING:" + name)

    return dict(
        base,
        zero_share_residual_policy=zero,
        generation_bound_constrained_projection=generation,
        explicit_predecessor_read_compatibility=compat,
        stable_project_root=stable,
    )


__all__ = ["validate_v2486_config"]
