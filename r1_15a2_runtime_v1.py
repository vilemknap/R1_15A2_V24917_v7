# -*- coding: utf-8 -*-
"""R1 / PTV Visum STEP 15A2 -- actual-path-incidence ADD calibration master.

This is a guarded generative calibration system.  It uses official saved Visum
PrT path and path-link lists to build the current flow matrix / route-incidence
operator.  A bounded regularised least-squares solve produces *OD guidance only*.
The guidance is projected to zone WORK/SERVICE production/attraction ADD
attributes; no OD matrix is directly corrected.  Every applied candidate must go
through the active Visum TG -> TD -> realization -> assignment sequence and must
pass CAL-only CSD acceptance plus IDP guardrails.  VALIDATION profiles are report
only and never enter candidate design or acceptance.

Default is DESIGN ONLY.  For a real guarded step set R1_15A2_APPLY=1 or change
"apply" in R1_15A2_CONFIG.json.

Required next to this script:
  r1_15a2_core.py
  R1_15A2_CONFIG.json
  helpers/R1_12D_CSD2022_GEH_FORENSIC_444_PROCSEQ_EMBEDDED.py
  helpers/R1_11D_V1_3_COMPONENT_DIST_BEHAVIOR_DIAGNOSTICS.py

Run manually from PTV Visum with an accepted .ver open.  Do not place this master
inside the active Procedure Sequence.
"""
from __future__ import print_function

import csv
import gc
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    import numpy as np
except Exception:
    np = None

try:
    import win32com.client  # type: ignore
except Exception:
    win32com = None  # type: ignore

SCRIPT_ID = "R1_15A2_ACTUAL_PATH_INCIDENCE_CALIBRATION_MASTER_V1_0"
OUT_ROOT_NAME = "R1_15A2_ACTUAL_PATH_INCIDENCE_CALIBRATION"
CONFIG_NAME = "R1_15A2_CONFIG.json"
D12_NAME = "R1_12D_CSD2022_GEH_FORENSIC_444_PROCSEQ_EMBEDDED.py"
D11_NAME = "R1_11D_V1_3_COMPONENT_DIST_BEHAVIOR_DIAGNOSTICS.py"
D12_DETAIL = "01_DETAIL_444_FORENSIC.csv"
D12_SUMMARY = "09_SUMMARY.json"
D11_PREFIX = "r1_step11d_v1_3_component_dist_behavior_"
D11_SUMMARY = D11_PREFIX + "summary.json"
EXPECTED_ZONES = 681

PATH_KEY_HEADERS = ["OrigZoneNo", "DestZoneNo", "Index"]
PATH_EXTRA_ATTRS = ["Vol(AP)", "t0", "v0", "tCur", "vCur", "Impedance(AP)", "Length"]
PATHLINK_KEY_HEADERS = ["OrigZoneNo", "DestZoneNo", "PathIndex", "Index"]
PATHLINK_EXTRA_ATTRS = ["LinkNo", "FromNodeNo", "ToNodeNo"]

ADD_ATTR_MAP = {
    ("WORK", "PROD"): "ADD_PROD_W",
    ("WORK", "ATT"): "ADD_ATT_W",
    ("SERVICE", "PROD"): "ADD_PROD_S",
    ("SERVICE", "ATT"): "ADD_ATT_S",
}

PROCSEQ_CORE_ATTRS = [
    "NO", "No", "OPERATIONNO", "OperationNo", "INDEX", "Index", "ORDERNO", "OrderNo",
    "ACTIVE", "Active", "OPERATIONTYPE", "OperationType", "PROCEDURETYPE", "ProcedureType",
    "PROCEDURE", "Procedure", "NAME", "Name", "USERDEFINEDNAME", "UserDefinedName",
    "COMMENT", "Comment", "VARIANT", "Variant", "FILE", "File", "FILENAME", "FileName",
    "DSEGSET", "DSegSet", "DSEGCODE", "DSegCode", "DSTRATSET", "DStratSet", "DSTRATCODE", "DStratCode",
    "MODE", "Mode", "MODES", "Modes", "TSYSSET", "TSysSet", "TRANSPORTSYSTEMSET", "TransportSystemSet",
    "FORMULA", "Formula", "EXPRESSION", "Expression", "SCRIPTFILE", "ScriptFile", "SCRIPTFILENAME", "ScriptFileName",
]


def script_dir():
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path.cwd()


sys.path.insert(0, str(script_dir()))
from r1_15a2_core import (  # noqa: E402
    acceptance_decision,
    build_actual_path_incidence,
    merge_actual_path_incidence_batches,
    family_from_dseg,
    fval,
    first_value,
    ival,
    norm_code,
    path_parity_rows,
    prepare_guidance_problem,
    project_guidance_to_add,
    solve_guidance,
    summarize_path_parity,
    sval,
)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def compact_error(exc, limit=1200):
    text = (exc.__class__.__name__ + ": " + sval(exc)).replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "..."


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None or not str(val).strip():
        return bool(default)
    return str(val).strip().lower() in ("1", "true", "yes", "y", "ano", "on")


def env_int(name, default):
    try:
        return int(round(float(str(os.environ.get(name, default)).strip().replace(",", "."))))
    except Exception:
        return int(default)


def env_float(name, default):
    try:
        return float(str(os.environ.get(name, default)).strip().replace(",", "."))
    except Exception:
        return float(default)


