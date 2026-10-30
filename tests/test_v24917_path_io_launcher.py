"""Optional launcher scopes flags without changing sealed options or Visum API."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def load():
    path = Path(__file__).resolve().parents[1] / '01_SPUSTIT_V24917_PATH_IO_PROBE_SILENT.py'
    spec = importlib.util.spec_from_file_location('_path_io_launcher_test', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('fail', [False, True])
def test_flags_are_scoped_and_restored(monkeypatch, fail):
    launcher = load()
    monkeypatch.setenv(launcher.FLAGS[0], '0')
    monkeypatch.delenv(launcher.FLAGS[1], raising=False)
    host = object()
    def run():
        assert all(os.environ[name] == '1' for name in launcher.FLAGS)
        assert parent.Visum is host
        if fail: raise RuntimeError('INJECTED_PARENT_ERROR')
        return 'DONE'
    parent = SimpleNamespace(main=run)
    monkeypatch.setattr(launcher, 'load_parent', lambda: parent)
    if fail:
        with pytest.raises(RuntimeError, match='INJECTED_PARENT_ERROR'): launcher.main(host)
    else:
        assert launcher.main(host) == 'DONE'
    assert os.environ[launcher.FLAGS[0]] == '0'
    assert launcher.FLAGS[1] not in os.environ


def test_no_host_cannot_start_calibration():
    with pytest.raises(RuntimeError, match='NO_INJECTED_VISUM'): load().main()
