# -*- coding: utf-8 -*-
"""Exact semantic continuation after PROFILE488 A0004 cycle-3 TD telemetry failure.

The source run accepted Generation in outer cycle 3, then failed inside the TD
realization rollback path only because PERFORMANCE/SUMMARY.json publication hit
a Windows PermissionError. The TD rollback itself was verified exact. This
module resumes outer cycle 3 at TD and never replays the already accepted
Generation update.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Mapping

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError, canonical_hash

SCHEMA = "R1_15A2_PROFILE488_A0004_CYCLE3_TD_RECOVERY_AUTHORITY_V1"
AUTHORITY_FILE = "PROFILE488_A0004_CYCLE3_TD_RECOVERY_AUTHORITY.json"
AUTHORITY_SHA256 = "02b5ae06f42cabcaacd223210a6dbc50738125a4d71f1457e4c02f85cb5965c4"
EXPECTED_SEMANTIC_STATE_HASH = "c853dba4c29526903c5a16c496d5863e3506a12fcf5a5b8103ba3bb98cb2d97d"
EXPECTED_CHECKPOINT_NAME = "ACCEPTED_B_0004_d26d01d6f9a5.ver"
EXPECTED_ACCEPTED_COUNT = 4
EXPECTED_NEXT_OUTER_CYCLE = 3
EXPECTED_MAX_LINEAGE_OUTER_CYCLE = 100
EXPECTED_GENERATION_REFERENCE_SHA256 = "da69a14dca52e80eb751c9227452c71d1fffff7a75a5097efe2df9b6c924d703"
EXPECTED_GENERATION_RECORD_SHA256 = "44dff28be5ddb9c6046eb6c19eb887a6f07956d687381c9a3bf4686f281dceff"
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


def validate_generation_reference(reference: Mapping[str, Any]) -> None:
    _require(reference.get("schema") == "R1_15A2_SHARED_OBJECTIVE_V22",
             "PROFILE488_A0004_GENERATION_REFERENCE_SCHEMA_MISMATCH")
    expected_components = [
        "LONG_COMPOSITE", "SCHOOL", "SERV_E_C", "SERV_E_noC",
        "SERV_noE_C", "SERV_noE_noC", "SERV_stud", "WORK_E_C",
        "WORK_E_noC", "WORK_noE_C", "WORK_noE_noC", "WORK_stud",
    ]
    _require(list(reference.get("components", [])) == expected_components,
             "PROFILE488_A0004_GENERATION_REFERENCE_COMPONENT_SET_MISMATCH")
    weights = reference.get("component_weights") or {}
    _require(set(weights) == set(expected_components),
             "PROFILE488_A0004_GENERATION_REFERENCE_WEIGHT_SET_MISMATCH")
    _require(reference.get("target_hash") ==
             "6fa9d0908fe27b330946e1f58ccae630c430c6c9c7e9d6c08838eb5a6b780502",
             "PROFILE488_A0004_GENERATION_REFERENCE_TARGET_HASH_MISMATCH")
    _require(reference.get("observation_hash") ==
             "0f0bb12af3f7e05db7f41e27c961e9462c963a86a00b7d29999e328db6aefc81",
             "PROFILE488_A0004_GENERATION_REFERENCE_OBSERVATION_HASH_MISMATCH")
    _require(reference.get("cal_objective_metric") == "WEIGHTED_MEAN_GEH" and
             reference.get("cal_objective_key") == "objective_geh_mean_weighted",
             "PROFILE488_A0004_GENERATION_REFERENCE_OBJECTIVE_MISMATCH")


def load_authority(package_root=None) -> Dict[str, Any]:
    root = _root(package_root)
    path = root / AUTHORITY_FILE
    _require(path.is_file(), "PROFILE488_A0004_AUTHORITY_MISSING")
    _require(rt.sha256_file(path) == AUTHORITY_SHA256,
             "PROFILE488_A0004_AUTHORITY_HASH_MISMATCH")
    authority = rt.read_json(path)
    validate_authority(authority, root)
    out = copy.deepcopy(dict(authority))
    out["authority_path"] = str(path)
    out["authority_sha256"] = AUTHORITY_SHA256
    return out


def validate_authority(authority: Mapping[str, Any], root: Path) -> None:
    _require(authority.get("schema") == SCHEMA,
             "PROFILE488_A0004_AUTHORITY_SCHEMA_MISMATCH")
    _require(authority.get("source_checkpoint_name") == EXPECTED_CHECKPOINT_NAME,
             "PROFILE488_A0004_CHECKPOINT_NAME_MISMATCH")
    _require(int(authority.get("accepted_count", -1)) == EXPECTED_ACCEPTED_COUNT,
             "PROFILE488_A0004_ACCEPTED_COUNT_MISMATCH")
    _require(int(authority.get("inherited_outer_cycles", -1)) == 2,
             "PROFILE488_A0004_INHERITED_CYCLES_MISMATCH")
    _require(int(authority.get("next_outer_cycle", -1)) == EXPECTED_NEXT_OUTER_CYCLE,
             "PROFILE488_A0004_NEXT_CYCLE_MISMATCH")
    _require(int(authority.get("max_lineage_outer_cycle", -1)) == EXPECTED_MAX_LINEAGE_OUTER_CYCLE,
             "PROFILE488_A0004_MAX_CYCLE_MISMATCH")
    _require(int(authority.get("inherited_stationary_cycle_streak", -1)) == 0,
             "PROFILE488_A0004_STATIONARY_STREAK_MISMATCH")
    _require(int(authority.get("inherited_completed_demand_cycles", -1)) == 0,
             "PROFILE488_A0004_COMPLETED_CYCLES_MISMATCH")
    _require(authority.get("demand_converged") is False and
             authority.get("supply_started") is False,
             "PROFILE488_A0004_SOURCE_PHASE_MISMATCH")
    _require(authority.get("resume_substep") == "TD_FINECDF_V17" and
             int(authority.get("resume_outer_cycle", -1)) == 3 and
             authority.get("resume_generation_completed") is True and
             authority.get("resume_generation_changed") is True and
             authority.get("resume_td_completed") is False and
             authority.get("td_realization_pending") is True,
             "PROFILE488_A0004_PARTIAL_CYCLE_CONTRACT_MISMATCH")
    _require(authority.get("semantic_state_hash") == EXPECTED_SEMANTIC_STATE_HASH,
             "PROFILE488_A0004_SEMANTIC_STATE_HASH_MISMATCH")
    hashes = authority.get("semantic_hashes") or {}
    required = ("fixed_link_hash", "dseg_hash", "operations_hash", "addval_hash",
                "matrix_hash", "generation_hash", "td_hash")
    _require(set(required).issubset(hashes),
             "PROFILE488_A0004_SEMANTIC_FIELDS_MISSING")
    _require(tuple(authority.get("bounded_inner_budget_stop_reasons", ())) ==
             BOUNDED_INNER_BUDGET_STOP_REASONS,
             "PROFILE488_A0004_BUDGET_REASON_SET_MISMATCH")
    evidence = authority.get("source_restart_evidence") or {}
    _require(evidence.get("rollback_verified") is True and
             evidence.get("rollback_snapshot_equal") is True and
             evidence.get("rollback_diagnostic_equal") is True and
             evidence.get("cycle3_generation_completed") is True and
             evidence.get("cycle3_generation_accepted") is True and
             evidence.get("cycle3_td_completed") is False and
             evidence.get("safe_restart_from_latest_accepted_checkpoint") is True and
             evidence.get("manual_reopen_required") is True,
             "PROFILE488_A0004_RESTART_EVIDENCE_MISMATCH")

    ref_path = root / str(authority.get("generation_reference_file"))
    _require(ref_path.is_file(), "PROFILE488_A0004_GENERATION_REFERENCE_FILE_MISSING")
    _require(rt.sha256_file(ref_path) == EXPECTED_GENERATION_REFERENCE_SHA256 ==
             authority.get("generation_reference_sha256"),
             "PROFILE488_A0004_GENERATION_REFERENCE_FILE_HASH_MISMATCH")
    reference = rt.read_json(ref_path)
    validate_generation_reference(reference)
    _require(canonical_hash(reference) == canonical_hash(authority.get("generation_reference") or {}),
             "PROFILE488_A0004_GENERATION_REFERENCE_EMBEDDED_COPY_MISMATCH")

    rec_path = root / str(authority.get("resume_generation_record_file"))
    _require(rec_path.is_file(), "PROFILE488_A0004_GENERATION_RECORD_FILE_MISSING")
    _require(rt.sha256_file(rec_path) == EXPECTED_GENERATION_RECORD_SHA256 ==
             authority.get("resume_generation_record_sha256"),
             "PROFILE488_A0004_GENERATION_RECORD_FILE_HASH_MISMATCH")
    record = rt.read_json(rec_path)
    _require(record.get("status") == "ACCEPTED" and record.get("search_complete") is True,
             "PROFILE488_A0004_GENERATION_RECORD_INVALID")
    _require(canonical_hash(record) == canonical_hash(authority.get("resume_generation_record") or {}),
             "PROFILE488_A0004_GENERATION_RECORD_EMBEDDED_COPY_MISMATCH")


def matches_live_semantic(live_semantic: Mapping[str, Any], package_root=None) -> bool:
    try:
        authority = load_authority(package_root)
    except Exception:
        return False
    return live_semantic.get("semantic_state_hash") == authority.get("semantic_state_hash")


def resolve_continuation(source_version, live_semantic: Mapping[str, Any], package_root=None) -> Dict[str, Any]:
    root = _root(package_root)
    authority = load_authority(root)
    source_version = Path(source_version).resolve()
    _require(source_version.is_file(), "PROFILE488_A0004_SOURCE_VERSION_MISSING")
    _require(source_version.name == EXPECTED_CHECKPOINT_NAME,
             "PROFILE488_A0004_SOURCE_CHECKPOINT_NAME_MISMATCH")
    _require(live_semantic.get("semantic_state_hash") == authority.get("semantic_state_hash"),
             "PROFILE488_A0004_LIVE_SEMANTIC_STATE_MISMATCH")
    actual = live_semantic.get("semantic_hashes") or {}
    expected = authority.get("semantic_hashes") or {}
    mismatches = {name: {"expected": value, "actual": actual.get(name)}
                  for name, value in expected.items() if actual.get(name) != value}
    _require(not mismatches,
             "PROFILE488_A0004_LIVE_SEMANTIC_FIELDS_MISMATCH:" +
             json.dumps(mismatches, sort_keys=True))
    reference = rt.read_json(root / authority["generation_reference_file"])
    record = rt.read_json(root / authority["resume_generation_record_file"])
    validate_generation_reference(reference)
    return {
        "schema": "R1_15A2_PROFILE488_RESOLVED_A0004_CYCLE3_TD_RECOVERY_V1",
        "enabled": True,
        "mode": "EXACT_SEMANTIC_PROFILE488_A0004_PARTIAL_CYCLE3_TD_RESUME",
        "source_version": str(source_version),
        "source_version_name": source_version.name,
        "expected_source_checkpoint_name": EXPECTED_CHECKPOINT_NAME,
        "source_checkpoint_name_matches": True,
        "source_release": authority.get("source_release"),
        "source_run_id": authority.get("source_run_id"),
        "source_terminal_status": authority.get("source_terminal_status"),
        "source_error_class": authority.get("source_error_class"),
        "accepted_count": EXPECTED_ACCEPTED_COUNT,
        "inherited_outer_cycles": 2,
        "next_outer_cycle": EXPECTED_NEXT_OUTER_CYCLE,
        "max_lineage_outer_cycle": EXPECTED_MAX_LINEAGE_OUTER_CYCLE,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 0,
        "semantic_state_hash": authority.get("semantic_state_hash"),
        "semantic_hashes": copy.deepcopy(expected),
        "resume_substep": "TD_FINECDF_V17",
        "resume_outer_cycle": 3,
        "resume_generation_completed": True,
        "resume_generation_changed": True,
        "resume_td_completed": False,
        "resume_generation_record": copy.deepcopy(record),
        "generation_reference": copy.deepcopy(reference),
        "generation_reference_sha256": EXPECTED_GENERATION_REFERENCE_SHA256,
        "path_epoch_checkpoint": copy.deepcopy(authority.get("path_epoch_checkpoint")),
        "bounded_inner_budget_stop_reasons": list(BOUNDED_INNER_BUDGET_STOP_REASONS),
        "continue_bounded_budget_without_accepted_change": True,
        "bounded_budget_counts_as_stationarity": False,
        "supply_unlock_criterion": "AFTER_OUTER_CYCLE_100_ONLY_AND_FINAL_STATIONARITY_CRITERION",
        "raw_ver_sha_role": "PROVENANCE_AND_WITHIN_RUN_SOURCE_MUTATION_SENTINEL_ONLY_NOT_CROSS_RUN_RESTART_ACCEPTANCE",
        "raw_ver_sha_used_for_restart_acceptance": False,
        "authority_path": str(root / AUTHORITY_FILE),
        "authority_sha256": AUTHORITY_SHA256,
    }


__all__ = [
    "load_authority", "validate_authority", "validate_generation_reference",
    "matches_live_semantic", "resolve_continuation", "EXPECTED_SEMANTIC_STATE_HASH",
]
