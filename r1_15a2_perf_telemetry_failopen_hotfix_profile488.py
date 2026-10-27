# -*- coding: utf-8 -*-
"""Fail-open, long-path-safe hotfix for V246 performance telemetry.

The parent telemetry module remains byte-for-byte untouched.  This overlay only
replaces its private JSON writer.  Telemetry is evidence-only: persistent locks,
MAX_PATH-style failures, or fallback publication errors must never terminate
calibration.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import threading
import time

import r1_15a2_perf_v246 as perf
import r1_15a2_runtime_io_hotfix_profile488 as critical_io

_ACTIVATED = False
_ORIGINAL = perf._atomic_json


def _record_io_error(path: Path, exc: BaseException) -> None:
    try:
        critical_io._ensure_parent(path)
        error_path = path.parent / "TELEMETRY_IO_ERRORS.log"
        with critical_io._open_text(error_path, "a", encoding="utf-8") as h:
            h.write(
                "%s\t%s\t%s: %s\n"
                % (
                    datetime.now().astimezone().isoformat(),
                    str(path),
                    type(exc).__name__,
                    str(exc),
                )
            )
    except BaseException:
        pass


def _fallback_path(path: Path) -> Path:
    seed = "%s|%s|%s|%s" % (
        path.name,
        os.getpid(),
        threading.get_ident(),
        time.monotonic_ns(),
    )
    token = hashlib.blake2s(seed.encode("utf-8"), digest_size=6).hexdigest()
    # Preserve the established discoverable pattern while keeping the basename
    # short enough for deep run trees.
    return path.with_name("%s.FALLBACK_%s.json" % (path.stem[:16], token))


def _failopen_atomic_json(path, value):
    path = Path(path)
    tmp = None
    try:
        critical_io._ensure_parent(path)
        tmp = critical_io._short_temp_path(path, "p")
        with critical_io._open_text(tmp, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=True, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        delay = 0.02
        last = None
        for attempt in range(8):
            try:
                os.replace(
                    critical_io._native_path(tmp),
                    critical_io._native_path(path),
                )
                return True
            except OSError as exc:
                last = exc
                if attempt == 7:
                    break
                time.sleep(delay)
                delay = min(delay * 2.0, 0.25)
        if last is not None:
            _record_io_error(path, last)
        try:
            fallback = _fallback_path(path)
            with critical_io._open_text(fallback, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=True, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException as fallback_exc:
            _record_io_error(path, fallback_exc)
        return False
    except BaseException as exc:
        _record_io_error(path, exc)
        return False
    finally:
        if tmp is not None:
            try:
                if critical_io._exists(tmp):
                    critical_io._unlink(tmp)
            except BaseException:
                pass


def activate():
    global _ACTIVATED
    if perf._atomic_json is not _failopen_atomic_json:
        perf._atomic_json = _failopen_atomic_json
    _ACTIVATED = True
    return {
        "status": "ACTIVE",
        "target": "r1_15a2_perf_v246._atomic_json",
        "policy": "TELEMETRY_IO_BEST_EFFORT_LONG_PATH_SAFE_NEVER_ABORT_CALIBRATION",
        "parent_module_modified_on_disk": False,
        "replace_retry_attempts": 8,
        "short_temp_names": True,
        "windows_extended_length_path_io": True,
        "fallback_snapshot": True,
    }


def deactivate_for_test():
    global _ACTIVATED
    perf._atomic_json = _ORIGINAL
    _ACTIVATED = False


__all__ = ["activate", "deactivate_for_test", "_failopen_atomic_json"]
