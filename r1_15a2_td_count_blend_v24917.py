# -*- coding: utf-8 -*-
"""V24917 TD calibration against counts AND the mobility survey (TDBLEND1).

Before: the FineCDF TD search minimised only the 512-point IDP CDF error; counts
were a guard (CAL GEH may worsen by <= 0.5 %).  Large intrazonal trip shares in the
aggregated district zones satisfied the survey and never reached the network.

Now the TD objective is a weighted blend, each part normalised to the state at the
start of the TD stage (both parts = 1 there):

    F = w_cnt * Q / Q_ref  +  w_idp * sum_c J_c / sum_c J_c,ref        w_cnt = 0.60

    Q   = sum_p w_p (M_p - O_p)^2 / d_p^2 / sum_p w_p,   d_p^2 = max(50, (M_ref,p + O_p)/2)
          (mean GEH^2 with the denominator frozen at the stage start: Gauss-Newton ready)
    J_c = sealed v1.9 FineCDF objective of component c (unchanged formula).

Legacy inner search (TDJOINT1 disabled): every component c gets the residual
    r'_c = [ sqrt(w_idp / J_ref) * r_idp,c ;  sqrt(w_cnt / Q_ref) * q(M_ref + dM_c) ]
so its objective/gradient is the component's share of F to first order.  dM_c is the
count change caused by component c alone, from the FlowBundle path incidence of the
current epoch (vehicles of each OD-family through each profile) and the live kappa /
band factors of the TD -> vehicle chain:

    dV_fam[o,d] = f_c * kappa_c * (dT_c[o,d] + dT_c[d,o]) / 2
    dM_p,c      = sum_v a_p,v * dV_fam[o_v,d_v] / V_fam[o_v,d_v]

TDJOINT1 enabled: one stacked residual covers all components and the count term
exactly once; bounded native coordinate probes rank isolated and combined steps.
This remains a surrogate, not a replacement for live outer acceptance.

Inner modes (run option td_inner_mode):
    FROZEN_PATHS (default)  each inner evaluation runs ONLY the TD operation (seconds);
                            paths, DIS skims and counts are linearised on the current
                            epoch.  The full assignment happens in the realization step.
    DYNAMIC                 V24916 behaviour: every evaluation = TD + full assignment +
                            skims (slow); counts are then MEASURED, dM_c only splits them.

Outer acceptance of the realized TD (fresh assignment, live 12D/11D):
    F_out = w_cnt * GEHw_after/GEHw_before + w_idp * IDP_after/IDP_before <= 1 - 0.001
    hard guards kept: observation set, protected profiles, new severe GEH profiles,
    component authority; the survey may worsen at most 25 % (IDP_after/IDP_before).
"""
from __future__ import annotations

import functools
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

RELEASE = "R1_15A2_V24917_TD_COUNT_BLEND_V1_20261025"
SCHEMA = "R1_15A2_V24917_TD_COUNT_BLEND_V1"
PASSENGER_DSEGS = ("NATIVE_CW", "NATIVE_CW_noT", "NATIVE_CS", "NATIVE_CS_noT", "NATIVE_CL", "NATIVE_CF",
                   "EXOG_EE_CW", "EXOG_EE_CW_noT", "EXOG_EE_CS", "EXOG_EE_CS_noT", "EXOG_EE_CL", "EXOG_EE_CF")
RELAXED_INNER_GUARDS = {"max_fine_cdf_rmse_degradation": 0.03, "max_mean_error_degradation": 0.05}
OUTER_MIN_RELATIVE_IMPROVEMENT = 0.001
OUTER_MAX_IDP_RATIO = 1.25
SOFT_REASON_PREFIXES = ("SELECTED_TD_OBJECTIVE_NOT_IMPROVED", "SELECTED_COMPONENT_NOT_IMPROVED",
                        "NONSELECTED_COMPONENT_DEGRADED", "CAL_CSD_DEGRADED_TOO_MUCH",
                        "TD_BENEFIT_COST_RATIO_TOO_LOW", "GLOBAL_IDP_MEAN_DEGRADED",
                        "GLOBAL_IDP_COMPONENT_DEGRADED")
