# -*- coding: utf-8 -*-
"""SEAMS1: the whole TD stage through the REAL controller / V24916 dispatch / V24917 wrappers.

Only Visum (adapter, native TD search) is faked.  Installed in the live order:
    V24916 controller patch (acp.install) -> TD blend -> IZPEN1/ICONG1 -> demand policy.
Every JSON the controller writes goes through the real atomic_json (non-serialisable values fail).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import r1_15a2_intrazonal_penalty_v24917 as iz  # noqa: E402
from test_v24917_intrazonal_penalty import (  # noqa: E402
    BASE, FakeMatrix, IC_OPTS, OPTS, _skims, make_visum)

CFG_PATH = ROOT / "tests" / "data" / "EFFECTIVE_CONFIG_RUN_20261025_175302.json"


class StageAdapter:
    """Minimal live-adapter surface used by the TD stage (mirrors V24917 adapter hooks)."""

    def __init__(self, visum, ratio=0.5):
        self.visum = visum
        self.bc = {"WORK_E_C": (0.0359, -0.3355), "SERV_E_C": (0.0359, -0.1980)}
        self.ratio = ratio
        self.calls = []
        self.cfg = {}
        self.v24916_dynamic_skims = SimpleNamespace(
            require_current=lambda: SimpleNamespace(epoch=1, matrix_meta_by_dseg={}), current=None)
        self.v24917_status = {}

    # snapshot / state -------------------------------------------------------------
    def snapshot(self):
        td = [{"component": c, "status": "OK", "current_b": b, "current_c": cc}
              for c, (b, cc) in sorted(self.bc.items())]
        base = {"state_hash": "%064x" % abs(hash((tuple(sorted(self.bc.items())),
                                                   float(self.visum.mats[9002].a.sum())))),
                "matrices": [], "dseg_map": {}, "td_values": td,
                "fixed_link_hash": 1, "dseg_hash": 1, "operations_hash": 1, "addval_hash": 1,
                "generation_hash": 1}
        return iz.extend_snapshot(base, self.visum)

    def diagnostics(self, folder, label):
        self.calls.append(("DIAG", label))
        obs = 1000.0
        rows = [{"role": "CALIBRATION", "observed": obs, "model": obs * self.ratio, "profile_weight": 1.0,
                 "countlocation_no": "920001", "link_no": 8000071, "from_node_no": 9000222,
                 "to_node_no": 9000524}]
        return {"d12": {"rows": rows}, "d11": {"summary": {}},
                "signals": {"WORK_E_C": {"_obj": 0.20, "calibratable": True}}}

    # writes -----------------------------------------------------------------------
    def apply_td(self, rows):
        for r in rows:
            self.bc[r["component"]] = (float(r["candidate_b"]), float(r["candidate_c"]))
        self.calls.append(("APPLY_TD", len(rows)))

    def parameter_persistence(self, block, rows):
        self.calls.append(("PERSIST", block))

    def assign_for_block(self, folder, block):
        self.calls.append(("ASSIGN", block))
        self.ratio *= 1.02                   # each realised change improves the counts a bit
        return 0.0004

    def begin_candidate_readback_context(self, *a, **k):
        assert isinstance(a[0], str) and len(a[0]) == 64

    def invalidate_candidate_readback(self, *a, **k):
        pass

    def accepted_state_changed(self, state, diag, reason, phase):
        self.calls.append(("ACCEPTED", reason))
        return {"reason": reason}

    def block_gate(self, block, before, after, rows):
        import r1_15a2_td_count_blend_v24917 as tb
        parent = {"accepted": False, "reasons": ["SELECTED_TD_OBJECTIVE_NOT_IMPROVED"]}
        return tb.outer_decision(parent, before, after, self.cfg)


@pytest.fixture
def stage(monkeypatch, tmp_path):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as tx
    import r1_15a2_active_controller_patch_v24916p2c as acp
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_td_count_blend_v24917 as tb
    import r1_15a2_demand_policy_v1 as dp
    import r1_15a2_multiblock as mb
    for obj, name in ((ctrl, "run_finecdf_inner"), (ctrl, "_realize_finecdf_td"), (ctrl, "_finecdf_td_once"),
                      (ctrl, "_finecdf_td_once_impl"), (ctrl, "_generation_update_once"),
                      (ctrl, "restore_td_parameters"), (ctrl, "_generation_counts_cfg"),
                      (ctrl, "_td_realization_scales"), (ctrl, "_finecdf_budget_for_cycle"),
                      (tx, "restore_td_parameters"), (acp, "targeted_run_finecdf_inner"),
                      (bm.DynamicFamilyMetrics, "evaluate"), (bm.NoDirectMatrixWriteTDAdapter, "execute"),
                      (mb, "_multiplicative_coefficient_bounds"), (mb, "_soft_multiplier_bounds")):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    monkeypatch.setattr(tb, "_STATE", {})
    monkeypatch.setattr(iz, "_INSTALLED", {})
    monkeypatch.setattr(dp, "_ACTIVE", {})
    inner_calls = []

    def fake_inner(adapter, cfg, folder, control, package_root, phase_budget=None):
        inner_calls.append(phase_budget)
        Path(folder).mkdir(parents=True, exist_ok=True)
        b, c = adapter.bc["WORK_E_C"]
        return {"changed_rows": [{"component": "WORK_E_C", "after_b": b + 0.05, "after_c": c * 0.9}],
                "stop_reason": "MAX_ITERATIONS", "search_complete": False, "progress_continue": True,
                "stationarity_confirmed": False}
    # the real bridge restore needs Visum TD parameters: fake the b/c part only
    def fake_restore(adapter, before, rows, folder=None):
        by = {r["component"]: r for r in before["td_values"]}
        for r in rows:
            adapter.bc[r["component"]] = (by[r["component"]]["current_b"], by[r["component"]]["current_c"])
        return [{"status": "OK"}]
    monkeypatch.setattr(tx, "restore_td_parameters", fake_restore)
    monkeypatch.setattr(ctrl, "restore_td_parameters", fake_restore)
    monkeypatch.setattr(mb, "td_component_metrics",
                        lambda sig, comps, cfg: {"weighted_objective": float(sig.get("WORK_E_C", {}).get("_obj", 0.2))})

    def install(iz_opts):
        acp.install(ctrl)                                   # V24916 dispatch
        monkeypatch.setattr(acp, "targeted_run_finecdf_inner", fake_inner)
        tb.install(print_fn=lambda *a: None)                # V24917 TD blend
        iz.install(print_fn=lambda *a: None)                # IZPEN1 + ICONG1
        opts = dp.load_options(tmp_path / "noopts", environ={})
        opts.update(td_every_n_cycles=2)
        dp.activate(SimpleNamespace(coupled_runtime=ctrl), options=opts, print_fn=lambda *a: None)
    cfg = json.loads(CFG_PATH.read_text("utf-8"))
    return SimpleNamespace(ctrl=ctrl, install=install, cfg=cfg, folder=tmp_path, inner_calls=inner_calls)


def _act(visum, monkeypatch, opts):
    monkeypatch.setattr(iz, "td_utility_refs", lambda v: {"WORK_E_C": 9002, "SERV_E_C": 9002})
    return iz.activate(visum, opts, print_fn=lambda *a: None)


def test_td_stage_real_wiring_bc_plus_penalty_realised(stage, monkeypatch):
    v = make_visum()
    _act(v, monkeypatch, OPTS)
    stage.install(OPTS)
    monkeypatch.setattr(iz, "search", lambda *a: {"status": "COMPLETED", "changed": True, "F_start": 1.0,
                                                  "F_final": 0.8, "evaluations": 5,
                                                  "penalty_parent": [0.0], "penalty_target": [4.0]})
    ad = StageAdapter(v)
    ad.cfg = stage.cfg
    state, diag = ad.snapshot(), ad.diagnostics(None, "BASE")
    folder = stage.folder / "DEMAND_CYCLE_02_TD_FINECDF"
    changed, st, dg, rec = stage.ctrl._finecdf_td_once(ad, stage.cfg, folder, SimpleNamespace(
        checkpoint=lambda *a, **k: None, remaining=lambda: 1e9), state, diag, "root", outer_cycle=2)
    assert stage.inner_calls and int(stage.inner_calls[0]["max_td_evaluations"]) <= 60
    assert changed is True and rec["status"] == "ACCEPTED_FINECDF_TD"
    assert rec["realization"]["selected_scale"] == 1.0
    assert st[iz.SNAPSHOT_KEY] == {"1": 4.0} and iz.read_penalty(v).tolist() == [4.0]
    assert ad.bc["WORK_E_C"][0] == pytest.approx(0.0359 + 0.05)
    assert rec["inner"]["v24917_intrazonal_penalty"]["changed"] is True
    assert rec["td_run_policy_reason"]
    saved = json.loads((folder / "TD_FINECDF_BLOCK_RESULT.json").read_text("utf-8"))
    assert saved["status"] == "ACCEPTED_FINECDF_TD"
    assert ("ACCEPTED", "V24916_ACCEPTED_REALIZED_FINECDF_TD_STATE_CHANGED") in ad.calls


def test_td_stage_policy_skip_on_odd_cycle(stage, monkeypatch):
    v = make_visum()
    _act(v, monkeypatch, OPTS)
    stage.install(OPTS)
    import r1_15a2_demand_policy_v1 as dp
    pol = next(iter(dp._ACTIVE.values()))["policy"]
    pol.last_generation_changed = True   # TG moved -> no plateau
    pol.td_calls = 1                     # not the first cycle of the run
    ad = StageAdapter(v)
    ad.cfg = stage.cfg
    state, diag = ad.snapshot(), ad.diagnostics(None, "BASE")
    changed, st, dg, rec = stage.ctrl._finecdf_td_once(ad, stage.cfg, stage.folder / "C1", SimpleNamespace(
        checkpoint=lambda *a, **k: None), state, diag, "root", outer_cycle=1)
    assert changed is False and st is state and not stage.inner_calls


def test_td_stage_congestion_feedback_then_td(stage, monkeypatch):
    v = make_visum()
    ttc, tt0 = _skims(1.5)
    v.mats[9872], v.mats[9871] = FakeMatrix(ttc), FakeMatrix(tt0)
    monkeypatch.setattr(iz, "_skim_matrix_no", lambda visum, code, dseg, retry=None: 9872 if code == "TTC" else 9871)
    _act(v, monkeypatch, IC_OPTS)
    stage.install(IC_OPTS)
    monkeypatch.setattr(iz, "search", lambda *a: {"status": "COMPLETED", "changed": False})
    ad = StageAdapter(v, ratio=0.85)
    ad.cfg = stage.cfg
    state, diag = ad.snapshot(), ad.diagnostics(None, "BASE")
    folder = stage.folder / "DEMAND_CYCLE_04_TD_FINECDF"
    changed, st, dg, rec = stage.ctrl._finecdf_td_once(ad, stage.cfg, folder, SimpleNamespace(
        checkpoint=lambda *a, **k: None, remaining=lambda: 1e9), state, diag, "root", outer_cycle=4)
    fb = rec["v24917_congested_impedance"]
    assert fb["status"] == "APPLIED" and changed is True
    assert v.mats[9002].a[0, 3] == pytest.approx(BASE[0, 3] * 1.25)
    assert st[iz.BASE_KEY] != state[iz.BASE_KEY]
    json.dumps(rec)                                         # whole record serialisable
    assert ad.calls.index(("ASSIGN", "TD_FINECDF")) < [i for i, c in enumerate(ad.calls) if c[0] == "APPLY_TD"][0]


def test_td_stage_inner_failure_rolls_back_penalty_and_base(stage, monkeypatch):
    v = make_visum()
    _act(v, monkeypatch, OPTS)
    stage.install(OPTS)
    import r1_15a2_active_controller_patch_v24916p2c as acp
    monkeypatch.setattr(iz, "search", lambda *a: {"status": "COMPLETED", "changed": True, "F_start": 1.0,
                                                  "F_final": 0.8, "evaluations": 5,
                                                  "penalty_parent": [0.0], "penalty_target": [4.0]})
    ad = StageAdapter(v)
    ad.cfg = stage.cfg
    state, diag = ad.snapshot(), ad.diagnostics(None, "BASE")

    def failing_diag(folder, label):
        if label == "AFTER_FINECDF_TD":
            raise RuntimeError("IPF did not converge (synthetic hard failure)")
        return StageAdapter.diagnostics(ad, folder, label)
    ad.diagnostics = failing_diag
    rollbacks = []

    def rollback(adapter, before, baseline_diag, folder, cfg=None):
        stage.ctrl.restore_td_parameters(adapter, before, stage.ctrl._all_td_restore_rows(before), folder)
        iz.restore_from_snapshot(adapter.visum, before, adapter)
        rollbacks.append(folder)
        return adapter.snapshot(), baseline_diag
    monkeypatch.setattr(stage.ctrl, "_rollback_td_all", rollback)
    with pytest.raises(RuntimeError):
        stage.ctrl._finecdf_td_once(ad, stage.cfg, stage.folder / "C2", SimpleNamespace(
            checkpoint=lambda *a, **k: None, remaining=lambda: 1e9), state, diag, "root", outer_cycle=2)
    assert rollbacks and iz.read_penalty(v).tolist() == [0.0] and ad.bc["WORK_E_C"][0] == pytest.approx(0.0359)
    saved = json.loads((stage.folder / "C2" / "TD_FINECDF_BLOCK_RESULT.json").read_text("utf-8"))
    assert saved["status"] == "FAILED_BUT_ROLLBACK_VERIFIED"
