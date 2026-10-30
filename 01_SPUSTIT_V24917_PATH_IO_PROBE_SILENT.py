# -*- coding: utf-8 -*-
"""Optional FULL calibration: qualify pages + private fast SQLite publication.

Run R1_BENCHMARK_PATH_EXPORT.py first for a standalone READ-ONLY page profile.
This launcher runs the NORMAL calibration and native model calculations. It
sets two flags only for this call; sealed run options/manifests are not edited.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLAGS = ('R1_PATH_STORE_FAST_STAGING', 'R1_PATH_EXPORT_PAGE_PROBE')


def load_parent():
    spec = importlib.util.spec_from_file_location('_r1_path_io_silent_parent',
        HERE / '01_SPUSTIT_V24917_TDJOINT1_SILENT.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('PATH_IO_SILENT_PARENT_UNAVAILABLE')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def main(visum=None):
    visum = visum if visum is not None else globals().get('Visum')
    com = globals().get('COM')
    if visum is None and com is None:
        raise RuntimeError('NO_INJECTED_VISUM')
    previous = {name: os.environ.get(name) for name in FLAGS}
    try:
        for name in FLAGS: os.environ[name] = '1'
        parent = load_parent()
        parent.Visum, parent.COM = visum, com
        return parent.main()
    finally:
        for name, value in previous.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value


if __name__ == '__main__' or globals().get('Visum') is not None or globals().get('COM') is not None:
    main()
