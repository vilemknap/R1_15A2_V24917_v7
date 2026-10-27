# -*- coding: utf-8 -*-
"""Fail-closed V2.4.9.14 continuation of the verified V24912 A0009 state.

This module does not load a Visum version.  The user opens the authoritative
accepted checkpoint, the launcher builds the live semantic restart authority,
and this module verifies that authority before any SaveVersion or parameter
write is allowed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError

SCHEMA = "R1_15A2_V24914_DEMAND_CONTINUATION_AUTHORITY_V1"
AUTHORITY_FILE = "V24914_DEMAND_CONTINUATION_AUTHORITY.json"
BOUNDED_INNER_BUDGET_STOP_REASONS = (
    "MAX_ITERATIONS",
    "TD_EVALUATION_BUDGET",
    "TD_INNER_TIME_BUDGET",
)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def load_authority(package_root=None) -> Dict[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    path = root / AUTHORITY_FILE
    _require(path.is_file(), "V24914_CONTINUATION_AUTHORITY_MISSING")
    obj = rt.read_json(path)
    validate_authority(obj)
    obj = dict(obj)
    obj["authority_path"] = str(path)
    obj["authority_sha256"] = rt.sha256_file(path)
    return obj


def validate_authority(authority: Mapping[str, Any]) -> None:
    _require(authority.get("schema") == SCHEMA, "V24914_CONTINUATION_AUTHORITY_SCHEMA_MISMATCH")
    _require(authority.get("source_release") ==
             "R1_15A2_V2_4_9_12_GUARD_POLICY_REBASE_20261018",
             "V24914_CONTINUATION_SOURCE_RELEASE_MISMATCH")
    _require(authority.get("source_terminal_status") ==
             "DEMAND_SEARCH_INCOMPLETE_SUPPLY_LOCKED:MAX_ITERATIONS",
             "V24914_CONTINUATION_SOURCE_STATUS_MISMATCH")
    _require(int(authority.get("accepted_count", -1)) == 9,
             "V24914_CONTINUATION_ACCEPTED_COUNT_MISMATCH")
    _require(int(authority.get("inherited_outer_cycles", -1)) == 5,
             "V24914_CONTINUATION_INHERITED_CYCLE_MISMATCH")
    _require(int(authority.get("next_outer_cycle", -1)) == 6,
             "V24914_CONTINUATION_NEXT_CYCLE_MISMATCH")
    _require(int(authority.get("max_lineage_outer_cycle", -1)) == 12,
             "V24914_CONTINUATION_MAX_CYCLE_MISMATCH")
    _require(int(authority.get("inherited_stationary_cycle_streak", -1)) == 0,
             "V24914_CONTINUATION_STATIONARY_STREAK_MISMATCH")
    _require(authority.get("demand_converged") is False and
             authority.get("supply_started") is False,
             "V24914_CONTINUATION_SOURCE_PHASE_MISMATCH")
    _require(authority.get("semantic_state_hash") and
             len(str(authority.get("semantic_state_hash"))) == 64,
             "V24914_CONTINUATION_SEMANTIC_HASH_MISSING")
    semantic_hashes = authority.get("semantic_hashes", {}) or {}
    required = ("fixed_link_hash", "dseg_hash", "operations_hash", "addval_hash",
                "matrix_hash", "generation_hash", "td_hash")
    _require(set(required).issubset(semantic_hashes),
             "V24914_CONTINUATION_SEMANTIC_FIELDS_MISSING")
    _require(tuple(authority.get("bounded_inner_budget_stop_reasons", ())) ==
             BOUNDED_INNER_BUDGET_STOP_REASONS,
             "V24914_CONTINUATION_BUDGET_REASON_SET_MISMATCH")
    cycles = list(authority.get("source_cycle_summary", []))
    _require([int(x.get("cycle", -1)) for x in cycles] == [1, 2, 3, 4, 5],
             "V24914_CONTINUATION_SOURCE_CYCLE_SEQUENCE_MISMATCH")
    _require(cycles[-1].get("status") == "SEARCH_INCOMPLETE" and
             cycles[-1].get("generation_completed") is True and
             cycles[-1].get("td_completed") is True and
             cycles[-1].get("generation_changed") is True and
             cycles[-1].get("td_changed") is True,
             "V24914_CONTINUATION_SOURCE_CYCLE5_NOT_ACCEPTED_CHANGED_STATE")


def _candidate_artifact_roots(source_version: Path):
    source_version = Path(source_version).resolve()
    roots = []
    for p in (source_version.parent,) + tuple(source_version.parent.parents):
        for candidate in (p, p / "CALIBRATION"):
            if candidate in roots:
                continue
            if (candidate / "RUN_STATUS.json").is_file() or (candidate / "LATEST_ACCEPTED_CHECKPOINT.json").is_file():
                roots.append(candidate)
    return roots


def _read_optional(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return rt.read_json(path) if path.is_file() else None
    except Exception as exc:
        raise SupplyContractError("V24914_CONTINUATION_ARTIFACT_UNREADABLE:%s:%s" % (path, exc))


def discover_source_artifacts(source_version: Path) -> Dict[str, Any]:
    roots = _candidate_artifact_roots(source_version)
    if not roots:
        return {"status": "SOURCE_RUN_ARTIFACTS_NOT_FOUND_STATIC_AUTHORITY_USED",
                "roots_checked": [str(Path(source_version).resolve().parent)]}
    root = roots[0]
    status = _read_optional(root / "RUN_STATUS.json")
    latest = _read_optional(root / "LATEST_ACCEPTED_CHECKPOINT.json")
    return {
        "status": "SOURCE_RUN_ARTIFACTS_FOUND",
        "artifact_root": str(root),
        "run_status_path": str(root / "RUN_STATUS.json") if status is not None else None,
        "latest_checkpoint_path": str(root / "LATEST_ACCEPTED_CHECKPOINT.json") if latest is not None else None,
        "run_status": status,
        "latest_checkpoint": latest,
    }


def _verify_optional_source_artifacts(discovered: Mapping[str, Any], authority: Mapping[str, Any]) -> Dict[str, Any]:
    if discovered.get("status") != "SOURCE_RUN_ARTIFACTS_FOUND":
        return {"status": discovered.get("status"), "verified": False,
                "reason": "LIVE_SEMANTIC_AUTHORITY_IS_SUFFICIENT"}
    status = discovered.get("run_status")
    latest = discovered.get("latest_checkpoint")
    checks = {}
    if status is not None:
        checks["terminal_status"] = status.get("status") == authority.get("source_terminal_status")
        checks["accepted_count"] = int(status.get("accepted_count", -1)) == int(authority.get("accepted_count"))
        checks["demand_converged"] = status.get("demand_converged") is False
        checks["supply_started"] = status.get("supply_started") is False
        cycles = list(status.get("demand_cycles", []))
        checks["cycle_count"] = len(cycles) >= int(authority.get("inherited_outer_cycles"))
        if cycles:
            last = cycles[-1]
            checks["last_cycle"] = int(last.get("cycle", -1)) == int(authority.get("inherited_outer_cycles"))
            checks["last_cycle_status"] = last.get("status") == "SEARCH_INCOMPLETE"
            checks["last_cycle_changed"] = last.get("generation_changed") is True and last.get("td_changed") is True
    if latest is not None:
        semantic = latest.get("semantic_restart_authority", {}) or {}
        checks["latest_semantic_state"] = semantic.get("semantic_state_hash") == authority.get("semantic_state_hash")
        checks["latest_accepted_count"] = int(latest.get("accepted_count", -1)) == int(authority.get("accepted_count"))
    _require(all(checks.values()), "V24914_SOURCE_RUN_ARTIFACT_MISMATCH:" +
             json.dumps(checks, sort_keys=True))
    return {"status": "SOURCE_RUN_ARTIFACTS_MATCH", "verified": True,
            "artifact_root": discovered.get("artifact_root"), "checks": checks}


def resolve_continuation(source_version, live_semantic: Mapping[str, Any], package_root=None) -> Dict[str, Any]:
    authority = load_authority(package_root)
    source_version = Path(source_version).resolve()
    _require(source_version.is_file(), "V24914_CONTINUATION_SOURCE_VERSION_MISSING")
    _require(live_semantic.get("semantic_state_hash") == authority.get("semantic_state_hash"),
             "V24914_CONTINUATION_LIVE_SEMANTIC_STATE_MISMATCH")
    actual_fields = live_semantic.get("semantic_hashes", {}) or {}
    expected_fields = authority.get("semantic_hashes", {}) or {}
    mismatches = {name: {"expected": expected_fields.get(name), "actual": actual_fields.get(name)}
                  for name in expected_fields if actual_fields.get(name) != expected_fields.get(name)}
    _require(not mismatches, "V24914_CONTINUATION_LIVE_SEMANTIC_FIELDS_MISMATCH:" +
             json.dumps(mismatches, sort_keys=True))
    discovered = discover_source_artifacts(source_version)
    artifact_check = _verify_optional_source_artifacts(discovered, authority)
    return {
        "schema": "R1_15A2_V24914_RESOLVED_DEMAND_CONTINUATION_V1",
        "enabled": True,
        "mode": "EXACT_SEMANTIC_A0009_LINEAGE_CONTINUATION",
        "source_version": str(source_version),
        "source_version_name": source_version.name,
        "expected_source_checkpoint_name": authority.get("source_checkpoint_name"),
        "source_checkpoint_name_matches": source_version.name == authority.get("source_checkpoint_name"),
        "source_release": authority.get("source_release"),
        "source_run_id": authority.get("source_run_id"),
        "source_terminal_status": authority.get("source_terminal_status"),
        "accepted_count": int(authority.get("accepted_count")),
        "inherited_outer_cycles": int(authority.get("inherited_outer_cycles")),
        "next_outer_cycle": int(authority.get("next_outer_cycle")),
        "max_lineage_outer_cycle": int(authority.get("max_lineage_outer_cycle")),
        "inherited_stationary_cycle_streak": int(authority.get("inherited_stationary_cycle_streak")),
        "inherited_completed_demand_cycles": int(authority.get("inherited_completed_demand_cycles", 0)),
        "semantic_state_hash": authority.get("semantic_state_hash"),
        "semantic_hashes": dict(authority.get("semantic_hashes", {})),
        "bounded_inner_budget_stop_reasons": list(BOUNDED_INNER_BUDGET_STOP_REASONS),
        "continue_bounded_budget_without_accepted_change": True,
        "supply_unlock_criterion": authority.get("supply_unlock_criterion"),
        "source_cycle_summary": list(authority.get("source_cycle_summary", [])),
        "authority_path": authority.get("authority_path"),
        "authority_sha256": authority.get("authority_sha256"),
        "source_artifact_check": artifact_check,
        "raw_ver_sha_role": authority.get("raw_ver_sha_role"),
        "raw_ver_sha_used_for_restart_acceptance": False,
    }


__all__ = [
    "SCHEMA", "AUTHORITY_FILE", "BOUNDED_INNER_BUDGET_STOP_REASONS",
    "load_authority", "validate_authority", "discover_source_artifacts",
    "resolve_continuation",
]
