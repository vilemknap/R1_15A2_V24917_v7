# -*- coding: utf-8 -*-
"""TDSPLIT1 (b/c and intrazonal penalty realised separately, penalty step cap) + SEVRELAX1."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import r1_15a2_core as core  # noqa: E402
import r1_15a2_intrazonal_penalty_v24917 as iz  # noqa: E402
import r1_15a2_severity_relax_v24917 as sr  # noqa: E402

CFG = json.loads((ROOT / "tests" / "data" / "EFFECTIVE_CONFIG_RUN_20261025_175302.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- SEVRELAX1
def test_relax_only_raises_and_reaches_gate():
    c = copy.deepcopy(CFG)
    rec = sr.relax(c, {"single": 25.0, "high": 15.0})
    sev = c["early_exploration_acceptance"]["severity"]
    assert sev["max_single_profile_geh_increase"] == 25.0 and sev["max_high_geh_increase"] == 15.0
    assert c["supply_route_choice_acceptance"]["severity"]["max_single_profile_geh_increase"] == 25.0
    assert c["supply_route_choice_acceptance"]["severity"]["max_high_geh_increase"] == 15.0
    assert "early_exploration_acceptance.max_single_profile_geh_increase" in rec
    c2 = copy.deepcopy(CFG)
    sr.relax(c2, {"single": 5.0, "high": 5.0})                      # never tightens
    assert c2["early_exploration_acceptance"]["severity"]["max_single_profile_geh_increase"] == 15.0
    # a +22 single-profile jump: rejected with the sealed value, accepted after relaxation
    before = [{"countlocation_no": str(900000 + i), "role": "CALIBRATION", "observed": 1000.0,
               "model": 800.0, "profile_weight": 1.0} for i in range(40)]
    after = [dict(r) for r in before]
    for r in before[30:]:
        r["model"] = 300.0              # existing severe profiles (severity budget baseline)
    for r in after[1:30]:
        r["model"] = 950.0
    for r in after[30:]:
        r["model"] = 330.0
    after[0]["model"] = 1900.0          # GEH 6.7 -> 23.6 (+17: above 15, below 25)
    g0 = core.geh(800.0, 1000.0); g1 = core.geh(1900.0, 1000.0)
    assert 15.0 < g1 - g0 < 25.0
    cfg = copy.deepcopy(CFG); cfg["runtime_acceptance_outer_cycle"] = 1
    d0 = core.acceptance_decision(before, after, {}, {}, cfg, policy_scope="GENERATION")
    assert "NEW_SEVERE_GEH_PROFILE" in d0["reasons"]
    sr.relax(cfg, {"single": 25.0, "high": 15.0})
    d1 = core.acceptance_decision(before, after, {}, {}, cfg, policy_scope="GENERATION")
    assert "NEW_SEVERE_GEH_PROFILE" not in d1.get("reasons", [])


def test_install_wraps_both_builders(monkeypatch):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    monkeypatch.setattr(sr, "options", lambda: {"single": 25.0, "high": 15.0})
    sr.install(print_fn=lambda *a: None)
    assert getattr(ctrl._generation_counts_cfg, "__r1_sevrelax__", False)
    g = ctrl._generation_counts_cfg(copy.deepcopy(CFG), outer_cycle=2)
    t = ctrl._td_acceptance_cfg_for_cycle(copy.deepcopy(CFG), outer_cycle=2)
    for c in (g, t):
        assert c["early_exploration_acceptance"]["severity"]["max_single_profile_geh_increase"] == 25.0


# -------------------------------------------------------------- TDSPLIT1
class Ctrl:
    def __init__(self, accept):
        self.accept = accept                         # function(rows, pen) -> bool
        self.applied = []

    def _td_realization_scales(self, cfg):
        return [1.0, 0.5, 0.25]

    def _td_rows_at_scale(self, before, target_rows, scale):
        return [dict(r, candidate_b=r["candidate_b"] * scale) for r in target_rows]

    canonical_hash = staticmethod(lambda x: json.dumps(x, sort_keys=True, default=str))
    restore_td_parameters = staticmethod(lambda adapter, *a, **k: setattr(adapter, "rows", []) or [])
    _all_td_restore_rows = staticmethod(lambda before: [])

    class _RS:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def recovery_scope(self, control, label):
        return self._RS()

    def _assign_candidate(self, adapter, folder, block):
        return 0.001

    def _td_expected_freeze(self, *a, **k):
        return None

    def atomic_json(self, path, data):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, default=str))

    def _is_retryable_td_realization_error(self, exc):
        return False

    def _rollback_td_all(self, adapter, before, diag, folder, cfg):
        return "ROLLED_STATE", "ROLLED_DIAG"

    number = staticmethod(float)


class Ad:
    def __init__(self, ctrl):
        self.ctrl, self.rows, self.pen = ctrl, [], None
        self.visum = None

    def apply_td(self, rows):
        self.rows = rows

    def parameter_persistence(self, *a):
        return None

    def snapshot(self):
        return {"matrices": [], "dseg_map": {}, iz.SNAPSHOT_KEY: iz.penalty_dict(self.pen)}

    def diagnostics(self, folder, label):
        return {"d12": {"rows": []}}

    def block_gate(self, block, before, after, rows):
        ok = self.ctrl.accept(self.rows, self.pen)
        return {"accepted": ok, "reasons": [] if ok else ["NEW_SEVERE_GEH_PROFILE"]}


@pytest.fixture
def izstate(monkeypatch):
    zones = [1, 2, 3]
    monkeypatch.setitem(iz.STATE, "zones", zones)
    monkeypatch.setitem(iz.STATE, "options", {"iz_max_cycle_change_min": 2.5, "iz_split_realization": True,
                                              "iz_max_penalty_min": 15.0})
    monkeypatch.setitem(iz.STATE, "active", True)

    def write(visum, pen, adapter=None):
        adapter_holder["ad"].pen = np.asarray(pen, dtype=float)
        return adapter_holder["ad"].pen
    adapter_holder = {}
    monkeypatch.setattr(iz, "write_penalty", write)
    monkeypatch.setattr(iz, "penalty_from_snapshot",
                        lambda snap: np.array([float(snap[iz.SNAPSHOT_KEY][str(z)]) for z in zones]))
    return adapter_holder


def run(izstate, tmp_path, accept):
    c = Ctrl(accept)
    ad = Ad(c)
    izstate["ad"] = ad
    stage = {"parent": [0.0, 6.25, 4.0], "target": [7.5, 0.5, 4.0]}
    target_rows = [{"component": "WORK_noE_C", "candidate_b": 2.0, "candidate_c": -1.0}]
    before = {"state_hash": "P", "td_values": [{"component": "WORK_noE_C", "current_b": 1.0, "current_c": -1.0}]}
    cfg = {"td_soft_reference_policy": {"enabled": True}}
    out = iz._realize_with_penalty(c, ad, cfg, tmp_path, SimpleNamespace(checkpoint=lambda *a, **k: None),
                                   before, {}, target_rows, stage)
    ev = json.loads((tmp_path / "TD_REALIZATION_ATTEMPTS.json").read_text())
    return out, ev, ad


def test_penalty_change_capped_per_cycle(izstate, tmp_path):
    out, ev, ad = run(izstate, tmp_path, lambda rows, pen: True)
    assert ev["selected_kind"] == "BC_AND_PENALTY"
    assert list(ad.pen) == [2.5, 3.75, 4.0]          # +7.5 -> +2.5, -5.75 -> -2.5


def test_bc_only_after_combined_rejections(izstate, tmp_path):
    # the penalty change is what breaks the network: anything that moves the penalty is rejected
    out, ev, ad = run(izstate, tmp_path, lambda rows, pen: np.allclose(pen, [0.0, 6.25, 4.0]))
    kinds = [a["kind"] for a in ev["attempts"]]
    assert kinds == ["BC_AND_PENALTY"] * 3 + ["BC_ONLY"]
    assert ev["selected_kind"] == "BC_ONLY" and ad.rows and ad.rows[0]["candidate_b"] == 2.0
    assert list(ad.pen) == [0.0, 6.25, 4.0]


def test_penalty_only_when_bc_breaks(izstate, tmp_path):
    out, ev, ad = run(izstate, tmp_path, lambda rows, pen: not rows)
    kinds = [a["kind"] for a in ev["attempts"]]
    assert kinds[-1] == "PENALTY_ONLY" and ev["selected_kind"] == "PENALTY_ONLY"
    assert out[0][0].get("v24917_noop_bc_row_for_iz_penalty") is True


def test_all_rejected_rolls_back(izstate, tmp_path):
    out, ev, ad = run(izstate, tmp_path, lambda rows, pen: False)
    assert out[0] == [] and out[1] == "ROLLED_STATE"
    assert [a["kind"] for a in ev["attempts"]].count("PENALTY_ONLY") == 2
