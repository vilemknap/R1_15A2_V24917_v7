"""A rejected spatial direction may be re-solved, never merely relabelled accepted."""
import copy
import math
from types import SimpleNamespace

import numpy as np
import pytest

import r1_15a2_zonal_count_fit_v24917 as zf
import r1_15a2_trial_adapter_v24917 as adapter_mod
from test_v24917_step_search import harness, opts, linear_model, STEP  # noqa: F401


def problem():
    rows = [{"countlocation_no": str(920001+i), "observed": 1000.0,
             "model": 600.0 if i == 0 else 1000.0, "geh": 10.0 if i == 0 else 0.0}
            for i in range(2)]
    return zf.FitProblem([1, 2], rows, np.array([[100., 60., 100., 60.], [3., -3., 3., -3.]]),
        np.array([400., 0.]), np.array([1., 3.]),
        [("WORK", role, z) for role in ("PROD", "ATT") for z in (1, 2)],
        np.ones(4)*1000, np.ones(4)*-.22, np.ones(4)*.4,
        {"WORK": (np.array([1000., 1000., -1000., -1000.]), 2000.)})


def test_secant_operator_matches_measurement_without_mutating_original():
    p = problem()
    original = p.G.copy(), p.lower.copy(), p.upper.copy()
    x = np.ones(4)*.4
    delta = np.array([150., 300.])
    new, audit = zf.measured_refit_problem(p, x, delta, .5)
    np.testing.assert_allclose(new.G @ x, delta, atol=1e-12)
    for actual, before in zip((p.G, p.lower, p.upper), original):
        np.testing.assert_array_equal(actual, before)
    np.testing.assert_allclose(new.lower, p.lower*.5)
    np.testing.assert_allclose(new.upper, p.upper*.5)
    assert audit["authority"] == "LOCAL_PROPOSAL_ONLY_NOT_NATIVE_ZONAL_JACOBIAN"
    assert audit["prediction_error_l2_after"] < 1e-12
    # Information orthogonal to the measured vector is preserved, not invented.
    orthogonal = np.array([1., -1., 0., 0.])
    np.testing.assert_allclose(new.G @ orthogonal, p.G @ orthogonal)


def test_measured_fit_can_leave_a_saturated_common_direction_with_exact_pa():
    p = problem()
    original = zf.solve(p, {"ridge_relative": .01})
    np.testing.assert_allclose(original["x"], .4, atol=1e-8)
    new, _ = zf.measured_refit_problem(p, original["x"], np.array([150., 300.]), .5)
    result = zf.solve(new, {"ridge_relative": .01, "nonlinear_pa_repair": True})
    assert result["converged"]
    assert np.ptp(result["x"]) > .05  # different zones, not a common shrunken scale
    assert np.all(result["x"] >= new.lower-1e-10)
    assert np.all(result["x"] <= new.upper+1e-10)
    b = result["nonlinear_pa_repair"]["WORK"]
    assert abs(b["nonlinear_pa_gap"]) <= b["allowed_gap"]


def test_indistinguishable_zones_are_not_differentiated_artificially():
    p = problem()
    p.G[:, :] = np.array([[100.], [2.]])
    corrected, _ = zf.measured_refit_problem(p, np.ones(4)*.4, np.array([200., 80.]), .5)
    fit = zf.solve(corrected, {"ridge_relative": .01, "nonlinear_pa_repair": True})
    assert np.ptp(fit["x"]) < 1e-9


@pytest.mark.parametrize("x,delta,fraction", [
    (np.zeros(4), np.ones(2), .5),
    (np.ones(3), np.ones(2), .5),
    (np.ones(4)*.2, np.ones(3), .5),
    (np.array([np.nan, .1, .1, .1]), np.ones(2), .5),
    (np.ones(4)*.2, np.array([np.inf, 1.]), .5),
    (np.ones(4)*.41, np.ones(2), .5),
    (np.ones(4)*.2, np.ones(2), 0),
    (np.ones(4)*.2, np.ones(2), .51),
])
def test_invalid_or_unmeasured_directions_cannot_refit(x, delta, fraction):
    with pytest.raises(ValueError, match="V24917_REFIT_"):
        zf.measured_refit_problem(problem(), x, delta, fraction)