def read_json(path):
    with Path(path).open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows or [])
    if fields is None:
        fields = []
        seen = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    fields.append(key); seen.add(key)
        if not fields:
            fields = ["empty"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter=";", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def read_csv_auto(path):
    path = Path(path)
    for sep in (";", ","):
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                rows = [dict(r) for r in csv.DictReader(f, delimiter=sep)]
            if rows and len(rows[0]) > 1:
                return rows
        except Exception:
            pass
    return []


def log_line(out_dir, message):
    line = "%s  %s" % (now_iso(), message)
    try:
        print(line)
    except Exception:
        pass
    try:
        with (Path(out_dir) / "00_LOG.txt").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_folder(folder, zip_path):
    folder = Path(folder); zip_path = Path(zip_path)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file() and p.suffix.lower() not in (".ver", ".verx"):
                zf.write(str(p), str(p.relative_to(folder)))
    return zip_path


def load_config():
    path = script_dir() / CONFIG_NAME
    if not path.is_file():
        raise RuntimeError("Missing configuration: %s" % path)
    cfg = read_json(path)
    # Only operational overrides are allowed here. Numerical defaults remain
    # versioned in the JSON and are copied into every evidence package.
    cfg["apply"] = env_bool("R1_15A2_APPLY", cfg.get("apply", False))
    cfg["run_procseq"] = env_bool("R1_15A2_RUN_PROCSEQ", cfg.get("run_procseq", True))
    cfg["max_accepted_iterations"] = env_int("R1_15A2_MAX_ITER", cfg.get("max_accepted_iterations", 1))
    cfg["enable_kordon_pairs"] = env_bool("R1_15A2_ENABLE_KORDON_PAIRS", cfg.get("enable_kordon_pairs", False))
    cfg["guidance_mode"] = os.environ.get("R1_15A2_GUIDANCE_MODE", cfg.get("guidance_mode", "POSITIVE_ONLY"))
    cfg["config_path"] = str(path)
    cfg["config_sha256"] = sha256_file(path)
    return cfg


import r1_15a2_com_compat as com


def get_visum():
    return com.bind_injected(globals())


def att(obj, name, default=None):
    try:
        value = obj.AttValue(name)
        return default if value is None else value
    except Exception:
        return default


def get_all(coll, limit=None):
    items = com.collection_items(coll)
    return items[:limit] if limit else items


def get_multi(coll, attr_name, retry_policy=None):
    return com.get_multi_att_values(coll, attr_name, retry_policy)


def set_multi(coll, attr_name, rows, retry_policy=None):
    return com.set_multi_att_values(coll, attr_name, rows, retry_policy)


def zone_numbers(visum, retry_policy=None):
    nums, _indices = com.zone_identity(visum, retry_policy=retry_policy)
    if sorted(nums) != list(range(1, EXPECTED_ZONES + 1)):
        raise RuntimeError("Zone gate failed; expected exactly 1..%d, got count=%d" % (EXPECTED_ZONES, len(nums)))
    # GetValues follows model axis order. Do not sort away an axis mismatch.
    if nums != sorted(nums):
        raise RuntimeError("ZONE_MATRIX_AXIS_ORDER_MISMATCH: GetMultiAttValues(NO) order is not 1..681")
    return nums


def resolve_actuator_zone_scope(zone_nos, cfg, out_dir):
    """Resolve the exact zone set on which ordinary WORK/SERVICE ADD may act.

    This is deliberately an actuator-scope authority, not an II/IE/EI/EE zone
    classification.  The inherited Visum workflow protects special external
    macrozones and SK gate seed zones from ordinary ADD calibration because they
    have separate synthetic P/A logic.  The list is versioned in the JSON
    configuration and every run exports the resolved scope.
    """
    policy = sval(cfg.get("zone_actuator_policy", "EXCLUDE_CONFIGURED_SPECIAL_ZONES")).strip().upper()
    all_zones = set(int(z) for z in zone_nos)
    if policy == "ALL_ZONES":
        excluded = set()
        reason = "ALL_ZONES_EXPLICIT"
    elif policy == "EXCLUDE_CONFIGURED_SPECIAL_ZONES":
        excluded = set(int(x) for x in cfg.get("add_actuator_excluded_zone_nos", []))
        missing = sorted(excluded - all_zones)
        if missing:
            raise RuntimeError("Configured ADD actuator exclusions are not present in Zone.NO: %s" % missing)
        expected = int(cfg.get("expected_add_actuator_excluded_zone_count", 0) or 0)
        if expected > 0 and len(excluded) != expected:
            raise RuntimeError(
                "ADD actuator exclusion authority count mismatch: configured=%d expected=%d" %
                (len(excluded), expected)
            )
        reason = "CONFIGURED_SPECIAL_ZONE_EXCLUSION"
    else:
        raise RuntimeError("Unsupported zone_actuator_policy=%s" % policy)

    eligible = sorted(all_zones - excluded)
    expected_eligible = int(cfg.get("expected_add_actuator_eligible_zone_count", 0) or 0)
    if expected_eligible > 0 and len(eligible) != expected_eligible:
        raise RuntimeError(
            "ADD actuator eligible-zone count mismatch: resolved=%d expected=%d" %
            (len(eligible), expected_eligible)
        )
    rows = []
    for z in sorted(all_zones):
        rows.append({
            "zone_no": z,
            "add_actuatable": int(z in eligible),
            "scope_reason": "ORDINARY_WS_ADD_ACTUATOR" if z in eligible else reason,
        })
    write_csv(Path(out_dir) / "00_ZONE_ACTUATOR_SCOPE.csv", rows)
    summary = {
        "policy": policy,
        "zone_count": len(all_zones),
        "eligible_zone_count": len(eligible),
        "excluded_zone_count": len(excluded),
        "excluded_zone_nos": sorted(excluded),
        "mutable_relation_policy": sval(cfg.get("mutable_relation_policy", "BOTH_ENDPOINTS_ACTUATABLE")).upper(),
        "passes": True,
    }
    write_json(Path(out_dir) / "00_ZONE_ACTUATOR_SCOPE_SUMMARY.json", summary)
    return eligible, summary


def read_zone_attr(visum, attr_name, zone_nos, zone_indices=None, retry_policy=None):
    return com.indexed_zone_values(
        visum, attr_name, zone_nos, retry_policy=retry_policy, zone_indices=zone_indices)


def write_zone_attr(visum, attr_name, zone_nos, values, zone_indices=None,
                    retry_policy=None, readback_tolerance=1.0e-7):
    if len(zone_nos) != len(values):
        raise RuntimeError("ZONE_WRITE_LENGTH_MISMATCH")
    indices = zone_indices or com.zone_write_indices(visum, zone_nos, retry_policy)
    expected = {int(z) for z in zone_nos}
    if set(indices) != expected or len(set(indices.values())) != len(indices):
        raise RuntimeError("ZONE_WRITE_CACHED_IDENTITY_MISMATCH")
    rows = [[indices[int(z)], com.finite_float(v, attr_name)] for z, v in zip(zone_nos, values)]
    set_multi(visum.Net.Zones, attr_name, rows, retry_policy=retry_policy)
    got = read_zone_attr(
        visum, attr_name, zone_nos, zone_indices=indices, retry_policy=retry_policy)
    max_abs = max((abs(a-b) for a,b in zip(got, values)), default=0.0)
    if max_abs > float(readback_tolerance):
        raise RuntimeError("Zone attribute readback mismatch %s max_abs=%g" % (attr_name, max_abs))
    return got


def save_version(visum, path):
    """Publish fresh nonempty bytes; never mistake an old/partial file for a save."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError("SAVEVERSION_REFUSES_EXISTING_FILE:" + str(path))
    errors = []
    for fn in (
        lambda: visum.IO.SaveVersion(str(path)),
        lambda: visum.SaveVersion(str(path)),
    ):
        try:
            fn()
        except Exception as exc:
            errors.append(compact_error(exc))
            # A failed first API call may have left a corrupt .ver. Keep it as
            # forensic evidence, but do not allow the fallback to endorse it.
            if path.exists():
                raise RuntimeError("SAVEVERSION_FAILED_WITH_PARTIAL_FILE:" + str(path)) from exc
            continue
        if path.is_file() and path.stat().st_size > 0:
            return {"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}
        if path.exists():
            raise RuntimeError("SAVEVERSION_EMPTY_OR_NONFILE_OUTPUT:" + str(path))
        errors.append("SaveVersion returned without producing a file")
    raise RuntimeError("Could not save checkpoint %s: %s" % (path, " | ".join(errors)))


def load_version(visum, path):
    path = Path(path)
    if not path.is_file():
        raise RuntimeError("Rollback checkpoint missing: %s" % path)
    errors = []
    for fn in (
        lambda: visum.IO.LoadVersion(str(path)),
        lambda: visum.LoadVersion(str(path)),
    ):
        try:
            fn(); return
        except Exception as exc:
            errors.append(compact_error(exc))
    raise RuntimeError("Could not load checkpoint %s: %s" % (path, " | ".join(errors)))


# -----------------------------------------------------------------------------
# Helper diagnostics
# -----------------------------------------------------------------------------

# Live V2.4.5 exposed a Windows MAX_PATH failure: deeply nested candidate /
# rollback folders plus the helper's own output tree can exceed 260 characters.
# Helpers therefore execute in a short OS-temporary workspace.  Only compact
# evidence mirrors and ZIP archives are published back to the durable run tree.
# This preserves the diagnostic semantics while decoupling helper I/O from the
# controller's descriptive folder hierarchy.
_HELPER_MIRROR_TEXT_PATTERNS = ("*fatal_error*.txt", "*_stdout.txt", "*.log")

def _short_helper_workspace(stage):
    token = re.sub(r"[^A-Za-z0-9]+", "", str(stage).upper())[:10] or "HELPER"
    path = Path(tempfile.mkdtemp(prefix="R1A2_%s_" % token))
    # Leave ample room for helper-created subdirectories / filenames.
    # 220 is deliberately stricter than historical MAX_PATH=260.
    if len(str(path)) > 120:
        shutil.rmtree(str(path), ignore_errors=True)
        raise RuntimeError("HELPER_TEMP_ROOT_TOO_LONG:%d:%s" % (len(str(path)), path))
    return path

def _copy_if_file(source, destination):
    """Atomically copy one evidence file.

    The caller must already choose a path-safe durable mirror directory.  A
    temporary sibling plus os.replace avoids endorsing a partial copy if the
    process is interrupted.
    """
    source = Path(source); destination = Path(destination)
    if not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp_%d" % os.getpid())
    try:
        if tmp.exists():
            tmp.unlink()
        shutil.copy2(str(source), str(tmp))
        os.replace(str(tmp), str(destination))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
    return destination


def _run_directory_for_path(path):
    path = Path(path).resolve()
    for candidate in (path,) + tuple(path.parents):
        if not candidate.name.upper().startswith("RUN_"):
            continue
        parent = candidate.parent.name.upper()
        if parent.startswith("R1_15A2_") and parent.endswith("_RUNS"):
            return candidate
    return None


def _durable_helper_paths(out_dir, stem):
    """Choose a mirror and archive location with Windows MAX_PATH headroom.

    Deep TRY/rollback folders can be valid controller evidence locations while
    still being unsafe destinations for helper filenames.  When the projected
    path is long, evidence is stored under RUN_x/H/<token>; the returned paths
    are authoritative and are recorded in HELPER_WORKSPACE_POLICY.json.
    """
    out_dir = Path(out_dir)
    preferred = out_dir / stem
    # Reserve enough room for the longest current 11D/12D evidence filename.
    use_central = len(str(preferred)) + 120 >= 240
    run_dir = _run_directory_for_path(out_dir)
    if use_central and run_dir is not None:
        token = hashlib.sha256(str(preferred).encode("utf-8")).hexdigest()[:16]
        mirror = run_dir / "H" / (stem[:20] + "_" + token)
        mode = "RUN_ROOT_H_CENTRAL_SHORT_MIRROR"
    else:
        mirror = preferred
        mode = "IN_PLACE"
    mirror.mkdir(parents=True, exist_ok=True)
    archive = mirror.parent / (mirror.name + ".zip")
    stage_log = mirror / "20_STAGE_LOG.txt"
    return {
        "mirror": mirror,
        "archive": archive,
        "stage_log": stage_log,
        "mode": mode,
        "intended_mirror": preferred,
        "run_directory": run_dir,
    }

def _mirror_helper_failure(workspace, mirror):
    workspace = Path(workspace); mirror = Path(mirror)
    mirror.mkdir(parents=True, exist_ok=True)
    copied = []
    seen = set()
    for pattern in _HELPER_MIRROR_TEXT_PATTERNS:
        for source in workspace.rglob(pattern):
            if not source.is_file() or source.name in seen:
                continue
            target = mirror / source.name
            _copy_if_file(source, target)
            copied.append(str(target)); seen.add(source.name)
    return copied

def _archive_helper_workspace(workspace, zip_path):
    workspace = Path(workspace); zip_path = Path(zip_path)
    if workspace.exists():
        zip_folder(workspace, zip_path)
        return zip_path
    return None

def _clear_helper_workspace(workspace, preserve=()):
    workspace = Path(workspace)
    keep = {Path(x).resolve() for x in preserve}
    if not workspace.exists():
        return
    for child in list(workspace.iterdir()):
        if child.resolve() in keep:
            continue
        if child.is_dir():
            shutil.rmtree(str(child), ignore_errors=True)
        else:
            try:
                child.unlink()
            except FileNotFoundError:
                pass


def run_helper(script, visum, stage, workspace, stage_log, retry_policy=None):
    script = Path(script); workspace = Path(workspace); stage_log = Path(stage_log)
    workspace.mkdir(parents=True, exist_ok=True)
    stage_log.parent.mkdir(parents=True, exist_ok=True)
    if not script.is_file():
        raise RuntimeError("Helper script missing: %s" % script)

    attempts, delay, factor, maximum = com.com_retry_settings(retry_policy)
    if not bool(dict(retry_policy or {}).get("helper_retry_enabled", False)):
        attempts = 1

    for attempt in range(1, attempts + 1):
        if attempt > 1:
            _clear_helper_workspace(workspace, preserve=(stage_log,))
            workspace.mkdir(parents=True, exist_ok=True)
        copy = workspace / script.name
        if script.resolve() != copy.resolve():
            shutil.copy2(str(script), str(copy))
        stdout_path = workspace / (stage + "_stdout.txt")

        def silent_print(*args, **kwargs):
            try:
                sep = kwargs.get("sep", " "); end = kwargs.get("end", "\n")
                with stdout_path.open("a", encoding="utf-8") as f:
                    f.write(sep.join(str(x) for x in args) + end)
            except Exception:
                pass

        with stage_log.open("a", encoding="utf-8") as f:
            f.write("%s START %s %s attempt=%d/%d\n" %
                    (now_iso(), stage, copy, attempt, attempts))
        env = {"Visum": visum, "__name__": "__main__", "__file__": str(copy),
               "print": silent_print}
        old_cwd = os.getcwd()
        try:
            os.chdir(str(workspace))
            exec(compile(copy.read_text(encoding="utf-8-sig"), str(copy), "exec"), env, env)
        except Exception as exc:
            if not com.is_retryable_com_error(exc) or attempt >= attempts:
                raise
            with stage_log.open("a", encoding="utf-8") as f:
                f.write("%s RETRYABLE_COM %s attempt=%d/%d delay=%.6g error=%s\n" %
                        (now_iso(), stage, attempt, attempts, delay, compact_error(exc)))
            com._pump_waiting_messages()
            if delay > 0.0:
                time.sleep(delay)
            delay = min(maximum, delay * factor if delay > 0.0 else maximum)
            continue
        finally:
            os.chdir(old_cwd)
        with stage_log.open("a", encoding="utf-8") as f:
            f.write("%s DONE %s attempt=%d\n" % (now_iso(), stage, attempt))
        return


def find_file_recursive(root, name):
    root = Path(root)
    direct = root / name
    if direct.is_file():
        return direct
    candidates = list(root.rglob(name))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def run_12d(visum, out_dir, label, cfg):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    durable = _durable_helper_paths(out_dir, "12D_" + label)
    mirror = durable["mirror"]
    if mirror.exists():
        shutil.rmtree(str(mirror), ignore_errors=True)
        mirror.mkdir(parents=True, exist_ok=True)
    scratch = _short_helper_workspace("12D_" + label)
    helper_name = str(cfg.get("12d_helper_name", D12_NAME))
    if Path(helper_name).name != helper_name or not helper_name.endswith(".py"):
        shutil.rmtree(str(scratch), ignore_errors=True)
        raise RuntimeError("Unsafe 12D helper selection")
    try:
        authority_rel = cfg.get("12d_authority_csv")
        if authority_rel:
            authority_path = (script_dir() / str(authority_rel)).resolve()
            if not authority_path.is_relative_to(script_dir().resolve()) or not authority_path.is_file():
                raise RuntimeError("CSD408 selected authority CSV unavailable or out of package")
            expected_sha = cfg.get("12d_authority_sha256")
            if not expected_sha or sha256_file(authority_path) != expected_sha:
                raise RuntimeError("CSD408 approved authority SHA256 mismatch")
            shutil.copy2(str(authority_path), str(scratch / authority_path.name))
        city_rel = cfg.get("12d_city_authority_csv")
        if city_rel:
            city_path = (script_dir() / str(city_rel)).resolve()
            if not city_path.is_relative_to(script_dir().resolve()) or not city_path.is_file():
                raise RuntimeError("Approved CITY90 RPDI authority missing or outside package")
            city_sha = cfg.get("12d_city_authority_sha256")
            if not city_sha or sha256_file(city_path) != city_sha:
                raise RuntimeError("CITY90 authoritative R1_OBS_RPDI SHA256 mismatch")
            shutil.copy2(str(city_path), str(scratch / city_path.name))
        helper_args = (script_dir() / "helpers" / helper_name, visum,
                       "12D_" + label, scratch, durable["stage_log"])
        if cfg.get("com_resilience") is None:
            # Preserve the historical five-argument helper boundary for legacy
            # releases and test doubles. V2.4.9.3 opts into the sixth argument.
            run_helper(*helper_args)
        else:
            run_helper(*helper_args, cfg.get("com_resilience"))
        detail_name = str(cfg.get("12d_detail_name", D12_DETAIL))
        if Path(detail_name).name != detail_name or not detail_name.endswith(".csv"):
            raise RuntimeError("Unsafe 12D detail selection")
        detail = find_file_recursive(scratch, detail_name)
        summary = find_file_recursive(scratch, D12_SUMMARY)
        if not detail or not summary:
            raise RuntimeError("12D output incomplete in short helper workspace %s" % scratch)
        meta = read_json(summary)
        if meta.get("status") != "PASS":
            raise RuntimeError("12D not PASS: %s" % summary)
        rows = read_csv_auto(detail)
        expected_rows = int(cfg.get("expected_12d_rows", 444))
        expected_cal = int(cfg.get("expected_calibration_rows", 404))
        expected_val = int(cfg.get("expected_validation_rows", 40))
        cal_n = sum(1 for r in rows if sval(r.get("role", "")).upper() == "CALIBRATION")
        val_n = sum(1 for r in rows if sval(r.get("role", "")).upper() == "VALIDATION")
        if len(rows) != expected_rows or cal_n != expected_cal or val_n != expected_val:
            raise RuntimeError(
                "12D authority row gate failed: rows=%d/%d CAL=%d/%d VALID=%d/%d" %
                (len(rows), expected_rows, cal_n, expected_cal, val_n, expected_val)
            )
        # Publish only compact, path-safe mirrors; the full raw helper tree lives
        # in the ZIP evidence.  This avoids recreating the helper's nested tree
        # inside already-deep TRY/ROLLBACK folders.
        mirror.mkdir(parents=True, exist_ok=True)
        detail_mirror = _copy_if_file(detail, mirror / detail.name)
        summary_mirror = _copy_if_file(summary, mirror / summary.name)
        for source in scratch.rglob("19_*AUTHORITY_CHECK.json"):
            _copy_if_file(source, mirror / source.name)
        for name in ("12d_PASS.txt", "12d_geh_forensic.log"):
            source = find_file_recursive(scratch, name)
            if source:
                _copy_if_file(source, mirror / source.name)
        evidence_zip = durable["archive"]
        _archive_helper_workspace(scratch, evidence_zip)
        write_json(mirror / "HELPER_WORKSPACE_POLICY.json", {
            "execution_workspace_policy": "SHORT_OS_TEMP",
            "execution_workspace_length": len(str(scratch)),
            "durable_mirror": str(mirror),
            "intended_mirror": str(durable["intended_mirror"]),
            "durable_mirror_mode": durable["mode"],
            "evidence_zip": str(evidence_zip),
            "reason": "WINDOWS_MAX_PATH_HARDENING_V2489",
        })
        return {
            "rows": rows, "summary": meta,
            "detail_path": str(detail_mirror), "summary_path": str(summary_mirror),
            "row_gate": {"rows": len(rows), "calibration": cal_n, "validation": val_n},
            "helper_workspace_policy": "SHORT_OS_TEMP", "evidence_zip": str(evidence_zip),
        }
    except BaseException:
        try:
            _mirror_helper_failure(scratch, mirror)
            _archive_helper_workspace(scratch, mirror.parent / (mirror.name + "_FAILED.zip"))
        except Exception:
            pass
        raise
    finally:
        shutil.rmtree(str(scratch), ignore_errors=True)


# R1 15A2 requires the atomic IDP diagnostics of legacy 11D, NOT its old
# TFlowFuzzy scaffold or its superseded calibration-count selection. 12D is
# independently sealed and mandatory for the authoritative 498 count rows.
# The legacy 11D summary remains unaltered for forensic traceability.
_15A2_ATOMIC_IDP = {
    "WORK_E_C": 9101, "WORK_E_noC": 9102, "WORK_noE_C": 9103,
    "WORK_noE_noC": 9104, "WORK_stud": 9105,
    "SERV_E_C": 9106, "SERV_E_noC": 9107, "SERV_noE_C": 9108,
    "SERV_noE_noC": 9109, "SERV_stud": 9110, "SCHOOL": 9117,
}
_15A2_LEGACY_11D_STATUSES = {
    "PASS_11D_BASELINE_DIAGNOSTICS_READ_ONLY",
    "REVIEW_11D_TFLOWFUZZY_SCAFFOLD",
    "REVIEW_11D_NO_TRAFFIC_COUNT_ROWS",
    "REVIEW_11D_COMPONENT_WEIGHT_FALLBACK",
}


def assess_11d_idp_gate(meta, d12, cfg):
    """Strict 15A2 IDP/read-only gate; legacy TFF and count metadata advisory.

    It is NOT an authorization of APPLY, saved-path parity, nor fresh assignment.
    Never replace any 11D numeric data with invented/fallback values.
    """
    failures, notices = [], []
    legacy = sval(meta.get("final_status", ""))
    if meta.get("step") != "11d_v1_3":
        failures.append("UNEXPECTED_11D_HELPER_VERSION")
    if legacy not in _15A2_LEGACY_11D_STATUSES:
        failures.append("UNRECOGNIZED_LEGACY_11D_STATUS:" + legacy)
    for key in ("model_modified", "model_saved", "matrix_correction_executed", "assignment_executed"):
        # Missing is NOT the same as false. Require the original helper's
        # explicit claim for each invariant, in addition to controller snapshot.
        if meta.get(key) is not False:
            failures.append("11D_READ_ONLY_INVARIANT_NOT_PROVEN:" + key)

    gate = d12.get("row_gate", {}) if isinstance(d12, dict) else {}
    for key, expected in (("rows", 498), ("calibration", 462), ("validation", 36)):
        if gate.get(key) != expected:
            failures.append("12D_APPROVED_COUNT_AUTHORITY_NOT_PROVEN:" + key)
    if not isinstance(d12, dict) or d12.get("summary", {}).get("status") != "PASS":
        failures.append("12D_PASSED_SUMMARY_NOT_AVAILABLE")

    dist = meta.get("dist_classification_matrix") or {}
    if dist.get("code") != "R1_OSRM_DIST_KM":
        failures.append("11D_DIST_KM_CLASSIFICATION_CODE_WRONG")
    readback = dist.get("readback") or {}
    for key in ("nonfinite_cells", "negative_cells"):
        if readback.get(key) != 0:
            failures.append("11D_CLASSIFICATION_%s_NOT_ZERO" % key.upper())
    if (meta.get("idp_contract") or {}).get("backend_metric") != "DIST_KM":
        failures.append("11D_IDP_BACKEND_NOT_DIST_KM")

    rows = meta.get("component_dist_summary_rows", [])
    if not isinstance(rows, list):
        failures.append("11D_ATOMIC_COMPONENT_SUMMARIES_NOT_LIST")
        rows = []
    seen, selected = set(), {}
    for row in rows:
        if not isinstance(row, dict):
            failures.append("11D_ATOMIC_COMPONENT_ROW_NOT_DICT")
            continue
        name = sval(row.get("component", ""))
        if name in _15A2_ATOMIC_IDP:
            if name in seen:
                failures.append("11D_DUPLICATE_ATOMIC_COMPONENT:" + name)
            seen.add(name)
            selected[name] = row
    for name, matrix_no in _15A2_ATOMIC_IDP.items():
        row = selected.get(name)
        if row is None:
            failures.append("11D_REQUIRED_ATOMIC_COMPONENT_MISSING:" + name)
            continue
        if row.get("target_status") != "ACTIVE_COMPONENT_DIST_TARGET":
            failures.append("11D_COMPONENT_TARGET_NOT_ACTIVE:" + name)
        if fval(row.get("matrix_no"), None) != matrix_no:
            failures.append("11D_COMPONENT_MATRIX_NUMBER_MISMATCH:" + name)
        expected_family = "SCHOOL" if name == "SCHOOL" else ("SERVICE" if name.startswith("SERV_") else "WORK")
        family = sval(row.get("family", "")).upper()
        if family == "SERV":
            family = "SERVICE"
        if family != expected_family:
            failures.append("11D_COMPONENT_FAMILY_MISMATCH:" + name)
        for field, require_positive in (("conditioned_volume", True),
                                        ("total_volume", True),
                                        ("mean_model_conditioned", False),
                                        ("mean_target", True),
                                        ("l1_distance_half", False),
                                        ("rmse_share", False)):
            value = fval(row.get(field), None)
            if value is None or value < 0 or (require_positive and value <= 0):
                failures.append("11D_COMPONENT_INVALID_%s:%s" % (field.upper(), name))
        cv = fval(row.get("conditioned_volume"), None)
        tv = fval(row.get("total_volume"), None)
        if cv is not None and tv is not None and cv > tv + max(1e-7, tv * 1e-7):
            failures.append("11D_COMPONENT_CONDITIONED_EXCEEDS_TOTAL:" + name)
        l1 = fval(row.get("l1_distance_half"), None)
        if l1 is not None and l1 > 1.000001:
            failures.append("11D_COMPONENT_L1_OUT_OF_RANGE:" + name)

    tff = meta.get("tflowfuzzy_scaffold_status")
    if tff not in ("PASS_INACTIVE_TFLOWFUZZY_SCAFFOLD", "REVIEW_TFLOWFUZZY_SCAFFOLD"):
        failures.append("11D_UNKNOWN_TFLOWFUZZY_STATUS")
    if tff != "PASS_INACTIVE_TFLOWFUZZY_SCAFFOLD":
        notices.append("LEGACY_INACTIVE_TFLOWFUZZY_SCAFFOLD_NOT_REQUIRED_BY_15A2")
    if not isinstance(meta.get("outputs"), dict):
        failures.append("11D_OUTPUT_CATALOG_MISSING")

    # Original 11D may label the whole run REVIEW because its legacy count
    # selector is empty or because composite weights used fallbacks. Neither
    # can replace the mandatory 12D count gate or atomic IDP metric gate.
    if legacy == "REVIEW_11D_NO_TRAFFIC_COUNT_ROWS":
        notices.append("LEGACY_11D_COUNT_ROWS_NOT_15A2_AUTHORITY_USE_12D_498")
    if legacy == "REVIEW_11D_COMPONENT_WEIGHT_FALLBACK":
        notices.append("LEGACY_11D_COMPOSITE_WEIGHT_FALLBACK_ATOMIC_IDP_VALIDATED")
    if legacy == "REVIEW_11D_TFLOWFUZZY_SCAFFOLD":
        notices.append("LEGACY_11D_TFLOWFUZZY_REVIEW_NOT_USED_FOR_15A2")

    # 66 is a demand-matrix correction. An ACTIVE type 66 is never advisory,
    # even if the helper's fuzzy scaffold classifier selected nothing.
    # Actual operation rows are exported in a separate 11D JSON. The caller
    # verifies them from that unmodified file, without trusting free text.
    if cfg.get("apply", False) and legacy != "PASS_11D_BASELINE_DIAGNOSTICS_READ_ONLY":
        failures.append("PRODUCTION_APPLY_REQUIRES_EXPLICIT_LEGACY_11D_APPROVAL")

    return {
        "status": "PASS_IDP_ONLY_WITH_LEGACY_11D_ADVISORIES" if not failures and notices else
                  "PASS_ATOMIC_IDP_READ_ONLY" if not failures else "FAIL_IDP_OR_READ_ONLY",
        "passes": not failures,
        "original_final_status": legacy,
        "original_helper_unchanged": True,
        "model_read_only_verified_from_helper_fields": all(meta.get(k) is False for k in
            ("model_modified", "model_saved", "matrix_correction_executed", "assignment_executed")),
        "mandatory_12d_row_gate": gate,
        "validated_atomic_idp_components": sorted(k for k in _15A2_ATOMIC_IDP if k in selected),
        "notices": notices,
        "failures": failures,
        "does_not_authorize_apply": True,
    }


def run_11d(visum, out_dir, label, d12=None, cfg=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    durable = _durable_helper_paths(out_dir, "11D_" + label)
    mirror = durable["mirror"]
    if mirror.exists():
        shutil.rmtree(str(mirror), ignore_errors=True)
        mirror.mkdir(parents=True, exist_ok=True)
    scratch = _short_helper_workspace("11D_" + label)
    cfg = cfg or {}
    try:
        helper_args = (script_dir() / "helpers" / D11_NAME, visum,
                       "11D_" + label, scratch, durable["stage_log"])
        if cfg.get("com_resilience") is None:
            run_helper(*helper_args)
        else:
            run_helper(*helper_args, cfg.get("com_resilience"))
        summary = find_file_recursive(scratch, D11_SUMMARY)
        if not summary:
            raise RuntimeError("11D summary missing in short helper workspace %s (check mirrored stdout/fatal evidence)" % scratch)
        meta = read_json(summary)
        decision = assess_11d_idp_gate(meta, d12, cfg)
        # Independently inspect the helper's original scaffold operation inventory,
        # which is kept in its own JSON. Fail closed if any correction is active.
        tff_file = find_file_recursive(scratch, "r1_step11d_v1_3_component_dist_behavior_tflowfuzzy_scaffold_status.json")
        if not tff_file:
            decision["failures"].append("11D_TFLOWFUZZY_OPERATION_INVENTORY_MISSING")
        else:
            raw_tff = read_json(tff_file)
            ops = raw_tff.get("operations")
            if not isinstance(ops, list) or not ops:
                decision["failures"].append("11D_TFLOWFUZZY_OPERATION_INVENTORY_EMPTY")
            else:
                active66 = []
                for op in ops:
                    typ = fval(op.get("operation_type"), None)
                    if typ == 66:
                        state = sval(op.get("active", "")).strip().upper()
                        if state not in ("0", "0.0", "FALSE", "F", "NO", "-0"):
                            active66.append(op.get("index"))
                if active66:
                    decision["failures"].append("ACTIVE_DEMAND_MATRIX_CORRECTION_TYPE_66:" + str(active66))
        required_sources = []
        for suffix in ("component_model_dist_vs_idp_summary.csv",
                       "component_model_dist_vs_idp.csv", "component_model_dist_baseline.csv"):
            exact_name = D11_PREFIX + suffix
            source = find_file_recursive(scratch, exact_name)
            if not source:
                decision["failures"].append("11D_REQUIRED_COMPONENT_CSV_MISSING:" + exact_name)
            else:
                required_sources.append(source)
        decision["passes"] = not decision["failures"]
        if not decision["passes"]:
            decision["status"] = "FAIL_IDP_OR_READ_ONLY"
        gate_source = scratch / "11D_15A2_COMPATIBILITY_GATE.json"
        write_json(gate_source, decision)

        # Compact durable mirror needed by downstream source loaders.
        mirror.mkdir(parents=True, exist_ok=True)
        summary_mirror = _copy_if_file(summary, mirror / summary.name)
        if tff_file:
            _copy_if_file(tff_file, mirror / tff_file.name)
        for source in required_sources:
            _copy_if_file(source, mirror / source.name)
        _copy_if_file(gate_source, mirror / gate_source.name)
        _mirror_helper_failure(scratch, mirror)
        evidence_zip = durable["archive"]
        _archive_helper_workspace(scratch, evidence_zip)
        write_json(mirror / "HELPER_WORKSPACE_POLICY.json", {
            "execution_workspace_policy": "SHORT_OS_TEMP",
            "execution_workspace_length": len(str(scratch)),
            "durable_mirror": str(mirror),
            "intended_mirror": str(durable["intended_mirror"]),
            "durable_mirror_mode": durable["mode"],
            "evidence_zip": str(evidence_zip),
            "reason": "WINDOWS_MAX_PATH_HARDENING_V2489",
        })
        if not decision["passes"]:
            raise RuntimeError("11D 15A2 compatibility gate failed: %s; inspect %s" %
                               (",".join(decision["failures"][:8]), mirror / "11D_15A2_COMPATIBILITY_GATE.json"))
        return {"summary": meta, "summary_path": str(summary_mirror), "idp_gate": decision,
                "helper_workspace_policy": "SHORT_OS_TEMP", "evidence_zip": str(evidence_zip)}
    except BaseException:
        try:
            _mirror_helper_failure(scratch, mirror)
            failed_zip = mirror.parent / (mirror.name + "_FAILED.zip")
            if not durable["archive"].is_file():
                _archive_helper_workspace(scratch, failed_zip)
        except Exception:
            pass
        raise
    finally:
        shutil.rmtree(str(scratch), ignore_errors=True)


def run_diagnostics(visum, out_dir, label, cfg):
    d12 = run_12d(visum, out_dir, label, cfg)
    d11 = run_11d(visum, out_dir, label, d12=d12, cfg=cfg)
    return d12, d11


# -----------------------------------------------------------------------------
# Official Visum saved-path export (15N-derived)
# -----------------------------------------------------------------------------

def get_lists_object(visum):
    try:
        return visum.Workbench.Lists, "Visum.Workbench.Lists"
    except Exception:
        return visum.Lists, "Visum.Lists"


def get_all_routes_filter():
    if win32com is not None:
        try:
            return getattr(win32com.client.constants, "routeFilter_filterAllRoutes"), "COM_ENUM"
        except Exception:
            pass
    return com.ALL_ROUTES, "PTV_2026_CREATEPRTPATHLIST_EXAMPLE_ENUM_0"


def list_dsegs(visum):
    rows = []
    for ds in get_all(visum.Net.DemandSegments):
        code = sval(att(ds, "CODE", "")).strip()
        if not code:
            continue
        matrix_no = ""; matrix_sum = None; matrix_code = ""
        try:
            matrix = ds.ODMatrix
            if matrix is not None:
                matrix_no = ival(att(matrix, "NO", None), "")
                matrix_sum = fval(att(matrix, "SUM", None), None)
                matrix_code = sval(att(matrix, "CODE", ""))
        except Exception:
            pass
        rows.append({
            "code": code, "norm_code": norm_code(code), "name": sval(att(ds, "NAME", "")),
            "mode": sval(att(ds, "MODE", "")), "object": ds,
            "matrix_no": matrix_no, "matrix_code": matrix_code, "matrix_sum": matrix_sum,
        })
    return rows


def selected_passenger_dsegs(visum, cfg):
    # Production default is an exact DSeg list.  Family discovery remains a
    # fallback for explicit research/diagnostic configurations, but a calibration
    # run must never silently add another DSeg merely because its code contains
    # CW/CS.
    explicit = [norm_code(x) for x in cfg.get("path_export_dsegs", []) if norm_code(x)]
    explicit_set = set(explicit)
    allowed_families = set(str(x).upper() for x in cfg.get("path_export_families", ["CW", "CS", "CL", "CF"]))
    include_exog = bool(cfg.get("include_exog_ee_paths", True))
    out = []
    for row in list_dsegs(visum):
        c = row["norm_code"]
        if explicit_set:
            if c in explicit_set:
                out.append(row)
            continue
        if not (c.startswith("NATIVE_") or (include_exog and c.startswith("EXOG_EE_"))):
            continue
        fam = ""
        for token in ("CW", "CS", "CL", "CF"):
            if c.endswith("_" + token) or ("_" + token + "_") in c:
                fam = token; break
        if fam in allowed_families:
            out.append(row)
    order = {code: idx for idx, code in enumerate(explicit)}
    out.sort(key=lambda r: (order.get(r["norm_code"], len(order)), r["norm_code"]))
    return out


def create_list(lists, name):
    return com.object_property(lists, name)


def add_list_columns(obj, key_headers, extras):
    # Add exact columns in explicit order. AddKeyColumns has a host-dependent
    # default schema; an equal column count alone does not prove key order.
    for col in key_headers:
        obj.AddColumn(col)
    failures = []
    for col in extras:
        try:
            obj.AddColumn(col)
        except Exception as exc:
            failures.append({"column": col, "error": compact_error(exc)})
    return "ExplicitVerifiedKeyColumns", failures


def set_list_objects(obj, dseg_row, all_routes):
    errors = []
    for arg in (dseg_row["code"], dseg_row.get("object")):
        if arg is None:
            continue
        try:
            obj.SetObjects(0, arg, all_routes)
            return True, ""
        except Exception as exc:
            errors.append(compact_error(exc))
    return False, " | ".join(errors)


def save_to_array(obj):
    value = obj.SaveToArray
    value = com.member_value(value)
    rows = []
    for row in ([] if value is None else value):
        if isinstance(row, (tuple, list)):
            rows.append(list(row))
        else:
            try:
                rows.append(list(row))
            except Exception:
                rows.append([row])
    return rows


def verified_bounded_signature(obj):
    """Return exact live Visum 2026 COM dispatch signature, never guess arguments."""
    ole = getattr(obj, "_oleobj_", None)
    if ole is None:
        raise RuntimeError("PRT_LIST_NO_OLE_TYPEINFO_FOR_BOUNDED_EXPORT")
    ti = ole.GetTypeInfo()
    ta = ti.GetTypeAttr()
    nfunc = int(ta.cFuncs if hasattr(ta, "cFuncs") else ta[8])
    for i in range(nfunc):
        desc = ti.GetFuncDesc(i)
        memid = int(desc.memid if hasattr(desc, "memid") else desc[0])
        names = [str(x) for x in ti.GetNames(memid)]
        if names and names[0].lower() == "savetoarray":
            if [x.lower() for x in names[1:3]] != ["firstobject", "lastobject"]:
                raise RuntimeError("PRT_BOUNDED_SAVE_TO_ARRAY_ARGUMENTS_UNVERIFIED:" + repr(names))
            kind = int(desc.invkind if hasattr(desc, "invkind") else desc[4])
            if kind not in (1, 2):
                raise RuntimeError("PRT_BOUNDED_SAVE_TO_ARRAY_INVKIND_UNVERIFIED:" + str(kind))
            return ole, memid, kind
    raise RuntimeError("PRT_BOUNDED_SAVE_TO_ARRAY_NOT_FOUND")


def iter_prt_pathlink_bounded(obj, headers, page_size=256, max_pages=500000,
                              require_verified=True, progress=None,
                              retry_policy=None, retry_progress=None):
    """One streaming iterator across pages so parent/child keys survive every boundary.

    Only bounded COM method confirmed by live 15P probe.  For tiny offline
    synthetic stubs without COM, tests may explicitly permit legacy iteration.
    No real COM runtime may silently fall back to a full unbounded read.
    """
    if page_size < 1 or max_pages < 1:
        raise RuntimeError("INVALID_PATHLINK_PAGE_BUDGET")
    try:
        ole, memid, kind = verified_bounded_signature(obj)
    except Exception:
        if require_verified:
            raise
        # Historical Python-only test stubs (not enabled by production config).
        for row in save_to_array(obj):
            if len(row) != len(headers):
                raise RuntimeError("PATHLINK_STUB_ROW_WIDTH_MISMATCH")
            yield row
        return
    first = 1
    pages = 0
    effective_page_size = int(page_size)
    fallback_applied = False
    while True:
        if pages >= int(max_pages):
            raise RuntimeError("PATHLINK_BOUNDED_PAGE_BUDGET_EXCEEDED")
        last = first + effective_page_size - 1
        def retry_observer(event):
            if retry_progress is not None:
                retry_progress(dict(event, first=first, last=last,
                                    page_size=effective_page_size, pages=pages))
        def exhausted_observer(event):
            if retry_progress is not None:
                retry_progress(dict(event, first=first, last=last,
                                    page_size=effective_page_size, pages=pages,
                                    com_retry_exhausted=True))
        try:
            raw = com.bounded_ole_invoke_with_retry(
                ole, memid, kind, first, last, retry_policy=retry_policy,
                label="PRT_PATHLINK_SAVE_TO_ARRAY", on_retry=retry_observer,
                on_exhausted=exhausted_observer)
        except Exception as exc:
            # RPC call rejection is a busy-host condition: bounded retry keeps
            # exactly the same page. It must never trigger pagination drift.
            if com.is_retryable_com_error(exc):
                raise
            if (effective_page_size > 80 and not fallback_applied and
                    com.is_bounded_page_size_error(exc)):
                effective_page_size = 80  # proven live in 15P; bounded only
                fallback_applied = True
                continue
            raise
        data = [] if raw is None else raw
        # Visum exposes a finite tuple of records, not a list of dictionaries.
        count = 0
        for row in data:
            values = list(row)
            if len(values) != len(headers):
                raise RuntimeError("PATHLINK_BOUNDED_ROW_WIDTH_MISMATCH")
            count += 1
            if count > effective_page_size:
                raise RuntimeError("PATHLINK_BOUNDED_PAGE_EXCEEDED_REQUEST")
            yield values
        pages += 1
        if progress is not None:
            progress(pages, first, count, effective_page_size)
        if count < effective_page_size:
            break
        first += count


def matrix_interzonal_authority(ds, expected_zones=None):
    """Read physical OD off-diagonal; never silently reinterpret matrix SUM."""
    if np is None:
        raise RuntimeError("NUMPY_REQUIRED_FOR_OFFDIAGONAL_PARITY")
    matrix = ds.get("object").ODMatrix
    a = np.asarray(matrix.GetValues(), dtype=float)
    if a.ndim != 2 or a.shape[0] != a.shape[1] or (expected_zones is not None
           and a.shape != (int(expected_zones), int(expected_zones))):
        raise RuntimeError("DSeg_OD_MATRIX_SHAPE_NOT_SQUARE_EXPECTED")
    if not np.isfinite(a).all() or np.any(a < 0):
        raise RuntimeError("DSeg_OD_MATRIX_INVALID_FINITE_NONNEGATIVE")
    total = float(np.sum(a, dtype=np.float64))
    declared = ds.get("matrix_sum")
    if declared is None or not math.isfinite(float(declared)):
        raise RuntimeError("DSeg_OD_MATRIX_SUM_UNREADABLE")
    if abs(total-float(declared)) > max(1.0e-6, abs(float(declared))*1.0e-8):
        raise RuntimeError("DSeg_OD_MATRIX_SUM_READBACK_MISMATCH")
    diagonal = float(np.trace(a, dtype=np.float64))
    return dict(total=total, diagonal=diagonal, interzonal=max(0.0, total-diagonal),
                matrix_size=int(a.shape[0]))


def open_stream_csv(path, fields):
    """Open a semicolon CSV writer without accumulating rows in memory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter=";", extrasaction="ignore")
    writer.writeheader()
    return handle, writer


