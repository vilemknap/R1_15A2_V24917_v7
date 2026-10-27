# -*- coding: utf-8 -*-
"""V2.4.8.5 stable project-root safety contract.

Retains the V2.4.8 zero-share and persistent-cache contracts while requiring
outermost prior-run-tree normalization and a fail-closed non-nesting postcondition.
"""
from __future__ import annotations
from r1_15a2_safety_v248 import *  # noqa: F401,F403
from r1_15a2_safety_v248 import validate_v248_config
from r1_15a2_supply import SupplyContractError

RELEASE = "R1_15A2_V2_4_8_5_STABLE_PROJECT_ROOT_20261016"
_SOURCE_RULES = {
    "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016":
        "5c7417c7cf33dd6426c4eda3937a5e84e4c17f8798403fca8333099948ccbf02",
    "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016":
        "724e98e85bf1b9a2391b34b33eb525e268440082f5ae59b4b629417b38b8de4f",
    "R1_15A2_V2_4_8_3_CACHE_COMPAT_HOTFIX_20261016":
        "d4629fdf4ccc0ddf3b48fa2f35db42c9079ae7bfff1943a025a13cc56a377be8",
    "R1_15A2_V2_4_8_4_RUN_ROOT_HOTFIX_20261016":
        "4137a6e922147cb1810d9249d835a995fa211723de29ed2098bfb90555c1695d",
}
_ALLOWED_MODULES = {
    "r1_15a2_two_mode_v238.py",
    "r1_15a2_trial_adapter_v240.py",
    "r1_15a2_persistent_path_cache_v248.py",
}


def validate_v2485_config(cfg, package_root=None):
    base = validate_v248_config(cfg, package_root)
    if cfg.get("release") != RELEASE or cfg.get("safety_gate_release") != RELEASE:
        raise SupplyContractError("V2485_RELEASE_IDENTITY_MISSING")

    stable = cfg.get("performance", {}).get("stable_project_root", {})
    if stable.get("enabled") is not True:
        raise SupplyContractError("V2485_STABLE_PROJECT_ROOT_DISABLED")
    if stable.get("selection") != "PARENT_OF_OUTERMOST_QUALIFYING_R1_15A2_*_RUNS_ANCESTOR":
        raise SupplyContractError("V2485_PROJECT_ROOT_SELECTION_CHANGED")
    if stable.get("qualifying_child_prefix") != "RUN_":
        raise SupplyContractError("V2485_RUN_TREE_QUALIFIER_CHANGED")
    if stable.get("reject_nested_new_run") is not True:
        raise SupplyContractError("V2485_NESTED_RUN_POSTCONDITION_DISABLED")
    if stable.get("plain_source_fallback") != "SOURCE_PARENT":
        raise SupplyContractError("V2485_PLAIN_SOURCE_FALLBACK_CHANGED")
    if stable.get("source_version_remains_immutable_authority") is not True:
        raise SupplyContractError("V2485_SOURCE_AUTHORITY_CHANGED")

    policy = cfg.get("two_mode", {}).get("zero_share_residual_policy", {})
    if policy.get("enabled") is not True:
        raise SupplyContractError("V2485_ZERO_SHARE_RESIDUAL_POLICY_DISABLED")
    if policy.get("action") != "EXCLUDE_FROM_GUIDANCE_PRESERVE_BASE_MARGINS":
        raise SupplyContractError("V2485_ZERO_SHARE_RESIDUAL_ACTION_CHANGED")
    if policy.get("requires_existing_geometry") is not True or policy.get("requires_path_volume_parity_pass") is not True:
        raise SupplyContractError("V2485_ZERO_SHARE_SAFETY_GATE_MISSING")
    if policy.get("acceptance_authority") != "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D":
        raise SupplyContractError("V2485_ACCEPTANCE_AUTHORITY_CHANGED")
    limit = policy.get("max_dseg_relative_volume")
    base_limit = cfg.get("dseg_path_volume_relative_tolerance")
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0.0 < float(limit) <= float(base_limit):
        raise SupplyContractError("V2485_ZERO_SHARE_RESIDUAL_TOLERANCE_INVALID")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    if compat.get("enabled") is not True or compat.get("target_release") != RELEASE:
        raise SupplyContractError("V2485_PREDECESSOR_CACHE_COMPATIBILITY_DISABLED")
    if compat.get("policy") != "READ_ONLY_EXACT_PREDECESSOR_STORE_WITH_ALL_NONCONSUMER_CONTRACT_FIELDS_EXACT":
        raise SupplyContractError("V2485_PREDECESSOR_CACHE_POLICY_CHANGED")
    if compat.get("allowed_contract_differences") != ["config_sha256", "path_implementation_files", "contract_hash"]:
        raise SupplyContractError("V2485_ALLOWED_CONTRACT_DIFFERENCES_CHANGED")
    predecessors = compat.get("predecessors")
    if not isinstance(predecessors, list) or len(predecessors) != len(_SOURCE_RULES):
        raise SupplyContractError("V2485_PREDECESSOR_RULE_COUNT_INVALID")
    seen = set()
    for row in predecessors:
        if not isinstance(row, dict):
            raise SupplyContractError("V2485_PREDECESSOR_RULE_INVALID")
        release = row.get("source_release")
        if release not in _SOURCE_RULES or row.get("source_config_sha256") != _SOURCE_RULES[release]:
            raise SupplyContractError("V2485_PREDECESSOR_IDENTITY_CHANGED")
        impl = row.get("source_path_implementation_files")
        if (not isinstance(impl, dict) or set(impl) != _ALLOWED_MODULES or
                any(not isinstance(v, str) or len(v) != 64 for v in impl.values())):
            raise SupplyContractError("V2485_PREDECESSOR_MODULE_HASH_SET_INVALID")
        seen.add(release)
    if seen != set(_SOURCE_RULES):
        raise SupplyContractError("V2485_PREDECESSOR_RULE_MISSING")

    impl = cfg.get("implementation_files", {})
    for name in ("r1_15a2_safety_v2485.py", "r1_15a2_persistent_path_cache_v248.py",
                 "r1_15a2_trial_adapter_v240.py", "r1_15a2_two_mode_v238.py"):
        if not isinstance(impl.get(name), str) or len(impl[name]) != 64:
            raise SupplyContractError("V2485_IMPLEMENTATION_HASH_MISSING:" + name)
    return dict(base, zero_share_residual_policy=policy,
                explicit_predecessor_read_compatibility=compat,
                stable_project_root=stable)


__all__ = ["validate_v2485_config"]
