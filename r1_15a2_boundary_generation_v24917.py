# -*- coding: utf-8 -*-
"""BNDGEN1 (V24917): border-crossing (cordon X1-X31) synthetic P/A as a Generation lever.

The 31 boundary zones carry their trips only through the synthetic boundary vectors
P09F4_PER_PRE_* / A09F4_PER_PRE_* (no ADD_* coefficients), so the WORK/SERVICE zonal
fit never touched them and the count deficit on the crossings could not shrink.

One variable per (family, crossing zone): a log step that scales the production AND
the attraction of that zone in the family's five person-group layers together
(boundary P/A are symmetric "pre-sym" inputs).  Its count exposure is the FlowBundle
exposure of every OD with the crossing as origin plus as destination (the PROD and
ATT columns of the zonal fit, merged after the family normalisation).  It is solved
JOINTLY with the domestic WORK/SERVICE variables (same weights, ridge, P/A balance).

Bounds: the per-cycle step caps of the active phase (CATCH_UP / REFINE) and the ZAHR
boundary envelope of the targeted-generation policy (default x[0.5, 2] of the run-start value
of the family's P total of the zone).  LONG/SCHOOL boundary layers and FOREIGN are not
touched.  Rows are written in the same trial as the W/S rows (one assignment) and are
snapshot/rollback state (mb.GENERATION_ATTRS is extended on activation).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

RELEASE = "R1_15A2_V24917_BOUNDARY_GENERATION_V1_20261025"
EPS = 1.0e-12
GROUPS = ("E_C", "E_noC", "noE_C", "noE_noC", "stud")
FAMILY_TOKEN = {"WORK": "WORK", "SERVICE": "SERV"}
DEFAULT_ZONES = list(range(650, 681))           # X1 ... X31
STATE: Dict[str, Any] = {"active": False}


def attrs_for(family: str, side: str) -> List[str]:
    pre = "P09F4_PER_PRE_" if side == "P" else "A09F4_PER_PRE_"
    return [pre + FAMILY_TOKEN[family] + "_" + g for g in GROUPS]


ALL_ATTRS = [a for f in ("WORK", "SERVICE") for s in ("P", "A") for a in attrs_for(f, s)]


def options() -> Dict[str, Any]:
    out = {"bd_enabled": True, "bd_zones": list(DEFAULT_ZONES)}
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options()
    out["bd_enabled"] = bool(o.get("bd_enabled", True))
    if o.get("bd_zones"):
        out["bd_zones"] = [int(z) for z in o["bd_zones"]]
    return out


def _zone_values(visum, attr: str) -> Dict[int, float]:
    nos = [int(float(v)) for _, v in visum.Net.Zones.GetMultiAttValues("NO", False)]
    vals = [float(v or 0.0) for _, v in visum.Net.Zones.GetMultiAttValues(attr, False)]
    return dict(zip(nos, vals))


def activate(visum) -> Dict[str, Any]:
    """Validate policy; defer unavailable optional COM boundary layers."""
    o = options()
    try:
        if not o["bd_enabled"]:
            STATE.update(active=False, reason="bd_enabled=false")
            return dict(STATE)
        import r1_15a2_multiblock as mb
        values = {a: _zone_values(visum, a) for a in ALL_ATTRS}
        zones = []
        for z in o["bd_zones"]:
            total = sum(values[a].get(z, 0.0) for a in ALL_ATTRS)
            if total > EPS:
                zones.append(int(z))
        if not zones:
            STATE.update(active=False, reason="NO_BOUNDARY_ZONE_WITH_POSITIVE_WS_PA")
            return dict(STATE)
        for a in ALL_ATTRS:
            if a not in mb.GENERATION_ATTRS:
                mb.GENERATION_ATTRS.append(a)
        STATE.update(active=True, zones=zones, attrs=list(ALL_ATTRS), release=RELEASE,
                     ws_total_p=float(sum(values[a].get(z, 0.0) for z in zones
                                          for a in ALL_ATTRS if a.startswith("P09F4"))))
        return dict(STATE)
    except Exception as exc:
        STATE.update(active=False, reason="%s:%s" % (type(exc).__name__, exc))
        return dict(STATE)


def active() -> bool:
    return bool(STATE.get("active"))


# ---------------------------------------------------------------- design
def current_values(visum, zones: Sequence[int]) -> Dict[str, Dict[int, float]]:
    out = {}
    for a in ALL_ATTRS:
        vals = _zone_values(visum, a)
        out[a] = {int(z): float(vals.get(int(z), 0.0)) for z in zones}
    return out


def bounds(current: Mapping[str, Mapping[int, float]], reference_values: Mapping[str, Mapping[str, Any]],
           cfg: Mapping[str, Any], envelope: Sequence[float]) -> Dict[Tuple[str, str, int], Tuple[float, float]]:
    """(family, PROD|ATT, zone) bounds; both roles get the same bounds (merged later)."""
    max_up = float(cfg.get("max_add_log_up", 0.04))
    max_dn = abs(float(cfg.get("max_add_log_down", 0.04)))
    lo_mult, hi_mult = float(envelope[0]), float(envelope[1])
    out = {}
    ref = reference_values or {}
    for z in STATE.get("zones", []):
        for fam in ("WORK", "SERVICE"):
            cur = sum(current[a][z] for a in attrs_for(fam, "P"))
            if cur <= EPS:
                continue
            r = 0.0
            for a in attrs_for(fam, "P"):
                rv = (ref.get(a) or {}).get(str(z))
                r += float(rv) if rv is not None else current[a][z]
            r = r if r > EPS else cur
            lo = max(-max_dn, math.log(lo_mult * r / cur))
            hi = min(max_up, math.log(hi_mult * r / cur))
            lo, hi = min(0.0, lo), max(0.0, hi)
            if hi - lo > EPS:
                out[(fam, "PROD", int(z))] = (lo, hi)
                out[(fam, "ATT", int(z))] = (lo, hi)
    return out


def merge_pa(problem, zone_set: Iterable[int]):
    """Merge PROD+ATT columns of boundary zones into one (family, 'PA', zone) variable."""
    import r1_15a2_zonal_count_fit_v24917 as zf
    zone_set = {int(z) for z in zone_set}
    keys = list(problem.var_keys)
    idx = {k: i for i, k in enumerate(keys)}
    keep: List[int] = []
    cols, new_keys, base, lo, hi = [], [], [], [], []
    bal = {f: [] for f in problem.balance_vectors}
    used = set()
    for i, (fam, role, z) in enumerate(keys):
        if i in used:
            continue
        if int(z) in zone_set and role in ("PROD", "ATT"):
            other = idx.get((fam, "ATT" if role == "PROD" else "PROD", z))
            group = [i] + ([other] if other is not None else [])
            used.update(group)
            cols.append(problem.G[:, group].sum(axis=1))
            new_keys.append((fam, "PA", int(z)))
            base.append(float(sum(problem.base[g] for g in group)))
            lo.append(float(max(problem.lower[g] for g in group)))
            hi.append(float(min(problem.upper[g] for g in group)))
            for f, (vec, tot) in problem.balance_vectors.items():
                # BALANCE1: the crossing scales its (symmetric, pre-sym) P and A together, so the
                # variable is trip-end neutral by construction; the incidence margins of its
                # origin/destination side differ only by path sampling.
                bal[f].append(0.0)
        else:
            used.add(i)
            cols.append(problem.G[:, i])
            new_keys.append((fam, role, z))
            base.append(float(problem.base[i]))
            lo.append(float(problem.lower[i]))
            hi.append(float(problem.upper[i]))
            for f, (vec, tot) in problem.balance_vectors.items():
                bal[f].append(float(vec[i]))
    G = np.column_stack(cols) if cols else np.zeros((problem.G.shape[0], 0))
    balance = {f: (np.asarray(bal[f]), problem.balance_vectors[f][1]) for f in problem.balance_vectors}
    out = zf.FitProblem(problem.zones, problem.profile_rows, G, problem.target, problem.weight, new_keys,
                        np.asarray(base), np.asarray(lo), np.asarray(hi), balance)
    out.unexposed_count = getattr(problem, "unexposed_count", 0)
    out.boundary_variables = sum(1 for k in new_keys if k[1] == "PA")
    return out


def split_rows(rows: Sequence[Mapping[str, Any]]):
    dom, bd = [], {}
    for r in rows:
        if str(r.get("role")) == "PA":
            bd[(str(r["family"]), int(r["zone_no"]))] = float(r["log_step"])
        else:
            dom.append(r)
    return dom, bd


def design_payload(steps: Mapping[Tuple[str, int], float], current: Mapping[str, Mapping[int, float]]):
    return {"steps": {"%s|%d" % k: float(v) for k, v in steps.items()},
            "current": {a: {str(z): float(v) for z, v in m.items()} for a, m in current.items()},
            "summary": {"variables": len(steps),
                        "zones": sorted({z for _, z in steps}),
                        "max_step": max([abs(v) for v in steps.values()], default=0.0),
                        "mean_step": float(np.mean(list(steps.values()))) if steps else 0.0}}


def rows_at_scale(bd: Mapping[str, Any], scale: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not bd or not bd.get("steps"):
        return out
    for key, step in sorted(bd["steps"].items()):
        fam, z = key.split("|")
        z = int(z)
        for side, role in (("P", "PROD"), ("A", "ATT")):
            for a in attrs_for(fam, side):
                c = float(bd["current"][a][str(z)])
                if c <= EPS:
                    continue
                out.append({"zone_no": z, "attr": a, "family": fam, "role": role, "branch": "BOUNDARY",
                            "current": c, "proposed": c * math.exp(float(scale) * float(step)),
                            "log_step": float(scale) * float(step), "source": "V24917_BNDGEN1"})
    return out


__all__ = ["RELEASE", "ALL_ATTRS", "attrs_for", "activate", "active", "current_values", "bounds",
           "merge_pa", "split_rows", "design_payload", "rows_at_scale", "options", "STATE"]
