# -*- coding: utf-8 -*-
"""Run inside the opened 2050 Visum copy. See scenario_tools/README_CZ.md."""
from pathlib import Path
import runpy
YEAR = 2050

def main():
    host = globals().get("Visum")
    if host is None: host = globals().get("COM")
    if host is None: raise RuntimeError("Run this script inside PTV Visum; no new COM instance will be created.")
    folder = Path(__file__).resolve().parent
    api = runpy.run_path(str(folder.parent / "scenario_io.py"))
    api["validate_package"]()
    if api["read_config"](folder)["year"] != YEAR:
        raise RuntimeError("Launcher and scenario year do not match")
    return api["run_import"](host, folder)

if __name__ == "__main__" or "Visum" in globals() or "COM" in globals():
    main()
