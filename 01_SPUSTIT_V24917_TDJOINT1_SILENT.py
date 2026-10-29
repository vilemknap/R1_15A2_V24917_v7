# -*- coding: utf-8 -*-
"""SILENT V24917 TDJOINT1 full calibration. Run inside an opened PTV Visum.

Run via Scripts > Run script file. All ordinary Python prints and any Python
exception traceback are logged in R1_15A2_SILENT_DEBUG beside the source .ver.
A single SILENT_*_DEBUG.zip is assembled for the next debugging round.
The native Visum application's own message boxes cannot be suppressed here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = "01_SPUSTIT_V24917_TDJOINT1.py"


def load_parent():
    spec = importlib.util.spec_from_file_location(
        "_r1_v24917_silent_parent", HERE / PARENT)
    if spec is None or spec.loader is None:
        raise RuntimeError("V24917_SILENT_PARENT_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_silent_helper():
    # Visum's Scripts host does not necessarily put the script directory on
    # sys.path. Load the helper by exact sibling path, just like the parent.
    spec = importlib.util.spec_from_file_location(
        "_r1_v24917_silent_helper", HERE / "v24917_silent_debug.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("V24917_SILENT_HELPER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    run_silent = load_silent_helper().run_silent
    visum = globals().get("Visum")
    com = globals().get("COM")
    host = visum if visum is not None else com

    def execute_parent():
        if host is None:
            raise RuntimeError("NO_INJECTED_VISUM")
        parent = load_parent()
        parent.Visum = visum
        parent.COM = com
        return parent.main()

    return run_silent(host, HERE, execute_parent)


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
