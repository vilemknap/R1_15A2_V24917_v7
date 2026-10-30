# -*- coding: utf-8 -*-
"""Rebuild native A0001 Generation matrices and enumerate NEW paths.

Open ACCEPTED_A_0001_8dcf6dca8fa2.ver in Visum, then run this script.
WARNING: an explicit Visum.LoadVersion discards unsaved in-memory edits.
The source .ver is NOT overwritten. The previous SQLite is NOT used.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = "01_SPUSTIT_V24917_PREFLIGHTIOFIX1.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("A0001_GENERATION_REBUILD_MODULE_UNAVAILABLE:" + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_project_base(host):
    source = Path(str(host.IO.CurrentVersionFile)).resolve()
    cps = source.parent
    calib = cps.parent
    old_run = calib.parent
    runs_root = old_run.parent
    if (cps.name.upper() != "CHECKPOINTS" or
            calib.name.upper() != "CALIBRATION" or
            not old_run.name.upper().startswith("RUN_") or
            runs_root.name.upper() != "R1_15A2_V16_RUNS"):
        raise RuntimeError("A0001_REBUILD_SOURCE_LAYOUT_INVALID")
    return runs_root.parent.resolve()


def _execute(host, com):
    original_path = list(sys.path)
    try:
        # Prepare the sealed V24917 runtime before importing A0001 modules.
        parent = _load_module("_r1_a0001_fresh_enum_base",
                              HERE / PARENT)
        v16, _, _ = parent.prepare(host, com)
        sys.path[:] = [str(HERE)] + [p for p in sys.path if p != str(HERE)]
        original = importlib.import_module("r1_15a2_resume_a0001_v24917")
        rebuild = importlib.import_module("r1_15a2_rebuild_generation_a0001_v24917")
        from r1_15a2_supply import canonical_hash
        recipe = original.authority(HERE)
        source = Path(str(host.IO.CurrentVersionFile)).resolve()
        paths = rebuild.source_paths(source, recipe)
        # Only source coefficients + provenance are authoritative; the old
        # serialized matrices and old SQLite path store are explicitly rejected.
        disk = original.hard_reopen_checkpoint(host, paths, recipe)
        continuation = original.load_continuation(paths, recipe, canonical_hash)
        rebuild.install_rebuild(
            v16, paths, recipe, continuation, disk_receipt=disk, print_fn=print)
        print("A0001 Generation reconstruction: source reloaded from disk; "
              "old OD matrix hash not treated as identity; "
              "full native recompute + NEW full path enumeration.")
        print("A0001: old SQLite deliberately ignored: " + str(paths["sqlite"]))
        return v16.main()
    finally:
        sys.path[:] = original_path


def main():
    visum = globals().get("Visum")
    com = globals().get("COM")
    host = visum if visum is not None else com
    if host is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    helper = _load_module("_r1_a0001_fresh_enum_silent",
                          HERE / "v24917_silent_debug.py")
    return helper.run_silent(
        host, HERE, lambda: _execute(host, com),
        project_root_override=_source_project_base(host))


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
