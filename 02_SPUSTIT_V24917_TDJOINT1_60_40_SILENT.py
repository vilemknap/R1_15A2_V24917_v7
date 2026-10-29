# -*- coding: utf-8 -*-
"""Silent V24917 launcher, explicitly 60% counts / 40% IDP survey.

Uses the same logging/exception behavior as the standard silent launcher.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    visum, com = globals().get("Visum"), globals().get("COM")
    if visum is None and com is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    spec = importlib.util.spec_from_file_location(
        "_r1_v24917_silent_60_40",
        HERE / "01_SPUSTIT_V24917_TDJOINT1_SILENT.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("R1_SILENT_60_40_PARENT_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.Visum, module.COM = visum, com
    return module.main(parent_launcher=module.WEIGHTED_LAUNCHER)


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
