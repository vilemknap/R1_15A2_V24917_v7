# -*- coding: utf-8 -*-
"""R1 15A2 V2.4.8.9 TD realization and rollback-evidence stabilization: persistent path-epoch calibration.

Extends V2.4.7 with immutable cross-run path-epoch checkpoints and accepted-state bindings.
Adaptive search can follow a different accepted path than V2.4.5, while every
candidate still requires the unchanged live assignment and acceptance gates.

Run manually from Visum Scripts > Execute script file, never from Procedure Sequence.
The source .ver is preserved. The script first saves an isolated working copy,
then performs real candidate writes, real Visum recomputations, live acceptance,
and no-LoadVersion in-place rollback for rejected candidates.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import contextlib
import csv
import json
import os
import sys
import traceback

HERE = Path(__file__).resolve().parent
if globals().get("Visum") is not None or globals().get("COM") is not None:
    if getattr(sys, "_r1_15a2_calibration_busy", False):
        raise RuntimeError("ANOTHER_15A2_RUN_IS_ACTIVE")
    for name in list(sys.modules):
        if name.startswith("r1_15a2_"):
            del sys.modules[name]
_ORIGINAL_SYS_PATH = list(sys.path)
# A previous Visum run may have left another release ahead of this directory.
# Give this complete release first priority even when HERE is already present.
sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]

import r1_15a2_com_compat as com
import r1_15a2_live_api_audit as api_audit
import r1_15a2_runtime_v1 as rt
import r1_15a2_supply_visum as supply_runtime
import r1_15a2_visum_parameters as vp
from r1_15a2_supply import canonical_hash
from r1_15a2_safety_v248 import final_artifact_name
from r1_15a2_safety_v2489 import validate_v2489_config
from r1_15a2_trial_adapter_v243 import VisumAdapter
from r1_15a2_overnight_controller_v240 import OvernightControl, atomic_json
from r1_15a2_overnight_controller_v242 import run_overnight_calibration_coupled

RELEASE = "R1_15A2_V2_4_8_9_TD_REALIZATION_STABILIZATION_20261016"


def _is_runs_root(path):
    name = Path(path).name.upper()
    return name.startswith("R1_15A2_") and name.endswith("_RUNS")


def _run_tree_ancestors(source_ver):
    """Return qualifying RUNS ancestors from nearest to outermost.

    A directory only qualifies when the source is below its RUN_* child. This
    avoids treating an unrelated archive directory ending in _RUNS as a live
    calibration run tree.
    """
    source_ver = Path(source_ver).resolve()
    found = []
    for candidate in (source_ver.parent,) + tuple(source_ver.parent.parents):
        if not _is_runs_root(candidate):
            continue
        try:
            rel = source_ver.relative_to(candidate)
        except ValueError:
            continue
        if len(rel.parts) >= 2 and rel.parts[0].upper().startswith("RUN_"):
            found.append(candidate)
    return found


def _stable_project_layout(source_ver):
    """Resolve a stable project root from plain, singly nested or repeatedly
    nested accepted checkpoints.

    V2.4.8.3 nested the next RUNS directory below the loaded checkpoint.
    V2.4.8.4 fixed one nesting level by taking the nearest RUNS ancestor, but a
    checkpoint from an already nested failed run still had two RUNS ancestors.
    The correct project base is the parent of the *outermost* qualifying RUNS
    ancestor. The loaded .ver remains the immutable source authority.
    """
    source_ver = Path(source_ver).resolve()
    roots = _run_tree_ancestors(source_ver)
    if roots:
        outermost = roots[-1]
        project_base = outermost.parent.resolve()
        mode = "OUTERMOST_PRIOR_RUN_TREE_NORMALIZED"
    else:
        outermost = None
        project_base = source_ver.parent.resolve()
        mode = "SOURCE_PARENT"
    return {
        "source_version": source_ver,
        "project_base": project_base,
        "mode": mode,
        "detected_run_roots_nearest_first": roots,
        "outermost_run_root": outermost,
    }


def _stable_project_base(source_ver):
    layout = _stable_project_layout(source_ver)
    return layout["project_base"], layout["mode"]


def _is_relative_to(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def _assert_new_run_is_not_nested(run_directory, prior_run_roots):
    for prior in prior_run_roots:
        if _is_relative_to(run_directory, prior):
            raise RuntimeError("V2489_NEW_RUN_STILL_NESTED_UNDER_PRIOR_RUN_TREE:%s" % prior)



def load_config():
    path = HERE / "R1_15A2_CONFIG_V2_4_8_9.json"
    cfg = rt.read_json(path)
    # Hard locks: working-copy calibration is not production release/apply.
    cfg["apply"] = False
    cfg["production_apply"] = False
    cfg["trial_calibration"]["enabled"] = True
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = rt.sha256_file(path)
    implementation = [
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_9.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_8.py",
        "r1_15a2_trial_adapter_v243.py", "r1_15a2_trial_adapter_v240.py", "r1_15a2_overnight_controller_v240.py",
        "r1_15a2_overnight_controller_v242.py", "r1_15a2_finecdf_bridge_v242.py",
        "reference_v18/R1_BC_AUTO_DIST_ONLY_FINECDF_ADAPTIVE_v1_8.py",
        "r1_15a2_inplace_transaction_v239.py", "r1_15a2_assignment_authority_v239.py",
        "r1_15a2_two_mode_v238.py", "r1_15a2_com_compat.py", "r1_15a2_live_api_audit.py",
        "r1_15a2_controller_v22.py", "r1_15a2_sequence_v23.py", "r1_15a2_supply.py",
        "r1_15a2_supply_visum.py", "r1_15a2_runtime_v1.py", "r1_15a2_core.py",
        "r1_15a2_multiblock.py", "r1_15a2_visum_parameters.py", "r1_15a2_safety_v246.py", "r1_15a2_safety_v247.py", "r1_15a2_safety_v248.py", "r1_15a2_safety_v2482.py", "r1_15a2_safety_v2483.py", "r1_15a2_safety_v2485.py", "r1_15a2_safety_v2486.py", "r1_15a2_safety_v2487.py", "r1_15a2_safety_v2488.py", "r1_15a2_safety_v2489.py", "r1_15a2_persistent_path_cache_v248.py", "r1_15a2_perf_v246.py",
        "R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1.py",
    ]
    # Include every local runtime module and diagnostic helper, not just the
    # manually enumerated immediate imports. Old aliases cannot pass as V245.
    implementation = sorted(set(implementation) |
                            {str(p.relative_to(HERE)) for p in HERE.glob("r1_15a2_*.py")} |
                            {str(p.relative_to(HERE)) for p in (HERE / "helpers").glob("*.py")})
    cfg["implementation_files"] = {name: rt.sha256_file(HERE / name) for name in implementation}
    cfg["implementation_hash"] = canonical_hash(cfg["implementation_files"])
    cfg["cp03_live_hotfixes"] = ["SHORT_RUN_ROOT", "SHORT_OS_TEMP_11D_12D_HELPER_WORKSPACES", "ROLLBACK_STATE_EVIDENCE_BEFORE_DIAGNOSTICS"]
    cfg["cp02_performance_features"] = [
        "PER_OPERATION_TELEMETRY", "BULK_LINK_COM_READ_WITH_VERIFIED_FALLBACK",
        "ADAPTIVE_BOUNDED_PATH_PAGING", "LAZY_SUPPLY_SEQUENCE_EVIDENCE",
        "FIRST_SUFFICIENT_LIVE_CANDIDATE", "ADAPTIVE_GENERATION_STEP_SCHEDULE",
        "PROGRESSIVE_FINECDF_V18", "ADAPTIVE_FINECDF_TRUST_REGION",
        "ADDVAL1_STEP_UNITS_4_2_1",
    ]
    cfg["v248_persistent_path_cache_features"] = [
        "INITIAL_PATH_ENUMERATION_ONCE",
        "FROZEN_PATH_BASIS_REUSED_ACROSS_ACCEPTED_STATES",
        "LIVE_OD_TOTAL_REWEIGHT_ON_FROZEN_PATH_SHARES",
        "LIVE_PROFILE_RESIDUAL_REBIND_WITHOUT_COM_REENUMERATION",
        "REENUMERATE_ONLY_AFTER_COMPLETE_LOCAL_PLATEAU",
        "FRESH_IDENTICAL_PATH_BASIS_REQUIRED_FOR_STATIONARITY",
        "NEW_POSITIVE_OD_FORCES_REENUMERATION_NO_INVENTED_SHARE",
        "IMMUTABLE_SQLITE_CHECKPOINT_AFTER_EVERY_SUCCESSFUL_ENUMERATION",
        "SHA256_AND_SQLITE_INTEGRITY_VERIFIED_CROSS_RUN_RESTORE",
        "EXPLICIT_ACCEPTED_STATE_TO_PATH_EPOCH_BINDINGS",
        "LEGACY_V247_EXACT_STATE_IMPORT_WITH_ALL_PROFILE_FLOW_PARITY",
        "READ_ONLY_PERSISTENT_STORE_DURING_CALIBRATION",
        "INTRAZONAL_POSITIVE_OD_NEVER_REQUIRES_NETWORK_PATH_SUPPORT",
        "WINDOWS_OBSOLETE_SQLITE_DELETE_LOCK_IS_NONFATAL_AFTER_VERIFIED_REFRESH",
        "ZERO_SAVED_SHARE_EXISTING_GEOMETRY_RESIDUAL_WITHIN_PARITY_IS_GUIDANCE_EXCLUDED",
        "EXPLICIT_V2481_V2482_READ_ONLY_CACHE_CONTRACT_COMPATIBILITY",
    ]
    cfg["v2486_unified_features"] = [
        "OUTERMOST_PRIOR_RUN_TREE_NORMALIZATION",
        "NEW_RUN_OUTSIDE_ALL_DETECTED_PRIOR_RUN_ROOTS_POSTCONDITION",
        "DIRECT_ACTUATOR_CAPACITY_CLIP_BEFORE_GENERATION_TRIAL",
        "SAME_FAMILY_PA_ROLE_ATTENUATION_PRESERVES_SPATIAL_PATTERN",
        "SATURATED_REQUESTS_AUDITED_NOT_SILENTLY_DROPPED",
        "UNCHANGED_FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D_ACCEPTANCE",
        "READ_ONLY_CACHE_COMPATIBILITY_V2481_THROUGH_BOTH_V2485_BRANCHES",
    ]
    cfg["v2487_live_coefficient_features"] = [
        "LIVE_VISUM_ZONE_ATTRIBUTE_IS_COEFFICIENT_AUTHORITY",
        "NO_GLOBAL_ABSOLUTE_UPPER_BOUND_FOR_ADD_OR_ZAHR_COEFFICIENTS",
        "SALARY_USES_CURRENT_VALUE_PLUS_PER_BLOCK_DELTA_AND_FORMULA_DOMAIN",
        "RELATIVE_LOG_STEP_REMAINS_STAGE_AND_BACKTRACKING_BOUNDED",
        "FINITE_NONNEGATIVE_MULTIPLICATIVE_DOMAIN_REMAINS_FAIL_CLOSED",
        "LEGACY_3_AND_10_LIMITS_DISABLED_NOT_RELAXED_TO_NEW_MAGIC_NUMBERS",
        "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D_ACCEPTANCE_UNCHANGED",
        "READ_ONLY_CACHE_COMPATIBILITY_V2481_THROUGH_V2486",
    ]
    cfg["v2488_path_cache_semantic_compat_features"] = [
        "FULL_CONFIG_SHA_IS_PROVENANCE_NOT_PATH_DATA_IDENTITY",
        "EXPLICIT_PATH_SEMANTIC_FIELDS_REMAIN_EXACT",
        "FULL_SEVEN_MODULE_PATH_IMPLEMENTATION_MAP_REQUIRED_FOR_REVIEWED_PREDECESSOR",
        "ACTUAL_DEPLOYED_V2482_ZERO_VOLUME_RELEASE_HASHES_PINNED",
        "INCOMPATIBLE_CACHE_IS_PERFORMANCE_MISS_NOT_CALIBRATION_ABORT",
        "CORRUPTION_INTEGRITY_BINDING_AND_STORE_HASH_FAILURES_REMAIN_FAIL_CLOSED",
        "LEGACY_EXACT_STATE_IMPORT_OR_FRESH_ENUMERATION_FALLBACK",
    ]
    cfg["v2489_td_realization_stabilization_features"] = [
        "BACKTRACK_NATIVE_TD_REALIZATION_IN_B_AND_LOG_NEG_C",
        "NATIVE_20B_IPF_NONCONVERGENCE_ONLY_IS_RETRYABLE",
        "IPF_TOLERANCE_IS_NEVER_RELAXED",
        "RESTORE_ACCEPTED_PARENT_BC_BEFORE_EACH_REALIZATION_ATTEMPT",
        "NO_NEXT_GENERATION_UNTIL_TD_REALIZATION_COMPLETE",
        "TD_REALIZATION_EXHAUSTION_IS_FAIL_CLOSED_NOT_PLATEAU",
        "ATOMIC_11D_12D_EVIDENCE_COPY",
        "CENTRAL_SHORT_RUN_ROOT_HELPER_MIRROR_WHEN_PATH_IS_UNSAFE",
    ]
    for module in (com, api_audit, rt, vp, supply_runtime):
        if Path(module.__file__).resolve().parent != HERE.resolve():
            raise RuntimeError("V248_MIXED_RELEASE_MODULE:" + module.__name__)
    for rel, target in ((cfg["tg_dependency_contract_file"], "tg_dependency_contract"),
                        (cfg["td"]["long_authority_file"], "long_authority")):
        p = HERE / rel
        cfg[target] = rt.read_json(p)
        cfg[target + "_path"] = str(p)
        cfg[target + "_sha256"] = rt.sha256_file(p)
    cfg["api_approved_observations"] = []
    for fn in ("R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv", "R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_90.csv"):
        with (HERE / "authorities" / fn).open(encoding="utf-8-sig", newline="") as h:
            for r in csv.DictReader(h):
                cfg["api_approved_observations"].append({
                    "no": int(r["countlocation_no"]),
                    "observed": float(r["observed_passenger_cars_O"]),
                    "role": r["role"], "weight": float(r["live_weight"]),
                    "edge_key": [int(r[k]) for k in ("current_link_no", "current_from_node_no", "current_to_node_no")],
                    "direction": r.get("observation_direction", "DIRECTIONAL"),
                    "countlocation_code": r["countlocation_code"], "profile_id": r["profile_id"],
                    "period_basis": r["period_basis"],
                    "observed_scope": r.get("vehicle_scope_original", r.get("vehicle_scope")),
                })
    validate_v2489_config(cfg, HERE)
    return cfg


def _main_impl():
    visum, _ = com.bind_injected(globals())
    source_ver = Path(str(visum.IO.CurrentVersionFile))
    if not source_ver.is_file():
        raise RuntimeError("CURRENT_VERSION_FILE_NOT_FOUND")
    source_sha_before = rt.sha256_file(source_ver)
    # Resolve a stable project-level output location before SaveVersion changes
    # CurrentVersionFile.  A loaded accepted checkpoint may live deep inside a
    # previous RUNS tree; never nest the next run below that checkpoint folder.
    project_layout = _stable_project_layout(source_ver)
    project_base = project_layout["project_base"]
    project_base_mode = project_layout["mode"]
    runs = project_base / "R1_15A2_V2489_RUNS"
    runs.mkdir(parents=True, exist_ok=True)
    folder = runs / ("RUN_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir()
    _assert_new_run_is_not_nested(folder, project_layout["detected_run_roots_nearest_first"])
    (runs / "LATEST_RUN.txt").write_text(str(folder), encoding="utf-8")
    (folder / "00_RELEASE.txt").write_text(RELEASE + "\n", encoding="utf-8")
    lock = project_base / ".R1_15A2_FULL_CALIBRATION.lock"
    have_lock = False
    adapter = None
    control = None
    prior_runtime_visum = getattr(rt, "Visum", None)
    prior_base_visum = getattr(supply_runtime.base, "Visum", None)
    result = {"status": "STARTING", "release": RELEASE, "production_apply": False, "trial_writes": True}
    with (folder / "CONSOLE_CAPTURE.log").open("w", encoding="utf-8") as console:
        with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                have_lock = True
                with os.fdopen(fd, "w", encoding="utf-8") as h:
                    json.dump({"pid": os.getpid(), "run": str(folder)}, h)
                have_lock = True
                sys._r1_15a2_calibration_busy = True
                cfg = load_config()
                local_appdata = os.environ.get("LOCALAPPDATA")
                cache_root = (Path(local_appdata) / "R1_15A2_PATH_CACHE_V248"
                              if local_appdata else
                              project_base / "R1_15A2_PATH_CACHE_V248")
                legacy_roots = [
                    project_base / "R1_15A2_V2488_RUNS",
                    project_base / "R1_15A2_V2487_RUNS",
                    project_base / "R1_15A2_V2486_RUNS",
                    project_base / "R1_15A2_V2485_RUNS",
                    project_base / "R1_15A2_V2484_RUNS",
                    project_base / "R1_15A2_V2483_RUNS",
                    project_base / "R1_15A2_V2482_RUNS",
                    project_base / "R1_15A2_V2481_RUNS",
                    project_base / "R1_15A2_V247_RUNS",
                    project_base / "R1_15A2_V246_RUNS",
                    project_base / "R1_15A2_V245_RUNS",
                    project_base / "R1_15A2_V2_4_5_FULL_CALIBRATION_REPAIR_RUNS",
                ]
                cfg["runtime_persistent_path_cache_root"] = str(cache_root)
                cfg["runtime_legacy_path_cache_roots"] = [str(x) for x in legacy_roots]
                cfg["runtime_source_version_sha256"] = source_sha_before
                cfg["runtime_source_version_path"] = str(source_ver)
                atomic_json(folder / "RUN_ROOT_AUTHORITY.json", {
                    "source_version": str(source_ver),
                    "source_parent": str(source_ver.parent),
                    "project_base": str(project_base),
                    "project_base_mode": project_base_mode,
                    "detected_run_roots_nearest_first": [str(x) for x in project_layout["detected_run_roots_nearest_first"]],
                    "outermost_run_root": (str(project_layout["outermost_run_root"])
                                             if project_layout["outermost_run_root"] is not None else None),
                    "normalization_depth": len(project_layout["detected_run_roots_nearest_first"]),
                    "runs_root": str(runs),
                    "run_directory": str(folder),
                    "policy": "OUTERMOST_QUALIFYING_RUNS_ANCESTOR_PARENT; NEVER_NEST_NEW_RUN_UNDER_PRIOR_RUN_TREE",
                    "postcondition_new_run_outside_all_detected_prior_run_roots": True,
                })
                atomic_json(folder / "PERSISTENT_PATH_CACHE_LOCATION.json", {
                    "root": str(cache_root),
                    "root_policy": cfg["performance"]["persistent_path_cache"]["root_policy"],
                    "legacy_roots": [str(x) for x in legacy_roots],
                    "source_version": str(source_ver),
                    "source_sha256": source_sha_before,
                })
                methodology = {
                    "production_release": False,
                    "working_copy_trial_calibration": True,
                    "csd408_mapping_review_acknowledged": bool(cfg.get("csd408_mapping_review_acknowledged", False)),
                    "city90_bidirectional_qa_acknowledged": bool(cfg.get("city90_bidirectional_qa_acknowledged", False)),
                    "two_mode_full_geometry_identity_proven": False,
                    "two_mode_geometry_role": "CANDIDATE_PROPOSAL_ONLY",
                    "candidate_acceptance_role": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_DIAGNOSTICS",
                    "duplicate_policy": cfg.get("supply", {}).get("sequence", {}).get("design_only_duplicate_scope_policy"),
                    "observation_contract": "498_INDEPENDENT_ROWS_PRESERVED_CAL_VALID_ROLES_UNCHANGED",
                    "calibration_order": ["COUPLED_DEMAND:GENERATION_THEN_FINECDF_TD_REPEAT", "SUPPLY_ROUTE_CHOICE"],
                    "supply_addval1_role": "FINAL_ROUTE_CHOICE_LINK_TUNING_AFTER_COUPLED_DEMAND_FIXED_POINT_ONLY",
                    "trip_generation_and_distribution_relationship": "ONE_COUPLED_DEMAND_PHASE_NOT_INDEPENDENT_PHASES",
                    "td_authority": "HASH_LOCKED_R1_BC_AUTO_DIST_ONLY_FINECDF_ADAPTIVE_V1_8_512_POINT_IDP",
                    "native_multi_guard_policy": "DIAGNOSTIC_ONLY_NATIVE_OUTPUT_AUTHORITY",
                    "performance_search_semantics": "PERSISTENT_PATH_EPOCH_ADAPTIVE_EXPLICIT_NOT_BITWISE_IDENTICAL",
                    "path_enumeration_policy": "AUTHORIZED_PERSISTENT_CACHE_OR_FRESH_ENUMERATION_THEN_ONLY_AT_LOCAL_PLATEAU",
                    "path_epoch_acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_DIAGNOSTICS",
                    "persistent_path_cache_policy": "HASHED_SQLITE_PLUS_ACCEPTED_STATE_BINDINGS_FAIL_CLOSED",
                    "stable_project_root_policy": "OUTERMOST_PRIOR_RUN_TREE_NORMALIZED_AND_POSTCONDITION_CHECKED",
                    "generation_bound_projection_policy": "CLIP_DIRECT_ACTUATOR_CAPACITY_THEN_ATTENUATE_LARGER_PA_ROLE",
                    "generation_bound_projection_acceptance": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
                    "td_realization_policy": "BACKTRACK_B_AND_LOG_NEG_C_WITH_UNCHANGED_NATIVE_IPF_TOLERANCE",
                    "td_generation_gate": "TD_REALIZATION_COMPLETE_BEFORE_NEXT_GENERATION",
                    "rollback_evidence_policy": "ATOMIC_COPY_AND_CENTRAL_SHORT_RUN_ROOT_MIRROR_WHEN_NEEDED",
                    "cp03_live_path_hotfix_retained": True,
                }
                atomic_json(folder / "METHODOLOGY_STATUS.json", methodology)
                result["methodology_status"] = methodology
                atomic_json(folder / "SOURCE_VERSION_AUTHORITY.json", {
                    "source_version": str(source_ver), "source_sha256_before": source_sha_before,
                    "policy": "SOURCE_FILE_MUST_REMAIN_UNTOUCHED_WORK_ONLY_ON_SAVED_COPY",
                })
                # Isolate all subsequent writes from the user's source .ver.
                working = folder / "WORKING_START.ver"
                working_cp = rt.save_version(visum, working)
                atomic_json(folder / "WORKING_COPY.json", working_cp)
                control = OvernightControl(folder, cfg)
                rt.Visum = visum

                # Full API audit remains read-only and catches COM/schema drift before writes.
                def td_check():
                    state = vp.read_td_parameter_state(visum)
                    return {"passes": all(r["status"] == "OK" for r in state["rows"]),
                            "rows": state["rows"], "operation_rows": state["operation_rows"]}
                control.checkpoint("LIVE_API_PREFLIGHT", force=True)
                report = api_audit.collect_live_api(visum, cfg, folder / "API_PREFLIGHT", extra_checks=(
                    ("TG_FORMULA_PARAMETER_BINDINGS", lambda: vp.audit_trip_generation_contract(visum, cfg)),
                    ("TD_COMPONENT_PARAMETER_BINDINGS", td_check),
                    ("PROCSEQ_TYPE_ORDER", lambda: rt.audit_procseq(visum, folder / "API_PREFLIGHT", cfg)),
                ))
                if report["required_failures"]:
                    result = {"status": "LIVE_API_PREFLIGHT_FAILED", "required_failures": report["required_failures"]}
                else:
                    adapter = VisumAdapter(visum, cfg, control)
                    result = run_overnight_calibration_coupled(adapter, cfg, folder / "CALIBRATION", control, HERE)

                # Save a final deliverable only when the controller exposes a verified live state.
                final_name = final_artifact_name(result)
                if adapter is not None and final_name is not None:
                    try:
                        live = adapter.snapshot()
                        if live["state_hash"] != result["final_state_hash"]:
                            raise RuntimeError("FINAL_LIVE_STATE_DIFFERS_FROM_CONTROLLER_ACCEPTED_STATE")
                        if rt.sha256_file(source_ver) != source_sha_before:
                            raise RuntimeError("SOURCE_FILE_CHANGED_BEFORE_FINAL_SAVE")
                        final_cp = rt.save_version(visum, folder / final_name)
                        if adapter.snapshot() != live:
                            raise RuntimeError("SAVEVERSION_CHANGED_VERIFIED_MODEL_STATE")
                        result["final_accepted_version"] = final_cp
                    except Exception as exc:
                        result["final_save_error"] = str(exc)
                        result["status"] = "FINAL_SAVE_FAILED_USE_LATEST_ACCEPTED_CHECKPOINT"
                elif adapter is not None:
                    result["final_accepted_version_not_written"] = "NO_VERIFIED_FINAL_STATE_OR_FAILED_RUN"
            except BaseException as exc:
                result = {"status": "FULL_OVERNIGHT_FAILED", "error": str(exc), "traceback": traceback.format_exc(),
                          "production_apply": False, "trial_writes": True}
            finally:
                try:
                    source_sha_after = rt.sha256_file(source_ver)
                    result["source_version"] = str(source_ver)
                    result["source_sha256_before"] = source_sha_before
                    result["source_sha256_after"] = source_sha_after
                    result["source_file_unchanged"] = source_sha_after == source_sha_before
                    if not result["source_file_unchanged"]:
                        result["status"] = "SOURCE_VERSION_FILE_CHANGED_UNEXPECTEDLY"
                except Exception as exc:
                    result["source_integrity_error"] = str(exc)
                    result["status"] = "FAILED_SOURCE_INTEGRITY_UNVERIFIED"
                result.update(release=RELEASE, production_apply=False, trial_writes=True,
                              load_version_called=False, run_directory=str(folder))
                if adapter is not None:
                    try:
                        adapter.close()
                    except Exception as exc:
                        result["adapter_close_error"] = str(exc)
                try:
                    atomic_json(folder / "00_RESULT.json", result)
                    (folder / "00_FINAL_STATUS.txt").write_text(str(result.get("status")) + "\n", encoding="utf-8")
                    if control is not None:
                        control.finish(result.get("status", "FINISHED"), accepted_count=result.get("accepted_count"))
                finally:
                    rt.Visum = prior_runtime_visum
                    supply_runtime.base.Visum = prior_base_visum
                    if have_lock:
                        sys._r1_15a2_calibration_busy = False
                        try:
                            lock.unlink()
                        except OSError:
                            pass
                    sys.path[:] = _ORIGINAL_SYS_PATH
    return result


def main():
    try:
        return _main_impl()
    finally:
        sys.path[:] = _ORIGINAL_SYS_PATH


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
