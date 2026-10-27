# -*- coding: utf-8 -*-
"""ONE-CLICK V24917 + PREFLIGHTIOFIX1 (use this file instead of 01_SPUSTIT_V24917_TARGETED_CATCHUP.py).

Visum: open the .ver to start from, then Scripts -> Run script file -> this file.

Identical V24917 run (01_SPUSTIT_V24917_TARGETED_CATCHUP.py is loaded unchanged
and stays hash-identical for DIAGFAST integrity).  Additionally, before the run,
the COM API preflight evidence publication (COM_API_PREFLIGHT.json) is made
tolerant to transient Windows file locks: live 2026-10-26 a WinError 5 on that
JSON turned the PASSED check ZONE_ATTRIBUTE:FP_2_SERVICE_stud into a required
failure (LIVE_API_PREFLIGHT_FAILED).  No check, model read, calibration or
acceptance rule is changed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V17_LAUNCHER = "01_SPUSTIT_V24917_TARGETED_CATCHUP.py"
FIX_MODULE = "r1_15a2_preflight_iofix_v24917.py"
FIX_MODULE_SHA256 = "a843a89df41aaec1ff4d2e9d442cb88b18a4e8273b3e45a8c3498de3800ea6f8"


def verify_fix_module():
    import hashlib
    got = hashlib.sha256((HERE / FIX_MODULE).read_bytes()).hexdigest()
    if got != FIX_MODULE_SHA256:
        raise RuntimeError("V24917_PREFLIGHTIOFIX1_MODULE_HASH_MISMATCH:" + got)
    return got


def load_v17_launcher():
    spec = importlib.util.spec_from_file_location("_r1_v24917_launcher", HERE / V17_LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)      # no Visum in its globals -> does not auto-run
    return module


def prepare(visum, com=None, print_fn=print):
    verify_fix_module()
    v17 = load_v17_launcher()
    v16, installed = v17.prepare(visum, com, print_fn=print_fn)
    # After prepare(): the V24916 module graph (incl. r1_15a2_live_api_audit) is loaded.
    sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]
    import r1_15a2_preflight_iofix_v24917 as preflight_iofix
    status = preflight_iofix.activate()
    print_fn("R1 V24917 PREFLIGHTIOFIX1 active: COM_API_PREFLIGHT.json publication is lock-tolerant "
             "(retry %d x, then direct rewrite / keep .tmp; checks unchanged)" % status["replace_attempts"])
    original_install = v16._install_runtime

    def install_runtime(visum_, authority, manifest, workspace):
        out = dict(original_install(visum_, authority, manifest, workspace))
        out["v24917_preflight_iofix"] = preflight_iofix.status()
        return out
    v16._install_runtime = install_runtime
    return v16, installed, status


def main():
    visum = globals().get("Visum")
    com = globals().get("COM")
    if visum is None and com is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    old_path = list(sys.path)
    try:
        v16, _installed, _status = prepare(visum if visum is not None else com, com)
        return v16.main()
    finally:
        sys.path[:] = old_path


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
