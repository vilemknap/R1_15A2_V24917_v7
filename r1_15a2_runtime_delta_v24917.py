# -*- coding: utf-8 -*-
"""V24917 config delta on top of the V24916 PROFILE488FIX1 delta.

Only two additive config sections are introduced:
  * v24917_targeted_generation  - targeted catch-up Generation policy
  * v24917_release_identity     - release/feature identity
The authorized Generation scope additionally includes LONG demand. Every other
inherited field is verified by the V24916 validator after reversing that exact
scope extension and removing the additive sections.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

import r1_15a2_profile488_gatefix_v24916p2c as parent_delta
import r1_15a2_targeted_generation_v24917 as tg
import r1_15a2_profile_roster_v24917 as roster

RELEASE = "R1_15A2_V24917_MOBILITYALLOC1_TDLONG1_LIVE_PENDING_20261027"
PACKAGE_REVISION = "V24917_MOBILITYALLOC1_TDLONG1_LIVE_PENDING_20261027"
V24917_KEYS = ("v24917_targeted_generation", "v24917_release_identity")


def long_generation_scope(scope):
    """Allow a LONG-only TG trial to prove changed demand through its own matrices."""
    out = copy.deepcopy(scope)
    for key, additions in (("dseg_codes", ("NATIVE_CL",)),
                           ("matrix_nos", tuple(range(9111, 9116)))):
        values = out.setdefault(key, [])
        for value in additions:
            if value not in values: values.append(value)
    return out


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False, default=str
                                     ).encode("utf-8")).hexdigest()


def identity() -> dict:
    return {
        "release": RELEASE, "package_revision": PACKAGE_REVISION,
        "parent_release": parent_delta.RELEASE,
        "features": [
            "V24917_ZONAL_COUNT_FIT_TARGETED_GENERATION",
            "CATCH_UP_PHASE_UNTIL_MODEL_OBS_0_80_PLUS50_MINUS20_PER_CYCLE",
            "GEN_DOMESTIC_WS_PROD_UPPER_3_ATT_UPPER_5_ZAHR_UNCHANGED",
            "FLOWBUNDLE_EVIDENCE_PUBLISH_FIX",
            "GENERATION_GATE_NONFATAL",
            "CONFIGURABLE_TD_SCHEDULING_AND_STATIONARY_EARLY_STOP",
            "DIAGFAST_V2_DIRECT_GUARD",
            "GENFIX1_TRANSIENT_SAFE_EXACT_SNAPSHOT_READS",
            "GENFIX1_LIVE_GENERATION_PARENT_DIFF",
            "GENFIX1_RECOVERY_OWNERSHIP_UNTIL_VERIFIED_RECOMPUTE",
            "GENFIX2_VERIFIED_PARENT_RECOVERY_ALL_DOMAINS",
            "GENFIX2_MOBILITY_FINAL_AND_LIVE_GUARD",
            "GENFIX2_FINAL_EFFECT_PREDICTION_COM_AND_ARCHIVE_SAFETY",
            "TDJOINT1_SINGLE_SHARED_SCORE_BOUNDED_COMPONENT_POLL",
            "TDJOINT1_ISOLATED_REALIZATION_AFTER_VERIFIED_PLATEAU",
            "MOBILITYALLOC1_ZONE_INDEPENDENT_LONG_GUARD_PROJECTION",
            "TDLONG1_HASH_BOUND_DISTANCE_MASK_AND_COMPONENT_PA_MAX_FLOW",
            "LONG_POST_TD_OSRM_GE80_MASK_WITHOUT_UPPER_BOUND",
            "LONG_ZONAL_GENERATION_SHARED_CACHE_LIVE_ACCEPTANCE",
        ],
        "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
        "acceptance_thresholds_changed_by_v24917": False,
        "parent_files_modified": False,  # role is tagged by V24917 only; byte-locked parent unchanged
    }


def apply_active_runtime_delta(parent_cfg: Mapping[str, Any]) -> dict:
    cfg = parent_delta.apply_active_runtime_delta(parent_cfg)
    cfg["v24917_targeted_generation"] = tg.validate_policy(tg.DEFAULT_POLICY)
    ident = identity()
    ident["policy_hash"] = _hash(cfg["v24917_targeted_generation"])
    cfg["v24917_release_identity"] = ident
    roster.apply_cfg(cfg)
    cfg["matrix_scope_by_block"]["GENERATION"] = long_generation_scope(
        cfg["matrix_scope_by_block"]["GENERATION"])
    return cfg


def validate_active_runtime_delta(child: Mapping[str, Any], parent: Mapping[str, Any]) -> dict:
    base_child = roster.strip_cfg({k: v for k, v in dict(child).items() if k not in V24917_KEYS})
    base_child = copy.deepcopy(base_child)
    original_scope = parent["matrix_scope_by_block"]["GENERATION"]
    if base_child["matrix_scope_by_block"]["GENERATION"] != long_generation_scope(original_scope):
        raise RuntimeError("V24917_LONG_GENERATION_SCOPE_MISMATCH")
    base_child["matrix_scope_by_block"]["GENERATION"] = copy.deepcopy(original_scope)
    result = dict(parent_delta.validate_active_runtime_delta(base_child, parent))
    policy = tg.validate_policy(child.get("v24917_targeted_generation") or {})
    if policy != tg.validate_policy(tg.DEFAULT_POLICY):
        raise RuntimeError("V24917_POLICY_DIFFERS_FROM_SEALED_DEFAULT")
    ident = dict(child.get("v24917_release_identity") or {})
    if ident.get("release") != RELEASE or ident.get("policy_hash") != _hash(policy):
        raise RuntimeError("V24917_RELEASE_IDENTITY_MISMATCH")
    result["v24917"] = {"passes": True, "release": RELEASE,
                        "policy_hash": ident["policy_hash"],
                        "inherited_fields_unchanged_except_long_generation_scope": True,
                        "long_generation_scope": child["matrix_scope_by_block"]["GENERATION"],
                        "profile_roster": dict(child.get(roster.CFG_KEY) or {"enabled": False})}
    return result


__all__ = ["RELEASE", "PACKAGE_REVISION", "V24917_KEYS", "apply_active_runtime_delta",
           "validate_active_runtime_delta", "identity"]