def export_actual_paths_and_build_incidence(
    visum, out_dir, cfg, profiles, actuatable_zones,
    station_map=None, pair_authority=None, route_batch_callback=None, build_incidence=True,
):
    """Export official saved paths one DSeg at a time and build sparse incidence.

    A full R1 saved-path export can contain millions of path-link rows.  Keeping
    all selected demand segments in Python lists at once is unnecessary and can
    exhaust the Visum process.  This routine therefore:

      1. exports one DSeg path list and path-link list,
      2. streams the raw evidence to combined CSV files,
      3. immediately reduces the batch to compact sparse incidence,
      4. releases the raw rows before the next DSeg,
      5. merges only the compact per-DSeg incidence batches.

    No route is reconstructed; the source remains the official Visum PrT path
    and PrT path-link lists.  Every non-empty selected DSeg must export both
    lists successfully.  The routine is fail-closed even in design-only mode.
    """
    out_dir = Path(out_dir)
    lists, lists_source = get_lists_object(visum)
    all_routes, filter_source = get_all_routes_filter()
    dsegs = selected_passenger_dsegs(visum, cfg)
    if not dsegs:
        raise RuntimeError("No selected assignment-ready passenger demand segments found.")
    selected_codes = set(x["norm_code"] for x in dsegs)
    if len(selected_codes) != len(dsegs):
        raise RuntimeError("Duplicate selected DSeg codes")
    if cfg.get("require_all_path_export_dsegs", False):
        expected = {norm_code(x) for x in cfg.get("path_export_dsegs", [])}
        if expected != selected_codes:
            raise RuntimeError("Exact saved-path DSeg scope mismatch: missing=%s unexpected=%s" %
                               (sorted(expected-selected_codes), sorted(selected_codes-expected)))
    if not build_incidence and route_batch_callback is None:
        raise RuntimeError("Supply path export requires an actual-route collector")
    required_mutable = set(norm_code(x) for x in cfg.get("mutable_dsegs", []) if norm_code(x))
    missing_mutable = sorted(required_mutable - selected_codes)
    if missing_mutable:
        raise RuntimeError("Selected saved-path scope is missing mutable DSeg(s): %s" % ",".join(missing_mutable))

    path_fields = ["dseg_code"] + PATH_KEY_HEADERS + PATH_EXTRA_ATTRS
    pathlink_fields = ["dseg_code"] + PATHLINK_KEY_HEADERS + PATHLINK_EXTRA_ATTRS
    path_handle, path_writer = open_stream_csv(out_dir / "03_PRT_PATHS_ALL.csv", path_fields)
    link_handle, link_writer = open_stream_csv(out_dir / "04_PRT_PATHLINKS_ALL.csv", pathlink_fields)

    status_rows = []
    failures = []
    volume_parity_rows = []
    batches = []
    total_path_rows = 0
    total_link_rows = 0
    peak_batch_path_rows = 0
    peak_batch_pathlink_rows = 0
    selected_complete = 0
    selected_zero_matrix = 0
    fatal_errors = []

    station_map = station_map or {}
    pair_authority = pair_authority or []
    tol = float(cfg.get("dseg_path_volume_relative_tolerance", 0.01))
    zero_tol = float(cfg.get("zero_matrix_absolute_tolerance", 1.0e-9))

    try:
        for pos, ds in enumerate(dsegs, start=1):
            code = ds["code"]
            status = {
                "dseg_code": code,
                "norm_code": ds["norm_code"],
                "order": pos,
                "matrix_no": ds.get("matrix_no", ""),
                "matrix_code": ds.get("matrix_code", ""),
                "matrix_sum": ds.get("matrix_sum", ""),
                "path_rows": 0,
                "pathlink_rows": 0,
                "incidence_batch_variables": 0,
                "incidence_batch_nnz": 0,
                "complete": 0,
                "status": "STARTED",
            }
            path_rows_ds = []
            link_rows_ds = []
            path_error = ""
            link_error = ""

            # Official PrT path list for one DSeg.
            try:
                pl = create_list(lists, "CreatePrTPathList")
                ok, err = set_list_objects(pl, ds, all_routes)
                if not ok:
                    raise RuntimeError(err)
                mode, failed = add_list_columns(pl, PATH_KEY_HEADERS, PATH_EXTRA_ATTRS)
                failures.extend([dict(x, dseg_code=code, list="PrTPathList") for x in failed])
                arr = save_to_array(pl)
                missing_columns = {x["column"] for x in failed}
                if "Vol(AP)" in missing_columns:
                    raise RuntimeError("REQUIRED_PATH_VOLUME_COLUMN_UNAVAILABLE")
                headers = PATH_KEY_HEADERS + [x for x in PATH_EXTRA_ATTRS if x not in missing_columns]
                for values in com.validated_array_rows(arr, headers, PATH_KEY_HEADERS + ["Vol(AP)"]):
                    rec = dict({"dseg_code": code}, **values)
                    path_rows_ds.append(rec)
                    path_writer.writerow({k: rec.get(k, "") for k in path_fields})
                status["path_rows"] = len(path_rows_ds)
                status["path_key_mode"] = mode
                path_volume_sum = math.fsum(r["Vol(AP)"] for r in path_rows_ds)
                del arr
                try:
                    del pl
                except Exception:
                    pass
            except Exception as exc:
                path_volume_sum = 0.0
                path_error = compact_error(exc)
                status["path_error"] = path_error

            matrix_sum = ds.get("matrix_sum")
            matrix_sum_readable = matrix_sum is not None
            status["matrix_sum_readable"] = int(matrix_sum_readable)
            matrix_is_zero = matrix_sum_readable and abs(float(matrix_sum)) <= zero_tol
            try:
                mat_scope = matrix_interzonal_authority(ds, cfg.get("expected_zones"))
                inter_path = math.fsum(float(r["Vol(AP)"]) for r in path_rows_ds
                    if r["OrigZoneNo"] != r["DestZoneNo"])
                intra_path = math.fsum(float(r["Vol(AP)"]) for r in path_rows_ds
                    if r["OrigZoneNo"] == r["DestZoneNo"])
                reference = mat_scope["interzonal"]
                rel = abs(inter_path-reference)/max(1.0, abs(reference))
                volume_pass = (abs(inter_path) <= zero_tol if reference <= zero_tol else rel <= tol)
                status["matrix_interzonal_sum"] = reference
                status["matrix_intrazonal_sum"] = mat_scope["diagonal"]
                status["saved_path_interzonal_sum"] = inter_path
                status["saved_path_intrazonal_sum"] = intra_path
                matrix_error = ""
            except Exception as exc:
                mat_scope = None
                inter_path = intra_path = 0.0
                rel = None
                volume_pass = False
                matrix_error = compact_error(exc)
                status["matrix_interzonal_error"] = matrix_error
            volume_parity_rows.append({
                "dseg_code": code,
                "matrix_no": ds.get("matrix_no", ""),
                "matrix_code": ds.get("matrix_code", ""),
                "matrix_sum": matrix_sum,
                "matrix_diagonal_intra_zonal": "" if mat_scope is None else mat_scope["diagonal"],
                "matrix_interzonal_sum": "" if mat_scope is None else mat_scope["interzonal"],
                "saved_path_volume_sum": path_volume_sum,
                "saved_path_intrazonal_volume_sum": intra_path,
                "saved_path_interzonal_volume_sum": inter_path,
                "parity_basis": "INTERZONAL_ONLY_WITH_SAVED_PATH_DIAGONAL_EXCLUDED",
                "relative_abs_diff": "" if rel is None else rel,
                "passes": int(volume_pass and not path_error),
                "tolerance": tol,
                "matrix_is_zero": int(matrix_is_zero),
                "error": matrix_error,
            })

            if cfg.get("path_export_fail_fast", False) and (not volume_pass or path_error):
                status["status"] = "FAIL_EARLY_INTERZONAL_PARITY_OR_PATH_LIST"
                status["complete"] = 0
                fatal_errors.append("%s pathlist/parity rejected: %s; relative_diff=%s" %
                                    (code, path_error or matrix_error, rel))
                status_rows.append(status)
                total_path_rows += len(path_rows_ds)
                peak_batch_path_rows = max(peak_batch_path_rows, len(path_rows_ds))
                del path_rows_ds
                gc.collect()
                break

            # Official PrT path-link list; 15P established verified bounded COM pages.
            # On design-only V2.3.7 a streaming collector joins each route
            # immediately, keeping no entire-DSeg path-link array in memory.
            streamed_collector = None
            try:
                pll = create_list(lists, "CreatePrTPathLinkList")
                ok, err = set_list_objects(pll, ds, all_routes)
                if not ok:
                    raise RuntimeError(err)
                mode, failed = add_list_columns(pll, PATHLINK_KEY_HEADERS, PATHLINK_EXTRA_ATTRS)
                failures.extend([dict(x, dseg_code=code, list="PrTPathLinkList") for x in failed])
                if failed:
                    raise RuntimeError("REQUIRED_PATHLINK_COLUMNS_UNAVAILABLE:" + ",".join(x["column"] for x in failed))
                headers = PATHLINK_KEY_HEADERS + PATHLINK_EXTRA_ATTRS
                progress_file = out_dir / "04_PATHLINK_READ_PROGRESS.json"
                last_progress = [0.0]
                def checkpoint_progress(pages, first, count, size):
                    moment = time.monotonic()
                    if pages == 1 or moment-last_progress[0] > 15.0:
                        write_json(progress_file, {
                            "status": "READING_BOUNDED_PRTPATHLINK_LIST",
                            "dseg_code": code, "dseg_index": pos,
                            "dseg_total": len(dsegs), "pages": pages,
                            "raw_rows_at_least": first + count - 1,
                            "page_size": size,
                            "apply": False,
                        })
                        last_progress[0] = moment
                def checkpoint_retry(event):
                    moment = time.monotonic()
                    write_json(progress_file, {
                        "status": "RETRYING_TRANSIENT_COM_REJECTION",
                        "dseg_code": code, "dseg_index": pos,
                        "dseg_total": len(dsegs), "pages": event.get("pages"),
                        "raw_rows_at_least": int(event.get("first", 1)) - 1,
                        "page_size": event.get("page_size"),
                        "bounded_range_first": event.get("first"),
                        "bounded_range_last": event.get("last"),
                        "retry_attempt": event.get("attempt"),
                        "retry_next_attempt": event.get("next_attempt"),
                        "retry_max_attempts": event.get("max_attempts"),
                        "retry_delay_seconds": event.get("delay_seconds"),
                        "retry_hresult": event.get("hresult"),
                        "apply": False,
                    })
                    last_progress[0] = moment
                raw_pages = iter_prt_pathlink_bounded(
                    pll, headers,
                    page_size=int(cfg.get("pathlink_page_size", 256)),
                    max_pages=int(cfg.get("pathlink_max_pages", 500000)),
                    require_verified=bool(cfg.get("require_verified_bounded_pathlink_com", False)),
                    progress=checkpoint_progress,
                    retry_policy=cfg.get("com_resilience"),
                    retry_progress=checkpoint_retry)
                norm_links = com.normalized_prt_pathlink_rows(raw_pages, headers)
                status["pathlink_key_mode"] = mode
                status["bounded_pathlink_streaming"] = True
                status["pathlink_rows"] = 0
                def write_normalized_link_rows():
                    for values in norm_links:
                        rec = dict({"dseg_code": code}, **values)
                        link_writer.writerow({k: rec.get(k, "") for k in pathlink_fields})
                        status["pathlink_rows"] += 1
                        yield rec
                if not build_incidence and route_batch_callback is not None and (
                    hasattr(getattr(route_batch_callback, "__self__", None), "consume_stream")):
                    streamed_collector = route_batch_callback.__self__.consume_stream(
                        path_rows_ds, write_normalized_link_rows(), ds)
                else:
                    link_rows_ds.extend(write_normalized_link_rows())
                status["pathlink_rows"] = int(status["pathlink_rows"])
                try:
                    del pll
                except Exception:
                    pass
            except Exception as exc:
                link_error = compact_error(exc)
                status["pathlink_error"] = link_error

            total_path_rows += len(path_rows_ds)
            total_link_rows += int(status.get("pathlink_rows", len(link_rows_ds)))
            peak_batch_path_rows = max(peak_batch_path_rows, len(path_rows_ds))
            peak_batch_pathlink_rows = max(peak_batch_pathlink_rows, len(link_rows_ds))

            if streamed_collector is not None and not path_error and not link_error:
                status["actual_route_collector"] = streamed_collector
                status["incidence_batch_variables"] = 0
                status["incidence_batch_nnz"] = 0
                status["complete"] = 1
                status["status"] = "PASS_BOUNDED_STREAMED_AND_REDUCED"
                selected_complete += 1
            elif matrix_is_zero and not path_rows_ds and not link_rows_ds and not path_error and not link_error:
                # A truly empty DSeg contributes no incidence and does not need a
                # synthetic zero-column batch.
                status["complete"] = 1
                status["status"] = "PASS_ZERO_MATRIX_NO_SAVED_PATHS_EXPECTED"
                selected_complete += 1
                selected_zero_matrix += 1
            elif path_rows_ds and (link_rows_ds or (not build_incidence and all(
                    r.get("OrigZoneNo") == r.get("DestZoneNo") for r in path_rows_ds))) and not path_error and not link_error:
                try:
                    if route_batch_callback is not None:
                        status["actual_route_collector"] = route_batch_callback(path_rows_ds, link_rows_ds, ds)
                    local = build_actual_path_incidence(
                        path_rows_ds,
                        link_rows_ds,
                        profiles,
                        mutable_dsegs=cfg.get("mutable_dsegs"),
                        actuatable_zone_nos=actuatable_zones,
                        mutable_relation_policy=cfg.get("mutable_relation_policy", "BOTH_ENDPOINTS_ACTUATABLE"),
                        station_link_to_labels=station_map,
                        pair_authority=pair_authority,
                        skip_wiggly_pair_paths=bool(cfg.get("skip_wiggly_pair_paths", True)),
                    ) if build_incidence else {"variable_count": 0, "incidence_nnz": 0}
                    if build_incidence:
                        batches.append(local)
                    status["incidence_batch_variables"] = int(local.get("variable_count", 0) or 0)
                    status["incidence_batch_nnz"] = int(local.get("incidence_nnz", 0) or 0)
                    status["complete"] = 1
                    status["status"] = "PASS_EXPORTED_AND_REDUCED"
                    selected_complete += 1
                except Exception as exc:
                    status["status"] = "FAIL_INCIDENCE_REDUCTION"
                    status["incidence_error"] = compact_error(exc)
                    fatal_errors.append("%s incidence reduction: %s" % (code, compact_error(exc)))
            else:
                status["status"] = "FAIL_INCOMPLETE_SAVED_PATH_EXPORT"
                fatal_errors.append(
                    "%s path_rows=%d pathlink_rows=%d path_error=%s pathlink_error=%s" %
                    (code, len(path_rows_ds), int(status.get("pathlink_rows", len(link_rows_ds))), path_error, link_error)
                )

            if matrix_error:
                status["status"] = "FAIL_OFFDIAGONAL_MATRIX_AUTHORITY"
                status["complete"] = 0
                if streamed_collector is not None and selected_complete:
                    selected_complete -= 1
                fatal_errors.append("%s unreadable offdiagonal OD: %s" % (code, matrix_error))
            if cfg.get("require_dseg_matrix_sum", True) and not matrix_sum_readable:
                status["status"] = "FAIL_MATRIX_SUM_UNREADABLE"
                status["complete"] = 0
                if selected_complete > 0 and (matrix_is_zero or (path_rows_ds and link_rows_ds and not path_error and not link_error)):
                    selected_complete -= 1
                fatal_errors.append("%s ODMatrix.SUM is unreadable" % code)

            status_rows.append(status)
            # Release the raw batch before processing the next DSeg.
            del path_rows_ds
            del link_rows_ds
            gc.collect()
            if fatal_errors and bool(cfg.get("path_export_fail_fast", False)):
                break

    finally:
        path_handle.close()
        link_handle.close()

    write_csv(out_dir / "03B_DSEG_PATH_EXPORT_STATUS.csv", status_rows)
    write_csv(out_dir / "03C_PATH_COLUMN_FAILURES.csv", failures)
    write_csv(out_dir / "03D_DSEG_PATH_VOLUME_PARITY.csv", volume_parity_rows)

    dseg_volume_parity_passes = (
        len(volume_parity_rows) == len(dsegs)
        and bool(volume_parity_rows)
        and all(int(r.get("passes", 0) or 0) == 1 for r in volume_parity_rows)
    )
    all_selected_complete = selected_complete == len(dsegs)
    summary = {
        "lists_source": lists_source,
        "route_filter_source": filter_source,
        "dseg_count": len(dsegs),
        "dseg_complete_count": selected_complete,
        "dseg_zero_matrix_count": selected_zero_matrix,
        "all_selected_dsegs_complete": all_selected_complete,
        "path_rows": total_path_rows,
        "pathlink_rows": total_link_rows,
        "peak_batch_path_rows": peak_batch_path_rows,
        "peak_batch_pathlink_rows": peak_batch_pathlink_rows,
        "memory_strategy": "BOUNDED_COM_PAGES_ROUTE_JOIN_STREAM_SQLITE_FOR_DESIGN_ONLY",
        "volume_parity_basis": "OFFDIAGONAL_INTERZONAL",
        "incidence_batch_count": len(batches),
        "dsegs": [x["code"] for x in dsegs],
        "dseg_path_volume_parity_passes": dseg_volume_parity_passes,
        "dseg_path_volume_parity_rows": len(volume_parity_rows),
        "fatal_errors": fatal_errors,
    }

    if fatal_errors or not all_selected_complete:
        summary["status"] = "FAIL_INCOMPLETE_SELECTED_DSEG_PATH_AUTHORITY"
        write_json(out_dir / "03A_PATH_EXPORT_SUMMARY.json", summary)
        raise RuntimeError(
            "Incomplete official saved-path authority for selected DSegs: %s" %
            (" | ".join(fatal_errors) if fatal_errors else "completion count mismatch")
        )
    if not build_incidence:
        if not dseg_volume_parity_passes:
            summary["status"] = "FAIL_DSEG_PATH_VOLUME_PARITY"
            write_json(out_dir / "03A_PATH_EXPORT_SUMMARY.json", summary)
            raise RuntimeError("Supply saved paths do not reconstruct DSeg matrix totals")
        summary["status"] = "PASS_EXPORTED_TO_ACTUAL_ROUTE_COLLECTOR"
        write_json(out_dir / "03A_PATH_EXPORT_SUMMARY.json", summary)
        return None, summary
    if not batches:
        summary["status"] = "FAIL_NO_NONZERO_SAVED_PATH_BATCHES"
        write_json(out_dir / "03A_PATH_EXPORT_SUMMARY.json", summary)
        raise RuntimeError(
            "No non-empty official saved PrT path/path-link batch. Re-run assignment with Storage of paths = Save as routes."
        )

    try:
        incidence = merge_actual_path_incidence_batches(batches)
    except Exception as exc:
        summary["status"] = "FAIL_SPARSE_BATCH_MERGE"
        summary["merge_error"] = compact_error(exc)
        write_json(out_dir / "03A_PATH_EXPORT_SUMMARY.json", summary)
        raise
    summary.update({
        "status": "PASS_EXPORTED_REDUCED_AND_MERGED",
        "merged_variable_count": int(incidence.get("variable_count", 0) or 0),
        "merged_projection_base_variable_count": int(incidence.get("projection_base_variable_count", 0) or 0),
        "merged_incidence_nnz": int(incidence.get("incidence_nnz", 0) or 0),
        "merged_path_link_coverage": float(incidence.get("path_link_coverage", 0.0) or 0.0),
        "merged_path_link_volume_coverage": float(incidence.get("path_link_volume_coverage", 0.0) or 0.0),
    })
    write_json(out_dir / "03A_PATH_EXPORT_SUMMARY.json", summary)
    return incidence, summary


