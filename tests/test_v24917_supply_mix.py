# -*- coding: utf-8 -*-
"""SUPPLYMIX1: ADDVAL1 route-choice lever inside the demand cycles (REAL gate, REAL rollback)."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import r1_15a2_core as core  # noqa: E402
import r1_15a2_supply_mix_v24917 as sm  # noqa: E402
from r1_15a2_supply import SupplyContractError, canonical_hash  # noqa: E402

CFG = json.loads((ROOT / "tests" / "data" / "EFFECTIVE_CONFIG_RUN_20261025_175302.json")
                 .read_text(encoding="utf-8"))
OPTS = {"enabled": True, "every_n": 1, "start_cycle": 1, "max_trials": 2, "step_units": [8, 4],
        "max_groups": 12, "max_edges": 120, "min_driver_geh": 10.0, "drivers": "AUTO",
        "reset_position": 15}

ON = [(1, 2), (2, 3)]          # actual paths through the overloaded profile 900001
OFF = [(3, 4), (4, 5)]         # diverging/rejoining alternative, counted by 900003
ON2 = [(7, 8)]                 # second branch of 900001 (must not be used: one branch per profile)
UND = [(5, 6)]                 # branch of the underloaded profile 900002


def kt(k):
    return "%d|%d" % k


def profiles():
    rows = []
    for no, model, obs in ((900001, 3000.0, 1500.0), (900002, 600.0, 1400.0), (900003, 900.0, 1500.0)):
        rows.append({"countlocation_no": str(no), "role": "CALIBRATION", "observed": obs, "model": model,
                     "profile_weight": 1.0})
    for i in range(30):
        rows.append({"countlocation_no": str(910000 + i), "role": "CALIBRATION", "observed": 1000.0,
                     "model": 1000.0 + (i % 5), "profile_weight": 1.0})
    return rows


def ladder(gid, driver, keys, signs, units=(16, 8, 4, 2, 1), rank=1, old=0.0):
    out = []
    for u in units:
        ch = [{"key": list(k), "expected_old": old, "new": old + s * 0.5 * u, "delta": s * 0.5 * u}
              for k, s in zip(keys, signs)]
        out.append({"candidate_id": "SEQ_%s_%d" % (gid, u), "driver_profile": str(driver), "changes": ch,
                    "step_units": u, "backtracking_group_id": gid, "backtracking_group_rank": rank})
    return out


def design():
    c = []
    c += ladder("G1", 900001, ON + OFF, [1, 1, -1, -1], rank=2)
    c += ladder("G1B", 900001, ON2, [1], rank=1)          # better design rank, same profile
    c += ladder("G2", 900002, UND, [-1], rank=3)
    return {"candidates": c, "authority": {"assignment_path_hash": "APH"}}


class FakeAdapter:
    """Profile 900001 volume falls by `shift` per ADDVAL1 of ON-minus-OFF contrast; 900003 gains it."""

    def __init__(self, shift=60.0, fail_assign_once=False, design_error=None):
        self.cfg = copy.deepcopy(CFG)
        self.rows0 = profiles()
        keys = ON + OFF + ON2 + UND
        self.addval = {kt(k): 0.0 for k in keys}
        from r1_15a2_supply import SupplyPolicy
        self.baseline_addval = {k: self.addval[kt(k)] for k in keys}
        self.policy = SupplyPolicy.from_config(CFG)
        self.link_t0 = {k: 100.0 for k in keys}
        self.vol = dict(self.addval)
        self.shift = shift
        self.assignments = []
        self.plans = []
        self.kept = []
        self.fail_assign_once = fail_assign_once
        self.design_error = design_error
        self.supply_path_proof = None
        self.writes = 0

    def snapshot(self):
        av = dict(self.addval)
        return {"fixed_link_hash": 1, "dseg_hash": 1, "operations_hash": 1, "addval1": av,
                "td_hash": 1, "generation_hash": 1, "matrix_hash": 7, "matrices": [], "dseg_map": {},
                "state_hash": canonical_hash(sorted(av.items()))}

    def diagnostics(self, folder, label):
        on = sum(self.vol[kt(k)] for k in ON) / len(ON) - sum(self.vol[kt(k)] for k in OFF) / len(OFF)
        und = -self.vol[kt(UND[0])]
        rows = []
        for r in self.rows0:
            m = r["model"]
            if r["countlocation_no"] == "900001":
                m = m - self.shift * on
            elif r["countlocation_no"] == "900003":
                m = m + self.shift * on
            elif r["countlocation_no"] == "900002":
                m = m + 40.0 * und
            rows.append(dict(r, model=m))
        return {"d12": {"rows": rows}, "d11": {"summary": {}}, "signals": {}}

    def read_links(self):
        return {k: {"addval1": self.addval[kt(k)], "t0_c_seconds": self.link_t0[k],
                    "eligible": True} for k in self.link_t0}

    def supply_design(self, diag, folder, snapshot):
        if self.design_error:
            raise SupplyContractError(self.design_error)
        self.supply_path_proof = {"parent_hash": snapshot["state_hash"], "assignment_path_hash": "APH"}
        return design()

    def apply_supply(self, candidate, snapshot, folder):
        if candidate["parent_hash"] != snapshot["state_hash"] or self.snapshot() != snapshot:
            raise SupplyContractError("STALE_SUPPLY_PARENT")
        if (self.supply_path_proof or {}).get("parent_hash") != snapshot["state_hash"]:
            raise SupplyContractError("UNVERIFIED_OR_STALE_ACTUAL_PATH_PROOF")
        for ch in candidate["changes"]:
            k = "%d|%d" % tuple(ch["key"])
            assert self.addval[k] == ch["expected_old"]
            self.addval[k] = ch["new"]
            self.writes += 1

    def assign_for_block(self, folder, block):
        assert block in ("SUPPLY_ADDVAL1", "GENERATION")
        if self.fail_assign_once:
            self.fail_assign_once = False
            raise RuntimeError("SIMULATED_ASSIGNMENT_FAILURE")
        self.vol = dict(self.addval)
        self.assignments.append(str(folder))
        return 0.001

    def block_gate(self, block, before, after, rows):
        return core.acceptance_decision(before["d12"]["rows"], after["d12"]["rows"], {}, {}, self.cfg,
                                        policy_scope=block)

    def accepted_state_changed(self, state, diag, reason, phase):
        self.kept.append((reason, phase))
        return {"epoch": 1, "phase": phase}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_inplace_transaction_v24915p2 as tx
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_demand_policy_v1 as dp

    def restore(adapter, before_snapshot, changes, folder=None):
        for ch in changes:
            k = "%d|%d" % tuple(int(x) for x in ch["key"])
            adapter.addval[k] = before_snapshot["addval1"][k]
        return []
    monkeypatch.setattr(tx, "restore_supply_parameters", restore)

    def ledger(diag, state, anchors, policy, reference, cfg):
        m = core.csd_metrics(diag["d12"]["rows"], "CALIBRATION", True)
        return {"total": m["objective_geh_mean_weighted"] / 50.0, "raw_cal": m["objective_geh_mean_weighted"],
                "cal_metrics": m}
    monkeypatch.setattr(base, "ledger", ledger)
    monkeypatch.setattr(dp, "catchup_phase", lambda cfg, diag: ("CATCH_UP", 0.6))
    control = SimpleNamespace(checkpoint=lambda *a, **k: None)

    def make(**kw):
        ad = FakeAdapter(**kw)
        state = ad.snapshot()
        diag = ad.diagnostics(tmp_path, "BASE")

        def run(opts=None, cycle=3):
            return sm.supply_block(ctrl, base, tx, ad, copy.deepcopy(CFG), tmp_path / "SM", control, state,
                                   diag, None, None, None, cycle, dict(opts or OPTS))
        return SimpleNamespace(ad=ad, run=run, state=state, diag=diag, base=base)
    return make


# ----------------------------------------------------------------- pure
@pytest.mark.parametrize("failure", [
    OSError("OPTIONS_IO_FAILED"),
    json.JSONDecodeError("OPTIONS_JSON_FAILED", "{", 1),
    RuntimeError("R1_RUN_OPTION_RANGE:sp_every_n_cycles"),
])
def test_options_never_replace_unreadable_or_invalid_configuration(monkeypatch, failure):
    import r1_15a2_demand_policy_v1 as dp
    def fail():
        raise failure
    monkeypatch.setattr(dp, "load_options", fail)
    with pytest.raises(type(failure)) as caught:
        sm.options()
    assert caught.value is failure


def test_options_preserve_validated_disabled_schedule(monkeypatch):
    import r1_15a2_demand_policy_v1 as dp
    values = dp.validate({"sp_enabled": False, "sp_every_n_cycles": 3,
                          "sp_start_cycle": 4, "sp_step_units": [8, 2]})
    monkeypatch.setattr(dp, "load_options", lambda: values)
    opts = sm.options()
    assert opts["enabled"] is False
    assert opts["every_n"] == 3 and opts["start_cycle"] == 4
    assert opts["step_units"] == [8, 2]
    assert sm.due(4, opts) == (False, "DISABLED")


@pytest.mark.parametrize("content,exception", [
    ("{", json.JSONDecodeError),
    ("[]", RuntimeError),
    ('{"sp_every_n_cycles":0}', RuntimeError),
    ('{"sp_enabled":"invalid"}', RuntimeError),
])
def test_options_reject_real_invalid_run_options_file(tmp_path, monkeypatch, content, exception):
    import r1_15a2_demand_policy_v1 as dp
    (tmp_path / "R1_RUN_OPTIONS.json").write_text(content, encoding="utf-8")
    original = dp.load_options
    monkeypatch.setattr(dp, "load_options", lambda: original(root=tmp_path, environ={}))
    with pytest.raises(exception):
        sm.options()


def test_generation_wrapper_cannot_run_supply_with_unverified_options(monkeypatch):
    failure = RuntimeError("UNVERIFIED_SUPPLY_OPTIONS")
    def fail(): raise failure
    monkeypatch.setattr(sm, "options", fail)
    monkeypatch.setattr(sm, "supply_block", lambda *a: pytest.fail("Supply must not start"))
    result = (False, {}, {}, {}, {})
    wrapped = sm._wrap_generation(lambda *a, **kw: result, None, None, None)
    with pytest.raises(RuntimeError, match="UNVERIFIED_SUPPLY_OPTIONS") as error:
        wrapped(None, {}, None, None, {}, {}, None, None, None, outer_cycle=3)
    assert error.value is failure


def test_invalid_options_cannot_partially_install_and_retry_is_possible(monkeypatch):
    import r1_15a2_demand_policy_v1 as dp
    import r1_15a2_acceleration_v24915p1 as perf1
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    original_plan = perf1.phase_recompute_plan
    original_generation = ctrl._generation_update_once
    monkeypatch.setattr(perf1, "phase_recompute_plan", original_plan)
    monkeypatch.setattr(ctrl, "_generation_update_once", original_generation)
    state = copy.deepcopy(sm._STATE)
    state["installed"] = False
    monkeypatch.setattr(sm, "_STATE", state)
    before = copy.deepcopy(state)
    failure = RuntimeError("OPTIONS_MUST_FAIL_BEFORE_PATCHING")
    def fail(): raise failure
    monkeypatch.setattr(dp, "load_options", fail)
    with pytest.raises(RuntimeError, match="OPTIONS_MUST_FAIL_BEFORE_PATCHING"):
        sm.install(print_fn=lambda *a: None)
    assert sm._STATE == before
    assert perf1.phase_recompute_plan is original_plan
    assert ctrl._generation_update_once is original_generation
    valid = dp.validate({"sp_enabled": False})
    monkeypatch.setattr(dp, "load_options", lambda: valid)
    result = sm.install(print_fn=lambda *a: None)
    assert result["installed"] and result["options"]["enabled"] is False


def test_due_and_driver_mode():
    assert sm.due(3, OPTS) == (True, "EVERY_1")
    assert sm.due(None, OPTS)[0] is False
    o = dict(OPTS, every_n=3, start_cycle=4)
    assert [c for c in range(1, 12) if sm.due(c, o)[0]] == [4, 7, 10]
    assert sm.due(5, dict(OPTS, enabled=False)) == (False, "DISABLED")
    assert sm.driver_mode(OPTS, "CATCH_UP") == "OVERLOADED"
    assert sm.driver_mode(OPTS, "REFINE") == "BOTH"
    assert sm.driver_mode(dict(OPTS, drivers="BOTH"), "CATCH_UP") == "BOTH"


def test_select_groups_one_branch_per_profile_highest_geh_and_sign_filter():
    table = sm.profile_table(profiles())
    g = sm.select_groups(design(), table, OPTS, "OVERLOADED")
    assert [x["group_id"] for x in g] == ["G1B"]                 # best design rank of 900001 only
    g = sm.select_groups(design(), table, OPTS, "BOTH")
    assert {x["driver_profile"] for x in g} == {"900001", "900002"}
    assert g[0]["geh"] >= g[1]["geh"]
    g = sm.select_groups(design(), table, dict(OPTS, min_driver_geh=28.0), "BOTH")
    assert {x["driver_profile"] for x in g} == {"900001"}
    g = sm.select_groups(design(), table, OPTS, "BOTH", excluded_profiles=["900001"])
    assert [x["driver_profile"] for x in g] == ["900002"]


def test_select_groups_skips_link_overlap_and_edge_budget():
    d = design()
    d["candidates"] += ladder("G3", 900003, [ON[0]], [1], rank=4)   # overlaps G1 keys
    table = sm.profile_table(profiles())
    table["900003"]["sign"] = 1
    d["candidates"] = [c for c in d["candidates"] if c["backtracking_group_id"] != "G1B"]
    g = sm.select_groups(d, table, OPTS, "BOTH")
    assert "G3" not in [x["group_id"] for x in g]
    g = sm.select_groups(d, table, dict(OPTS, max_edges=1), "BOTH")
    assert all(len(x["keys"]) <= 1 for x in g)


def test_merged_candidate_picks_ladder_step_and_signs():
    table = sm.profile_table(profiles())
    d = design()
    d["candidates"] = [c for c in d["candidates"] if c["backtracking_group_id"] != "G1B"]
    groups = sm.select_groups(d, table, OPTS, "BOTH")
    cand = sm.merged_candidate(groups, 8, d, "PARENT")
    news = {tuple(c["key"]): c["new"] for c in cand["changes"]}
    assert news[ON[0]] == 4.0 and news[OFF[0]] == -4.0 and news[UND[0]] == -4.0
    assert cand["positive_edges"] == 2 and cand["negative_edges"] == 3
    assert cand["parent_hash"] == "PARENT" and cand["assignment_path_hash"] == "APH"
    cand3 = sm.merged_candidate(groups, 3, d, "PARENT")              # no unit 3 -> largest smaller (2)
    assert {m["step_units"] for m in cand3["members"]} == {2}
    assert sm.merged_candidate([], 8, d, "P") is None


def test_cold_supply_plan():
    inv = [{"no": 1, "type": 9, "active": 1}, {"no": 5, "type": 45, "active": 1},
           {"no": 15, "type": 9, "active": 1}, {"no": 16, "type": 101, "active": 0},
           {"no": 17, "type": 101, "active": 1}, {"no": 18, "type": 101, "active": 1},
           {"no": 19, "type": 101, "active": 1}, {"no": 20, "type": 101, "active": 1},
           {"no": 31, "type": 104, "active": 1}, {"no": 40, "type": 75, "active": 1}]
    base_plan = {"inventory": inv, "approved_assignment_positions": [20], "selected_operation_positions": [20, 40]}
    out = sm.cold_supply_plan(base_plan, {}, 15)
    assert out["v24917_supplymix_plan"]["applied"] is True
    assert out["selected_operation_positions"] == [15, 17, 18, 19, 20, 40]
    bad = sm.cold_supply_plan(base_plan, {}, 17)
    assert bad["v24917_supplymix_plan"]["applied"] is False
    assert any(r.startswith("RESET_OPERATION_TYPE") for r in bad["v24917_supplymix_plan"]["reasons"])
    cfg = {"supply": {"assignment_operations": [{"no": 20}]}}
    out2 = sm.cold_supply_plan({"inventory": inv}, cfg, 15)
    assert out2["selected_operation_positions"] == [15, 17, 18, 19, 20, 40]


def test_plan_wrapper_supply_only_and_fail_closed(monkeypatch):
    monkeypatch.setattr(sm, "options", lambda: dict(OPTS))
    inv = [{"no": 15, "type": 9, "active": 1}, {"no": 20, "type": 101, "active": 1}]
    w = sm._wrap_plan(lambda v, c, b: {"inventory": inv, "approved_assignment_positions": [20],
                                       "selected_operation_positions": [20]})
    assert w(None, {}, "GENERATION")["selected_operation_positions"] == [20]
    assert w(None, {}, "SUPPLY_ADDVAL1")["selected_operation_positions"] == [15, 20]
    monkeypatch.setattr(sm, "options", lambda: dict(OPTS, reset_position=20))
    with pytest.raises(Exception, match="COLD_PLAN_UNAVAILABLE"):     # class may be a reloaded copy
        w(None, {}, "SUPPLY_ADDVAL1")


def test_plan_uses_one_validated_options_snapshot(monkeypatch):
    reads = []
    def options():
        reads.append(1)
        if len(reads) > 1:
            raise RuntimeError("OPTIONS_RELOADED_DURING_ONE_PLAN")
        return dict(OPTS)
    monkeypatch.setattr(sm, "options", options)
    inv = [{"no": 15, "type": 9, "active": 1}, {"no": 20, "type": 101, "active": 1}]
    wrapped = sm._wrap_plan(lambda *args: {"inventory": inv,
        "approved_assignment_positions": [20], "selected_operation_positions": [20]})
    assert wrapped(None, {}, "GENERATION")["selected_operation_positions"] == [20]
    assert reads == []
    assert wrapped(None, {}, "SUPPLY_ADDVAL1")["selected_operation_positions"] == [15, 20]
    assert reads == [1]


def test_plan_propagates_invalid_options_before_cold_plan(monkeypatch):
    failure = RuntimeError("BAD_OPTIONS_BEFORE_COLD_PLAN")
    def fail(): raise failure
    monkeypatch.setattr(sm, "options", fail)
    monkeypatch.setattr(sm, "cold_supply_plan", lambda *a: pytest.fail("No unverified plan"))
    wrapped = sm._wrap_plan(lambda *args: {})
    with pytest.raises(RuntimeError, match="BAD_OPTIONS_BEFORE_COLD_PLAN") as error:
        wrapped(None, {}, "SUPPLY_ADDVAL1")
    assert error.value is failure


# ------------------------------------------------------------- block
def _no_g1b(h, monkeypatch):
    d = design()
    d["candidates"] = [c for c in d["candidates"] if c["backtracking_group_id"] != "G1B"]
    monkeypatch.setattr(h.ad, "supply_design", lambda diag, folder, snap: (
        setattr(h.ad, "supply_path_proof", {"parent_hash": snap["state_hash"], "assignment_path_hash": "APH"}),
        d)[1])


def test_block_accepts_first_trial_and_keeps_it_in_place(harness, monkeypatch):
    h = harness(shift=60.0)
    _no_g1b(h, monkeypatch)
    changed, st, dg, val, rec = h.run()
    assert rec["status"] == "ACCEPTED", rec
    assert changed is True and rec["driver_mode"] == "OVERLOADED"
    assert len(h.ad.assignments) == 1                           # no re-apply, no rollback
    assert st["addval1"][kt(ON[0])] == 4.0 and st["addval1"][kt(OFF[0])] == -4.0   # unit 8 = 4 ADDVAL1
    assert st["addval1"][kt(UND[0])] == 0.0                     # underloaded driver not used in CATCH_UP
    assert h.ad.kept == [("V24917_SUPPLYMIX_ACCEPTED_ADDVAL1_STATE", "SUPPLY")]
    assert rec["attempts"][0]["drivers"][0]["geh_after"] < rec["attempts"][0]["drivers"][0]["geh_before"]


def test_block_overshoot_retries_smaller_step_without_rollback(harness, monkeypatch):
    h = harness(shift=60.0)
    _no_g1b(h, monkeypatch)
    h.ad.shift = 350.0          # unit 8 (contrast 8 ADDVAL1 = 2800 veh) overshoots, 900003 explodes
    changed, st, dg, val, rec = h.run()
    statuses = [a["status"] for a in rec["attempts"]]
    assert statuses == ["REJECTED", "ELIGIBLE"]
    assert rec["attempts"][0]["excluded_after_trial"] == []     # overshoot is not a wrong direction
    assert rec["status"] == "ACCEPTED" and changed is True
    assert st["addval1"][kt(ON[0])] == 2.0 and st["addval1"][kt(OFF[1])] == -2.0
    assert len(h.ad.assignments) == 2                           # two trials, no rollback recompute


def test_block_wrong_direction_driver_dropped_then_exact_rollback(harness, monkeypatch):
    h = harness(shift=-60.0)    # the branch moves traffic the wrong way
    _no_g1b(h, monkeypatch)
    changed, st, dg, val, rec = h.run()
    assert rec["attempts"][0]["status"] == "REJECTED"
    assert rec["attempts"][0]["excluded_after_trial"] == ["900001"]
    assert len(rec["attempts"]) == 1 and rec["stop_reason"] == "NO_COST_SAFE_PROVED_BRANCH"
    assert rec["status"] == "NO_ACCEPTED_TRIAL" and changed is False
    assert st == h.state and h.ad.snapshot() == h.state
    assert len(h.ad.assignments) == 2                           # trial + rollback recompute


def test_block_second_trial_accepted_after_parameter_restore(harness, monkeypatch):
    h = harness(shift=60.0)
    d = design()
    d["candidates"] = [c for c in d["candidates"] if c["backtracking_group_id"] != "G1B"]
    monkeypatch.setattr(h.ad, "supply_design", lambda diag, folder, snap: (
        setattr(h.ad, "supply_path_proof", {"parent_hash": snap["state_hash"], "assignment_path_hash": "APH"}),
        d)[1])
    orig_gate = h.ad.block_gate
    calls = {"n": 0}

    def gate(block, before, after, rows):
        calls["n"] += 1
        dec = orig_gate(block, before, after, rows)
        if calls["n"] == 1:
            dec["accepted"] = False
            dec.setdefault("reasons", []).append("TEST_FORCED_REJECTION")
        return dec
    monkeypatch.setattr(h.ad, "block_gate", gate)
    changed, st, dg, val, rec = h.run()
    assert [a["status"] for a in rec["attempts"]] == ["REJECTED", "ELIGIBLE"]
    assert rec["status"] == "ACCEPTED" and changed is True
    assert st["addval1"][kt(ON[0])] == 2.0 and st["addval1"][kt(OFF[0])] == -2.0   # unit 4
    assert len(h.ad.assignments) == 2                           # two trials, no rollback recompute
    assert rec["attempts"][1]["drivers"][0]["geh_after"] < rec["attempts"][1]["drivers"][0]["geh_before"]


def test_block_design_failure_is_recorded_without_write(harness):
    h = harness(design_error="PATH_EPOCH_CACHE_CONTEXT_NOT_COMPATIBLE")
    changed, st, dg, val, rec = h.run()
    assert changed is False and rec["status"] == "DESIGN_FAILED_NO_WRITE"
    assert h.ad.writes == 0 and h.ad.assignments == []


def test_block_assignment_error_rolls_back_and_continues(harness):
    h = harness(shift=60.0, fail_assign_once=True)
    changed, st, dg, val, rec = h.run()
    assert changed is False and rec["status"] == "TRIAL_FAILED_ROLLBACK_VERIFIED"
    assert h.ad.snapshot() == h.state and st is h.state
    assert len(h.ad.assignments) == 1                           # the rollback recompute


def test_block_no_driver_branch(harness):
    h = harness()
    changed, st, dg, val, rec = h.run(opts=dict(OPTS, min_driver_geh=500.0))
    assert changed is False and rec["status"] == "NO_DRIVER_BRANCH" and h.ad.writes == 0


def test_rollback_diag_mismatch_triggers_full_recovery(harness, monkeypatch):
    h = harness(shift=60.0)
    import r1_15a2_overnight_controller_v24915p2 as base
    monkeypatch.setattr(h.ad, "block_gate", lambda *a, **k: {"accepted": False, "reasons": ["X"]})

    def bad_rollback(*a, **k):
        raise SupplyContractError("INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER")
    monkeypatch.setattr(base, "_rollback_candidate", bad_rollback)
    changed, st, dg, val, rec = h.run()
    assert rec["status"] == "RECOVERED_FULL_RECOMPUTE_FROM_PARENT_PARAMETERS"
    assert st["addval1"] == h.state["addval1"]                 # parent parameters restored
    assert "INPLACE_ROLLBACK_DIAGNOSTICS_DIFFER" in rec["rollback_error"]


# -------------------------------------------------------------- wrapper
def test_generation_wrapper_runs_supply_after_generation(harness, monkeypatch, tmp_path):
    import r1_15a2_overnight_controller_v24915p2 as base
    import r1_15a2_inplace_transaction_v24915p2 as tx
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    import r1_15a2_demand_policy_v1 as dp
    h = harness(shift=60.0)
    monkeypatch.setattr(sm, "options", lambda: dict(OPTS, every_n=2))
    pol = SimpleNamespace(last_generation_complete=True)
    monkeypatch.setitem(dp._ACTIVE, "test", {"policy": pol})
    seen = {}

    def orig(adapter, cfg, folder, control, state, diag, anchors, reference, policy, outer_cycle=None):
        seen["cycle"] = outer_cycle
        return False, state, diag, {"total": 1.0}, {"status": "CONFIGURED_GENERATION_SEARCH_EXHAUSTED",
                                                     "stationarity_confirmed": True}
    w = sm._wrap_generation(orig, ctrl, base, tx)
    control = SimpleNamespace(checkpoint=lambda *a, **k: None)
    gfolder = tmp_path / "DEMAND_CYCLE_03_GENERATION"
    r = w(h.ad, copy.deepcopy(CFG), gfolder, control, h.state, h.diag, None, None, None, outer_cycle=4)
    assert r[0] is False and "v24917_supplymix" not in r[4]       # cycle 4 not due (start 1, every 2)
    _no_g1b(h, monkeypatch)
    r = w(h.ad, copy.deepcopy(CFG), tmp_path / "DEMAND_CYCLE_05_GENERATION", control, h.state, h.diag,
          None, None, None, outer_cycle=5)
    assert r[0] is True and r[4]["v24917_supplymix"]["status"] == "ACCEPTED"
    assert r[4]["stationarity_confirmed"] is False and pol.last_generation_complete is False
    assert (tmp_path / "DEMAND_CYCLE_05_SUPPLYMIX" / "SUPPLYMIX_BLOCK_RESULT.json").is_file()
    import inspect
    assert "outer_cycle" in inspect.signature(w).parameters


def test_design_runs_with_lowered_attribution_coverage_and_restores_policy(harness):
    from r1_15a2_supply import SupplyPolicy
    h = harness(shift=60.0)
    h.ad.policy = SupplyPolicy(lattice=0.5, max_step=8.0, max_cumulative=15.0, min_attribution_coverage=0.9)
    seen = {}
    orig = h.ad.supply_design

    def design_spy(diag, folder, snap):
        seen["cov"] = h.ad.policy.min_attribution_coverage
        seen["maxc"] = h.ad.policy.max_candidates
        return orig(diag, folder, snap)
    h.ad.supply_design = design_spy
    h.run(opts=dict(OPTS, min_attribution_coverage=0.5))
    assert seen["cov"] == 0.5 and seen["maxc"] == 60
    assert h.ad.policy.min_attribution_coverage == 0.9 and h.ad.policy.max_candidates == 8


def test_options_validation_sp(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    (tmp_path / "R1_RUN_OPTIONS.json").write_text(json.dumps({"sp_step_units": [4, 8]}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="sp_step_units"):
        dp.load_options(tmp_path, environ={})
    (tmp_path / "R1_RUN_OPTIONS.json").write_text(json.dumps({"sp_drivers": "x"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="sp_drivers"):
        dp.load_options(tmp_path, environ={})
    o = dp.load_options(tmp_path / "none", environ={"R1_SP_EVERY_N": "3", "R1_SP_STEP_UNITS": "16,8,2"})
    assert o["sp_every_n_cycles"] == 3 and o["sp_step_units"] == [16, 8, 2]


def test_td_first_cycle_of_run_then_every_n(tmp_path):
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options(tmp_path / "none", environ={"R1_TD_EVERY_N": "3"})
    assert o["td_first_cycle"] is True
    pol = dp.DemandPolicy(o)
    assert pol.td_due(1, True) == (True, "FIRST_CYCLE_OF_RUN")
    pol.note_td(1, True, False, {})
    assert pol.td_due(2, True) == (False, "NOT_DUE") and pol.td_due(3, True) == (True, "EVERY_3")
    pol2 = dp.DemandPolicy(o)                       # restart in the middle of the lineage
    assert pol2.td_due(7, True) == (True, "FIRST_CYCLE_OF_RUN")
    off = dp.DemandPolicy(dp.load_options(tmp_path / "none", environ={"R1_TD_FIRST_CYCLE": "false"}))
    assert off.td_due(1, True)[1] != "FIRST_CYCLE_OF_RUN"


# ---------------------------------------------------------------- INTADDVAL1
def test_integer_snap_rounds_away_from_zero_and_reids():
    import r1_15a2_supply_mix_v24917 as smx
    cand = {"candidate_id": "SUPPLYMIX_x", "changes": [
        {"key": [1, 2, 3], "expected_old": 0.0, "new": 0.5, "delta": 0.5},
        {"key": [2, 3, 4], "expected_old": 3.0, "new": 0.5, "delta": -2.5},
        {"key": [3, 4, 5], "expected_old": -2.0, "new": 2.0, "delta": 4.0}]}
    out = smx.snap_integer(cand)
    assert [r["new"] for r in out["changes"]] == [1.0, 0.0, 2.0]
    assert all(float(r["new"]).is_integer() for r in out["changes"])
    assert out["candidate_id"] != "SUPPLYMIX_x" and out["positive_edges"] == 2 and out["negative_edges"] == 1
    assert smx.snap_integer(None) is None


def test_addval_value_type_probe():
    import r1_15a2_supply_mix_v24917 as smx
    from types import SimpleNamespace as NS

    def adapter(vt):
        attrs = NS(ItemByKey=lambda k: NS(ValueType=vt))
        return NS(visum=NS(Net=NS(Links=NS(Attributes=attrs))))
    assert smx.addval_integer(adapter(1))["integer"] is True
    assert smx.addval_integer(adapter(2))["integer"] is False
    assert smx.addval_integer(NS())["integer"] is True          # unknown -> integer (safe for both)


# ---------------------------------------------------------- COSTFIX1 regressions

def _cost_basis(keys, *, t0=100.0):
    from r1_15a2_supply import SupplyPolicy
    return ({k: {"addval1": 0.0, "t0_c_seconds": t0, "eligible": True} for k in keys},
            {k: 0.0 for k in keys}, SupplyPolicy.from_config(CFG))


def test_costfix1_reproduces_live_integer_half_step_cost_violation():
    """Cycles 10/12/14 had a profile 920435 with step_units=1 and integer ADDVAL1.

    The design's -0.5 is legal for t0=7 s, but rounding to -1 yields -3 s.
    The entire proven branch must be skipped BEFORE any write/assignment.
    """
    from r1_15a2_supply import check_addval_change
    edge = (123, 5, 6)
    links, baseline, policy = _cost_basis([edge], t0=7.0)
    assert check_addval_change(edge, 0.0, -0.5, 0.0, links[edge], policy)
    assert sm.snap_integer({"candidate_id": "A", "changes": [
        {"key": list(edge), "expected_old": 0.0, "new": -0.5}]} )["changes"][0]["new"] == -1.0
    with pytest.raises(RuntimeError, match="NONPOSITIVE_MINIMUM_GENERALIZED_COST"):
        check_addval_change(edge, 0.0, -1.0, 0.0, links[edge], policy)
    d = {"candidates": ladder("UNDER", 920435, [edge], [-1.0],
                              units=(1,)), "authority": {"assignment_path_hash": "A"}}
    table = {"920435": {"geh": 70.0, "sign": -1}}
    cand, audit = sm.cost_safe_merged_candidate(
        d, table, OPTS, "BOTH", 8, "P", links, baseline, policy, True)
    assert cand is None
    assert audit["rejected_reasons"]["INTEGER_ADDVAL1_FRACTIONAL_STEP"] == 1


def test_costfix1_reuses_smaller_legal_proved_step_instead_of_failing():
    edge = (456, 6, 7)
    links, baseline, policy = _cost_basis([edge], t0=25.0)
    d = {"candidates": ladder("UNDER", 920435, [edge], [-1.0],
                              units=(8, 4, 2, 1)), "authority": {"assignment_path_hash": "A"}}
    table = {"920435": {"geh": 75.0, "sign": -1}}
    cand, audit = sm.cost_safe_merged_candidate(
        d, table, OPTS, "BOTH", 8, "P", links, baseline, policy, True)
    assert cand is not None and cand["changes"][0]["new"] == -2.0
    assert cand["members"][0]["step_units"] == 4
    assert audit["rejected_reasons"]["NONPOSITIVE_MINIMUM_GENERALIZED_COST"] == 1
    assert audit["full_proved_branches_only"] is True


def test_costfix1_uses_positive_bypass_when_on_path_has_no_discount_headroom():
    on = (123, 1, 2)
    off = (456, 1, 3)
    links, baseline, policy = _cost_basis([on, off], t0=7.0)
    d = {"candidates":
         ladder("ON_SHORT", 920435, [on], [-1.0], units=(2, 1), rank=1)
         + ladder("OFF_BYPASS", 920435, [off], [1.0], units=(2, 1), rank=2),
         "authority": {"assignment_path_hash": "A"}}
    table = {"920435": {"geh": 77.0, "sign": -1}}
    cand, audit = sm.cost_safe_merged_candidate(
        d, table, OPTS, "BOTH", 8, "P", links, baseline, policy, True)
    assert cand is not None
    assert cand["changes"][0]["key"] == list(off)
    assert cand["changes"][0]["new"] == 1.0
    assert audit["selected_steps"][0]["group_id"] == "OFF_BYPASS"
    assert audit["rejected_reasons"]["NONPOSITIVE_MINIMUM_GENERALIZED_COST"] == 1


def test_costfix1_does_not_invent_unproved_bypass_or_split_contiguous_path():
    edge = (456, 5, 6)
    links, baseline, policy = _cost_basis([edge], t0=5.0)
    d = {"candidates": ladder("ONLY_SHORT", 920435, [edge], [-1.0],
                              units=(8, 4, 2, 1)), "authority": {"assignment_path_hash": "A"}}
    cand, audit = sm.cost_safe_merged_candidate(
        d, {"920435": {"geh": 80.0, "sign": -1}}, OPTS, "BOTH", 8,
        "P", links, baseline, policy, True)
    assert cand is None
    assert audit["candidate_groups_selected"] == 0
    assert "NONPOSITIVE_MINIMUM_GENERALIZED_COST" in audit["rejected_reasons"]
    assert "INTEGER_ADDVAL1_FRACTIONAL_STEP" in audit["rejected_reasons"]


def test_costfix1_block_skips_unsafe_underloaded_branch_but_changes_safe_overload(harness, monkeypatch):
    h = harness(shift=60.0)
    _no_g1b(h, monkeypatch)
    h.ad.link_t0[UND[0]] = 7.0
    # Force selection of underloaded as well. Its whole branch would be unsafe.
    changed, st, dg, value, rec = h.run(opts=dict(OPTS, drivers="BOTH"))
    assert changed is True and rec["status"] == "ACCEPTED"
    assert st["addval1"][kt(UND[0])] == 0.0
    assert st["addval1"][kt(ON[0])] > 0.0
    assert rec["costfix1"]["trials"][0]["positive_generalized_link_cost_guard"] is True
    assert "NONPOSITIVE_MINIMUM_GENERALIZED_COST" in rec["costfix1"]["trials"][0]["rejected_reasons"]
    assert len(h.ad.assignments) == 1


def test_costfix1_block_only_unsafe_branch_makes_no_writes_and_no_assignment(harness, monkeypatch):
    h = harness(shift=60.0)
    d = {"candidates": ladder("ONLY_SHORT", 900002, [UND[0]], [-1.0],
                              units=(8, 4, 2, 1)),
         "authority": {"assignment_path_hash": "APH"}}
    monkeypatch.setattr(h.ad, "supply_design", lambda diag, folder, snap: (
        setattr(h.ad, "supply_path_proof", {"parent_hash": snap["state_hash"],
                                            "assignment_path_hash": "APH"}), d)[1])
    h.ad.link_t0[UND[0]] = 7.0
    changed, st, dg, value, rec = h.run(opts=dict(OPTS, drivers="BOTH"))
    assert changed is False
    assert rec["status"] == "NO_COST_SAFE_CANDIDATE"
    assert rec["search_complete"] is False and rec["stationarity_confirmed"] is False
    assert rec["stop_reason"] == "NO_COST_SAFE_PROVED_BRANCH"
    assert h.ad.writes == 0 and h.ad.assignments == []
    assert st == h.state and h.ad.snapshot() == h.state


def test_costfix1_does_not_repeat_identical_fallback_assignment(harness, monkeypatch):
    h = harness(shift=60.0)
    _no_g1b(h, monkeypatch)
    # t0=35 s means negative -4 fails but -2 is legal, for both configured
    # attempt limits 8 and 4. The second trial would repeat the same branch.
    h.ad.link_t0[OFF[0]] = 35.0
    h.ad.link_t0[OFF[1]] = 35.0
    monkeypatch.setattr(h.ad, "block_gate", lambda *a, **k: {"accepted": False, "reasons": ["TEST_REJECT"]})
    changed, st, dg, value, rec = h.run()
    assert changed is False and len(rec["attempts"]) == 1
    assert rec["stop_reason"] == "DUPLICATE_COST_SAFE_CANDIDATE"
    assert len(h.ad.assignments) == 2  # one trial, one rollback recompute
