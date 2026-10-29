"""Numerical parity and bounded-work regressions for Generation fit speedups."""
from types import SimpleNamespace as NS

import numpy as np
import pytest

import r1_15a2_zonal_count_fit_v24917 as fit


def scalar_effect(incidence, problem):
    """Independent scalar OD accounting, before and after family centering."""
    rows = {r['profile_index']: i for i, r in enumerate(problem.profile_rows)}
    columns = {key: k for k, key in enumerate(problem.var_keys)}
    direct = np.zeros_like(problem.G)
    through = {f: np.zeros(len(rows)) for f in fit.FAMILIES}
    op = incidence['incidence']
    for p, c, a in zip(op.row_idx, op.col_idx, op.values):
        if p not in rows or a == 0:
            continue
        meta = incidence['variables'][c]
        f = meta.get('family', '').upper()
        if f not in through:
            continue
        i = rows[p]
        through[f][i] += a
        for role, zone in [('PROD', meta['origin']), ('ATT', meta['destination'])]:
            k = columns.get((f, role, zone))
            if k is not None:
                direct[i, k] += a
    fixed = np.abs(direct).sum(axis=0) <= fit.EPS
    margins = {(f, role, z): 0. for f in fit.FAMILIES for role in fit.ROLES for z in problem.zones}
    for v in incidence.get('projection_base_variables', incidence['variables']):
        f = v.get('family', '').upper()
        if f in through:
            for role, z in [('PROD', v['origin']), ('ATT', v['destination'])]:
                if (f, role, z) in margins:
                    margins[f, role, z] += max(0., float(v.get('q_current', 0.)))
    for f in fit.FAMILIES:
        # Use the authority's NumPy reduction for marginal totals. Python 3.12+
        # sum(float) uses compensation and is a different rounding algorithm.
        totals = {r: float(np.sum([margins[f, r, z] for z in problem.zones])) for r in fit.ROLES}
        if min(totals.values()) <= fit.EPS:
            continue
        center = np.array([.5*margins[f, role, z]/totals[role] if family == f else 0.
                           for family, role, z in problem.var_keys])
        direct -= np.outer(through[f], center)
    direct[:, fixed] = 0.
    return direct, through, fixed


@pytest.mark.parametrize('seed', range(5))
def test_numpy_aggregation_matches_scalar_with_duplicates_filters_and_frozen_families(seed):
    rng = np.random.default_rng(seed)
    zones = [10, 30, 20, 40, 99]  # deliberately non-sorted, last zone has no exposure
    variables = [dict(family=f, origin=o, destination=d, q_current=float(rng.uniform(1, 100)))
                 for f in ('WORK', 'SERVICE', 'LONG', 'FOREIGN')
                 for o in zones for d in zones]
    profiles = [dict(role='CALIBRATION', observed=100., model=70., profile_weight=1.)
                for _ in range(8)]
    profiles[1]['role'] = 'VALIDATION'
    profiles[2]['observed'] = 0.
    profiles[3]['profile_weight'] = 0.
    r = rng.integers(0, len(profiles), 400)
    c = rng.integers(0, len(variables), 400)
    a = rng.uniform(.001, 30., 400)
    a[::9] = 0.
    # Remove exposure of zone 99 while retaining its reference margins.
    a[[v['origin'] == 99 or v['destination'] == 99 for v in (variables[i] for i in c)]] = 0.
    r = np.r_[r, r[:15], -1, 100]
    c = np.r_[c, c[:15], 999999, 999999]  # unfitted rows must not dereference OD metadata
    a = np.r_[a, a[:15], 1., 1.]
    inc = dict(profiles=profiles, variables=variables, projection_base_variables=variables,
               incidence=NS(row_idx=r, col_idx=c, values=a))
    bounds = {(f, role, z): (-.2, .4) for f in fit.FAMILIES for role in fit.ROLES for z in zones}
    del bounds['WORK', 'ATT', 30]  # excluded actuator, not excluded OD throughput
    p = fit.build_problem(inc, zones, bounds, {})
    reference, through, fixed = scalar_effect(inc, p)
    np.testing.assert_array_equal(p.G, reference)
    assert p.unexposed_count == np.count_nonzero(fixed)
    assert [row['profile_index'] for row in p.profile_rows] == [0, 4, 5, 6, 7]
    for i, row in enumerate(p.profile_rows):
        assert row['mutable_through_work'] == through['WORK'][i]
        assert row['mutable_through_service'] == through['SERVICE'][i]
    assert all(k[0] in fit.FAMILIES for k in p.var_keys)
    np.testing.assert_array_equal(p.lower[fixed], 0.)
    np.testing.assert_array_equal(p.upper[fixed], 0.)


