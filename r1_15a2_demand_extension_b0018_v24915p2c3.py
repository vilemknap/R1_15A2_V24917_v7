# -*- coding: utf-8 -*-
"""Fail-closed B0018 demand extension for PERF2C R3.

This module intentionally presents the small compatibility surface expected by
V24915 PERF2's existing continuation hook.  The parent launcher calls the
functions using historical B0016 names; internally they are strict B0018-only
resolvers.  A semantic mismatch never falls back to A0009/B0016.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Mapping

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError, canonical_hash

SCHEMA = "R1_15A2_V24915_PERF2C_R3_B0018_DEMAND_EXTENSION_AUTHORITY_V1"
AUTHORITY_FILE = "V24915_PERF2C_R3_B0018_DEMAND_EXTENSION_AUTHORITY.json"
AUTHORITY_SHA256 = "d2d3224f3e5e5f82c079285ff0a05594453c393d647cfab7bf9c2f854496941f"
EXPECTED_CHECKPOINT_NAME = "ACCEPTED_B_0018_3d57d34487ba.ver"
EXPECTED_SEMANTIC_STATE_HASH = "cef9b4247114a01e54d45b885f3321a0a22387fe67fc7c1dfdd44f9d1134590e"
EXPECTED_ACCEPTED_COUNT = 18
EXPECTED_NEXT_OUTER_CYCLE = 16
EXPECTED_MAX_LINEAGE_OUTER_CYCLE = 25
EXPECTED_GENERATION_REFERENCE_SHA256 = "57016672bc247a820075998e98453e7dd4155d6e5b3fd2dcdf752731f6c29e2c"
BOUNDED_INNER_BUDGET_STOP_REASONS = (
    "MAX_ITERATIONS",
    "TD_EVALUATION_BUDGET",
    "TD_INNER_TIME_BUDGET",
)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _root(package_root=None) -> Path:
    return Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent


def load_authority(package_root=None) -> Dict[str, Any]:
    root = _root(package_root)
    path = root / AUTHORITY_FILE
    _require(path.is_file(), "V24915P2C3_B0018_AUTHORITY_MISSING")
    _require(rt.sha256_file(path) == AUTHORITY_SHA256,
             "V24915P2C3_B0018_AUTHORITY_HASH_MISMATCH")
    authority = rt.read_json(path)
    _require(authority.get("schema") == SCHEMA,
             "V24915P2C3_B0018_AUTHORITY_SCHEMA_MISMATCH")
    _require(authority.get("source_checkpoint_name") == EXPECTED_CHECKPOINT_NAME,
             "V24915P2C3_B0018_CHECKPOINT_NAME_MISMATCH")
    _require(int(authority.get("accepted_count", -1)) == EXPECTED_ACCEPTED_COUNT,
             "V24915P2C3_B0018_ACCEPTED_COUNT_MISMATCH")
    _require(int(authority.get("inherited_outer_cycles", -1)) == 15 and
             int(authority.get("next_outer_cycle", -1)) == EXPECTED_NEXT_OUTER_CYCLE,
             "V24915P2C3_B0018_CYCLE_BOUNDARY_MISMATCH")
    _require(int(authority.get("max_lineage_outer_cycle", -1)) == EXPECTED_MAX_LINEAGE_OUTER_CYCLE,
             "V24915P2C3_B0018_MAX_CYCLE_MISMATCH")
    _require(int(authority.get("extension_outer_cycles", -1)) == 10 and
             int(authority.get("extension_outer_cycle_start", -1)) == 16 and
             int(authority.get("extension_outer_cycle_end", -1)) == 25,
             "V24915P2C3_B0018_EXTENSION_BUDGET_MISMATCH")
    _require(int(authority.get("inherited_stationary_cycle_streak", -1)) == 0,
             "V24915P2C3_B0018_STATIONARY_RESET_MISMATCH")
    _require(authority.get("source_demand_converged") is True and
             authority.get("extension_resets_demand_convergence") is True and
             authority.get("supply_locked_during_extension") is True,
             "V24915P2C3_B0018_PHASE_POLICY_MISMATCH")
    _require(authority.get("resume_substep") == "GENERATION" and
             authority.get("td_realization_pending") is False,
             "V24915P2C3_B0018_RESUME_SUBSTEP_MISMATCH")
    _require(authority.get("semantic_state_hash") == EXPECTED_SEMANTIC_STATE_HASH,
             "V24915P2C3_B0018_SEMANTIC_STATE_HASH_MISMATCH")
    expected_hashes = authority.get("semantic_hashes") or {}
    _require(set(expected_hashes) == {
        "fixed_link_hash", "dseg_hash", "operations_hash", "addval_hash",
        "matrix_hash", "generation_hash", "td_hash"},
        "V24915P2C3_B0018_SEMANTIC_FIELDS_MISMATCH")
    from r1_15a2_restart_v2494 import semantic_state_hash
    _require(semantic_state_hash(dict(expected_hashes)) == EXPECTED_SEMANTIC_STATE_HASH,
             "V24915P2C3_B0018_AUTHORITY_SELF_INCONSISTENT")
    _require(authority.get("generation_backtracking_scales") == [1.0, 0.5, 0.25, 0.125, 0.0625] and
             int(authority.get("generation_max_trials_per_block", -1)) == 5,
             "V24915P2C3_B0018_GENERATION_SEARCH_GRID_MISMATCH")
    _require(tuple(authority.get("bounded_inner_budget_stop_reasons", ())) ==
             BOUNDED_INNER_BUDGET_STOP_REASONS,
             "V24915P2C3_B0018_BUDGET_REASON_SET_MISMATCH")
    ref_path = root / str(authority.get("generation_reference_file", ""))
    _require(ref_path.is_file(), "V24915P2C3_B0018_GENERATION_REFERENCE_MISSING")
    _require(rt.sha256_file(ref_path) == EXPECTED_GENERATION_REFERENCE_SHA256 ==
             authority.get("generation_reference_sha256"),
             "V24915P2C3_B0018_GENERATION_REFERENCE_HASH_MISMATCH")
    out = copy.deepcopy(dict(authority))
    out["authority_path"] = str(path)
    out["authority_sha256"] = AUTHORITY_SHA256
    return out


def matches_b0016_live_semantic(live_semantic: Mapping[str, Any], package_root=None) -> bool:
    """Compatibility name; matches only the exact B0018 semantic authority."""
    try:
        authority = load_authority(package_root)
    except Exception:
        return False
    return live_semantic.get("semantic_state_hash") == authority.get("semantic_state_hash")


def resolve_b0016(source_version, live_semantic: Mapping[str, Any], package_root=None) -> Dict[str, Any]:
    """Compatibility name; resolve exact B0018 -> cycle 16 demand continuation."""
    root = _root(package_root)
    authority = load_authority(root)
    source_version = Path(source_version).resolve()
    _require(source_version.is_file(), "V24915P2C3_B0018_SOURCE_VERSION_MISSING")
    _require(source_version.name == EXPECTED_CHECKPOINT_NAME,
             "V24915P2C3_B0018_SOURCE_CHECKPOINT_NAME_MISMATCH")
    _require(live_semantic.get("semantic_state_hash") == EXPECTED_SEMANTIC_STATE_HASH,
             "V24915P2C3_B0018_LIVE_SEMANTIC_STATE_MISMATCH")
    actual = live_semantic.get("semantic_hashes") or {}
    expected = authority.get("semantic_hashes") or {}
    mismatches = {name: {"expected": value, "actual": actual.get(name)}
                  for name, value in expected.items() if actual.get(name) != value}
    _require(not mismatches,
             "V24915P2C3_B0018_LIVE_SEMANTIC_FIELDS_MISMATCH:" +
             json.dumps(mismatches, sort_keys=True))
    ref_path = root / authority["generation_reference_file"]
    reference = rt.read_json(ref_path)
    _require(reference.get("schema") == "R1_15A2_SHARED_OBJECTIVE_V22",
             "V24915P2C3_B0018_GENERATION_REFERENCE_SCHEMA_MISMATCH")
    return {
        "schema": "R1_15A2_V24915_RESOLVED_B0018_DEMAND_EXTENSION_V1",
        "enabled": True,
        "mode": "EXACT_SEMANTIC_B0018_DEMAND_EXTENSION_CYCLES16_25_SUPPLY_LOCKED",
        "source_version": str(source_version),
        "source_version_name": source_version.name,
        "expected_source_checkpoint_name": EXPECTED_CHECKPOINT_NAME,
        "source_checkpoint_name_matches": True,
        "source_release": "R1_15A2_V2_4_9_15_PERF2_CANDIDATE_READBACK_BUNDLE_20261019",
        "source_run_id": authority.get("source_run_id"),
        "source_terminal_status": "FAILED_SUPPLY:FAILED",
        "source_error_class": "SUPPLY_TEMP_SQLITE_QUERY_ONLY_BLOCKED_TEMP_TABLE",
        "accepted_count": EXPECTED_ACCEPTED_COUNT,
        "inherited_outer_cycles": 15,
        "next_outer_cycle": EXPECTED_NEXT_OUTER_CYCLE,
        "max_lineage_outer_cycle": EXPECTED_MAX_LINEAGE_OUTER_CYCLE,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": int(authority.get("inherited_completed_demand_cycles", 10)),
        "semantic_state_hash": EXPECTED_SEMANTIC_STATE_HASH,
        "semantic_hashes": copy.deepcopy(expected),
        "resume_substep": "GENERATION",
        "generation_reference": copy.deepcopy(reference),
        "generation_reference_sha256": EXPECTED_GENERATION_REFERENCE_SHA256,
        "bounded_inner_budget_stop_reasons": list(BOUNDED_INNER_BUDGET_STOP_REASONS),
        "continue_bounded_budget_without_accepted_change": True,
        "supply_unlock_criterion": "DISABLED_DURING_B0018_EXTENSION_REVIEW_AFTER_CYCLE25",
        "raw_ver_sha_role": authority.get("raw_ver_sha_role"),
        "raw_ver_sha_used_for_restart_acceptance": False,
        "authority_path": str(root / AUTHORITY_FILE),
        "authority_sha256": AUTHORITY_SHA256,
        "b0018_demand_extension": {
            "outer_cycle_start": 16,
            "outer_cycle_end": 25,
            "outer_cycle_count": 10,
            "stationary_streak_reset": True,
            "supply_locked": True,
            "generation_backtracking_scales": [1.0, 0.5, 0.25, 0.125, 0.0625],
            "generation_max_trials_per_block": 5,
            "acceptance_thresholds_changed": False,
            "td_math_changed": False,
        },
    }


def resolve_a0009(source_version, live_semantic: Mapping[str, Any], package_root=None) -> Dict[str, Any]:
    raise SupplyContractError(
        "V24915P2C3_DEMAND_EXTENSION_REQUIRES_EXACT_B0018_SEMANTIC_CHECKPOINT")


__all__ = [
    "AUTHORITY_FILE", "AUTHORITY_SHA256", "EXPECTED_CHECKPOINT_NAME",
    "EXPECTED_SEMANTIC_STATE_HASH", "EXPECTED_ACCEPTED_COUNT",
    "EXPECTED_NEXT_OUTER_CYCLE", "EXPECTED_MAX_LINEAGE_OUTER_CYCLE",
    "load_authority", "matches_b0016_live_semantic", "resolve_b0016", "resolve_a0009",
]