# -----------------------------------------------------------------------------
# Optional 15L station-pair authority
# -----------------------------------------------------------------------------

def load_kordon_inputs(cfg):
    if not cfg.get("enable_kordon_pairs", False):
        return {}, []
    mapping_path = Path(cfg.get("kordon_mapping_csv", ""))
    authority_path = Path(cfg.get("kordon_authority_csv", ""))
    if not mapping_path.is_absolute():
        mapping_path = script_dir() / mapping_path
    if not authority_path.is_absolute():
        authority_path = script_dir() / authority_path
    if not mapping_path.is_file() or not authority_path.is_file():
        raise RuntimeError("Kordon pair mode enabled but mapping/authority files are missing.")
    station_map = defaultdict(list)
    for row in read_csv_auto(mapping_path):
        key = (ival(row.get("link_no"), None), ival(row.get("from_node_no"), None), ival(row.get("to_node_no"), None))
        label = sval(row.get("station_label", "")).strip().upper()
        if None not in key and label:
            station_map[key].append(label)
    authority = []
    role = sval(cfg.get("kordon_pair_role", "DIAGNOSTIC")).upper()
    for row in read_csv_auto(authority_path):
        if ival(row.get("use_as_primary_station_od_target"), 0) != 1:
            continue
        if sval(row.get("category", "")).upper() != sval(cfg.get("kordon_category", "OA")).upper():
            continue
        if ival(row.get("is_virtual_c17"), 0) == 1:
            continue
        o = sval(row.get("origin_label", "")).upper(); d = sval(row.get("destination_label", "")).upper()
        if not o or not d or o == d:
            continue
        rr = dict(row); rr["role"] = role
        authority.append(rr)
    return dict(station_map), authority


