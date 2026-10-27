# -*- coding: utf-8 -*-
"""R1 15A2 V2.4.8 persistent path-epoch adaptive-performance coupled-demand and ADDVAL1 calibration.

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
from r1_15a2_safety_v248 import validate_v248_config, final_artifact_name
from r1_15a2_trial_adapter_v243 import VisumAdapter
from r1_15a2_overnight_controller_v240 import OvernightControl, atomic_json
from r1_15a2_overnight_controller_v242 import run_overnight_calibration_coupled

RELEASE = "R1_15A2_V2_4_8_PERSISTENT_PATH_CACHE_20261016"


def load_config():
    path = HERE / "R1_15A2_CONFIG_V2_4_8.json"
    cfg = rt.read_json(path)
    # Hard locks: working-copy calibration is not production release/apply.
    cfg["apply"] = False
    cfg["production_apply"] = False
    cfg["trial_calibration"]["enabled"] = True
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = rt.sha256_file(path)
    implementation = [
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8.py",
        "r1_15a2_trial_adapter_v243.py", "r1_15a2_trial_adapter_v240.py", "r1_15a2_overnight_controller_v240.py",
        "r1_15a2_overnight_controller_v242.py", "r1_15a2_finecdf_bridge_v242.py",
        "reference_v18/R1_BC_AUTO_DIST_ONLY_FINECDF_ADAPTIVE_v1_8.py",
        "r1_15a2_inplace_transaction_v239.py", "r1_15a2_assignment_authority_v239.py",
        "r1_15a2_two_mode_v238.py", "r1_15a2_com_compat.py", "r1_15a2_live_api_audit.py",
        "r1_15a2_controller_v22.py", "r1_15a2_sequence_v23.py", "r1_15a2_supply.py",
        "r1_15a2_supply_visum.py", "r1_15a2_runtime_v1.py", "r1_15a2_core.py",
        "r1_15a2_multiblock.py", "r1_15a2_visum_parameters.py", "r1_15a2_safety_v246.py", "r1_15a2_safety_v247.py", "r1_15a2_safety_v248.py", "r1_15a2_persistent_path_cache_v248.py", "r1_15a2_perf_v246.py",
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
    validate_v248_config(cfg, HERE)
    return cfg


def _main_impl():
    visum, _ = com.bind_injected(globals())
    source_ver = Path(str(visum.IO.CurrentVersionFile))
    if not source_ver.is_file():
        raise RuntimeError("CURRENT_VERSION_FILE_NOT_FOUND")
    source_sha_before = rt.sha256_file(source_ver)
    # Resolve output location before SaveVersion changes CurrentVersionFile.
    root, _ = api_audit.project_output_root(visum)
    runs = root.parent / "R1_15A2_V248_RUNS"
    runs.mkdir(parents=True, exist_ok=True)
    folder = runs / ("RUN_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir()
    (runs / "LATEST_RUN.txt").write_text(str(folder), encoding="utf-8")
    (folder / "00_RELEASE.txt").write_text(RELEASE + "\n", encoding="utf-8")
    lock = source_ver.parent / ".R1_15A2_FULL_CALIBRATION.lock"
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
                              root.parent / "R1_15A2_PATH_CACHE_V248")
                legacy_roots = [
                    root.parent / "R1_15A2_V247_RUNS",
                    root.parent / "R1_15A2_V246_RUNS",
                    root.parent / "R1_15A2_V245_RUNS",
                    root.parent / "R1_15A2_V2_4_5_FULL_CALIBRATION_REPAIR_RUNS",
                    source_ver.parent / "R1_15A2_V2_4_5_FULL_CALIBRATION_REPAIR_RUNS",
                ]
                cfg["runtime_persistent_path_cache_root"] = str(cache_root)
                cfg["runtime_legacy_path_cache_roots"] = [str(x) for x in legacy_roots]
                cfg["runtime_source_version_sha256"] = source_sha_before
                cfg["runtime_source_version_path"] = str(source_ver)
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
