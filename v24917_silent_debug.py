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


def run_silent(visum, package_root, parent_main):
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
    output_root = (source.parent if source is not None else package_root) / DEBUG_NAME
    output_root.mkdir(parents=True, exist_ok=True)
    runs_root = (source.parent / RUNS_NAME) if source is not None else None
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
    bundle_info = _bundle(archive, report, run_folder, log)
    report["bundle_file"] = str(archive)
    report["bundle_info"] = bundle_info
    _atomic_json(status_path, report)
    _atomic_json(output_root / "SILENT_LATEST.json", report)
    return report