# -----------------------------------------------------------------------------
# Procedure and candidate write gates
# -----------------------------------------------------------------------------

def proc_bool(value):
    s = sval(value).strip().lower()
    if s in ("1", "true", "yes", "y", "active", "aktiv", "ano", "x", "checked"):
        return True
    if s in ("0", "false", "no", "n", "inactive", "ne", "", "none"):
        return False
    try:
        return float(s.replace(",", ".")) != 0.0
    except Exception:
        return False


def audit_procseq(visum, out_dir, cfg):
    rows = []
    ops = get_all(visum.Procedures.Operations)
    for idx, op in enumerate(ops, start=1):
        vals = {}
        for name in PROCSEQ_CORE_ATTRS:
            value = att(op, name, None)
            if value not in (None, ""):
                vals.setdefault(name.upper(), value)
        active = com.active_bool(vals.get("ACTIVE", ""))
        text = " ".join(sval(x) for x in vals.values()).upper()
        compact = re.sub(r"[^A-Z0-9_]+", "", text)
        operation_type_int = com.exact_int(vals.get("OPERATIONTYPE"), "OPERATIONTYPE")
        is_tg = operation_type_int == com.TG
        is_td = operation_type_int == com.TD
        is_assignment = operation_type_int == com.ASSIGNMENT_PRT
        is_master = "15A2" in compact or SCRIPT_ID.replace("_", "") in compact
        rows.append({
            "seq_index": idx, "active": int(active), "operation_type": operation_type_int if operation_type_int is not None else "", "text": text[:1500],
            "is_tg": int(active and is_tg), "is_td": int(active and is_td),
            "is_assignment": int(active and is_assignment), "is_recursive_master": int(active and is_master),
        })
    write_csv(Path(out_dir) / "00_PROCSEQ_AUDIT.csv", rows)
    result = {
        "readable": bool(rows),
        "active_tg": sum(r["is_tg"] for r in rows),
        "active_td": sum(r["is_td"] for r in rows),
        "active_assignment": sum(r["is_assignment"] for r in rows),
        "recursive_master": sum(r["is_recursive_master"] for r in rows),
    }
    tg_idx = [r["seq_index"] for r in rows if r["is_tg"]]
    td_idx = [r["seq_index"] for r in rows if r["is_td"]]
    asg_idx = [r["seq_index"] for r in rows if r["is_assignment"]]
    result["tg_indices"] = tg_idx
    result["td_indices"] = td_idx
    result["assignment_indices"] = asg_idx
    result["tg_before_td"] = bool(any(t < d for t in tg_idx for d in td_idx))
    result["assignment_after_td"] = bool(any(a > d for a in asg_idx for d in td_idx))
    reasons = []
    if cfg.get("require_active_tg_td", True) and result["active_tg"] <= 0:
        reasons.append("NO_ACTIVE_TRIP_GENERATION")
    if cfg.get("require_active_tg_td", True) and result["active_td"] <= 0:
        reasons.append("NO_ACTIVE_TRIP_DISTRIBUTION")
    if cfg.get("require_active_assignment", True) and result["active_assignment"] <= 0:
        reasons.append("NO_ACTIVE_ASSIGNMENT")
    if cfg.get("require_active_tg_td", True) and tg_idx and td_idx and not result["tg_before_td"]:
        reasons.append("NO_TRIP_GENERATION_BEFORE_TRIP_DISTRIBUTION")
    if cfg.get("require_active_assignment", True) and td_idx and asg_idx and not result["assignment_after_td"]:
        reasons.append("NO_ASSIGNMENT_AFTER_TRIP_DISTRIBUTION")
    if result["recursive_master"] > 0:
        reasons.append("MASTER_IS_ACTIVE_INSIDE_PROCSEQ")
    result["passes"] = not reasons
    result["reasons"] = reasons
    write_json(Path(out_dir) / "00_PROCSEQ_AUDIT_SUMMARY.json", result)
    return result


