# -*- coding: utf-8 -*-
"""Reviewed overnight-budget extension for V24915 PERF2 R4 continuation.

The historical restart authorities remain untouched.  This module first resolves
and verifies them exactly (A0009 or B0016), then extends only the *runtime outer
cycle budget* from 12 to 50.  Acceptance thresholds, stationarity, assignment,
FineCDF inner budgets and supply unlock semantics are unchanged.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Mapping

import r1_15a2_runtime_v1 as rt
import r1_15a2_demand_continuation_v24914 as a0009
import r1_15a2_demand_continuation_v24915r4 as b0016
from r1_15a2_supply import SupplyContractError

CONTRACT_FILE = "V24915_PERF2_R5_OVERNIGHT50_EXTENSION_CONTRACT.json"
CONTRACT_SHA256 = "f855f750e0c4b79a27c59b3c6adabde6f76c8879654543d5ba1348cc29656169"
SOURCE_MAX_LINEAGE_OUTER_CYCLE = 12
EXTENDED_MAX_LINEAGE_OUTER_CYCLE = 50
GLOBAL_RUNTIME_SECONDS = 64800.0


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _root(package_root=None) -> Path:
    return Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent


def load_extension_contract(package_root=None) -> Dict[str, Any]:
    root = _root(package_root)
    path = root / CONTRACT_FILE
    _require(path.is_file(), "V24915R5_OVERNIGHT50_CONTRACT_MISSING")
    _require(rt.sha256_file(path) == CONTRACT_SHA256,
             "V24915R5_OVERNIGHT50_CONTRACT_HASH_MISMATCH")
    obj = rt.read_json(path)
    _require(obj.get("schema") ==
             "R1_15A2_V24915_PERF2_R5_OVERNIGHT50_EXTENSION_CONTRACT_V1",
             "V24915R5_OVERNIGHT50_CONTRACT_SCHEMA_MISMATCH")
    _require(int(obj.get("source_lineage_outer_cycle_cap", -1)) == SOURCE_MAX_LINEAGE_OUTER_CYCLE,
             "V24915R5_OVERNIGHT50_SOURCE_CAP_MISMATCH")
    _require(int(obj.get("extended_lineage_outer_cycle_cap", -1)) == EXTENDED_MAX_LINEAGE_OUTER_CYCLE,
             "V24915R5_OVERNIGHT50_EXTENDED_CAP_MISMATCH")
    _require(float(obj.get("global_runtime_seconds", -1.0)) == GLOBAL_RUNTIME_SECONDS,
             "V24915R5_OVERNIGHT50_RUNTIME_MISMATCH")
    _require(int(obj.get("early_exploration_acceptance_through_outer_cycle", -1)) == 12,
             "V24915R5_OVERNIGHT50_ACCEPTANCE_HORIZON_DRIFT")
    for key in (
        "candidate_math_changed", "assignment_method_changed",
        "acceptance_thresholds_changed", "stationarity_rule_changed",
        "supply_unlock_rule_changed",
    ):
        _require(obj.get(key) is False, "V24915R5_OVERNIGHT50_UNREVIEWED_METHOD_CHANGE:" + key)
    return obj


def _extend(resolved: Mapping[str, Any], package_root=None) -> Dict[str, Any]:
    contract = load_extension_contract(package_root)
    out = copy.deepcopy(dict(resolved))
    source_cap = int(out.get("max_lineage_outer_cycle", -1))
    _require(source_cap == SOURCE_MAX_LINEAGE_OUTER_CYCLE,
             "V24915R5_OVERNIGHT50_RESOLVED_SOURCE_CAP_MISMATCH")
    out["source_max_lineage_outer_cycle"] = source_cap
    out["max_lineage_outer_cycle"] = EXTENDED_MAX_LINEAGE_OUTER_CYCLE
    out["overnight_budget_extension"] = {
        "schema": contract["schema"],
        "source_max_lineage_outer_cycle": SOURCE_MAX_LINEAGE_OUTER_CYCLE,
        "extended_max_lineage_outer_cycle": EXTENDED_MAX_LINEAGE_OUTER_CYCLE,
        "global_runtime_seconds": GLOBAL_RUNTIME_SECONDS,
        "acceptance_thresholds_changed": False,
        "stationarity_rule_changed": False,
        "supply_unlock_rule_changed": False,
        "early_exploration_acceptance_through_outer_cycle": 12,
        "post_cycle_12_acceptance": "EXISTING_V2495_FALLBACK_UNCHANGED",
    }
    out["mode"] = str(out.get("mode", "")) + "__OVERNIGHT50"
    return out


def matches_b0016_live_semantic(live_semantic: Mapping[str, Any], package_root=None) -> bool:
    return b0016.matches_live_semantic(live_semantic, package_root)


def resolve_b0016(source_version, live_semantic: Mapping[str, Any], package_root=None) -> Dict[str, Any]:
    return _extend(b0016.resolve_continuation(source_version, live_semantic, package_root), package_root)


def resolve_a0009(source_version, live_semantic: Mapping[str, Any], package_root=None) -> Dict[str, Any]:
    return _extend(a0009.resolve_continuation(source_version, live_semantic, package_root), package_root)


__all__ = [
    "CONTRACT_FILE", "CONTRACT_SHA256", "SOURCE_MAX_LINEAGE_OUTER_CYCLE",
    "EXTENDED_MAX_LINEAGE_OUTER_CYCLE", "GLOBAL_RUNTIME_SECONDS",
    "load_extension_contract", "matches_b0016_live_semantic",
    "resolve_b0016", "resolve_a0009",
]
