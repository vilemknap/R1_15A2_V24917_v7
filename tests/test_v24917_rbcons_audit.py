# -*- coding: utf-8 -*-
"""Audit 2026-10-26: SEVRELAX2 horizon/protected options and RBCONS1 rollback consistency."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import r1_15a2_core as core  # noqa: E402
import r1_15a2_severity_relax_v24917 as sr  # noqa: E402
import r1_15a2_rollback_consistency_v24917 as rb  # noqa: E402
import r1_15a2_acceleration_v24915p1 as perf1  # noqa: E402

CFG = json.loads((ROOT / "tests" / "data" / "EFFECTIVE_CONFIG_RUN_20261025_175302.json").read_text(encoding="utf-8"))
OPTS = {"single": 25.0, "high": 15.0, "extend_horizon": True, "protected_hard": 0.0}


def _rows(n=40):
    return [{"countlocation_no": str(900000 + i), "role": "CALIBRATION", "observed": 1000.0,
             "model": 800.0, "profile_weight": 1.0} for i in range(n)]


# ---------------------------------------------------------------- SEVRELAX2
def test_cycle13_falls_back_to_strict_contract_without_extension():
    cfg = copy.deepcopy(CFG)
    cfg["runtime_acceptance_outer_cycle"] = 13
    assert core.early_exploration_policy(cfg, "GENERATION") is None
    assert core.early_exploration_policy(cfg, "TD") is None
    sr.relax(cfg, dict(OPTS, extend_horizon=False))
    assert core.early_exploration_policy(cfg, "GENERATION") is None


def test_horizon_extension_keeps_relaxed_budgets_after_cycle_12():
    before, after = _rows(), _rows()
    for r in after[1:]:
        r["model"] = 950.0
    after[0]["model"] = 1250.0                     # GEH 6.7 -> 7.5 : +0.8 ... and a +3 jump below
    after[2]["model"] = 1400.0                     # +4.8 GEH single jump (strict contract allows 2.0)
    cfg = copy.deepcopy(CFG)
    cfg["runtime_acceptance_outer_cycle"] = 13
    strict = core.severity_transition_guard(before, after, cfg, "GENERATION")
    assert not str(strict.get("mode", "")).startswith("EARLY_EXPLORATION")
    rec = sr.relax(cfg, OPTS)
    assert rec["early_exploration_acceptance.through_outer_cycle"][0] == 12
    assert cfg["early_exploration_acceptance"]["through_outer_cycle"] >= 100
    pol = core.early_exploration_policy(cfg, "GENERATION")
    assert pol is not None and pol["severity"]["max_single_profile_geh_increase"] == 25.0
    assert core.early_exploration_policy(cfg, "TD") is not None
    g = core.severity_transition_guard(before, after, cfg, "GENERATION")
    assert str(g["mode"]).startswith("EARLY_EXPLORATION")
    assert "SINGLE_PROFILE_GEH_INCREASE_EXCEEDED" not in g["violation_codes"]


def test_protected_option_default_unchanged_and_only_relaxes():
    c = copy.deepcopy(CFG)
    sr.relax(c, OPTS)
    assert c["early_exploration_acceptance"]["severity"]["protected_after_hard_geh"] == 20.0
    c = copy.deepcopy(CFG)
    sr.relax(c, dict(OPTS, protected_hard=10.0))           # never tightens
    assert c["early_exploration_acceptance"]["severity"]["protected_after_hard_geh"] == 20.0
    c = copy.deepcopy(CFG)
    sr.relax(c, dict(OPTS, protected_hard=25.0))
    assert c["early_exploration_acceptance"]["severity"]["protected_after_hard_geh"] == 25.0
    c["runtime_acceptance_outer_cycle"] = 2
    before, after = _rows(), _rows()
    before[0]["model"] = 1000.0                             # GEH 0 (protected)
    after[0]["model"] = 1500.0                              # GEH 13.9? -> make it >20
    after[0]["model"] = 1800.0
    assert 20.0 <= core.geh(1800.0, 1000.0) < 25.0
    assert core.protected_profile_guard(before, after, c, "GENERATION")["passes"]
    assert not core.protected_profile_guard(before, after, CFG | {"runtime_acceptance_outer_cycle": 2},
                                            "GENERATION")["passes"]


def test_run_options_validate_new_keys():
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(root=ROOT)
    assert o["sev_extend_early_horizon"] is True
    assert o["sev_protected_after_hard_geh"] == 0.0
    assert o["rb_tolerant_diagnostics"] is True and o["rb_roster_reuse_proof"] is True


# ---------------------------------------------------------------- RBCONS1 proof
DSEGS = ["A", "B"]


def _sig_cfg(n_roster):
    return {"expected_12d_rows": n_roster, "supply": {"passenger_dsegs": DSEGS},
            "performance": {"v24915_perf1": {"rollback_diagnostic_reuse": {
                "enabled": True, "expected_profiles": 498, "absolute_tolerance": 1e-6,
                "relative_tolerance": 1e-10}}}}


def _sig_rows():
    return [{"countlocation_no": str(i), "link_no": i, "from_node_no": 10 * i, "to_node_no": 10 * i + 1,
             "observation_direction": "DIRECTED", "model_A": 1.0 * i, "model_B": 2.0, "model": 1.0 * i + 2.0}
            for i in range(1, 4)]


def _table(monkeypatch, delta=0.0):
    t = {(i, 10 * i, 10 * i + 1): {"A": 1.0 * i + delta, "B": 2.0} for i in range(1, 4)}
    monkeypatch.setattr(perf1, "_link_volume_table", lambda visum, dsegs, retry: t)


def test_reuse_proof_uses_active_roster_count(monkeypatch):
    _table(monkeypatch)
    monkeypatch.setattr(rb, "options", lambda: {"tolerant": True, "roster_proof": True})
    orig = perf1.count_profile_signature
    orig = getattr(orig, "__wrapped__", orig)
    raw = orig(None, _sig_cfg(3), _sig_rows())
    assert raw["reason"] == "BASELINE_PROFILE_COUNT_MISMATCH"        # the live symptom (498 vs roster)
    sig = rb.wrap_signature(orig)(None, _sig_cfg(3), _sig_rows())
    assert sig["passes"] is True and sig["v24917_expected_profiles"] == 3
    _table(monkeypatch, delta=1e-3)                                    # genuinely different loads
    assert rb.wrap_signature(orig)(None, _sig_cfg(3), _sig_rows())["passes"] is False
    # rows that do not match the roster count keep the original refusal
    out = rb.wrap_signature(orig)(None, _sig_cfg(5), _sig_rows())
    assert out["reason"] == "BASELINE_PROFILE_COUNT_MISMATCH"


def test_reuse_proof_errors_never_raise(monkeypatch):
    _table(monkeypatch)
    monkeypatch.setattr(rb, "options", lambda: {"tolerant": True, "roster_proof": True})
    rows = _sig_rows()
    del rows[0]["model_A"]
    orig = getattr(perf1.count_profile_signature, "__wrapped__", perf1.count_profile_signature)
    out = rb.wrap_signature(orig)(None, _sig_cfg(3), rows)
    assert out["passes"] is False and out["reason"] == "SIGNATURE_READ_FAILED"


# ---------------------------------------------------------------- RBCONS1 tolerant
class Adapter:
    def __init__(self, snap, diag):
        self.snap, self.diag, self.diag_calls = snap, diag, 0

    def snapshot(self):
        return dict(self.snap)

    def diagnostics(self, folder, label):
        self.diag_calls += 1
        return self.diag


def _diag(delta=0.0, extra_geh=0.0):
    rows = _rows(10)
    for r in rows:
        r["model"] = 800.0 + delta
    return {"d12": {"rows": rows}, "d11": {"summary": {}}, "tag": delta}


def _hash(d):
    return json.dumps(d, sort_keys=True, default=str)


def _orig_raising(*a, **k):
    raise RuntimeError("INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER")


def _orig_raising_sig(adapter, block, before_snapshot, baseline_diag_hash, diagnostic_hash_fn, folder,
                      candidate_rows=None, candidate=None, baseline_diag=None):
    return _orig_raising()


@pytest.mark.parametrize("delta,snap_same,tolerant,expect_ok", [
    (0.2, True, True, True),          # noise
    (5.0, True, True, False),         # real difference
    (0.2, False, True, False),        # snapshot not exact -> fail-closed
    (0.2, True, False, False),        # option off
])
def test_tolerant_rollback_diagnostics(tmp_path, monkeypatch, delta, snap_same, tolerant, expect_ok):
    monkeypatch.setattr(rb, "options", lambda: {"tolerant": tolerant, "roster_proof": True})
    base_diag = _diag(0.0)
    before = {"state_hash": "s"}
    ad = Adapter(before if snap_same else {"state_hash": "x"}, _diag(delta))
    saved = []
    fn = rb.wrap_rollback_and_verify(_orig_raising_sig, lambda p, o: saved.append((p, o)))
    if expect_ok:
        res, diag = fn(ad, "GENERATION", before, _hash(base_diag), _hash, tmp_path,
                       candidate_rows=[], candidate={}, baseline_diag=base_diag)
        assert diag is ad.diag and diag is not base_diag and res["passes"]
        assert res["diagnostic_hash"] == _hash(diag) and res["diagnostic_equivalent"]
        assert not res["diagnostic_equal"]
        assert saved and saved[0][1]["status"] == "SNAPSHOT_EXACT_LOADS_NUMERICALLY_EQUIVALENT"
    else:
        with pytest.raises(RuntimeError, match="INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER"):
            fn(ad, "GENERATION", before, _hash(base_diag), _hash, tmp_path,
               candidate_rows=[], candidate={}, baseline_diag=base_diag)


def test_other_rollback_errors_are_not_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "options", lambda: {"tolerant": True, "roster_proof": True})

    def orig(adapter, block, before_snapshot, baseline_diag_hash, diagnostic_hash_fn, folder,
             candidate_rows=None, candidate=None, baseline_diag=None):
        raise RuntimeError("INPLACE_ROLLBACK_COM_DEAD")
    ad = Adapter({"state_hash": "s"}, _diag(0.0))
    fn = rb.wrap_rollback_and_verify(orig, lambda p, o: None)
    with pytest.raises(RuntimeError, match="COM_DEAD"):
        fn(ad, "GENERATION", {"state_hash": "s"}, "h", _hash, tmp_path, baseline_diag=_diag(0.0))
    assert ad.diag_calls == 0


def test_rollback_candidate_still_forwards_baseline_diag(monkeypatch):
    import inspect
    seen = {}

    def orig(adapter, block, before_snapshot, baseline_diag_hash, diagnostic_hash_fn, folder,
             candidate_rows=None, candidate=None, baseline_diag=None):
        seen["baseline_diag"] = baseline_diag
        return {"passes": True}, baseline_diag
    fn = rb.wrap_rollback_and_verify(orig, lambda p, o: None)
    assert "baseline_diag" in inspect.signature(fn).parameters
    fn(None, "GENERATION", {}, "h", _hash, "f", candidate_rows=[], candidate={}, baseline_diag={"x": 1})
    assert seen["baseline_diag"] == {"x": 1}


def test_same_step_accepted_in_cycle12_rejected_in_cycle13_unless_extended():
    def rows():
        return [{"countlocation_no": str(900000 + i), "role": "CALIBRATION", "observed": 1000.0,
                 "model": 1000.0, "profile_weight": 1.0} for i in range(40)]
    b, a = rows(), rows()
    for r in b[5:]:
        r["model"] = 1300.0
    for r in a[5:]:
        r["model"] = 1100.0
    for i in range(5, 15):
        b[i]["model"], a[i]["model"] = 2000.0, 1500.0      # severe profiles improve
    for i in range(1, 5):
        b[i]["model"], a[i]["model"] = 1700.0, 1900.0      # 4 profiles cross GEH20 (+4.6)
    res = {}
    for cyc in (12, 13):
        c = copy.deepcopy(CFG)
        c["runtime_acceptance_outer_cycle"] = cyc
        res[cyc] = core.acceptance_decision(b, a, {}, {}, c, policy_scope="GENERATION")["accepted"]
    assert res == {12: True, 13: False}                     # the conflict
    c = copy.deepcopy(CFG)
    c["runtime_acceptance_outer_cycle"] = 13
    sr.relax(c, OPTS)
    assert core.acceptance_decision(b, a, {}, {}, c, policy_scope="GENERATION")["accepted"] is True


def test_longtrip_options(monkeypatch):
    import r1_15a2_demand_policy_v1 as dp
    import r1_15a2_td_count_blend_v24917 as tb
    o = dp.load_options(root=ROOT)
    assert o["td_count_weight"] == pytest.approx(0.60) and o["td_max_survey_degradation"] == pytest.approx(1.25)
    assert o["bd_enabled"] is True
    t = tb.options()
    assert t["w_cnt"] == pytest.approx(0.60) and t["w_idp"] == pytest.approx(0.40) and t["max_idp_ratio"] == 1.25
    with pytest.raises(RuntimeError):
        dp.load_options(root=ROOT, environ={"R1_TD_MAX_SURVEY_DEGRADATION": "0.9"})
