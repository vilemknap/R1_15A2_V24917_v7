"""Exact recovery of PROFILE488 run RUN_20261022_030700_218899 after A0004.

Open ACCEPTED_B_0004_d26d01d6f9a5.ver before launching. The launcher verifies
the exact semantic authority, preserves the original fixed-reference Generation
objective, skips cycles 1-2 and the already accepted Generation substep of cycle
3, and resumes directly at cycle-3 FineCDF TD. The global wall-clock limit stays
disabled and the exact 100 TG/TD outer-cycle target is preserved. Path cache is
re-enumerated into a new run-isolated namespace. Performance telemetry is
best-effort and can no longer terminate calibration on Windows file-lock errors.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import contextlib
import copy
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
from r1_15a2_supply import SupplyContractError, canonical_hash
from r1_15a2_safety_v248 import final_artifact_name
from r1_15a2_safety_v24915p2 import (
    preflight_v24915p2_deployment_files, validate_v24915p2_config,
    validate_v24915p2_runtime_bundle,
)
from r1_15a2_safety_v24915p2c import (
    PACKAGE_REVISION as PERF2C_PACKAGE_REVISION,
    RELEASE as PERF2C_RELEASE,
    preflight_v24915p2c_overlay,
)
from r1_15a2_supply_temp_sqlite_hotfix_v24915p2c2 import activate_supply_temp_sqlite_hotfix
import r1_15a2_restart_v2494 as restart
import r1_15a2_demand_continuation_v24914 as demand_continuation
import r1_15a2_demand_continuation_v24915r4 as demand_continuation_r4
import r1_15a2_demand_continuation_v24915r5 as demand_continuation_r5
import r1_15a2_demand_continuation_profile488_a0004 as recovery_a0004
import r1_15a2_perf_telemetry_failopen_hotfix_profile488 as telemetry_failopen
from r1_15a2_trial_adapter_v24915p2c import VisumAdapter
from r1_15a2_overnight_controller_v24915p2 import OvernightControl as _BoundedOvernightControl, atomic_json
import r1_15a2_overnight_controller_coupled_v24915p2_force100 as coupled_runtime
from r1_15a2_overnight_controller_coupled_v24915p2_force100 import run_overnight_calibration_coupled
from r1_15a2_supply_handoff_v24915p2 import run_verified_supply_only



class UnlimitedOvernightControl(_BoundedOvernightControl):
    """Fresh100 control with no global wall-clock stop.

    The inherited 18 h numeric config value is retained only so the reviewed
    parent PERF2/R5 config can still be validated byte-for-byte/semantically.
    Runtime stopping is governed by the 100 outer-cycle cap, stationarity,
    explicit STOP_REQUESTED, and existing inner-block budgets.
    """
    def __init__(self, run_root, cfg, clock=None):
        if clock is None:
            super().__init__(run_root, cfg)
        else:
            super().__init__(run_root, cfg, clock=clock)
        self.max_seconds = float("inf")
        self.progress["wall_clock_limit_disabled"] = True
        self.progress["global_max_runtime_seconds"] = None
        self.checkpoint("STARTING", force=True)

    def _write(self, now):
        self.progress.update(
            elapsed_seconds=round(now - self.started, 3),
            remaining_seconds=None,
            wall_clock_limit_disabled=True,
            global_max_runtime_seconds=None,
            updated=datetime.now().astimezone().isoformat(),
        )
        atomic_json(self.root / "00_PROGRESS.json", self.progress)
        self.last_write = now


RELEASE = "R1_15A2_V24915_PERF2C_PROFILE488_A0004_CYCLE3_TD_RECOVERY_TELEMETRYFIX1_NO_WALLCLOCK_20261022"
FRESH100_MODE = "FRESH_CYCLE1_FORCE_EXACT_100_TGTD_OUTER_CYCLES"
FRESH100_MAX_OUTER_CYCLES = 100
PARENT_COMPAT_RUNTIME_SECONDS = 64800.0
SEALED_IDP_AUTHORITY_DIR = HERE / "helpers" / "R1_IDP_DISTRIBUTION_AUTHORITY_V1"
SEALED_IDP_DIST_CURVES_SHA256 = "f68087c249d6f1da2582e2ea1d723a8b3d1a8d99af82ffe5283f63d0de6a0737"
SEALED_IDP_REQUIRED_COMPONENTS = (
    "WORK_E_C", "WORK_E_noC", "WORK_noE_C", "WORK_noE_noC", "WORK_stud",
    "SERV_E_C", "SERV_E_noC", "SERV_noE_C", "SERV_noE_noC", "SERV_stud", "SCHOOL",
)

CURRENT_12D_HELPER = "R1_12D_CURRENT_COUNTLOCATION_488_ALL_CALIBRATION_20261022.py"
CURRENT_CSD_AUTH_REL = "authorities/R1_CSD2022_COUNTLOCATION_AUTHORITY_CURRENT_362_20261022.csv"
CURRENT_CITY_AUTH_REL = "authorities/R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_CURRENT_126_20261022.csv"
CURRENT_COUNTLOCATION_SOURCE_REL = "authorities/COUNTLOCATION-2026-10-22-02-23-34.xlsx"
CURRENT_CSD_AUTH_SHA256 = "86319e09010e2c4c261437a805541f9ff45b6bd0a3fe48d0757123f595c112ba"
CURRENT_CITY_AUTH_SHA256 = "2154cfd4fb080f63ec3f6e233d27bb8d7787a0598febf38c14e7851f3f66a7e0"
CURRENT_COUNTLOCATION_SOURCE_SHA256 = "0244e311488e88f754a691e8c1d535608a13360e91086ee116d6d9e71bf7f860"
CURRENT_PROFILE_COUNT = 488


def _load_current_profile_authority():
    observations = []
    files = (
        (CURRENT_CSD_AUTH_REL, CURRENT_CSD_AUTH_SHA256),
        (CURRENT_CITY_AUTH_REL, CURRENT_CITY_AUTH_SHA256),
    )
    for rel, expected_sha in files:
        path = HERE / rel
        if not path.is_file() or rt.sha256_file(path) != expected_sha:
            raise RuntimeError("CURRENT_COUNTLOCATION_AUTHORITY_FILE_MISMATCH:" + rel)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for r in csv.DictReader(handle):
                role = str(r.get("role", "")).strip().upper()
                if role != "CALIBRATION":
                    raise RuntimeError("CURRENT_COUNTLOCATION_AUTHORITY_ROLE_NOT_CALIBRATION:" + str(r.get("countlocation_no")))
                scope = r.get("vehicle_scope_original") or r.get("vehicle_scope") or ""
                observations.append({
                    "no": int(r["countlocation_no"]),
                    "observed": float(r["observed_passenger_cars_O"]),
                    "role": "CALIBRATION",
                    "weight": float(r["live_weight"]),
                    "edge_key": [int(r[k]) for k in ("current_link_no", "current_from_node_no", "current_to_node_no")],
                    "direction": r.get("observation_direction") or "DIRECTIONAL",
                    "countlocation_code": r["countlocation_code"],
                    "profile_id": r["profile_id"],
                    "period_basis": r["period_basis"],
                    "observed_scope": scope,
                })
    if len(observations) != CURRENT_PROFILE_COUNT:
        raise RuntimeError("CURRENT_COUNTLOCATION_AUTHORITY_ROW_COUNT:%d" % len(observations))
    if len({x["no"] for x in observations}) != CURRENT_PROFILE_COUNT:
        raise RuntimeError("CURRENT_COUNTLOCATION_AUTHORITY_DUPLICATE_NO")
    if len({x["profile_id"] for x in observations}) != CURRENT_PROFILE_COUNT:
        raise RuntimeError("CURRENT_COUNTLOCATION_AUTHORITY_DUPLICATE_PROFILE_ID")
    source = HERE / CURRENT_COUNTLOCATION_SOURCE_REL
    if not source.is_file() or rt.sha256_file(source) != CURRENT_COUNTLOCATION_SOURCE_SHA256:
        raise RuntimeError("CURRENT_COUNTLOCATION_SOURCE_XLSX_MISMATCH")
    return observations


def _bind_current_profile_authority(cfg):
    observations = _load_current_profile_authority()
    cfg["api_approved_observations"] = observations
    cfg["12d_helper_name"] = CURRENT_12D_HELPER
    cfg["12d_authority_csv"] = CURRENT_CSD_AUTH_REL
    cfg["12d_authority_sha256"] = CURRENT_CSD_AUTH_SHA256
    cfg["12d_city_authority_csv"] = CURRENT_CITY_AUTH_REL
    cfg["12d_city_authority_sha256"] = CURRENT_CITY_AUTH_SHA256
    cfg["current_countlocation_authority"] = {
        "source_xlsx": CURRENT_COUNTLOCATION_SOURCE_REL,
        "source_xlsx_sha256": CURRENT_COUNTLOCATION_SOURCE_SHA256,
        "rows": CURRENT_PROFILE_COUNT,
        "calibration": CURRENT_PROFILE_COUNT,
        "validation": 0,
        "policy": "EVERY_ROW_IN_USER_TABLE_IS_CALIBRATION_AUTHORITY",
        "source_R1_ACTIVE_ignored": True,
        "source_R1_ROLE_ignored": True,
    }
    return observations


def _apply_current_profile_metadata_to_working_copy(visum, observations):
    coll = visum.Net.CountLocations
    applied = []
    for row in observations:
        no = int(row["no"])
        obj = coll.ItemByKey(no)
        if com.exact_int(obj.AttValue("NO"), "COUNTLOCATION.NO") != no:
            raise RuntimeError("CURRENT_COUNTLOCATION_IDENTITY_MISMATCH:%d" % no)
        obj.SetAttValue("R1_ACTIVE", 1)
        obj.SetAttValue("R1_ROLE", "CALIBRATION")
        if not com.active_bool(obj.AttValue("R1_ACTIVE")):
            raise RuntimeError("CURRENT_COUNTLOCATION_ACTIVE_WRITE_FAILED:%d" % no)
        if str(obj.AttValue("R1_ROLE")).strip().upper() != "CALIBRATION":
            raise RuntimeError("CURRENT_COUNTLOCATION_ROLE_WRITE_FAILED:%d" % no)
        observed = com.finite_float(obj.AttValue("R1_OBS_RPDI"), "R1_OBS_RPDI")
        if abs(observed - float(row["observed"])) > 1.0e-6:
            raise RuntimeError("CURRENT_COUNTLOCATION_OBS_MISMATCH:%d" % no)
        key = tuple(com.exact_int(obj.AttValue(a), a) for a in ("LINKNO", "FROMNODENO", "TONODENO"))
        if key != tuple(row["edge_key"]):
            raise RuntimeError("CURRENT_COUNTLOCATION_EDGE_MISMATCH:%d" % no)
        applied.append(no)
    if len(applied) != CURRENT_PROFILE_COUNT:
        raise RuntimeError("CURRENT_COUNTLOCATION_APPLY_COUNT:%d" % len(applied))
    return {
        "status": "PASS",
        "rows": len(applied),
        "calibration_rows": len(applied),
        "validation_rows": 0,
        "working_copy_R1_ACTIVE": 1,
        "working_copy_R1_ROLE": "CALIBRATION",
        "selection_policy": "ALL_ROWS_FROM_CURRENT_USER_TABLE",
    }


def _fresh_baseline_sidecar_diagnostic(source_ver, source_semantic):
    """Inspect an adjacent historical semantic sidecar without making it a fresh-start gate.

    In FRESH_CYCLE1 mode the live currently-opened .ver is explicitly the new
    baseline.  An adjacent sidecar may legitimately describe an older accepted
    checkpoint and therefore may differ after intentional model edits.  The
    sidecar is retained as diagnostic provenance only; the hard semantic gate is
    the live-source -> SaveVersion working-copy identity check performed next.
    """
    path = restart.sidecar_path(source_ver)
    try:
        adjacent = restart.load_optional_sidecar(source_ver)
    except SupplyContractError as exc:
        return {
            "status": "HISTORICAL_SIDECAR_INVALID_IGNORED_FOR_FRESH_BASELINE",
            "path": str(path),
            "restart_allowed": True,
            "fresh_start_sidecar_role": "HISTORICAL_DIAGNOSTIC_ONLY",
            "diagnostic_error": str(exc),
            "raw_ver_sha_compared": False,
        }
    if adjacent is None:
        return {
            "status": "OPTIONAL_SIDECAR_NOT_PRESENT",
            "path": str(path),
            "restart_allowed": True,
            "fresh_start_sidecar_role": "HISTORICAL_DIAGNOSTIC_ONLY",
            "raw_ver_sha_compared": False,
        }
    result = restart.compare_authorities(
        adjacent, source_semantic, label="SOURCE_ADJACENT_SEMANTIC_SIDECAR")
    result.update({
        "status": (
            "HISTORICAL_SIDECAR_SEMANTICS_MATCH_DIAGNOSTIC"
            if result.get("passes") else
            "HISTORICAL_SIDECAR_MISMATCH_IGNORED_FOR_FRESH_BASELINE"
        ),
        "path": str(path),
        "restart_allowed": True,
        "fresh_start_sidecar_role": "HISTORICAL_DIAGNOSTIC_ONLY",
    })
    return result


def _fresh_run_cache_root(run_folder, project_base):
    """Return an empty run-isolated cache namespace.

    The namespace is unique per newly created RUN_* folder.  Existing global
    V248 cache roots and all legacy run trees are intentionally excluded, so a
    fresh path export is mandatory for the current network.  Cache data created
    later inside this same run may still be reused normally.
    """
    run_folder = Path(run_folder)
    project_base = Path(project_base)
    local_appdata = os.environ.get("LOCALAPPDATA")
    cache_parent = (Path(local_appdata) / "R1_15A2_PATH_CACHE_V248_FRESH_RUNS"
                    if local_appdata else
                    project_base / "R1_15A2_PATH_CACHE_V248_FRESH_RUNS")
    root = cache_parent / run_folder.name
    if root.exists():
        raise RuntimeError("FRESH_RUN_PATH_CACHE_ROOT_ALREADY_EXISTS:" + str(root))
    return root


def _activate_sealed_idp_authority():
    """Pin 11D to the authority embedded with this package.

    Older environments may carry R1_IDP_AUTHORITY_DIR or a stale extracted
    authority. R4 intentionally overrides that process-local environment value
    only after exact file/hash/component validation. This does not touch Visum.
    """
    target = SEALED_IDP_AUTHORITY_DIR / "R1_IDP_DIST_KM_TARGET_CURVES_V1.csv"
    if not target.is_file():
        raise RuntimeError("V24915R4_SEALED_IDP_TARGET_CURVES_MISSING")
    got = rt.sha256_file(target)
    if got != SEALED_IDP_DIST_CURVES_SHA256:
        raise RuntimeError("V24915R4_SEALED_IDP_TARGET_CURVES_HASH_MISMATCH:%s" % got)
    with target.open(encoding="utf-8-sig", newline="") as h:
        rows = list(csv.DictReader(h))
    counts = {}
    for row in rows:
        comp = str(row.get("component", "")).strip()
        if comp:
            counts[comp] = counts.get(comp, 0) + 1
    missing = [name for name in SEALED_IDP_REQUIRED_COMPONENTS if counts.get(name) != 512]
    if missing:
        raise RuntimeError("V24915R4_SEALED_IDP_COMPONENT_CONTRACT_MISMATCH:" + ",".join(missing))
    previous = os.environ.get("R1_IDP_AUTHORITY_DIR")
    os.environ["R1_IDP_AUTHORITY_DIR"] = str(SEALED_IDP_AUTHORITY_DIR)
    return {
        "status": "SEALED_IDP_AUTHORITY_ACTIVE",
        "authority_dir": str(SEALED_IDP_AUTHORITY_DIR),
        "target_curve_sha256": got,
        "target_components": list(SEALED_IDP_REQUIRED_COMPONENTS),
        "rows_per_component": {name: counts[name] for name in SEALED_IDP_REQUIRED_COMPONENTS},
        "previous_env_authority_dir": previous,
        "env_override_policy": "PACKAGE_SEALED_AUTHORITY_WINS_AFTER_EXACT_HASH_AND_COMPONENT_VALIDATION",
    }


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
            raise RuntimeError("V24915P2_NEW_RUN_STILL_NESTED_UNDER_PRIOR_RUN_TREE:%s" % prior)





def _fresh100_runtime_continuation(cfg):
    """Accept the one explicit fresh-cycle-1 descriptor; otherwise use parent rules."""
    raw = cfg.get("runtime_demand_continuation", {}) or {}
    if raw.get("mode") != FRESH100_MODE:
        return _PARENT_RUNTIME_CONTINUATION(cfg)
    required = {
        "enabled": True,
        "accepted_count": 0,
        "next_outer_cycle": 1,
        "inherited_outer_cycles": 0,
        "inherited_stationary_cycle_streak": 0,
        "inherited_completed_demand_cycles": 0,
        "max_lineage_outer_cycle": FRESH100_MAX_OUTER_CYCLES,
        "resume_substep": "GENERATION",
    }
    for key, expected in required.items():
        if raw.get(key) != expected:
            raise RuntimeError("FRESH100_CONTINUATION_FIELD_MISMATCH:%s" % key)
    reasons = tuple(raw.get("bounded_inner_budget_stop_reasons", ()))
    if set(reasons) != set(coupled_runtime.V24914_BOUNDED_INNER_BUDGET_STOP_REASONS):
        raise RuntimeError("FRESH100_BOUNDED_BUDGET_REASON_SET_MISMATCH")
    if not isinstance(raw.get("semantic_state_hash"), str) or not raw.get("semantic_state_hash"):
        raise RuntimeError("FRESH100_SOURCE_SEMANTIC_HASH_MISSING")
    return copy.deepcopy(dict(raw))


def _normalize_fresh100_to_parent50(cfg):
    """Return an audit-only copy matching the already-reviewed PERF2 R5 config."""
    base = copy.deepcopy(dict(cfg))
    phases = base.get("calibration_phases", [])
    if phases:
        phases[0]["max_cycles"] = 50
    dc = base.get("coupled_demand", {})
    dc["max_outer_cycles"] = 50
    stages = dc.get("finecdf_td", {}).get("progressive_schedule", [])
    if stages:
        stages[-1]["through_outer_cycle"] = 50
    gen = base.get("performance", {}).get("generation_step_schedule", [])
    if gen:
        gen[-1]["through_outer_cycle"] = 50
    for key in ("fresh100_overlay", "v24915_perf2c_runtime_options",
                "v24915_perf2c_overlay_revision"):
        base.pop(key, None)
    base.pop("runtime_demand_continuation", None)
    return base


def _validate_fresh100_effective_config(cfg):
    phases = cfg.get("calibration_phases", [])
    if not phases or int(phases[0].get("max_cycles", -1)) != FRESH100_MAX_OUTER_CYCLES:
        raise RuntimeError("FRESH100_DEMAND_PHASE_CAP_NOT_100")
    dc = cfg.get("coupled_demand", {})
    if int(dc.get("max_outer_cycles", -1)) != FRESH100_MAX_OUTER_CYCLES:
        raise RuntimeError("FRESH100_OUTER_CAP_NOT_100")
    if int(dc.get("min_stationary_cycles", -1)) != 2:
        raise RuntimeError("FRESH100_STATIONARITY_RULE_DRIFT")
    if int(dc.get("supply_max_cycles", -1)) != 100:
        raise RuntimeError("FRESH100_SUPPLY_CAP_DRIFT")
    td_sched = dc.get("finecdf_td", {}).get("progressive_schedule", [])
    if not td_sched or int(td_sched[-1].get("through_outer_cycle", -1)) != FRESH100_MAX_OUTER_CYCLES:
        raise RuntimeError("FRESH100_TD_SCHEDULE_NOT_100")
    gen_sched = cfg.get("performance", {}).get("generation_step_schedule", [])
    if not gen_sched or int(gen_sched[-1].get("through_outer_cycle", -1)) != FRESH100_MAX_OUTER_CYCLES:
        raise RuntimeError("FRESH100_GENERATION_SCHEDULE_NOT_100")
    if float(cfg.get("trial_calibration", {}).get("max_runtime_seconds", -1)) != PARENT_COMPAT_RUNTIME_SECONDS:
        raise RuntimeError("FRESH100_PARENT_COMPAT_RUNTIME_DRIFT")
    return True


def _fresh100_runtime_preflight(cfg, package_root=None):
    root = Path(package_root).resolve() if package_root is not None else HERE
    # Prove the inherited reviewed runtime still validates after reversing only
    # the child budget/restart overlay.
    parent_cfg = _normalize_fresh100_to_parent50(cfg)
    base = dict(validate_v24915p2_runtime_bundle(parent_cfg, root))
    overlay = dict(preflight_v24915p2c_overlay(root))
    _validate_fresh100_effective_config(cfg)
    base["perf2c_overlay"] = overlay
    base["fresh100"] = {
        "passes": True,
        "mode": "EXACT_SEMANTIC_PROFILE488_A0004_PARTIAL_CYCLE3_TD_RESUME",
        "start_outer_cycle": 3,
        "accepted_count_start": 4,
        "max_outer_cycles": FRESH100_MAX_OUTER_CYCLES,
        "max_runtime_seconds": None,
        "parent_compat_max_runtime_seconds": PARENT_COMPAT_RUNTIME_SECONDS,
        "wall_clock_limit_disabled": True,
        "parent_calibration_math_changed": False,
        "parent_acceptance_changed": False,
        "assignment_method_changed": False,
        "source_ver_role": "EXACT_ACCEPTED_A0004_RECOVERY_CHECKPOINT",
        "continuation_from_prior_run": True,
        "resume_substep": "TD_FINECDF_V17",
        "resume_outer_cycle": 3,
        "performance_telemetry_policy": "BEST_EFFORT_NEVER_ABORT_CALIBRATION",
    }
    return base


_PARENT_RUNTIME_CONTINUATION = coupled_runtime._runtime_demand_continuation
coupled_runtime._runtime_demand_continuation = _fresh100_runtime_continuation
activate_supply_temp_sqlite_hotfix()
TELEMETRY_FAILOPEN_STATUS = telemetry_failopen.activate()

def load_config(execution_mode="FULL"):
    path = HERE / "R1_15A2_CONFIG_V2_4_9_15_PERF2.json"
    cfg = rt.read_json(path)
    # Hard locks: working-copy calibration is not production release/apply.
    cfg["apply"] = False
    cfg["production_apply"] = False
    cfg["trial_calibration"]["enabled"] = True
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = rt.sha256_file(path)
    implementation = [
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15_PERF2.py",
        "r1_15a2_safety_v24915p2.py",
        "r1_15a2_candidate_readback_bundle_v24915p2.py",
        "r1_15a2_trial_adapter_v24915p2.py",
        "r1_15a2_inplace_transaction_v24915p2.py",
        "r1_15a2_overnight_controller_v24915p2.py",
        "r1_15a2_overnight_controller_coupled_v24915p2.py",
        "r1_15a2_overnight_controller_coupled_v24915p2_force100.py",
        "r1_15a2_demand_continuation_profile488_a0004.py",
        "r1_15a2_perf_telemetry_failopen_hotfix_profile488.py",
        "r1_15a2_perf_v246.py",
        "r1_15a2_supply_handoff_v24915p2.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_15.py",
        "R1_15A2_SUPPLY_FROM_CONVERGED_DEMAND_V2_4_9_15.py",
        "r1_15a2_safety_v24915p1.py",
        "r1_15a2_acceleration_v24915p1.py",
        "r1_15a2_trial_adapter_v24915p1.py",
        "r1_15a2_inplace_transaction_v24915p1.py",
        "r1_15a2_overnight_controller_v24915p1.py",
        "r1_15a2_overnight_controller_coupled_v24915p1.py",
        "r1_15a2_supply_handoff_v24915p1.py",
        "r1_15a2_supply_handoff_v24913.py",
        "r1_15a2_safety_v24915.py", "r1_15a2_demand_continuation_v24914.py", "r1_15a2_demand_continuation_v24915r4.py", "r1_15a2_demand_continuation_v24915r5.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_5.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_4.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_3.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_2.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_0.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_9.py",
        "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_8_8.py",
        "r1_15a2_trial_adapter_v243.py", "r1_15a2_trial_adapter_v240.py", "r1_15a2_overnight_controller_v240.py",
        "r1_15a2_overnight_controller_v242.py", "r1_15a2_finecdf_bridge_v242.py",
        "reference_v19/R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_v1_9.py",
        "reference_v18/R1_BC_AUTO_DIST_ONLY_FINECDF_ADAPTIVE_v1_8.py",
        "r1_15a2_inplace_transaction_v239.py", "r1_15a2_assignment_authority_v239.py",
        "r1_15a2_two_mode_v238.py", "r1_15a2_com_compat.py", "r1_15a2_live_api_audit.py",
        "r1_15a2_controller_v22.py", "r1_15a2_sequence_v23.py", "r1_15a2_supply.py",
        "r1_15a2_supply_visum.py", "r1_15a2_runtime_v1.py", "r1_15a2_core.py",
        "r1_15a2_multiblock.py", "r1_15a2_visum_parameters.py", "r1_15a2_safety_v246.py", "r1_15a2_safety_v247.py", "r1_15a2_safety_v248.py", "r1_15a2_safety_v2482.py", "r1_15a2_safety_v2483.py", "r1_15a2_safety_v2485.py", "r1_15a2_safety_v2486.py", "r1_15a2_safety_v2487.py", "r1_15a2_safety_v2488.py", "r1_15a2_safety_v2489.py", "r1_15a2_safety_v2490.py", "r1_15a2_safety_v2492.py", "r1_15a2_safety_v2493.py", "r1_15a2_safety_v2494.py", "r1_15a2_safety_v2495.py", "r1_15a2_safety_v2496.py", "r1_15a2_safety_v24912.py", "r1_15a2_guard_policy_v24912.py", "r1_15a2_restart_v2494.py", "r1_15a2_persistent_path_cache_v248.py", "r1_15a2_perf_v246.py",
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
    cfg["v24915_perf2_features"] = [
        "EXACT_STATE_CANDIDATE_READBACK_BUNDLE",
        "SESSION_RUN_PARENT_BLOCK_CANDIDATE_AND_EPOCH_BINDING",
        "INVALIDATE_BEFORE_EVERY_MODEL_SIDE_EFFECT",
        "LEGACY_SNAPSHOT_PAYLOAD_AND_MATRIX_HASH_SEMANTICS_UNCHANGED",
        "ROLLBACK_PROFILE_SIGNATURE_CAN_BE_CAPTURED_IN_BUNDLE",
        "LIVE_12D_11D_ACCEPTANCE_UNCHANGED",
    ]
    cfg["cp02_performance_features"] = [
        "PER_OPERATION_TELEMETRY", "BULK_LINK_COM_READ_WITH_VERIFIED_FALLBACK",
        "ADAPTIVE_BOUNDED_PATH_PAGING", "LAZY_SUPPLY_SEQUENCE_EVIDENCE",
        "FIRST_SUFFICIENT_LIVE_CANDIDATE", "ADAPTIVE_GENERATION_STEP_SCHEDULE",
        "PROGRESSIVE_FINECDF_V19_SOFT_REFERENCE", "ADAPTIVE_FINECDF_TRUST_REGION",
        "ADDVAL1_BRANCH_LOCAL_STEP_SECONDS_80_40_20_10_5",
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
    cfg["v2490_td_soft_reference_features"] = [
        "MOBILITY_SURVEY_CDF_IS_SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT",
        "INNER_FINECDF_MIN_RELATIVE_IMPROVEMENT_0P001",
        "FULL_REALIZATION_SELECTED_AGGREGATE_MIN_IMPROVEMENT_0P005",
        "BOUNDED_SELECTED_AND_NONSELECTED_COMPONENT_TRADEOFF_0P05",
        "SOFT_REJECTION_BACKTRACKS_B_LINEAR_AND_C_LOG_NEG",
        "ALL_SOFT_REJECTED_REALIZED_SCALES_RESTORE_PARENT_PLATEAU",
        "NATIVE_IPF_TOLERANCE_UNCHANGED",
        "TD_BC_READBACK_NUMERIC_TOLERANCE_WITH_EXACT_FROZEN_CONTEXT",
    ]
    cfg["v2492_signed_generation_features"] = [
        "SIGNED_OD_GUIDANCE_CAN_INCREASE_AND_DECREASE_RELATIONS",
        "FAMILY_GLOBAL_SCALE_PLUS_NONLINEAR_ZERO_TOTAL_ZONE_REDISTRIBUTION",
        "COMMON_PRODUCTION_ATTRACTION_FAMILY_TOTAL",
        "OPPOSITE_SIGN_ROLE_TOTALS_REMOVE_GLOBAL_DRIFT_KEEP_LOCAL_PATTERN",
        "DOMESTIC_AND_SALARY_HARD_ENVELOPE_0P5_TO_2P0",
        "DOMESTIC_AND_SALARY_SOFT_REFERENCE_0P8_TO_1P25",
        "ZAHR_RUN_START_REFERENCE_MULTIPLIER_HARD_0P5_TO_2P0",
        "LATE_CYCLE_GLOBAL_GENERATION_DRIFT_LIMIT_0P005_LOG",
        "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D_ACCEPTANCE_UNCHANGED",
    ]
    cfg["v2493_method_and_com_correction_features"] = [
        "CSD_CAL_USES_OBSERVATION_WEIGHTED_MEAN_GEH_NOT_GEH_SQUARED",
        "PROFILE_SUMS_ARE_DIAGNOSTIC_PASSAGE_CHECKSUMS_NOT_UNIQUE_TRIPS",
        "LONG_ACCEPTANCE_USES_ONE_GLOBAL_LONG_COMPOSITE",
        "FIVE_NATIVE_LONG_MATRICES_RETAIN_COMMON_B_OFFSET_AND_C_MULTIPLIER",
        "ZONE_NO_TO_COM_ROW_KEY_IDENTITY_CACHED_ON_ADAPTER_START",
        "GENERATION_APPLY_AND_ROLLBACK_USE_SETMULTIATTVALUES_WITH_READBACK",
        "COM_RETRY_ONLY_FOR_TRANSIENT_RPC_CALL_REJECTED_OR_RETRY_LATER",
        "COM_SIGNATURE_FALLBACK_SEPARATE_FROM_TRANSIENT_RETRY",
        "FULL_12D_11D_HELPER_RETRY_IS_BOUNDED_AND_TRANSIENT_ONLY",
    ]
    cfg["v2494_path_export_and_restart_features"] = [
        "RAW_BOUNDED_OLE_INVOKE_USES_SAME_RANGE_TRANSIENT_RETRY",
        "TRANSIENT_RPC_REJECTION_NEVER_TRIGGERS_PAGE_SIZE_FALLBACK",
        "PAGE_SIZE_FALLBACK_ONLY_FOR_MEMORY_RANGE_OR_OVERFLOW_FAILURE",
        "RAW_VER_SHA_IS_PROVENANCE_AND_WITHIN_RUN_MUTATION_SENTINEL_ONLY",
        "RESTART_ACCEPTANCE_USES_EXPLICIT_SEMANTIC_MODEL_HASHES",
        "MANUAL_VISUM_SAVE_RESERIALIZATION_IS_ALLOWED_WHEN_SEMANTICS_MATCH",
        "CHECKPOINTS_PUBLISH_ADJACENT_SEMANTIC_RESTART_SIDECARS",
    ]
    cfg["v2495_geh20_hysteresis_severity_budget_features"] = [
        "GEH20_CROSSINGS_INSIDE_19P5_TO_20P5_ARE_HYSTERESIS_DIAGNOSTIC_ONLY",
        "GENERATION_MAX_3_MATERIAL_NEW_GEH20",
        "GENERATION_MAX_SINGLE_GEH_INCREASE_2P0",
        "GENERATION_MAX_TOTAL_NEW_GEH20_EXCESS_2P0",
        "TD_MAX_1_MATERIAL_NEW_GEH20",
        "TD_MAX_SINGLE_GEH_INCREASE_1P0",
        "TD_MAX_TOTAL_NEW_GEH20_EXCESS_0P75",
        "NEW_GEH30_REMAINS_ZERO_TOLERANCE",
        "CONTINUOUS_SEVERITY_PENALTY_DEFERRED_NOT_IMPLEMENTED",
    ]
    cfg["v2496_early_exploration_pareto_features"] = [
        "ALL_12_COUPLED_DEMAND_CYCLES_USE_BASELINE_RELATIVE_PARETO_EXPLORATION",
        "GENERATION_ACCEPTS_ANY_REAL_POSITIVE_WEIGHTED_GEH_IMPROVEMENT",
        "GENERATION_MAY_TRADE_UP_TO_2_PERCENT_CAL_GEH_FOR_MATERIAL_SEVERITY_GAIN",
        "TD_ACCEPTS_0P25_PERCENT_DISTRIBUTION_IMPROVEMENT_WITH_UP_TO_5_PERCENT_CAL_GEH_COST",
        "TD_BENEFIT_COST_RATIO_MINIMUM_1P5",
        "GEH20_AND_GEH30_ARE_CONTINUOUS_DIAGNOSTICS_DURING_EARLY_EXPLORATION",
        "GEH35_IS_WARNING_AND_GEH40_USES_SCOPE_SPECIFIC_NET_COUNT_BUDGET",
        "GEH60_IS_DIAGNOSTIC_THRESHOLD_WITH_GT10_PROFILE_DELTA_HARD",
        "SINGLE_PROFILE_GEH_INCREASE_GT15_REMAINS_HARD",
        "PROTECTED_BELOW_GEH5_CANNOT_CROSS_GEH20",
        "CURRENT_EXPLORATORY_AND_BEST_SO_FAR_CHECKPOINTS_ARE_SEPARATE",
        "NO_ACCEPTANCE_RELAXATION; CYCLES_13_TO_50_USE_EXISTING_POST_12_FALLBACK",
    ]
    cfg["runtime_execution_mode"] = str(execution_mode).upper()
    cfg["v24913_supply_route_choice_features"] = [
        "SUPPLY_HAS_INDEPENDENT_ACCEPTANCE_CYCLE_CLOCK",
        "SUPPLY_BASELINE_RELATIVE_SEVERITY_POLICY",
        "HALF_ADDVAL_LATTICE_EQUALS_FIVE_GENERALIZED_SECONDS",
        "BRANCH_LOCAL_80_40_20_10_5_SECOND_BACKTRACKING",
        "COMPLETE_BACKTRACKING_LADDERS_NOT_GLOBAL_STEP_FIRST_TRUNCATION",
        "RELAXED_ROUTE_PATH_AND_DRIVER_DISCOVERY_WITH_FRESH_ASSIGNMENT_AUTHORITY",
        "DEMAND_HASHES_FROZEN_DURING_SUPPLY",
        "SUPPLY_ONLY_LAUNCH_REQUIRES_MATCHING_DEMAND_CONVERGED_AUTHORITY",
    ]
    cfg["v24915_r4_b0016_continuation_features"] = [
        "EXACT_B0016_SEMANTIC_RESTART_AUTHORITY",
        "ACCEPTED_COUNT_16",
        "RESUME_LINEAGE_CYCLE11_AT_TD_ONLY",
        "DO_NOT_REPLAY_ALREADY_ACCEPTED_CYCLE11_GENERATION",
        "PRESERVE_ORIGINAL_GENERATION_COUNTS_REFERENCE",
        "PACKAGE_SEALED_IDP_AUTHORITY_OVERRIDES_STALE_EXTERNAL_AUTHORITY",
        "SUPPLY_REMAINS_LOCKED_UNTIL_EXISTING_CONVERGENCE_RULE_PASSES",
    ]
    cfg["v24915_r5_overnight50_features"] = [
        "OUTER_DEMAND_CYCLE_CAP_50",
        "GLOBAL_WALLCLOCK_BUDGET_18_HOURS",
        "CYCLE11_TD_RESUME_FROM_B0016_PRESERVED",
        "FINAL_GENERATION_STEP_STAGE_EXTENDED_TO_50_WITH_SAME_BOUNDS",
        "FINECDF_FULL_VERIFY_STAGE_EXTENDED_TO_50_WITH_SAME_INNER_BUDGET",
        "EARLY_EXPLORATION_ACCEPTANCE_ENDS_AT_12_UNCHANGED",
        "CYCLES_13_TO_50_USE_EXISTING_POST_12_ACCEPTANCE_FALLBACK",
        "TWO_COMPLETE_UNCHANGED_CYCLES_STILL_UNLOCK_SUPPLY",
        "SUPPLY_MAX_CYCLES_REMAINS_100",
    ]
    cfg["fresh100_features"] = [
        "EXACT_PROFILE488_A0004_SEMANTIC_RECOVERY",
        "START_OUTER_CYCLE_3_ACCEPTED_COUNT_4",
        "RESUME_CYCLE3_AT_TD_ONLY_WITHOUT_REPLAYING_ACCEPTED_GENERATION",
        "PRESERVE_ORIGINAL_GENERATION_COUNTS_REFERENCE",
        "OUTER_DEMAND_CYCLE_CAP_100",
        "GLOBAL_WALLCLOCK_LIMIT_DISABLED",
        "BOUNDED_FINECDF_INNER_BUDGET_MAY_CONTINUE_NEXT_OUTER_CYCLE",
        "CALIBRATION_MATH_AND_ACCEPTANCE_THRESHOLDS_UNCHANGED",
        "PERF2C_SINGLE_PASS_ADAPTER_AND_SUPPLY_TEMP_SQLITE_HOTFIX_RETAINED",
    ]
    cfg["v24914_demand_continuation_features"] = [
        "EXACT_A0009_SEMANTIC_RESTART_AUTHORITY",
        "INHERITED_ACCEPTED_COUNT_9",
        "LINEAGE_OUTER_CYCLE_START_6",
        "BOUNDED_INNER_MAX_ITERATIONS_CONTINUES_OUTER_LOOP",
        "BOUNDED_INNER_EVALUATION_BUDGET_CONTINUES_OUTER_LOOP",
        "BOUNDED_INNER_TIME_BUDGET_CONTINUES_OUTER_LOOP",
        "BOUNDED_BUDGET_NEVER_COUNTS_AS_STATIONARITY",
        "GLOBAL_STOP_AND_TECHNICAL_ERRORS_REMAIN_FAIL_CLOSED",
        "SUPPLY_REMAINS_LOCKED_UNTIL_TWO_COMPLETE_UNCHANGED_CYCLES",
        "V24913_ROUTE_CHOICE_POLICY_PRESERVED",
    ]
    cfg["v24915_com_busy_retry_safe_finalizer_features"] = [
        "BOUNDED_PATH_EXPORT_TRANSIENT_RETRY_LEASE_120_SECONDS",
        "BOUNDED_PATH_EXPORT_EXACT_SAME_RANGE_ACROSS_RETRIES",
        "GENERIC_COM_RETRY_POLICY_UNCHANGED",
        "TRANSIENT_RPC_REJECTION_NEVER_TRIGGERS_PAGE_SIZE_FALLBACK",
        "FINAL_VERIFICATION_TRANSIENT_RETRY_LEASE_30_SECONDS",
        "TRANSIENT_FINAL_READBACK_EXHAUSTION_RESTARTS_FROM_LATEST_ACCEPTED_CHECKPOINT",
        "NONTRANSIENT_OR_STATE_MISMATCH_REMAINS_FAIL_CLOSED_MANUAL_REOPEN",
        "A0009_LINEAGE_AND_V24913_SUPPLY_POLICY_UNCHANGED",
    ]
    validate_v24915p2_config(cfg, HERE)
    # Child overlay: same reviewed mathematics and exact 100-cycle horizon,
    # resumed from the verified A0004 partial-cycle checkpoint after the accepted
    # Generation substep of outer cycle 3. No global wall-clock stop.
    cfg["calibration_phases"][0]["max_cycles"] = FRESH100_MAX_OUTER_CYCLES
    cfg["coupled_demand"]["max_outer_cycles"] = FRESH100_MAX_OUTER_CYCLES
    cfg["coupled_demand"]["finecdf_td"]["progressive_schedule"][-1]["through_outer_cycle"] = FRESH100_MAX_OUTER_CYCLES
    cfg["performance"]["generation_step_schedule"][-1]["through_outer_cycle"] = FRESH100_MAX_OUTER_CYCLES
    cfg["v24915_perf2c_runtime_options"] = {
        "schema": "R1_15A2_V24915_PERF2C_CONFIG_V1",
        "enabled": True,
        "shadow_parity_once": True,
        "fallback_to_legacy": True,
        "public_snapshot_schema_changed": False,
        "semantic_hashes_changed": False,
        "matrix_fingerprint_semantics_changed": False,
        "cross_call_cache": False,
        "new_mutation_epoch": False,
        "new_authority_token": False,
        "persistent_cache_main_database_writable": False,
        "connection_local_temp_schema_for_supply": True,
    }
    cfg["v24915_perf2c_overlay_revision"] = PERF2C_PACKAGE_REVISION
    cfg["fresh100_overlay"] = {
        "mode": "EXACT_SEMANTIC_PROFILE488_A0004_PARTIAL_CYCLE3_TD_RESUME",
        "start_outer_cycle": 3,
        "accepted_count_start": 4,
        "max_outer_cycles": FRESH100_MAX_OUTER_CYCLES,
        "max_runtime_seconds": None,
        "parent_compat_max_runtime_seconds": PARENT_COMPAT_RUNTIME_SECONDS,
        "wall_clock_limit_disabled": True,
        "force_exact_tgtd_outer_cycles": FRESH100_MAX_OUTER_CYCLES,
        "supply_locked_before_final_tgtd_cycle": True,
        "supply_disabled_after_final_tgtd_cycle": True,
        "continuation_from_prior_run": True,
        "source_ver_is_new_baseline": False,
        "resume_substep": "TD_FINECDF_V17",
        "resume_outer_cycle": 3,
        "skip_already_accepted_cycle3_generation": True,
        "cross_run_path_cache_restore": False,
        "legacy_path_cache_import": False,
        "fresh_path_enumeration_required": True,
    }
    return cfg


def _main_impl(execution_mode="FULL"):
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
    execution_mode = str(execution_mode or "FULL").upper()
    runs_name = ("R1_15A2_V24915_PERF2C_FRESH100_SUPPLY_RUNS" if execution_mode == "SUPPLY_ONLY"
                 else "R1_15A2_V24915_PERF2C_PROFILE488_A0004_RECOVERY_RUNS")
    runs = project_base / runs_name
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
                deployment_preflight = dict(preflight_v24915p2_deployment_files(HERE))
                deployment_preflight["perf2c_overlay"] = dict(preflight_v24915p2c_overlay(HERE))
                deployment_preflight["fresh100_entrypoint"] = True
                deployment_preflight["profile488_a0004_recovery_entrypoint"] = True
                deployment_preflight["telemetry_failopen_hotfix"] = copy.deepcopy(TELEMETRY_FAILOPEN_STATUS)
                atomic_json(folder / "V24915_PERF1_DEPLOYMENT_PREFLIGHT.json", deployment_preflight)
                cfg = load_config(execution_mode)
                sealed_idp_authority = _activate_sealed_idp_authority()
                atomic_json(folder / "V24915_PERF2_R4_SEALED_IDP_AUTHORITY.json", sealed_idp_authority)
                runtime_bundle_preflight = _fresh100_runtime_preflight(cfg, HERE)
                runtime_bundle_preflight["deployment_preflight"] = deployment_preflight
                atomic_json(folder / "V24915_PERF1_RUNTIME_BUNDLE_PREFLIGHT.json", runtime_bundle_preflight)
                current_profile_observations = _bind_current_profile_authority(cfg)
                atomic_json(folder / "CURRENT_COUNTLOCATION_CALIBRATION_AUTHORITY.json", cfg["current_countlocation_authority"])
                # The network was intentionally modified.  Never restore paths
                # from the global V248 cache or historical RUNS trees.  This
                # run gets a unique, initially absent cache root; therefore its
                # first path epoch must be freshly enumerated from live Visum.
                cache_root = _fresh_run_cache_root(folder, project_base)
                legacy_roots = []
                cfg["runtime_persistent_path_cache_root"] = str(cache_root)
                cfg["runtime_legacy_path_cache_roots"] = []
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
                    "root_policy": "FRESH_RUN_ISOLATED_NO_CROSS_RUN_RESTORE",
                    "legacy_roots": [],
                    "cross_run_restore_allowed": False,
                    "legacy_import_allowed": False,
                    "fresh_path_enumeration_required": True,
                    "within_run_cache_reuse_allowed": True,
                    "source_version": str(source_ver),
                    "source_sha256": source_sha_before,
                })
                methodology = {
                    "production_release": False,
                    "working_copy_trial_calibration": True,
                    "v24915_package_revision": cfg.get("package_revision"),
                    "v24915_runtime_bundle_preflight": runtime_bundle_preflight,
                    "v24915_demand_continuation_policy": "EXACT_PROFILE488_A0004_PARTIAL_CYCLE3_TD_RESUME",
                    "execution_mode": execution_mode,
                    "fresh100_mode": "EXACT_SEMANTIC_PROFILE488_A0004_PARTIAL_CYCLE3_TD_RESUME",
                    "fresh100_outer_cycle_cap": FRESH100_MAX_OUTER_CYCLES,
                    "fresh100_wall_clock_limit_disabled": True,
                    "fresh100_global_max_runtime_seconds": None,
                    "fresh100_source_role": "EXACT_A0004_RECOVERY_CHECKPOINT",
                    "fresh100_path_cache_policy": "FRESH_ENUMERATION_NO_CROSS_RUN_RESTORE_WITHIN_RUN_REUSE_ONLY",
                    "csd408_mapping_review_acknowledged": bool(cfg.get("csd408_mapping_review_acknowledged", False)),
                    "city90_bidirectional_qa_acknowledged": bool(cfg.get("city90_bidirectional_qa_acknowledged", False)),
                    "two_mode_full_geometry_identity_proven": False,
                    "two_mode_geometry_role": "CANDIDATE_PROPOSAL_ONLY",
                    "candidate_acceptance_role": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_DIAGNOSTICS",
                    "duplicate_policy": cfg.get("supply", {}).get("sequence", {}).get("design_only_duplicate_scope_policy"),
                    "observation_contract": "488_ROWS_FROM_USER_COUNTLOCATION_TABLE_ALL_CALIBRATION",
                    "countlocation_authority": copy.deepcopy(cfg.get("current_countlocation_authority", {})),
                    "calibration_order": ["COUPLED_DEMAND:GENERATION_THEN_FINECDF_TD_REPEAT", "SUPPLY_ROUTE_CHOICE"],
                    "supply_addval1_role": "FINAL_ROUTE_CHOICE_LINK_TUNING_AFTER_COUPLED_DEMAND_FIXED_POINT_ONLY",
                    "trip_generation_and_distribution_relationship": "ONE_COUPLED_DEMAND_PHASE_NOT_INDEPENDENT_PHASES",
                    "td_authority": "HASH_LOCKED_R1_BC_AUTO_DIST_ONLY_FINECDF_SOFT_V1_9_512_POINT_IDP",
                    "td_survey_reference_role": "SOFT_DIRECTIONAL_REFERENCE_NOT_EXACT_FIT",
                    "td_exact_curve_match_required": False,
                    "td_acceptance_policy": "MATERIAL_AGGREGATE_IMPROVEMENT_WITH_BOUNDED_COMPONENT_TRADEOFF",
                    "native_multi_guard_policy": "DIAGNOSTIC_ONLY_NATIVE_OUTPUT_AUTHORITY",
                    "performance_search_semantics": "PERSISTENT_PATH_EPOCH_ADAPTIVE_EXPLICIT_NOT_BITWISE_IDENTICAL",
                    "path_enumeration_policy": "AUTHORIZED_PERSISTENT_CACHE_OR_FRESH_ENUMERATION_THEN_ONLY_AT_LOCAL_PLATEAU",
                    "path_epoch_acceptance_authority": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_DIAGNOSTICS",
                    "persistent_path_cache_policy": "HASHED_SQLITE_PLUS_ACCEPTED_STATE_BINDINGS_FAIL_CLOSED",
                    "stable_project_root_policy": "OUTERMOST_PRIOR_RUN_TREE_NORMALIZED_AND_POSTCONDITION_CHECKED",
                    "generation_bound_projection_policy": "CLIP_DIRECT_ACTUATOR_CAPACITY_THEN_ATTENUATE_LARGER_PA_ROLE",
                    "generation_bound_projection_acceptance": "FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D",
                    "td_realization_policy": "BACKTRACK_B_AND_LOG_NEG_C_WITH_UNCHANGED_NATIVE_IPF_TOLERANCE_AND_SOFT_ACCEPTANCE",
                    "td_parameter_freeze_policy": "EXACT_FROZEN_CONTEXT_AND_METADATA_NUMERIC_B_C_1E_8_1E_10",
                    "td_generation_gate": "TD_REALIZATION_COMPLETE_BEFORE_NEXT_GENERATION",
                    "rollback_evidence_policy": "ATOMIC_COPY_AND_CENTRAL_SHORT_RUN_ROOT_MIRROR_WHEN_NEEDED",
                    "csd_calibration_objective": "OBSERVATION_WEIGHTED_MEAN_GEH",
                    "profile_sum_role": "DIAGNOSTIC_ONLY_PROFILE_PASSAGE_CHECKSUM_NOT_UNIQUE_TRIPS",
                    "long_acceptance_role": "GLOBAL_LONG_COMPOSITE_FROM_FIVE_NATIVE_MATRICES",
                    "long_parameterization": "COMMON_B_OFFSET_AND_COMMON_C_MULTIPLIER",
                    "zone_attribute_transaction": "CACHED_ZONE_COM_KEYS_SETMULTIATTVALUES_READBACK",
                    "com_retry_policy": "BOUNDED_TRANSIENT_RPC_CALL_REJECTED_OR_RETRY_LATER_ONLY",
                    "bounded_path_export_retry": "SAME_PAGE_RANGE_TRANSIENT_RETRY_BEFORE_NONTRANSIENT_PAGE_BACKTRACK",
                    "path_export_page_size_fallback": "NONTRANSIENT_MEMORY_RANGE_OR_OVERFLOW_ONLY",
                    "restart_authority": "SEMANTIC_MODEL_STATE",
                    "raw_ver_sha_role": restart.RAW_VER_SHA_ROLE,
                    "raw_ver_sha_used_for_restart_acceptance": False,
                    "cp03_live_path_hotfix_retained": True,
                }
                atomic_json(folder / "METHODOLOGY_STATUS.json", methodology)
                result["methodology_status"] = methodology

                # Build the restart authority from live model semantics. A normal
                # Visum Save may reserialize the .ver and change its raw SHA-256;
                # that byte identity is provenance only across runs. During this
                # run it remains a hard mutation sentinel for the untouched source.
                control = UnlimitedOvernightControl(folder, cfg)
                rt.Visum = visum
                adapter = VisumAdapter(visum, cfg, control)
                control.checkpoint("SOURCE_SEMANTIC_RESTART_AUTHORITY", force=True)
                source_snapshot = adapter.snapshot()
                source_semantic = restart.build_authority(
                    source_snapshot, version_path=source_ver,
                    raw_ver_sha256=source_sha_before,
                    origin="RUN_START_LIVE_SOURCE_VERSION")
                # Fresh-cycle-1 contract: the currently opened live .ver is the
                # new baseline authority.  Any adjacent sidecar belongs to prior
                # lineage and is diagnostic only; it must not veto an intentional
                # fresh baseline.  The hard gate remains the live-source -> saved
                # working-copy semantic identity check below.
                sidecar_check = _fresh_baseline_sidecar_diagnostic(
                    source_ver, source_semantic)
                source_semantic["optional_adjacent_sidecar_check"] = sidecar_check
                atomic_json(folder / "SOURCE_SEMANTIC_RESTART_AUTHORITY.json", source_semantic)
                cfg["runtime_source_semantic_state_hash"] = source_semantic["semantic_state_hash"]
                cache_location_path = folder / "PERSISTENT_PATH_CACHE_LOCATION.json"
                cache_location = rt.read_json(cache_location_path)
                cache_location.update({
                    "source_semantic_state_hash": source_semantic["semantic_state_hash"],
                    "source_raw_ver_sha_role": restart.RAW_VER_SHA_ROLE,
                    "source_raw_ver_sha_used_for_restart_acceptance": False,
                })
                atomic_json(cache_location_path, cache_location)
                atomic_json(folder / "SOURCE_VERSION_AUTHORITY.json", {
                    "source_version": str(source_ver),
                    "source_sha256_before": source_sha_before,
                    "raw_ver_sha_role": restart.RAW_VER_SHA_ROLE,
                    "raw_ver_sha_used_for_restart_acceptance": False,
                    "semantic_restart_schema": restart.SCHEMA,
                    "semantic_state_hash": source_semantic["semantic_state_hash"],
                    "semantic_hashes": source_semantic["semantic_hashes"],
                    "optional_adjacent_sidecar_check": sidecar_check,
                    "policy": "SOURCE_FILE_MUST_REMAIN_UNTOUCHED_DURING_THIS_RUN; CROSS_RUN_RESTART_USES_SEMANTICS_NOT_RAW_VER_SHA",
                })

                if execution_mode == "FULL":
                    continuation = recovery_a0004.resolve_continuation(
                        source_ver, source_semantic, HERE)
                    cfg["runtime_demand_continuation"] = continuation
                    handoff_name = "PROFILE488_A0004_CYCLE3_TD_RECOVERY_HANDOFF.json"
                    atomic_json(folder / handoff_name, continuation)
                    methodology["v24915_demand_continuation_policy"] = (
                        "EXACT_SEMANTIC_PROFILE488_A0004_SKIP_CYCLES1_2_AND_CYCLE3_GENERATION_RESUME_TD")
                    methodology["demand_continuation"] = {
                        "mode": continuation["mode"],
                        "accepted_count": continuation["accepted_count"],
                        "inherited_outer_cycles": continuation["inherited_outer_cycles"],
                        "next_outer_cycle": continuation["next_outer_cycle"],
                        "max_lineage_outer_cycle": continuation["max_lineage_outer_cycle"],
                        "resume_substep": continuation["resume_substep"],
                        "resume_outer_cycle": continuation["resume_outer_cycle"],
                        "semantic_state_hash": continuation["semantic_state_hash"],
                        "generation_reference_sha256": continuation["generation_reference_sha256"],
                        "budget_stop_reasons": continuation["bounded_inner_budget_stop_reasons"],
                        "source_role": "EXACT_ACCEPTED_A0004_RECOVERY_CHECKPOINT",
                    }
                    methodology["performance_telemetry_policy"] = (
                        "BEST_EFFORT_NEVER_ABORT_CALIBRATION_ON_WINDOWS_FILE_LOCK")
                    atomic_json(folder / "METHODOLOGY_STATUS.json", methodology)

                # Isolate all subsequent writes from the user's source .ver and
                # prove that SaveVersion preserved every restart-relevant model
                # semantic field even when the serialized bytes differ.
                working = folder / "WORKING_START.ver"
                working_cp = rt.save_version(visum, working)
                atomic_json(folder / "WORKING_COPY.json", working_cp)
                control.checkpoint("WORKING_COPY_SEMANTIC_IDENTITY", force=True)
                working_snapshot = adapter.snapshot()
                working_semantic = restart.build_authority(
                    working_snapshot, version_path=working,
                    raw_ver_sha256=working_cp.get("sha256"),
                    origin="WORKING_COPY_AFTER_SAVEVERSION")
                working_semantic["source_semantic_comparison"] = restart.require_authority_match(
                    source_semantic, working_semantic,
                    label="WORKING_COPY_SEMANTIC_IDENTITY")
                atomic_json(folder / "WORKING_COPY_SEMANTIC_IDENTITY.json", working_semantic)
                atomic_json(restart.sidecar_path(working), working_semantic)
                cfg["runtime_working_semantic_state_hash"] = working_semantic["semantic_state_hash"]

                # User-selected current CountLocation table is the sole calibration
                # roster. Old R1_ACTIVE/R1_ROLE metadata are normalized only in the
                # isolated working copy so all 488 rows enter the calibration objective.
                profile_authority_apply = _apply_current_profile_metadata_to_working_copy(
                    visum, current_profile_observations)
                profile_authority_apply["source_xlsx_sha256"] = CURRENT_COUNTLOCATION_SOURCE_SHA256
                profile_authority_apply["source_xlsx"] = CURRENT_COUNTLOCATION_SOURCE_REL
                profile_authority_apply["working_copy_only"] = True
                profile_authority_apply["source_ver_on_disk_modified"] = False
                # Save the profile-bound state to a DISTINCT checkpoint.  The runtime
                # intentionally refuses to overwrite an existing .ver, so reusing
                # WORKING_START.ver here would fail before cycle 1.
                profile_bound_working = folder / "WORKING_PROFILE488_START.ver"
                normalized_working_cp = rt.save_version(visum, profile_bound_working)
                atomic_json(folder / "WORKING_PROFILE488_COPY.json", normalized_working_cp)
                profile_authority_apply["initial_working_copy_path"] = str(working)
                profile_authority_apply["profile_bound_working_copy_path"] = str(profile_bound_working)
                profile_authority_apply["working_copy_sha256"] = normalized_working_cp.get("sha256")
                normalized_snapshot = adapter.snapshot()
                normalized_semantic = restart.build_authority(
                    normalized_snapshot, version_path=profile_bound_working,
                    raw_ver_sha256=normalized_working_cp.get("sha256"),
                    origin="WORKING_COPY_AFTER_PROFILE488_AUTHORITY_BIND")
                normalized_semantic["pre_profile_bind_semantic_comparison"] = restart.require_authority_match(
                    working_semantic, normalized_semantic,
                    label="PROFILE488_BIND_RESTART_SEMANTIC_IDENTITY")
                working_semantic = normalized_semantic
                atomic_json(folder / "WORKING_COPY_SEMANTIC_IDENTITY.json", working_semantic)
                atomic_json(restart.sidecar_path(profile_bound_working), working_semantic)
                cfg["runtime_working_semantic_state_hash"] = working_semantic["semantic_state_hash"]
                atomic_json(folder / "COUNTLOCATION_CALIBRATION_AUTHORITY_APPLY.json", profile_authority_apply)

                startup_semantic_evidence = {
                    "source_semantic_state_hash": source_semantic["semantic_state_hash"],
                    "working_semantic_state_hash": working_semantic["semantic_state_hash"],
                    "raw_ver_sha_role": restart.RAW_VER_SHA_ROLE,
                    "raw_ver_sha_used_for_restart_acceptance": False,
                    "source_semantic_authority_file": str(
                        folder / "SOURCE_SEMANTIC_RESTART_AUTHORITY.json"),
                    "working_semantic_authority_file": str(
                        folder / "WORKING_COPY_SEMANTIC_IDENTITY.json"),
                    "demand_continuation": copy.deepcopy(
                        cfg.get("runtime_demand_continuation", {})),
                    "countlocation_calibration_authority": copy.deepcopy(
                        cfg.get("current_countlocation_authority", {})),
                    "countlocation_calibration_authority_apply": copy.deepcopy(profile_authority_apply),
                }
                result.update(startup_semantic_evidence)

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
                    result.update(status="LIVE_API_PREFLIGHT_FAILED",
                                  required_failures=report["required_failures"])
                else:
                    if execution_mode == "SUPPLY_ONLY":
                        controller_result = run_verified_supply_only(
                            adapter, cfg, folder / "CALIBRATION", control, source_ver)
                    else:
                        controller_result = run_overnight_calibration_coupled(
                            adapter, cfg, folder / "CALIBRATION", control, HERE)
                    controller_result.update(startup_semantic_evidence)
                    controller_result["methodology_status"] = methodology
                    result = controller_result

                # Save a final deliverable only when the controller exposes a verified live state.
                final_name = final_artifact_name(result)
                if adapter is not None and final_name is not None:
                    try:
                        live = adapter.snapshot()
                        if live["state_hash"] != result["final_state_hash"]:
                            raise RuntimeError("FINAL_LIVE_STATE_DIFFERS_FROM_CONTROLLER_ACCEPTED_STATE")
                        if rt.sha256_file(source_ver) != source_sha_before:
                            raise RuntimeError("SOURCE_FILE_CHANGED_BEFORE_FINAL_SAVE")
                        final_path = folder / final_name
                        final_cp = rt.save_version(visum, final_path)
                        final_live = adapter.snapshot()
                        if final_live != live:
                            raise RuntimeError("SAVEVERSION_CHANGED_VERIFIED_MODEL_STATE")
                        final_semantic = restart.build_authority(
                            final_live, version_path=final_path,
                            raw_ver_sha256=final_cp.get("sha256"),
                            origin="FINAL_VERIFIED_DELIVERABLE_AFTER_SAVE")
                        restart.require_authority_match(
                            source_semantic if result.get("accepted_count", 0) == 0 else
                            restart.build_authority(live, origin="CONTROLLER_FINAL_LIVE_STATE"),
                            final_semantic, label="FINAL_SAVE_SEMANTIC_IDENTITY")
                        atomic_json(restart.sidecar_path(final_path), final_semantic)
                        result["final_accepted_version"] = final_cp
                        result["final_semantic_restart_authority"] = {
                            "path": str(restart.sidecar_path(final_path)),
                            "semantic_state_hash": final_semantic["semantic_state_hash"],
                            "raw_ver_sha_role": restart.RAW_VER_SHA_ROLE,
                        }
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
                    result["raw_ver_sha_role"] = restart.RAW_VER_SHA_ROLE
                    result["raw_ver_sha_used_for_restart_acceptance"] = False
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


def main(execution_mode="FULL"):
    try:
        return _main_impl(execution_mode)
    finally:
        sys.path[:] = _ORIGINAL_SYS_PATH


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main("FULL")
