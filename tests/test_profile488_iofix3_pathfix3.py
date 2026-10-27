from pathlib import Path
import json
import os

import r1_15a2_runtime_io_hotfix_profile488 as io
import r1_15a2_perf_telemetry_failopen_hotfix_profile488 as telemetry


def _deep_parent(tmp_path, minimum_length=210):
    parent = tmp_path
    parent.mkdir(parents=True, exist_ok=True)
    i = 0
    while len(str(parent)) < minimum_length:
        parent = parent / ("d%02d_abcdefghijk" % i)
        parent.mkdir()
        i += 1
    return parent


def test_windows_extended_path_conversion_local_and_unc():
    local = io._native_path(r"C:\\Users\\user\\deep\\file.json", os_name="nt")
    unc = io._native_path(r"\\server\share\deep\file.json", os_name="nt")
    assert local.startswith("\\\\?\\C:\\")
    assert unc.startswith("\\\\?\\UNC\\server\\share\\")


def test_atomic_json_survives_simulated_legacy_max_path(tmp_path, monkeypatch):
    parent = _deep_parent(tmp_path)
    target = parent / "ROLLBACK_PARAMETER_READBACK.json"
    short_tmp = io._short_temp_path(target, "j")
    old_style_tmp_length = len(str(target)) + len(".31584.22420.385458213670400.tmp")
    assert len(str(target)) < 260
    assert old_style_tmp_length >= 260
    assert len(str(short_tmp)) < 260

    real_open = io._OPEN
    real_replace = io._REAL_REPLACE

    def max_path_open(path, *args, **kwargs):
        if len(os.fspath(path)) >= 260:
            raise FileNotFoundError(2, "simulated legacy MAX_PATH", os.fspath(path))
        return real_open(path, *args, **kwargs)

    def max_path_replace(src, dst):
        if max(len(os.fspath(src)), len(os.fspath(dst))) >= 260:
            raise FileNotFoundError(2, "simulated legacy MAX_PATH", os.fspath(src))
        return real_replace(src, dst)

    monkeypatch.setattr(io, "_OPEN", max_path_open)
    monkeypatch.setattr(io, "_REAL_REPLACE", max_path_replace)
    io.critical_atomic_json(target, {"ok": True, "kind": "rollback"})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "ok": True,
        "kind": "rollback",
    }
    assert not list(parent.glob(".r1*.tmp"))


def test_atomic_copy_uses_short_temp_and_hash_readback(tmp_path, monkeypatch):
    source = tmp_path / "source.bin"
    source.write_bytes((b"abcdef" * 1000) + b"tail")
    parent = _deep_parent(tmp_path / "copy", minimum_length=205)
    destination = parent / "VERY_LONG_DURABLE_HELPER_EVIDENCE_FILENAME.json"

    real_replace = io._REAL_REPLACE

    def max_path_replace(src, dst):
        if max(len(os.fspath(src)), len(os.fspath(dst))) >= 260:
            raise FileNotFoundError(2, "simulated legacy MAX_PATH", os.fspath(src))
        return real_replace(src, dst)

    monkeypatch.setattr(io, "_REAL_REPLACE", max_path_replace)
    assert io.critical_copy_if_file(source, destination) == destination
    assert destination.read_bytes() == source.read_bytes()
    assert not list(parent.glob(".r1*.tmp"))


def test_telemetry_uses_short_temp_at_deep_path(tmp_path, monkeypatch):
    parent = _deep_parent(tmp_path, minimum_length=210)
    target = parent / "SUMMARY.json"
    real_open = io._OPEN
    real_replace = telemetry.os.replace

    def max_path_open(path, *args, **kwargs):
        if len(os.fspath(path)) >= 260:
            raise FileNotFoundError(2, "simulated legacy MAX_PATH", os.fspath(path))
        return real_open(path, *args, **kwargs)

    def max_path_replace(src, dst):
        if max(len(os.fspath(src)), len(os.fspath(dst))) >= 260:
            raise FileNotFoundError(2, "simulated legacy MAX_PATH", os.fspath(src))
        return real_replace(src, dst)

    monkeypatch.setattr(io, "_OPEN", max_path_open)
    monkeypatch.setattr(telemetry.os, "replace", max_path_replace)
    assert telemetry._failopen_atomic_json(target, {"event_count": 1}) is True
    assert json.loads(target.read_text(encoding="utf-8"))["event_count"] == 1
    assert not list(parent.glob(".r1*.tmp"))