EPS = 1.0e-12
_STATE: Dict[str, Any] = {}
ORIGINAL_EVALUATE = None      # pure survey DynamicFamilyMetrics.evaluate (set by install)


# ------------------------------------------------------------------ options
def options() -> Dict[str, Any]:
    try:
        import r1_15a2_demand_policy_v1 as dp
        o = dp.load_options()
    except Exception:
        # Configuration errors must not silently replace a requested joint run.
        raise
    w = float(o.get("td_count_weight", 0.60))
    return {"w_cnt": w, "w_idp": 1.0 - w,
            "joint_enabled": bool(o.get("td_joint_enabled", False)),
            "inner_mode": str(o.get("td_inner_mode", "FROZEN_PATHS")).upper(),
            "tg_max_trials": int(o.get("tg_max_trials", 6)),
            "td_realization_max_trials": int(o.get("td_realization_max_trials", 5)),
            "td_inner_max_evaluations": int(o.get("td_inner_max_evaluations", 180)),
            "td_inner_budget_multiplier": float(o.get("td_inner_budget_multiplier", 2.0)),
            "max_idp_ratio": float(o.get("td_max_survey_degradation", OUTER_MAX_IDP_RATIO))}


def search_budget(stage, cfg, opts):
    """Expand the selected original phase, bounded by explicit integration caps.

    Changing only max evaluations would merely remove the former ceiling;
    early phases would still have 28/60 evaluations. Keep the phase schedule,
    the global iteration fence and all stop/stationarity semantics intact.
    """
    out = dict(stage)
    if not out:
        return out
    base_eval, base_iter = int(out['max_td_evaluations']), int(out['max_iterations'])
    factor = float(opts.get('td_inner_budget_multiplier', 1.0))
    if min(base_eval, base_iter) <= 0 or not math.isfinite(factor) or not 1. <= factor <= 4.:
        raise ValueError('V24917_INVALID_SEARCH_BUDGET')
    requested_eval, requested_iter = math.ceil(base_eval*factor), math.ceil(base_iter*factor)
    fine = (cfg.get('coupled_demand') or {}).get('finecdf_td') or {}
    iteration_cap = int(fine.get('max_iterations', requested_iter))
    cap = int(opts['td_inner_max_evaluations'])
    if min(iteration_cap, cap) <= 0:
        raise ValueError('V24917_INVALID_SEARCH_BUDGET_CAP')
    out['max_td_evaluations'] = min(requested_eval, cap)
    out['max_iterations'] = min(requested_iter, iteration_cap)
    if requested_eval > cap:
        out['max_iterations'] = min(out['max_iterations'], max(2, cap//5))
    capped = out['max_td_evaluations'] < requested_eval or out['max_iterations'] < requested_iter
    if capped:
        out['allow_progress_continue'] = True
        out['v24917_capped'] = True
    out['v24917_search_budget'] = {'original_evaluations': base_eval, 'original_iterations': base_iter,
        'multiplier': factor, 'requested_evaluations': requested_eval,
        'requested_iterations': requested_iter, 'evaluation_cap': cap, 'iteration_cap': iteration_cap,
        'effective_evaluations': out['max_td_evaluations'], 'effective_iterations': out['max_iterations']}
    return out


# ------------------------------------------------------------------ count model
def cl_key(value) -> str:
    """Canonical CountLocation number: '920001', 920001, '920001.0' -> '920001'."""
    s = str(value if value is not None else "").strip()
    try:
        f = float(s)
        if math.isfinite(f) and f == int(f):
            return str(int(f))
    except ValueError:
        pass
    return s


def _family_of_component(name: str) -> Optional[str]:
    n = str(name).upper()
    if n == "SCHOOL" or n.startswith("WORK_"):
        return "WORK"
    if n.startswith("SERV_"):
        return "SERVICE"
    return None


class CountModel:
    """Profiles of the calibration roster, live volumes and the linear TD->count map."""

    def __init__(self, visum, cfg: Mapping[str, Any], zone_order, incidence=None):
        self.v = visum
        self.retry_policy = cfg.get("com_resilience") or {"enabled": True, "max_attempts": 5}
        self.zone_index = {int(z): i for i, z in enumerate(zone_order)}
        self.n = len(zone_order)
        prof = []
        for r in cfg.get("api_approved_observations", []) or []:
            if str(r.get("role", "CALIBRATION")).upper() != "CALIBRATION":
                continue
            obs = float(r.get("observed", 0.0) or 0.0)
            if obs <= 0.0:
                continue
            edge = [int(x) for x in r["edge_key"]]
            prof.append({"no": int(r["no"]), "profile_id": str(r.get("profile_id", "")),
                         "obs": obs, "w": float(r.get("weight", 1.0) or 1.0),
                         "from": edge[1], "to": edge[2],
                         "both": str(r.get("direction", "")).upper() == "BOTH"})
        if not prof:
            raise RuntimeError("V24917_TD_BLEND_NO_CALIBRATION_PROFILES")
        self.profiles = prof
        self.O = np.array([p["obs"] for p in prof])
        self.W = np.array([p["w"] for p in prof])
        self.incidence = incidence
        self._links = {}

    # live volumes ---------------------------------------------------------
    def _link(self, fr, to):
        # GENFIX2: an unreadable required link is not an observed zero.  Cache
        # only successful objects; transient COM rejection uses bounded retry.
        from r1_15a2_com_compat import com_call_with_retry
        key = (int(fr), int(to))
        if self._links.get(key) is None:
            obj = com_call_with_retry(
                lambda: self.v.Net.Links.ItemByKey(*key),
                label="TD_COUNT_LINK:%s" % (key,),
                retry_policy=getattr(self, "retry_policy", {"enabled": True, "max_attempts": 5}))
            if obj is None:
                raise RuntimeError("V24917_TD_COUNT_REQUIRED_LINK_MISSING:%s" % (key,))
            self._links[key] = obj
        return self._links[key]

    def _vol(self, link):
        from r1_15a2_com_compat import com_call_with_retry
        if link is None:
            raise RuntimeError("V24917_TD_COUNT_REQUIRED_LINK_MISSING")
        total = 0.0
        for dseg in PASSENGER_DSEGS:
            attr = "VOLVEH_DSEG(%s,AP)" % dseg
            x = float(com_call_with_retry(
                lambda: link.AttValue(attr), label="TD_COUNT:" + attr,
                retry_policy=getattr(self, "retry_policy", {"enabled": True, "max_attempts": 5})))
            if not math.isfinite(x) or x < 0.0:
                raise RuntimeError("V24917_TD_COUNT_INVALID_VOLUME:" + attr)
            total += x
        return total

    def read_live(self) -> np.ndarray:
        out = np.zeros(len(self.profiles))
        volumes = {}
        def volume(fr, to):
            key = (int(fr), int(to))
            if key not in volumes:
                volumes[key] = self._vol(self._link(*key))
            return volumes[key]
        for i, p in enumerate(self.profiles):
            v = volume(p["from"], p["to"])
            if p["both"]:
                v += volume(p["to"], p["from"])
            out[i] = v
        return out

    # reference / linear map ----------------------------------------------
    def set_reference(self, M_ref: np.ndarray, matrices: Mapping[int, np.ndarray], read_matrix, *, measured=False):
        self.M_ref = np.asarray(M_ref, dtype=float)
        self.d2 = np.maximum(50.0, 0.5 * (self.M_ref + self.O))
        self.Q_ref = self.Q(self.M_ref)
        if measured:
            # Native assignment supplies the count response. No person-to-vehicle
            # approximation, OD copies or W/S incidence belong to this path.
            self.T_ref, self.kappa, self.band, self.V = {}, {}, {}, {}
            self.linear = None
            self.linear_profile_coverage = {"mapped": 0, "profiles": len(self.profiles),
                                            "used": False, "reason": "MEASURED_NATIVE_ASSIGNMENT"}
            return
        self.T_ref = {int(k): np.array(v, dtype=float, copy=True) for k, v in matrices.items()}
        sums = {}
        def s(no):
            if no not in sums:
                sums[no] = float(read_matrix(no).sum())
            return sums[no]
        self.kappa, self.band = {}, {}
        for no in self.T_ref:
            if 9101 <= no <= 9117 and no != 9116:
                tot = float(self.T_ref[no].sum())
                self.kappa[no] = s(no + 100) / tot if tot > 0 else 0.0
        work = sum(s(n) for n in range(9201, 9206))
        serv = sum(s(n) for n in range(9206, 9211))
        for no in range(9101, 9106):
            self.band[no] = s(9221) / work if work > 0 else 1.0
        for no in range(9106, 9111):
            self.band[no] = s(9222) / serv if serv > 0 else 1.0
        self.band[9117] = s(9225) / s(9217) if s(9217) > 0 else 1.0
        self.V = {"WORK": read_matrix(9226), "SERVICE": read_matrix(9222)}
        self.linear = self._build_linear()
        self.Q_ref = self.Q(self.M_ref)

    def _build_linear(self):
        inc = self.incidence
        if not inc:
            return None
        by_no = {cl_key(p["no"]): i for i, p in enumerate(self.profiles)}
        by_pid = {p["profile_id"]: i for i, p in enumerate(self.profiles) if p["profile_id"]}
        pmap = {}
        for k, p in enumerate(inc.get("profiles", []) or []):
            key = cl_key(p.get("countlocation_no", ""))
            i = by_no.get(key)
            if i is None:
                i = by_pid.get(str(p.get("profile_id", "")))
            if i is not None:
                pmap[k] = i
        op = inc.get("incidence")
        variables = inc.get("variables", []) or []
        self.linear_profile_coverage = {"mapped": len(set(pmap.values())), "profiles": len(self.profiles)}
        if op is None or not pmap:
            return None
        out = {}
        rows = np.asarray(op.row_idx, dtype=np.int64)
        cols = np.asarray(op.col_idx, dtype=np.int64)
        vals = np.asarray(op.values, dtype=float)
        for fam in ("WORK", "SERVICE"):
            R, O_, D_, C = [], [], [], []
            V = self.V[fam]
            for r, c, a in zip(rows.tolist(), cols.tolist(), vals.tolist()):
                i = pmap.get(int(r))
                if i is None or a == 0.0:
                    continue
                meta = variables[int(c)]
                if str(meta.get("family", "")).upper() != fam:
                    continue
                o = self.zone_index.get(int(meta["origin"]))
                d = self.zone_index.get(int(meta["destination"]))
                if o is None or d is None or V[o, d] <= EPS:
                    continue
                R.append(i); O_.append(o); D_.append(d); C.append(a / V[o, d])
            out[fam] = (np.asarray(R, dtype=np.int64), np.asarray(O_, dtype=np.int64),
                        np.asarray(D_, dtype=np.int64), np.asarray(C, dtype=float))
        return out

    def delta_for(self, matrix_nos, matrices) -> np.ndarray:
        dm = np.zeros(len(self.profiles))
        if self.linear is None:
            return dm
        for no in matrix_nos:
            no = int(no)
            fam = "SERVICE" if 9106 <= no <= 9110 else ("WORK" if (9101 <= no <= 9105 or no == 9117) else None)
            if fam is None or no not in self.T_ref:
                continue
            R, O_, D_, C = self.linear[fam]
            if not len(R):
                continue
            dT = np.asarray(matrices[no], dtype=float) - self.T_ref[no]
            sym = 0.5 * (dT[O_, D_] + dT[D_, O_]) * self.band.get(no, 1.0) * self.kappa.get(no, 0.0)
            dm += np.bincount(R, weights=C * sym, minlength=len(self.profiles))
        return dm

    def q(self, M) -> np.ndarray:
        return np.sqrt(self.W / self.W.sum()) * (np.asarray(M) - self.O) / np.sqrt(self.d2)

    def Q(self, M) -> float:
        r = self.q(M)
        return float(r @ r)

    def mean_geh(self, M) -> float:
        M = np.maximum(0.0, np.asarray(M))
        den = M + self.O
        g = np.where(den > 0, np.sqrt(2.0 * (M - self.O) ** 2 / np.maximum(den, EPS)), 0.0)
        return float((self.W * g).sum() / self.W.sum())


def is_td_inner_bridge(bridge) -> bool:
    """True only for the live NoDirectMatrixWriteTDAdapter of a FineCDF TD stage."""
    return (bridge is not None and getattr(bridge, "outer_adapter", None) is not None
            and callable(getattr(bridge, "read_matrix", None))
            and getattr(bridge, "zone_order", None) is not None
            and getattr(bridge, "root", None) is not None)


class Blend:
    """Per-TD-stage state attached to the bridge's DynamicFamilyMetrics instance."""

    def __init__(self, bridge, ref, opts):
        self.bridge, self.ref, self.opts = bridge, ref, opts
        outer = bridge.outer_adapter
        self.model = CountModel(bridge.v, getattr(outer, "cfg", {}) or {}, bridge.zone_order,
                                getattr(outer, "v24917_last_incidence", None))
        self.measured = not getattr(bridge, "_v24917_frozen", False)
        self.ref_set = False
        self.log = Path(bridge.root) / "V24917_TD_COUNT_BLEND.jsonl"
        for k, v in RELAXED_INNER_GUARDS.items():
            ref.CONFIG[k] = max(float(ref.CONFIG.get(k, 0.0)), v)

    def stacked(self, out: Mapping[str, Mapping[str, Any]], matrices, M_ref=None):
        """Full residual of F without touching ``out``: [sqrt(w_idp/J_ref) r_idp ; sqrt(w_cnt/Q_ref) q(M)].

        r @ r == F = w_cnt Q(M)/Q_ref + w_idp J/J_ref.  ``M_ref`` (first call only) sets the count
        reference explicitly instead of reading live link volumes (used when the reference matrices
        are not the ones the live assignment was computed from).
        """
        m, wc, wi = self.model, self.opts["w_cnt"], self.opts["w_idp"]
        live = m.read_live() if self.measured else None
        if not self.ref_set:
            reference = (live if self.measured else m.read_live()) if M_ref is None else np.asarray(M_ref, dtype=float)
            m.set_reference(reference, matrices, self.bridge.read_matrix, measured=self.measured)
            self.J_ref = max(EPS, float(sum(v["objective"] for v in out.values())))
            self.ref_set = True
        if self.measured:
            M = live
        else:
            total = np.zeros(len(m.profiles))
            for key in out:
                total += m.delta_for(self.ref.TARGETS[key]["matrix_nos"], matrices)
            M = m.M_ref + total
        keys = sorted(out)
        r_idp = np.concatenate([np.asarray(out[k]["residual"], dtype=float).ravel() for k in keys]) \
            if keys else np.zeros(0)
        J = float(sum(float(out[k]["objective"]) for k in keys))
        Q_ref = max(EPS, m.Q_ref)
        r = np.r_[math.sqrt(wi / self.J_ref) * r_idp, math.sqrt(wc / Q_ref) * m.q(M)]
        parts = {"J": J, "J_ref": self.J_ref, "Q": m.Q(M), "Q_ref": Q_ref, "idp_term": J / self.J_ref,
                 "count_term": m.Q(M) / Q_ref, "mean_geh_weighted": m.mean_geh(M),
                 "model_obs_ratio": float(M.sum() / m.O.sum())}
        return r, float(r @ r), parts

    def apply(self, out: Dict[str, Dict[str, Any]], matrices) -> Dict[str, Dict[str, Any]]:
        if self.opts.get("joint_enabled", False):
            from r1_15a2_td_joint_v24917 import score_blend
            return score_blend(self, out, matrices)
        m, wc, wi = self.model, self.opts["w_cnt"], self.opts["w_idp"]
        if not self.ref_set:
            m.set_reference(m.read_live(), {no: matrices[no] for no in matrices}, self.bridge.read_matrix)
            self.J_ref = max(EPS, float(sum(v["objective"] for v in out.values())))
            self.ref_set = True
        lin = {key: m.delta_for(self.ref.TARGETS[key]["matrix_nos"], matrices) for key in out}
        total_lin = sum(lin.values()) if lin else np.zeros(len(m.profiles))
        if self.measured:
            M_meas = m.read_live()
            gap = (M_meas - m.M_ref) - total_lin
            absum = sum(np.abs(v) for v in lin.values()) if lin else np.zeros(len(m.profiles))
            n = max(1, len(out))
            attributed = {}
            for key, dm in lin.items():
                share = np.where(absum > EPS, np.abs(dm) / np.maximum(absum, EPS), 1.0 / n)
                attributed[key] = dm + gap * share
        else:
            M_meas = m.M_ref + total_lin
            attributed = lin
        q_ref_scale = math.sqrt(wc / max(EPS, m.Q_ref))
        i_scale = math.sqrt(wi / self.J_ref)
        J_sum = 0.0
        for key, met in out.items():
            r_idp = np.asarray(met["residual"], dtype=float)
            J_sum += float(met["objective"])
            r_cnt = q_ref_scale * m.q(m.M_ref + attributed[key])
            r = np.r_[i_scale * r_idp, r_cnt]
            met["v24917_idp_objective"] = float(met["objective"])
            met["v24917_count_term"] = float(r_cnt @ r_cnt)
            met["residual"] = r
            met["objective"] = float(r @ r)
        F = wc * m.Q(M_meas) / max(EPS, m.Q_ref) + wi * J_sum / self.J_ref
        rec = {"t": time.time(), "mode": "MEASURED" if self.measured else "FROZEN_LINEAR",
               "F_blend": F, "count_term": m.Q(M_meas) / max(EPS, m.Q_ref), "idp_term": J_sum / self.J_ref,
               "mean_geh_weighted": m.mean_geh(M_meas), "mean_geh_weighted_ref": m.mean_geh(m.M_ref),
               "model_obs_ratio": float(M_meas.sum() / m.O.sum()),
               "linear_map": m.linear is not None, "w_cnt": wc, "w_idp": wi,
               "linear_profile_coverage": getattr(m, "linear_profile_coverage", None)}
        if not getattr(self, "_coverage_reported", False):
            self._coverage_reported = True
            cov = getattr(m, "linear_profile_coverage", None) or {}
            print("R1 V24917 TD BLEND: count term on %s/%s profiles via FlowBundle incidence%s" % (
                cov.get("mapped", 0), cov.get("profiles", len(m.profiles)),
                "" if m.linear is not None else " - NO INCIDENCE, count term constant (survey-only TD)"))
        try:
            with self.log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        except Exception:
            pass
        _STATE["last_inner"] = rec
        return out


# ------------------------------------------------------------------ outer acceptance
def outer_decision(parent: Mapping[str, Any], before, after, cfg) -> Dict[str, Any]:
    import r1_15a2_core as core
    import r1_15a2_multiblock as mb
    o = options()
    wc, wi = o["w_cnt"], o["w_idp"]
    cb = core.csd_metrics(before["d12"]["rows"], "CALIBRATION", True).get("objective_geh_mean_weighted", float("inf"))
    ca = core.csd_metrics(after["d12"]["rows"], "CALIBRATION", True).get("objective_geh_mean_weighted", float("inf"))
    comps = sorted(before.get("signals", {}) or {})
    ib = mb.td_component_metrics(before.get("signals", {}), comps, cfg).get("weighted_objective", float("inf"))
    ia = mb.td_component_metrics(after.get("signals", {}), comps, cfg).get("weighted_objective", float("inf"))
    cnt_ratio = ca / cb if cb > EPS and math.isfinite(ca) else float("inf")
    idp_ratio = ia / ib if ib > EPS and math.isfinite(ia) else (1.0 if ia == ib else float("inf"))
    F = wc * cnt_ratio + wi * idp_ratio
    hard = [r for r in (parent.get("reasons") or [])
            if not any(str(r).startswith(p) for p in SOFT_REASON_PREFIXES)]
    reasons = list(hard)
    if not (F <= 1.0 - OUTER_MIN_RELATIVE_IMPROVEMENT):
        reasons.append("V24917_TD_BLEND_NOT_IMPROVED")
    max_idp_ratio = float(o.get("max_idp_ratio", OUTER_MAX_IDP_RATIO))
    if idp_ratio > max_idp_ratio:
        reasons.append("V24917_TD_SURVEY_DEGRADED_BEYOND_25PCT")
    out = dict(parent)
    out["parent_reasons"] = list(parent.get("reasons") or [])
    out["parent_accepted"] = bool(parent.get("accepted"))
    out["reasons"] = reasons
    out["accepted"] = not reasons
    out["v24917_td_blend"] = {"schema": SCHEMA, "w_cnt": wc, "w_idp": wi, "F": F,
                              "cal_geh_before": cb, "cal_geh_after": ca, "count_ratio": cnt_ratio,
                              "idp_before": ib, "idp_after": ia, "idp_ratio": idp_ratio,
                              "min_relative_improvement": OUTER_MIN_RELATIVE_IMPROVEMENT,
                              "max_idp_ratio": max_idp_ratio,
                              "hard_reasons_kept": hard}
    _STATE["last_outer"] = out["v24917_td_blend"]
    print("R1 V24917 TD BLEND: F=%.4f counts %.3f->%.3f (x%.3f) survey x%.3f -> %s"
          % (F, cb, ca, cnt_ratio, idp_ratio, "ACCEPT" if out["accepted"] else "REJECT:" + ",".join(reasons)))
    return out


# ------------------------------------------------------------------ install
def install(print_fn=print) -> Dict[str, Any]:
    if _STATE.get("installed"):
        return _STATE["installed"]
    import r1_15a2_finecdf_bridge_v24916 as bridge_mod
    import r1_15a2_overnight_controller_coupled_v24915p2_force100 as ctrl
    opts = options()

    # 1. blended inner metric
    global ORIGINAL_EVALUATE
    orig_eval = bridge_mod.DynamicFamilyMetrics.evaluate
    if not getattr(orig_eval, "_v24917_blend", False):
        ORIGINAL_EVALUATE = orig_eval
        @functools.wraps(orig_eval)
        def evaluate(self, matrices):
            out = orig_eval(self, matrices)
            if not is_td_inner_bridge(self.bridge):
                # 11D overlay / dynamic 11D file publishing build this class with a bare
                # SimpleNamespace(dynamic_skim_epoch=...): diagnostics keep the pure survey metric.
                from r1_15a2_dynamic_11d_files_v24917 import record_metrics
                record_metrics(self, out)
                return out
            blend = getattr(self, "_v24917_blend_state", None)
            if blend is None:
                try:
                    blend = Blend(self.bridge, self.ref, options())
                except Exception as exc:
                    if options().get("joint_enabled", False):
                        raise RuntimeError("TDJOINT1_BLEND_INITIALIZATION_FAILED") from exc
                    blend = False  # legacy behavior, only with TDJOINT1 explicitly off
                    _STATE["blend_init_failures"] = _STATE.get("blend_init_failures", 0) + 1
                    _STATE["last_blend_init_error"] = repr(exc)[:2000]
                    print("R1 V24917 TD BLEND WARNING: blend disabled for this TD stage, "
                          "survey-only inner metric: %r" % (exc,))
                self._v24917_blend_state = blend
                if blend is not False:
                    _STATE["last_blend"] = blend
            if blend is False:
                return out
            return blend.apply(out, matrices)
        evaluate._v24917_blend = True
        bridge_mod.DynamicFamilyMetrics.evaluate = evaluate

    # 2. frozen-path inner execution (TD operation only)
    orig_exec = bridge_mod.NoDirectMatrixWriteTDAdapter.execute
    if not getattr(orig_exec, "_v24917_frozen", False):
        @functools.wraps(orig_exec)
        def execute(self):
            if not hasattr(self, "_v24917_frozen"):
                manager = getattr(self.outer_adapter, "v24916_dynamic_skims", None)
                current = getattr(manager, "current", None) if manager is not None else None
                self._v24917_frozen = bool(self.dynamic_skim_enabled and current is not None
                                           and options()["inner_mode"] == "FROZEN_PATHS")
                if self._v24917_frozen:
                    self.dynamic_skim_epoch = current
            if not self._v24917_frozen:
                return orig_exec(self)
            self.assert_isolated()
            if getattr(self.outer_adapter, '_long_post_td_mask_enabled', False):
                ordinal = int(getattr(self, '_long_mask_eval', 0)) + 1
                self._long_mask_eval = ordinal
                bridge_mod.rt.execute_procseq(self.v, Path(self.root) / 'LONG_MASK_INNER' / ('EVAL_%04d' % ordinal))
            else:
                self.v.Procedures.Execute()
            arrays = self.read_outputs()
            for no, a in arrays.items():
                if float(a.sum()) <= 0 or float(a.min()) < -1e-10:
                    raise RuntimeError("V24917_FROZEN_TD_INVALID_OUTPUT_M%d" % no)
            self.guard_protected(full=True)
            return arrays
        execute._v24917_frozen = True
        bridge_mod.NoDirectMatrixWriteTDAdapter.execute = execute

    # 3. Explicit TG/TD search budgets; capped stages remain bounded searches.
    orig_gcfg = ctrl._generation_counts_cfg
    if not getattr(orig_gcfg, "_v24917_fast", False):
        @functools.wraps(orig_gcfg)
        def generation_counts_cfg(cfg, *args, **kwargs):
            out = orig_gcfg(cfg, *args, **kwargs)
            n = options()["tg_max_trials"]
            scales = list(out.get("backtracking_scales") or [1.0, 0.5, 0.25])
            out["backtracking_scales"] = scales[:max(1, n)]
            return out
        generation_counts_cfg._v24917_fast = True
        ctrl._generation_counts_cfg = generation_counts_cfg
    orig_scales = ctrl._td_realization_scales
    if not getattr(orig_scales, "_v24917_fast", False):
        @functools.wraps(orig_scales)
        def td_realization_scales(cfg, *args, **kwargs):
            return orig_scales(cfg, *args, **kwargs)[:max(1, options()["td_realization_max_trials"])]
        td_realization_scales._v24917_fast = True
        ctrl._td_realization_scales = td_realization_scales
    orig_budget = ctrl._finecdf_budget_for_cycle
    if not getattr(orig_budget, "_v24917_fast", False):
        @functools.wraps(orig_budget)
        def finecdf_budget_for_cycle(cfg, *args, **kwargs):
            return search_budget(orig_budget(cfg, *args, **kwargs) or {}, cfg, options())
        finecdf_budget_for_cycle._v24917_fast = True
        ctrl._finecdf_budget_for_cycle = finecdf_budget_for_cycle

    status = {"installed": True, "release": RELEASE, "options": opts}
    print_fn("R1 V24917 TD BLEND: counts %.0f %% / survey %.0f %%, inner=%s, TG trials<=%d, "
             "TD realizations<=%d, TD inner evals<=%d, phase budget multiplier %.2f"
             % (100 * opts["w_cnt"], 100 * opts["w_idp"], opts["inner_mode"], opts["tg_max_trials"],
                opts["td_realization_max_trials"], opts["td_inner_max_evaluations"],
                opts.get("td_inner_budget_multiplier", 1.0)))
    _STATE["installed"] = status
    return status


__all__ = ["RELEASE", "SCHEMA", "options", "search_budget", "CountModel", "Blend", "outer_decision", "install"]