def test_empty_incidence_keeps_all_actuators_fixed():
    inc = dict(profiles=[dict(role='CALIBRATION', observed=1., model=1.)],
               variables=[dict(family='WORK', origin=1, destination=1, q_current=1.)],
               incidence=NS(row_idx=[], col_idx=[], values=[]))
    p = fit.build_problem(inc, [1], {('WORK', r, 1): (-.1, .1) for r in fit.ROLES}, {})
    np.testing.assert_array_equal(p.G, np.zeros((1, 2)))
    assert p.unexposed_count == 2


def legacy_projection(z, lo, hi, vecs):
    """The pre-optimization 100-bisection numerical reference."""
    result = np.clip(z, lo, hi)
    for vec in vecs:
        idx = np.flatnonzero(np.abs(vec) > fit.EPS)
        if not len(idx): continue
        v = vec[idx]
        def candidate(lam): return np.clip(z[idx] - lam*v, lo[idx], hi[idx])
        def g(lam): return float(v @ candidate(lam))
        g0 = g(0.)
        if abs(g0) <= 1e-12*max(1., float(np.abs(v) @ np.abs(candidate(0.)))):
            continue
        step = max(1e-12, abs(g0)/max(fit.EPS, float(v@v)))
        a, b = 0., step if g0 > 0 else -step
        for _ in range(200):
            if (g(b)>0) != (g0>0) or g(b) == 0: break
            a, b = b, 2*b
        left, right = min(a,b), max(a,b)
        for _ in range(100):
            mid = .5*(left+right)
            if g(mid) > 0: left = mid
            else: right = mid
        result[idx] = candidate(.5*(left+right))
    return result


@pytest.mark.parametrize('seed', range(5))
def test_projection_matches_legacy_and_preserves_original_tolerance(seed):
    rng = np.random.default_rng(seed)
    z = rng.normal(0., .8, 32)
    lo, hi = -rng.uniform(0., .4, 32), rng.uniform(0., .5, 32)
    lo[0] = hi[0] = 0.
    vectors = [np.r_[rng.uniform(.1, 10, 8), -rng.uniform(.1, 10, 8), np.zeros(16)],
               np.r_[np.zeros(16), rng.uniform(.1, 10, 8), -rng.uniform(.1, 10, 8)], np.zeros(32)]
    expected = legacy_projection(z, lo, hi, vectors)
    actual = fit.project_box_hyperplanes(z, lo, hi, vectors)
    np.testing.assert_allclose(actual, expected, atol=2e-11, rtol=0.)
    assert np.all(actual >= lo) and np.all(actual <= hi)
    for v in vectors:
        assert abs(v @ actual) <= 1e-12*max(1., float(np.abs(v) @ np.abs(actual)))


def test_projection_finishes_before_fixed_bisection_budget(monkeypatch):
    calls = []
    clip = np.clip
    monkeypatch.setattr(fit.np, 'clip', lambda *a, **kw: calls.append(1) or clip(*a, **kw))
    z = np.array([.37, -.18, .04, .11])
    lo, hi, v = np.full(4, -.2), np.full(4, .3), np.array([2., 3., -5., -1.])
    result = fit.project_box_hyperplanes(z, lo, hi, [v])
    assert len(calls) < 90  # no timing-sensitive wall-clock assertion
    assert abs(v @ result) <= 1e-12*max(1., float(np.abs(v) @ np.abs(result)))


