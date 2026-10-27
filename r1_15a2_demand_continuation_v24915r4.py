# -*- coding: utf-8 -*-
"""Fail-closed continuation from the real V24915 B0016 accepted checkpoint.

B0016 was saved after the Generation substep of lineage outer cycle 11 was
accepted, while the following FineCDF TD substep failed in the 11D compatibility
gate.  This module verifies the exact semantic state and resumes cycle 11 at TD;
it never replays the already accepted Generation update.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Mapping

import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError, canonical_hash

SCHEMA = "R1_15A2_V24915_B0016_CONTINUATION_AUTHORITY_V1"
AUTHORITY_FILE = "V24915_B0016_CONTINUATION_AUTHORITY.json"
AUTHORITY_SHA256 = "602d0cdf7b40ad6cb8ab49d36030e6bc16c06eba757d56ffdf7d4ad28e3185a9"
EXPECTED_SEMANTIC_STATE_HASH = "46a0c61d45e55cc9d2a91be0c62839fee7ef9236924e59d6ebc27b62619c63d2"
EXPECTED_CHECKPOINT_NAME = "ACCEPTED_B_0016_d1211a44ac4d.ver"
EXPECTED_ACCEPTED_COUNT = 16
EXPECTED_NEXT_OUTER_CYCLE = 11
EXPECTED_MAX_LINEAGE_OUTER_CYCLE = 12
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
    _require(path.is_file(), "V24915R4_B0016_AUTHORITY_MISSING")
    _require(rt.sha256_file(path) == AUTHORITY_SHA256,
             "V24915R4_B0016_AUTHORITY_HASH_MISMATCH")
    authority = rt.read_json(path)
    validate_authority(authority, root)
    out = copy.deepcopy(dict(authority))
    out["authority_path"] = str(path)
    out["authority_sha256"] = AUTHORITY_SHA256
    return out


def validate_generation_reference(reference: Mapping[str, Any]) -> None:
    _require(reference.get("schema") == "R1_15A2_SHARED_OBJECTIVE_V22",
             "V24915R4_GENERATION_REFERENCE_SCHEMA_MISMATCH")
    expected_components = [
        "LONG_COMPOSITE", "SCHOOL", "SERV_E_C", "SERV_E_noC",
        "SERV_noE_C", "SERV_noE_noC", "SERV_stud", "WORK_E_C",
        "WORK_E_noC", "WORK_noE_C", "WORK_noE_noC", "WORK_stud",
    ]
    _require(list(reference.get("components", [])) == expected_components,
             "V24915R4_GENERATION_REFERENCE_COMPONENT_SET_MISMATCH")
    weights = reference.get("component_weights") or {}
    _require(set(weights) == set(expected_components),
             "V24915R4_GENERATION_REFERENCE_WEIGHT_SET_MISMATCH")
    _require(reference.get("target_hash") ==
             "6fa9d0908fe27b330946e1f58ccae630c430c6c9c7e9d6c08838eb5a6b780502",
             "V24915R4_GENERATION_REFERENCE_TARGET_HASH_MISMATCH")
    _require(reference.get("observation_hash") ==
             "af69aadb01a0caad81d796d2d02fc0d9c6a34ea2051678a9a871055bba32e707",
             "V24915R4_GENERATION_REFERENCE_OBSERVATION_HASH_MISMATCH")
    _require(reference.get("cal_objective_metric") == "WEIGHTED_MEAN_GEH" and
             reference.get("cal_objective_key") == "objective_geh_mean_weighted",
             "V24915R4_GENERATION_REFERENCE_OBJECTIVE_MISMATCH")


def validate_authority(authority: Mapping[str, Any], root: Path) -> None:
    _require(authority.get("schema") == SCHEMA,
             "V24915R4_B0016_AUTHORITY_SCHEMA_MISMATCH")
    _require(authority.get("source_checkpoint_name") == EXPECTED_CHECKPOINT_NAME,
             "V24915R4_B0016_CHECKPOINT_NAME_MISMATCH")
    _require(int(authority.get("accepted_count", -1)) == EXPECTED_ACCEPTED_COUNT,
             "V24915R4_B0016_ACCEPTED_COUNT_MISMATCH")
    _require(int(authority.get("inherited_outer_cycles", -1)) == 10,
             "V24915R4_B0016_INHERITED_CYCLES_MISMATCH")
    _require(int(authority.get("next_outer_cycle", -1)) == EXPECTED_NEXT_OUTER_CYCLE,
             "V24915R4_B0016_NEXT_CYCLE_MISMATCH")
    _require(int(authority.get("max_lineage_outer_cycle", -1)) == EXPECTED_MAX_LINEAGE_OUTER_CYCLE,
             "V24915R4_B0016_MAX_CYCLE_MISMATCH")
    _require(int(authority.get("inherited_stationary_cycle_streak", -1)) == 0,
             "V24915R4_B0016_STATIONARY_STREAK_MISMATCH")
    _require(int(authority.get("inherited_completed_demand_cycles", -1)) == 5,
             "V24915R4_B0016_COMPLETED_CYCLES_MISMATCH")
    _require(authority.get("demand_converged") is False and
             authority.get("supply_started") is False,
             "V24915R4_B0016_SOURCE_PHASE_MISMATCH")
    _require(authority.get("resume_substep") == "TD_FINECDF_V17" and
             int(authority.get("resume_outer_cycle", -1)) == 11 and
             authority.get("resume_generation_completed") is True and
             authority.get("resume_generation_changed") is True and
             authority.get("resume_td_completed") is False and
             authority.get("td_realization_pending") is True,
             "V24915R4_B0016_PARTIAL_CYCLE_CONTRACT_MISMATCH")
    _require(authority.get("semantic_state_hash") == EXPECTED_SEMANTIC_STATE_HASH,
             "V24915R4_B0016_SEMANTIC_STATE_HASH_MISMATCH")
    hashes = authority.get("semantic_hashes") or {}
    required = ("fixed_link_hash", "dseg_hash", "operations_hash", "addval_hash",
                "matrix_hash", "generation_hash", "td_hash")
    _require(set(required).issubset(hashes),
             "V24915R4_B0016_SEMANTIC_FIELDS_MISSING")
    _require(tuple(authority.get("bounded_inner_budget_stop_reasons", ())) ==
             BOUNDED_INNER_BUDGET_STOP_REASONS,
             "V24915R4_B0016_BUDGET_REASON_SET_MISMATCH")
    evidence = authority.get("source_restart_evidence") or {}
    _require(evidence.get("live_matches_last_accepted") is True and
             evidence.get("manual_reopen_required") is False and
             evidence.get("safe_restart_from_latest_accepted_checkpoint") is True and
             evidence.get("cycle11_generation_completed") is True and
             evidence.get("cycle11_td_completed") is False,
             "V24915R4_B0016_RESTART_EVIDENCE_MISMATCH")
    ref_rel = authority.get("generation_reference_file")
    ref_path = root / str(ref_rel)
    _require(ref_path.is_file(), "V24915R4_GENERATION_REFERENCE_FILE_MISSING")
    _require(rt.sha256_file(ref_path) == EXPECTED_GENERATION_REFERENCE_SHA256 ==
             authority.get("generation_reference_sha256"),
             "V24915R4_GENERATION_REFERENCE_FILE_HASH_MISMATCH")
    reference = rt.read_json(ref_path)
    validate_generation_reference(reference)
    _require(canonical_hash(reference) == canonical_hash(authority.get("generation_reference") or {}),
             "V24915R4_GENERATION_REFERENCE_EMBEDDED_COPY_MISMATCH")


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
    _require(source_version.is_file(), "V24915R4_B0016_SOURCE_VERSION_MISSING")
    _require(source_version.name == EXPECTED_CHECKPOINT_NAME,
             "V24915R4_B0016_SOURCE_CHECKPOINT_NAME_MISMATCH")
    _require(live_semantic.get("semantic_state_hash") == authority.get("semantic_state_hash"),
             "V24915R4_B0016_LIVE_SEMANTIC_STATE_MISMATCH")
    actual = live_semantic.get("semantic_hashes") or {}
    expected = authority.get("semantic_hashes") or {}
    mismatches = {name: {"expected": value, "actual": actual.get(name)}
                  for name, value in expected.items() if actual.get(name) != value}
    _require(not mismatches,
             "V24915R4_B0016_LIVE_SEMANTIC_FIELDS_MISMATCH:" +
             json.dumps(mismatches, sort_keys=True))
    reference = rt.read_json(root / authority["generation_reference_file"])
    validate_generation_reference(reference)
    return {
        "schema": "R1_15A2_V24915_RESOLVED_B0016_CONTINUATION_V1",
        "enabled": True,
        "mode": "EXACT_SEMANTIC_B0016_PARTIAL_CYCLE11_TD_RESUME",
        "source_version": str(source_version),
        "source_version_name": source_version.name,
        "expected_source_checkpoint_name": EXPECTED_CHECKPOINT_NAME,
        "source_checkpoint_name_matches": True,
        "source_release": authority.get("source_release"),
        "source_run_id": authority.get("source_run_id"),
        "source_terminal_status": authority.get("source_terminal_status"),
        "source_error_class": authority.get("source_error_class"),
        "accepted_count": EXPECTED_ACCEPTED_COUNT,
        "inherited_outer_cycles": 10,
        "next_outer_cycle": EXPECTED_NEXT_OUTER_CYCLE,
        "max_lineage_outer_cycle": EXPECTED_MAX_LINEAGE_OUTER_CYCLE,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 5,
        "semantic_state_hash": authority.get("semantic_state_hash"),
        "semantic_hashes": copy.deepcopy(expected),
        "resume_substep": "TD_FINECDF_V17",
        "resume_outer_cycle": 11,
        "resume_generation_completed": True,
        "resume_generation_changed": True,
        "resume_td_completed": False,
        "resume_generation_record": copy.deepcopy(authority.get("resume_generation_record") or {}),
        "generation_reference": copy.deepcopy(reference),
        "generation_reference_sha256": EXPECTED_GENERATION_REFERENCE_SHA256,
        "path_epoch_checkpoint": copy.deepcopy(authority.get("path_epoch_checkpoint")),
        "bounded_inner_budget_stop_reasons": list(BOUNDED_INNER_BUDGET_STOP_REASONS),
        "continue_bounded_budget_without_accepted_change": True,
        "supply_unlock_criterion": "TWO_CONSECUTIVE_COMPLETE_SUCCESSFUL_CONFIGURED_TG_TD_SEARCHES_WITH_NO_CHANGE",
        "raw_ver_sha_role": "PROVENANCE_AND_WITHIN_RUN_SOURCE_MUTATION_SENTINEL_ONLY_NOT_CROSS_RUN_RESTART_ACCEPTANCE",
        "raw_ver_sha_used_for_restart_acceptance": False,
        "authority_path": str(root / AUTHORITY_FILE),
        "authority_sha256": AUTHORITY_SHA256,
    }


__all__ = [
    "load_authority", "validate_authority", "validate_generation_reference",
    "matches_live_semantic", "resolve_continuation", "EXPECTED_SEMANTIC_STATE_HASH",
]