def test_short_recovery_root_path_budget_passes():
    run = Path("/tmp/R1B/R1_15A2_P488_RUNS/RUN_20261022_120000_123456")
    audit = io.audit_run_path_budget(run)
    assert audit["passes"] is True
    assert audit["max_projected_logical_length"] < audit["safe_logical_path_budget"]
    assert all(
        len(Path(row["short_temp_path"]).name) <= 28
        for row in audit["samples"]
    )


def test_pathfix3_launcher_uses_short_root_and_expected_release():
    root = Path(__file__).resolve().parents[1]
    launcher = root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py"
    text = launcher.read_text(encoding="utf-8")
    assert "r1_15a2_fresh0_shortroot_parent_v24916" in text
    assert "RUNS_ROOT_NAME" in text

    import r1_15a2_active_targeting_runtime_v24916_fresh0isolated as runtime
    assert runtime.RUNS_ROOT_NAME == "R1_15A2_V16_RUNS"
    assert runtime.RELEASE.endswith("IOFIX3_PATHFIX3_CACHE_DISABLED_20261022")

def test_runtime_v1_json_csv_writers_are_hardened(tmp_path):
    import r1_15a2_runtime_v1 as rt

    status = io.activate()
    assert status["status"] == "ACTIVE"
    assert rt.write_json is io.critical_runtime_write_json
    assert rt.write_csv is io.critical_runtime_write_csv
    assert rt.read_json is io.critical_runtime_read_json
    assert rt.read_csv_auto is io.critical_runtime_read_csv_auto

    parent = _deep_parent(tmp_path / "runtime", minimum_length=205)
    json_path = parent / "ROLLBACK_DIAGNOSTIC_REUSE_PROOF.json"
    csv_path = parent / "PROCEDURE_EXECUTION_PLAN_ACTIVE.csv"
    rt.write_json(json_path, {"passes": True, "rows": 2})
    rt.write_csv(csv_path, [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])

    assert rt.read_json(json_path)["passes"] is True
    assert rt.read_csv_auto(csv_path) == [
        {"a": "1", "b": "x"},
        {"a": "2", "b": "y"},
    ]
    assert not list(parent.glob(".r1*.tmp"))


def test_dynamic_finecdf_reference_writers_are_hardened(tmp_path):
    import r1_15a2_finecdf_bridge_v242 as bridge

    io.activate()
    package_root = Path(__file__).resolve().parents[1]
    ref, _path, _sha = bridge.load_reference(package_root, {})
    assert ref._R1_IOFIX3_PATHFIX3_ACTIVE is True
    assert ref.write_json.__name__ == "ref_write_json"
    assert ref.write_csv.__name__ == "ref_write_csv"
    assert ref.dump_arrays.__name__ == "ref_dump_arrays"

    parent = _deep_parent(tmp_path / "finecdf", minimum_length=205)
    ref.write_json(parent / "V242_FINECDF_INNER_RESULT.json", {"status": "OK"})
    ref.write_csv(parent / "COMPONENT_FINE_CDF.csv", [{"x": 1, "y": 2}])
    ref.dump_arrays(parent / "BEST_STATE.npz", {9001: ref.np.zeros((2, 2))})

    assert json.loads(
        (parent / "V242_FINECDF_INNER_RESULT.json").read_text(encoding="utf-8")
    )["status"] == "OK"
    assert (parent / "COMPONENT_FINE_CDF.csv").stat().st_size > 0
    assert (parent / "BEST_STATE.npz").stat().st_size > 0
    assert not list(parent.glob(".r1*.tmp"))
