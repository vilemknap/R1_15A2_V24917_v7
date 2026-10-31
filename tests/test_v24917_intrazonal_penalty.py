# -*- coding: utf-8 -*-
"""IZPEN1: intrazonal impedance lever (M9002 diagonal penalty for big intrazonal zones)."""
import contextlib
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1_15a2_intrazonal_penalty_v24917 as iz  # noqa: E402

OPTS = {"iz_enabled": True, "iz_matrix_no": 9002, "iz_min_share_select": 0.70,
        "iz_min_production_select": 5000.0, "iz_zones": [], "iz_exclude_zones": [],
        "iz_max_penalty_min": 15.0, "iz_max_step_min": 5.0, "iz_probe_min": 2.0,
        "iz_min_intrazonal_share": 0.40, "iz_max_iterations": 3, "iz_ridge_relative": 0.05}


class FakeMatrix:
    def __init__(self, a, mtype=4):
        self.a = np.array(a, dtype=float)
        self.att = {"MATRIXTYPE": mtype, "OBJECTTYPEREF": 2}
        self.writes = 0

    def GetValues(self):
        return tuple(tuple(r) for r in self.a.tolist())

    def SetValues(self, v):
        self.writes += 1
        self.a = np.array(v, dtype=float)

    def AttValue(self, k):
        return self.att[k]


class FakeVisum:
    def __init__(self, mats, n):
        self.mats = {int(k): FakeMatrix(v) for k, v in mats.items()}
        zones = [(i + 1, float(i + 1)) for i in range(n)]
        self.Net = SimpleNamespace(
            Matrices=SimpleNamespace(ItemByKey=self._item),
            Zones=SimpleNamespace(GetMultiAttValues=lambda attr: zones))

    def _item(self, no):
        if int(no) not in self.mats:
            raise KeyError(no)
        return self.mats[int(no)]


N = 6
BASE = np.array([[8.0 if i == j else 10.0 + 3.0 * abs(i - j) for j in range(N)] for i in range(N)])
BASE[0, 0] = 15.0                                       # big district zone: high diagonal impedance
P = np.array([20000.0, 3000, 3000, 3000, 3000, 3000])
A = np.array([22000.0, 2600, 2600, 2600, 2600, 2600])
C = -0.25
SELF_MASS = {0: 60.0}                                    # huge own attraction mass inside the zone
COUNT_ZONES = [0]


def gravity(U, iters=60):
    f = np.exp(C * U)
    for z, m in SELF_MASS.items():
        f[z, z] *= m
    T = f * P[:, None] * A[None, :] / A.sum()
    for _ in range(iters):
        T *= (P / T.sum(axis=1))[:, None]
        T *= (A / T.sum(axis=0))[None, :]
    return T


def ws_mats(T):
    out = {9101: 0.6 * T, 9106: 0.4 * T}
    for no in range(9102, 9111):
        out.setdefault(no, np.zeros((N, N)))
    return out


def make_visum(penalty0=None):
    U = BASE.copy()
    if penalty0 is not None:
        for z, p in penalty0.items():
            U[z - 1, z - 1] += p
    T = gravity(U)
    mats = {9001: BASE.copy(), 9002: U}
    mats.update(ws_mats(T))
    return FakeVisum(mats, N)


@pytest.fixture
def act(monkeypatch):
    def _act(visum, opts=None, refs=9002):
        monkeypatch.setattr(iz, "td_utility_refs", lambda v: {"WORK_E_C": refs, "SERV_E_C": refs})
        return iz.activate(visum, dict(OPTS, **(opts or {})), print_fn=lambda *a: None)
    yield _act
    iz.STATE.clear()
    iz.STATE.update(active=False, reason="TEST_RESET")
    iz._STAGE.clear()


# ------------------------------------------------------------------ selection / activation
def test_select_zones_auto_explicit_exclude_and_existing():
    ws = np.diag([9000.0, 100.0, 6000.0, 50.0])
    ws[0, 1] = 1000.0          # zone1 share 0.9 prod 10000
    ws[2, 3] = 4000.0          # zone3 share 0.6
    zo = [1, 2, 3, 4]
    z, rows, basis = iz.select_zones(ws, zo, OPTS)
    assert z == [1] and basis.startswith("AUTO") and rows[0]["ws_intrazonal_share"] == pytest.approx(0.9)
    z, _r, basis = iz.select_zones(ws, zo, dict(OPTS, iz_zones=[3, 4]))
    assert z == [3, 4] and basis == "EXPLICIT_IZ_ZONES"
    z, _r, _b = iz.select_zones(ws, zo, dict(OPTS, iz_exclude_zones=[1]))
    assert z == []
    z, _r, _b = iz.select_zones(ws, zo, OPTS, existing={4: 2.5})
    assert z == [1, 4]


def test_activate_selects_big_intrazonal_zone(act):
    v = make_visum()
    st = act(v)
    assert st["active"] and st["zones"] == [1]
    assert st["selection"][0]["ws_intrazonal_share"] > 0.7 and st["selection"][0]["diag_m9001_min"] == 15.0


