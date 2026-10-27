# -*- coding: utf-8 -*-
"""V24917 LONG and SCHOOL trip-generation calibration (LSGEN1).

Requires the zone attributes ADD_PROD_L (AMDY k_long, start 0.2), ADD_ATT_L, ADD_PROD_SCH,
ADD_ATT_SCH and the generation formulas that multiply FP_3_LONG_*, FA_3_LONG, FP_5_SCHOOL,
FA_5_SCHOOL by them.  When the attributes are missing the module stays inactive.

Design (after the WORK/SERVICE zonal fit, on its residual):
    r_ls = (O - M) - G_ws x_ws                                  (what W/S do not explain)
    min  1/2 sum_p W_p^2 (G_ls y - r_ls)_p^2 + 1/2 lambda |y|^2 + 1/2 mu (P-A balance SCHOOL)^2

  SCHOOL  per zone PROD/ATT (log steps).  SCHOOL shares the vehicle segment CW with WORK,
          so its exposure is the WORK FlowBundle incidence times the SCHOOL share of the
          vehicle OD cell:  a_p,v * s_od,  s_od = M9225[o,d] / M9226[o,d].  Doubly-constrained
          normalisation g = (sum P u / P + sum A v / A) / 2 as in the W/S fit.
  LONG    one global production step (all zones, ADD_PROD_L).  LONG has its own segment
          NATIVE_CL, so the exposure of a profile is its live NATIVE_CL volume times the
          share of LONG production that the coefficient scales (FP_3_LONG / matrix totals;
          boundary productions P09F4 are not scaled).  ADD_ATT_L stays (attractions only
          redistribute because TG balances to productions).

Bounds (LSSENS1, more cautious than W/S, run options ls_*): step per cycle +-10 %,
SCHOOL absolute envelope [0.67, 1.5], LONG x[0.5, 2] of its reference (0.1-0.4 for
k_long = 0.2), ridge 0.05 (W/S 0.01).
Rows are written together with the W/S rows of the same trial (one assignment) and
are part of the snapshot / rollback state (mb.GENERATION_ATTRS is extended).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np

RELEASE = "R1_15A2_V24917_LONG_SCHOOL_GENERATION_V1_20261025"
ATTRS = ("ADD_PROD_L", "ADD_ATT_L", "ADD_PROD_SCH", "ADD_ATT_SCH")
EPS = 1.0e-12
# LSSENS1: LONG/SCHOOL are calibrated more cautiously than WORK/SERVICE.
LS_DEFAULTS = {
    "ls_max_step_up": 0.10,              # +10 % per zone and cycle   (W/S +25 %)
    "ls_max_step_down": 0.10,            # -10 % per zone and cycle   (W/S -20 %)
    "ls_school_envelope": [0.67, 1.5],   # absolute ADD_*_SCH         (W/S 0.25-5)
    "ls_long_envelope_ref": [0.5, 2.0],  # x reference ADD_PROD_L, i.e. 0.1-0.4 for 0.2
    "ls_ridge_relative": 0.05,           # 5x the W/S ridge: LS only explain what W/S cannot
}


def ls_options() -> dict:
    # An invalid or unreadable run policy must never silently replace the
    # operator's LONG/SCHOOL bounds with defaults. The generation adapter
    # catches the design error, defers LS for this cycle and continues W/S.
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options()
    return {k: o.get(k, v) for k, v in LS_DEFAULTS.items()}


def _attribute_missing(exc) -> bool:
    """Identify a confirmed missing network attribute, not an arbitrary COM error."""
    if isinstance(exc, (KeyError, AttributeError)):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in (
        "unknown attribute", "attribute not found", "no such attribute",
        "attribute does not exist", "invalid attribute id"))


def availability(visum) -> Dict[str, Any]:
    """Read-only, bounded RPC retry with explicit unknown/temporary/absent states."""
    import r1_15a2_com_compat as com
    retry = {"enabled": True, "max_attempts": 4, "initial_delay_seconds": 0.1,
             "backoff_factor": 2.0, "max_delay_seconds": 0.5, "max_elapsed_seconds": 2.0}
    for attr in ATTRS:
        try:
            com.com_call_with_retry(lambda a=attr: visum.Net.Zones.GetMultiAttValues(a, False),
                                    label="LONG_SCHOOL_ATTRIBUTE_%s" % attr, retry_policy=retry)
        except Exception as exc:
            return {"available": False,
                    "reason": ("ATTRIBUTES_MISSING" if _attribute_missing(exc) else
                               "TRANSIENT_COM_EXHAUSTED" if com.is_retryable_com_error(exc) else
                               "ATTRIBUTE_READ_UNVERIFIED"),
                    "failed_attr": attr, "error": repr(exc)[:1000],
                    "retryable_com": bool(com.is_retryable_com_error(exc)),
                    "evidence_complete": bool(_attribute_missing(exc))}
    return {"available": True, "reason": "ATTRIBUTES_VERIFIED", "evidence_complete": True}


def available(visum) -> bool:
    return bool(availability(visum)["available"])


def activate(visum) -> Dict[str, Any]:
    """Extend snapshot/rollback only after confirming all four attributes."""
    import r1_15a2_multiblock as mb
    probe = availability(visum)
    if not probe["available"]:
        return {"active": False, "attrs": list(ATTRS), **probe}
    for a in ATTRS:
        if a not in mb.GENERATION_ATTRS:
            mb.GENERATION_ATTRS.append(a)
    mb.GENERATION_ATTR_MAP.setdefault(("LONG", "PROD", "DOMESTIC"), "ADD_PROD_L")
    mb.GENERATION_ATTR_MAP.setdefault(("LONG", "ATT", "DOMESTIC"), "ADD_ATT_L")
    mb.GENERATION_ATTR_MAP.setdefault(("SCHOOL", "PROD", "DOMESTIC"), "ADD_PROD_SCH")
    mb.GENERATION_ATTR_MAP.setdefault(("SCHOOL", "ATT", "DOMESTIC"), "ADD_ATT_SCH")
    return {"active": True, "attrs": list(ATTRS), "release": RELEASE}


def _matrix(visum, no):
    return np.asarray(visum.Net.Matrices.ItemByKey(int(no)).GetValues(), dtype=float)


def _zone_values(visum, attr, zones) -> np.ndarray:
    vals = dict((int(float(k)), float(v)) for k, v in
                zip([v for _, v in visum.Net.Zones.GetMultiAttValues("NO", False)],
                    [v for _, v in visum.Net.Zones.GetMultiAttValues(attr, False)]))
    return np.array([vals.get(int(z), 0.0) for z in zones], dtype=float)


def _cl_volume(visum, edge, both) -> float:
    def vol(fr, to):
        try:
            return float(visum.Net.Links.ItemByKey(int(fr), int(to)).AttValue("VOLVEH_DSEG(NATIVE_CL,AP)"))
        except Exception:
            return 0.0
    v = vol(edge[1], edge[2])
    if both:
        v += vol(edge[2], edge[1])
    return v


def design(visum, cfg: Mapping[str, Any], zones: Sequence[int], incidence: Mapping[str, Any],
           ws_problem, ws_solution, reference_values: Mapping[str, Mapping[str, Any]] = None,
           fit_cfg: Mapping[str, Any] = None) -> Dict[str, Any]:
    import r1_15a2_zonal_count_fit_v24917 as zf
    fit_cfg = dict(fit_cfg or {})
    zones = [int(z) for z in zones]
    zidx = {z: i for i, z in enumerate(zones)}
    nz = len(zones)
    rows = list(ws_problem.profile_rows)
    P = len(rows)
    target = np.asarray(ws_problem.target, dtype=float) - np.asarray(ws_solution["predicted_change"], dtype=float)
    weight = np.asarray(ws_problem.weight, dtype=float)
    lso = ls_options()
    max_up = min(float(cfg.get("max_add_log_up", 0.03)), math.log1p(float(lso["ls_max_step_up"])))
    max_dn = min(float(cfg.get("max_add_log_down", 0.03)), -math.log1p(-float(lso["ls_max_step_down"])))
    # LONGGUARD1: separate hard LONG +/-10% per candidate even when the
    # run options request an exploratory +/-50% LSGEN step. School keeps its
    # existing cap; only the LONG variable is additionally constrained.
    max_up_long = min(max_up, math.log1p(0.10))
    max_dn_long = min(max_dn, -math.log1p(-0.10))
    SCHOOL_HARD = tuple(float(x) for x in lso["ls_school_envelope"])
    LONG_REF_MULT = tuple(float(x) for x in lso["ls_long_envelope_ref"])

    # ---- SCHOOL exposure through WORK incidence -------------------------------------
    m25, m26 = _matrix(visum, 9225), _matrix(visum, 9226)
    share = np.where(m26 > EPS, m25 / np.maximum(m26, EPS), 0.0)
    share = 0.5 * (share + share.T)
    row_of_profile = {}
    for i, r in enumerate(rows):
        row_of_profile[int(r.get("profile_index", i))] = i
    variables = list(incidence["variables"])
    op = incidence["incidence"]
    var_keys, cols = [], {}
    def col(key):
        if key not in cols:
            cols[key] = len(var_keys)
            var_keys.append(key)
        return cols[key]
    entries: List[tuple] = []
    margins = {"PROD": np.zeros(nz), "ATT": np.zeros(nz)}
    for meta in incidence.get("projection_base_variables") or variables:
        if str(meta.get("family", "")).upper() != "WORK":
            continue
        o, d = zidx.get(int(meta["origin"])), zidx.get(int(meta["destination"]))
        if o is None or d is None:
            continue
        q = max(0.0, float(meta.get("q_current", 0.0) or 0.0)) * share[o, d]
        margins["PROD"][o] += q
        margins["ATT"][d] += q
    for p, c, a in zip(np.asarray(op.row_idx).tolist(), np.asarray(op.col_idx).tolist(),
                       np.asarray(op.values, dtype=float).tolist()):
        i = row_of_profile.get(int(p))
        if i is None or a == 0.0:
            continue
        meta = variables[int(c)]
        if str(meta.get("family", "")).upper() != "WORK":
            continue
        o, d = zidx.get(int(meta["origin"])), zidx.get(int(meta["destination"]))
        if o is None or d is None:
            continue
        s = a * share[o, d]
        if s <= 0.0:
            continue
        entries.append((i, col(("SCHOOL", "PROD", zones[o])), s))
        entries.append((i, col(("SCHOOL", "ATT", zones[d])), s))

    # ---- LONG exposure from live NATIVE_CL volumes ----------------------------------
    # The original unrestricted LSGEN1 design was able to increase every
    # ADD_PROD_L even when native LONG OD contained <100 km trips.  For an
    # invalid/unverified parent, omit this variable without weakening SCHOOL.
    longguard1_allow_long = bool(fit_cfg.get("longguard1_allow_long", False))
    from r1_15a2_td_count_blend_v24917 import cl_key
    obs_by_no = {cl_key(r["no"]): r for r in cfg.get("api_approved_observations", []) or []}
    long_scaled_share = 0.0
    cl = np.zeros(P)
    if longguard1_allow_long:
        fp_long = sum(float(_zone_values(visum, a, zones).sum()) for a in
                      ("FP_3_LONG_E_C", "FP_3_LONG_E_noC", "FP_3_LONG_noE_C", "FP_3_LONG_noE_noC", "FP_3_LONG_stud"))
        mat_long = sum(float(_matrix(visum, no).sum()) for no in range(9111, 9116))
        long_scaled_share = min(1.0, fp_long / mat_long) if mat_long > EPS else 0.0
        for i, r in enumerate(rows):
            ob = obs_by_no.get(cl_key(r.get("countlocation_no")))
            if ob:
                cl[i] = _cl_volume(visum, ob["edge_key"], str(ob.get("direction", "")).upper() == "BOTH")
    if cl.sum() > EPS and long_scaled_share > 0.0:
        k_long = col(("LONG", "PROD", 0))
        for i in np.flatnonzero(cl > 0):
            entries.append((int(i), k_long, float(cl[i] * long_scaled_share)))

    nv = len(var_keys)
    if nv == 0:
        return {"rows_by_attr": {}, "summary": {"status": "NO_LONG_SCHOOL_EXPOSURE"}}
    G = np.zeros((P, nv))
    for i, k, v in entries:
        G[i, k] += v
    # SCHOOL doubly-constrained normalisation
    p_tot, a_tot = float(margins["PROD"].sum()), float(margins["ATT"].sum())
    school_through = np.zeros(P)
    for i, k, v in entries:
        if var_keys[k][0] == "SCHOOL" and var_keys[k][1] == "PROD":
            school_through[i] += v
    gvec, bvec = np.zeros(nv), np.zeros(nv)
    for k, (fam, role, z) in enumerate(var_keys):
        if fam != "SCHOOL" or p_tot <= EPS or a_tot <= EPS:
            continue
        b = margins[role][zidx[z]]
        gvec[k] = 0.5 * b / (p_tot if role == "PROD" else a_tot)
        bvec[k] = b if role == "PROD" else -b
    G -= np.outer(school_through, gvec)

    # ---- bounds ------------------------------------------------------------------------
    cur = {a: _zone_values(visum, a, zones) for a in ATTRS}
    ref = reference_values or {}
    lo, hi, base = np.zeros(nv), np.zeros(nv), np.ones(nv)
    for k, (fam, role, z) in enumerate(var_keys):
        if fam == "SCHOOL":
            attr = "ADD_PROD_SCH" if role == "PROD" else "ADD_ATT_SCH"
            c = cur[attr][zidx[z]]
            if c <= EPS:
                continue
            lo[k] = max(-max_dn, math.log(SCHOOL_HARD[0] / c))
            hi[k] = min(max_up, math.log(SCHOOL_HARD[1] / c))
            base[k] = max(EPS, margins[role][zidx[z]])
        else:
            c = cur["ADD_PROD_L"]
            r = np.array([float((ref.get("ADD_PROD_L") or {}).get(str(z), c[i]) or c[i])
                          for i, z in enumerate(zones)])
            ok = c > EPS
            if not ok.any():
                continue
            lo[k] = max(-max_dn_long, float(np.max(np.log(LONG_REF_MULT[0] * r[ok] / c[ok]))))
            hi[k] = min(max_up_long, float(np.min(np.log(LONG_REF_MULT[1] * r[ok] / c[ok]))))
        lo[k], hi[k] = min(0.0, lo[k]), max(0.0, hi[k])
    exposed = np.abs(G).sum(axis=0) > EPS
    lo[~exposed] = 0.0
    hi[~exposed] = 0.0
    problem = zf.FitProblem(zones, rows, G, target, weight, var_keys, base, lo, hi,
                            {"SCHOOL": (bvec, 0.5 * (p_tot + a_tot))} if p_tot > EPS else {})
    sol = zf.solve(problem, {"ridge_relative": float(lso["ls_ridge_relative"]),
                             "balance_weight_relative": float(fit_cfg.get("balance_weight_relative", 50.0)),
                             "max_iter": int(fit_cfg.get("max_iter", 6000)),
                             "tolerance": float(fit_cfg.get("tolerance", 1.0e-9))})
    x = sol["x"]
    steps: Dict[str, Dict[int, float]] = {a: {} for a in ATTRS}
    for k, (fam, role, z) in enumerate(var_keys):
        if abs(x[k]) < 1.0e-6:
            continue
        if fam == "SCHOOL":
            steps["ADD_PROD_SCH" if role == "PROD" else "ADD_ATT_SCH"][int(z)] = float(x[k])
        else:
            for zz in zones:
                steps["ADD_PROD_L"][zz] = float(x[k])
    obs = np.array([float(r["observed"]) for r in rows])
    model = np.array([float(r["model"]) for r in rows])
    after = model + np.asarray(ws_solution["predicted_change"]) + sol["predicted_change"]
    summary = {"status": "OK", "release": RELEASE, "variables": nv, "sensitivity": lso,
               "max_log_up": max_up, "max_log_down": max_dn,
               "longguard1_max_log_up": max_up_long, "longguard1_max_log_down": max_dn_long,
               "longguard1_long_step_hard_ceiling": 0.10,
               "school_zone_vars": sum(1 for k in var_keys if k[0] == "SCHOOL"),
               "longguard1_long_generation_permitted": longguard1_allow_long,
               "longguard1_status": "ACTIVE" if longguard1_allow_long else "DEFERRED_PARENT_SUPPORT_UNVERIFIED_OR_INVALID",
               "long_global_log_step": float(next((x[k] for k, v in enumerate(var_keys) if v[0] == "LONG"), 0.0)),
               "long_scaled_share": long_scaled_share, "long_profile_volume": float(cl.sum()),
               "school_zones_changed": len(steps["ADD_PROD_SCH"]) + len(steps["ADD_ATT_SCH"]),
               "objective_initial": sol["objective_initial"], "objective_final": sol["objective_final"],
               "converged": bool(sol["converged"]),
               "linear_ratio_after_ws_and_ls": float(after.sum() / obs.sum()) if obs.sum() > 0 else None}
    return {"steps": steps, "current": {a: {int(z): float(cur[a][i]) for i, z in enumerate(zones)} for a in ATTRS},
            "summary": summary,
            "predicted_change": [float(v) for v in np.asarray(sol["predicted_change"], dtype=float)],
            # MOBILITYZONE1 re-evaluates effects after bounding production steps.
            "effect_operator": {"keys": [list(k) for k in var_keys], "G": G.tolist()}}


def rows_at_scale(ls: Mapping[str, Any], scale: float) -> List[Dict[str, Any]]:
    out = []
    if not ls or "steps" not in ls:
        return out
    fam_role = {"ADD_PROD_L": ("LONG", "PROD"), "ADD_ATT_L": ("LONG", "ATT"),
                "ADD_PROD_SCH": ("SCHOOL", "PROD"), "ADD_ATT_SCH": ("SCHOOL", "ATT")}
    for attr, by_zone in ls["steps"].items():
        for z, step in by_zone.items():
            c = float(ls["current"][attr][int(z)])
            if c <= EPS:
                continue
            fam, role = fam_role[attr]
            out.append({"zone_no": int(z), "attr": attr, "family": fam, "role": role, "branch": "DOMESTIC",
                        "current": c, "proposed": c * math.exp(float(scale) * step),
                        "log_step": float(scale) * step, "source": "V24917_LSGEN1"})
    return out


__all__ = ["RELEASE", "ATTRS", "available", "availability", "activate", "design", "rows_at_scale"]
