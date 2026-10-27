# -*- coding: utf-8 -*-
"""V24917 MOBILITY1 + GENFIX1; preserves the PREFLIGHTIOFIX1 entry point.

Open the accepted .ver in Visum, then run this script through Scripts.
It does not create a Visum instance or load a model automatically.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT_LAUNCHER = "01_SPUSTIT_V24917_PREFLIGHTIOFIX1.py"
RELEASE = "R1_15A2_V24917_MOBILITY1_GENFIX1_20261027"


def load_parent():
    spec = importlib.util.spec_from_file_location(
        "_r1_v24917_genfix1_parent", HERE / PARENT_LAUNCHER)
    if spec is None or spec.loader is None:
        raise RuntimeError("V24917_GENFIX1_PARENT_LAUNCHER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    visum, com = globals().get("Visum"), globals().get("COM")
    if visum is None and com is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    parent = load_parent()
    parent.Visum = visum
    parent.COM = com
    print("=== " + RELEASE + " ===")
    return parent.main()


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
