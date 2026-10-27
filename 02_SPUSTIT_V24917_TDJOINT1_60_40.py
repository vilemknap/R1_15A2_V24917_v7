# -*- coding: utf-8 -*-
"""TDJOINT1 optional 60% counts / 40% survey; other settings unchanged."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

def load_parent():
    spec = importlib.util.spec_from_file_location(
        "_r1_tdjoint1_weight_parent", HERE / "01_SPUSTIT_V24917_TDJOINT1.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("TDJOINT1_PARENT_LAUNCHER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    parent = load_parent()
    parent.Visum, parent.COM = globals().get("Visum"), globals().get("COM")
    key = "R1_TD_COUNT_WEIGHT"
    previous = os.environ.get(key)
    try:
        os.environ[key] = "0.60"
        print("TDJOINT1: explicit TD weights 60% counts / 40% survey")
        return parent.main()
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous

if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
