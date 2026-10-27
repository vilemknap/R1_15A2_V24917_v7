from __future__ import annotations
import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1_15a2_profile488_gatefix_v24916p2c as fix
import r1_15a2_fresh0_shortroot_parent_v24916 as parent


def test_effective_config_uses_current_profile488_authority_counts():
    base = parent.load_config("FULL")
    child = fix.apply_active_runtime_delta(base)
    assert child["expected_12d_rows"] == 488
    assert child["expected_calibration_rows"] == 488
    assert child["expected_validation_rows"] == 0
    report = fix.validate_active_runtime_delta(child, base)
    assert report["passes"] is True
    assert report["profile488_runtime_gate_correction"] == {
        "expected_12d_rows": 488,
        "expected_calibration_rows": 488,
        "expected_validation_rows": 0,
    }


def test_11d_cross_gate_accepts_exact_profile488_gate_and_runs_parent_checks():
    seen = {}
    def parent_assess(meta, d12, cfg):
        seen["gate"] = copy.deepcopy(d12["row_gate"])
        return {
            "status": "PASS_ATOMIC_IDP_READ_ONLY",
            "passes": True,
            "mandatory_12d_row_gate": copy.deepcopy(d12["row_gate"]),
            "notices": [],
            "failures": [],
        }
    wrapped = fix._profile488_assess_wrapper(parent_assess)
    d12 = {"row_gate": {"rows": 488, "calibration": 488, "validation": 0}}
    cfg = {"expected_12d_rows": 488, "expected_calibration_rows": 488, "expected_validation_rows": 0}
    out = wrapped({}, d12, cfg)
    assert seen["gate"] == {"rows": 498, "calibration": 462, "validation": 36}
    assert out["passes"] is True
    assert out["mandatory_12d_row_gate"] == d12["row_gate"]
    assert out["active_12d_row_gate_expected"] == d12["row_gate"]
    assert "PROFILE488_12D_GATE_488_488_0_VALIDATED" in out["notices"]


def test_11d_cross_gate_fails_closed_on_wrong_profile488_counts():
    def parent_assess(meta, d12, cfg):
        return {"status":"PASS_ATOMIC_IDP_READ_ONLY","passes":True,"notices":[],"failures":[]}
    wrapped = fix._profile488_assess_wrapper(parent_assess)
    cfg = {"expected_12d_rows": 488, "expected_calibration_rows": 488, "expected_validation_rows": 0}
    out = wrapped({}, {"row_gate":{"rows":487,"calibration":487,"validation":0}}, cfg)
    assert out["passes"] is False
    assert "PROFILE488_12D_ACTIVE_AUTHORITY_NOT_PROVEN:rows" in out["failures"]
    assert "PROFILE488_12D_ACTIVE_AUTHORITY_NOT_PROVEN:calibration" in out["failures"]


def test_launcher_installs_profile488_gate_before_parent_main():
    text = (ROOT / "00_0_SPUSTIT_V24916_FRESH0_ISOLATED_ACTIVE_TARGETING.py").read_text(encoding="utf-8")
    assert "activate_runtime_gate_overlay" in text
    assert text.index("profile488_gate_status = activate_runtime_gate_overlay()") < text.index('result = parent.main("FULL")')
