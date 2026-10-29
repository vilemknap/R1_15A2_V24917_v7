# -*- coding: utf-8 -*-
"""BNDGEN1 border-crossing P/A lever + the one-off X1-X31 uplift script."""
import gzip
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import r1_15a2_boundary_generation_v24917 as bd  # noqa: E402
import r1_15a2_zonal_count_fit_v24917 as zf  # noqa: E402
from test_v24917_targeted_catchup import synthetic_incidence  # noqa: E402


@pytest.fixture
def bdstate(monkeypatch):
    monkeypatch.setattr(bd, "STATE", {"active": True, "zones": [10]})
    return bd.STATE


def test_attr_catalogue():
    assert bd.attrs_for("WORK", "P")[0] == "P09F4_PER_PRE_WORK_E_C"
    assert bd.attrs_for("SERVICE", "A")[-1] == "A09F4_PER_PRE_SERV_stud"
    assert len(bd.ALL_ATTRS) == 20 and not any("FOREIGN" in a or "LONG" in a for a in bd.ALL_ATTRS)


def test_bounds_caps_and_envelope(bdstate):
    cur = {a: {10: 4.0} for a in bd.ALL_ATTRS}                 # 4x the run-start value ...
    ref = {a: {"10": 1.0} for a in bd.ALL_ATTRS}               # ... of the run-start value 1.0
    cfg = {"max_add_log_up": math.log(1.5), "max_add_log_down": -math.log(0.8)}
    b = bd.bounds(cur, ref, cfg, [0.25, 5.0])
    lo, hi = b[("WORK", "PROD", 10)]
    assert hi == pytest.approx(math.log(5.0 / 4.0))             # envelope x5 binds before +50 %
    assert lo == pytest.approx(math.log(0.8))
    assert b[("WORK", "ATT", 10)] == (lo, hi)
    b2 = bd.bounds(cur, None, cfg, [0.25, 5.0])                # reference = current
    assert b2[("SERVICE", "PROD", 10)][1] == pytest.approx(math.log(1.5))


def _bounds_with_boundary(zones, bzone, lo=-0.2, hi=0.4, domestic=True):
    out = {}
    for f in zf.FAMILIES:
        for r in zf.ROLES:
            for z in zones:
                if z == bzone or domestic:
                    out[(f, r, z)] = (lo, hi)
    return out


def test_merge_pa_sums_columns_and_balance(bdstate):
    inc, zones = synthetic_incidence(n_zones=10)
    p0 = zf.build_problem(inc, zones, _bounds_with_boundary(zones, 10), {})
    p1 = bd.merge_pa(p0, [10])
    assert len(p1.var_keys) == len(p0.var_keys) - 2 and p1.boundary_variables == 2
    i = p1.var_keys.index(("WORK", "PA", 10))
    gp, ga = p0.var_keys.index(("WORK", "PROD", 10)), p0.var_keys.index(("WORK", "ATT", 10))
    assert np.allclose(p1.G[:, i], p0.G[:, gp] + p0.G[:, ga])
    vec, _ = p1.balance_vectors["WORK"]
    v0, _ = p0.balance_vectors["WORK"]
    assert vec[i] == 0.0                     # BALANCE1: crossing P+A together is trip-end neutral
    # untouched domestic columns identical
    j0 = p0.var_keys.index(("SERVICE", "ATT", 3)); j1 = p1.var_keys.index(("SERVICE", "ATT", 3))
    assert np.allclose(p0.G[:, j0], p1.G[:, j1])


def test_joint_fit_raises_underloaded_crossing(bdstate):
    inc, zones = synthetic_incidence(n_zones=10, residual_factor=1.0)
    inc["profiles"][8]["observed"] *= 3.0                       # deficit next to the crossing (zone 10)
    bounds = _bounds_with_boundary(zones, 10, domestic=False)   # only the crossing can act
    p = bd.merge_pa(zf.build_problem(inc, zones, bounds, {}), [10])
    sol = zf.solve(p, {})
    rows = zf.projection_rows(p, sol)
    dom, steps = bd.split_rows(rows)
    assert not dom and steps[("WORK", 10)] > 0.05 and steps[("SERVICE", 10)] > 0.05


