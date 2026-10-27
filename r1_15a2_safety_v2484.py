# -*- coding: utf-8 -*-
"""V2.4.8.4 run-root safety contract; retains exact predecessor-cache compatibility."""
from __future__ import annotations
from r1_15a2_safety_v248 import *  # noqa: F401,F403
from r1_15a2_safety_v248 import validate_v248_config
from r1_15a2_supply import SupplyContractError

RELEASE = 'R1_15A2_V2_4_8_4_RUN_ROOT_HOTFIX_20261016'
_SOURCE_RULES = {
    "R1_15A2_V2_4_8_1_LIVE_RUN_HOTFIX_20261016": "5c7417c7cf33dd6426c4eda3937a5e84e4c17f8798403fca8333099948ccbf02",
    "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016": "724e98e85bf1b9a2391b34b33eb525e268440082f5ae59b4b629417b38b8de4f",
}
_ALLOWED_MODULES = {
    "r1_15a2_two_mode_v238.py",
    "r1_15a2_trial_adapter_v240.py",
    "r1_15a2_persistent_path_cache_v248.py",
}

def validate_v2484_config(cfg, package_root=None):
    base = validate_v248_config(cfg, package_root)
    if cfg.get("release") != RELEASE or cfg.get("safety_gate_release") != RELEASE:
        raise SupplyContractError("V2484_RELEASE_IDENTITY_MISSING")
    policy = cfg.get("two_mode", {}).get("zero_share_residual_policy", {})
    if policy.get("enabled") is not True:
        raise SupplyContractError("V2484_ZERO_SHARE_RESIDUAL_POLICY_DISABLED")
    if policy.get("action") != "EXCLUDE_FROM_GUIDANCE_PRESERVE_BASE_MARGINS":
        raise SupplyContractError("V2484_ZERO_SHARE_RESIDUAL_ACTION_CHANGED")
    if policy.get("requires_existing_geometry") is not True or policy.get("requires_path_volume_parity_pass") is not True:
        raise SupplyContractError("V2484_ZERO_SHARE_SAFETY_GATE_MISSING")
    if policy.get("acceptance_authority") != "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D":
        raise SupplyContractError("V2484_ACCEPTANCE_AUTHORITY_CHANGED")
    limit = policy.get("max_dseg_relative_volume")
    base_limit = cfg.get("dseg_path_volume_relative_tolerance")
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0.0 < float(limit) <= float(base_limit):
        raise SupplyContractError("V2484_ZERO_SHARE_RESIDUAL_TOLERANCE_INVALID")
    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    if compat.get("enabled") is not True or compat.get("target_release") != RELEASE:
        raise SupplyContractError("V2484_PREDECESSOR_CACHE_COMPATIBILITY_DISABLED")
    if compat.get("policy") != "READ_ONLY_EXACT_PREDECESSOR_STORE_WITH_ALL_NONCONSUMER_CONTRACT_FIELDS_EXACT":
        raise SupplyContractError("V2484_PREDECESSOR_CACHE_POLICY_CHANGED")
    if compat.get("allowed_contract_differences") != ["config_sha256", "path_implementation_files", "contract_hash"]:
        raise SupplyContractError("V2484_ALLOWED_CONTRACT_DIFFERENCES_CHANGED")
    predecessors = compat.get("predecessors")
    if not isinstance(predecessors, list) or len(predecessors) != len(_SOURCE_RULES):
        raise SupplyContractError("V2484_PREDECESSOR_RULE_COUNT_INVALID")
    seen = set()
    for row in predecessors:
        if not isinstance(row, dict):
            raise SupplyContractError("V2484_PREDECESSOR_RULE_INVALID")
        release = row.get("source_release")
        if release not in _SOURCE_RULES or row.get("source_config_sha256") != _SOURCE_RULES[release]:
            raise SupplyContractError("V2484_PREDECESSOR_IDENTITY_CHANGED")
        impl = row.get("source_path_implementation_files")
        if not isinstance(impl, dict) or set(impl) != _ALLOWED_MODULES or any(not isinstance(v, str) or len(v) != 64 for v in impl.values()):
            raise SupplyContractError("V2484_PREDECESSOR_MODULE_HASH_SET_INVALID")
        seen.add(release)
    if seen != set(_SOURCE_RULES):
        raise SupplyContractError("V2484_PREDECESSOR_RULE_MISSING")
    impl = cfg.get("implementation_files", {})
    for name in ("r1_15a2_safety_v2484.py", "r1_15a2_persistent_path_cache_v248.py", "r1_15a2_trial_adapter_v240.py", "r1_15a2_two_mode_v238.py"):
        if not isinstance(impl.get(name), str) or len(impl[name]) != 64:
            raise SupplyContractError("V2484_IMPLEMENTATION_HASH_MISSING:" + name)
    return dict(base, zero_share_residual_policy=policy,
                explicit_predecessor_read_compatibility=compat)

__all__ = ["validate_v2484_config"]
