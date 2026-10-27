# -*- coding: utf-8 -*-
"""STEP1: computed Generation step through the REAL gate, one trial, adoption in place."""
import copy
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1_15a2_core as core  # noqa: E402
import r1_15a2_step_search_v24917 as step  # noqa: E402
from r1_15a2_supply import canonical_hash  # noqa: E402

CFG = json.loads((ROOT / "tests" / "data" / "EFFECTIVE_CONFIG_RUN_20261025_175302.json")
                 .read_text(encoding="utf-8"))
CFG["runtime_acceptance_outer_cycle"] = 1
OPTS = {"enabled": True, "margin": 0.15, "min_scale": 0.05, "max_scale": 1.0, "grid": 20,
        "rho_bounds": (0.2, 1.5)}
N = 40
STEP = 0.2                     # design log step of every zone at scale 1
EXP0 = 6.0                     # profile 0 reacts 6x stronger than the linear fit says


def base_rows():
    rows = []
    for i in range(N):
        m0 = 950.0 if i == 0 else 300.0 + 10.0 * i
        rows.append({"countlocation_no": str(920000 + i), "role": "CALIBRATION", "observed": 1000.0,
                     "model": m0, "profile_weight": 1.0})
    return rows


def linear_model():
    rows = base_rows()
    # first-order response the fit reports: d m / d s = m0 * STEP (profile 0 under-estimated)
    return {"keys": [str(920000 + i) for i in range(N)],
            "delta_full": [r["model"] * STEP for r in rows]}


def gate(before, after):
    return core.acceptance_decision(before, after, {}, {}, CFG, policy_scope="GENERATION")


@pytest.fixture(autouse=True)
def opts(monkeypatch):
    monkeypatch.setattr(step, "options", lambda: dict(OPTS))
    monkeypatch.setitem(step._STATE, "rho", None)


# --------------------------------------------------------------- unit
def test_step_model_linear_and_secant_volumes():
    m = step.StepModel(base_rows(), linear_model(), rho=0.5)
    assert m.mapped == N
    v = m.volumes(1.0)
    assert v[5] == pytest.approx(350.0 + 0.5 * 350.0 * STEP)
    meas = [dict(r, model=r["model"] * 1.3) for r in base_rows()]
    m.set_measured(0.8, meas)
    assert m.volumes(0.4)[5] == pytest.approx(350.0 + 0.5 * (350.0 * 1.3 - 350.0))
    rows = m.rows(0.4)
    assert rows[5]["model"] == pytest.approx(350.0 + 0.5 * 105.0)
    assert m.volumes(0.0)[3] == pytest.approx(330.0)


def test_learn_rho_from_measurement():
    m = step.StepModel(base_rows(), linear_model(), rho=1.0)
    meas = [dict(r, model=r["model"] + 0.6 * r["model"] * STEP) for r in base_rows()]
    assert m.learn_rho(1.0, meas) == pytest.approx(0.6)


def test_choose_full_step_when_gate_passes_everywhere():
    rows = base_rows()
    rows[0]["model"] = 400.0               # no fragile profile
    lin = {"keys": [r["countlocation_no"] for r in rows], "delta_full": [r["model"] * STEP for r in rows]}
    m = step.StepModel(rows, lin)
    plan = step.choose_scale(m, gate, 0.001, OPTS, 1.0)
    assert plan["scale"] == pytest.approx(1.0)
    assert plan["predicted_rel_improvement"] > 0.01


def test_choose_scale_respects_real_guard_with_margin():
    rows = base_rows()
    lin = {"keys": [r["countlocation_no"] for r in rows],
           "delta_full": [r["model"] * STEP for r in rows]}
    lin["delta_full"][0] = 950.0 * 1.2        # fragile (protected) profile overshoots at s=1
    m = step.StepModel(rows, lin)
    plan = step.choose_scale(m, gate, 0.001, OPTS, 1.0)
    s = plan["scale"]
    assert s is not None and s < 1.0
    # the chosen scale and the margin point both pass the real gate on the model
    assert gate(rows, m.rows(s))["accepted"]
    assert gate(rows, m.rows(min(1.0, s * 1.15)))["accepted"]
    # the full step is rejected by the real gate
    assert not gate(rows, m.rows(1.0))["accepted"]