def build_add_candidate(visum, projection_rows, zone_nos, scale, cfg, actuatable_zone_nos=None):
    preserve_zero = bool(cfg.get("preserve_zero_add", True))
    authority = cfg.get("generation_coefficient_authority", {}) or {}
    live_authority = (authority.get("enabled") is True and
                      sval(authority.get("mode", "")).upper() ==
                      "LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP")
    add_min = float(authority.get("multiplicative_minimum", 0.0)) if live_authority else float(cfg.get("add_min", 0.0))
    add_max = float("inf") if live_authority else float(cfg.get("add_max", 3.0))
    min_step = float(cfg.get("min_add_log_step", 1.0e-5))
    max_changes = int(cfg.get("max_zone_attribute_changes", 0))
    actuatable_set = None if actuatable_zone_nos is None else set(int(x) for x in actuatable_zone_nos)
    current_by_attr = {}
    for attr_name in sorted(set(ADD_ATTR_MAP.values())):
        current_by_attr[attr_name] = read_zone_attr(visum, attr_name, zone_nos)
    zone_idx = {z: i for i, z in enumerate(zone_nos)}
    rows = []
    for p in projection_rows:
        key = (sval(p.get("family")).upper(), sval(p.get("role")).upper())
        attr_name = ADD_ATTR_MAP.get(key)
        z = ival(p.get("zone_no"), None)
        if not attr_name or z not in zone_idx:
            continue
        if actuatable_set is not None and int(z) not in actuatable_set:
            raise RuntimeError("Projection attempted to write protected/non-actuatable Zone.NO=%s" % z)
        log_step = float(p.get("log_step", 0.0) or 0.0) * float(scale)
        if abs(log_step) < min_step:
            continue
        cur = float(current_by_attr[attr_name][zone_idx[z]])
        if preserve_zero and abs(cur) <= 1.0e-12:
            continue
        proposed = max(add_min, min(add_max, cur * math.exp(log_step)))
        if not math.isfinite(proposed):
            raise RuntimeError("NONFINITE_LIVE_GENERATION_COEFFICIENT:%s:%s" % (attr_name, z))
        if proposed < 0.0:
            raise RuntimeError("NEGATIVE_LIVE_GENERATION_COEFFICIENT:%s:%s" % (attr_name, z))
        if abs(proposed - cur) <= 1.0e-12:
            continue
        rows.append({
            "zone_no": z, "family": key[0], "role": key[1], "attr": attr_name,
            "current": cur, "log_step_full": float(p.get("log_step", 0.0) or 0.0),
            "attempt_scale": float(scale), "log_step_applied": log_step,
            "multiplier": math.exp(log_step), "proposed": proposed, "delta": proposed - cur,
            "coefficient_authority": ("LIVE_CURRENT_VALUE_RELATIVE_LOG_STEP"
                                      if live_authority else "LEGACY_ABSOLUTE_BOUNDS"),
        })
    rows.sort(key=lambda r: abs(r["log_step_applied"]), reverse=True)
    if max_changes > 0 and len(rows) > max_changes:
        raise RuntimeError(
            "ADD candidate has %d writes, above fail-closed max_zone_attribute_changes=%d; "
            "do not silently truncate a balanced P/A projection" % (len(rows), max_changes)
        )
    return rows, current_by_attr


def apply_add_candidate(visum, candidate_rows, zone_nos, zone_indices=None,
                        retry_policy=None, readback_tolerance=1.0e-7):
    by_attr = defaultdict(dict)
    for row in candidate_rows:
        by_attr[row["attr"]][int(row["zone_no"])] = float(row["proposed"])
    audit = []
    for attr_name, changes in sorted(by_attr.items()):
        before = read_zone_attr(
            visum, attr_name, zone_nos, zone_indices=zone_indices,
            retry_policy=retry_policy)
        after_target = list(before)
        idx = {z: i for i, z in enumerate(zone_nos)}
        for z, value in changes.items():
            after_target[idx[z]] = value
        after = write_zone_attr(
            visum, attr_name, zone_nos, after_target, zone_indices=zone_indices,
            retry_policy=retry_policy, readback_tolerance=readback_tolerance)
        for z, value in changes.items():
            i = idx[z]
            audit.append({
                "zone_no": z, "attr": attr_name, "before": before[i],
                "target": value, "after_readback": after[i],
                "abs_error": abs(after[i] - value),
                "status": "OK" if abs(after[i] - value) <= readback_tolerance else "READBACK_MISMATCH",
            })
    return audit


