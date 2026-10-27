"""MOBILITY1: aggregate trip rate per family within the mobility-survey band."""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import r1_15a2_mobility_guard_v24917 as mg  # noqa: E402

OPTS = {"enabled": True, "lo": 0.75, "hi": 1.25}


def zones(mult_w=1.0, mult_s=1.0, n=10, zahr=()):
    out = []
    for z in range(1, n + 1):
        r = {"zone_no": z, "NOT_ZAHR": 0.0 if z in zahr else 1.0, "ADD_PROD_W": mult_w, "ADD_PROD_S": mult_s}
        for g in mg.GROUPS:
            r["FP_1_WORK_%s" % g] = 10.0 * z * mult_w          # FP already includes the multiplier
            r["FP_2_SERVICE_%s" % g] = 20.0 * z * mult_s
        out.append(r)
    return out


def rows(step_w, step_s=0.0, n=10):
    out = []
    for z in range(1, n + 1):
        for fam, s in (("WORK", step_w), ("SERVICE", step_s)):
            out.append({"zone_no": z, "family": fam, "role": "PROD", "log_step": s,
                        "base_margin_volume": 100.0, "multiplier": math.exp(s)})
            out.append({"zone_no": z, "family": fam, "role": "ATT", "log_step": s,
                        "base_margin_volume": 100.0, "multiplier": math.exp(s)})
    return out


def test_ratio_is_trip_rate_over_survey():
    assert mg.ratio(mg.zone_productions(zones(1.0), "WORK")) == pytest.approx(1.0)
    assert mg.ratio(mg.zone_productions(zones(1.2), "WORK")) == pytest.approx(1.2)
    zr = zones(1.0, zahr=(3,))
    assert 3 not in mg.zone_productions(zr, "WORK")


def test_full_step_attenuated_to_upper_band_and_attractions_untouched():
    out, rep = mg.guard(rows(math.log(1.5)), zones(1.1), OPTS)       # 1.1 * 1.5 = 1.65 > 1.25
    w = rep["families"]["WORK"]
    assert w["status"] == "ATTENUATED" and w["ratio_after"] == pytest.approx(1.25, abs=1e-6)
    prod = [r for r in out if r["family"] == "WORK" and r["role"] == "PROD"]
    att = [r for r in out if r["family"] == "WORK" and r["role"] == "ATT"]
    assert all(r["log_step"] == pytest.approx(math.log(1.25 / 1.1)) for r in prod)
    assert all(r["log_step"] == pytest.approx(math.log(1.5)) for r in att)
    assert rep["families"]["SERVICE"]["status"] == "WITHIN_BAND"


def test_outside_band_may_not_move_further_but_may_return():
    out, rep = mg.guard(rows(0.2, -0.1), zones(1.4, 1.4), OPTS)       # already 1.4 > 1.25
    assert rep["families"]["WORK"]["status"] == "ATTENUATED"
    assert rep["families"]["WORK"]["ratio_after"] == pytest.approx(1.4, abs=1e-6)
    assert rep["families"]["SERVICE"]["status"] == "OUTSIDE_BAND_NOT_MOVING_AWAY"
    out, rep = mg.guard(rows(-0.5), zones(1.0), OPTS)                 # 0.61 < 0.75
    assert rep["families"]["WORK"]["ratio_after"] == pytest.approx(0.75, abs=1e-6)


def test_disabled_and_missing_attributes():
    r = rows(1.0)
    out, rep = mg.guard(r, zones(1.0), dict(OPTS, enabled=False))
    assert rep["status"] == "DISABLED" and out is r
    bad = [{"zone_no": 1, "NOT_ZAHR": 1.0, "ADD_PROD_W": 1.0, "ADD_PROD_S": 1.0}]
    with pytest.raises(KeyError):
        mg.guard(rows(0.1, n=1), bad, OPTS)


def test_run_options():
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(root=ROOT)
    assert (o["mg_enabled"], o["mg_min_ratio"], o["mg_max_ratio"]) == (True, 0.75, 1.25)
