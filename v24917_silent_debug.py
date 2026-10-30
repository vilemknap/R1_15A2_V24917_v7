# -*- coding: utf-8 -*-
"""Silent, fail-observable Visum launcher support; no model mutation or dialog APIs.

Redirects Python stdout/stderr to a continuously flushed log. Exceptions are
recorded rather than allowed to trigger the Visum Python-host traceback dialog.
PTV-native modal dialogs remain outside the Python wrapper's control.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import zipfile

SCHEMA = "R1_15A2_V24917_SILENT_DEBUG_V1"
RUNS_NAME = "R1_15A2_V16_RUNS"
DEBUG_NAME = "R1_15A2_SILENT_DEBUG"
MAX_CAPTURE_FILE_BYTES = 3_000_000
MAX_BUNDLE_BYTES = 20_000_000
MAX_FILES = 60
SELECTED = {
    "00_RESULT.json", "RUN_STATUS.json", "00_PROGRESS.json",
    "00_FINAL_STATUS.txt", "00_PREFLIGHT.json",
    "00_PROCSEQ_AUDIT_SUMMARY.json", "00_SUPPLY_ASSIGNMENT_PLAN.json",
    "00_V240_ASSIGNMENT_SCOPE.json", "RUN_ROOT_AUTHORITY.json",
    "WORKING_COPY_OPERATIONS_DIFF.json",
    "LONG_MASK_RESULT.json", "LONG_MASK_PLAN.json",
    "LONG_MASK_EXECUTION_PLAN.json", "LATEST_BOOTSTRAP.json",
    "BOOTSTRAP_FAILED.json", "V24917_RUNTIME_STATUS.json",
    "METHODOLOGY_STATUS.json", "COM_API_PREFLIGHT.json",
}


class _Autoflush:
    def __init__(self, output):
        self.output = output

    def write(self, data):
        self.output.write(str(data))
        self.output.flush()
        return len(str(data))

    def flush(self):
        self.output.flush()

    def isatty(self):
        return False

    @property
    def encoding(self):
        return self.output.encoding


def _timestamp():
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")


def _atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp_" + os.urandom(5).hex())
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                  allow_nan=False, default=str) + "\n",
                       encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (ValueError, OSError, UnicodeError):
        return None


def _find_new_run(root, before):
    if not root.is_dir():
        return None
    found = [d for d in root.iterdir()
             if d.is_dir() and d.name.startswith("RUN_") and d.name not in before]
    return max(found, key=lambda d: d.stat().st_mtime_ns) if found else None


def _terminal_status(run_folder, result):
    # Never call an unsuccessful calibration successful merely because its
    # controller returned a dict instead of raising.
    if run_folder is not None:
        for name in ("RUN_STATUS.json", "00_RESULT.json"):
            payload = _read_json(run_folder / name)
            if isinstance(payload, dict) and isinstance(payload.get("status"), str):
                return payload["status"], str(run_folder / name)
    if isinstance(result, dict) and isinstance(result.get("status"), str):
        return result["status"], "RETURNED_DICTIONARY"
    return "RETURNED_UNVERIFIED", "NO_TERMINAL_STATUS"


def _compact_run_evidence(run_folder):
    """Bounded scientific evidence for an uploadable ZIP without huge JSONs.

    A live Generation result can exceed 3 MB solely because it repeats several
    hundred zone-level SCHOOL FP violations for every rejected trial. Preserve
    counts, causes and a small deterministic sample instead of silently
    omitting that essential evidence from the silent debug bundle.
    """
    from collections import Counter
    result = {"schema": "R1_15A2_SILENT_COMPACT_EVIDENCE_V1",
              "run_folder": run_folder.name, "files": {}}
    patterns = {
        "generation": "GENERATION_BLOCK_RESULT*.json",
        "td": "TD_FINECDF_BLOCK_RESULT*.json",
        "target_plan": "TD_TARGET_PLAN*.json",
        "rollback": "ROLLBACK_SUMMARY*.json",
        "generation_timing": "V24917_TIMING*.json",
    }
    for label, pattern in patterns.items():
        matching = []
        for f in run_folder.rglob(pattern):
            if f.is_file():
                try:
                    stat = f.stat()
                    if stat.st_size <= 8_000_000:
                        matching.append((stat.st_mtime_ns, f))
                except OSError:
                    continue
        if not matching:
            continue
        _, selected = max(matching, key=lambda pair: pair[0])
        payload = _read_json(selected)
        if not isinstance(payload, dict):
            result["files"][label] = {"status": "UNREADABLE_JSON",
                                      "path": selected.relative_to(run_folder).as_posix()}
            continue
        loc = selected.relative_to(run_folder).as_posix()
        if label == "generation":
            trials = []
            for trial in payload.get("attempts", []):
                decision = trial.get("decision") or {}
                mobility = decision.get("mobility_guard_live") or {}
                zonal = mobility.get("mobilityzone1") or {}
                by_reason = Counter()
                for violation in zonal.get("violations", []):
                    for reason in violation.get("reasons", [violation.get("reason", "UNKNOWN")]):
                        by_reason[str(violation.get("family", "?")) + ":" + str(reason)] += 1
                trials.append({
                    "trial": trial.get("trial"),
                    "scale": (trial.get("candidate") or {}).get("scale"),
                    "status": trial.get("status"), "gap": trial.get("gap"),
                    "reasons": decision.get("reasons"),
                    "model_obs_ratio_before": (decision.get("cal_before") or {}).get("model_obs_ratio"),
                    "model_obs_ratio_after": (decision.get("cal_after") or {}).get("model_obs_ratio"),
                    "weighted_geh_before": decision.get("cal_objective_before"),
                    "weighted_geh_after": decision.get("cal_objective_after"),
                    "mobility_families": mobility.get("families"),
                    "zonal_mobility_status": zonal.get("status"),
                    "zonal_mobility_violation_count": len(zonal.get("violations", [])),
                    "zonal_mobility_violation_counts": dict(sorted(by_reason.items())),
                    "zonal_mobility_sample": (zonal.get("violations") or [])[:5],
                })
            summary = {"status": payload.get("status"),
                       "configured_search_exhausted": payload.get("configured_search_exhausted"),
                       "search_complete": payload.get("search_complete"),
                       "stationarity_confirmed": payload.get("stationarity_confirmed"),
                       "ls_search_incomplete": payload.get("ls_search_incomplete"),
                       "attempts": trials}
        elif label == "td":
            inner = payload.get("inner") or {}
            summary = {"status": payload.get("status"), "gap": payload.get("gap"),
                       "td_realization_complete": payload.get("td_realization_complete"),
                       "inner_status": inner.get("status"),
                       "inner_stop_reason": inner.get("stop_reason"),
                       "inner_search_complete": inner.get("search_complete"),
                       "inner_evaluations": inner.get("td_evaluations"),
                       "changed_components": inner.get("changed_components"),
                       "changed_rows": payload.get("changed_rows"),
                       "td_target_plan": payload.get("td_target_plan"),
                       "incomplete_search_reasons": payload.get("incomplete_search_reasons")}
        elif label == "rollback":
            summary = {"passes": payload.get("passes"),
                       "snapshot_equal": payload.get("snapshot_equal"),
                       "diagnostic_equal": payload.get("diagnostic_equal"),
                       "reason": payload.get("reason"),
                       "gap": payload.get("gap"),
                       "genfix2_parent_proof_passes":
                           (payload.get("genfix2_parent_proof") or {}).get("passes")}
        elif label == "generation_timing":
            summary = {"label": payload.get("label"),
                       "block": payload.get("block"),
                       "savings": payload.get("savings")}
        else:
            summary = {"status": payload.get("status"),
                       "reason": payload.get("reason"),
                       "active_components": payload.get("active_components"),
                       "global_11d_evaluation_required":
                           payload.get("global_11d_evaluation_required")}
        result["files"][label] = {"path": loc, "summary": summary}
    return result


def _bundle(target, report, run_folder, log):
    files = []
    if run_folder is not None and run_folder.is_dir():
        for p in run_folder.rglob("*"):
            if (p.is_file() and
                    (p.name in SELECTED or
                     p.name.startswith("LONG_MASK_") and p.suffix.lower() == ".json")):
                try:
                    size = p.stat().st_size
                    if size <= MAX_CAPTURE_FILE_BYTES:
                        files.append((p.stat().st_mtime_ns, p, size))
                except OSError:
                    continue
    files.sort(key=lambda row: row[0], reverse=True)
    files = files[:MAX_FILES]
    used = 0
    selected = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as archive:
        archive.writestr("SILENT_STATUS.json",
                         json.dumps(report, ensure_ascii=False, indent=2, default=str))
        if run_folder is not None and run_folder.is_dir():
            try:
                compact = _compact_run_evidence(run_folder)
            except Exception as exc:
                compact = {"status": "SUMMARY_FAILED", "error": repr(exc)}
            archive.writestr("SILENT_CALIBRATION_SUMMARY.json",
                             json.dumps(compact, ensure_ascii=False, indent=2,
                                        default=str))
        if log.exists():
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - MAX_CAPTURE_FILE_BYTES))
                tail = stream.read()
            archive.writestr("SILENT_PYTHON_LOG_TAIL.txt", tail)
        for _, path, size in files:
            if used + size > MAX_BUNDLE_BYTES:
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if len(raw) > MAX_CAPTURE_FILE_BYTES:
                continue
            rel = path.relative_to(run_folder).as_posix()
            archive.writestr("RUN/" + rel, raw)
            selected.append({"name": rel, "size_bytes": len(raw),
                             "sha256": hashlib.sha256(raw).hexdigest()})
            used += len(raw)
        archive.writestr("BUNDLE_FILE_INDEX.json",
                         json.dumps(selected, ensure_ascii=False, indent=2))
    return {"file_count": len(selected), "uncompressed_run_bytes": used}


def run_silent(visum, package_root, parent_main, *, project_root_override=None):
    """Run normal full controller, capture its terminal status, bundle evidence.

    A new run must not be conflated with a stale existing one. Exceptions do
    not leave Python and thus do not show the Python host traceback dialog.
    They are never turned into SUCCESS. No Visum version is loaded or saved
    by this wrapper, and the scientific runtime is not patched here.
    """
    package_root = Path(package_root).resolve()
    source = None
    try:
        source = Path(str(visum.IO.CurrentVersionFile)).resolve()
    except Exception:
        pass
    # An accepted source checkpoint may live under a previous RUN_*/CHECKPOINTS.
    # Default behavior is unchanged; A0001 passes the validated outer project
    # base so debug files and new-run discovery stay OUTSIDE the old run tree.
    if project_root_override is not None:
        project_root = Path(project_root_override).resolve()
        if source is None or project_root not in source.parents:
            raise RuntimeError("SILENT_PROJECT_ROOT_OVERRIDE_NOT_SOURCE_ANCESTOR")
    else:
        project_root = source.parent if source is not None else package_root
    output_root = project_root / DEBUG_NAME
    output_root.mkdir(parents=True, exist_ok=True)
    runs_root = (project_root / RUNS_NAME) if source is not None else None
    before = ({p.name for p in runs_root.iterdir()
               if p.is_dir() and p.name.startswith("RUN_")}
              if runs_root is not None and runs_root.is_dir() else set())
    tag = _timestamp()
    log = output_root / ("SILENT_%s.log" % tag)
    traceback_text = None
    error = None
    returned = None
    with log.open("w", encoding="utf-8", buffering=1) as out:
        writer = _Autoflush(out)
        with redirect_stdout(writer), redirect_stderr(writer):
            print("SILENT_RUNTIME_START", tag, "source", str(source))
            try:
                returned = parent_main()
            except BaseException as exc:
                error = type(exc).__name__ + ":" + str(exc)
                traceback_text = traceback.format_exc()
                print("SILENT_EXCEPTION", error)
                print(traceback_text)
            finally:
                print("SILENT_RUNTIME_STOP", tag)
    run_folder = (_find_new_run(runs_root, before) if runs_root is not None else None)
    if error:
        status, status_source = "FAILED_SILENT", "PYTHON_EXCEPTION"
    else:
        status, status_source = _terminal_status(run_folder, returned)
    report = {
        "schema": SCHEMA, "status": status,
        "status_source": status_source,
        "silent_python_console": True,
        "native_visum_dialogs_suppressed": False,
        "error": error, "traceback": traceback_text,
        "source_version": str(source) if source is not None else None,
        "debug_project_root": str(project_root),
        "resolved_runs_root": str(runs_root) if runs_root is not None else None,
        "explicit_project_root_used": project_root_override is not None,
        "run_directory": str(run_folder) if run_folder is not None else None,
        "python_log": str(log),
        "started_tag": tag,
        "finished_at": datetime.now().astimezone().isoformat(),
        "model_changed_by_wrapper": False,
        "calibration_returned": repr(returned)[:1500] if returned is not None else None,
    }
    status_path = output_root / ("SILENT_%s_STATUS.json" % tag)
    archive = output_root / ("SILENT_%s_DEBUG.zip" % tag)
    _atomic_json(status_path, report)
    try:
        bundle_info = _bundle(archive, report, run_folder, log)
        report["bundle_file"] = str(archive)
        report["bundle_info"] = bundle_info
        # Stable filename for repeatedly uploading one file after each crash.
        latest_archive = output_root / "SILENT_LATEST_DEBUG.zip"
        latest_tmp = output_root / (".SILENT_LATEST_" + os.urandom(5).hex() + ".tmp")
        try:
            shutil.copyfile(archive, latest_tmp)
            os.replace(latest_tmp, latest_archive)
            report["latest_debug_zip"] = str(latest_archive)
        finally:
            latest_tmp.unlink(missing_ok=True)
    except Exception as bundle_exc:
        # Evidence publication failures must be visible in the status JSON
        # without showing an unhandled Python-host traceback.
        report["bundle_error"] = type(bundle_exc).__name__ + ":" + str(bundle_exc)
    _atomic_json(status_path, report)
    _atomic_json(output_root / "SILENT_LATEST.json", report)
    return report
