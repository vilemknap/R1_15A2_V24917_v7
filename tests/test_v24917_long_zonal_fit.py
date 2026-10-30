"""LONG uses the W/S normalized OD-to-profile local response, offline only."""
import numpy as np
import pytest

import r1_15a2_core as core
import r1_15a2_long_zonal_fit_v24917 as longfit
import r1_15a2_zonal_count_fit_v24917 as zf
from r1_15a2_skim_v24916p2c import ordered_zone_hash


def _inputs():
    zones = (1, 2)
    observed = {
        "status": "OBSERVED_LONG_OD_PROFILE_ONLY",
        "source_status": "CALLER_SUPPLIED_INPUTS_LIVE_EPOCH_UNVERIFIED",
        "zone_order_sha256": ordered_zone_hash(zones),
        "vehicle_production": np.array([100., 50.]),
        "vehicle_attraction": np.array([50., 100.]),
        "vehicle_total": 150.,
        # Synthetic fully-overnight case reproduces the old normalized
        # path formula; real AMDY elasticity is normally strictly below 1.
        "attraction_elasticity": {1: 1.0, 2: 1.0},
        "profile_identity": ["P0", "P1"],
        "variables": [
            {"dseg_code": "NATIVE_CL", "family": "LONG", "origin": 1,
             "destination": 2, "q_current": 100.},
            {"dseg_code": "NATIVE_CL", "family": "LONG", "origin": 2,
             "destination": 1, "q_current": 50.},
        ],
        "incidence": core.SparseOperator(np.array([0, 1]), np.array([0, 1]),
                                         np.array([100., 50.]), 2, 2),
    }
    rows = [{"profile_index": 0, "countlocation_no": "P0", "observed": 120., "model": 100.},
            {"profile_index": 1, "countlocation_no": "P1", "observed": 40., "model": 50.}]
    ws_problem = zf.FitProblem(zones, rows, np.zeros((2, 0)), np.array([20., -10.]),
                               np.ones(2), [], np.array([]), np.array([]), np.array([]), {})
    ws_solution = {"predicted_change": np.array([5., 0.])}
    bounds = {("LONG", role, z): (-0.1, 0.1)
              for role in ("PROD", "ATT") for z in zones}
    return observed, ws_problem, ws_solution, zones, bounds


def test_long_G_matches_work_service_normalized_path_formula():
    observed, ws, sol, zones, bounds = _inputs()
    problem = longfit.build_problem(observed, ws, sol, zones, bounds)
    assert problem.var_keys == [("LONG", "PROD", 1), ("LONG", "PROD", 2),
                                ("LONG", "ATT", 1), ("LONG", "ATT", 2)]
    assert problem.base == pytest.approx([100., 50., 50., 100.])
    np.testing.assert_allclose(problem.G,
        [[100.-100./3, -100./6, -100./6, 100.-100./3],
         [-50./3, 50.-50./6, 50.-50./6, -50./3]])
    assert problem.target == pytest.approx([15., -10.])
    assert problem.balance_vectors["LONG"][0] == pytest.approx([100., 50., -50., -100.])


def test_intrazonal_mass_enters_normalizer_without_profile_exposure():
    observed, ws, sol, zones, bounds = _inputs()
    observed["vehicle_production"][0] += 20.
    observed["vehicle_attraction"][0] += 20.
    observed["vehicle_total"] += 20.
    problem = longfit.build_problem(observed, ws, sol, zones, bounds)
    assert problem.base == pytest.approx([120., 50., 70., 100.])
    assert problem.G[0, 0] == pytest.approx(100. - 100. * .5 * 120. / 170.)
    assert problem.G[1, 0] == pytest.approx(-50. * .5 * 120. / 170.)


def test_diagnostic_fit_improves_target_and_keeps_exact_pa_balance():
    args = _inputs()
    result = longfit.fit(*args, solver_cfg={"max_iter": 2000})
    assert result["status"] == "LOCAL_LINEAR_PROPOSAL_ONLY"
    assert result["long_generation_permitted"] is False
    assert result["native_filter_verified"] is False
    assert "candidate_rows" not in result
    problem, solution = result["problem"], result["solution"]
    assert solution["objective_final"] < solution["objective_initial"]
    assert solution["balance_mode"] == "HARD"
    assert np.all(solution["x"] >= problem.lower - 1.e-12)
    assert np.all(solution["x"] <= problem.upper + 1.e-12)
    prod = problem.base[:2] @ np.expm1(solution["x"][:2])
    att = problem.base[2:] @ np.expm1(solution["x"][2:])
    assert prod == pytest.approx(att, abs=2.e-8)
    assert result["predicted_profile_change"] == pytest.approx(problem.G @ solution["x"])