def test_activate_inactive_reasons(act):
    v = make_visum()
    assert "TD_UTILITY_NOT_M9002" in act(v, refs=9001)["reason"]
    v = make_visum(); del v.mats[9002]
    assert act(v)["reason"].startswith("MATRIX_M9002_MISSING")
    v = make_visum(); v.mats[9002].a[0, 1] += 1.0
    assert "OFFDIAGONAL" in act(v)["reason"]
    assert act(v, opts={"iz_enabled": False})["reason"] == "DISABLED_BY_RUN_OPTION"
    v = make_visum(); v.mats[9001] = None
    st = act(v)
    assert st["active"] is False and st["reason"].startswith("ACTIVATION_ERROR")


def test_restart_keeps_zone_with_existing_penalty(act):
    v = make_visum(penalty0={1: 3.0, 4: 1.5})
    st = act(v)
    assert st["zones"] == [1, 4]
    assert iz.read_penalty(v).tolist() == pytest.approx([3.0, 1.5])


# ------------------------------------------------------------------ read / write / snapshot
def test_write_read_roundtrip_bounds_and_integrity(act):
    v = make_visum()
    act(v)
    calls = []
    ad = SimpleNamespace(invalidate_candidate_readback=lambda r, mutation=True: calls.append(r))
    back = iz.write_penalty(v, [4.25], ad)
    assert back.tolist() == pytest.approx([4.25]) and v.mats[9002].a[0, 0] == pytest.approx(19.25)
    assert np.array_equal(v.mats[9001].a, BASE) and calls == ["V24917_IZ_PENALTY_WRITE"]
    with pytest.raises(iz.IZError):
        iz.write_penalty(v, [16.0])
    with pytest.raises(iz.IZError):
        iz.write_penalty(v, [-0.5])
    v.mats[9002].a[2, 3] += 0.1
    with pytest.raises(iz.IZError, match="OFFDIAGONAL"):
        iz.read_penalty(v)


def test_snapshot_extension_keeps_state_hash(act):
    v = make_visum()
    base = {"state_hash": "h" * 64, "matrices": []}
    assert iz.extend_snapshot(base, v) is base          # inactive -> untouched
    act(v)
    iz.write_penalty(v, [2.0])
    s = iz.extend_snapshot(base, v)
    assert s["state_hash"] == base["state_hash"] and s[iz.SNAPSHOT_KEY] == {"1": 2.0}
    assert iz.penalty_from_snapshot(s).tolist() == [2.0]


# ------------------------------------------------------------------ linear pieces
def test_attribute_partitions_probe_change_exactly():
    rng = np.random.default_rng(3)
    dT = {9101: rng.normal(size=(5, 5)), 9106: rng.normal(size=(5, 5))}
    idx = np.array([0, 2, 3])
    parts = [iz.attribute(dT, idx, k) for k in range(3)]
    for no in dT:
        assert np.allclose(sum(p[no] for p in parts), dT[no])
    # zone 0 owns its full row/column except cells shared with other selected zones (half)
    assert parts[0][9101][0, 1] == pytest.approx(dT[9101][0, 1])
    assert parts[0][9101][0, 2] == pytest.approx(0.5 * dT[9101][0, 2])
    assert parts[0][9101][0, 0] == pytest.approx(dT[9101][0, 0])


def test_bounded_ridge_step_respects_bounds():
    J = np.array([[1.0, 0.0], [0.0, 2.0], [1.0, 1.0]])
    r = np.array([-3.0, -2.0, 0.5])
    free = iz.bounded_ridge_step(r, J, np.array([-10.0, -10.0]), np.array([10.0, 10.0]), 1e-9)
    ls = np.linalg.lstsq(J, -r, rcond=None)[0]
    assert np.allclose(free, ls, atol=1e-6)
    capped = iz.bounded_ridge_step(r, J, np.array([0.0, 0.0]), np.array([0.5, 10.0]), 1e-9)
    assert capped[0] == pytest.approx(0.5) and 0.0 <= capped[1] <= 10.0


def test_matrix_ref_parser():
    assert iz.matrix_ref_no("Matrix([NO]=9002)") == 9002
    assert iz.matrix_ref_no("Matrix([NO] = 9001)") == 9001
    assert iz.matrix_ref_no("9002") == 9002
    assert iz.matrix_ref_no("") is None


# ------------------------------------------------------------------ search on a synthetic gravity model
class FakeBridge:
    def __init__(self, visum, ref, root, control=None, telemetry=None, outer_adapter=None):
        self.v, self.ref, self.root, self.outer_adapter = visum, ref, Path(root), outer_adapter
        self.dynamic_skim_enabled = True
        self.zone_order = list(range(1, N + 1))
        self.isolated = False
        self.runs = 0

    def isolate_td(self):
        self.isolated = True

    def restore_controls(self):
        self.isolated = False

    def read_matrix(self, no):
        return self.v.mats[int(no)].a.copy()

    def execute(self):
        assert self.isolated
        self.runs += 1
        T = gravity(self.v.mats[9002].a)
        return {9101: 0.6 * T, 9106: 0.4 * T}


OBS_OUT = 2500.0          # counts: trips leaving zone 1 (model ~ 330 at start)
SURVEY_INTRA = 0.74       # survey: intrazonal share of all trips (model 0.776)


def pure_eval(metrics, mats):
    out = {}
    for key, no in (("WORK_E_C", 9101), ("SERV_E_C", 9106)):
        T = mats[no]
        share = float(np.trace(T) / T.sum())
        r = np.array([(share - SURVEY_INTRA) * 10.0])
        out[key] = {"objective": float(r @ r), "residual": r}
    return out


