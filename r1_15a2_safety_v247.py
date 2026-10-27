"""Hard configuration and final-artifact contracts for R1 15A2 V2.4.7."""
from __future__ import annotations

import math
from pathlib import Path

from r1_15a2_safety_v245 import (
    adapter_config_scope,
    final_artifact_name,
    recovery_scope,
    stationary_td_result,
    validate_v245_config,
)
from r1_15a2_supply import SupplyContractError


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SupplyContractError("V246_INVALID_CONFIG:" + name)
    return value


def _finite_nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SupplyContractError("V246_INVALID_CONFIG:" + name)
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise SupplyContractError("V246_INVALID_CONFIG:" + name)
    return value


def validate_v247_config(cfg, package_root=None):
    """Validate every performance feature before any Visum model mutation."""
    base = validate_v245_config(cfg)
    perf = cfg.get("performance", {})
    release = perf.get("release")
    if release not in ("V2.4.7", "V2.4.8"):
        raise SupplyContractError("V247_PERFORMANCE_RELEASE_IDENTITY_MISSING")
    expected_semantics = (
        "PERSISTENT_PATH_EPOCH_ADAPTIVE_EXPLICIT_NOT_BITWISE_IDENTICAL"
        if release == "V2.4.8" else
        "PATH_EPOCH_ADAPTIVE_EXPLICIT_NOT_BITWISE_IDENTICAL")
    if perf.get("search_semantics") != expected_semantics:
        raise SupplyContractError("V247_SEARCH_SEMANTICS_NOT_ACKNOWLEDGED")

    telemetry = perf.get("telemetry", {})
    if telemetry.get("enabled") is not True:
        raise SupplyContractError("V246_TELEMETRY_REQUIRED")

    bulk = perf.get("bulk_link_read", {})
    if bulk.get("enabled") is not True or bulk.get("verify_object_no") is not True:
        raise SupplyContractError("V246_BULK_LINK_READ_NOT_VERIFIED")
    if bulk.get("fallback_to_scalar") is not True:
        raise SupplyContractError("V246_SCALAR_FALLBACK_REQUIRED")

    lazy = perf.get("lazy_supply_sequence_evidence", {})
    if lazy.get("enabled") is not True:
        raise SupplyContractError("V246_LAZY_SEQUENCE_EVIDENCE_REQUIRED")

    first = perf.get("first_sufficient", {})
    if first.get("enabled") is not True:
        raise SupplyContractError("V246_FIRST_SUFFICIENT_POLICY_REQUIRED")
    for key in ("generation_min_relative_improvement", "supply_min_relative_improvement"):
        value = _finite_nonnegative(first.get(key), key)
        if value >= 1.0:
            raise SupplyContractError("V246_FIRST_SUFFICIENT_THRESHOLD_OUT_OF_RANGE:" + key)

    gen_schedule = perf.get("generation_step_schedule")
    if not isinstance(gen_schedule, list) or len(gen_schedule) < 2:
        raise SupplyContractError("V246_GENERATION_STEP_SCHEDULE_MISSING")
    previous = 0
    gen_names = set()
    for stage in gen_schedule:
        if not isinstance(stage, dict):
            raise SupplyContractError("V246_GENERATION_STEP_STAGE_NOT_OBJECT")
        name = str(stage.get("name", ""))
        if not name or name in gen_names:
            raise SupplyContractError("V246_GENERATION_STEP_STAGE_NAME_INVALID")
        gen_names.add(name)
        through = _positive_int(stage.get("through_outer_cycle"),
                                "generation_step.through_outer_cycle")
        if through <= previous:
            raise SupplyContractError("V246_GENERATION_STEP_SCHEDULE_NOT_INCREASING")
        previous = through
        od = _finite_nonnegative(stage.get("max_od_relative_up"),
                                 "generation_step.max_od_relative_up")
        add = _finite_nonnegative(stage.get("max_add_log_up"),
                                  "generation_step.max_add_log_up")
        salary = _finite_nonnegative(stage.get("salary_max_abs_delta_per_block"),
                                     "generation_step.salary_max_abs_delta_per_block")
        if not (0 < od <= 0.25 and 0 < add <= 0.20 and 0 < salary <= 0.20):
            raise SupplyContractError("V246_GENERATION_STEP_STAGE_OUTSIDE_SAFE_CAP")

    two = cfg.get("two_mode", {})
    page = _positive_int(two.get("page_size"), "two_mode.page_size")
    if page > 4096:
        raise SupplyContractError("V246_PAGE_SIZE_ABOVE_VERIFIED_CAP")
    fallbacks = two.get("page_size_fallbacks")
    if not isinstance(fallbacks, list) or not fallbacks:
        raise SupplyContractError("V246_PAGE_FALLBACK_LADDER_MISSING")
    values = [_positive_int(x, "two_mode.page_size_fallbacks") for x in fallbacks]
    if any(x >= page for x in values) or values != sorted(set(values), reverse=True):
        raise SupplyContractError("V246_PAGE_FALLBACK_LADDER_INVALID")
    if values[-1] != 80:
        raise SupplyContractError("V246_PAGE_FALLBACK_MUST_END_AT_80")

    supply = cfg.get("supply", {})
    lattice = _finite_nonnegative(supply.get("lattice"), "supply.lattice")
    max_step = _finite_nonnegative(supply.get("max_step"), "supply.max_step")
    if lattice <= 0 or max_step <= 0:
        raise SupplyContractError("V246_ADDVAL_STEP_MUST_BE_POSITIVE")
    units = supply.get("sequence", {}).get("step_units_schedule")
    if not isinstance(units, list) or not units:
        raise SupplyContractError("V246_ADDVAL_STEP_SCHEDULE_MISSING")
    units = [_positive_int(x, "supply.sequence.step_units_schedule") for x in units]
    if units != sorted(set(units), reverse=True) or units[-1] != 1:
        raise SupplyContractError("V246_ADDVAL_STEP_SCHEDULE_INVALID")
    if max(units) * lattice > max_step + 1e-12:
        raise SupplyContractError("V246_ADDVAL_STEP_SCHEDULE_EXCEEDS_MAX_STEP")

    dc = cfg.get("coupled_demand", {})
    if previous < int(dc.get("max_outer_cycles", 0)):
        raise SupplyContractError("V246_GENERATION_STEP_SCHEDULE_DOES_NOT_COVER_OUTER_LOOP")
    final_gen = gen_schedule[-1]
    if (float(final_gen["max_od_relative_up"]) != float(cfg.get("max_od_relative_up")) or
            float(final_gen["max_add_log_up"]) != float(cfg.get("max_add_log_up")) or
            float(final_gen["salary_max_abs_delta_per_block"]) !=
            float(cfg.get("salary", {}).get("max_abs_delta_per_block"))):
        raise SupplyContractError("V246_FINAL_GENERATION_STAGE_NOT_FULL_ORIGINAL_ENVELOPE")

    fine = dc.get("finecdf_td", {})
    schedule = fine.get("progressive_schedule")
    if not isinstance(schedule, list) or len(schedule) < 2:
        raise SupplyContractError("V246_PROGRESSIVE_TD_SCHEDULE_MISSING")
    previous = 0
    names = set()
    for i, stage in enumerate(schedule):
        if not isinstance(stage, dict):
            raise SupplyContractError("V246_PROGRESSIVE_TD_STAGE_NOT_OBJECT")
        name = str(stage.get("name", ""))
        if not name or name in names:
            raise SupplyContractError("V246_PROGRESSIVE_TD_STAGE_NAME_INVALID")
        names.add(name)
        through = _positive_int(stage.get("through_outer_cycle"), "through_outer_cycle")
        if through <= previous:
            raise SupplyContractError("V246_PROGRESSIVE_TD_SCHEDULE_NOT_INCREASING")
        previous = through
        mi = _positive_int(stage.get("max_iterations"), "stage.max_iterations")
        me = _positive_int(stage.get("max_td_evaluations"), "stage.max_td_evaluations")
        if mi > fine.get("max_iterations") or me > fine.get("max_td_evaluations"):
            raise SupplyContractError("V246_PROGRESSIVE_TD_STAGE_EXCEEDS_FULL_BUDGET")
        allow = stage.get("allow_progress_continue")
        if not isinstance(allow, bool):
            raise SupplyContractError("V246_PROGRESSIVE_TD_ALLOW_FLAG_INVALID")
        if i < len(schedule)-1 and allow is not True:
            raise SupplyContractError("V246_EARLY_TD_STAGE_MUST_ALLOW_PROGRESS")
    if previous < dc.get("max_outer_cycles"):
        raise SupplyContractError("V246_PROGRESSIVE_TD_SCHEDULE_DOES_NOT_COVER_OUTER_LOOP")
    last = schedule[-1]
    if last.get("allow_progress_continue") is not False:
        raise SupplyContractError("V246_FINAL_TD_STAGE_MUST_BE_FULL")
    if (last.get("max_iterations") != fine.get("max_iterations") or
            last.get("max_td_evaluations") != fine.get("max_td_evaluations")):
        raise SupplyContractError("V246_FINAL_TD_STAGE_NOT_FULL_BUDGET")

    expected_rel = "reference_v18/R1_BC_AUTO_DIST_ONLY_FINECDF_ADAPTIVE_v1_8.py"
    expected_id = "R1_BC_AUTO_DIST_ONLY_FINECDF_ADAPTIVE_V1_8_20261016"
    if fine.get("reference_script") != expected_rel or fine.get("reference_script_id") != expected_id:
        raise SupplyContractError("V246_FINECDF_V18_AUTHORITY_NOT_LOCKED")
    expected_sha = str(fine.get("reference_sha256", ""))
    if len(expected_sha) != 64:
        raise SupplyContractError("V246_FINECDF_V18_SHA_INVALID")
    if package_root is not None:
        import hashlib
        path = Path(package_root) / expected_rel
        if not path.is_file():
            raise SupplyContractError("V246_FINECDF_V18_FILE_MISSING")
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        if h != expected_sha:
            raise SupplyContractError("V246_FINECDF_V18_FILE_HASH_MISMATCH")

    epochs = perf.get("path_epochs", {})
    if epochs.get("enabled") is not True:
        raise SupplyContractError("V247_PATH_EPOCHS_REQUIRED")
    if epochs.get("initial_enumeration_required") is not True:
        raise SupplyContractError("V247_INITIAL_PATH_ENUMERATION_REQUIRED")
    if epochs.get("refresh_trigger") != "COMPLETE_LOCAL_PLATEAU_ON_CURRENT_PATH_BASIS":
        raise SupplyContractError("V247_PATH_EPOCH_REFRESH_TRIGGER_NOT_LOCKED")
    if epochs.get("fresh_assignment_acceptance_authority") is not True:
        raise SupplyContractError("V247_FRESH_ASSIGNMENT_ACCEPTANCE_REQUIRED")
    if epochs.get("new_positive_od_without_epoch_support_forces_reenumeration") is not True:
        raise SupplyContractError("V247_NEW_POSITIVE_OD_REFRESH_GATE_REQUIRED")
    if epochs.get("policy") != "INITIAL_ENUMERATION_REUSED_UNTIL_LOCAL_PLATEAU_THEN_FRESH_REENUMERATION":
        raise SupplyContractError("V247_PATH_EPOCH_POLICY_NOT_LOCKED")
    if epochs.get("live_od_reweighting") is not True or epochs.get("live_profile_rebind") is not True:
        raise SupplyContractError("V247_PATH_EPOCH_LIVE_REBIND_REQUIRED")
    if epochs.get("new_positive_od_policy") != "MANDATORY_REENUMERATION_NO_INVENTED_PATH_SHARE":
        raise SupplyContractError("V247_NEW_POSITIVE_OD_POLICY_NOT_LOCKED")
    if epochs.get("stationarity_requires_fresh_identical_basis") is not True:
        raise SupplyContractError("V247_PATH_EPOCH_STATIONARITY_GATE_REQUIRED")
    if epochs.get("comparison_basis") != "GEOMETRY_PARENT_KEYS_AND_PATH_VOLUMES_ROUNDED_6_DECIMALS":
        raise SupplyContractError("V247_PATH_EPOCH_COMPARISON_BASIS_NOT_LOCKED")
    if cfg.get("two_mode", {}).get("path_epoch_volume_comparison_decimals") != 6:
        raise SupplyContractError("V247_PATH_EPOCH_VOLUME_PRECISION_NOT_LOCKED")
    if epochs.get("cleanup_obsolete_sqlite_after_verified_refresh") is not True:
        raise SupplyContractError("V247_PATH_EPOCH_SQLITE_CLEANUP_REQUIRED")
    if epochs.get("retain_sqlite_stores") != 1:
        raise SupplyContractError("V247_PATH_EPOCH_SQLITE_RETENTION_NOT_LOCKED")
    demand_refresh = _positive_int(epochs.get("max_demand_reenumerations"),
                                   "path_epochs.max_demand_reenumerations")
    supply_refresh = _positive_int(epochs.get("max_supply_reenumerations"),
                                   "path_epochs.max_supply_reenumerations")
    if demand_refresh > 32 or supply_refresh > 64:
        raise SupplyContractError("V247_PATH_EPOCH_REFRESH_LIMIT_UNSAFE")
    if epochs.get("acceptance_authority") != "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D":
        raise SupplyContractError("V247_PATH_EPOCH_ACCEPTANCE_AUTHORITY_CHANGED")
    if cfg.get("trial_calibration", {}).get("path_epoch_calibration") is not True:
        raise SupplyContractError("V247_TRIAL_PATH_EPOCH_ACKNOWLEDGEMENT_MISSING")

    return {
        "passes": True,
        "base_contract": base,
        "bulk_link_read": True,
        "adaptive_page_size": page,
        "addval_step_units": units,
        "generation_step_stages": [s["name"] for s in gen_schedule],
        "progressive_td_stages": [s["name"] for s in schedule],
        "path_epoch_limits": {"DEMAND": demand_refresh, "SUPPLY": supply_refresh},
        "minimum_confirmed_stationary_cycles": dc.get("min_stationary_cycles"),
    }


__all__ = [
    "adapter_config_scope", "final_artifact_name", "recovery_scope",
    "stationary_td_result", "validate_v247_config",
]
