# -*- coding: utf-8 -*-
"""V24917 TD PERF: UNIVERSAL NEW RUN from the currently open compatible .ver.

PTV Visum 2026 -> Scripts -> Run script file -> this exact launcher.
No A0001/B0002 checkpoint authority or resumed cycle, no source SaveVersion or
LoadVersion. Starts accepted_count=0, cycle 01 and freshly enumerates paths.
A separate project sandbox protects concurrently running older calibration.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = "01_SPUSTIT_V24917_PREFLIGHTIOFIX1.py"
GUARD = "r1_15a2_fresh_universal_v24917.py"
SILENT = "v24917_silent_debug.py"


def sibling(filename, name):
    path = HERE / filename
    if not path.is_file():
        raise RuntimeError("FRESH_UNIVERSAL_PACKAGE_FILE_MISSING:" + filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("FRESH_UNIVERSAL_MODULE_NOT_LOADABLE:" + filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_calibration(host, com, guard, source, sandbox):
    original_path = list(sys.path)
    try:
        # This loads the original sealed V24916 fresh-cycle-1 runtime + all
        # optimizations from the pinned reviewed V24917 branch.
        parent = sibling(PARENT, "_r1_v24917_fresh_universal_parent")
        v16, _, _ = parent.prepare(host, com)
        sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]
        options = json.loads((HERE / "R1_RUN_OPTIONS.json").read_text("utf-8"))
        installed = guard.install(v16, source, sandbox, options=options)
        print("FRESH_UNIVERSAL_RUNTIME_INSTALLED", installed)
        print("FRESH_UNIVERSAL_START_CYCLE", 1, "ACCEPTED_COUNT", 0)
        print("FRESH_UNIVERSAL_NEW_NATIVE_PATH_EPOCH_REQUIRED")
        return v16.main()
    finally:
        sys.path[:] = original_path


def main():
    host = globals().get("Visum") or globals().get("COM")
    com = globals().get("COM")
    if host is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    # The detached guard must load before the V24916 module purge; its private
    # import name is not part of the sealed r1_15a2_* module namespace.
    guard = sibling(GUARD, "_r1_v24917_fresh_universal_guard")
    source = Path(str(host.IO.CurrentVersionFile)).resolve()
    sandbox = guard.sandbox_for(source)
    silent = sibling(SILENT, "_r1_v24917_fresh_universal_silent")
    return guard.run_silent_detached(
        host, HERE, lambda: run_calibration(host, com, guard, source, sandbox),
        sandbox, silent)


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