class FakeBlend:
    def __init__(self, bridge, ref, opts):
        self.ref_set, self.measured = False, True
        self.model = SimpleNamespace(linear=True)

    def stacked(self, out, mats, M_ref=None):
        keys = sorted(out)
        r_idp = np.concatenate([out[k]["residual"] for k in keys])
        J = float(sum(out[k]["objective"] for k in keys))
        T = mats[9101] + mats[9106]
        M = np.array([float(T[z].sum() - T[z, z]) for z in COUNT_ZONES])
        O = OBS_OUT * np.ones(len(COUNT_ZONES))
        q = (M - O) / np.sqrt(0.5 * (M + O))
        if not self.ref_set:
            self.J_ref, self.Q_ref, self.ref_set = max(J, 1e-12), float(q @ q), True
        r = np.r_[math.sqrt(0.35 / self.J_ref) * r_idp, math.sqrt(0.65 / self.Q_ref) * q]
        return r, float(r @ r), {"J": J, "M": M.tolist()}


@pytest.fixture
def search_env(monkeypatch, act, tmp_path):
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_td_count_blend_v24917 as tb
    ref = SimpleNamespace(TARGETS={"WORK_E_C": {"matrix_nos": [9101]}, "SERV_E_C": {"matrix_nos": [9106]}})
    monkeypatch.setattr(bm, "load_reference", lambda root, cfg=None: (ref, "x", "sha"))
    bridges = []

    def mk(*a, **k):
        b = FakeBridge(*a, **k)
        bridges.append(b)
        return b
    monkeypatch.setattr(bm, "NoDirectMatrixWriteTDAdapter", mk)
    monkeypatch.setattr(bm, "DynamicFamilyMetrics", lambda bridge, ref: SimpleNamespace(bridge=bridge))
    monkeypatch.setattr(tb, "ORIGINAL_EVALUATE", pure_eval)
    monkeypatch.setattr(tb, "Blend", FakeBlend)
    monkeypatch.setattr(tb, "options", lambda: {"w_cnt": 0.65, "w_idp": 0.35})
    v = make_visum()
    act(v)
    adapter = SimpleNamespace(visum=v, invalidate_candidate_readback=lambda *a, **k: None,
                              v24916_dynamic_skims=None)
    control = SimpleNamespace(checkpoint=lambda *a, **k: None)
    return SimpleNamespace(v=v, adapter=adapter, control=control, folder=tmp_path, bridges=bridges)


def test_search_moves_trips_out_of_big_zone_and_restores_parent(search_env):
    e = search_env
    rep = iz.search(e.adapter, {}, e.folder / "IZ", e.control, "root")
    assert rep["status"] == "COMPLETED" and rep["changed"]
    assert rep["F_final"] < rep["F_start"] * 0.9
    p = float(rep["penalty_target"][0])
    assert 0.0 < p <= 15.0
    assert rep["shares_final"][0] < rep["shares_start"][0]
    assert rep["shares_final"][0] >= 0.40 - 1e-9
    assert iz.read_penalty(e.v).tolist() == [0.0]              # model left at the parent penalty
    assert not e.bridges[0].isolated                            # TD controls restored
    assert (e.folder / "IZ" / "V24917_IZ_SEARCH.json").is_file()
    assert rep["evaluations"] <= 1 + 3 * 4


def test_search_share_floor_binds(search_env, monkeypatch):
    e = search_env
    iz.STATE["options"] = dict(iz.STATE["options"], iz_min_intrazonal_share=0.88, iz_max_iterations=5)
    rep = iz.search(e.adapter, {}, e.folder / "IZ", e.control, "root")
    assert rep["shares_final"][0] >= 0.88 - 1e-6
    assert rep["shares_start"][0] > 0.88


def test_search_step_cap(search_env):
    e = search_env
    iz.STATE["options"] = dict(iz.STATE["options"], iz_max_step_min=1.0, iz_max_iterations=1)
    rep = iz.search(e.adapter, {}, e.folder / "IZ", e.control, "root")
    assert float(rep["penalty_target"][0]) <= 1.0 + 1e-9


def test_search_total_move_bounded_by_cycle_cap(search_env):
    """RBCONS1 audit: the search never optimises a penalty the realization would cap."""
    e = search_env
    iz.STATE["options"] = dict(iz.STATE["options"], iz_max_step_min=5.0, iz_max_iterations=3,
                               iz_max_cycle_change_min=1.5)
    rep = iz.search(e.adapter, {}, e.folder / "IZ", e.control, "root")
    assert rep["cycle_cap"] == 1.5
    assert float(rep["penalty_target"][0]) <= 1.5 + 1e-9
    iz.STATE["options"] = dict(iz.STATE["options"], iz_max_cycle_change_min=0.0)
    rep2 = iz.search(e.adapter, {}, e.folder / "IZ_NOCAP", e.control, "root")
    assert float(rep2["penalty_target"][0]) > 1.5


