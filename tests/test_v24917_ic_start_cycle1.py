"""User decision 2026-11-06: the TD impedance sees the congested skim from cycle 1 (ICONG1)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import r1_15a2_demand_policy_v1 as dp  # noqa: E402
import r1_15a2_intrazonal_penalty_v24917 as iz  # noqa: E402
from test_v24917_intrazonal_penalty import IC_OPTS, _diag, act, make_visum  # noqa: E402,F401


def test_run_options_start_congested_impedance_in_cycle_1():
    o = dp.load_options(root=ROOT)
    assert o["ic_enabled"] is True
    assert o["ic_start_cycle"] == 1
    assert o["ic_start_model_obs_ratio"] == 0.8          # ratio trigger unchanged, cycle trigger added


def test_cycle_1_triggers_feedback_below_ratio_threshold(act):
    o = dp.load_options(root=ROOT)
    act(make_visum(), opts=dict(IC_OPTS, ic_start_cycle=o["ic_start_cycle"]))
    due = iz.congestion_due(_diag(0.74), 1)                # live model/counts ~0.74 < 0.80
    assert due["due"]
    assert iz.STATE["ic_start"] == {"outer_cycle": 1, "model_obs_ratio": 0.74, "trigger": "OUTER_CYCLE"}
    assert iz.congestion_due(_diag(0.74), 2)["due"]        # stays on in later cycles