def test_rows_at_scale_and_payload(bdstate):
    cur = {a: {10: (2.0 if a.startswith("P09F4") else 2.5)} for a in bd.ALL_ATTRS}
    cur["P09F4_PER_PRE_WORK_stud"][10] = 0.0                    # zero layer stays zero
    payload = bd.design_payload({("WORK", 10): 0.3}, cur)
    rows = bd.rows_at_scale(json.loads(json.dumps(payload)), 0.5)
    assert len(rows) == 9 and all(r["branch"] == "BOUNDARY" for r in rows)
    r = next(r for r in rows if r["attr"] == "A09F4_PER_PRE_WORK_E_C")
    assert r["proposed"] == pytest.approx(2.5 * math.exp(0.15)) and r["role"] == "ATT"
    assert not any(r["attr"].startswith(("P09F4_PER_PRE_SERV", "A09F4_PER_PRE_SERV")) for r in rows)
    assert bd.rows_at_scale(None, 1.0) == []


class FakeZones:
    def __init__(self, n=681, x_value=10.0, names=True):
        self.n = n
        self.vals = {"NO": {k: float(k) for k in range(1, n + 1)},
                     "NAME": {k: ("X%d" % (k - 649) if 650 <= k <= 680 and names else "Z%d" % k)
                              for k in range(1, n + 1)}}
        layers = ["LONG_E_C", "LONG_E_noC", "LONG_noE_C", "LONG_noE_noC", "LONG_stud", "SCHOOL",
                  "SERV_E_C", "SERV_E_noC", "SERV_noE_C", "SERV_noE_noC", "SERV_stud",
                  "WORK_E_C", "WORK_E_noC", "WORK_noE_C", "WORK_noE_noC", "WORK_stud", "FOREIGN"]
        for pre in ("P09F4_PER_PRE_", "A09F4_PER_PRE_"):
            for l in layers:
                self.vals[pre + l] = {k: (x_value if 650 <= k <= 680 or k in (608, 615) else 0.0)
                                      for k in range(1, n + 1)}
        self.fail_on = None

    def GetMultiAttValues(self, attr, *a):
        if attr not in self.vals:
            raise RuntimeError("Could not find attribute with ID " + attr)
        return [(k, v) for k, v in sorted(self.vals[attr].items())]

    def SetMultiAttValues(self, attr, pairs, *a):
        if self.fail_on == attr:
            self.fail_on = None                            # transient: the rollback write succeeds
            for k, v in pairs[:3]:
                self.vals[attr][k] = -1.0                  # half-written
            raise RuntimeError("COM write failed")
        for k, v in pairs:
            self.vals[attr][k] = float(v)


def _visum(tmp_path, zones):
    ver = tmp_path / "model.ver"
    ver.write_text("x")
    return SimpleNamespace(Net=SimpleNamespace(Zones=zones), AttValue=lambda a: str(ver),
                           GetPath=lambda i: str(tmp_path), Log=lambda *a: None)


def test_activate_extends_generation_attrs(monkeypatch):
    import r1_15a2_multiblock as mb
    monkeypatch.setattr(mb, "GENERATION_ATTRS", list(mb.GENERATION_ATTRS))
    monkeypatch.setattr(bd, "STATE", {"active": False})
    monkeypatch.setattr(bd, "options", lambda: {"bd_enabled": True, "bd_zones": list(range(650, 681))})
    v = SimpleNamespace(Net=SimpleNamespace(Zones=FakeZones()))
    st = bd.activate(v)
    assert st["active"] and st["zones"] == list(range(650, 681))
    assert all(a in mb.GENERATION_ATTRS for a in bd.ALL_ATTRS)
    assert st["ws_total_p"] == pytest.approx(31 * 10 * 10.0)
    monkeypatch.setattr(bd, "STATE", {"active": False})
    v2 = SimpleNamespace(Net=SimpleNamespace(Zones=SimpleNamespace(
        GetMultiAttValues=lambda *a: (_ for _ in ()).throw(RuntimeError("no attr")))))
    assert bd.activate(v2)["active"] is False                   # never raises


def _script(dry):
    ns = {"__r1_test__": True, "__name__": "__main__"}
    src = (ROOT / ("R1_BOUNDARY_X_PA_UPLIFT_DRY_RUN.py" if dry else "R1_BOUNDARY_X_PA_UPLIFT_APPLY.py")).read_text(encoding="utf-8")
    exec(compile(src, "uplift", "exec"), ns)
    ns["SHOW_MESSAGE_BOX"] = False
    return ns


