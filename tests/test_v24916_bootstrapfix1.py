from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import r1_15a2_com_compat as com


def _load_launcher(root: Path):
    path = root / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py"
    spec = importlib.util.spec_from_file_location("v24916_bootstrapfix1_launcher_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_launcher_com_retry_compat_accepts_legacy_four_item_budget(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    original = launcher.com._retry_budget
    monkeypatch.setattr(launcher.com, "_retry_budget", lambda policy: (3, 0.0, 2.0, 0.5))
    status = launcher._install_com_retry_budget_compat()
    assert status["probe_length"] == 5
    assert tuple(launcher.com._retry_budget({"enabled": False})) == (3, 0.0, 2.0, 0.5, None)
    monkeypatch.setattr(launcher.com, "_retry_budget", original)


def test_launcher_com_retry_compat_rejects_invalid_shape(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    monkeypatch.setattr(launcher.com, "_retry_budget", lambda policy: (1, 2, 3))
    with pytest.raises(RuntimeError, match="COM_RETRY_BUDGET_CONTRACT_MISMATCH"):
        launcher._install_com_retry_budget_compat()


def test_runs_root_exists_even_if_iofix_activation_fails(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    monkeypatch.setattr(launcher, "HERE", package_dir)

    source = tmp_path / "model" / "BASELINE.ver"
    source.parent.mkdir()
    source.write_bytes(b"x")
    visum = SimpleNamespace(IO=SimpleNamespace(CurrentVersionFile=str(source)))
    monkeypatch.setattr(launcher.com, "bind_injected", lambda g: (visum, None))

    def fail_activation():
        raise ValueError("not enough values to unpack (expected 5, got 4)")

    monkeypatch.setattr(launcher.runtime_io_hotfix, "activate", fail_activation)

    with pytest.raises(ValueError, match="expected 5, got 4"):
        launcher.main()

    workspace = source.parent / launcher.RUNS_ROOT_NAME
    assert workspace.is_dir()
    latest = json.loads((workspace / launcher.BOOTSTRAP_FILE).read_text(encoding="utf-8"))
    assert latest["status"] == "FAILED"
    assert latest["stage"] == "ACTIVATE_IOFIX3"
    assert latest["exception_type"] == "ValueError"
    assert (workspace / launcher.BOOTSTRAP_FAILURE_FILE).is_file()

    locator = (package_dir / launcher.PACKAGE_LOCATOR_FILE).read_text(encoding="utf-8")
    assert str(workspace) in locator
    assert "FAILED:ACTIVATE_IOFIX3" in locator
    package_failure = json.loads((package_dir / launcher.PACKAGE_FAILURE_FILE).read_text(encoding="utf-8"))
    assert package_failure["stage"] == "ACTIVATE_IOFIX3"
    assert "expected 5, got 4" in package_failure["exception"]


def test_main_normalizes_four_item_retry_budget_before_live_preflight(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    launcher = _load_launcher(root)
    source = tmp_path / "BASELINE.ver"
    source.write_bytes(b"x")
    visum = SimpleNamespace(IO=SimpleNamespace(CurrentVersionFile=str(source)))
    monkeypatch.setattr(launcher.com, "bind_injected", lambda g: (visum, None))
    monkeypatch.setattr(launcher.com, "_retry_budget", lambda policy: (2, 0.0, 2.0, 0.5))
    monkeypatch.setattr(launcher.runtime_io_hotfix, "activate", lambda: {"status": "ACTIVE"})
    monkeypatch.setattr(launcher.telemetry_failopen, "activate", lambda: {"status": "ACTIVE"})

    seen = {}
    def fake_preflight(v, workspace):
        # This call is the exact site that previously hard-unpacked five values.
        seen["retry_result"] = launcher.com.com_call_with_retry(
            lambda: "LIVE_OK", retry_policy={"enabled": True})
        return ({
            "passes": True,
            "authority_hash": "abc",
            "source_semantic_state_hash": "a" * 64,
        }, {"passes": True})

    monkeypatch.setattr(launcher, "_run_live_preflight", fake_preflight)
    monkeypatch.setattr(launcher, "_install_runtime", lambda *a, **k: {"installed": True})
    monkeypatch.setattr(launcher.parent, "main", lambda mode: {"status": "RETURNED", "mode": mode})
    out = launcher.main()
    assert out["status"] == "RETURNED"
    assert seen["retry_result"] == "LIVE_OK"
    payload = json.loads((source.parent / launcher.RUNS_ROOT_NAME / launcher.BOOTSTRAP_FILE).read_text(encoding="utf-8"))
    assert payload["status"] == "CALIBRATION_RETURNED"
    assert payload["bootstrapfix_revision"] == launcher.BOOTSTRAPFIX_REVISION
