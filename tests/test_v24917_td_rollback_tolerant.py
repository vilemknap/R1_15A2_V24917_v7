# -*- coding: utf-8 -*-
"""TDROLLBACK1: parameter-exact TD rollback accepted within numerical noise only."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import r1_15a2_td_rollback_tolerant_v24917 as tr  # noqa: E402


def rows(scale=1.0, bump=None):
    out = []
    for i in range(30):
        m = (1000.0 + 10 * i) * scale
        if bump and i == bump[0]:
            m += bump[1]
        out.append({"countlocation_no": str(900000 + i), "role": "CALIBRATION", "observed": 1200.0,
                    "model": m, "profile_weight": 1.0})
    return out


def snap(td=1.0, mat="A", gen="G", pen="P"):
    return {"state_hash": mat + gen + pen + str(td), "generation_values": gen, "addval1": {"1|2|3": 0.0},
            "v24917_iz_penalty": pen, "td_values": [{"component": "W", "current_b": td}],
            "matrices": [{"matrix_no": 9101, "sha256_float64_le": mat}], "matrix_hash": mat}


class Ad:
    def __init__(self, state, diag_rows):
        self.state, self.rows, self.changed = state, diag_rows, []

    def snapshot(self):
        return dict(self.state)

    def diagnostics(self, folder, label):
        return {"d12": {"rows": self.rows}}

    def accepted_state_changed(self, s, d, reason, phase):
        self.changed.append(reason)


def ctrl(freeze_ok=True):
    from r1_15a2_supply import SupplyContractError

    def freeze(before, after, rows_, cfg, path):
        if not freeze_ok:
            raise SupplyContractError("TD_PARAMETER_READBACK_MISMATCH")

    def orig(adapter, before, baseline, folder, cfg=None):
        raise SupplyContractError("V242_TD_ROLLBACK_NOT_IDENTICAL")
    return SimpleNamespace(_td_expected_freeze=freeze, atomic_json=lambda p, d: None, orig=orig)


def test_accepts_noise_level_recompute(tmp_path):
    c = ctrl()
    before = snap()
    # This test covers load roundoff with EXACT matrices. Changed matrix bytes
    # are exercised by the GENFIX2 disk-bound numerical proof regressions.
    ad = Ad(snap(), rows(1.0 + 1e-12))
    st, dg = tr.wrap_rollback_td_all(c.orig, c)(ad, before, {"d12": {"rows": rows()}}, tmp_path, {})
    assert st["matrices"][0]["sha256_float64_le"] == "A"
    assert dg["d12"]["rows"] == ad.rows


def test_refuses_material_load_difference(tmp_path):
    c = ctrl()
    ad = Ad(snap(mat="B"), rows(bump=(3, 25.0)))
    with pytest.raises(Exception, match="V242_TD_ROLLBACK_NOT_IDENTICAL"):
        tr.wrap_rollback_td_all(c.orig, c)(ad, snap(), {"d12": {"rows": rows()}}, tmp_path, {})


def test_refuses_unrestored_parameters(tmp_path):
    c = ctrl()
    ad = Ad(snap(pen="Q"), rows())
    with pytest.raises(Exception, match="NOT_IDENTICAL"):
        tr.wrap_rollback_td_all(c.orig, c)(ad, snap(), {"d12": {"rows": rows()}}, tmp_path, {})
    c2 = ctrl(freeze_ok=False)
    with pytest.raises(Exception, match="NOT_IDENTICAL"):
        tr.wrap_rollback_td_all(c2.orig, c2)(Ad(snap(), rows()), snap(), {"d12": {"rows": rows()}}, tmp_path, {})


def test_other_errors_pass_through(tmp_path):
    def orig(*a, **k):
        raise RuntimeError("COM_DEAD")
    with pytest.raises(RuntimeError, match="COM_DEAD"):
        tr.wrap_rollback_td_all(orig, ctrl())(Ad(snap(), rows()), snap(), {"d12": {"rows": rows()}}, tmp_path)
    ok = tr.wrap_rollback_td_all(lambda *a, **k: ("S", "D"), ctrl())
    assert ok(None, None, None, tmp_path) == ("S", "D")


def test_install_on_live_controller():
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as fc
    tr.install(print_fn=lambda *a: None)
    assert getattr(fc._rollback_td_all, "__r1_tdrollback1__", False)


def test_penalty_rounding_noise_is_not_a_parameter_change():
    a = {"v24917_iz_penalty": {"503": 6.172800001, "611": 6.25}, "generation_values": "G"}
    b = {"v24917_iz_penalty": {"503": 6.1728, "611": 6.25}, "generation_values": "G"}
    assert tr.parameter_differences(a, b) == []
    b["v24917_iz_penalty"]["611"] = 6.3
    assert tr.parameter_differences(a, b) == ["v24917_iz_penalty"]