def _graded_zones():
    z = FakeZones()
    for a in z.vals:
        if a.startswith(("P09F4", "A09F4")) and not a.endswith("FOREIGN"):
            z.vals[a][650] = 500.0           # X1: 16 layers x 500 = 8000 -> x2
            z.vals[a][651] = 50.0            # X2: 800 -> graded
            z.vals[a][652] = 10.0            # X3: 160 -> x8
            z.vals[a][653] = 0.0             # X4: empty stays empty
    return z


def test_factor_rule():
    ns = _script(True)
    f = ns["factor_for"]
    assert f(100.0) == 8.0 and f(300.0) == 8.0 and f(2000.0) == 2.0 and f(9000.0) == 2.0 and f(0.0) == 1.0
    assert f(1000.0) == pytest.approx(8.0 * 0.25 ** (math.log(1000 / 300) / math.log(2000 / 300)))
    assert 2.0 < f(800.0) < 8.0 and f(500.0) > f(1000.0)


def test_uplift_dry_run_writes_nothing(tmp_path):
    z = _graded_zones()
    ns = _script(True)
    assert ns["main"](_visum(tmp_path, z)) == "PASS_DRY_RUN_NOTHING_WRITTEN"
    assert z.vals["P09F4_PER_PRE_WORK_E_C"][650] == 500.0
    d = next((tmp_path / "R1_BOUNDARY_X_PA_UPLIFT").glob("DRYRUN_*"))
    txt = (d / "02_ZONE_TOTALS.csv").read_text(encoding="utf-8-sig")
    assert "650;X1;8000.0;2.0;16000.0" in txt and "652;X3;160.0;8.0;1280.0" in txt


def test_uplift_apply_graded_crossings_only_and_refuses_repeat(tmp_path):
    z = _graded_zones()
    ns = _script(False)
    v = _visum(tmp_path, z)
    assert ns["main"](v) == "PASS_APPLIED_NOT_SAVED"
    f2 = ns["factor_for"](800.0)
    assert z.vals["P09F4_PER_PRE_WORK_E_C"][650] == pytest.approx(1000.0)      # x2
    assert z.vals["A09F4_PER_PRE_SCHOOL"][651] == pytest.approx(50.0 * f2)     # graded, P and A alike
    assert z.vals["P09F4_PER_PRE_SCHOOL"][651] == pytest.approx(50.0 * f2)
    assert z.vals["P09F4_PER_PRE_WORK_E_C"][652] == pytest.approx(80.0)        # x8
    assert z.vals["P09F4_PER_PRE_WORK_E_C"][653] == 0.0
    assert z.vals["P09F4_PER_PRE_WORK_E_C"][615] == 10.0                       # district untouched
    assert z.vals["P09F4_PER_PRE_FOREIGN"][650] == 10.0                        # FOREIGN untouched
    bk = next((tmp_path / "R1_BOUNDARY_X_PA_UPLIFT").glob("APPLY_*/BACKUP_BEFORE.json.gz"))
    assert json.loads(gzip.open(str(bk)).read())["values"]["P09F4_PER_PRE_WORK_E_C"]["650"] == 500.0
    assert ns["main"](v) == "FAILED"                                           # second uplift refused
    assert z.vals["P09F4_PER_PRE_WORK_E_C"][650] == pytest.approx(1000.0)


def test_uplift_apply_rolls_back_on_write_error(tmp_path):
    z = _graded_zones()
    z.fail_on = "A09F4_PER_PRE_LONG_E_C"
    ns = _script(False)
    assert ns["main"](_visum(tmp_path, z)) == "FAILED_ROLLED_BACK"
    for a in ("P09F4_PER_PRE_WORK_E_C", "A09F4_PER_PRE_LONG_E_C"):
        assert z.vals[a][650] == 500.0 and z.vals[a][1] == 0.0


def test_uplift_refuses_wrong_zone_names(tmp_path):
    z = FakeZones(names=False)
    ns = _script(False)
    assert ns["main"](_visum(tmp_path, z)) == "FAILED"
    assert z.vals["P09F4_PER_PRE_WORK_E_C"][650] == 10.0


