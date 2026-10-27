# -*- coding: utf-8 -*-
"""Fail-closed safety gates for PERF2C R3 B0018 Demand extension 16..25."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError, canonical_hash

RELEASE = "R1_15A2_V24915_PERF2C_R3_B0018_DEMAND_EXTENSION_16_25_20261020"
PARENT_RELEASE = "R1_15A2_V2_4_9_15_PERF2C_R2_SINGLE_PASS_EXACT_SNAPSHOT_SUPPLY_TEMP_HOTFIX_20261020"
PACKAGE_REVISION = "V24915_PERF2C_R3_B0018_DEMAND_EXTENSION_16_25"
MANIFEST_FILE = "V24915_PERF2C_R3_OVERLAY_MANIFEST.json"
MANIFEST_SHA256 = "dee2e15b1ed761ddd94fdeaa6357bf30d3d171c47cd621057570645152042754"
CONTRACT_FILE = "V24915_PERF2C_R3_B0018_DEMAND_EXTENSION_CONTRACT.json"
CONTRACT_SHA256 = "85548aa7024b10f41f4ca8e10866d849547a2a8df4746706d0366c9acaae22e2"
AUTHORITY_FILE = "V24915_PERF2C_R3_B0018_DEMAND_EXTENSION_AUTHORITY.json"
AUTHORITY_SHA256 = "d2d3224f3e5e5f82c079285ff0a05594453c393d647cfab7bf9c2f854496941f"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canon(value: Any) -> str:
    return canonical_hash(value)


def preflight_v24915p2c3_overlay(package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    manifest_path = root / MANIFEST_FILE
    _require(manifest_path.is_file(), "V24915P2C3_MANIFEST_MISSING")
    _require(rt.sha256_file(manifest_path) == MANIFEST_SHA256,
             "V24915P2C3_MANIFEST_HASH_MISMATCH")
    manifest = rt.read_json(manifest_path)
    _require(manifest.get("schema") == "R1_15A2_V24915_PERF2C_R3_OVERLAY_MANIFEST_V1",
             "V24915P2C3_MANIFEST_SCHEMA_MISMATCH")
    _require(manifest.get("release") == RELEASE and
             manifest.get("parent_release") == PARENT_RELEASE and
             manifest.get("package_revision") == PACKAGE_REVISION,
             "V24915P2C3_MANIFEST_IDENTITY_MISMATCH")
    failures=[]; checked=0
    for row in manifest.get("files", []):
        rel=str(row.get("path", "")); path=root / rel
        if not rel or not path.is_file():
            failures.append({"path":rel,"reason":"MISSING"}); continue
        checked += 1
        if int(path.stat().st_size) != int(row.get("size", -1)):
            failures.append({"path":rel,"reason":"SIZE_MISMATCH"})
        elif rt.sha256_file(path) != row.get("sha256"):
            failures.append({"path":rel,"reason":"SHA256_MISMATCH"})
    _require(not failures, "V24915P2C3_MANIFEST_INVALID:"+json.dumps(failures,sort_keys=True))
    for name, digest, code in (
        (CONTRACT_FILE, CONTRACT_SHA256, "CONTRACT"),
        (AUTHORITY_FILE, AUTHORITY_SHA256, "AUTHORITY"),
    ):
        path=root/name
        _require(path.is_file() and rt.sha256_file(path)==digest,
                 "V24915P2C3_%s_HASH_MISMATCH" % code)
    contract=rt.read_json(root/CONTRACT_FILE)
    _require(contract.get("outer_cycle_start")==16 and contract.get("outer_cycle_end")==25 and
             contract.get("outer_cycle_count")==10,
             "V24915P2C3_CONTRACT_CYCLE_RANGE_MISMATCH")
    _require(contract.get("supply_locked_through_extension") is True and
             contract.get("review_required_after_cycle_25") is True,
             "V24915P2C3_CONTRACT_SUPPLY_LOCK_MISSING")
    for key in (
        "generation_step_math_changed", "generation_candidate_direction_math_changed",
        "td_math_changed", "td_realization_scales_changed", "assignment_method_changed",
        "assignment_gap_changed", "geh_acceptance_changed", "idp_acceptance_changed",
        "guard_policy_changed", "early_exploration_acceptance_horizon_changed",
        "direct_od_writes_changed", "path_cache_semantics_changed",
        "snapshot_semantics_changed", "rollback_semantics_changed",
        "supply_candidate_math_changed",
    ):
        _require(contract.get(key) is False, "V24915P2C3_UNSAFE_CONTRACT_FLAG:"+key)
    from r1_15a2_demand_extension_b0018_v24915p2c3 import load_authority
    authority=load_authority(root)
    return {
        "passes": True, "release": RELEASE, "parent_release": PARENT_RELEASE,
        "package_revision": PACKAGE_REVISION, "files_checked": checked,
        "manifest_sha256": MANIFEST_SHA256, "contract_sha256": CONTRACT_SHA256,
        "authority_sha256": AUTHORITY_SHA256,
        "source_checkpoint": authority.get("source_checkpoint_name"),
        "outer_cycles": [16,25], "outer_cycle_count": 10,
        "supply_locked_during_extension": True,
        "generation_backtracking_scales": [1.0,0.5,0.25,0.125,0.0625],
    }


def validate_v24915p2c3_config_delta(child: Mapping[str, Any], base: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    """Prove exact four-field runtime delta over the already validated R2 config."""
    c=copy.deepcopy(dict(child)); b=copy.deepcopy(dict(base))
    _require(int(b.get("coupled_demand",{}).get("max_outer_cycles",-1))==50,
             "V24915P2C3_PARENT_OUTER_CAP_NOT_50")
    _require(int(b.get("coupled_demand",{}).get("min_stationary_cycles",-1))==2,
             "V24915P2C3_PARENT_STATIONARITY_NOT_2")
    _require(b.get("backtracking_scales")==[1.0,0.5,0.25],
             "V24915P2C3_PARENT_GENERATION_SCALES_DRIFT")
    _require(int(b.get("trial_calibration",{}).get("max_trials_per_block",{}).get("GENERATION",-1))==3,
             "V24915P2C3_PARENT_GENERATION_TRIAL_CAP_DRIFT")

    _require(int(c.get("coupled_demand",{}).get("max_outer_cycles",-1))==25,
             "V24915P2C3_CHILD_OUTER_CAP_NOT_25")
    _require(int(c.get("coupled_demand",{}).get("min_stationary_cycles",-1))==11,
             "V24915P2C3_SUPPLY_LOCK_STATIONARITY_NOT_11")
    _require(c.get("backtracking_scales")==[1.0,0.5,0.25,0.125,0.0625],
             "V24915P2C3_CHILD_GENERATION_SCALES_MISMATCH")
    _require(int(c.get("trial_calibration",{}).get("max_trials_per_block",{}).get("GENERATION",-1))==5,
             "V24915P2C3_CHILD_GENERATION_TRIAL_CAP_NOT_5")
    _require(int(c.get("early_exploration_acceptance",{}).get("through_outer_cycle",-1))==12,
             "V24915P2C3_EARLY_ACCEPTANCE_HORIZON_DRIFT")
    td_scales=c.get("coupled_demand",{}).get("finecdf_td",{}).get("realization_backtracking_scales")
    _require(td_scales==b.get("coupled_demand",{}).get("finecdf_td",{}).get("realization_backtracking_scales"),
             "V24915P2C3_TD_REALIZATION_SCALES_DRIFT")
    _require(int(c.get("coupled_demand",{}).get("finecdf_td",{}).get("progressive_schedule",[])[-1].get("through_outer_cycle",-1))>=25,
             "V24915P2C3_FINECDF_SCHEDULE_DOES_NOT_COVER_25")
    _require(int(c.get("performance",{}).get("generation_step_schedule",[])[-1].get("through_outer_cycle",-1))>=25,
             "V24915P2C3_GENERATION_SCHEDULE_DOES_NOT_COVER_25")
    ext=c.get("v24915_perf2c_r3_demand_extension") or {}
    _require(ext.get("enabled") is True and ext.get("outer_cycle_start")==16 and
             ext.get("outer_cycle_end")==25 and ext.get("outer_cycle_count")==10 and
             ext.get("supply_locked_during_extension") is True,
             "V24915P2C3_RUNTIME_EXTENSION_METADATA_INVALID")

    # Normalize exactly the reviewed child dimensions and demand-extension metadata.
    c["coupled_demand"]["max_outer_cycles"] = b["coupled_demand"]["max_outer_cycles"]
    c["coupled_demand"]["min_stationary_cycles"] = b["coupled_demand"]["min_stationary_cycles"]
    c["backtracking_scales"] = copy.deepcopy(b["backtracking_scales"])
    c["trial_calibration"]["max_trials_per_block"]["GENERATION"] = b["trial_calibration"]["max_trials_per_block"]["GENERATION"]
    c.pop("v24915_perf2c_r3_demand_extension", None)
    c.pop("v24915_perf2c_r3_overlay_revision", None)
    _require(_canon(c)==_canon(b), "V24915P2C3_UNREVIEWED_CONFIG_DRIFT")
    preflight_v24915p2c3_overlay(package_root)
    return {"passes":True,"outer_cycles":[16,25],"count":10,"supply_locked":True}


__all__=[
    "RELEASE","PARENT_RELEASE","PACKAGE_REVISION","MANIFEST_FILE","MANIFEST_SHA256",
    "CONTRACT_FILE","CONTRACT_SHA256","AUTHORITY_FILE","AUTHORITY_SHA256",
    "preflight_v24915p2c3_overlay","validate_v24915p2c3_config_delta",
]
