from __future__ import annotations

from pathlib import Path

import r1_15a2_fresh0_shortroot_parent_v24916 as parent
import r1_15a2_profile488_gatefix_v24916p2c as release
import r1_15a2_runtime_io_hotfix_profile488 as current_io
import r1_15a2_perf_telemetry_failopen_hotfix_profile488 as current_telemetry

ROOT = Path(__file__).resolve().parents[1]


def test_integrated_hotfix_metadata_is_sealed_in_effective_config():
    base = parent.load_config("FULL")
    child = release.apply_active_runtime_delta(base)
    audit = release.validate_active_runtime_delta(child, base)
    hot = child["v24916_integrated_hotfixes"]
    assert audit["passes"] is True
    assert hot["com_busy_snapshot_retry"]["status"] == "ACTIVE"
    assert hot["td09c_16_or_17_native_scope"]["status"] == "ACTIVE"
    assert hot["iofix4_import_audit"]["decision"] == (
        "CURRENT_V24916_IOFIX3_PATHFIX3_IS_STRICT_SUPERSET_NO_DOWNGRADE"
    )
    assert child["v24916_release_identity"]["com_busy_snapshot_retry"] is True
    assert child["v24916_release_identity"]["td09c_16_or_17_native_scope"] is True


def test_current_v24916_io_layer_contains_all_iofix4_compatibility_primitives():
    required = (
        "_native_path",
        "_short_temp_path",
        "critical_atomic_json",
        "critical_atomic_text",
        "critical_copy_if_file",
        "critical_runtime_read_json",
        "critical_runtime_write_json",
        "critical_runtime_write_csv",
        "critical_runtime_read_csv_auto",
        "replace_with_retry",
        "audit_run_path_budget",
    )
    for name in required:
        assert hasattr(current_io, name), name
    assert current_telemetry.critical_io is current_io


def test_launcher_activates_both_imported_hotfixes_before_live_preflight():
    text = (ROOT / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py").read_text(
        encoding="utf-8"
    )
    assert text.index("combusy_status = combusy_hotfix.activate()") < text.index(
        'stage = "LIVE_READ_ONLY_PREFLIGHT"'
    )
    assert text.index("td09c_status = td09c_hotfix.activate()") < text.index(
        'stage = "LIVE_READ_ONLY_PREFLIGHT"'
    )
    assert "td09c_hotfix.read_only_source_preflight(visum)" in text