def adapter_context():
    import r1_15a2_targeted_generation_v24917 as tg
    ad = adapter_mod.VisumAdapter.__new__(adapter_mod.VisumAdapter)
    ad.cfg = {tg.POLICY_KEY: copy.deepcopy(tg.DEFAULT_POLICY)}
    p = problem()
    ls = {"steps": {"ADD_PROD_L": {}, "ADD_ATT_L": {}}, "predicted_change": [0., 0.]}
    ctx = {"_genfix2_effect_model": {"problem": p, "ls": ls, "bd": None},
           "_mobilityzone1": {"enabled": False},
           "_genfix2_mobility": {"zone_rows": [], "options": {"enabled": False, "lo": .75, "hi": 2.5}},
           "v24917": {"overlay_phase": "CATCH_UP"}}
    rows = [dict(r, role="CALIBRATION") for r in p.profile_rows]
    before = {"d12": {"rows": rows}}
    after = {"d12": {"rows": [dict(r, model=r["model"]+d) for r,d in zip(rows, [150., 300.])]}}
    preview = {"effect_rows": [{"family": f, "role": r, "zone_no": z,
                               "implemented_total_log_effect": .4} for f,r,z in p.var_keys]}
    return ad, ctx, preview, before, after


def test_real_adapter_refits_without_visum_access_and_retains_parent(tmp_path):
    ad, ctx, preview, before, after = adapter_context()
    new, audit = ad.refine_generation_design(ctx, 1., preview, before, after, tmp_path)
    assert new is not None and audit["status"] == "ZONAL_DIRECTION_REFITTED"
    assert new["_genfix2_mobility"] is ctx["_genfix2_mobility"]
    assert new["_mobilityzone1"] is ctx["_mobilityzone1"]
    assert ctx["_genfix2_effect_model"]["problem"].G[0, 0] == 100.
    assert "measured_zonal_refit" not in ctx["v24917"]
    assert (tmp_path / "MEASURED_ZONAL_REFIT.json").is_file()
    # The preview operator must use the revised model, not stale fit output.
    prediction = ad._final_step_prediction(new, preview, 1.)
    np.testing.assert_allclose(prediction["delta"], [150., 300.])


@pytest.mark.parametrize("change", ["observation", "missing", "duplicate", "parent", "nan"])
def test_adapter_rejects_unbound_measurements(tmp_path, change):
    ad, ctx, preview, before, after = adapter_context()
    if change == "observation": after["d12"]["rows"][0]["observed"] += 1
    if change == "missing": after["d12"]["rows"].pop()
    if change == "duplicate": after["d12"]["rows"].append(dict(after["d12"]["rows"][0]))
    if change == "parent": before["d12"]["rows"][0]["model"] += 1
    if change == "nan": after["d12"]["rows"][0]["model"] = float("nan")
    with pytest.raises(ValueError, match="V24917_REFIT_"):
        ad.refine_generation_design(ctx, 1., preview, before, after, tmp_path)


@pytest.mark.parametrize("by_zone, predicted", [({1: .01}, [0., 0.]), ({}, [1., 0.])])
def test_mixed_long_response_is_not_assigned_to_ws_columns(tmp_path, by_zone, predicted):
    ad, ctx, preview, before, after = adapter_context()
    ctx["_genfix2_effect_model"]["ls"] = {"steps": {"ADD_PROD_L": by_zone}, "predicted_change": predicted}
    new, audit = ad.refine_generation_design(ctx, 1., preview, before, after, tmp_path)
    assert new is None and audit["status"] == "DEFERRED_MIXED_LONG_SCHOOL_ACTUATORS"