def verify_add_candidate_persistence(visum, candidate_rows, zone_nos,
                                     zone_indices=None, retry_policy=None,
                                     readback_tolerance=1.0e-7):
    """Verify that no later Procedure Sequence operation overwrote ADD writes."""
    idx = {z: i for i, z in enumerate(zone_nos)}
    by_attr = defaultdict(list)
    for row in candidate_rows:
        by_attr[row["attr"]].append(row)
    audit = []
    for attr_name, rows in sorted(by_attr.items()):
        values = read_zone_attr(
            visum, attr_name, zone_nos, zone_indices=zone_indices,
            retry_policy=retry_policy)
        for row in rows:
            z = int(row["zone_no"])
            target = float(row["proposed"])
            got = float(values[idx[z]])
            err = abs(got - target)
            audit.append({
                "zone_no": z, "attr": attr_name, "target": target,
                "after_procseq": got, "abs_error": err,
                "status": "OK" if err <= readback_tolerance else "OVERWRITTEN_OR_CHANGED",
            })
    return audit


def mutable_matrix_fingerprints(visum, cfg):
    """Read deterministic fingerprints of the mutable assignment-ready OD matrices."""
    if np is None:
        raise RuntimeError("NumPy is required for mutable OD matrix fingerprinting")
    wanted = set(norm_code(x) for x in cfg.get("mutable_dsegs", []))
    rows = []
    for ds in list_dsegs(visum):
        if ds["norm_code"] not in wanted:
            continue
        obj = ds.get("object")
        try:
            mat = obj.ODMatrix
            values = mat.GetValues()
            arr = np.asarray(values, dtype="<f8")
            if arr.ndim != 2:
                raise RuntimeError("matrix array is not 2D: shape=%r" % (arr.shape,))
            contiguous = np.ascontiguousarray(arr, dtype="<f8")
            digest = hashlib.sha256(contiguous.tobytes(order="C")).hexdigest()
            rows.append({
                "dseg_code": ds["code"], "norm_code": ds["norm_code"],
                "matrix_no": ival(att(mat, "NO", None), ""),
                "matrix_code": sval(att(mat, "CODE", "")),
                "rows": int(contiguous.shape[0]), "cols": int(contiguous.shape[1]),
                "sum": float(np.sum(contiguous)),
                "nonzero": int(np.count_nonzero(contiguous)),
                "sha256_float64_le": digest,
                "status": "OK",
            })
        except Exception as exc:
            rows.append({
                "dseg_code": ds["code"], "norm_code": ds["norm_code"],
                "matrix_no": ds.get("matrix_no", ""), "matrix_code": ds.get("matrix_code", ""),
                "status": "FAILED", "error": compact_error(exc),
            })
    return rows


def compare_matrix_fingerprints(before_rows, after_rows):
    bmap = {r.get("norm_code"): r for r in before_rows if r.get("norm_code")}
    amap = {r.get("norm_code"): r for r in after_rows if r.get("norm_code")}
    rows = []
    for code in sorted(set(bmap) | set(amap)):
        b = bmap.get(code, {}); a = amap.get(code, {})
        same = bool(
            b.get("status") == "OK" and a.get("status") == "OK"
            and b.get("sha256_float64_le") == a.get("sha256_float64_le")
        )
        rows.append({
            "norm_code": code,
            "before_status": b.get("status", "MISSING"), "after_status": a.get("status", "MISSING"),
            "before_matrix_no": b.get("matrix_no", ""), "after_matrix_no": a.get("matrix_no", ""),
            "before_sum": b.get("sum", ""), "after_sum": a.get("sum", ""),
            "before_sha256": b.get("sha256_float64_le", ""),
            "after_sha256": a.get("sha256_float64_le", ""),
            "changed": int(not same),
        })
    return rows


def execute_procseq(visum, out_dir):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    with (Path(out_dir) / "20_PROCSEQ_EXECUTION.txt").open("a", encoding="utf-8") as f:
        f.write("%s START Visum.Procedures.Execute()\n" % now_iso())
    visum.Procedures.Execute()
    with (Path(out_dir) / "20_PROCSEQ_EXECUTION.txt").open("a", encoding="utf-8") as f:
        f.write("%s END Visum.Procedures.Execute()\n" % now_iso())


def guidance_rows(problem, result):
    out = []
    for meta, value in zip(problem.variable_meta, result.x.tolist()):
        row = dict(meta)
        row.update({
            "relative_od_guidance": float(value),
            "absolute_od_guidance": float(value) * float(meta.get("q_current", 0.0) or 0.0),
            "active": int(abs(float(value)) > 1.0e-10),
        })
        out.append(row)
    out.sort(key=lambda r: abs(r["absolute_od_guidance"]), reverse=True)
    return out


def objective_rows_with_fit(problem, result):
    out = []
    for row, pred, rem in zip(problem.objective_rows, result.predicted_change.tolist(), result.residual_after_linear.tolist()):
        rr = dict(row)
        rr["predicted_flow_change"] = float(pred)
        rr["target_minus_predicted"] = float(rem)
        out.append(rr)
    return out


def release_heavy_references():
    gc.collect()


# -----------------------------------------------------------------------------
# Main guarded loop
# -----------------------------------------------------------------------------

