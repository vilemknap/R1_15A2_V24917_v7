# -*- coding: utf-8 -*-
"""Run the INCOMPLETE cycle-1 TD from opened ACCEPTED_A_0001_*.ver.

PTV Visum: open the exact accepted A0001 checkpoint; choose Scripts >
Run script file > this launcher. Never reloads model or re-enumerates routes.
Original complete SQLite path store and fixed generation reference MUST exist.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = "01_SPUSTIT_V24917_PREFLIGHTIOFIX1.py"


def load_parent():
    spec = importlib.util.spec_from_file_location("_r1_a0001_resume_parent", HERE / PARENT)
    if spec is None or spec.loader is None:
        raise RuntimeError("A0001_RESUME_BASE_LAUNCHER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _execute(host, com):
    original_sys_path = list(sys.path)
    try:
        # The V24916 entry point purges old r1_15a2 modules. Import the
        # resume module only after normal V24917 setup and manifest checks.
        parent = load_parent()
        v16, _, _ = parent.prepare(host, com)
        sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]
        resume = importlib.import_module("r1_15a2_resume_a0001_v24917")
        from r1_15a2_supply import canonical_hash
        recipe = resume.authority(HERE)
        checkpoint = Path(str(host.IO.CurrentVersionFile)).resolve()
        paths = resume.check_source(checkpoint, recipe)
        continuation = resume.load_continuation(paths, recipe, canonical_hash)
        resume.install_resume(v16, checkpoint, recipe, paths, continuation)
        print("A0001: original checkpoint verified; cycle 1 TD continuation prepared.")
        print("A0001: source SQLite is read-only: " + str(paths["sqlite"]))
        return v16.main()
    finally:
        sys.path[:] = original_sys_path


def main():
    visum = globals().get("Visum")
    com = globals().get("COM")
    host = visum if visum is not None else com
    if host is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    spec = importlib.util.spec_from_file_location(
        "_r1_a0001_silent_helper", HERE / "v24917_silent_debug.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("A0001_RESUME_SILENT_HELPER_UNAVAILABLE")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper.run_silent(host, HERE, lambda: _execute(host, com))


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