def test_unexposed_zones_and_identity_mismatch_fail_closed():
    observed, ws, sol, zones, bounds = _inputs()
    observed["variables"].extend([
        {"dseg_code": "NATIVE_CL", "family": "LONG", "origin": 3,
         "destination": 1, "q_current": 10.},
        {"dseg_code": "NATIVE_CL", "family": "LONG", "origin": 1,
         "destination": 3, "q_current": 10.},
    ])
    observed["incidence"] = core.SparseOperator(np.array([0, 1]), np.array([0, 1]),
                                                  np.array([100., 50.]), 2, 4)
    observed["vehicle_production"] = np.array([110., 50., 10.])
    observed["vehicle_attraction"] = np.array([60., 100., 10.])
    observed["vehicle_total"] = 170.
    observed["attraction_elasticity"][3] = 1.0
    zones = (1, 2, 3)
    observed["zone_order_sha256"] = ordered_zone_hash(zones)
    bounds.update({("LONG", role, 3): (-.1, .1) for role in ("PROD", "ATT")})
    problem = longfit.build_problem(observed, ws, sol, zones, bounds)
    assert problem.unexposed_count == 2
    assert problem.lower[2] == problem.upper[2] == 0.
    assert problem.lower[5] == problem.upper[5] == 0.
    observed["profile_identity"][0] = "WRONG"
    with pytest.raises(ValueError, match="PROFILE_IDENTITY_MISMATCH"):
        longfit.build_problem(observed, ws, sol, zones, bounds)


def test_wrong_source_or_bounds_cannot_produce_long_proposal():
    observed, ws, sol, zones, bounds = _inputs()
    with pytest.raises(ValueError, match="BOUND_INVALID"):
        longfit.build_problem(observed, ws, sol, zones,
                              {**bounds, ("LONG", "PROD", 1): (0.01, 0.1)})
    observed["status"] = "UNVERIFIED"
    with pytest.raises(ValueError, match="OBSERVED_INCIDENCE_REQUIRED"):
        longfit.fit(observed, ws, sol, zones, bounds)


def test_long_overnight_only_derivative_and_exact_balance():
    observed, ws, sol, zones, bounds = _inputs()
    # PROD applies to the whole source production; ADD_ATT_L changes only
    # 25/50 percent of the attraction through PRENOC_SVK.
    observed["attraction_elasticity"] = {1: .25, 2: .50}
    p = longfit.build_problem(observed, ws, sol, zones, bounds,
                              observed["attraction_elasticity"])
    assert p.base == pytest.approx([100., 50., 12.5, 50.])
    assert p.balance_vectors["LONG"][0] == pytest.approx([100., 50., -12.5, -50.])
    # The destination-2 profile contribution is scaled by eta_2=.5,
    # not by one, and the normalization is scaled consistently.
    assert p.G[0, 3] == pytest.approx(
        100. * .5 - 100. * .5 * 50. / 150.)
    assert p.G[1, 2] == pytest.approx(
        50. * .25 - 50. * .5 * 12.5 / 150.)
    solution = zf.solve(p, {"balance_mode": "HARD",
                            "nonlinear_pa_repair": True,
                            "max_iter": 2000})
    prod = p.base[:2] @ np.expm1(solution["x"][:2])
    att = p.base[2:] @ np.expm1(solution["x"][2:])
    assert prod == pytest.approx(att, abs=2e-8)


def test_missing_or_invalid_overnight_share_fails_closed():
    obs, ws, sol, zones, bounds = _inputs()
    del obs["attraction_elasticity"]
    with pytest.raises(ValueError, match="LONG_FIT_OVERNIGHT_ELASTICITY_REQUIRED"):
        longfit.build_problem(obs, ws, sol, zones, bounds)
    with pytest.raises(ValueError, match="LONG_FIT_OVERNIGHT_ELASTICITY_INVALID"):
        longfit.build_problem(obs, ws, sol, zones, bounds,
                              {1: .2, 2: 1.4})