# ------------------------------------------------------------------ realization / rollback / install
class _Ctrl:
    """Minimal force100 controller surface used by _realize_with_penalty."""

    def __init__(self, gate_accepts):
        import r1_15a2_overnight_controller_coupled_v24915p2_force100 as real
        self.real = real
        self.gate_accepts = gate_accepts
        self.canonical_hash = real.canonical_hash
        self.number = real.number
        self._td_rows_at_scale = real._td_rows_at_scale
        self._td_expected_freeze = real._td_expected_freeze
        self._all_td_restore_rows = real._all_td_restore_rows
        self._is_retryable_td_realization_error = real._is_retryable_td_realization_error
        self.rollbacks = []
        self.assigned = []

    def _td_realization_scales(self, cfg):
        return [1.0, 0.5]

    def restore_td_parameters(self, adapter, before, rows, folder=None):
        adapter.bc = {r["component"]: (r["current_b"], r["current_c"]) for r in before["td_values"]}
        target = iz.penalty_from_snapshot(before)
        iz.write_penalty(adapter.visum, target, adapter)

    @contextlib.contextmanager
    def recovery_scope(self, control, name):
        yield

    def _assign_candidate(self, adapter, folder, block):
        self.assigned.append(iz.read_penalty(adapter.visum).tolist())
        return 0.001

    def atomic_json(self, path, payload):
        pass

    def _rollback_td_all(self, adapter, before, diag, folder, cfg):
        self.restore_td_parameters(adapter, before, [])
        self.rollbacks.append(folder)
        return adapter.snapshot(), {"rollback": True}


class _Adapter:
    def __init__(self, visum, ctrl):
        self.visum = visum
        self.ctrl = ctrl
        self.bc = {"WORK_E_C": (0.5, -0.3), "SERV_E_C": (0.4, -0.2)}
        self.gate_calls = []

    def invalidate_candidate_readback(self, *a, **k):
        pass

    def snapshot(self):
        td = [{"component": c, "status": "OK", "current_b": b, "current_c": cc}
              for c, (b, cc) in sorted(self.bc.items())]
        base = {"state_hash": "a" * 64, "matrices": [], "dseg_map": {}, "td_values": td,
                "fixed_link_hash": 1, "dseg_hash": 1, "operations_hash": 1, "addval_hash": 1,
                "generation_hash": 1}
        return iz.extend_snapshot(base, self.visum)

    def apply_td(self, rows):
        for r in rows:
            self.bc[r["component"]] = (r["candidate_b"], r["candidate_c"])

    def parameter_persistence(self, block, rows):
        pass

    def diagnostics(self, folder, label):
        return {"label": label}

    def block_gate(self, block, before, after, rows):
        self.gate_calls.append([r["component"] for r in rows])
        return {"accepted": self.ctrl.gate_accepts, "reasons": [] if self.ctrl.gate_accepts else ["X"]}


def test_realize_penalty_only_accepted_reports_noop_bc_row(act, tmp_path):
    v = make_visum()
    act(v)
    ctrl = _Ctrl(gate_accepts=True)
    ad = _Adapter(v, ctrl)
    before = ad.snapshot()
    stage = {"parent": np.array([0.0]), "target": np.array([6.0])}
    cfg = {"td_soft_reference_policy": {"enabled": True}}
    rows, after, diag, gap, ev = iz._realize_with_penalty(ctrl, ad, cfg, tmp_path, None, before, {}, [], stage)
    assert ev["status"] == "REALIZED" and ev["selected_scale"] == 1.0
    assert after[iz.SNAPSHOT_KEY] == {"1": 6.0} and iz.read_penalty(v).tolist() == [6.0]
    assert len(rows) == 1 and rows[0]["v24917_noop_bc_row_for_iz_penalty"]
    assert ad.gate_calls == [["SERV_E_C", "WORK_E_C"]]
    assert ad.bc == {"WORK_E_C": (0.5, -0.3), "SERV_E_C": (0.4, -0.2)}


def test_realize_with_bc_rows_scales_penalty_and_rolls_back_when_rejected(act, tmp_path):
    v = make_visum()
    act(v)
    ctrl = _Ctrl(gate_accepts=False)
    ad = _Adapter(v, ctrl)
    before = ad.snapshot()
    stage = {"parent": np.array([0.0]), "target": np.array([4.0])}
    target_rows = [{"component": "WORK_E_C", "candidate_b": 0.7, "candidate_c": -0.25}]
    cfg = {"td_soft_reference_policy": {"enabled": True}}
    rows, state, diag, gap, ev = iz._realize_with_penalty(ctrl, ad, cfg, tmp_path, None, before, {},
                                                          target_rows, stage)
    # combined (penalty follows the scale), then TDSPLIT1: b/c alone (parent penalty), penalty alone
    assert ctrl.assigned == [[4.0], [2.0], [0.0], [0.0], [4.0], [2.0]]
    assert rows == [] and ev["status"] == "SOFT_REFERENCE_PLATEAU" and ctrl.rollbacks
    assert iz.read_penalty(v).tolist() == [0.0] and ad.bc["WORK_E_C"] == (0.5, -0.3)