# ------------------------------------------------------------ integration
class FakeAdapter:
    """Zones = profiles; model volume m_p(g) = m0_p * (g_p/g0_p)^k_p (k_0 = 6, others 1)."""

    def __init__(self):
        self.cfg = copy.deepcopy(CFG)
        self.rows0 = base_rows()
        self.g0 = {str(i + 1): 1.0 for i in range(N)}
        self.g = dict(self.g0)                 # live parameters (COM)
        self.vol_g = dict(self.g0)             # parameters the last assignment saw
        self.assignments = []
        self.diags = []
        self.kept = []

    # state ---------------------------------------------------------------
    def snapshot(self):
        mats = canonical_hash(sorted(self.vol_g.items()))
        gv = {"ADD_PROD_W": dict(self.g)}
        return {"fixed_link_hash": 1, "dseg_hash": 1, "operations_hash": 1, "addval1": {},
                "td_hash": 1, "td_values": [], "generation_values": gv,
                "generation_hash": canonical_hash(gv), "matrices": [{"matrix_no": 9201, "sha256_float64_le": mats}],
                "matrix_hash": mats, "dseg_map": {},
                "state_hash": canonical_hash([gv, mats])}

    def _model(self, i):
        z = str(i + 1)
        k = EXP0 if i == 0 else 1.0
        return self.rows0[i]["model"] * (self.vol_g[z] / self.g0[z]) ** k

    def diagnostics(self, folder, label):
        self.diags.append(label)
        rows = [dict(r, model=self._model(i)) for i, r in enumerate(self.rows0)]
        return {"d12": {"rows": rows}, "d11": {"summary": {}}, "signals": {}}

    # design / preview / apply -------------------------------------------
    def generation_design(self, diag, folder):
        return {"result": None, "projection": None, "v24917_step_model": linear_model()}

    def generation_preview(self, context, scale):
        rows = [{"zone_no": int(z), "attr": "ADD_PROD_W", "current": v,
                 "proposed": v * math.exp(scale * STEP)} for z, v in sorted(self.g.items(), key=lambda x: int(x[0]))]
        return {"candidate_rows": rows}

    def apply_generation(self, context, scale, folder):
        rows = self.generation_preview(context, scale)["candidate_rows"]
        for r in rows:
            self.g[str(r["zone_no"])] = r["proposed"]
        return rows

    def assign_for_block(self, folder, block):
        self.vol_g = dict(self.g)
        self.assignments.append(str(folder))
        return 0.001

    def parameter_persistence(self, block, rows):
        return None

    def block_gate(self, block, before, after, rows):
        return core.acceptance_decision(before["d12"]["rows"], after["d12"]["rows"], {}, {}, self.cfg,
                                        policy_scope="GENERATION")

    def accepted_state_changed(self, state, diag, reason, phase):
        self.kept.append(reason)
        return {"epoch": 2}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_inplace_transaction_v24915p2 as tx
    ad = FakeAdapter()

    def restore(adapter, before_snapshot, candidate_rows, folder=None):
        for r in candidate_rows:
            adapter.g[str(r["zone_no"])] = before_snapshot["generation_values"][r["attr"]][str(r["zone_no"])]
        return []
    monkeypatch.setattr(tx, "restore_generation_parameters", restore)

    def ledger(diag, state, anchors, policy, reference, cfg):
        m = core.csd_metrics(diag["d12"]["rows"], "CALIBRATION", True)
        return {"total": m["objective_geh_mean_weighted"] / 50.0, "raw_cal": m["objective_geh_mean_weighted"],
                "cal_metrics": m}
    monkeypatch.setattr(base, "ledger", ledger)
    ctrl = SimpleNamespace(_generation_counts_cfg=lambda cfg, *a, **k: cfg)
    cfg = {"backtracking_scales": [1.0, 0.5, 0.25],
           "matrix_scope_by_block": {"GENERATION": {"matrix_nos": [9201]}},
           "performance": {"first_sufficient": {"generation_min_relative_improvement": 0.001}}}
    control = SimpleNamespace(checkpoint=lambda *a, **k: None)
    state = ad.snapshot()
    diag = ad.diagnostics(tmp_path, "BASE")

    def run():
        return step.generation_block(ctrl, base, tx, ad, cfg, tmp_path / "GEN", control, state, diag,
                                     None, None, None)
    return SimpleNamespace(ad=ad, run=run, state=state, diag=diag, base=base, folder=tmp_path / "GEN")


