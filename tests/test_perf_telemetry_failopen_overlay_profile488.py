from pathlib import Path
import json
import os

import r1_15a2_perf_v246 as perf
import r1_15a2_perf_telemetry_failopen_hotfix_profile488 as hotfix


def test_persistent_summary_lock_never_escapes(tmp_path, monkeypatch):
    real_replace = os.replace
    def locked(src, dst):
        if Path(dst).name == "SUMMARY.json":
            raise PermissionError(5, "simulated Windows lock", str(dst))
        return real_replace(src, dst)
    monkeypatch.setattr(hotfix.os, "replace", locked)
    monkeypatch.setattr(hotfix.time, "sleep", lambda _: None)
    hotfix.activate()
    try:
        t = perf.PerformanceTelemetry(tmp_path / "PERFORMANCE", clock=lambda: 10.0)
        row = t.event("BUNDLE_INVALIDATE", mutation=True)
        assert row["name"] == "BUNDLE_INVALIDATE"
        assert (tmp_path / "PERFORMANCE" / "EVENT_000001.json").is_file()
        assert list((tmp_path / "PERFORMANCE").glob("SUMMARY.FALLBACK_*.json"))
        assert not list((tmp_path / "PERFORMANCE").glob("*.tmp"))
    finally:
        hotfix.deactivate_for_test()


def test_transient_summary_lock_retries_then_publishes(tmp_path, monkeypatch):
    real_replace = os.replace
    remaining = {"n": 2}
    def transient(src, dst):
        if Path(dst).name == "SUMMARY.json" and remaining["n"]:
            remaining["n"] -= 1
            raise PermissionError(5, "transient simulated Windows lock", str(dst))
        return real_replace(src, dst)
    monkeypatch.setattr(hotfix.os, "replace", transient)
    monkeypatch.setattr(hotfix.time, "sleep", lambda _: None)
    hotfix.activate()
    try:
        t = perf.PerformanceTelemetry(tmp_path / "PERFORMANCE", clock=lambda: 10.0)
        t.event("TEST")
        summary = json.loads((tmp_path / "PERFORMANCE" / "SUMMARY.json").read_text())
        assert summary["event_count"] == 1
        assert remaining["n"] == 0
        assert not list((tmp_path / "PERFORMANCE").glob("*.tmp"))
    finally:
        hotfix.deactivate_for_test()
