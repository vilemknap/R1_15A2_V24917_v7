from __future__ import annotations

import importlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

import r1_15a2_core as core

ROOT = Path(__file__).resolve().parents[1]


def _skip_if_v24913_supersedes_runtime_manifest():
    if (ROOT / "R1_15A2_CONFIG_V2_4_9_13.json").is_file():
        pytest.skip("V24913 intentionally supersedes shared runtime files and owns its own exact manifest")


def _load_cfg():
    launcher_path = ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py"
    spec = importlib.util.spec_from_file_location("v24912_complete_launcher_test", launcher_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_config()


def _row(code: str = "A"):
    return {
        "countlocation_no": code,
        "role": "CALIBRATION",
        "observed": 100.0,
        "model": 100.0,
        "profile_weight": 1.0,
    }


def test_v24912_live_missing_policy_module_failure_is_closed():
    """Reproduce the live boundary with the release root absent from sys.path."""
    cfg = _load_cfg()
    cfg["runtime_acceptance_outer_cycle"] = 1
    cfg["runtime_acceptance_scope"] = "GENERATION"
    saved_path = list(sys.path)
    saved_facade = sys.modules.pop("r1_15a2_guard_policy_v24912", None)
    try:
        sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != ROOT]
        guard = core.severity_transition_guard([_row()], [_row()], cfg, "GENERATION")
    finally:
        sys.path[:] = saved_path
        if saved_facade is not None:
            sys.modules["r1_15a2_guard_policy_v24912"] = saved_facade
    assert guard["passes"] is True
    assert guard["mode"] == "EARLY_EXPLORATION_BASELINE_RELATIVE_SEVERITY_V24912"
    assert guard["v24912_policy"]["implementation_owner"] == "r1_15a2_core.py"
    assert guard["v24912_policy"]["runtime_external_policy_import_required"] is False


def test_v24912_core_contains_no_late_policy_import():
    text = (ROOT / "r1_15a2_core.py").read_text(encoding="utf-8")
    assert "from r1_15a2_guard_policy_v24912 import" not in text
    assert core.rebase_severity_guard_v24912.__module__ == "r1_15a2_core"


def test_v24912_compatibility_facade_reexports_embedded_policy():
    facade = importlib.import_module("r1_15a2_guard_policy_v24912")
    assert facade.rebase_severity_guard_v24912 is core.rebase_severity_guard_v24912
    assert facade.RUNTIME_EXTERNAL_POLICY_IMPORT_REQUIRED is False
    assert facade.IMPLEMENTATION_OWNER == "r1_15a2_core.py"


def test_v24912_complete_runtime_preflight_passes():
    _skip_if_v24913_supersedes_runtime_manifest()
    cfg = _load_cfg()
    from r1_15a2_safety_v24912 import validate_v24912_runtime_bundle
    report = validate_v24912_runtime_bundle(cfg, ROOT)
    assert report["passes"] is True
    assert report["files_checked"] >= 50
    assert report["late_policy_import_required"] is False
    assert report["live_failure_signature_reproduced_and_closed"] == \
        "NO_MODULE_NAMED_R1_15A2_GUARD_POLICY_V24912"


def test_v24912_runtime_preflight_reports_all_missing_files(tmp_path):
    """An incomplete extraction fails once, before calibration, with a full list."""
    manifest = json.loads((ROOT / "V24912_RUNTIME_BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest["files"]:
        src = ROOT / row["path"]
        dst = tmp_path / row["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copy2(ROOT / "V24912_RUNTIME_BUNDLE_MANIFEST.json",
                 tmp_path / "V24912_RUNTIME_BUNDLE_MANIFEST.json")
    # Remove two independent runtime files to prove aggregated reporting.
    (tmp_path / "r1_15a2_guard_policy_v24912.py").unlink()
    helper = tmp_path / "helpers" / "R1_12D_CSD408_CITY90_RPDI_498_APPROVED.py"
    helper.unlink()
    cfg = _load_cfg()
    from r1_15a2_safety_v24912 import validate_v24912_runtime_bundle
    with pytest.raises(Exception) as excinfo:
        validate_v24912_runtime_bundle(cfg, tmp_path)
    text = str(excinfo.value)
    assert "r1_15a2_guard_policy_v24912.py" in text
    assert "R1_12D_CSD408_CITY90_RPDI_498_APPROVED.py" in text


def test_v24912_runtime_manifest_is_exact():
    _skip_if_v24913_supersedes_runtime_manifest()
    import hashlib
    manifest = json.loads((ROOT / "V24912_RUNTIME_BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["package_revision"] == "V24912_COMPLETE_R2"
    assert manifest["file_count"] == len(manifest["files"])
    for row in manifest["files"]:
        path = ROOT / row["path"]
        assert path.is_file(), row["path"]
        data = path.read_bytes()
        assert len(data) == row["size"], row["path"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["path"]


def test_v24912_launcher_runs_deployment_preflight_before_config_and_model_work():
    text = (ROOT / "R1_15A2_FULL_OVERNIGHT_PERSISTENT_PATH_CACHE_V2_4_9_12.py").read_text(encoding="utf-8")
    pre = text.index("deployment_preflight = preflight_v24912_deployment_files(HERE)")
    load = text.index("cfg = load_config()", pre)
    working = text.index("WORKING_START.ver", load)
    assert pre < load < working
