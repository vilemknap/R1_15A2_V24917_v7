# -*- coding: utf-8 -*-
"""Silent Visum launcher for the unchanged V24917 TDJOINT1 calibration.

Visum routes Python print() to modal Information windows in some host setups.
Redirect *only* stdout to a durable local log for the entire calibration.
Errors still propagate to the Visum host; safety confirmation dialogs stay on.
No new Visum instance, no LoadVersion and no calibration policy changes.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import traceback
import uuid

HERE = Path(__file__).resolve().parent
PARENT_LAUNCHER = "01_SPUSTIT_V24917_TDJOINT1.py"
WEIGHTED_LAUNCHER = "02_SPUSTIT_V24917_TDJOINT1_60_40.py"
RELEASE = "R1_15A2_V24917_TDJOINT1_SILENT_STDOUT_20261029"


def log_directory():
    """No writes to the source .ver folder, no network dependency."""
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path(tempfile.gettempdir())) / "R1_15A2" / "SILENT_START"


def load_parent(filename=PARENT_LAUNCHER):
    if filename not in (PARENT_LAUNCHER, WEIGHTED_LAUNCHER):
        raise RuntimeError("R1_SILENT_UNAPPROVED_PARENT_LAUNCHER")
    spec = importlib.util.spec_from_file_location(
        "_r1_v24917_silent_parent_" + filename[:2], HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("R1_SILENT_PARENT_LAUNCHER_UNAVAILABLE:" + filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # no Visum in module globals -> no autorun
    return module



def _failure_status(result):
    """Legacy overnight controller returns some critical failures as a dict."""
    if not isinstance(result, dict):
        return None
    status = str(result.get("status") or "").strip().upper()
    if (status.startswith(("FAILED", "ERROR", "FINAL_SAVE_FAILED"))
            or status.endswith("_FAILED")
            or status == "SOURCE_VERSION_FILE_CHANGED_UNEXPECTEDLY"):
        return status
    return None


def main(parent_launcher=PARENT_LAUNCHER):
    visum, com = globals().get("Visum"), globals().get("COM")
    if visum is None and com is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    if parent_launcher not in (PARENT_LAUNCHER, WEIGHTED_LAUNCHER):
        raise RuntimeError("R1_SILENT_UNAPPROVED_PARENT_LAUNCHER")
    folder = log_directory()
    folder.mkdir(parents=True, exist_ok=True)
    logfile = folder / ("R1_SILENT_%s_%s.log" % (
        datetime.now().strftime("%Y%m%d_%H%M%S_%f"), uuid.uuid4().hex[:8]))

    # Do not catch stderr or Windows/Visum safety dialogs: only noncritical
    # Python stdout is redirected. On any failure, log the traceback and
    # re-raise the ORIGINAL exception so the host can display the error.
    with logfile.open("w", encoding="utf-8", buffering=1) as stream:
        with redirect_stdout(stream):
            try:
                print(RELEASE)
                print("Launch:", parent_launcher)
                print("Silent stdout log:", logfile)
                parent = load_parent(parent_launcher)
                parent.Visum = visum
                parent.COM = com
                result = parent.main()
                failure = _failure_status(result)
                if failure is not None:
                    # Original parent already owns cleanup and writes 00_RESULT.
                    # Convert a returned fatal status into an explicit host error
                    # so suppressing stdout cannot hide a failed calibration.
                    raise RuntimeError("R1_SILENT_CALIBRATION_FAILED:%s (log: %s)" %
                                       (failure, logfile))
                print("SILENT_LAUNCH_RETURNED")
                return result
            except BaseException:
                stream.write("\nSILENT_LAUNCH_EXCEPTION (propagated to Visum):\n")
                traceback.print_exc(file=stream)
                stream.flush()
                raise


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