def test_install_wrappers(monkeypatch, act, tmp_path):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as tx
    import r1_15a2_active_controller_patch_v24916p2c as acp
    for obj, name in ((ctrl, "run_finecdf_inner"), (ctrl, "_realize_finecdf_td"), (ctrl, "_finecdf_td_once"),
                      (ctrl, "restore_td_parameters"), (tx, "restore_td_parameters"),
                      (acp, "targeted_run_finecdf_inner")):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    monkeypatch.setattr(iz, "_INSTALLED", {})
    calls = []
    monkeypatch.setattr(ctrl, "run_finecdf_inner", lambda *a, **k: {"changed_rows": [], "inner": True})
    monkeypatch.setattr(ctrl, "_realize_finecdf_td", lambda *a: calls.append("ORIG") or ("orig",))
    monkeypatch.setattr(tx, "restore_td_parameters", lambda adapter, before, rows, folder=None: calls.append("BC"))
    monkeypatch.setattr(ctrl, "restore_td_parameters", tx.restore_td_parameters)
    v = make_visum()
    act(v)
    iz.install(print_fn=lambda *a: None)
    # restore hook writes the parent penalty from the snapshot
    iz.write_penalty(v, [5.0])
    ctrl.restore_td_parameters(SimpleNamespace(visum=v), {iz.SNAPSHOT_KEY: {"1": 1.0}}, [])
    assert calls == ["BC"] and iz.read_penalty(v).tolist() == [1.0]
    assert tx.restore_td_parameters is ctrl.restore_td_parameters
    # inner wrapper: search result decides whether realization carries the penalty
    monkeypatch.setattr(iz, "search", lambda *a: {"status": "COMPLETED", "changed": True, "F_start": 1.0,
                                                  "F_final": 0.9, "evaluations": 4,
                                                  "penalty_parent": [1.0], "penalty_target": [3.0]})
    inner = ctrl.run_finecdf_inner(SimpleNamespace(visum=v), {}, tmp_path / "FINECDF_INNER", None, "root")
    assert inner["v24917_intrazonal_penalty"]["changed"] and iz._STAGE["target"].tolist() == [3.0]
    monkeypatch.setattr(iz, "_realize_with_penalty", lambda *a: ("iz",))
    assert ctrl._realize_finecdf_td(None, {}, tmp_path, None, {}, {}, []) == ("iz",)
    assert ctrl._realize_finecdf_td(None, {}, tmp_path, None, {}, {}, []) == ("orig",)   # stage consumed
    # search failure -> penalties unchanged, no stage, run continues
    monkeypatch.setattr(iz, "search", lambda *a: (_ for _ in ()).throw(ValueError("boom")))
    inner = ctrl.run_finecdf_inner(SimpleNamespace(visum=v), {}, tmp_path / "FINECDF_INNER", None, "root")
    assert inner["v24917_intrazonal_penalty"]["status"] == "ERROR_PENALTY_UNCHANGED" and not iz._STAGE


