# -*- coding: utf-8 -*-
"""MOBILITYZONE1: fixed-reference domestic production envelope, per zone/purpose.

Raw pre-mode-choice FP productions are compared, never profile passages, vehicle
OD or attraction weights. Reference is the existing AMDY equation evaluated at
ADD_PROD_W/S/SCH=1 and ADD_PROD_L=0.2, NOT raw unscaled survey trip frequency.
Existing out-of-band parents may improve or hold, never move further away.
No COM writes, no LoadVersion, no changes to native TD or boundary production.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping

RELEASE = "R1_15A2_V24917_MOBILITYZONE1_20261027"
GROUPS = ("E_C", "E_noC", "noE_C", "noE_noC", "stud")
SPECS = {
    "WORK": ("ADD_PROD_W", 1.0, tuple("FP_1_WORK_" + x for x in GROUPS)),
    "SERVICE": ("ADD_PROD_S", 1.0, tuple("FP_2_SERVICE_" + x for x in GROUPS)),
    "LONG": ("ADD_PROD_L", 0.2, tuple("FP_3_LONG_" + x for x in GROUPS)),
    "SCHOOL": ("ADD_PROD_SCH", 1.0, ("FP_5_SCHOOL",)),
}
ATTR_FAMILY = {v[0]: k for k, v in SPECS.items()}
ATT_FAMILY = {"ADD_ATT_L": "LONG", "ADD_ATT_SCH": "SCHOOL"}
EPS = 1e-12
ATOL = 1e-7
RTOL = 1e-10
REFERENCE = "AMDY_DOMESTIC_FP_AT_CANONICAL_COEFFICIENT_NOT_RAW_SURVEY"
LONG_BAND = (0.5, 1.5)  # ADD_PROD_L 0.2 x [0.5, 1.5] = [0.1, 0.3]


def finite(value, name):
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("MOBILITYZONE1_INVALID:" + name) from exc
    if not math.isfinite(x):
        raise ValueError("MOBILITYZONE1_NONFINITE:" + name)
    return x


def close(a, b):
    return abs(a-b) <= ATOL + RTOL*max(abs(a), abs(b))


def limits(opts):
    lo = finite(opts.get("lo", .75), "lo")
    hi = finite(opts.get("hi", 1.25), "hi")
    if not 0 < lo <= 1 <= hi:
        raise ValueError("MOBILITYZONE1_INVALID_BAND")
    return lo, hi


def zone_map(rows):
    out = {}
    for row in rows:
        raw = finite(row.get("zone_no"), "zone_no")
        if raw != int(raw) or raw <= 0 or int(raw) in out:
            raise ValueError("MOBILITYZONE1_INVALID_OR_DUPLICATE_ZONE")
        out[int(raw)] = row
    if not out:
        raise ValueError("MOBILITYZONE1_EMPTY_ZONE_COVERAGE")
    return out


def enrich(adapter, rows):
    """Read LS FP strictly, with existing bounded COM retry and indexed identity.

    Failure defers only that optional family; no invented zeros or cached values.
    W/S required data have already been acquired by zone_state_rows.
    """
    import r1_15a2_runtime_v1 as rt
    out = copy.deepcopy(list(rows))
    families, unavailable = ["WORK", "SERVICE"], {}
    if not (getattr(adapter, "v24917_ls", {}) or {}).get("active"):
        return out, families, unavailable
    for fam in ("LONG", "SCHOOL"):
        families.append(fam)
        attr, _, fps = SPECS[fam]
        try:
            for name in (attr,) + fps:
                vals = rt.read_zone_attr_strict(adapter.visum, name, adapter.zones,
                    zone_indices=adapter.zone_write_index_by_no,
                    retry_policy=adapter.com_retry_policy)
                if len(vals) != len(out):
                    raise ValueError("MOBILITYZONE1_ATTRIBUTE_AXIS:" + name)
                if [int(r["zone_no"]) for r in out] != [int(z) for z in adapter.zones]:
                    raise ValueError("MOBILITYZONE1_ZONE_ORDER")
                for row, value in zip(out, vals):
                    row[name] = finite(value, name)
        except Exception as exc:
            unavailable[fam] = type(exc).__name__ + ":" + str(exc)
    return out, families, unavailable


def capture(rows, opts, families=("WORK", "SERVICE"), unavailable=None, anchor=None):
    """Build a fixed reference and retain the raw parent for readback/rollback."""
    lo, hi = limits(opts)
    if anchor is not None and tuple(anchor.get("long_band", ())) != LONG_BAND:
        raise ValueError("MOBILITYZONE1_LONG_BAND_CHANGED")
    by_zone = zone_map(rows)
    entries, errors = {}, dict(unavailable or {})
    for fam in families:
        if fam in errors:
            continue
        attr, ref, fps = SPECS[fam]
        current_entries = {}
        try:
            for z, row in by_zone.items():
                mask = finite(row.get("NOT_ZAHR"), "NOT_ZAHR:%s" % z)
                if mask < .5:
                    continue
                c = finite(row.get(attr), "%s:%s" % (attr, z))
                values = {a: finite(row.get(a), "%s:%s" % (a, z)) for a in fps}
                if c < 0 or any(v < 0 for v in values.values()):
                    raise ValueError("MOBILITYZONE1_NEGATIVE_PRODUCTION_OR_COEFFICIENT:%s:%s" % (fam,z))
                p = math.fsum(values.values())
                if c <= EPS and p > EPS:
                    raise ValueError("MOBILITYZONE1_POSITIVE_FP_WITH_ZERO_COEFFICIENT:%s:%s" % (fam,z))
                base = {a: v*ref/c for a,v in values.items()} if c > EPS else None
                entry = {"zone_no": z, "family": fam, "attr": attr, "reference_coefficient": ref,
                    "current": c, "production": p, "fp": values, "reference_fp": base,
                    "reference_production": math.fsum(base.values()) if base is not None else None,
                    "ratio_current": c/ref if p > EPS else None,
                    "status": "VERIFIED" if p > EPS else "ZERO_PRODUCTION_FROZEN"}
                key = fam + "|" + str(z)
                previous = (anchor or {}).get("entries", {}).get(key)
                if previous is not None:
                    old = previous["reference_fp"]
                    if (old is None) != (base is None) or (old is not None and
                            (set(old) != set(base) or any(not close(old[a],base[a]) for a in old))):
                        raise ValueError("MOBILITYZONE1_FIXED_REFERENCE_CHANGED:" + key)
                    entry["reference_fp"] = copy.deepcopy(old)
                    entry["reference_production"] = previous["reference_production"]
                current_entries[key] = entry
            old_keys = {k for k in (anchor or {}).get("entries", {}) if k.startswith(fam+"|")}
            if old_keys and old_keys != set(current_entries):
                raise ValueError("MOBILITYZONE1_DOMESTIC_COVERAGE_CHANGED:" + fam)
            if not current_entries:
                raise ValueError("MOBILITYZONE1_NO_DOMESTIC_ZONES:" + fam)
            entries.update(current_entries)
        except Exception as exc:
            errors[fam] = type(exc).__name__ + ":" + str(exc)
    outside = []
    for e in entries.values():
        band_lo, band_hi = LONG_BAND if e["family"] == "LONG" else (lo, hi)
        if e["ratio_current"] is not None and not band_lo-EPS <= e["ratio_current"] <= band_hi+EPS:
            outside.append({"zone_no": e["zone_no"], "family": e["family"],
                            "ratio": e["ratio_current"]})
    return {"release": RELEASE, "enabled": bool(opts.get("enabled", True)),
            "band": [lo, hi], "long_band": list(LONG_BAND), "reference_role": REFERENCE,
            "families": list(families), "entries": entries,
            "unavailable": errors, "out_of_band": outside,
            "target_satisfied": not bool(errors or outside), "parent_zone_rows": copy.deepcopy(list(rows)),
            "status": "VERIFIED" if not errors else "PARTIAL_DEFERRED",
            "search_complete": not bool(errors)}


def interval(entry, authority):
    lo, hi = authority["long_band"] if entry["family"] == "LONG" else authority["band"]
    r = entry["current"]/entry["reference_coefficient"]
    return min(lo,r), max(hi,r)


def bounded_step(entry, step, authority):
    step = finite(step, "log_step")
    if entry["reference_fp"] is None:
        return 0.0
    lo, hi = interval(entry, authority)
    r = entry["current"]/entry["reference_coefficient"]
    return min(math.log(hi/r), max(math.log(lo/r),step))


def constrain_fit_bounds(bounds, authority):
    """Intersect W/S production solver bounds with immutable zonal mobility.

    Domestic structural zeros and unverifiable references are removed from the
    actuator set.  Existing foreign and attraction bounds retain their own
    authority.  The last-line candidate/live guards still verify realization.
    """
    out = dict(bounds)
    if not authority["enabled"]:
        return out, {"status": "DISABLED", "changed": 0, "frozen": 0}
    zones = zone_map(authority["parent_zone_rows"])
    changed, frozen = [], []
    for key in list(out):
        fam, role, z = key
        z = int(z)
        if fam not in ("WORK", "SERVICE") or role != "PROD":
            continue
        if z not in zones:
            raise ValueError("MOBILITYZONE1_FIT_UNKNOWN_ZONE:%s" % z)
        if finite(zones[z].get("NOT_ZAHR"), "NOT_ZAHR") < .5:
            continue
        entry = authority["entries"].get(fam + "|" + str(z))
        if entry is None or entry.get("reference_fp") is None:
            out.pop(key)
            frozen.append({"family": fam, "zone_no": z, "reason": "UNVERIFIED_OR_ZERO_REFERENCE"})
            continue
        lo_ratio, hi_ratio = interval(entry, authority)
        current_ratio = entry["current"] / entry["reference_coefficient"]
        original_lo, original_hi = out[key]
        lower = max(float(original_lo), math.log(lo_ratio / current_ratio))
        upper = min(float(original_hi), math.log(hi_ratio / current_ratio))
        if lower > 0.0 + EPS or upper < 0.0 - EPS:
            raise ValueError("MOBILITYZONE1_FIT_NO_FEASIBLE_DIRECTION:%s:%s" % (fam, z))
        if upper - lower <= EPS:
            out.pop(key)
            frozen.append({"family": fam, "zone_no": z, "reason": "ZERO_FEASIBLE_INTERVAL"})
        else:
            out[key] = (lower, upper)
            if abs(lower-original_lo) > EPS or abs(upper-original_hi) > EPS:
                changed.append({"family": fam, "zone_no": z,
                                "lower_log": lower, "upper_log": upper})
    return out, {"release": RELEASE, "status": "CONSTRAINED",
                 "changed": len(changed), "frozen": len(frozen),
                 "changed_rows": changed, "frozen_rows": frozen,
                 "reference_role": authority["reference_role"]}


def guard_projection(rows, authority):
    """Clip W/S production proposals independently, BEFORE aggregate guard/P-A."""
    import r1_15a2_mobility_guard_v24917 as mg
    if not authority["enabled"]:
        return rows, {"status": "DISABLED"}
    out, changes = copy.deepcopy(list(rows)), []
    zones = zone_map(authority["parent_zone_rows"])
    seen = set()
    for row in out:
        fam, z = row.get("family"), int(row["zone_no"])
        if fam not in SPECS or row.get("role") != "PROD":
            continue
        if z not in zones:
            raise ValueError("MOBILITYZONE1_UNKNOWN_ZONE:%s" % z)
        if finite(zones[z].get("NOT_ZAHR"), "NOT_ZAHR") < .5 or row.get("branch") == "ZAHR":
            continue
        key = fam+"|"+str(z)
        if key in seen:
            raise ValueError("MOBILITYZONE1_DUPLICATE_STEP:"+key)
        seen.add(key)
        s = finite(row.get("log_step",0), "log_step")
        e = authority["entries"].get(key)
        t = bounded_step(e,s,authority) if e is not None else 0.0
        if t != s:
            changes.append({"zone_no":z,"family":fam,"before_log_step":s,"after_log_step":t})
        mg._set_step(row,t)
    return out, {"release":RELEASE,"status":"PROJECTED", "rows_clipped":len(changes),
                 "changes":changes,"unavailable":authority["unavailable"],
                 "out_of_band_parent": authority["out_of_band"],
                 "target_satisfied": authority["target_satisfied"]}


def guard_ls(ls, authority):
    """Project every LONG and SCHOOL production step against its own zone anchor."""
    if not ls or not authority["enabled"]:
        return ls
    out = copy.deepcopy(ls)
    steps, changed = out.get("steps",{}), False
    zones = zone_map(authority["parent_zone_rows"])
    edits = []
    for attr in ("ADD_PROD_L","ADD_PROD_SCH"):
        fam = ATTR_FAMILY[attr]
        items = steps.get(attr,{})
        if not items:
            continue
        clipped = {}
        for raw_z, s in items.items():
            z = int(raw_z); s = finite(s,"ls_step")
            e = authority["entries"].get(fam+"|"+str(z))
            # LSGEN writes a global LONG coefficient to every zone. Freeze
            # unsupported/external zones instead of inventing resident demand.
            clipped[raw_z] = bounded_step(e,s,authority) if e is not None else 0.0
        for z,t in clipped.items():
            if abs(t-float(items[z]))>EPS:
                edits.append({"attr":attr,"zone_no":int(z),"before":items[z],"after":t})
                changed = True
            items[z]=t
    # If optional LS data is unavailable, freeze that family's attraction too.
    for attr,fam in ATT_FAMILY.items():
        if fam in authority["unavailable"]:
            for z,s in steps.get(attr,{}).items():
                if s: changed=True
                steps[attr][z]=0.0
    if changed:
        model=out.get("effect_operator")
        if model:
            import numpy as np
            by={}
            for attr,by_zone in steps.items():
                fam=ATTR_FAMILY.get(attr) or ATT_FAMILY.get(attr)
                role="PROD" if attr in ATTR_FAMILY else "ATT"
                for z,s in by_zone.items(): by[(fam,role,int(z))]=float(s)
            x=np.array([by.get(tuple(k),0.0) for k in model["keys"]])
            delta=np.asarray(model["G"],dtype=float)@x
            if not np.isfinite(delta).all(): raise ValueError("MOBILITYZONE1_INVALID_LS_PREDICTION")
            out["predicted_change"]=delta.tolist()
        else:
            out["predicted_change"]=None
            out["prediction_unavailable_after_guard"]=True
    summary = out.setdefault("summary", {})
    if changed:
        summary["raw_solver_long_zone_steps"] = copy.deepcopy(ls.get("steps", {}).get("ADD_PROD_L", {}))
        summary["raw_solver_linear_ratio_after_ws_and_ls"] = summary.get("linear_ratio_after_ws_and_ls")
        # A solver's ratio cannot be presented as the guarded forecast.
        summary["linear_ratio_after_ws_and_ls"] = None
    summary.pop("long_global_log_step", None)
    summary["long_zone_steps"] = sum(abs(float(v)) > EPS for v in steps.get("ADD_PROD_L", {}).values())
    summary["long_generation_permitted"] = False
    summary["long_search_status"] = "LONG_SEARCH_INCOMPLETE" if summary["long_zone_steps"] == 0 else "PENDING_NATIVE_VERIFICATION"
    summary["school_zones_changed"] = sum(abs(float(v)) > EPS for attr in
        ("ADD_PROD_SCH", "ADD_ATT_SCH") for v in steps.get(attr, {}).values())
    summary["mobilityzone1"] = {"changes": edits, "deferred": authority["unavailable"],
        "prediction_role": "GUARDED_EFFECT_OPERATOR" if changed and out.get("effect_operator")
                           else "UNAVAILABLE" if out.get("prediction_unavailable_after_guard")
                           else "UNCHANGED_SOLVER_PREDICTION"}
    return out


def check_candidate(rows, authority):
    report={"release":RELEASE,"passes":True,"status":"VERIFIED", "violations":[],
            "deferred_families":authority["unavailable"],"checked":0}
    if not authority["enabled"]:
        return dict(report,status="DISABLED")
    zones=zone_map(authority["parent_zone_rows"])
    seen=set()
    for row in rows:
        attr=str(row.get("attr","")).upper();fam=ATTR_FAMILY.get(attr)
        if fam is None:
            fam=ATT_FAMILY.get(attr)
            if fam not in authority["unavailable"]: continue
        z=int(row["zone_no"]);key=fam+"|"+str(z)
        if (attr,z) in seen: raise ValueError("MOBILITYZONE1_DUPLICATE_CANDIDATE:"+key)
        seen.add((attr,z))
        if z not in zones: raise ValueError("MOBILITYZONE1_UNKNOWN_ZONE:"+key)
        if finite(zones[z].get("NOT_ZAHR"),"NOT_ZAHR")<.5: continue
        c=finite(row.get("current"),"current"); p=finite(row.get("proposed"),"proposed")
        e=authority["entries"].get(key)
        reason=None
        if min(c,p)<0: reason="NEGATIVE_COEFFICIENT"
        elif e is None or e["reference_fp"] is None:
            if not close(c,p):reason="UNVERIFIED_OR_ZERO_ZONE_MUTATION"
        elif attr in ATTR_FAMILY:
            report["checked"]+=1
            lo,hi=interval(e,authority)
            if not close(c,e["current"]):reason="STALE_PARENT_COEFFICIENT"
            elif not lo-EPS<=p/e["reference_coefficient"]<=hi+EPS:reason="ZONAL_ENVELOPE"
        if reason: report["violations"].append({"zone_no":z,"family":fam,"reason":reason,"current":c,"proposed":p})
    report["passes"]=not report["violations"]
    if not report["passes"]:report["status"]="REJECT_CANDIDATE"
    elif report["deferred_families"]:report["status"]="PARTIAL_DEFERRED"
    return report


def check_live(authority, rows):
    """Fixed per-group denominators detect production drift, not just ADD_PROD."""
    report={"release":RELEASE,"passes":True,"status":"VERIFIED","violations":[],"rows":[],
            "deferred_families":authority["unavailable"],"reference_role":REFERENCE}
    if not authority["enabled"]: return dict(report,status="DISABLED")
    by=zone_map(rows); old=zone_map(authority["parent_zone_rows"])
    if set(by)!=set(old):raise ValueError("MOBILITYZONE1_LIVE_ZONE_COVERAGE_CHANGED")
    for z in by:
        if finite(by[z].get("NOT_ZAHR"),"mask")!=finite(old[z].get("NOT_ZAHR"),"mask"):
            raise ValueError("MOBILITYZONE1_LIVE_MASK_CHANGED")
    for key,e in authority["entries"].items():
        z=e["zone_no"]; r=by[z];fam=e["family"];attr,ref,fps=SPECS[fam]
        c=finite(r.get(attr),attr);values={a:finite(r.get(a),a) for a in fps}
        bad=[]
        if c<0 or any(v<0 for v in values.values()):bad.append("NEGATIVE_VALUE")
        if e["reference_fp"] is None:
            if not close(c,e["current"]) or any(not close(values[a],e["fp"][a]) for a in fps):
                bad.append("ZERO_PRODUCTION_ZONE_CHANGED")
        else:
            lo,hi=interval(e,authority)
            if not lo-EPS<=c/ref<=hi+EPS:bad.append("COEFFICIENT_ENVELOPE")
            for a in fps:
                base=e["reference_fp"][a]
                expected=base*c/ref
                if not close(values[a],expected):bad.append("FP_REFERENCE_OR_FORMULA_CHANGED:"+a)
                if base>EPS and not lo-EPS<=values[a]/base<=hi+EPS:
                    bad.append("FP_ENVELOPE:"+a)
                elif base<=EPS and values[a]>ATOL:bad.append("ZERO_GROUP_BECAME_POSITIVE:"+a)
        total=math.fsum(values.values());base=e["reference_production"]
        target_lo,target_hi = authority["long_band"] if fam == "LONG" else authority["band"]
        report["rows"].append({"zone_no":z,"family":fam,"production":total,
            "reference_production":base,"ratio":total/base if base and base>EPS else None,
            "in_target_band":bool(base and base>EPS and target_lo-EPS<=total/base<=target_hi+EPS),
            "passes":not bad})
        if bad:report["violations"].append({"zone_no":z,"family":fam,"reasons":bad})
    # Deferred optional families are not "verified". Only unchanged parameters
    # are allowed, and incompleteness is propagated to stationarity logic.
    for fam in authority["unavailable"]:
        for attr in (SPECS[fam][0],)+tuple(a for a,f in ATT_FAMILY.items() if f==fam):
            for z in old:
                if attr in old[z] and (attr not in by[z] or not close(finite(old[z][attr],attr),finite(by[z][attr],attr))):
                    report["violations"].append({"zone_no":z,"family":fam,"reasons":["DEFERRED_FAMILY_PARAMETER_CHANGED"]})
    report["passes"]=not report["violations"]
    report["status"]="REJECT_CANDIDATE" if not report["passes"] else "PARTIAL_DEFERRED" if authority["unavailable"] else "VERIFIED"
    return report


def parent_unchanged(authority, rows):
    """Before first write: raw FP and coefficients must still be the same parent."""
    proof=check_live(authority,rows)
    by=zone_map(rows)
    for e in authority["entries"].values():
        if not close(finite(by[e["zone_no"]].get(e["attr"]),e["attr"]),e["current"]):
            proof["passes"]=False
            proof["violations"].append({"zone_no":e["zone_no"],"family":e["family"],"reasons":["PARENT_CHANGED_BEFORE_WRITE"]})
    return proof