def nonlinear_problem():
    keys = [(f, r, z) for f in fit.FAMILIES for r in fit.ROLES for z in [1, 2, 3]]
    base = np.array([150., 400., 30., 240., 110., 230.]*2)
    vectors = {f: (np.array([b if r == 'PROD' else -b if r == 'ATT' else 0.
                           for (ff, r, _), b in zip(keys, base)]) *
                       np.array([ff == f for ff, _, _ in keys]), 580.) for f in fit.FAMILIES}
    return fit.FitProblem([1, 2, 3], [], np.zeros((0, 12)), np.zeros(0), np.zeros(0), keys,
                          base, np.full(12, -.2), np.full(12, .4), vectors)


def legacy_nonlinear(p, raw):
    x = raw.copy()
    for family in p.balance_vectors:
        prod = [i for i, key in enumerate(p.var_keys) if key[:2] == (family, 'PROD')]
        att = [i for i, key in enumerate(p.var_keys) if key[:2] == (family, 'ATT')]
        before = x.copy()
        def candidate(lam):
            trial = before.copy()
            trial[prod] = np.clip(before[prod]-lam, p.lower[prod], p.upper[prod])
            trial[att] = np.clip(before[att]+lam, p.lower[att], p.upper[att])
            return trial
        left, right = -1., 1.
        for _ in range(100):
            mid = .5*(left+right)
            t = candidate(mid)
            gap = p.base[prod] @ np.expm1(t[prod]) - p.base[att] @ np.expm1(t[att])
            if gap > 0: left = mid
            else: right = mid
        x[prod+att] = candidate(.5*(left+right))[prod+att]
    return x


@pytest.mark.parametrize('tolerance', [1e-10, 1e-13])
def test_nonlinear_pa_uses_original_tolerance_with_less_work(monkeypatch, tolerance):
    p = nonlinear_problem()
    raw = np.array([.37, -.18, .04, .11, .2, -.1]*2)
    expected = legacy_nonlinear(p, raw)
    calls = []
    expm1 = np.expm1
    monkeypatch.setattr(fit.np, 'expm1', lambda *a, **kw: calls.append(1) or expm1(*a, **kw))
    actual, report = fit.repair_nonlinear_pa(p, raw, tolerance=tolerance)
    np.testing.assert_allclose(actual, expected, atol=2*tolerance, rtol=0.)
    assert np.all(actual >= p.lower) and np.all(actual <= p.upper)
    assert len(calls) < 360  # two families previously used >400 expm1 evaluations
    for f, row in report.items():
        assert row['allowed_gap'] == tolerance*max(1., p.balance_vectors[f][1])
        assert abs(row['nonlinear_pa_gap']) <= row['allowed_gap']
    np.testing.assert_array_equal(raw, [.37, -.18, .04, .11, .2, -.1]*2)


def test_solver_predictions_and_objective_match_original_projection(monkeypatch):
    from test_v24917_targeted_catchup import synthetic_incidence, all_bounds
    inc, zones = synthetic_incidence(n_zones=6)
    p = fit.build_problem(inc, zones, all_bounds(zones), {})
    actual = fit.solve(p, {'nonlinear_pa_repair': True})
    monkeypatch.setattr(fit, 'project_box_hyperplanes', legacy_projection)
    expected = fit.solve(p, {'nonlinear_pa_repair': True})
    np.testing.assert_allclose(actual['predicted_change'], expected['predicted_change'], rtol=1e-8, atol=1e-8)
    assert actual['objective_final'] == pytest.approx(expected['objective_final'], rel=1e-9)
    assert actual['converged'] == expected['converged']
