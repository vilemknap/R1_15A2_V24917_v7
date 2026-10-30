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
    assert (o["mg_enabled"], o["mg_min_ratio"], o["mg_max_ratio"]) == (True, 0.75, 2.5)



# W/S P=2.5 is a mobility (FP/survey) ceiling. A=4.0 is a separate
# domestic attraction coefficient ceiling, never a mobility factor.
WS_OPTS = {"enabled": True, "lo": 0.75, "hi": 2.5,
           "ws_attraction_coefficient_band": [0.75, 4.0]}


def full_zones(att=1.0):
    out = zones(1.0, 1.0, n=2)
    for row in out:
        row["ADD_ATT_W"] = att
        row["ADD_ATT_S"] = att
    return out


def final_candidates(prod=2.5, att=4.0):
    return [dict(zone_no=z, attr=attr, current=1.0, proposed=value)
            for z in (1, 2)
            for attr, value in (("ADD_PROD_W", prod), ("ADD_PROD_S", prod),
                                ("ADD_ATT_W", att), ("ADD_ATT_S", att))]


def after_zones(prod=2.5, att=4.0):
    result = full_zones()
    for row in result:
        row["ADD_PROD_W"] = row["ADD_PROD_S"] = prod
        row["ADD_ATT_W"] = row["ADD_ATT_S"] = att
        for g in mg.GROUPS:
            row["FP_1_WORK_" + g] *= prod
            row["FP_2_SERVICE_" + g] *= prod
    return result


def test_ws_final_mobility_2_5_and_attraction_4_0_both_pass():
    import r1_15a2_mobility_zone_v24917 as mz
    parent = full_zones()
    opts = mg.options()
    assert opts["ws_attraction_coefficient_band"] == [0.75, 4.0]
    assert opts["hi"] == 2.5
    assert mg.check_candidate(final_candidates(), parent, opts)["passes"]
    zone_auth = mz.capture(parent, opts, families=("WORK", "SERVICE"))
    assert mz.check_candidate(final_candidates(), zone_auth)["passes"]
    after = after_zones()
    proof = mg.check_live(parent, after, opts)
    assert proof["passes"] and proof["ws_attraction_coefficient_gate"]["checked_live_values"] == 4
    assert proof["families"]["WORK"]["ratio_realized"] == pytest.approx(2.5)
    assert proof["families"]["SERVICE"]["ratio_realized"] == pytest.approx(2.5)
    assert mz.check_live(zone_auth, after)["passes"]


@pytest.mark.parametrize("attr", ["ADD_PROD_W", "ADD_PROD_S"])
def test_ws_production_mobility_above_2_5_still_rejected(attr):
    candidate = final_candidates()
    for row in candidate:
        if row["attr"] == attr:
            row["proposed"] = 2.501
    assert not mg.check_candidate(candidate, full_zones(), WS_OPTS)["passes"]


@pytest.mark.parametrize("attr", ["ADD_ATT_W", "ADD_ATT_S"])
def test_ws_attraction_above_4_rejected_at_final_candidate_and_live(attr):
    candidate = final_candidates()
    for row in candidate:
        if row["attr"] == attr:
            row["proposed"] = 4.001
    proof = mg.check_candidate(candidate, full_zones(), WS_OPTS)
    assert proof["families"]["WORK"]["passes"] and proof["families"]["SERVICE"]["passes"]
    assert not proof["passes"] and not proof["ws_attraction_coefficient_gate"]["passes"]
    after = after_zones()
    for row in after:
        row[attr] = 4.01
    proof = mg.check_live(full_zones(), after, WS_OPTS)
    assert not proof["passes"] and not proof["ws_attraction_coefficient_gate"]["passes"]


def test_ws_attraction_initially_out_of_band_can_only_hold_or_return():
    before = full_zones(att=4.4)
    within = [dict(zone_no=1, attr="ADD_ATT_W", current=4.4, proposed=4.3)]
    assert mg.check_candidate(within, before, WS_OPTS)["passes"]
    within[0]["proposed"] = 4.41
    assert not mg.check_candidate(within, before, WS_OPTS)["passes"]
    after = full_zones(att=4.3)
    assert mg.check_live(before, after, WS_OPTS)["passes"]
    after[0]["ADD_ATT_W"] = 4.41
    assert not mg.check_live(before, after, WS_OPTS)["passes"]


def test_ws_attraction_zero_cannot_be_created_and_stale_parent_rejected():
    before = full_zones(att=0.0)
    assert mg.check_candidate([dict(zone_no=1, attr="ADD_ATT_W",
                                    current=0.0, proposed=0.0)], before, WS_OPTS)["passes"]
    assert not mg.check_candidate([dict(zone_no=1, attr="ADD_ATT_W",
                                        current=0.0, proposed=0.3)], before, WS_OPTS)["passes"]
    before = full_zones()
    assert not mg.check_candidate([dict(zone_no=1, attr="ADD_ATT_W",
                                        current=1.2, proposed=1.5)], before, WS_OPTS)["passes"]


def test_ws_attraction_unreadable_parent_and_tampered_band_fail_closed():
    before = full_zones()
    del before[0]["ADD_ATT_S"]
    with pytest.raises(ValueError, match="WS_ATTRACTION_PARENT_UNREADABLE"):
        mg.check_candidate(final_candidates(), before, WS_OPTS)
    with pytest.raises(ValueError, match="WS_ATTRACTION_BAND_MISMATCH"):
        mg.check_candidate(final_candidates(), full_zones(),
                           dict(WS_OPTS, ws_attraction_coefficient_band=[.75, 4.2]))


def test_ws_attraction_does_not_raise_mobility_ratio_to_four():
    before = full_zones()
    for att in (2.0, 3.0, 4.0):
        p = mg.check_candidate([dict(zone_no=1, attr="ADD_ATT_S",
                                     current=1.0, proposed=att)], before, WS_OPTS)
        assert p["passes"] and p["families"]["SERVICE"]["ratio_after"] == pytest.approx(1.0)


def test_ws_attraction_does_not_apply_to_zahr():
    before = full_zones()
    before[1]["NOT_ZAHR"] = 0.0
    before[1]["ADD_ATT_W"] = 50.0
    p = mg.check_candidate([dict(zone_no=2, attr="ADD_ATT_W",
                                 current=50.0, proposed=100.0)], before, WS_OPTS)
    assert p["passes"]
