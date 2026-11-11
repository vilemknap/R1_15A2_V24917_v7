# -*- coding: utf-8 -*-
"""Run inside the opened calibrated 2022 Visum model. See ../README_CZ.md."""
from pathlib import Path
import runpy


def main():
    host = globals().get('Visum')
    if host is None:
        host = globals().get('COM')
    if host is None:
        raise RuntimeError('Run this script inside PTV Visum; no new COM instance will be created.')
    folder = Path(__file__).resolve().parent
    api = runpy.run_path(str(folder.parent / 'scenario_io.py'))
    api['validate_package']()
    exporter = runpy.run_path(str(folder.parent / 'export_2022.py'))
    return exporter['run_export_2022'](host, folder, api)


if __name__ == '__main__' or 'Visum' in globals() or 'COM' in globals():
    main()