def test_uplift_output_folder_fallback(tmp_path, monkeypatch):
    z = _graded_zones()
    ns = _script(True)
    ns["__file__"] = str(tmp_path / "scripts" / "R1_BOUNDARY_X_PA_UPLIFT_DRY_RUN.py")
    (tmp_path / "scripts").mkdir()
    v = SimpleNamespace(Net=SimpleNamespace(Zones=z), Log=lambda *a: None,
                        AttValue=lambda a: (_ for _ in ()).throw(RuntimeError("no VERSIONFILE")),
                        GetPath=lambda i: (_ for _ in ()).throw(RuntimeError("no path")))
    assert ns["main"](v) == "PASS_DRY_RUN_NOTHING_WRITTEN"
    assert list((tmp_path / "scripts" / "R1_BOUNDARY_X_PA_UPLIFT").glob("DRYRUN_*/02_ZONE_TOTALS.csv"))


def test_adapter_fit_with_boundary(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as a17
    bd = a17.bdgen                       # the module object the adapter actually uses
    monkeypatch.setattr(bd, "STATE", {"active": True, "zones": [10]})
    inc, zones = synthetic_incidence(n_zones=10, residual_factor=1.0)
    inc["profiles"][8]["observed"] *= 3.0
    cur = {a: {10: 5.0} for a in bd.ALL_ATTRS}
    monkeypatch.setattr(bd, "current_values", lambda visum, zs: cur)
    ad = a17.VisumAdapter.__new__(a17.VisumAdapter)
    ad.zones = zones; ad.visum = None; ad.generation_reference_values = None
    dom_bounds = {(f, r, z): (-0.2, 0.4) for f in zf.FAMILIES for r in zf.ROLES for z in zones if z != 10}
    cfg = {"max_add_log_up": math.log(1.5), "max_add_log_down": -math.log(0.8)}
    rows, summary, problem, sol, payload = ad._fit_with_boundary(inc, dom_bounds, cfg, {"fit": {}})
    assert all(r["role"] in ("PROD", "ATT") for r in rows)
    assert payload["summary"]["boundary_variables_in_fit"] == 2
    assert float(payload["steps"]["WORK|10"]) > 0
    assert len(problem.var_keys) == len(dom_bounds) + 2
    assert summary["boundary"]["zones"] == [10]
    # BDPA1: boundary trip-end margins travel with the payload
    assert set(payload["margins"]) == set(payload["steps"])
    assert all(m.get("PROD", 0) > 0 and m.get("ATT", 0) > 0 for m in payload["margins"].values())
    import r1_15a2_boundary_pa_v24917 as bdpa
    d = bdpa.pa_delta(payload, 1.0)
    assert set(d) == {k.split("|")[0] for k in payload["steps"]}
    # STEP1 linear model includes the crossing contribution
    sm = a17.VisumAdapter._step_model(problem, sol, None)
    assert len(sm["delta_full"]) == len(problem.profile_rows)
    monkeypatch.setattr(bd, "STATE", {"active": False})
    rows2, *_rest, payload2 = ad._fit_with_boundary(inc, dom_bounds, cfg, {"fit": {}})
    assert payload2 is None


def test_zahr_envelope_expansion_does_not_expand_boundary_volume_band(monkeypatch):
    import r1_15a2_trial_adapter_v24917 as adapter
    import r1_15a2_targeted_generation_v24917 as tg
    boundary = adapter.bdgen  # launch tests can replace the collected module instance
    monkeypatch.setattr(boundary, 'STATE', {'active': True, 'zones': [650]})
    monkeypatch.setattr(boundary, 'current_values', lambda *args: {})
    seen = []
    class Captured(Exception):
        pass
    def inspect_bounds(current, references, cfg, envelope):
        seen.append(envelope)
        raise Captured()
    monkeypatch.setattr(boundary, 'bounds', inspect_bounds)
    obj = SimpleNamespace(visum=object(), generation_reference_values={})
    policy = tg.validate_policy(tg.DEFAULT_POLICY)
    assert policy['envelope']['zahr_reference_multiplier'] == [.5, 10.]
    with pytest.raises(Captured):
        adapter.VisumAdapter._fit_with_boundary(obj, {}, {}, {}, policy)
    assert seen == [[.5, 2.]]
