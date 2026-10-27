"""BDPA1: the Generation P/A balance (projection rebalance + apply gate) includes BNDGEN1 rows."""
from __future__ import annotations

import copy
import math

import numpy as np
import pytest

import r1_15a2_zonal_count_fit_v24917 as zf
import r1_15a2_targeted_generation_v24917 as tg
import r1_15a2_boundary_generation_v24917 as bdgen
import r1_15a2_boundary_pa_v24917 as bdpa
from test_v24917_targeted_catchup import synthetic_incidence, zone_rows, mb, real_cfg  # noqa: F401


@pytest.fixture
def mbp(mb, monkeypatch):
    for name in ("design_generation_candidates", "_constrain_generation_projection"):
        monkeypatch.setattr(mb, name, getattr(mb, name))
    monkeypatch.setitem(bdpa._STATE, "installed", False)
    bdpa.install(print_fn=lambda *a: None)
    yield mb
    bdpa._STATE["installed"] = False


def _fit_with_boundary(mb, cfg, boundary_zone=12):
    inc, zones = synthetic_incidence(n_zones=12, residual_factor=3.0)
    zr = zone_rows([z for z in zones if z != boundary_zone], value=1.9)
    bounds = tg.zone_bounds(mb, zr, cfg)
    for fam in zf.FAMILIES:
        for role in zf.ROLES:
            bounds[(fam, role, boundary_zone)] = (-0.2, 0.4)
    problem = zf.build_problem(inc, zones, bounds, cfg)
    margins = bdpa.margins_from_problem(problem, [boundary_zone])
    problem = bdgen.merge_pa(problem, [boundary_zone])
    sol = zf.solve(problem, tg.DEFAULT_POLICY["fit"])
    rows = zf.projection_rows(problem, sol, 1e-5)
    dom, steps = bdgen.split_rows(rows)
    bd = bdgen.design_payload(steps, {})
    bd["margins"] = {k: v for k, v in margins.items() if k in bd["steps"]}
    return dom, zr, bd


def _shift_attraction_to_boundary(dom, bd, factor=0.03):
    """Live situation: the crossings carry most of the attraction growth."""
    rows = []
    removed = {}
    for r in dom:
        r = dict(r)
        if r["role"] == "ATT" and r["log_step"] > 0:
            b = float(r["base_margin_volume"])
            new = r["log_step"] * factor
            removed[r["family"]] = removed.get(r["family"], 0.0) + b * (math.expm1(r["log_step"]) - math.expm1(new))
            r["log_step"] = new
            r["requested_log_step"] = new
            r["guided_margin_delta"] = r["projected_margin_delta"] = b * math.expm1(new)
        rows.append(r)
    bd = copy.deepcopy(bd)
    for fam, amount in removed.items():
        key = "%s|999" % fam
        bd["steps"][key] = 0.3
        bd["margins"][key] = {"PROD": 0.0, "ATT": amount / math.expm1(0.3)}
    return rows, bd


def test_margins_and_pa_delta():
    bd = {"steps": {"WORK|5": math.log(1.5)}, "margins": {"WORK|5": {"PROD": 100.0, "ATT": 300.0}}}
    d = bdpa.pa_delta(bd, 1.0)
    # BALANCE1: crossing P and A move together -> mean margin on both sides
    assert d["WORK"]["prod"] == pytest.approx(100.0) and d["WORK"]["att"] == pytest.approx(100.0)
    assert bdpa.pa_delta(bd, 0.0)["WORK"]["att"] == pytest.approx(0.0)
    assert bdpa.pa_delta({"steps": {"WORK|5": 0.1}}, 1.0) == {}          # old payload without margins


def test_symmetric_boundary_keeps_domestic_balance_and_reports_parts(mbp, real_cfg):
    """With the crossings trip-end neutral, BDPA1 only adds equal P/A parts to the gate totals."""
    import R1_15A2_ACTUAL_PATH_MULTIBLOCK_CALIBRATION_MASTER_V2_1 as master
    cfg = tg.overlay_cfg(real_cfg, "CATCH_UP")
    dom, zr, bd = _fit_with_boundary(mbp, cfg)
    plain = mbp.design_generation_candidates(dom, zr, cfg, scale=0.85)
    with bdpa.scope(bd):
        design = mbp.design_generation_candidates(dom, zr, cfg, scale=0.85)
    s = design["summary"]
    for fam, part in s["v24917_boundary_pa_delta_by_family"].items():
        assert part["prod"] == pytest.approx(part["att"])
    assert master.generation_apply_gate(copy.deepcopy(plain), cfg)["passes"]
    assert master.generation_apply_gate(copy.deepcopy(design), cfg)["passes"]


def test_no_scope_unchanged(mbp, real_cfg):
    cfg = tg.overlay_cfg(real_cfg, "CATCH_UP")
    dom, zr, bd = _fit_with_boundary(mbp, cfg)
    a = mbp.design_generation_candidates(dom, zr, cfg, scale=1.0)
    assert "v24917_pa_balance_scope" not in a["summary"]
    with bdpa.scope({"steps": bd["steps"]}):                 # payload without margins -> inactive
        b = mbp.design_generation_candidates(dom, zr, cfg, scale=1.0)
    assert "v24917_pa_balance_scope" not in b["summary"]
    assert a["summary"]["estimated_pa_delta_by_family"] == b["summary"]["estimated_pa_delta_by_family"]


def test_fit_balance_equals_total_with_boundary(mbp, real_cfg):
    """The joint fit balances domestic + crossings; BDPA1 accounting reproduces that balance."""
    cfg = tg.overlay_cfg(real_cfg, "CATCH_UP")
    dom, zr, bd = _fit_with_boundary(mbp, cfg)
    p = sum(r["base_margin_volume"] * r["log_step"] for r in dom if r["role"] == "PROD")
    a = sum(r["base_margin_volume"] * r["log_step"] for r in dom if r["role"] == "ATT")
    bp = sum(bd["margins"][k].get("PROD", 0.0) * s for k, s in bd["steps"].items())
    ba = sum(bd["margins"][k].get("ATT", 0.0) * s for k, s in bd["steps"].items())
    assert abs((p + bp) - (a + ba)) <= 0.05 * max(abs(p + bp), abs(a + ba), 1.0)
