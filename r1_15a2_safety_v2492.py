# -*- coding: utf-8 -*-
"""V2.4.9.2 signed Generation refinement safety contract.

The release keeps the V2.4.9.0 TD soft-reference and path-cache authority, but
replaces the one-sided Generation search by an auditable signed decomposition:

    family total scale + zero-total zonal redistribution.

Domestic AMDY-like coefficients use a reviewed 0.5--2.0 safety envelope with a
0.8--1.25 soft band.  ZAHR raw coefficients keep their native scale and are
bounded relative to the immutable run-start reference instead.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_safety_v2490 import (
    RELEASE as V2490_RELEASE,
    validate_v2490_config,
)
from r1_15a2_supply import SupplyContractError
import r1_15a2_runtime_v1 as rt

RELEASE = "R1_15A2_V2_4_9_2_SIGNED_GENERATION_REFINEMENT_20261018"
V2490_CONFIG_SHA256 = "c11085b40a72be78adf8a5848ac025e0c2265af6bf1c97a17704e323af9563a1"
V2490_PATH_IMPLEMENTATION_FILES = {
    "r1_15a2_two_mode_v238.py": "a58980069e942b6782f6d906443e81922f81e6596eb5de5be456719f96ce15ad",
    "r1_15a2_trial_adapter_v240.py": "f55e7e4936bb93770fb7ff99d6a485a0695575f1e6c59ba44552e2163c857109",
    "r1_15a2_persistent_path_cache_v248.py": "78522a1a9d7bd4bcabfb360604fd9c0a6d3415e0d845d935e7c3084aeedb276c",
    "r1_15a2_sequence_v23.py": "91a3c65e7c38a56dbb560d5debe91235ae10637176de16f08b29ccd09ff5a983",
    "r1_15a2_supply.py": "c35e6440b63bbc9ba2ec060ef77543d420e0411b5b463dee8479171e0a46198e",
    "r1_15a2_core.py": "f8c46886dc5fead310812f053037e005bee3c4bb641aa9439f11f222fb9976d7",
    "r1_15a2_runtime_v1.py": "eed25b8dc78ca2c256b6d67a4893cdbb8acae4fb80f529ff10254054bb7c14f9",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SupplyContractError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_and_validate_bundled_v2490(package_root: Path) -> Mapping[str, Any]:
    """Validate the immutable predecessor package that is bundled for lineage.

    Importing its launcher is deliberate: it reconstructs the exact runtime
    implementation hash map in the same way as a real V2.4.9.0 launch.
    """
    launcher = package_root / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_0.py"
    _require(launcher.is_file(), "V2492_BUNDLED_V2490_LAUNCHER_MISSING")
    spec = importlib.util.spec_from_file_location("_r1_v2490_lineage_launcher", launcher)
    _require(spec is not None and spec.loader is not None,
             "V2492_BUNDLED_V2490_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    baseline = module.load_config()
    return validate_v2490_config(baseline, package_root)


def _validate_unchanged_top_level(cfg: Mapping[str, Any], package_root: Path) -> None:
    baseline = rt.read_json(package_root / "R1_15A2_CONFIG_V2_4_9_0.json")
    changed = {
        "release", "safety_gate_release", "version", "guidance_mode",
        "allow_signed_apply", "max_od_relative_up", "max_add_log_up",
        "salary", "generation_signed_refinement",
        "generation_bound_constrained_projection",
        "generation_coefficient_authority", "methodology", "performance",
        "implementation_files",
    }
    for key, old_value in baseline.items():
        if key in changed:
            continue
        _require(key in cfg and _canonical(cfg[key]) == _canonical(old_value),
                 "V2492_UNCHANGED_CONFIG_DRIFT:" + key)

    # Only the per-block salary step is changed; all formula semantics remain.
    old_salary = copy.deepcopy(baseline["salary"])
    new_salary = copy.deepcopy(cfg.get("salary", {}))
    old_salary.pop("max_abs_delta_per_block", None)
    new_salary.pop("max_abs_delta_per_block", None)
    _require(_canonical(old_salary) == _canonical(new_salary),
             "V2492_SALARY_FORMULA_CONTRACT_DRIFT")

    # Preserve the complete V2490 performance contract except the named signed
    # schedule, release label, and one additional predecessor cache row.
    old_perf = copy.deepcopy(baseline["performance"])
    new_perf = copy.deepcopy(cfg.get("performance", {}))
    old_perf.pop("release", None); new_perf.pop("release", None)
    old_perf.pop("generation_step_schedule", None)
    new_perf.pop("generation_step_schedule", None)
    old_compat = old_perf["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
    new_compat = new_perf["persistent_path_cache"]["explicit_predecessor_read_compatibility"]
    old_compat.pop("target_release", None); new_compat.pop("target_release", None)
    new_compat["predecessors"] = [
        row for row in new_compat.get("predecessors", [])
        if row.get("source_release") != V2490_RELEASE
    ]
    _require(_canonical(old_perf) == _canonical(new_perf),
             "V2492_UNRELATED_PERFORMANCE_CONTRACT_DRIFT")


def validate_v2492_config(cfg: Mapping[str, Any], package_root=None) -> Mapping[str, Any]:
    root = Path(package_root).resolve() if package_root is not None else Path(__file__).resolve().parent
    predecessor = _load_and_validate_bundled_v2490(root)
    _validate_unchanged_top_level(cfg, root)

    _require(cfg.get("release") == RELEASE and cfg.get("safety_gate_release") == RELEASE,
             "V2492_RELEASE_IDENTITY_MISSING")
    _require(cfg.get("version") == "2.4.9.2-signed-generation-refinement-tg-td-supply",
             "V2492_VERSION_IDENTITY_MISSING")
    _require(str(cfg.get("guidance_mode", "")).upper() == "SIGNED" and
             cfg.get("allow_signed_apply") is True,
             "V2492_SIGNED_GUIDANCE_DISABLED")

    policy = cfg.get("generation_signed_refinement", {}) or {}
    expected_policy = {
        "enabled": True,
        "mode": "FAMILY_GLOBAL_PLUS_NONLINEAR_CENTERED_ZONE_LOG_EFFECT",
        "global_total_policy": "COMMON_CONSERVATIVE_FAMILY_TOTAL",
        "opposite_sign_total_policy": "ZERO_GLOBAL_KEEP_CENTERED_PATTERN",
        "centering_measure": "BASE_MARGIN_WEIGHTED_EXP_MULTIPLIER_EQUALS_ONE",
        "domestic_hard_min": 0.5,
        "domestic_hard_max": 2.0,
        "domestic_soft_min": 0.8,
        "domestic_soft_max": 1.25,
        "salary_hard_min": 0.5,
        "salary_hard_max": 2.0,
        "salary_soft_min": 0.8,
        "salary_soft_max": 1.25,
        "zahr_reference_multiplier_min": 0.5,
        "zahr_reference_multiplier_max": 2.0,
        "zahr_reference_soft_min": 0.7,
        "zahr_reference_soft_max": 1.3,
        "reference_source": "RUN_START_LIVE_VISUM_ZONE_ATTRIBUTES",
        "existing_outside_hard_envelope_policy": "ALLOW_INWARD_ONLY_NO_FORCED_ONE_STEP_CLAMP",
        "preserve_zero_policy": "UNCHANGED_EXISTING_ZERO_REMAINS_ZERO",
        "acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
    }
    for key, expected in expected_policy.items():
        _require(policy.get(key) == expected,
                 "V2492_SIGNED_POLICY_CHANGED:" + key)
    _require(0.0 < float(policy.get("soft_outward_step_factor", -1.0)) <= 1.0,
             "V2492_SOFT_OUTWARD_DAMPING_INVALID")
    _require(0.0 <= float(policy.get("max_family_global_log_up", -1.0)) <= 0.03 and
             0.0 <= float(policy.get("max_family_global_log_down", -1.0)) <= 0.03,
             "V2492_FAMILY_GLOBAL_STEP_INVALID")

    authority = cfg.get("generation_coefficient_authority", {}) or {}
    _require(authority.get("enabled") is True and
             authority.get("mode") ==
             "LIVE_CURRENT_VALUE_SIGNED_RELATIVE_LOG_STEP_WITH_EMPIRICAL_ENVELOPES",
             "V2492_COEFFICIENT_AUTHORITY_CHANGED")
    _require(authority.get("domestic_absolute_envelope") == [0.5, 2.0] and
             authority.get("salary_absolute_envelope") == [0.5, 2.0] and
             authority.get("zahr_envelope") == "RUN_START_REFERENCE_TIMES_[0.5,2.0]",
             "V2492_COEFFICIENT_ENVELOPE_CHANGED")

    projection = cfg.get("generation_bound_constrained_projection", {}) or {}
    _require(projection.get("enabled") is True and
             projection.get("mode") ==
             "SIGNED_CENTERED_ZONE_REFINEMENT_THEN_DOMAIN_AND_PA_REBALANCE" and
             projection.get("opposite_sign_policy") == "ZERO_GLOBAL_KEEP_CENTERED_PATTERN" and
             projection.get("role_balance_policy") ==
             "COMMON_FAMILY_TOTAL_PLUS_CENTERED_ZONE_PATTERN",
             "V2492_PROJECTION_POLICY_CHANGED")

    stages = cfg.get("performance", {}).get("generation_step_schedule", [])
    expected_names = ["SIGNED_EXPLORE", "SIGNED_REFINE", "DISTRIBUTION_FOCUS"]
    _require(isinstance(stages, list) and [s.get("name") for s in stages] == expected_names,
             "V2492_GENERATION_STAGE_NAMES_CHANGED")
    _require([int(s.get("through_outer_cycle", 0)) for s in stages] == [2, 4, 12],
             "V2492_GENERATION_STAGE_COVERAGE_CHANGED")
    limits = [(0.08, 0.06, 0.03), (0.06, 0.04, 0.015), (0.04, 0.02, 0.005)]
    for stage, (od, add, global_step) in zip(stages, limits):
        _require(float(stage.get("max_od_relative_up")) == od and
                 float(stage.get("max_od_relative_down")) == od and
                 float(stage.get("max_add_log_up")) == add and
                 float(stage.get("max_add_log_down")) == add and
                 float(stage.get("signed_max_family_global_log_up")) == global_step and
                 float(stage.get("signed_max_family_global_log_down")) == global_step,
                 "V2492_GENERATION_STAGE_LIMIT_CHANGED:" + str(stage.get("name")))
    last = stages[-1]
    _require(float(cfg.get("max_od_relative_up")) == float(last["max_od_relative_up"]) and
             float(cfg.get("max_od_relative_down")) == float(last["max_od_relative_down"]) and
             float(cfg.get("max_add_log_up")) == float(last["max_add_log_up"]) and
             float(cfg.get("max_add_log_down")) == float(last["max_add_log_down"]) and
             float(cfg.get("salary", {}).get("max_abs_delta_per_block")) ==
             float(last["salary_max_abs_delta_per_block"]),
             "V2492_FINAL_DISTRIBUTION_FOCUS_STAGE_NOT_BASE_ENVELOPE")

    compat = cfg.get("performance", {}).get("persistent_path_cache", {}).get(
        "explicit_predecessor_read_compatibility", {})
    _require(compat.get("target_release") == RELEASE,
             "V2492_CACHE_COMPAT_TARGET_CHANGED")
    rows = [r for r in compat.get("predecessors", [])
            if r.get("source_release") == V2490_RELEASE]
    _require(len(rows) == 1 and rows[0].get("source_config_sha256s") == [V2490_CONFIG_SHA256],
             "V2492_V2490_CONFIG_PROVENANCE_NOT_PINNED")
    _require(rows[0].get("source_path_implementation_files") == V2490_PATH_IMPLEMENTATION_FILES,
             "V2492_V2490_PATH_IMPLEMENTATION_NOT_PINNED")

    impl = cfg.get("implementation_files", {}) or {}
    required = (
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_2.py",
        "r1_15a2_safety_v2492.py", "r1_15a2_core.py",
        "r1_15a2_multiblock.py", "r1_15a2_supply_visum.py",
        "r1_15a2_overnight_controller_v242.py",
        "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
    )
    for name in required:
        _require(isinstance(impl.get(name), str) and len(impl[name]) == 64,
                 "V2492_IMPLEMENTATION_HASH_MISSING:" + name)

    return {
        "passes": True,
        "predecessor_contract": predecessor,
        "guidance_mode": "SIGNED",
        "generation_decomposition": policy["mode"],
        "domestic_hard_envelope": [0.5, 2.0],
        "domestic_soft_band": [0.8, 1.25],
        "zahr_reference_multiplier_envelope": [0.5, 2.0],
        "late_cycle_stage": "DISTRIBUTION_FOCUS",
        "fresh_visum_acceptance_retained": True,
        "real_visum_tested": False,
        "production_ready": False,
    }


__all__ = ["validate_v2492_config"]
