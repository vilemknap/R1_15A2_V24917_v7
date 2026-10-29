"""Regression tests for silent, fail-observable unattended Visum entry point."""
from pathlib import Path
from types import SimpleNamespace as NS
import json
import zipfile

import pytest

import v24917_silent_debug as silent


def _host(tmp_path):
    source = tmp_path / "source.ver"
    source.write_bytes(b"ORIGINAL")
    return NS(IO=NS(CurrentVersionFile=str(source))), source


def test_successful_run_creates_zip_and_preserves_source(tmp_path, capsys):
    host, source = _host(tmp_path)

    def calibration():
        folder = tmp_path / silent.RUNS_NAME / "RUN_20261029_00001"
        (folder / "CALIBRATION" / "BASELINE" / "MASK_VEHICLE_LONG").mkdir(parents=True)
        (folder / "RUN_STATUS.json").write_text(json.dumps({"status": "COMPLETE"}))
        (folder / "CALIBRATION" / "BASELINE" / "MASK_VEHICLE_LONG" / "LONG_MASK_RESULT.json").write_text(
            json.dumps({"status": "APPLIED_VERIFIED"}))
        print("SILENT_INTERNAL_DIAGNOSTIC")
        return {"status": "COMPLETE"}

    report = silent.run_silent(host, tmp_path, calibration)
    assert report["status"] == "COMPLETE"
    assert report["model_changed_by_wrapper"] is False
    assert source.read_bytes() == b"ORIGINAL"
    assert "SILENT_INTERNAL_DIAGNOSTIC" not in capsys.readouterr().out
    log = Path(report["python_log"]).read_text()
    assert "SILENT_INTERNAL_DIAGNOSTIC" in log
    with zipfile.ZipFile(report["bundle_file"]) as z:
        assert "RUN/RUN_STATUS.json" in z.namelist()
        assert any(n.endswith("/LONG_MASK_RESULT.json") for n in z.namelist())
        assert "SILENT_PYTHON_LOG_TAIL.txt" in z.namelist()
    assert (tmp_path / silent.DEBUG_NAME / "SILENT_LATEST.json").is_file()
    latest = tmp_path / silent.DEBUG_NAME / "SILENT_LATEST_DEBUG.zip"
    assert latest.is_file()
    with zipfile.ZipFile(latest) as bundle:
        assert "SILENT_STATUS.json" in bundle.namelist()


def test_python_exception_is_silent_but_not_mislabeled_success(tmp_path, capsys):
    host, source = _host(tmp_path)
    def failed():
        print("BEFORE_PYTHON_ERROR")
        raise ValueError("VISUM_DEBUG_SENTINEL")
    report = silent.run_silent(host, tmp_path, failed)
    assert report["status"] == "FAILED_SILENT"
    assert "VISUM_DEBUG_SENTINEL" in report["error"]
    assert "BEFORE_PYTHON_ERROR" not in capsys.readouterr().out
    assert "Traceback (most recent call last)" in Path(report["python_log"]).read_text()
    assert source.read_bytes() == b"ORIGINAL"
    with zipfile.ZipFile(report["bundle_file"]) as z:
        assert "VISUM_DEBUG_SENTINEL" in z.read("SILENT_STATUS.json").decode()


def test_returned_failure_not_reported_as_success(tmp_path):
    host, source = _host(tmp_path)
    def failed():
        folder = tmp_path / silent.RUNS_NAME / "RUN_BAD"
        folder.mkdir(parents=True)
        (folder / "RUN_STATUS.json").write_text('{"status":"FAILED"}')
        return None
    report = silent.run_silent(host, tmp_path, failed)
    assert report["status"] == "FAILED"
    assert report["status_source"].endswith("RUN_STATUS.json")


def test_prior_run_is_not_misattributed_to_new_execution(tmp_path):
    host, _ = _host(tmp_path)
    old = tmp_path / silent.RUNS_NAME / "RUN_OLD"
    old.mkdir(parents=True)
    (old / "RUN_STATUS.json").write_text('{"status":"COMPLETE"}')
    report = silent.run_silent(host, tmp_path, lambda: None)
    assert report["status"] == "RETURNED_UNVERIFIED"
    assert report["run_directory"] is None


def test_bundle_excludes_large_unneeded_payload(tmp_path):
    host, _ = _host(tmp_path)
    def calibration():
        folder = tmp_path / silent.RUNS_NAME / "RUN_SAFE"
        folder.mkdir(parents=True)
        (folder / "RUN_STATUS.json").write_text('{"status":"FAILED"}')
        (folder / "sensitive_huge_data.csv").write_bytes(b"x" * 10_000)
    report = silent.run_silent(host, tmp_path, calibration)
    with zipfile.ZipFile(report["bundle_file"]) as z:
        assert not any("sensitive_huge_data" in n for n in z.namelist())
        assert "RUN/RUN_STATUS.json" in z.namelist()