def main():
    cfg = load_config()
    root = script_dir() / OUT_ROOT_NAME
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / ("run_" + stamp())
    run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(str(script_dir() / CONFIG_NAME), str(run_dir / CONFIG_NAME))
    summary = {
        "script_id": SCRIPT_ID,
        "started_at": now_iso(),
        "run_dir": str(run_dir),
        "config": cfg,
        "status": "STARTED",
        "iterations": [],
        "method_contract": {
            "incidence_source": "OFFICIAL_VISUM_SAVED_PRT_PATH_AND_PATHLINK_LISTS",
            "od_solution_is_guidance_only": True,
            "direct_od_matrix_write": False,
            "candidate_actuators": sorted(set(ADD_ATTR_MAP.values())),
            "validation_used_for_design_or_acceptance": False,
        },
    }
    visum = None
    try:
        log_line(run_dir, "START %s" % SCRIPT_ID)
        visum, connection = get_visum()
        summary["connection"] = connection
        if cfg.get("apply", False) and not cfg.get("run_procseq", True):
            raise RuntimeError("APPLY requires RUN_PROCSEQ=1; ADD changes must be evaluated through fresh TG -> TD -> assignment.")
        if (
            cfg.get("apply", False)
            and sval(cfg.get("guidance_mode", "POSITIVE_ONLY")).strip().upper() == "SIGNED"
            and not cfg.get("allow_signed_apply", False)
        ):
            raise RuntimeError("SIGNED guidance is research-only in V1.0; set allow_signed_apply=true only after a dedicated P/A balance gate is validated.")
        zones = zone_numbers(visum)
        summary["zone_count"] = len(zones)
        actuatable_zones, actuator_scope = resolve_actuator_zone_scope(zones, cfg, run_dir)
        summary["zone_actuator_scope"] = actuator_scope
        proc = audit_procseq(visum, run_dir, cfg)
        if cfg.get("apply", False) and not proc.get("passes", False):
            raise RuntimeError("Procedure Sequence gate failed: %s" % proc.get("reasons"))
        station_map, pair_authority = load_kordon_inputs(cfg)
        summary["kordon_pair_mode"] = {
            "enabled": bool(cfg.get("enable_kordon_pairs", False)),
            "station_link_keys": len(station_map),
            "authority_rows": len(pair_authority),
            "role": cfg.get("kordon_pair_role", "DIAGNOSTIC"),
        }

        baseline_12d = None
        baseline_11d = None
        max_iter = max(1, int(cfg.get("max_accepted_iterations", 1)))
        accepted_count = 0
        for iteration in range(1, max_iter + 1):
            iter_dir = run_dir / ("ITER_%02d" % iteration)
            iter_dir.mkdir(parents=True, exist_ok=False)
            log_line(run_dir, "Iteration %d baseline diagnostics" % iteration)
            if baseline_12d is None or baseline_11d is None:
                baseline_12d, baseline_11d = run_diagnostics(visum, iter_dir, "BEFORE", cfg)
            else:
                # Persist a compact copy of carried accepted diagnostics.
                write_json(iter_dir / "00_CARRIED_BASELINE.json", {"from_previous_accepted_iteration": True})
            profiles = baseline_12d["rows"]
            incidence, path_export_summary = export_actual_paths_and_build_incidence(
                visum, iter_dir, cfg, profiles, actuatable_zones,
                station_map=station_map, pair_authority=pair_authority,
            )
            write_json(iter_dir / "05_INCIDENCE_SUMMARY.json", {
                k: v for k, v in incidence.items() if k not in (
                    "profiles", "variables", "projection_base_variables", "q_current", "incidence", "incidence_share",
                    "incidence_through", "full_profile_model_from_paths", "native_ws_profile_model_from_paths",
                    "mutable_profile_model_from_paths", "pair_observations",
                )
            })
            write_csv(iter_dir / "05A_VARIABLE_CATALOG.csv", incidence["variables"])
            write_csv(iter_dir / "05AA_PROJECTION_BASE_VARIABLE_CATALOG.csv", incidence["projection_base_variables"])
            path_scope_model_fields = ["model_" + sval(code) for code in path_export_summary.get("dsegs", [])]
            parity = path_parity_rows(
                profiles,
                incidence["full_profile_model_from_paths"],
                model_fields=path_scope_model_fields,
            )
            parity_summary = summarize_path_parity(parity, cfg)
            write_csv(iter_dir / "05B_PATH_VS_12D_PARITY.csv", parity)
            write_json(iter_dir / "05C_PATH_PARITY_SUMMARY.json", parity_summary)
            coverage_ok = float(incidence.get("path_link_coverage", 0.0)) >= float(cfg.get("min_path_link_coverage", 0.98))
            volume_coverage_ok = float(incidence.get("path_link_volume_coverage", 0.0)) >= float(cfg.get("min_path_link_volume_coverage", 0.995))
            dseg_volume_parity_ok = bool(path_export_summary.get("dseg_path_volume_parity_passes", False))
            if cfg.get("apply", False) and cfg.get("require_path_parity_for_apply", True):
                if not coverage_ok or not volume_coverage_ok or not parity_summary.get("passes", False):
                    raise RuntimeError(
                        "Saved-path authority gate failed: count_coverage=%s volume_coverage=%s parity=%s" %
                        (incidence.get("path_link_coverage"), incidence.get("path_link_volume_coverage"), parity_summary)
                    )
            if cfg.get("apply", False) and cfg.get("require_dseg_path_volume_parity_for_apply", True) and not dseg_volume_parity_ok:
                raise RuntimeError("DSeg saved-path volume totals do not match assigned OD matrix totals; inspect 03D_DSEG_PATH_VOLUME_PARITY.csv")

            problem = prepare_guidance_problem(incidence, cfg, include_pair_observations=bool(cfg.get("enable_kordon_pairs", False)))
            result = solve_guidance(problem, cfg)
            projection = project_guidance_to_add(
                problem, result, zones, cfg,
                all_variable_meta=incidence["projection_base_variables"],
            )
            write_csv(iter_dir / "06_OBJECTIVE_ROWS_LINEAR_FIT.csv", objective_rows_with_fit(problem, result))
            write_csv(iter_dir / "06B_DROPPED_OBJECTIVE_ROWS.csv", problem.dropped_objective_rows)
            write_json(iter_dir / "06C_SELECTION_SUMMARY.json", problem.selection_summary)
            write_csv(iter_dir / "07_OD_GUIDANCE.csv", guidance_rows(problem, result))
            write_csv(iter_dir / "08_ADD_PROJECTION.csv", projection.rows)
            write_csv(iter_dir / "08B_ADD_PROJECTION_FAMILY_SUMMARY.csv", projection.family_summaries)
            write_json(iter_dir / "07B_SOLVER_SUMMARY.json", {
                "objective_initial": result.objective_initial,
                "objective_final": result.objective_final,
                "iterations": result.iterations,
                "converged": result.converged,
                "lipschitz": result.lipschitz,
                "nonzero_guidance": int(sum(abs(float(x)) > 1.0e-10 for x in result.x.tolist())),
                "projection_weighted_rmse": projection.weighted_rmse,
                "projection_method": cfg.get("projection_method", "MARGINALS"),
                "projection_all_converged": all(bool(r.get("converged", False)) for r in projection.family_summaries) if projection.family_summaries else False,
                "history": result.history,
            })

            iter_summary = {
                "iteration": iteration,
                "path_export": path_export_summary,
                "path_link_coverage": incidence.get("path_link_coverage"),
                "path_link_volume_coverage": incidence.get("path_link_volume_coverage"),
                "dseg_path_volume_parity": dseg_volume_parity_ok,
                "path_scope_model_fields": path_scope_model_fields,
                "path_parity": parity_summary,
                "solver_objective_initial": result.objective_initial,
                "solver_objective_final": result.objective_final,
                "solver_converged": result.converged,
                "projection_rows": len(projection.rows),
                "selection_summary": problem.selection_summary,
                "status": "DESIGNED",
                "attempts": [],
            }
            summary["iterations"].append(iter_summary)

            if not cfg.get("apply", False):
                iter_summary["status"] = "PASS_DESIGN_ONLY"
                summary["status"] = "PASS_DESIGN_ONLY"
                break
            if cfg.get("require_solver_convergence_for_apply", True) and not result.converged:
                raise RuntimeError("Guidance solver did not converge; no APPLY is permitted.")
            if cfg.get("require_projection_convergence_for_apply", True):
                if not projection.family_summaries or not all(bool(r.get("converged", False)) for r in projection.family_summaries):
                    raise RuntimeError("P/A projection did not converge for every active family; no APPLY is permitted.")
            max_pa_gap = float(cfg.get("max_projected_pa_total_abs_gap", 1.0e-6))
            bad_pa_balance = [
                r for r in projection.family_summaries
                if float(r.get("projected_pa_total_abs_gap", 0.0) or 0.0) > max_pa_gap
            ]
            if bad_pa_balance:
                raise RuntimeError("Projected production/attraction totals are not balanced within tolerance; no APPLY is permitted.")
            if not projection.rows:
                iter_summary["status"] = "STOP_NO_ADD_PROJECTION"
                summary["status"] = "STOP_NO_ADD_PROJECTION"
                break

            pre_checkpoint = save_version(visum, iter_dir / "PRE.ver")
            iter_summary["pre_checkpoint"] = pre_checkpoint
            pre_matrix_fp = mutable_matrix_fingerprints(visum, cfg)
            write_csv(iter_dir / "09D_MUTABLE_MATRIX_FINGERPRINT_BEFORE.csv", pre_matrix_fp)
            if any(r.get("status") != "OK" for r in pre_matrix_fp):
                raise RuntimeError("Could not fingerprint all mutable OD matrices before APPLY")
            accepted_this_iteration = False
            scales = list(cfg.get("backtracking_scales", [1.0, 0.5, 0.25]))
            for attempt_no, scale in enumerate(scales, start=1):
                attempt_dir = iter_dir / ("ATTEMPT_%02d_SCALE_%s" % (attempt_no, str(scale).replace(".", "p")))
                attempt_dir.mkdir(parents=True, exist_ok=False)
                candidate, _curr = build_add_candidate(
                    visum, projection.rows, zones, float(scale), cfg,
                    actuatable_zone_nos=actuatable_zones,
                )
                write_csv(attempt_dir / "09_ADD_CANDIDATE.csv", candidate)
                attempt_summary = {"attempt": attempt_no, "scale": float(scale), "candidate_rows": len(candidate), "status": "STARTED"}
                iter_summary["attempts"].append(attempt_summary)
                if not candidate:
                    attempt_summary["status"] = "NO_EFFECTIVE_CANDIDATE"
                    continue
                try:
                    audit = apply_add_candidate(visum, candidate, zones)
                    write_csv(attempt_dir / "09B_ADD_APPLY_AUDIT.csv", audit)
                    bad = [r for r in audit if r.get("status") != "OK"]
                    if bad:
                        raise RuntimeError("ADD readback mismatch rows=%d" % len(bad))
                    if cfg.get("run_procseq", True):
                        execute_procseq(visum, attempt_dir)
                    persistence = verify_add_candidate_persistence(visum, candidate, zones)
                    write_csv(attempt_dir / "09C_ADD_POST_PROCSEQ_READBACK.csv", persistence)
                    if cfg.get("require_add_persistence_after_procseq", True):
                        overwritten = [r for r in persistence if r.get("status") != "OK"]
                        if overwritten:
                            raise RuntimeError("Procedure Sequence overwrote or changed %d ADD values" % len(overwritten))
                    post_matrix_fp = mutable_matrix_fingerprints(visum, cfg)
                    write_csv(attempt_dir / "09D_MUTABLE_MATRIX_FINGERPRINT_AFTER.csv", post_matrix_fp)
                    matrix_compare = compare_matrix_fingerprints(pre_matrix_fp, post_matrix_fp)
                    write_csv(attempt_dir / "09E_MUTABLE_MATRIX_CHANGE.csv", matrix_compare)
                    changed_n = sum(int(r.get("changed", 0) or 0) for r in matrix_compare)
                    if cfg.get("require_mutable_matrix_change_for_apply", True) and changed_n <= 0:
                        raise RuntimeError("ADD candidate did not change any mutable OD matrix after Procedure Sequence")
                    after_12d, after_11d = run_diagnostics(visum, attempt_dir, "AFTER", cfg)
                    decision = acceptance_decision(
                        baseline_12d["rows"], after_12d["rows"],
                        baseline_11d["summary"], after_11d["summary"], cfg,
                    )
                    write_json(attempt_dir / "10_ACCEPTANCE.json", decision)
                    attempt_summary["acceptance"] = decision
                    attempt_summary["mutable_matrix_changed_count"] = changed_n
                    if decision.get("accepted", False):
                        accepted = save_version(visum, attempt_dir / "ACCEPTED.ver")
                        attempt_summary["accepted_checkpoint"] = accepted
                        attempt_summary["status"] = "ACCEPTED"
                        iter_summary["status"] = "ACCEPTED"
                        accepted_this_iteration = True
                        accepted_count += 1
                        baseline_12d, baseline_11d = after_12d, after_11d
                        # Fresh official paths are exported at the beginning of the next iteration.
                        break
                    attempt_summary["status"] = "REJECTED"
                except Exception as exc:
                    attempt_summary["status"] = "FAILED"
                    attempt_summary["error"] = compact_error(exc)
                    with (attempt_dir / "99_TRACEBACK.txt").open("w", encoding="utf-8") as f:
                        f.write(traceback.format_exc())
                # Reject/failure: exact rollback before a smaller trust-region step.
                release_heavy_references()
                load_version(visum, pre_checkpoint["path"])
                attempt_summary["rolled_back_to"] = pre_checkpoint["path"]
                visum, _connection = get_visum()
                zones = zone_numbers(visum)

            if not accepted_this_iteration:
                iter_summary["status"] = "STOP_ALL_BACKTRACKING_ATTEMPTS_REJECTED"
                summary["status"] = iter_summary["status"]
                break
            summary["status"] = "PASS_ACCEPTED_ITERATION"

        summary["accepted_iteration_count"] = accepted_count
        if accepted_count and summary["status"] == "PASS_ACCEPTED_ITERATION":
            summary["status"] = "PASS_ACCEPTED_%d_ITERATION(S)" % accepted_count
    except Exception as exc:
        summary["status"] = "FAIL"
        summary["error"] = compact_error(exc)
        with (run_dir / "99_TRACEBACK.txt").open("w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
    finally:
        summary["finished_at"] = now_iso()
        write_json(run_dir / "00_MASTER_SUMMARY.json", summary)
        try:
            zip_path = root / (run_dir.name + ".zip")
            zip_folder(run_dir, zip_path)
            summary["evidence_zip"] = str(zip_path)
            summary["evidence_zip_sha256"] = sha256_file(zip_path)
            write_json(run_dir / "00_MASTER_SUMMARY.json", summary)
        except Exception as exc:
            summary["zip_error"] = compact_error(exc)
            write_json(run_dir / "00_MASTER_SUMMARY.json", summary)
        log_line(run_dir, "FINISHED %s" % summary.get("status"))
        log_line(run_dir, "Output: %s" % run_dir)


if __name__ == "__main__":
    main()

# -----------------------------------------------------------------------------
# V2.1 audited extensions (used when this file is imported as a runtime module)
# -----------------------------------------------------------------------------

def _fingerprint_matrix_object(mat, key, source, label=""):
    if np is None:
        raise RuntimeError("NumPy is required for matrix fingerprinting")
    values = mat.GetValues()
    arr = np.asarray(values, dtype="<f8")
    if arr.ndim != 2:
        raise RuntimeError("matrix array is not 2D: shape=%r" % (arr.shape,))
    if not np.all(np.isfinite(arr)) or np.any(arr < 0):
        raise RuntimeError("Demand matrix contains nonfinite or negative values")
    contiguous = np.ascontiguousarray(arr, dtype="<f8")
    return {
        "fingerprint_key": sval(key), "source": source, "label": label,
        "matrix_no": ival(att(mat, "NO", None), ""),
        "matrix_code": sval(att(mat, "CODE", "")),
        "rows": int(contiguous.shape[0]), "cols": int(contiguous.shape[1]),
        "sum": float(np.sum(contiguous)), "nonzero": int(np.count_nonzero(contiguous)),
        "sha256_float64_le": hashlib.sha256(contiguous.tobytes(order="C")).hexdigest(),
        "status": "OK",
    }


def matrix_fingerprints_for_scope(visum, dseg_codes=None, matrix_nos=None):
    """Fingerprint an explicit block-specific matrix scope.

    DSeg and matrix scopes are independent and deduplicated by matrix number.
    This fixes the V2.0 bug where TD_LONG was judged only by WORK/SERVICE DSegs.
    """
    rows = []
    seen_nos = set()
    wanted = set(norm_code(x) for x in (dseg_codes or []))
    for ds in list_dsegs(visum):
        if ds.get("norm_code") not in wanted:
            continue
        try:
            mat = ds["object"].ODMatrix
            no = ival(att(mat, "NO", None), None)
            if no is not None and no in seen_nos:
                continue
            if no is not None:
                seen_nos.add(no)
            rows.append(_fingerprint_matrix_object(mat, "DSEG:%s" % ds.get("norm_code"), "DSEG", ds.get("code", "")))
        except Exception as exc:
            rows.append({"fingerprint_key": "DSEG:%s" % ds.get("norm_code"), "source": "DSEG", "label": ds.get("code", ""), "status": "FAILED", "error": compact_error(exc)})
    for raw_no in matrix_nos or []:
        no = ival(raw_no, None)
        if no is None or no in seen_nos:
            continue
        seen_nos.add(no)
        try:
            mat = visum.Net.Matrices.ItemByKey(int(no))
            if mat is None:
                raise RuntimeError("matrix not found")
            rows.append(_fingerprint_matrix_object(mat, "MATRIX:%d" % no, "MATRIX_NO", ""))
        except Exception as exc:
            rows.append({"fingerprint_key": "MATRIX:%s" % sval(raw_no), "source": "MATRIX_NO", "matrix_no": no if no is not None else "", "status": "FAILED", "error": compact_error(exc)})
    return rows


def compare_explicit_matrix_fingerprints(before_rows, after_rows):
    bmap = {r.get("fingerprint_key"): r for r in before_rows if r.get("fingerprint_key")}
    amap = {r.get("fingerprint_key"): r for r in after_rows if r.get("fingerprint_key")}
    out = []
    for key in sorted(set(bmap) | set(amap)):
        b = bmap.get(key, {}); a = amap.get(key, {})
        comparable = b.get("status") == "OK" and a.get("status") == "OK"
        changed = comparable and b.get("sha256_float64_le") != a.get("sha256_float64_le")
        out.append({
            "fingerprint_key": key,
            "before_status": b.get("status", "MISSING"), "after_status": a.get("status", "MISSING"),
            "before_matrix_no": b.get("matrix_no", ""), "after_matrix_no": a.get("matrix_no", ""),
            "before_sum": b.get("sum", ""), "after_sum": a.get("sum", ""),
            "before_sha256": b.get("sha256_float64_le", ""), "after_sha256": a.get("sha256_float64_le", ""),
            "comparable": int(comparable), "changed": int(changed),
        })
    return out


def zone_parameter_snapshot(visum, zone_nos, attrs):
    rows = []
    for attr_name in attrs:
        try:
            vals = read_zone_attr(visum, attr_name, zone_nos)
            payload = np.asarray(vals, dtype="<f8") if np is not None else vals
            digest = hashlib.sha256(payload.tobytes(order="C")).hexdigest() if np is not None else ""
            rows.append({"attr": attr_name, "rows": len(vals), "sha256_float64_le": digest, "sum": float(sum(vals)), "status": "OK"})
        except Exception as exc:
            rows.append({"attr": attr_name, "status": "FAILED", "error": compact_error(exc)})
    return rows


def compare_parameter_snapshots(before_rows, after_rows, key_name="attr"):
    bmap = {r.get(key_name): r for r in before_rows if r.get(key_name)}
    amap = {r.get(key_name): r for r in after_rows if r.get(key_name)}
    out = []
    for key in sorted(set(bmap) | set(amap)):
        b = bmap.get(key, {}); a = amap.get(key, {})
        same = b.get("status") == "OK" and a.get("status") == "OK" and b.get("sha256_float64_le") == a.get("sha256_float64_le")
        out.append({key_name: key, "before_status": b.get("status", "MISSING"), "after_status": a.get("status", "MISSING"), "before_sha256": b.get("sha256_float64_le", ""), "after_sha256": a.get("sha256_float64_le", ""), "same": int(same)})
    return out

def read_zone_attr_strict(visum, attr_name, zone_nos, zone_indices=None, retry_policy=None):
    return com.indexed_zone_values(
        visum, attr_name, zone_nos, retry_policy=retry_policy, zone_indices=zone_indices)
