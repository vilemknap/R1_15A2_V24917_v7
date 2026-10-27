# -*- coding: utf-8 -*-
"""V24917 config delta on top of the V24916 PROFILE488FIX1 delta.

Only two additive config sections are introduced:
  * v24917_targeted_generation  - targeted catch-up Generation policy
  * v24917_release_identity     - release/feature identity
Every inherited field is proven unchanged by delegating to the V24916
validator on the config with these two sections removed.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

import r1_15a2_profile488_gatefix_v24916p2c as parent_delta
import r1_15a2_targeted_generation_v24917 as tg
import r1_15a2_profile_roster_v24917 as roster

RELEASE = "R1_15A2_V24917_GENFIX2_TDJOINT1_20261027"
PACKAGE_REVISION = "V24917_GENFIX2_TDJOINT1_20261027"
V24917_KEYS = ("v24917_targeted_generation", "v24917_release_identity")


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
            "COEFFICIENT_ENVELOPE_0_25_TO_5",
            "FLOWBUNDLE_EVIDENCE_PUBLISH_FIX",
            "GENERATION_GATE_NONFATAL",
            "SPARSE_TD_AND_STATIONARY_EARLY_STOP",
            "DIAGFAST_V2_DIRECT_GUARD",
            "GENFIX1_TRANSIENT_SAFE_EXACT_SNAPSHOT_READS",
            "GENFIX1_LIVE_GENERATION_PARENT_DIFF",
            "GENFIX1_RECOVERY_OWNERSHIP_UNTIL_VERIFIED_RECOMPUTE",
            "GENFIX2_VERIFIED_PARENT_RECOVERY_ALL_DOMAINS",
            "GENFIX2_MOBILITY_FINAL_AND_LIVE_GUARD",
            "GENFIX2_FINAL_EFFECT_PREDICTION_COM_AND_ARCHIVE_SAFETY",
            "TDJOINT1_SINGLE_SHARED_SCORE_BOUNDED_COMPONENT_POLL",
            "TDJOINT1_ISOLATED_REALIZATION_AFTER_VERIFIED_PLATEAU",
        ],
        "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
        "acceptance_thresholds_changed_by_v24917": False,
        "parent_files_modified": False,
    }


def apply_active_runtime_delta(parent_cfg: Mapping[str, Any]) -> dict:
    cfg = parent_delta.apply_active_runtime_delta(parent_cfg)
    cfg["v24917_targeted_generation"] = tg.validate_policy(tg.DEFAULT_POLICY)
    ident = identity()
    ident["policy_hash"] = _hash(cfg["v24917_targeted_generation"])
    cfg["v24917_release_identity"] = ident
    roster.apply_cfg(cfg)
    return cfg


def validate_active_runtime_delta(child: Mapping[str, Any], parent: Mapping[str, Any]) -> dict:
    base_child = roster.strip_cfg({k: v for k, v in dict(child).items() if k not in V24917_KEYS})
    result = dict(parent_delta.validate_active_runtime_delta(base_child, parent))
    policy = tg.validate_policy(child.get("v24917_targeted_generation") or {})
    if policy != tg.validate_policy(tg.DEFAULT_POLICY):
        raise RuntimeError("V24917_POLICY_DIFFERS_FROM_SEALED_DEFAULT")
    ident = dict(child.get("v24917_release_identity") or {})
    if ident.get("release") != RELEASE or ident.get("policy_hash") != _hash(policy):
        raise RuntimeError("V24917_RELEASE_IDENTITY_MISMATCH")
    result["v24917"] = {"passes": True, "release": RELEASE,
                        "policy_hash": ident["policy_hash"],
                        "inherited_fields_unchanged": True,
                        "profile_roster": dict(child.get(roster.CFG_KEY) or {"enabled": False})}
    return result


__all__ = ["RELEASE", "PACKAGE_REVISION", "V24917_KEYS", "apply_active_runtime_delta",
           "validate_active_runtime_delta", "identity"]
