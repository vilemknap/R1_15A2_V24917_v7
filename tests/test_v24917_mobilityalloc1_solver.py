"""MOBILITYALLOC1: exact nonlinear P/A repair of the zonal count fit."""
import numpy as np
import pytest

import r1_15a2_zonal_count_fit_v24917 as fit


def _problem():
    keys = [("WORK", "PROD", 1), ("WORK", "PROD", 2),
            ("WORK", "ATT", 1), ("WORK", "ATT", 2)]
    base = np.array([10., 10., 10., 10.])
    return fit.FitProblem(
        [1, 2], [{"observed": 10., "model": 8., "profile_index": i} for i in range(4)],
        np.eye(4), np.array([.1, 0., .05, .05]), np.ones(4),
        keys, base, np.full(4, -.2), np.full(4, .2),
        {"WORK": (np.array([10., 10., -10., -10.]), 20.)})


def _nonlinear_gap(problem, x):
    return float(problem.base[:2] @ np.expm1(x[:2])
                 - problem.base[2:] @ np.expm1(x[2:]))


def test_repair_turns_linear_pa_balance_into_actual_exponential_balance():
    problem = _problem()
    raw = np.array([.1, 0., .05, .05])
    assert problem.balance_vectors["WORK"][0] @ raw == pytest.approx(0.)
    assert _nonlinear_gap(problem, raw) > 0.01
    corrected, audit = fit.repair_nonlinear_pa(problem, raw)
    assert abs(_nonlinear_gap(problem, corrected)) < 2.e-9
    assert audit["WORK"]["within_bounds"]
    assert np.all(corrected >= problem.lower)
    assert np.all(corrected <= problem.upper)
    assert not np.array_equal(corrected, raw)
    assert np.array_equal(raw, np.array([.1, 0., .05, .05]))


def test_active_solver_option_reports_and_predicts_repaired_step():
    problem = _problem()
    result = fit.solve(problem, {"nonlinear_pa_repair": True, "max_iter": 2000})
    assert abs(_nonlinear_gap(problem, result["x"])) <= 2.e-9
    assert result["nonlinear_pa_repair"]["WORK"]["within_bounds"]
    assert np.allclose(result["predicted_change"], problem.G @ result["x"])
    assert result["objective_final"] <= result["objective_initial"]