def test_block_first_trial_rejected_secant_second_trial_kept_in_place(harness):
    changed, new_state, new_diag, value, rec = harness.run()
    ad = harness.ad
    assert changed is True and rec["status"] == "ACCEPTED" and rec["adopted_in_place"] is True
    a1, a2 = rec["attempts"]
    assert a1["status"] == "REJECTED" and a1["plan_mode"] == "LINEAR_FIT"
    assert a2["status"] == "ELIGIBLE" and a2["plan_mode"] == "SECANT_MEASURED"
    assert a2["candidate"]["scale"] < a1["candidate"]["scale"]
    # exactly two assignments: no rollback recompute between trials, no re-adoption
    assert len(ad.assignments) == 2
    assert ad.diags.count("AFTER") == 2 and "ROLLBACK" not in ad.diags and "ADOPTED" not in ad.diags
    # kept state is the live state of the second trial
    assert new_state == ad.snapshot()
    assert ad.kept == ["V242_ACCEPTED_GENERATION_STATE_CHANGED"]
    s2 = a2["candidate"]["scale"]
    assert ad.g["5"] == pytest.approx(math.exp(s2 * STEP))         # compounded from parent, not from trial 1
    assert (harness.folder / "STEP1_PLAN_01.json").is_file()
    assert step._STATE["rho"] is not None


def test_block_exhausted_rolls_back_once_to_identical_parent(harness, monkeypatch):
    monkeypatch.setattr(step, "options", lambda: dict(OPTS, max_scale=1.0, min_scale=0.9))
    changed, new_state, new_diag, value, rec = harness.run()
    ad = harness.ad
    assert changed is False and rec["status"] == "CONFIGURED_GENERATION_SEARCH_EXHAUSTED"
    assert rec["configured_search_exhausted"] is True
    assert rec["stationarity_confirmed"] is False  # fake design supplies no solver convergence proof
    assert ad.snapshot() == harness.state                              # parent restored
    assert ad.diags[-1] == "ROLLBACK"                                  # one verified rollback
    assert sum(1 for f in ad.assignments if "ROLLBACK" in f) == 1


def test_block_error_rolls_back_and_raises_not_a_plateau(harness, monkeypatch):
    real = harness.ad.assign_for_block
    calls = []

    def boom(folder, block):
        calls.append(folder)
        if len(calls) == 1:
            raise RuntimeError("visum died")
        return real(folder, block)
    monkeypatch.setattr(harness.ad, "assign_for_block", boom)
    from r1_15a2_supply import SupplyContractError
    with pytest.raises(SupplyContractError, match="NOT_A_PLATEAU"):
        harness.run()
    assert harness.ad.snapshot() == harness.state and "ROLLBACK" in str(calls[-1])


def test_install_replaces_generation_impl_and_respects_switch(monkeypatch):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    monkeypatch.setattr(ctrl, "_generation_update_once_impl", ctrl._generation_update_once_impl)
    monkeypatch.setitem(step._STATE, "installed", False)
    calls = []
    orig = ctrl._generation_update_once_impl
    monkeypatch.setattr(ctrl, "_generation_update_once_impl",
                        lambda *a, **k: calls.append("orig") or "ORIG")
    step.install(print_fn=lambda *a: None)
    assert getattr(ctrl._generation_update_once_impl, "__r1_step1__")
    monkeypatch.setattr(step, "options", lambda: dict(OPTS, enabled=False))
    assert ctrl._generation_update_once_impl(*range(9)) == "ORIG" and calls == ["orig"]
    monkeypatch.setattr(step, "generation_block", lambda *a, **k: "STEP1")
    monkeypatch.setattr(step, "options", lambda: dict(OPTS, enabled=True))
    assert ctrl._generation_update_once_impl(*range(9)) == "STEP1"
    monkeypatch.setitem(step._STATE, "installed", False)
    assert orig is not None


