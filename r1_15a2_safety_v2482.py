# -*- coding: utf-8 -*-
"""V2.4.8.2 zero-share residual live-run safety contract."""
from __future__ import annotations
from r1_15a2_safety_v248 import *  # noqa: F401,F403
from r1_15a2_safety_v248 import validate_v248_config
from r1_15a2_supply import SupplyContractError

RELEASE = "R1_15A2_V2_4_8_2_ZERO_SHARE_RESIDUAL_HOTFIX_20261016"

def validate_v2482_config(cfg, package_root=None):
    base = validate_v248_config(cfg, package_root)
    if cfg.get("release") != RELEASE or cfg.get("safety_gate_release") != RELEASE:
        raise SupplyContractError("V2482_RELEASE_IDENTITY_MISSING")
    policy = cfg.get("two_mode", {}).get("zero_share_residual_policy", {})
    if policy.get("enabled") is not True:
        raise SupplyContractError("V2482_ZERO_SHARE_RESIDUAL_POLICY_DISABLED")
    if policy.get("action") != "EXCLUDE_FROM_GUIDANCE_PRESERVE_BASE_MARGINS":
        raise SupplyContractError("V2482_ZERO_SHARE_RESIDUAL_ACTION_CHANGED")
    if policy.get("requires_existing_geometry") is not True:
        raise SupplyContractError("V2482_EXISTING_GEOMETRY_GATE_MISSING")
    if policy.get("requires_path_volume_parity_pass") is not True:
        raise SupplyContractError("V2482_PATH_PARITY_GATE_MISSING")
    if policy.get("acceptance_authority") != "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D":
        raise SupplyContractError("V2482_ACCEPTANCE_AUTHORITY_CHANGED")
    limit = policy.get("max_dseg_relative_volume")
    base_limit = cfg.get("dseg_path_volume_relative_tolerance")
    if isinstance(limit, bool) or not isinstance(limit, (int,float)) or not 0.0 < float(limit) <= float(base_limit):
        raise SupplyContractError("V2482_ZERO_SHARE_RESIDUAL_TOLERANCE_INVALID")
    expected = "EXISTING_GEOMETRY_ZERO_SAVED_SHARE_WITHIN_DSEG_PARITY_TOLERANCE_IS_GUIDANCE_EXCLUDED_NOT_REENUMERATED"
    if cfg.get("performance",{}).get("path_epochs",{}).get("zero_share_residual_policy") != expected:
        raise SupplyContractError("V2482_PATH_EPOCH_ZERO_SHARE_POLICY_MISSING")
    impl=cfg.get("implementation_files",{})
    for name in ("r1_15a2_safety_v2482.py","r1_15a2_two_mode_v238.py"):
        if not isinstance(impl.get(name),str) or len(impl[name]) != 64:
            raise SupplyContractError("V2482_IMPLEMENTATION_HASH_MISSING:"+name)
    return dict(base, zero_share_residual_policy=policy)

__all__ = ["validate_v2482_config"]