def test_iz_options_validation(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(tmp_path, environ={})
    assert o["iz_enabled"] is True and o["iz_matrix_no"] == 9002 and o["iz_min_intrazonal_share"] == 0.40
    o = dp.load_options(tmp_path, environ={"R1_IZ_ZONES": "611;612,615", "R1_IZ_ENABLED": "ne"})
    assert o["iz_zones"] == [611, 612, 615] and o["iz_enabled"] is False
    for bad in ({"iz_matrix_no": 9001}, {"iz_matrix_no": 9105}, {"iz_probe_min": 20, "iz_max_penalty_min": 10},
                {"iz_min_intrazonal_share": 0.99}, {"iz_max_iterations": 50}):
        with pytest.raises(RuntimeError):
            dp.validate(bad)


def test_search_two_zones_joint_jacobian(search_env, monkeypatch):
    e = search_env
    monkeypatch.setitem(SELF_MASS, 3, 40.0)
    monkeypatch.setattr(sys.modules[__name__], "COUNT_ZONES", [0, 3])
    monkeypatch.setattr(sys.modules[__name__], "OBS_OUT", 1200.0)
    U = BASE.copy(); U[3, 3] = 12.0
    for m in (e.v.mats[9001], e.v.mats[9002]):
        m.a = U.copy()
    iz.activate(e.v, dict(OPTS, iz_zones=[1, 4], iz_max_iterations=4), print_fn=lambda *a: None)
    rep = iz.search(e.adapter, {}, e.folder / "IZ2", e.control, "root")
    assert rep["status"] == "COMPLETED" and rep["changed"]
    assert rep["F_final"] < 0.5 * rep["F_start"]
    assert all(0.0 < float(x) <= 15.0 for x in rep["penalty_target"])
    it1 = rep["iterations"][0]
    assert it1["line_search"][0]["accepted"]           # first linearised step is already good


# ------------------------------------------------------------------ one-time setup script
class _Grav:
    def __init__(self, no):
        self.v = "Matrix([NO]=%d)" % no

    def AttValue(self, k):
        assert k == "UTILITYFUNCTION"
        return self.v

    def SetAttValue(self, k, val):
        assert k == "UTILITYFUNCTION"
        if not str(val).startswith("Matrix("):
            raise ValueError("format")
        self.v = str(val).replace(" ", "")


def _setup_visum():
    import importlib.util
    spec = importlib.util.spec_from_file_location("izsetup", ROOT / "R1_ADD_INTRAZONAL_IMPEDANCE_MATRIX.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    v = make_visum()
    del v.mats[9002]
    codes = mod.NATIVE_CODES + ["4_FOREIGN"]
    gravs = {c: _Grav(9001) for c in codes}
    class _NoUtil:                       # live Visum 2026: GRAVITATIONPARAMETERS has no UTILITYFUNCTION
        def AttValue(self, k):
            raise RuntimeError("GRAVITATIONPARAMETERS: Could not find attribute with ID %s." % k)

    class _DStrat(_Grav):
        GravitationParameters = _NoUtil()
    dstrats = {}
    for c in codes:
        d = _DStrat(9001)
        dstrats[c] = d
        gravs[c] = d
    params = SimpleNamespace(AttValue=lambda k: ",".join(codes),
                             TripDistributionDStratParameters=lambda c: dstrats[c])
    op = SimpleNamespace(AttValue=lambda k: 46.0, TripDistributionParameters=params)
    other = SimpleNamespace(AttValue=lambda k: 45.0)
    v.Procedures = SimpleNamespace(Operations=SimpleNamespace(GetAll=[other, op]))

    def add(no, otype=None, mtype=None):
        m = FakeMatrix(np.zeros((N, N)), mtype=mtype if mtype is not None else 3)
        m.att["OBJECTTYPEREF"] = otype if otype is not None else 2
        m.SetAttValue = lambda k, val: None
        v.mats[int(no)] = m
        return m
    v.Net.AddMatrix = add
    v.Net.RemoveMatrix = lambda m: v.mats.pop(next(k for k, x in v.mats.items() if x is m))
    names = [(i + 1, "Z%d" % (i + 1)) for i in range(N)]
    zones = v.Net.Zones.GetMultiAttValues
    v.Net.Zones.GetMultiAttValues = lambda a: names if a == "NAME" else zones(a)
    return mod, v, gravs


def test_setup_script_creates_copy_and_switches_native_strata(capsys):
    mod, v, gravs = _setup_visum()
    mod.Visum = v
    mod.main()
    assert np.array_equal(v.mats[9002].a, v.mats[9001].a) and v.mats[9002].att["MATRIXTYPE"] == 4
    assert all(iz.matrix_ref_no(gravs[c].v) == 9002 for c in mod.NATIVE_CODES)
    assert gravs["4_FOREIGN"].v == "Matrix([NO]=9001)"
    out = capsys.readouterr().out
    assert "HOTOVO" in out and "Zony pro paku" in out
    # second run: existing copy kept, strata already switched
    v.mats[9002].a[0, 0] += 3.0
    mod.main()
    assert v.mats[9002].a[0, 0] == pytest.approx(v.mats[9001].a[0, 0] + 3.0)


def test_runtime_utility_ref_reads_dstrat_first_then_gravity():
    class Bad:
        def AttValue(self, k):
            raise RuntimeError("no %s" % k)
    assert iz.utility_ref_of(_Grav(9002), Bad()) == 9002
    assert iz.utility_ref_of(Bad(), _Grav(9001)) == 9001
    assert iz.utility_ref_of(Bad(), Bad()) is None


# ------------------------------------------------------------------ ICONG1 congested TD impedance
IC_OPTS = dict(OPTS, ic_enabled=True, ic_mode="RATIO", ic_skim_dseg="NATIVE_CW", ic_start_model_obs_ratio=0.80,
               ic_start_cycle=0, ic_lambda=0.5, ic_ratio_max=4.0, ic_min_rel_change=0.002)


def _skims(cong=1.5):
    tt0 = BASE * 60.0
    ttc = tt0.copy()
    ttc[0, 1:] *= cong                   # congested exits of the big zone
    ttc[1, 2] = 0.0                      # no path -> OSRM kept
    return ttc, tt0


def test_congested_impedance_ratio_absolute_units_and_invalid_cells():
    ttc, tt0 = _skims(1.5)
    r = iz.congested_impedance(BASE, ttc, tt0, "RATIO", 4.0)
    assert r["unit"] == "s" and r["invalid_cells"] == 1
    assert r["U"][0, 3] == pytest.approx(BASE[0, 3] * 1.5) and r["U"][1, 2] == BASE[1, 2]
    assert r["U"][0, 0] == BASE[0, 0]
    a = iz.congested_impedance(BASE, ttc * 10, tt0, "ABSOLUTE", 4.0)
    assert a["U"][0, 3] == pytest.approx(BASE[0, 3] * 4.0)           # clipped at ratio_max
    m = iz.congested_impedance(BASE, ttc / 60.0, tt0 / 60.0, "RATIO", 4.0)
    assert m["unit"] == "min"
    with pytest.raises(iz.IZError):
        iz.congested_impedance(BASE, ttc * 1e3, tt0 * 1e3, "RATIO", 4.0)


def _diag(ratio):
    return {"d12": {"rows": [{"role": "CALIBRATION", "observed": 1000.0, "model": 1000.0 * ratio}]}}


def test_congestion_due_waits_for_late_phase_and_sticks(act):
    v = make_visum()
    act(v, opts=IC_OPTS)
    assert congestion_reason(_diag(0.5)) == "WAITING_FOR_LATE_PHASE"
    assert iz.congestion_due(_diag(0.85), 7)["due"] and iz.STATE["ic_start"]["outer_cycle"] == 7
    assert iz.congestion_due(_diag(0.5), 8)["due"]                   # once started it stays on
    iz.STATE["ic_started"] = False
    iz.STATE["options"] = dict(iz.STATE["options"], ic_start_cycle=10)
    assert iz.congestion_due(_diag(0.3), 10)["due"] and iz.STATE["ic_start"]["trigger"] == "OUTER_CYCLE"
    iz.STATE["options"] = dict(iz.STATE["options"], ic_enabled=False)
    assert not iz.congestion_due(_diag(0.9), 11)["due"]


def congestion_reason(d):
    return iz.congestion_due(d, 1)["reason"]


class _ICAdapter(_Adapter):
    def __init__(self, visum, ctrl):
        super().__init__(visum, ctrl)
        self.v24916_dynamic_skims = SimpleNamespace(
            require_current=lambda: SimpleNamespace(epoch=3, matrix_meta_by_dseg={}))
        self.transitions = []

    def accepted_state_changed(self, state, diag, reason, phase):
        self.transitions.append(reason)
        return {"reason": reason}


def _ic_env(act, monkeypatch, cong=1.5):
    v = make_visum()
    ttc, tt0 = _skims(cong)
    v.mats[9872], v.mats[9871] = FakeMatrix(ttc), FakeMatrix(tt0)
    monkeypatch.setattr(iz, "_skim_matrix_no", lambda visum, code, dseg, retry=None: 9872 if code == "TTC" else 9871)
    act(v, opts=IC_OPTS)
    ctrl = _Ctrl(gate_accepts=True)
    ctrl.restore_td_parameters = lambda adapter, before, rows, folder=None: iz.restore_from_snapshot(
        adapter.visum, before, adapter)
    ad = _ICAdapter(v, ctrl)
    return v, ctrl, ad


def test_congestion_feedback_blends_base_keeps_penalty_and_changes_state(act, monkeypatch, tmp_path):
    v, ctrl, ad = _ic_env(act, monkeypatch)
    iz.write_penalty(v, [3.0])
    before = ad.snapshot()
    st, dg, rec = iz.congestion_feedback(ctrl, ad, {}, tmp_path, None, before, _diag(0.85))
    assert rec["status"] == "APPLIED" and rec["applied"] and rec["unit"] == "s"
    M = v.mats[9002].a
    assert M[0, 3] == pytest.approx(BASE[0, 3] * (0.5 + 0.5 * 1.5))
    assert M[2, 4] == pytest.approx(BASE[2, 4]) and M[0, 0] == pytest.approx(BASE[0, 0] + 3.0)
    assert np.array_equal(v.mats[9001].a, BASE)
    assert st[iz.BASE_KEY] != before[iz.BASE_KEY] and st[iz.SNAPSHOT_KEY] == before[iz.SNAPSHOT_KEY]
    assert ctrl.assigned and ad.transitions == ["V24917_CONGESTED_TD_IMPEDANCE_FEEDBACK"]
    # rollback to the pre-feedback snapshot restores the OSRM base (and keeps the penalty)
    iz.restore_from_snapshot(v, before, ad)
    assert v.mats[9002].a[0, 3] == pytest.approx(BASE[0, 3]) and iz.read_penalty(v).tolist() == [3.0]
    # second step moves half of the remaining gap (MSA lambda 0.5)
    iz.restore_from_snapshot(v, st, ad)
    st2, _d, rec2 = iz.congestion_feedback(ctrl, ad, {}, tmp_path / "2", None, st, _diag(0.85))
    assert v.mats[9002].a[0, 3] == pytest.approx(BASE[0, 3] * (0.25 + 0.75 * 1.5))
    assert rec2["update_index"] == 2


def test_congestion_feedback_converged_and_failure_rollback(act, monkeypatch, tmp_path):
    v, ctrl, ad = _ic_env(act, monkeypatch, cong=1.0)
    before = ad.snapshot()
    st, dg, rec = iz.congestion_feedback(ctrl, ad, {}, tmp_path, None, before, _diag(0.9))
    assert rec["status"] == "CONVERGED_NO_WRITE" and st is before and not ctrl.assigned
    v2, ctrl2, ad2 = _ic_env(act, monkeypatch, cong=2.0)
    before2 = ad2.snapshot()
    ctrl2._assign_candidate = lambda *a: (_ for _ in ()).throw(RuntimeError("IPF"))
    st2, dg2, rec2 = iz.congestion_feedback(ctrl2, ad2, {}, tmp_path / "f", None, before2, _diag(0.9))
    assert rec2["status"] == "FAILED_ROLLED_BACK" and ctrl2.rollbacks
    assert v2.mats[9002].a[0, 3] == pytest.approx(BASE[0, 3]) and st2[iz.BASE_KEY] == before2[iz.BASE_KEY]


def test_activation_restart_with_congested_base(act):
    v = make_visum()
    v.mats[9002].a[0, 3] *= 1.3
    assert "OFFDIAGONAL" in act(v)["reason"]                         # without ICONG1: refused
    st = act(v, opts=IC_OPTS)
    assert st["active"] and st["base_source"].endswith("CONGESTED_RESTART") and st["ic_started"]
    assert iz.read_penalty(v).tolist() == [0.0]


def test_td_once_wrapper_runs_feedback_before_td(monkeypatch, act, tmp_path):
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_inplace_transaction_v24915p2 as tx
    import r1_15a2_active_controller_patch_v24916p2c as acp
    for obj, name in ((ctrl, "run_finecdf_inner"), (ctrl, "_realize_finecdf_td"), (ctrl, "_finecdf_td_once"),
                      (ctrl, "restore_td_parameters"), (tx, "restore_td_parameters"),
                      (acp, "targeted_run_finecdf_inner")):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    monkeypatch.setattr(iz, "_INSTALLED", {})
    seen = []
    monkeypatch.setattr(ctrl, "_finecdf_td_once", lambda a, c, f, k, state, diag, p, outer_cycle=None:
                        seen.append(state["tag"]) or (False, state, diag, {"td_realization_complete": True}))
    v = make_visum()
    act(v, opts=IC_OPTS)
    iz.install(print_fn=lambda *a: None)
    monkeypatch.setattr(iz, "congestion_feedback", lambda c, a, cfg, f, k, s, d: (
        dict(s, tag="AFTER_FEEDBACK"), d, {"applied": True, "status": "APPLIED"}))
    ch, st, dg, rec = ctrl._finecdf_td_once(None, {}, tmp_path, None, {"tag": "PARENT"}, _diag(0.9), "r",
                                            outer_cycle=5)
    assert seen == ["AFTER_FEEDBACK"] and ch is True and rec["v24917_congested_impedance"]["applied"]
    ch, st, dg, rec = ctrl._finecdf_td_once(None, {}, tmp_path, None, {"tag": "PARENT"}, _diag(0.2), "r",
                                            outer_cycle=6)
    assert seen[-1] == "AFTER_FEEDBACK"                              # started -> stays on
    import inspect
    assert "outer_cycle" in inspect.signature(ctrl._finecdf_td_once).parameters


def test_ic_options_validation(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(tmp_path, environ={})
    assert o["ic_enabled"] is True and o["ic_mode"] == "RATIO" and o["ic_start_model_obs_ratio"] == 0.80
    for bad in ({"ic_mode": "TCUR"}, {"ic_lambda": 0.0}, {"ic_ratio_max": 1.0}, {"ic_start_cycle": 200}):
        with pytest.raises(RuntimeError):
            dp.validate(bad)


# ------------------------------------------------------------------ CALLSIG1: real controller call shapes
def test_callsig_wrapped_controller_functions_accept_live_call_shapes(monkeypatch, act):
    """Live run 20261025_175302 died: _generation_counts_cfg() got an unexpected keyword 'outer_cycle'."""
    import json
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_finecdf_bridge_v24916 as bm
    import r1_15a2_td_count_blend_v24917 as tb
    import r1_15a2_inplace_transaction_v24915p2 as tx
    import r1_15a2_active_controller_patch_v24916p2c as acp
    for obj, name in ((bm.DynamicFamilyMetrics, "evaluate"), (bm.NoDirectMatrixWriteTDAdapter, "execute"),
                      (ctrl, "_generation_counts_cfg"), (ctrl, "_td_realization_scales"),
                      (ctrl, "_finecdf_budget_for_cycle"), (ctrl, "run_finecdf_inner"),
                      (ctrl, "_realize_finecdf_td"), (ctrl, "_finecdf_td_once"), (ctrl, "restore_td_parameters"),
                      (tx, "restore_td_parameters"), (acp, "targeted_run_finecdf_inner")):
        monkeypatch.setattr(obj, name, getattr(obj, name))
    monkeypatch.setattr(tb, "_STATE", {})
    monkeypatch.setattr(iz, "_INSTALLED", {})
    cfg = json.loads((ROOT / "tests" / "data" / "EFFECTIVE_CONFIG_RUN_20261025_175302.json").read_text("utf-8"))
    tb.install(print_fn=lambda *a: None)
    act(make_visum())
    st = iz.install(print_fn=lambda *a: None)
    # exact call shapes used by r1_15a2_overnight_controller_coupled_v24915p2_force100
    g1 = ctrl._generation_counts_cfg(cfg, outer_cycle=1)
    g2 = ctrl._generation_counts_cfg(cfg)
    limits = tb.options()
    assert len(g1["backtracking_scales"]) <= limits["tg_max_trials"] and g1["backtracking_scales"] == g2["backtracking_scales"]
    assert ctrl._td_realization_scales(cfg)[0] == 1.0 and len(ctrl._td_realization_scales(cfg)) <= limits["td_realization_max_trials"]
    b = ctrl._finecdf_budget_for_cycle(cfg, 3)
    assert not b or int(b["max_td_evaluations"]) <= limits["td_inner_max_evaluations"]
    # the V24916 dispatch calls its own module-level import of the inner search
    assert getattr(acp.targeted_run_finecdf_inner, "_v24917_iz", False)
    assert "r1_15a2_active_controller_patch_v24916p2c.targeted_run_finecdf_inner" in st["inner_dispatch_patched"]
    import inspect
    assert "outer_cycle" in inspect.signature(ctrl._finecdf_td_once).parameters


def test_congestion_only_without_iz_zones(act, monkeypatch, tmp_path):
    """iz_enabled=false + ic_enabled=true: empty penalty vector must not break M9002 writes."""
    v = make_visum()
    ttc, tt0 = _skims(1.5)
    v.mats[9872], v.mats[9871] = FakeMatrix(ttc), FakeMatrix(tt0)
    monkeypatch.setattr(iz, "_skim_matrix_no", lambda visum, code, dseg, retry=None: 9872 if code == "TTC" else 9871)
    st = act(v, opts=dict(IC_OPTS, iz_enabled=False))
    assert st["active"] and st["zones"] == []
    assert iz.read_penalty(v).size == 0 and iz.write_penalty(v, []).size == 0
    ctrl = _Ctrl(gate_accepts=True)
    ad = _ICAdapter(v, ctrl)
    before = ad.snapshot()
    assert before[iz.SNAPSHOT_KEY] == {}
    st2, _d, rec = iz.congestion_feedback(ctrl, ad, {}, tmp_path, None, before, _diag(0.9))
    assert rec["status"] == "APPLIED" and v.mats[9002].a[0, 3] == pytest.approx(BASE[0, 3] * 1.25)
    iz.restore_from_snapshot(v, before, ad)
    assert v.mats[9002].a[0, 3] == pytest.approx(BASE[0, 3])
