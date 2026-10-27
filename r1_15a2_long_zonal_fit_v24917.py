# -*- coding: utf-8 -*-
"""Offline LONG zonal first-order fit using the WORK/SERVICE count-fit principle.

This is a local proposal model on *final vehicle* NATIVE_CL path incidence:
    delta_od / q_od ~= u_origin + v_destination - g_LONG.
The real TG/TD/20A/20B response can differ. No output from this module may
enable LONG generation until native OD support and live trial gates are proven.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

import r1_15a2_zonal_count_fit_v24917 as zf
from r1_15a2_skim_v24916p2c import ordered_zone_hash

RELEASE = "R1_15A2_V24917_LONG_ZONAL_LOCAL_FIT_V1"
EPS = 1.0e-12


def build_problem(observed: Mapping[str, Any], ws_problem: zf.FitProblem,
                  ws_solution: Mapping[str, Any], zone_nos: Sequence[int],
                  bounds: Mapping[tuple[str, str, int], tuple[float, float]]) -> zf.FitProblem:
    """Use the same normalized OD/path linearization as the W/S fit.

    The caller supplies explicit, independently validated coefficient-domain
    bounds. No default LONG mobility bounds or native-filter claim is inferred.
    """
    if observed.get("status") != "OBSERVED_LONG_OD_PROFILE_ONLY":
        raise ValueError("LONG_FIT_OBSERVED_INCIDENCE_REQUIRED")
    if any(isinstance(z, (bool, np.bool_)) or not isinstance(z, (int, np.integer))
           for z in zone_nos):
        raise ValueError("LONG_FIT_ZONE_AXIS_INVALID")
    zones = tuple(int(z) for z in zone_nos)
    if not zones or len(set(zones)) != len(zones) or any(z <= 0 for z in zones):
        raise ValueError("LONG_FIT_ZONE_AXIS_INVALID")
    if observed.get("zone_order_sha256") != ordered_zone_hash(zones):
        raise ValueError("LONG_FIT_ZONE_ORDER_MISMATCH")
    zidx = {z: i for i, z in enumerate(zones)}
    profiles = list(observed.get("profile_identity") or [])
    variables = list(observed.get("variables") or [])
    op = observed.get("incidence")
    rows = list(ws_problem.profile_rows)
    if (op is None or op.n_rows != len(profiles) or op.n_cols != len(variables)
            or len(ws_problem.target) != len(rows) or len(ws_problem.weight) != len(rows)):
        raise ValueError("LONG_FIT_PROFILE_OR_OPERATOR_SHAPE")
    predicted_ws = np.asarray(ws_solution.get("predicted_change"), dtype=float)
    if predicted_ws.shape != (len(rows),) or not np.isfinite(predicted_ws).all():
        raise ValueError("LONG_FIT_WS_PREDICTION_INVALID")
    row_of_profile = {}
    for row, meta in enumerate(rows):
        pidx = int(meta["profile_index"])
        if pidx in row_of_profile or pidx < 0 or pidx >= len(profiles):
            raise ValueError("LONG_FIT_PROFILE_INDEX_INVALID")
        if str(meta.get("countlocation_no", pidx)) != str(profiles[pidx]):
            raise ValueError("LONG_FIT_PROFILE_IDENTITY_MISMATCH")
        row_of_profile[pidx] = row

    production = np.asarray(observed.get("vehicle_production"), dtype=float)
    attraction = np.asarray(observed.get("vehicle_attraction"), dtype=float)
    total = float(observed.get("vehicle_total", float("nan")))
    if (production.shape != (len(zones),) or attraction.shape != (len(zones),)
            or not np.isfinite(production).all() or not np.isfinite(attraction).all()
            or np.any(production < 0) or np.any(attraction < 0)
            or not np.isfinite(total) or total <= EPS
            or not np.isclose(float(np.sum(production)), total, rtol=1.e-12, atol=1.e-8)
            or not np.isclose(float(np.sum(attraction)), total, rtol=1.e-12, atol=1.e-8)):
        raise ValueError("LONG_FIT_MARGINS_INVALID")
    listed_mass = 0.0
    for meta in variables:
        if meta.get("dseg_code") != "NATIVE_CL" or meta.get("family") != "LONG":
            raise ValueError("LONG_FIT_VARIABLE_SCOPE_INVALID")
        o, d = int(meta["origin"]), int(meta["destination"])
        q = float(meta["q_current"])
        if o not in zidx or d not in zidx or not np.isfinite(q) or q <= 0.0:
            raise ValueError("LONG_FIT_VARIABLE_INVALID")
        listed_mass += q
    if listed_mass > total + 1.e-8:
        raise ValueError("LONG_FIT_MARGINS_INVALID")

    keys = []
    base, lower, upper = [], [], []
    key_index = {}
    for role, margin in (("PROD", production), ("ATT", attraction)):
        for z in zones:
            key = ("LONG", role, z)
            if key not in bounds or margin[zidx[z]] <= EPS:
                continue
            lo, hi = (float(v) for v in bounds[key])
            if not np.isfinite([lo, hi]).all() or lo > 0.0 or hi < 0.0 or lo > hi:
                raise ValueError("LONG_FIT_BOUND_INVALID")
            if hi - lo <= EPS:
                continue
            key_index[key] = len(keys)
            keys.append(key)
            base.append(float(margin[zidx[z]]))
            lower.append(lo)
            upper.append(hi)
    if not keys:
        raise ValueError("LONG_FIT_NO_ACTUATORS")

    G = np.zeros((len(rows), len(keys)))
    through = np.zeros(len(rows))
    r_idx = np.asarray(op.row_idx, dtype=np.int64)
    c_idx = np.asarray(op.col_idx, dtype=np.int64)
    val = np.asarray(op.values, dtype=float)
    if (r_idx.shape != c_idx.shape or r_idx.shape != val.shape or
            not np.isfinite(val).all() or np.any(val < 0) or
            np.any(r_idx < 0) or np.any(r_idx >= op.n_rows) or
            np.any(c_idx < 0) or np.any(c_idx >= op.n_cols)):
        raise ValueError("LONG_FIT_OPERATOR_INVALID")
    for pidx, cidx, amount in zip(r_idx, c_idx, val):
        row = row_of_profile.get(int(pidx))
        if row is None or amount <= 0.0:
            continue
        meta = variables[int(cidx)]
        through[row] += amount
        prod_key = key_index.get(("LONG", "PROD", int(meta["origin"])))
        att_key = key_index.get(("LONG", "ATT", int(meta["destination"])))
        if prod_key is not None:
            G[row, prod_key] += amount
        if att_key is not None:
            G[row, att_key] += amount
    direct = np.abs(G).sum(axis=0)
    unexposed = direct <= EPS
    gvec = np.zeros(len(keys))
    bvec = np.zeros(len(keys))
    for i, (_family, role, z) in enumerate(keys):
        b = production[zidx[z]] if role == "PROD" else attraction[zidx[z]]
        gvec[i] = 0.5 * b / total
        bvec[i] = b if role == "PROD" else -b
    G -= np.outer(through, gvec)
    lo_arr, hi_arr = np.asarray(lower), np.asarray(upper)
    lo_arr[unexposed] = 0.0
    hi_arr[unexposed] = 0.0
    G[:, unexposed] = 0.0
    target = np.asarray(ws_problem.target, dtype=float) - predicted_ws
    weight = np.asarray(ws_problem.weight, dtype=float)
    if not np.isfinite(target).all() or not np.isfinite(weight).all() or np.any(weight <= 0):
        raise ValueError("LONG_FIT_TARGET_INVALID")
    problem = zf.FitProblem(zones, rows, G, target, weight, keys,
                            np.asarray(base), lo_arr, hi_arr, {"LONG": (bvec, total)})
    problem.unexposed_count = int(np.count_nonzero(unexposed))
    return problem


def fit(observed: Mapping[str, Any], ws_problem: zf.FitProblem,
        ws_solution: Mapping[str, Any], zone_nos: Sequence[int],
        bounds: Mapping[tuple[str, str, int], tuple[float, float]],
        solver_cfg: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Produce a diagnostic proposal, never executable generation rows."""
    problem = build_problem(observed, ws_problem, ws_solution, zone_nos, bounds)
    cfg = {"balance_mode": "HARD", "nonlinear_pa_repair": True,
           "ridge_relative": 0.05, **dict(solver_cfg or {})}
    # An exploratory caller cannot silently disable the P/A contract.
    cfg["balance_mode"] = "HARD"
    cfg["nonlinear_pa_repair"] = True
    solution = zf.solve(problem, cfg)
    if solution["objective_final"] > solution["objective_initial"] + 1.0e-9:
        raise ValueError("LONG_FIT_OBJECTIVE_WORSENED")
    return {"release": RELEASE, "status": "LOCAL_LINEAR_PROPOSAL_ONLY",
            "long_generation_permitted": False, "native_filter_verified": False,
            "source_status": observed.get("source_status"),
            "problem": problem, "solution": solution,
            "diagnostic_steps": {str(key): float(solution["x"][i])
                                 for i, key in enumerate(problem.var_keys)},
            "predicted_profile_change": np.asarray(solution["predicted_change"]).copy()}


__all__ = ["RELEASE", "build_problem", "fit"]
