# -*- coding: utf-8 -*-
"""PTV Visum: open ACCEPTED_B_0002_e9eb29d6b38d.ver, then run this script.

Start with outer cycle 2 (Generation -> TD). The accepted cycle 1 is NEVER
replayed. A native path epoch is enumerated into a NEW sibling RUN_* folder.
Original B0002, sidecar, original RUN_STATUS and former SQLite stay untouched.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT_LAUNCHER = "01_SPUSTIT_V24917_PREFLIGHTIOFIX1.py"


def _load_parent():
    spec = importlib.util.spec_from_file_location(
        "_r1_b0002_parent_launcher", HERE / PARENT_LAUNCHER)
    if spec is None or spec.loader is None:
        raise RuntimeError("B0002_PARENT_LAUNCHER_NOT_AVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_project_base(host):
    cp = Path(str(host.IO.CurrentVersionFile)).resolve()
    require_parts = [cp.parent.name.upper(), cp.parent.parent.name.upper(),
                     cp.parent.parent.parent.name, cp.parent.parent.parent.parent.name.upper()]
    if (require_parts[0:2] != ["CHECKPOINTS", "CALIBRATION"] or
            not require_parts[2].startswith("RUN_") or
            require_parts[3] != "R1_15A2_V16_RUNS"):
        raise RuntimeError("B0002_SOURCE_MUST_BE_OLD_RUN_CALIBRATION_CHECKPOINT")
    return cp.parent.parent.parent.parent.parent.resolve()


def _execute(host, com):
    original_path = list(sys.path)
    try:
        launcher = _load_parent()
        v16, _, _ = launcher.prepare(host, com)
        # V24916 bootstrap clears previously imported r1_15a2_* modules.
        sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]
        resume = importlib.import_module("r1_15a2_resume_b0002_v24917")
        source = Path(str(host.IO.CurrentVersionFile)).resolve()
        recipe = resume.authority(HERE)
        checked = resume.check_source(source, recipe)
        installed = resume.install_resume(v16, source, recipe, checked)
        print("B0002 continuation: " + installed["mode"])
        print("B0002: cycle 1 already accepted; cycle 2 starts with new native paths")
        print("B0002: source is protected: " + str(source))
        return v16.main()
    finally:
        sys.path[:] = original_path


def main():
    visum, com = globals().get("Visum"), globals().get("COM")
    host = visum if visum is not None else com
    if host is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    spec = importlib.util.spec_from_file_location(
        "_r1_b0002_silent_helper", HERE / "v24917_silent_debug.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("B0002_SILENT_HELPER_NOT_AVAILABLE")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper.run_silent(
        host, HERE, lambda: _execute(host, com),
        project_root_override=_source_project_base(host))


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
