# -*- coding: utf-8 -*-
"""V24917 targeted Generation proposal: zonal P/A log multipliers fitted to counts.

Why
---
The inherited proposal chain (OD guidance -> MARGINALS projection -> family
global step + centred zonal pattern) conserves *margin totals*, not the count
effect.  A zone whose trips mostly do not cross a counted profile receives a
tiny margin request, and the family-global term is applied to every zone
uniformly.  With the model carrying ~26 % of RPDI the implemented TG step was
~0.4 % of the counted volume per cycle.

What
----
For each family f in (WORK, SERVICE) we fit zonal log multipliers of the
production (u) and attraction (v) coefficients directly against the CAL count
residuals, using the exact path incidence of the current path epoch (the same
per-profile OD attribution that FlowBundle reproduces in Visum):

    delta_od  ~= u_o + v_d - g_f              (doubly constrained, log-linear)
    g_f        = (sum P_i u_i / P_f + sum A_j v_j / A_f) / 2
    Delta_p    = sum_od a_{p,od} * delta_od   (a = OD flow through profile p)

    min  sum_p w_p^2 (r_p - Delta_p)^2  +  lambda ||x||^2
         + mu_f (sum_i P_i u_i - sum_j A_j v_j)^2 / P_f^2
    s.t. lo <= x <= hi   (per-zone step and coefficient-domain bounds)

with GEH-linearised weights w_p = sqrt(2 * weight / max(floor, obs + model)).
Zones without count exposure have zero data curvature and stay at 0 through
the ridge, so the proposal is targeted by construction.  Over-loaded profiles
(negative residual) pull the zones that load them downwards.  The result is a
list of projection rows in the inherited schema; the acceptance authority
(fresh assignment + live 12D/11D + all guards + rollback) is unchanged.

Pure numpy; no COM access.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

RELEASE = "R1_15A2_V24917_ZONAL_COUNT_FIT_V1"
METHOD = "V24917_ZONAL_COUNT_FIT"
FAMILIES = ("WORK", "SERVICE")
ROLES = ("PROD", "ATT")
EPS = 1.0e-12


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def geh(model: float, observed: float) -> float:
    denom = model + observed
    return math.sqrt(2.0 * (model - observed) ** 2 / denom) if denom > EPS else 0.0


class FitProblem:
    """Dense effect matrix G (profiles x variables) and bookkeeping."""

    def __init__(self, zones: Sequence[int], profile_rows: List[Dict[str, Any]],
                 G: np.ndarray, target: np.ndarray, weight: np.ndarray,
                 var_keys: List[Tuple[str, str, int]], base: np.ndarray,
                 lower: np.ndarray, upper: np.ndarray,
                 balance_vectors: Dict[str, Tuple[np.ndarray, float]]):
        self.zones = list(zones)
        self.profile_rows = profile_rows
        self.G = G
        self.target = target
        self.weight = weight
        self.var_keys = var_keys
        self.base = base
        self.lower = lower
        self.upper = upper
        self.balance_vectors = balance_vectors


def build_problem(incidence: Mapping[str, Any], zones: Sequence[int],
                  bounds: Mapping[Tuple[str, str, int], Tuple[float, float]],
                  cfg: Mapping[str, Any]) -> FitProblem:
    """Assemble the linear effect model from an inherited incidence result.

    ``bounds`` maps (family, role, zone) -> (low_log, high_log); a key absent
    from ``bounds`` is not an actuator (fixed at 0).
    """
    profiles = list(incidence["profiles"])
    variables = list(incidence["variables"])
    base_vars = list(incidence.get("projection_base_variables") or variables)
    op = incidence["incidence"]
    zones = [int(z) for z in zones]
    zidx = {z: i for i, z in enumerate(zones)}
    nz = len(zones)
    role_cfg = str(cfg.get("calibration_role", "CALIBRATION")).upper()
    floor = float(cfg.get("observed_weight_floor", 100.0))
    protected_geh = float(cfg.get("protected_geh", 5.0))
    protected_mult = float(cfg.get("protected_weight_multiplier", 3.0))

    # Rows: CAL profiles with positive observation.
    rows: List[Dict[str, Any]] = []
    row_of_profile: Dict[int, int] = {}
    for pidx, p in enumerate(profiles):
        if str(p.get("role", "")).upper() != role_cfg:
            continue
        obs = _f(p.get("observed"))
        model = _f(p.get("model"))
        if obs <= 0.0:
            continue
        w0 = _f(p.get("profile_weight", 1.0), 1.0)
        if w0 <= 0.0:
            continue
        g = geh(model, obs)
        w = math.sqrt(2.0 * w0 / max(floor, obs + model))
        if g < protected_geh:
            w *= protected_mult
        row_of_profile[pidx] = len(rows)
        rows.append({"profile_index": pidx, "observed": obs, "model": model,
                     "residual": obs - model, "geh": g, "weight": w,
                     "protected": g < protected_geh,
                     "countlocation_no": p.get("countlocation_no", p.get("profile_id", pidx))})
    if not rows:
        raise ValueError("V24917_FIT_NO_CALIBRATION_ROWS")

    # Margins per family from the full NATIVE WORK/SERVICE base catalogue.
    margins = {(f, r): np.zeros(nz) for f in FAMILIES for r in ROLES}
    for meta in base_vars:
        fam = str(meta.get("family", "")).upper()
        if fam not in FAMILIES:
            continue
        o, d = int(meta["origin"]), int(meta["destination"])
        q = max(0.0, _f(meta.get("q_current")))
        if o in zidx:
            margins[(fam, "PROD")][zidx[o]] += q
        if d in zidx:
            margins[(fam, "ATT")][zidx[d]] += q

    # Variables: (family, role, zone) actuators with bounds and positive base.
    var_keys: List[Tuple[str, str, int]] = []
    var_index: Dict[Tuple[str, str, int], int] = {}
    base_list, lo_list, hi_list = [], [], []
    for fam in FAMILIES:
        for role in ROLES:
            for z in zones:
                key = (fam, role, z)
                b = margins[(fam, role)][zidx[z]]
                if key not in bounds or b <= EPS:
                    continue
                lo, hi = bounds[key]
                lo, hi = float(min(0.0, lo)), float(max(0.0, hi))
                if hi - lo <= EPS:
                    continue
                var_index[key] = len(var_keys)
                var_keys.append(key)
                base_list.append(b)
                lo_list.append(lo)
                hi_list.append(hi)
    nv = len(var_keys)
    if nv == 0:
        raise ValueError("V24917_FIT_NO_ACTUATOR_VARIABLES")
    G = np.zeros((len(rows), nv))
    mutable_through = {f: np.zeros(len(rows)) for f in FAMILIES}

    r_idx = np.asarray(op.row_idx, dtype=np.int64)
    c_idx = np.asarray(op.col_idx, dtype=np.int64)
    vals = np.asarray(op.values, dtype=float)
    for p, c, a in zip(r_idx.tolist(), c_idx.tolist(), vals.tolist()):
        row = row_of_profile.get(int(p))
        if row is None or a == 0.0:
            continue
        meta = variables[int(c)]
        fam = str(meta.get("family", "")).upper()
        if fam not in FAMILIES:
            continue
        o, d = int(meta["origin"]), int(meta["destination"])
        mutable_through[fam][row] += a
        ko = var_index.get((fam, "PROD", o))
        kd = var_index.get((fam, "ATT", d))
        if ko is not None:
            G[row, ko] += a
        if kd is not None:
            G[row, kd] += a

    # A zone without any direct count exposure is not an actuator of this fit:
    # it could only act through the family normalisation term below, i.e. by
    # shifting demand to other zones.  It stays at 0 (targeted by design).
    direct_exposure = np.abs(G).sum(axis=0)
    unexposed = direct_exposure <= EPS

    # Family mean-growth correction (doubly constrained): a uniform change c of
    # both P and A must change every OD by c, not 2c, hence
    #   g_f = 0.5 * (sum_i P_i u_i / P_f + sum_j A_j v_j / A_f).
    balance_vectors: Dict[str, Tuple[np.ndarray, float]] = {}
    for fam in FAMILIES:
        p_tot = float(np.sum(margins[(fam, "PROD")]))
        a_tot = float(np.sum(margins[(fam, "ATT")]))
        if p_tot <= EPS or a_tot <= EPS:
            continue
        gvec = np.zeros(nv)
        bvec = np.zeros(nv)
        for k, (f2, role, z) in enumerate(var_keys):
            if f2 != fam:
                continue
            if role == "PROD":
                b = margins[(fam, "PROD")][zidx[z]]
                gvec[k] = 0.5 * b / p_tot
                bvec[k] = b
            else:
                b = margins[(fam, "ATT")][zidx[z]]
                gvec[k] = 0.5 * b / a_tot
                bvec[k] = -b
        G -= np.outer(mutable_through[fam], gvec)
        balance_vectors[fam] = (bvec, 0.5 * (p_tot + a_tot))

    lo_arr = np.asarray(lo_list); hi_arr = np.asarray(hi_list)
    lo_arr[unexposed] = 0.0
    hi_arr[unexposed] = 0.0
    G[:, unexposed] = 0.0
    target = np.asarray([r["residual"] for r in rows], dtype=float)
    weight = np.asarray([r["weight"] for r in rows], dtype=float)
    for i, r in enumerate(rows):
        r["mutable_through_work"] = float(mutable_through["WORK"][i])
        r["mutable_through_service"] = float(mutable_through["SERVICE"][i])
    problem = FitProblem(zones, rows, G, target, weight, var_keys,
                         np.asarray(base_list), lo_arr, hi_arr, balance_vectors)
    problem.unexposed_count = int(np.sum(unexposed))
    return problem


def project_box_hyperplanes(z: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                            vecs: Sequence[np.ndarray]) -> np.ndarray:
    """Euclidean projection onto {lo <= x <= hi, vec_f . x = 0 for every family f}.

    The family vectors have disjoint supports (a variable belongs to one family), so each
    family is projected independently: x(l) = clip(z - l*vec, lo, hi), vec.x(l) is
    monotone non-increasing in l; the root is found by bracketing + bisection.
    x = 0 is always feasible (lo <= 0 <= hi), hence a root exists.
    """
    x = np.clip(z, lo, hi)
    for vec in vecs:
        idx = np.nonzero(np.abs(vec) > EPS)[0]
        if idx.size == 0:
            continue
        v, zz, l0, h0 = vec[idx], z[idx], lo[idx], hi[idx]

        def g(lam):
            return float(v @ np.clip(zz - lam * v, l0, h0))
        g0 = g(0.0)
        if abs(g0) <= 1.0e-12 * max(1.0, float(np.abs(v) @ np.abs(np.clip(zz, l0, h0)))):
            x[idx] = np.clip(zz, l0, h0)
            continue
        step = max(1.0e-12, abs(g0) / max(EPS, float(v @ v)))
        a, b = 0.0, step if g0 > 0 else -step
        for _ in range(200):
            if (g(b) > 0) != (g0 > 0) or g(b) == 0.0:
                break
            a, b = b, 2.0 * b
        lo_l, hi_l = (a, b) if a < b else (b, a)
        for _ in range(100):
            mid = 0.5 * (lo_l + hi_l)
            if g(mid) > 0:
                lo_l = mid
            else:
                hi_l = mid
        x[idx] = np.clip(zz - 0.5 * (lo_l + hi_l) * v, l0, h0)
    return x


def repair_nonlinear_pa(problem: FitProblem, raw_x: np.ndarray,
                        tolerance: float = 1.0e-10) -> tuple[np.ndarray, dict]:
    """Enforce exact exp(log-step) P/A change inside the existing box.

    The linear hard plane is the solver's local approximation. A monotone
    one-dimensional correction per family moves productions down and
    attractions up by the same scalar (or the reverse), clipping each zonal
    step to its own bounds. Zero is in every box, so a root exists.
    """
    x = np.array(raw_x, dtype=float, copy=True)
    report = {}
    if not math.isfinite(float(tolerance)) or tolerance <= 0:
        raise ValueError("V24917_NONLINEAR_PA_INVALID_TOLERANCE")
    for family, (_vec, margin_total) in problem.balance_vectors.items():
        prod = np.array([i for i,key in enumerate(problem.var_keys)
                         if key[0] == family and key[1] == "PROD"], dtype=int)
        att = np.array([i for i,key in enumerate(problem.var_keys)
                        if key[0] == family and key[1] == "ATT"], dtype=int)
        if not len(prod) and not len(att):
            continue
        before = x.copy()

        def candidate(lam):
            trial = before.copy()
            trial[prod] = np.clip(before[prod] - lam, problem.lower[prod], problem.upper[prod])
            trial[att] = np.clip(before[att] + lam, problem.lower[att], problem.upper[att])
            return trial

        def gap(trial):
            value = (float(problem.base[prod] @ np.expm1(trial[prod]))
                     - float(problem.base[att] @ np.expm1(trial[att])))
            if not math.isfinite(value):
                raise ValueError("V24917_NONLINEAR_PA_NONFINITE:" + family)
            return value

        limit = max(1.0, float(np.max(np.abs(before - problem.lower))),
                    float(np.max(np.abs(problem.upper - before))))
        left, right = -limit, limit
        gl, gr = gap(candidate(left)), gap(candidate(right))
        if gl < 0.0 or gr > 0.0:
            raise ValueError("V24917_NONLINEAR_PA_NO_FEASIBLE_DIRECTION:" + family)
        allowed_gap = float(tolerance) * max(1.0, float(margin_total))
        if abs(gap(before)) <= allowed_gap:
            chosen = before
        else:
            for _ in range(100):
                middle = 0.5 * (left + right)
                gm = gap(candidate(middle))
                if gm > 0.0:
                    left = middle
                else:
                    right = middle
            chosen = candidate(0.5 * (left + right))
        remaining = gap(chosen)
        if abs(remaining) > allowed_gap:
            raise ValueError("V24917_NONLINEAR_PA_REPAIR_INCOMPLETE:" + family)
        x[prod] = chosen[prod]
        x[att] = chosen[att]
        report[family] = {"nonlinear_pa_gap": remaining,
                          "allowed_gap": allowed_gap,
                          "max_abs_log_step_repair": float(np.max(np.abs(chosen-before))),
                          "within_bounds": True}
    return x, report


def solve(problem: FitProblem, cfg: Mapping[str, Any]) -> Dict[str, Any]:
    """Bounded least squares by FISTA with an exact power-iteration step size.

    BALANCE1 (2026-10-26): ``balance_mode`` HARD (default) keeps the linearised trip-end
    balance sum_i P_i u_i = sum_j A_j v_j of every family EXACT in every iterate
    (projection onto box + hyperplane).  The former soft penalty (``SOFT``) was far too
    weak on the live problem: cycle 1 of 26.10. proposed SERVICE P +63 967 / A -2 361
    and WORK P +31 053 / A -178, which no P/A rebalance or the 2 % apply gate can accept.
    """
    G, W2 = problem.G, problem.weight ** 2
    nv = G.shape[1]
    diag_h = np.einsum("ij,i,ij->j", G, W2, G)
    positive = diag_h[diag_h > EPS]
    scale = float(np.median(positive)) if positive.size else 1.0
    ridge = float(cfg.get("ridge_relative", 0.02)) * scale
    hard = str(cfg.get("balance_mode", "HARD")).upper() == "HARD"
    mu = 0.0 if hard else float(cfg.get("balance_weight_relative", 50.0)) * scale * nv
    bal = [] if hard else [(vec / p_tot, ) for vec, p_tot in problem.balance_vectors.values()]
    hard_vecs = [np.asarray(vec, dtype=float) for vec, _ in problem.balance_vectors.values()] if hard else []

    def project(z):
        return project_box_hyperplanes(z, problem.lower, problem.upper, hard_vecs) if hard \
            else np.clip(z, problem.lower, problem.upper)

    def grad(x):
        resid = G @ x - problem.target
        g = G.T @ (W2 * resid) + ridge * x
        for (vec,) in bal:
            g = g + mu * vec * float(vec @ x)
        return g

    def objective(x):
        resid = G @ x - problem.target
        val = 0.5 * float(resid @ (W2 * resid)) + 0.5 * ridge * float(x @ x)
        for (vec,) in bal:
            val += 0.5 * mu * float(vec @ x) ** 2
        return val

    # Lipschitz constant of the gradient by power iteration.
    rng = np.random.default_rng(17)
    v = rng.random(nv) + 0.1
    v /= np.linalg.norm(v)
    lip = 1.0
    for _ in range(60):
        hv = G.T @ (W2 * (G @ v)) + ridge * v
        for (vec,) in bal:
            hv = hv + mu * vec * float(vec @ v)
        n = float(np.linalg.norm(hv))
        if n <= EPS:
            break
        v = hv / n
        lip = n
    lip = max(lip * 1.05, EPS)
    step = 1.0 / lip

    x = np.zeros(nv)
    y = x.copy()
    t = 1.0
    obj0 = objective(x)
    prev = obj0
    max_iter = int(cfg.get("max_iter", 4000))
    tol = float(cfg.get("tolerance", 1.0e-9))
    converged = False
    it = 0
    for it in range(1, max_iter + 1):
        x_new = project(y - step * grad(y))
        t_new = 0.5 * (1.0 + math.sqrt(1.0 + 4.0 * t * t))
        y = x_new + ((t - 1.0) / t_new) * (x_new - x)
        x, t = x_new, t_new
        if it % 20 == 0 or it == max_iter:
            obj = objective(x)
            if obj > prev * (1.0 + 1.0e-10):
                y, t = x.copy(), 1.0         # monotone restart
            if abs(prev - obj) <= tol * max(1.0, abs(prev)):
                converged = True
                prev = obj
                break
            prev = obj
    nonlinear_pa = {}
    if cfg.get("nonlinear_pa_repair", False):
        x, nonlinear_pa = repair_nonlinear_pa(problem, x,
            tolerance=float(cfg.get("nonlinear_pa_tolerance", 1.0e-10)))
    pred = G @ x
    balance = {}
    for fam, (vec, tot) in problem.balance_vectors.items():
        balance[fam] = {"linear_pa_gap": float(np.asarray(vec) @ x), "margin_total": float(tot),
                        "relative_to_total": float(np.asarray(vec) @ x) / max(EPS, float(tot))}
    return {"x": x, "predicted_change": pred, "objective_initial": obj0,
            "objective_final": objective(x), "iterations": it, "converged": converged,
            "ridge": ridge, "balance_weight": mu, "lipschitz": lip,
            "balance_mode": "HARD" if hard else "SOFT", "balance": balance,
            "nonlinear_pa_repair": nonlinear_pa}


def projection_rows(problem: FitProblem, solution: Mapping[str, Any],
                    min_step: float = 1.0e-5) -> List[Dict[str, Any]]:
    rows = []
    x = solution["x"]
    for k, (fam, role, z) in enumerate(problem.var_keys):
        step = float(x[k])
        if abs(step) < min_step:
            continue
        b = float(problem.base[k])
        delta = b * math.expm1(step)
        rows.append({
            "zone_no": int(z), "family": fam, "role": role,
            "projection_method": METHOD,
            "base_margin_volume": b,
            "guided_margin_delta": delta,
            "raw_relative_margin_change": math.expm1(step),
            "raw_log_step": step,
            "log_step": step,
            "multiplier": math.exp(step),
            "projected_margin_delta": delta,
            "fit_lower_log": float(problem.lower[k]),
            "fit_upper_log": float(problem.upper[k]),
            "fit_at_upper": bool(step >= problem.upper[k] - 1.0e-9),
            "fit_at_lower": bool(step <= problem.lower[k] + 1.0e-9),
        })
    rows.sort(key=lambda r: abs(float(r["log_step"])), reverse=True)
    return rows


def summary(problem: FitProblem, solution: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    pred = solution["predicted_change"]
    before = [r["geh"] for r in problem.profile_rows]
    after = [geh(max(0.0, r["model"] + float(d)), r["observed"])
             for r, d in zip(problem.profile_rows, pred.tolist())]
    fam_totals = {}
    for fam in FAMILIES:
        for role in ROLES:
            fam_totals["%s_%s_delta" % (fam, role)] = float(sum(
                float(r["projected_margin_delta"]) for r in rows
                if r["family"] == fam and r["role"] == role))
            fam_totals["%s_%s_base" % (fam, role)] = float(sum(
                float(problem.base[k]) for k, key in enumerate(problem.var_keys)
                if key[0] == fam and key[1] == role))
    obs = sum(r["observed"] for r in problem.profile_rows)
    model = sum(r["model"] for r in problem.profile_rows)
    return {
        "release": RELEASE, "method": METHOD,
        "profiles": len(problem.profile_rows), "variables": len(problem.var_keys),
        "unexposed_variables_fixed_at_zero": int(getattr(problem, "unexposed_count", 0)),
        "zones_changed": len({int(r["zone_no"]) for r in rows}),
        "rows": len(rows),
        "rows_at_upper": sum(1 for r in rows if r.get("fit_at_upper")),
        "rows_at_lower": sum(1 for r in rows if r.get("fit_at_lower")),
        "positive_rows": sum(1 for r in rows if float(r["log_step"]) > 0),
        "negative_rows": sum(1 for r in rows if float(r["log_step"]) < 0),
        "solver": {k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                   for k, v in solution.items() if k not in ("x", "predicted_change")},
        "linear_prediction": {
            "obs_sum": obs, "model_sum_before": model,
            "model_sum_after": model + float(np.sum(pred)),
            "ratio_before": model / obs if obs > 0 else None,
            "ratio_after": (model + float(np.sum(pred))) / obs if obs > 0 else None,
            "geh_mean_before": float(np.mean(before)), "geh_mean_after": float(np.mean(after)),
            "geh_ge20_before": int(sum(g >= 20 for g in before)),
            "geh_ge20_after": int(sum(g >= 20 for g in after)),
            "note": "Linearised first-order prediction on the current path epoch; "
                    "acceptance is decided by fresh assignment and live 12D/11D only.",
        },
        "margin_totals": fam_totals,
    }


def fit(incidence: Mapping[str, Any], zones: Sequence[int],
        bounds: Mapping[Tuple[str, str, int], Tuple[float, float]],
        cfg: Mapping[str, Any], solver_cfg: Optional[Mapping[str, Any]] = None):
    problem = build_problem(incidence, zones, bounds, cfg)
    solution = solve(problem, solver_cfg or {})
    rows = projection_rows(problem, solution, float(cfg.get("min_add_log_step", 1.0e-5)))
    return rows, summary(problem, solution, rows), problem, solution


__all__ = ["RELEASE", "METHOD", "build_problem", "solve", "repair_nonlinear_pa",
           "projection_rows", "summary", "fit", "geh"]