def test_boundary_uses_actual_joint_pa_column():
    p = SimpleNamespace(var_keys=[("WORK", "PROD", 1), ("WORK", "PA", 99)])
    preview = {"effect_rows": [{"family": "WORK", "role": "PROD", "zone_no": 1,
                               "implemented_total_log_effect": .017}]}
    x = adapter_mod.VisumAdapter._implemented_fit_vector(p, preview, .2, {"steps": {"WORK|99": .3}})
    np.testing.assert_allclose(x, [.017, .06])


def _refining_adapter(harness, monkeypatch):
    ad = harness.ad
    preview0, design0 = ad.generation_preview, ad.generation_design
    monkeypatch.setattr(ad, "generation_design", lambda d, f: dict(design0(d, f), revision=0))
    def preview(ctx, scale):
        rows = preview0(ctx, scale)["candidate_rows"]
        if ctx["revision"] == 1:
            for r in rows:
                z = str(r["zone_no"])
                r["current"] = ad.g0[z]
                r["proposed"] = ad.g0[z]*math.exp(0. if z == "1" else scale*STEP*.5)
        return {"candidate_rows": rows}
    monkeypatch.setattr(ad, "generation_preview", preview)
    calls = []
    def refine(ctx, scale, preview, before, after, folder):
        calls.append(ctx["revision"])
        assert before == harness.diag  # never promote rejected diagnostics to parent
        lin = linear_model()
        lin["delta_full"] = [0.] + [v*.5 for v in lin["delta_full"][1:]]
        return dict(ctx, revision=1, v24917_step_model=lin), {"status": "ZONAL_DIRECTION_REFITTED"}
    monkeypatch.setattr(ad, "refine_generation_design", refine, raising=False)
    return ad, calls


def test_controller_refits_once_and_adopts_new_spatial_direction(harness, monkeypatch):
    ad, calls = _refining_adapter(harness, monkeypatch)
    changed, state, diag, value, rec = harness.run()
    assert changed and rec["adopted_in_place"]
    assert calls == [0]
    assert [a["plan_mode"] for a in rec["attempts"]] == ["LINEAR_FIT", "MEASURED_ZONAL_REFIT"]
    assert ad.g["1"] == 1. and ad.g["2"] > 1.
    assert len(ad.assignments) == 2  # same budget; no extra assignment for the refit
    assert rec["measured_zonal_refit"]["status"] == "ZONAL_DIRECTION_REFITTED"


def test_refit_unavailable_retains_existing_measured_secant_search(harness, monkeypatch):
    def unavailable(*args): raise ValueError("invalid evidence")
    monkeypatch.setattr(harness.ad, "refine_generation_design", unavailable, raising=False)
    changed, state, diag, value, rec = harness.run()
    assert changed
    assert rec["measured_zonal_refit"]["status"] == "REFIT_UNAVAILABLE"
    assert rec["attempts"][1]["plan_mode"] == "SECANT_MEASURED"


def test_error_in_new_direction_retains_recovery_for_both_trials(harness, monkeypatch):
    ad, calls = _refining_adapter(harness, monkeypatch)
    original = ad.assign_for_block
    def fail_second(folder, block):
        if len(ad.assignments) == 1 and "ROLLBACK" not in str(folder):
            raise RuntimeError("second native assignment failed")
        return original(folder, block)
    monkeypatch.setattr(ad, "assign_for_block", fail_second)
    with pytest.raises(Exception, match="second native assignment failed"):
        harness.run()
    assert calls == [0]
    assert ad.snapshot() == harness.state
    assert ad.diags[-1] == "ROLLBACK"


def test_native_rejection_cannot_be_overridden_and_trial_budget_is_shared(harness, monkeypatch):
    ad, calls = _refining_adapter(harness, monkeypatch)
    monkeypatch.setattr(ad, "block_gate", lambda *args: {"accepted": False, "reasons": ["NATIVE_REJECTED"]})
    changed, state, diag, value, rec = harness.run()
    assert not changed and calls == [0]
    assert len(rec["attempts"]) == rec["planned_trials"] == 3
    assert all(a["status"] == "REJECTED" for a in rec["attempts"])
    assert len(ad.assignments) == 4  # three trials + the one verified rollback
    assert ad.snapshot() == harness.state
