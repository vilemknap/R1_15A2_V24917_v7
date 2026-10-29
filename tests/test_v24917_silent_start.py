"""Silent startup: stdout goes to log, errors remain visible to Visum.

No Visum COM is needed. These tests exercise the actual silent launcher.
"""
import importlib.util
import sys
from types import SimpleNamespace as NS

import pytest


def _script(filename):
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / filename


def _load(filename, alias):
    spec = importlib.util.spec_from_file_location(alias, _script(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_diagfast_start_print_goes_to_log_not_visum_stdout(tmp_path, monkeypatch, capsys):
    silent = _load("01_SPUSTIT_V24917_TDJOINT1_SILENT.py", "_silent_stdout_test")
    seen = []
    visum = object()
    def parent_main():
        print('DIAGFAST_DIRECT START {"mode": "FAST_EXACT", "inline_parity": 1}')
        print('V24917 another startup notice')
        return "CALIBRATION_RETURN"
    parent = NS(main=parent_main)
    def load(filename):
        seen.append(filename)
        return parent
    monkeypatch.setattr(silent, "load_parent", load)
    monkeypatch.setattr(silent, "log_directory", lambda: tmp_path)
    silent.Visum = visum
    silent.COM = None
    before = sys.stdout
    assert silent.main() == "CALIBRATION_RETURN"
    assert sys.stdout is before
    assert parent.Visum is visum
    assert seen == [silent.PARENT_LAUNCHER]
    assert capsys.readouterr().out == ""
    logs = list(tmp_path.glob("R1_SILENT_*.log"))
    assert len(logs) == 1
    txt = logs[0].read_text(encoding="utf-8")
    assert "DIAGFAST_DIRECT START" in txt
    assert "V24917 another startup notice" in txt
    assert "SILENT_LAUNCH_RETURNED" in txt


def test_exception_is_recorded_and_rethrown(tmp_path, monkeypatch, capsys):
    silent = _load("01_SPUSTIT_V24917_TDJOINT1_SILENT.py", "_silent_error_test")
    def fail():
        print("DIAGFAST_DIRECT START")
        raise RuntimeError("SYNTHETIC_CRITICAL_VISUM_ERROR")
    monkeypatch.setattr(silent, "log_directory", lambda: tmp_path)
    monkeypatch.setattr(silent, "load_parent", lambda filename: NS(main=fail))
    silent.Visum = object()
    silent.COM = None
    before = sys.stdout
    with pytest.raises(RuntimeError, match="SYNTHETIC_CRITICAL_VISUM_ERROR"):
        silent.main()
    assert sys.stdout is before
    assert capsys.readouterr().out == ""
    txt = next(tmp_path.glob("R1_SILENT_*.log")).read_text(encoding="utf-8")
    assert "SILENT_LAUNCH_EXCEPTION" in txt
    assert "RuntimeError: SYNTHETIC_CRITICAL_VISUM_ERROR" in txt


def test_stderr_not_redirected(tmp_path, monkeypatch, capsys):
    silent = _load("01_SPUSTIT_V24917_TDJOINT1_SILENT.py", "_silent_stderr_test")
    def parent_main():
        print("CRITICAL_VISUM_STDERR", file=sys.stderr)
        print("INFO_TO_LOG")
    monkeypatch.setattr(silent, "log_directory", lambda: tmp_path)
    monkeypatch.setattr(silent, "load_parent", lambda filename: NS(main=parent_main))
    silent.Visum = object()
    silent.COM = None
    silent.main()
    output = capsys.readouterr()
    assert output.out == ""
    assert "CRITICAL_VISUM_STDERR" in output.err
    log = next(tmp_path.glob("R1_SILENT_*.log")).read_text(encoding="utf-8")
    assert "INFO_TO_LOG" in log
    assert "CRITICAL_VISUM_STDERR" not in log


def test_no_visum_does_not_open_log(tmp_path, monkeypatch):
    silent = _load("01_SPUSTIT_V24917_TDJOINT1_SILENT.py", "_silent_no_visum_test")
    monkeypatch.setattr(silent, "log_directory", lambda: tmp_path)
    with pytest.raises(RuntimeError, match="NO_INJECTED_VISUM"):
        silent.main()
    assert list(tmp_path.iterdir()) == []


def test_weighted_entrypoint_keeps_parent_selection(tmp_path, monkeypatch):
    silent = _load("01_SPUSTIT_V24917_TDJOINT1_SILENT.py", "_silent_weight_test")
    seen = []
    monkeypatch.setattr(silent, "log_directory", lambda: tmp_path)
    monkeypatch.setattr(silent, "load_parent", lambda filename: seen.append(filename) or NS(main=lambda: 60))
    silent.Visum = object()
    silent.COM = None
    assert silent.main(parent_launcher=silent.WEIGHTED_LAUNCHER) == 60
    assert seen == ["02_SPUSTIT_V24917_TDJOINT1_60_40.py"]


def test_unapproved_parent_rejected_before_log(tmp_path, monkeypatch):
    silent = _load("01_SPUSTIT_V24917_TDJOINT1_SILENT.py", "_silent_unapproved_test")
    silent.Visum = object()
    silent.COM = None
    monkeypatch.setattr(silent, "log_directory", lambda: tmp_path)
    with pytest.raises(RuntimeError, match="R1_SILENT_UNAPPROVED_PARENT_LAUNCHER"):
        silent.main(parent_launcher="outside.py")
    assert list(tmp_path.iterdir()) == []
