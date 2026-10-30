# -*- coding: utf-8 -*-
"""MOBILITY2 / GENFIX2: explicit production envelope, before and after realization.

The existing reference R = sum(FP)/sum(FP/ADD_PROD) is retained.
The WORK/SERVICE production band is configured [0.75,3.0] in the universal
fresh release. It is NOT an independent survey coefficient validation.
The separate final W/S domestic ADD_ATT coefficient fence [0.75,5.0]
checks zonal write/readback, NEVER the production/survey mobility ratio.
For mixed-sign log steps R(s) is convex, not monotone: test its interior minimum
as well as both endpoints. Every final candidate is checked again after masks,
bounds and P/A balancing. Missing data never silently disables an enabled guard.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RELEASE = "R1_15A2_V24917_MOBILITY2_W_S_ATTR_FINAL_GATE_V3_20261031"
GROUPS = ("E_C", "E_noC", "noE_C", "noE_noC", "stud")
FP_ATTRS = {"WORK": ["FP_1_WORK_%s" % g for g in GROUPS],
            "SERVICE": ["FP_2_SERVICE_%s" % g for g in GROUPS]}
MULT_ATTR = {"WORK": "ADD_PROD_W", "SERVICE": "ADD_PROD_S"}
ATTRACTION_ATTR = {"WORK": "ADD_ATT_W", "SERVICE": "ADD_ATT_S"}
ATTRACTION_BAND = (0.75, 5.0)
EPS = 1.0e-12
CERT = "v24917_mobility2_certificate"


def options():
    import r1_15a2_demand_policy_v1 as dp
    o = dp.load_options()
    return {"enabled": bool(o.get("mg_enabled", True)),
            "lo": float(o.get("mg_min_ratio", .75)),
            "hi": float(o.get("mg_max_ratio", 2.0)),
            "ws_attraction_coefficient_band": list(ATTRACTION_BAND)}


def _f(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _limits(opts):
    lo, hi = _f(opts.get("lo")), _f(opts.get("hi"))
    if lo is None or hi is None or not 0 < lo <= hi:
        raise ValueError("MOBILITY2_INVALID_BAND")
    return lo, hi


def _attraction_band(opts):
    """Separate coefficient authority, not the observed mobility P band.

    Direct historical mobility test fixtures without this new policy remain
    production-only. The V24917 live adapter always uses options(), which
    explicitly installs the attraction fence and has complete zone snapshots.
    """
    raw = opts.get("ws_attraction_coefficient_band")
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError("MOBILITY2_WS_ATTRACTION_BAND_INVALID")
    lo, hi = (_f(x) for x in raw)
    if (lo, hi) != ATTRACTION_BAND:
        raise ValueError("MOBILITY2_WS_ATTRACTION_BAND_MISMATCH")
    return lo, hi


def _attraction_source(rows):
    """Strict fixed-pre-trial domestic W/S ADD_ATT parent; all zones, even FP=0."""
    result, seen = {}, set()
    for row in rows:
        z = int(row["zone_no"])
        if z <= 0 or z in seen:
            raise ValueError("MOBILITY2_WS_ATTRACTION_ZONE_ID_INVALID:" + str(z))
        seen.add(z)
        mask = _f(row.get("NOT_ZAHR"))
        if mask is None:
            raise ValueError("MOBILITY2_WS_ATTRACTION_MASK_UNREADABLE:" + str(z))
        if mask < 0.5:
            continue
        for family, attr in ATTRACTION_ATTR.items():
            value = _f(row.get(attr))
            if value is None or value < 0.0:
                raise ValueError("MOBILITY2_WS_ATTRACTION_PARENT_UNREADABLE:%s:%s" % (family, z))
            result[(z, attr)] = value
    if not result:
        raise ValueError("MOBILITY2_WS_ATTRACTION_NO_DOMESTIC_ZONES")
    return result


def _attraction_valid(current, proposed, low, high):
    if proposed is None or proposed < 0.0:
        return False
    tol = 1.0e-9 + 1.0e-10 * max(abs(current), abs(proposed))
    if current <= EPS:
        # Preserve structural-zero ADD_ATT. Generation uses preserve_zero_add.
        return abs(proposed - current) <= tol
    return min(low, current) - tol <= proposed <= max(high, current) + tol


def _attraction_candidate_guard(candidate_rows, parent_rows, band):
    parent = _attraction_source(parent_rows)
    low, high = band
    checked, errors = 0, []
    for row in candidate_rows:
        attr = str(row.get("attr", "")).upper()
        if attr not in ATTRACTION_ATTR.values():
            continue
        z = int(row["zone_no"])
        if (z, attr) not in parent:
            continue  # Foreign-zone ADD_ATT never receives a domestic constraint.
        checked += 1
        before = parent[(z, attr)]
        current, proposed = _f(row.get("current")), _f(row.get("proposed"))
        tol = 1.0e-9 + 1.0e-10 * max(abs(before), abs(current or 0.0))
        if current is None or abs(current - before) > tol:
            reason = "STALE_PARENT"
        elif not _attraction_valid(before, proposed, low, high):
            reason = "ATTRACTION_COEFFICIENT_OUTSIDE_BAND"
        else:
            continue
        errors.append({"zone_no": z, "attr": attr, "reason": reason,
                       "current": current, "proposed": proposed,
                       "parent": before})
    return {"policy": "DOMESTIC_WS_ATTR_COEFFICIENT_NOT_MOBILITY_RATIO",
            "band": [low, high], "checked_candidates": checked,
            "checked_parent_zones": len(parent) // len(ATTRACTION_ATTR),
            "passes": not errors, "violations": errors[:100]}


def _attraction_live_guard(before_rows, after_rows, band):
    before = _attraction_source(before_rows)
    after = _attraction_source(after_rows)
    if set(before) != set(after):
        raise ValueError("MOBILITY2_WS_ATTRACTION_LIVE_ZONE_COVERAGE_CHANGED")
    low, high = band
    errors = []
    for (z, attr), old in before.items():
        proposed = after[(z, attr)]
        if not _attraction_valid(old, proposed, low, high):
            errors.append({"zone_no": z, "attr": attr, "reason": "LIVE_ATTRACTION_OUTSIDE_BAND",
                           "parent": old, "realized": proposed})
    return {"policy": "DOMESTIC_WS_ATTR_COEFFICIENT_NOT_MOBILITY_RATIO",
            "band": [low, high], "checked_live_values": len(before),
            "passes": not errors, "violations": errors[:100]}


def zone_productions(zone_rows, family):
    out, seen = {}, set()
    for row in zone_rows:
        z = int(row["zone_no"])
        if z in seen:
            raise ValueError("MOBILITY2_DUPLICATE_ZONE:%s" % z)
        seen.add(z)
        mask = _f(row.get("NOT_ZAHR"))
        if mask is None:
            raise KeyError("MOBILITY2_DOMESTIC_MASK_MISSING:%s" % z)
        if mask < .5:
            continue
        values = [_f(row.get(attr)) for attr in FP_ATTRS[family]]
        if any(v is None for v in values):
            raise KeyError("MOBILITY2_FP_ATTRIBUTE_MISSING:%s:%s" % (family, z))
        if any(v < 0 for v in values):
            raise ValueError("MOBILITY2_NEGATIVE_PRODUCTION:%s:%s" % (family, z))
        p = math.fsum(values)
        # A domestic zone with zero production has zero weight in both sums.
        # Preserve the calibrated zero instead of requiring a positive ADD_PROD
        # for a mathematically inactive term. Nonfinite inputs remain errors.
        c = _f(row.get(MULT_ATTR[family]))
        if c is None:
            raise ValueError("MOBILITY2_NONFINITE_MULTIPLIER:%s:%s" % (family, z))
        if p <= EPS:
            continue
        if c <= EPS:
            raise ValueError("MOBILITY2_INVALID_MULTIPLIER:%s:%s" % (family, z))
        out[z] = (p, c)
    return out


def ratio(prod, steps=None, alpha=1.0, sign=0):
    den = math.fsum(p/c for p, c in prod.values())
    terms = []
    for z, (p, c) in prod.items():
        s = float((steps or {}).get(z, 0.0))
        if sign and s*sign > 0:
            s *= alpha
        terms.append(p*math.exp(s))
    return math.fsum(terms)/den if den > EPS else float("nan")


def _extrema(prod, steps, end=1.0):
    """Exact convex minimum, up to binary-search roundoff, over [0,end]."""
    def value(t):
        return ratio(prod, {z: t*s for z, s in steps.items()})
    def derivative(t):
        return math.fsum(p*steps.get(z, 0.0)*math.exp(t*steps.get(z, 0.0)) for z, (p, c) in prod.items())
    r0, r1 = value(0), value(end)
    if derivative(0) >= 0:
        minimum, at = r0, 0.0
    elif derivative(end) <= 0:
        minimum, at = r1, end
    else:
        lo, hi = 0.0, end
        for _ in range(65):
            mid = .5*(lo+hi)
            if derivative(mid) < 0:
                lo = mid
            else:
                hi = mid
        at = .5*(lo+hi)
        minimum = value(at)
    return minimum, max(r0, r1), at


def _set_step(row, step):
    row.setdefault("v24917_mobility_pre_log_step", float(row.get("log_step", 0.0)))
    row["log_step"] = float(step)
    if "requested_log_step" in row:
        row["requested_log_step"] = float(step)
    row["multiplier"] = math.exp(step)
    row["guided_margin_delta"] = row["projected_margin_delta"] = float(row.get("base_margin_volume", 0) or 0)*math.expm1(step)
    row["raw_relative_margin_change"] = math.expm1(step)


def guard(rows, zone_rows, opts=None):
    opts = dict(options() if opts is None else opts)
    lo, hi = _limits(opts)
    report = {"release": RELEASE, "band": [lo, hi], "families": {}, "passes": True}
    if not opts.get("enabled", True):
        report["status"] = "DISABLED"
        return rows, report
    out = [dict(r) for r in rows]
    for fam in MULT_ATTR:
        prod = zone_productions(zone_rows, fam)
        if not prod:
            report.update(status="BLOCKED_NO_DOMESTIC_PRODUCTION", passes=False, blocked_family=fam)
            return [], report
        prows, steps = {}, {}
        for r in out:
            z = int(r["zone_no"])
            if r.get("family") != fam or r.get("role") != "PROD" or z not in prod:
                continue
            if z in prows:
                raise ValueError("MOBILITY2_DUPLICATE_PRODUCTION_STEP:%s:%s" % (fam, z))
            step = _f(r.get("log_step", 0.0))
            if step is None:
                raise ValueError("MOBILITY2_NONFINITE_STEP")
            prows[z], steps[z] = r, step
        r0, r1 = ratio(prod), ratio(prod, steps)
        lower, upper = min(lo, r0), max(hi, r0)
        def feasible(alpha):
            low, high, _ = _extrema(prod, steps, alpha)
            return low >= lower-EPS*.25 and high <= upper+EPS*.25
        alpha = 1.0
        if not feasible(1.0):
            left, right = 0.0, 1.0
            # Feasibility of the entire PREFIX interval is monotone even when R is not.
            for _ in range(70):
                mid = .5*(left+right)
                if feasible(mid):
                    left = mid
                else:
                    right = mid
            alpha = left
        den = math.fsum(p/c for p, c in prod.values())
        for z, row in prows.items():
            _set_step(row, steps[z]*alpha)
            row[CERT] = {"family": fam, "ratio_current": r0, "lo": lower, "hi": upper,
                         "weight": prod[z][0]/den}
        after = ratio(prod, {z: float(r["log_step"]) for z, r in prows.items()})
        mn, mx, at = _extrema(prod, {z: s*alpha for z, s in steps.items()})
        report["families"][fam] = {"ratio_current": r0, "ratio_full_step": r1, "ratio_after": after,
            "zones": len(prod), "rows": len(prows), "factor": alpha,
            "minimum_over_scales": mn, "maximum_over_scales": mx, "minimum_at_scale": at,
            "status": "ATTENUATED" if alpha < 1.0 else ("WITHIN_BAND" if lo-EPS <= after <= hi+EPS else "OUTSIDE_BAND_NOT_MOVING_AWAY")}
    report["status"] = "OK"
    return out, report


def certificate_passes(rows, field="requested_log_step"):
    """P/A balancing must not undo the bounded production proposal (A02)."""
    families = {}
    for row in rows:
        cert = row.get(CERT)
        if not cert:
            continue
        fam = cert["family"]
        values = families.setdefault(fam, {"base": cert["ratio_current"], "lo": cert["lo"], "hi": cert["hi"], "deltas": []})
        if any(values[k] != cert[c] for k, c in (("base", "ratio_current"), ("lo", "lo"), ("hi", "hi"))):
            return False
        step = _f(row.get(field, row.get("log_step", 0.0)))
        if step is None:
            return False
        values["deltas"].append(float(cert["weight"])*math.expm1(step))
    return all(v["lo"]-EPS <= v["base"]+math.fsum(v["deltas"]) <= v["hi"]+EPS for v in families.values())


def check_candidate(rows, zone_rows, opts=None):
    """Validate the exact rows that will be written, AFTER all transformations."""
    opts = dict(options() if opts is None else opts)
    lo, hi = _limits(opts)
    report = {"release": RELEASE, "families": {}, "passes": True, "status": "OK"}
    if not opts.get("enabled", True):
        return dict(report, status="DISABLED")
    seen = set()
    for row in rows:
        key = (row.get("attr"), int(row["zone_no"]))
        if key in seen:
            raise ValueError("MOBILITY2_DUPLICATE_CANDIDATE_PARAMETER:%s" % (key,))
        seen.add(key)
    for fam, attr in MULT_ATTR.items():
        prod = zone_productions(zone_rows, fam)
        if not prod:
            raise ValueError("MOBILITY2_NO_DOMESTIC_PRODUCTION:" + fam)
        steps = {}
        for row in rows:
            z = int(row["zone_no"])
            if row.get("attr") != attr or z not in prod:
                continue
            current, proposed = _f(row.get("current")), _f(row.get("proposed"))
            if current is None or proposed is None or min(current, proposed) <= EPS:
                raise ValueError("MOBILITY2_INVALID_CANDIDATE_VALUE")
            if abs(current-prod[z][1]) > 1e-7 + 1e-10*abs(prod[z][1]):
                raise ValueError("MOBILITY2_STALE_CANDIDATE_PARENT:%s:%s" % (fam, z))
            steps[z] = math.log(proposed/current)
        r0, r1 = ratio(prod), ratio(prod, steps)
        ok = min(lo, r0)-EPS <= r1 <= max(hi, r0)+EPS
        report["families"][fam] = {"ratio_current": r0, "ratio_after": r1, "passes": ok, "zones": len(prod)}
        report["passes"] &= ok
    band = _attraction_band(opts)
    if band is not None:
        attraction = _attraction_candidate_guard(rows, zone_rows, band)
        report["ws_attraction_coefficient_gate"] = attraction
        report["passes"] = bool(report["passes"] and attraction["passes"])
    if not report["passes"]:
        report["status"] = "REJECTED_FINAL_CANDIDATE_OUTSIDE_ENVELOPE"
    return report


def check_live(before_rows, after_rows, opts=None):
    """Measure the realization against the fixed pre-trial reference, not a moving denominator."""
    opts = dict(options() if opts is None else opts)
    lo, hi = _limits(opts)
    report = {"release": RELEASE, "passes": True, "status": "OK", "families": {}}
    if not opts.get("enabled", True):
        return dict(report, status="DISABLED")
    for fam in MULT_ATTR:
        before, after = zone_productions(before_rows, fam), zone_productions(after_rows, fam)
        if not before or set(before) != set(after):
            raise ValueError("MOBILITY2_LIVE_COVERAGE_CHANGED:" + fam)
        for z in before:
            reference_before, reference_after = before[z][0]/before[z][1], after[z][0]/after[z][1]
            if abs(reference_after-reference_before) > 1e-7 + 1e-10*abs(reference_before):
                raise ValueError("MOBILITY2_UNIT_REFERENCE_CHANGED:%s:%s" % (fam, z))
        denominator = math.fsum(p/c for p, c in before.values())
        r0 = ratio(before)
        r1 = math.fsum(p for p, c in after.values())/denominator
        ok = min(lo, r0)-EPS <= r1 <= max(hi, r0)+EPS
        report["families"][fam] = {"ratio_current": r0, "ratio_realized": r1, "passes": ok}
        report["passes"] &= ok
    band = _attraction_band(opts)
    if band is not None:
        attraction = _attraction_live_guard(before_rows, after_rows, band)
        report["ws_attraction_coefficient_gate"] = attraction
        report["passes"] = bool(report["passes"] and attraction["passes"])
    if not report["passes"]:
        report["status"] = "REJECTED_LIVE_WS_PRODUCTION_OR_ATTRACTION_ENVELOPE"
    return report


__all__ = ["RELEASE", "GROUPS", "options", "zone_productions", "ratio", "guard", "check_candidate", "check_live", "certificate_passes"]