def test_options_validation(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(root=tmp_path, environ={})
    assert o["ts_enabled"] is True and o["ts_robust_margin"] == 0.15 and o["perf3_enabled"] is True
    with pytest.raises(RuntimeError):
        dp.load_options(root=tmp_path, environ={"R1_TS_MIN_SCALE": "0.9", "R1_TS_MAX_SCALE": "0.5"})
    o = dp.load_options(root=tmp_path, environ={"R1_TS_ENABLED": "0"})
    assert o["ts_enabled"] is False


def test_adapter_step_model_from_fit():
    import r1_15a2_trial_adapter_v24917 as ad
    problem = SimpleNamespace(profile_rows=[{"countlocation_no": 920001.0}, {"countlocation_no": "920002"}])
    sm = ad.VisumAdapter._step_model(problem, {"predicted_change": np.array([10.0, -5.0])},
                                     {"predicted_change": [1.0, 2.0]})
    assert sm["keys"] == ["920001", "920002"] and sm["delta_full"] == [11.0, -3.0]


def _with_pa_gap(ad, monkeypatch, gap_at):
    """Preview carries the V2.1 design summary; relative P/A gap = gap_at(scale)."""
    orig = ad.generation_preview

    def preview(context, scale):
        d = orig(context, scale)
        g = gap_at(scale)
        d["summary"] = {"estimated_pa_delta_by_family": {
            "WORK": {"estimated_prod_delta": 1000.0, "estimated_att_delta": 1000.0, "estimated_abs_gap": 1000.0 * g}}}
        return d
    monkeypatch.setattr(ad, "generation_preview", preview)

    def apply(context, scale, folder):
        if gap_at(scale) > 0.02:
            from r1_15a2_supply import SupplyContractError
            raise SupplyContractError("GENERATION_GATE:GENERATION_PA_GAP_WORK")
        rows = orig(context, scale)["candidate_rows"]
        for r in rows:
            ad.g[str(r["zone_no"])] = r["proposed"]
        return rows
    monkeypatch.setattr(ad, "apply_generation", apply)


def test_pre_apply_gate_shrinks_step_without_assignment(harness, monkeypatch):
    ad = harness.ad
    _with_pa_gap(ad, monkeypatch, lambda s: 0.03 if s > 0.5 else 0.01)
    changed, st, dg, val, rec = harness.run()
    a1 = rec["attempts"][0]
    assert a1.get("pre_apply_gate_shrink"), a1
    assert a1["candidate"]["scale"] <= 0.5
    assert all(x["reasons"] == ["GENERATION_PA_GAP_WORK"] for x in a1["pre_apply_gate_shrink"])
    # no assignment was spent on a gate-infeasible step
    assert all("TRY_01" in f for f in ad.assignments[:1])


def test_pre_apply_gate_infeasible_everywhere_is_a_plateau_not_a_crash(harness, monkeypatch):
    ad = harness.ad
    _with_pa_gap(ad, monkeypatch, lambda s: 0.05)
    changed, st, dg, val, rec = harness.run()
    assert changed is False and rec["status"] == "CONFIGURED_GENERATION_SEARCH_EXHAUSTED"
    assert rec["stop_reason"] == "PRE_APPLY_GATE_NO_FEASIBLE_SCALE"
    assert ad.assignments == [] and ad.snapshot() == harness.state


def test_apply_gate_error_is_rejection_and_smaller_step(harness, monkeypatch):
    ad = harness.ad
    _with_pa_gap(ad, monkeypatch, lambda s: 0.03 if s > 0.5 else 0.01)
    monkeypatch.setattr(step, "_pre_apply_gate", lambda preview, adapter: None)   # precheck unavailable
    changed, st, dg, val, rec = harness.run()
    assert rec["attempts"][0]["status"] == "REJECTED_PRE_APPLY_GATE"
    st_ = [(a["status"], a["candidate"]["scale"]) for a in rec["attempts"]]
    # each gate rejection shrinks the next step; a gate-feasible step is measured by a real trial
    assert all(b[1] < a_[1] for a_, b in zip(st_, st_[1:])), st_
    assert rec["status"] in ("ACCEPTED", "CONFIGURED_GENERATION_SEARCH_EXHAUSTED")   # never a crash
    assert harness.ad.assignments == [] or changed
