# -*- coding: utf-8 -*-
"""
R1 / PTV Visum 2026
STEP 12D -- CSD2022 GEH forensic diagnostics for approved 408 CountLocations.

Run after:
  12B8 import -> assignment -> 12C GEH scorer.

This script is conservative:
  * does NOT execute assignment;
  * does NOT modify network, demand, matrices, procedures, or version file;
  * reads exactly 408 approved CountLocations in 920001..920444 and assigned link volumes;
  * writes forensic CSV/JSON outputs beside the opened .ver;
  * best-effort writes only R1_12D_* diagnostic UDAs on CountLocations.

The approved 408 manifest comes from the user-selected CountLocations export.
The 444-count archive is historical only, NOT calibration input.
All approved IDs, observed values, roles and directed physical keys must match
the live model exactly; 127 non-CSD CountLocations are excluded by ID.
"""
from __future__ import print_function

import csv
import hashlib
import json
import math
import os
import re
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPT_ID = "R1_12D_CSD2022_GEH_FORENSIC_408_APPROVED_20261015"
RESERVED_FIRST = 920001
RESERVED_LAST = 920444
EXPECTED_ROWS = 408
EXPECTED_CALIBRATION = 372
EXPECTED_VALIDATION = 36
WRITE_DIAGNOSTIC_UDAS = True

FAMILIES = ("CF", "CL", "CS", "CS_noT", "CW", "CW_noT")
LAYERS = ("EXOG_EE", "NATIVE")
PASSENGER_DSEGS = tuple("%s_%s" % (layer, fam) for layer in LAYERS for fam in FAMILIES)
FREIGHT_DSEGS = ("LNV", "NV")
MODEL_SCOPE = "12PASS_DSEG_DIRECTED_AP_LNV_NV_EXCLUDED"

# Approved, immutable exported CountLocations: loaded from the CSV copied alongside this helper.
AUTHORITY_CSV_NAME = "R1_CSD2022_COUNTLOCATION_AUTHORITY_408.csv"
AUTHORITY_SHA256 = "7d455781f3b6ed10d4c7f7f5177c4d101222d72c07ce2292f9536207ed74aeb1"

UDA_DEFS = [
    ("R1_12D_DIAG_CLASS", "R1 12D Diag Class", "R1 12D diagnostic class", 5, None),
    ("R1_12D_SEVERITY", "R1 12D Severity", "R1 12D diagnostic severity", 5, None),
    ("R1_12D_ACTION_RANK", "R1 12D Action Rank", "R1 12D action queue rank", 2, 0),
    ("R1_12D_PRIMARY_FAMILY", "R1 12D Primary Family", "Dominant model family", 5, None),
    ("R1_12D_LAYER_MIX", "R1 12D Layer Mix", "EXOG/NATIVE layer mix category", 5, None),
    ("R1_12D_PAIR_RATIO", "R1 12D Pair Ratio", "Combined directional-pair model/obs ratio", 2, 6),
    ("R1_12D_FREIGHT_SHARE", "R1 12D Freight Share", "Excluded LNV/NV share of total PRT", 2, 6),
]


def now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_name(s):
    return re.sub(r"[^0-9A-Za-z_\-.]+", "_", str(s))


def as_float(v, default=0.0):
    try:
        if v is None or str(v).strip() == "":
            return default
        x = float(str(v).replace(",", "."))
        if not math.isfinite(x):
            return default
        return x
    except Exception:
        return default


def as_int(v, default=None):
    try:
        if v is None or str(v).strip() == "":
            return default
        return int(round(float(str(v).replace(",", "."))))
    except Exception:
        return default


def text(v, default=""):
    if v is None:
        return default
    return str(v)


def collection_items(coll):
    errors = []
    try:
        value = getattr(coll, "GetAll")
        if callable(value):
            value = value()
        if value is not None:
            return tuple(value)
    except Exception as exc:
        errors.append("GetAll: %s" % exc)
    try:
        return tuple(coll)
    except Exception as exc:
        errors.append("iteration: %s" % exc)
    raise RuntimeError("Could not enumerate COM collection (%s)" % " | ".join(errors))


def att(obj, names, default=None):
    if isinstance(names, str):
        names = [names]
    for name in names:
        try:
            return obj.AttValue(name)
        except Exception:
            pass
    return default


def set_att(obj, names, value, required=False):
    if isinstance(names, str):
        names = [names]
    errors = []
    for name in names:
        try:
            obj.SetAttValue(name, value)
            return name
        except Exception as exc:
            errors.append("%s: %s" % (name, exc))
    if required:
        raise RuntimeError("Could not set %r=%r (%s)" % (names, value, " | ".join(errors)))
    return None


def attr_exists(coll, attr_id):
    try:
        return bool(coll.AttrExists(attr_id))
    except Exception:
        try:
            items = collection_items(coll)
            if items:
                items[0].AttValue(attr_id)
                return True
        except Exception:
            return False
    return False


def ensure_countlocation_udas(v):
    rows = []
    coll = v.Net.CountLocations
    for attr_id, short_name, long_name, value_type, decimals in UDA_DEFS:
        if attr_exists(coll, attr_id):
            rows.append({"attribute": attr_id, "action": "EXISTING", "status": "OK"})
            continue
        try:
            if decimals is None:
                coll.AddUserDefinedAttribute(attr_id, short_name, long_name, value_type)
            else:
                coll.AddUserDefinedAttribute(attr_id, short_name, long_name, value_type, decimals)
            rows.append({"attribute": attr_id, "action": "CREATED", "status": "OK"})
        except Exception as exc:
            rows.append({"attribute": attr_id, "action": "CREATE_FAILED", "status": str(exc)})
    return rows


def get_visum():
    v = globals().get("Visum") or globals().get("COM")
    if v is not None:
        return v
    try:
        import win32com.client  # type: ignore
        for progid in ("Visum.Visum.260", "Visum.Visum.250", "Visum.Visum"):
            try:
                return win32com.client.GetActiveObject(progid)
            except Exception:
                pass
    except Exception:
        pass
    raise RuntimeError("Visum/COM global object is not available. Run inside PTV Visum.")


def version_project_dir(v):
    try:
        p = str(v.GetPath(2) or "").strip()
        if p:
            q = Path(p)
            if q.suffix.lower() == ".ver":
                q = q.parent
            return q
    except Exception:
        pass
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path.cwd()


def write_rows(path, headers, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in headers})


def write_kv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["METRIC", "VALUE"])
        for k, v in rows:
            w.writerow([k, v])


def geh_value(model, observed):
    model = max(0.0, float(model))
    observed = max(0.0, float(observed))
    denom = model + observed
    if denom <= 0:
        return 0.0
    return math.sqrt(2.0 * (model - observed) ** 2 / denom)


def severity(g):
    if g < 5:
        return "OK_0_5"
    if g < 10:
        return "OK_5_10"
    if g < 20:
        return "MEDIUM_10_20"
    if g < 30:
        return "HIGH_20_30"
    return "CRITICAL_GE30"


def percentiles(vals, p):
    xs = sorted([float(v) for v in vals if v is not None and math.isfinite(float(v))])
    if not xs:
        return 0.0
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * (p / 100.0)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def load_manifest():
    authority_path = Path(__file__).resolve().parent / AUTHORITY_CSV_NAME
    if not authority_path.is_file():
        raise RuntimeError("CSD408 approved authority CSV missing beside helper: %s" % authority_path)
    digest = hashlib.sha256(authority_path.read_bytes()).hexdigest()
    if digest != AUTHORITY_SHA256:
        raise RuntimeError("CSD408 authority SHA256 mismatch: %s" % digest)
    with authority_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        no = as_int(r.get("countlocation_no"))
        if no is None or no in out or not RESERVED_FIRST <= no <= RESERVED_LAST:
            raise RuntimeError("CSD408 invalid or duplicate authority number: %r" % no)
        if r.get("role") not in ("CALIBRATION", "VALIDATION"):
            raise RuntimeError("CSD408 invalid role: %s" % no)
        observed = as_float(r.get("observed_passenger_cars_O"), None)
        if observed is None or not math.isfinite(observed) or observed < 0:
            raise RuntimeError("CSD408 invalid observed intensity: %s" % no)
        if r.get("vehicle_scope") != "PERSONAL_ALL" or r.get("period_basis") != "RPDI_2022":
            raise RuntimeError("CSD408 observed scope mismatch: %s" % no)
        out[no] = r
    role_counts = {role: sum(1 for r in out.values() if r.get("role") == role)
                   for role in ("CALIBRATION", "VALIDATION")}
    if len(out) != EXPECTED_ROWS or role_counts != {"CALIBRATION": EXPECTED_CALIBRATION,
                                                      "VALIDATION": EXPECTED_VALIDATION}:
        raise RuntimeError("CSD408 approved authority count/role mismatch: %s" % role_counts)
    if len(set(r["profile_id"] for r in out.values())) != EXPECTED_ROWS:
        raise RuntimeError("CSD408 duplicate profile_id in manifest")
    return out


def _live_required(cl, att_name, number):
    try:
        v = cl.AttValue(att_name)
    except Exception as e:
        raise RuntimeError("CSD408 missing live attribute %s for %s: %r" % (att_name, number, e))
    if v is None or str(v).strip() == "":
        raise RuntimeError("CSD408 blank live attribute %s for %s" % (att_name, number))
    return v


def verify_live_authority(manifest, cl_objs, link_idx):
    live_nos = [as_int(att(cl, ["NO", "No"])) for cl in cl_objs]
    approved = set(manifest)
    if set(live_nos) != approved or len(live_nos) != len(approved):
        raise RuntimeError("CSD408 roster differs: missing=%s unexpected=%s duplicates=%s" % (
            sorted(approved - set(live_nos)), sorted(set(live_nos) - approved),
            len(live_nos) - len(set(live_nos))))
    for cl in cl_objs:
        no = as_int(att(cl, ["NO", "No"]))
        r = manifest[no]
        for live_name, reference_name in (("CODE", "countlocation_code"),
                                          ("R1_OBS_ID", "profile_id"),
                                          ("R1_ROLE", "role"),
                                          ("R1_OBS_SCOPE", "vehicle_scope"),
                                          ("R1_OBS_BASIS", "period_basis")):
            got = str(_live_required(cl, live_name, no)).strip()
            if got != str(r[reference_name]).strip():
                raise RuntimeError("CSD408 live mismatch %s for %s: %r != %r" % (
                    live_name, no, got, r[reference_name]))
        for live_name, reference_name in (("LINKNO", "current_link_no"),
                                          ("FROMNODENO", "current_from_node_no"),
                                          ("TONODENO", "current_to_node_no")):
            got = as_int(_live_required(cl, live_name, no))
            if got != as_int(r[reference_name]):
                raise RuntimeError("CSD408 physical directed mapping changed %s for %s: %s != %s" % (
                    live_name, no, got, r[reference_name]))
        key = tuple(as_int(r[n]) for n in ("current_link_no", "current_from_node_no", "current_to_node_no"))
        if key not in link_idx:
            raise RuntimeError("CSD408 physical directed link unavailable: %s at CountLocation %s" % (key, no))
        for live_attr in ("R1_OBS_RPDI", "R1_OBS_VALUE"):
            got = as_float(_live_required(cl, live_attr, no), None)
            expected = as_float(r["observed_passenger_cars_O"], None)
            if got is None or abs(got - expected) > 1e-7:
                raise RuntimeError("CSD408 observed intensity changed %s for %s: %r != %r" % (
                    live_attr, no, got, expected))
        active = as_int(_live_required(cl, "R1_ACTIVE", no))
        if active != 1:
            raise RuntimeError("CSD408 approved CountLocation not active: %s" % no)
        weight = as_float(_live_required(cl, "R1_WEIGHT", no), None)
        if weight is None or abs(weight - float(r["live_weight"])) > 1e-8:
            raise RuntimeError("CSD408 live profile weight changed at %s" % no)
    return {"status": "PASS_EXACT_APPROVED_ROSTER_AND_LIVE_VALUES",
            "authority_csv_sha256": AUTHORITY_SHA256,
            "rows": len(live_nos), "calibration": EXPECTED_CALIBRATION,
            "validation": EXPECTED_VALIDATION}


def read_link_index(v, probe_rows):
    idx = {}
    type_name_map = {}
    try:
        for lt in collection_items(v.Net.LinkTypes):
            lt_no = as_int(att(lt, ["NO", "No"]))
            if lt_no is not None:
                type_name_map[lt_no] = text(att(lt, ["NAME", "Name"], ""))
    except Exception:
        type_name_map = {}
    items = collection_items(v.Net.Links)
    dseg_attrs = ["VOLVEH_DSEG(%s,AP)" % ds for ds in PASSENGER_DSEGS]
    freight_attrs = ["VOLVEH_DSEG(%s,AP)" % ds for ds in FREIGHT_DSEGS]
    agg_attrs = ["VOLVEH_TSYS(C,AP)", "VOLVEH_TSYS(C_noT,AP)", "VOLVEHPRT(AP)"]
    # Probe attributes on first link only; all reads later still use safe default.
    if items:
        sample = items[0]
        for a in dseg_attrs:
            status = "OK" if att(sample, a, None) is not None else "MISSING_OR_BLANK_ON_SAMPLE"
            probe_rows.append({"attribute": a, "purpose": "GEH_INCLUDED_PASSENGER", "status": status})
        for a in freight_attrs:
            status = "OK" if att(sample, a, None) is not None else "MISSING_OR_BLANK_ON_SAMPLE"
            probe_rows.append({"attribute": a, "purpose": "QA_FREIGHT_EXCLUDED", "status": status})
        for a in agg_attrs:
            status = "OK" if att(sample, a, None) is not None else "MISSING_OR_BLANK_ON_SAMPLE"
            probe_rows.append({"attribute": a, "purpose": "QA_AGGREGATE", "status": status})
    for obj in items:
        no = as_int(att(obj, ["NO", "No"]))
        fr = as_int(att(obj, ["FROMNODENO", "FromNodeNo"]))
        to = as_int(att(obj, ["TONODENO", "ToNodeNo"]))
        if no is None or fr is None or to is None:
            continue
        row = {
            "link_no": no,
            "from_node_no": fr,
            "to_node_no": to,
            "type_no": as_int(att(obj, ["TYPENO", "TypeNo"])),
            "type_name": "",
            "road_no_link": text(att(obj, ["ROADNO", "RoadNo", "ROUTENO", "RouteNo", "CODE", "Code"], "")),
            "tsysset_link": text(att(obj, ["TSYSSET", "TSysSet"], "")),
            "length": as_float(att(obj, ["LENGTH", "Length"], 0.0)),
            "num_lanes": as_int(att(obj, ["NUMLANES", "NumLanes"], None), None),
            "cap_prt": as_float(att(obj, ["CAPPRT", "CapPrT"], 0.0)),
            "v0_prt": as_float(att(obj, ["V0PRT", "V0PrT"], 0.0)),
            "vdf_no": as_int(att(obj, ["VDFNO", "VdfNo"], None), None),
        }
        if row.get("type_no") in type_name_map:
            row["type_name"] = type_name_map[row.get("type_no")]
        else:
            row["type_name"] = text(att(obj, ["TYPENAME", "TypeName"], ""))
        for ds in PASSENGER_DSEGS:
            row["model_%s" % ds] = as_float(att(obj, "VOLVEH_DSEG(%s,AP)" % ds, 0.0))
        for ds in FREIGHT_DSEGS:
            row["qa_freight_%s_excluded" % ds] = as_float(att(obj, "VOLVEH_DSEG(%s,AP)" % ds, 0.0))
        row["qa_tsys_c"] = as_float(att(obj, ["VOLVEH_TSYS(C,AP)", "VolVehTSys(C,AP)"], 0.0))
        row["qa_tsys_cnot"] = as_float(att(obj, ["VOLVEH_TSYS(C_noT,AP)", "VOLVEH_TSYS(C_NOT,AP)"], 0.0))
        row["qa_prt_total"] = as_float(att(obj, ["VOLVEHPRT(AP)", "VolVehPrT(AP)", "VOLVEHPRT", "VolVehPrT"], 0.0))
        idx[(no, fr, to)] = row
    return idx


def read_countlocations(v):
    rows = []
    for obj in collection_items(v.Net.CountLocations):
        no = as_int(att(obj, ["NO", "No"]))
        if no is None or no < RESERVED_FIRST or no > RESERVED_LAST:
            continue
        rows.append(obj)
    rows.sort(key=lambda o: as_int(att(o, ["NO", "No"]), 0))
    return rows


def simple_summary(rows):
    n = len(rows)
    obs = sum(r.get("observed", 0.0) for r in rows)
    mod = sum(r.get("model", 0.0) for r in rows)
    diffs = [r.get("diff", 0.0) for r in rows]
    absdiffs = [abs(d) for d in diffs]
    gehs = [r.get("geh", 0.0) for r in rows]
    return {
        "n": n,
        "obs_sum": obs,
        "model_sum": mod,
        "model_obs_ratio": (mod / obs if obs else ""),
        "bias": mod - obs,
        "bias_percent": (100.0 * (mod - obs) / obs if obs else ""),
        "mae": (sum(absdiffs) / n if n else ""),
        "rmse": (math.sqrt(sum(d * d for d in diffs) / n) if n else ""),
        "geh_mean": (sum(gehs) / n if n else ""),
        "geh_median": percentiles(gehs, 50),
        "geh_p85": percentiles(gehs, 85),
        "geh_p90": percentiles(gehs, 90),
        "geh_p95": percentiles(gehs, 95),
        "geh_max": (max(gehs) if gehs else 0.0),
        "geh_lt5": sum(1 for r in rows if r.get("geh", 0.0) < 5),
        "geh_lt10": sum(1 for r in rows if r.get("geh", 0.0) < 10),
        "geh_ge30": sum(1 for r in rows if r.get("geh", 0.0) >= 30),
        "underload_n": sum(1 for r in rows if r.get("observed", 0.0) > 0 and r.get("ratio", -1) < 0.8),
        "severe_underload_n": sum(1 for r in rows if r.get("observed", 0.0) > 0 and r.get("ratio", -1) < 0.5),
        "overload_n": sum(1 for r in rows if r.get("observed", 0.0) > 0 and r.get("ratio", -1) > 1.2),
        "exog_share_model_weighted": (sum(r.get("layer_EXOG_EE", 0.0) for r in rows) / mod if mod else ""),
        "freight_share_prt_weighted": (sum(r.get("freight_total_excl", 0.0) for r in rows) / sum(r.get("qa_prt_total", 0.0) for r in rows) if sum(r.get("qa_prt_total", 0.0) for r in rows) else ""),
    }


def group_summary(rows, key, group_label=None):
    groups = {}
    for r in rows:
        val = r.get(key, "")
        if val is None or str(val).strip() == "":
            val = "<missing>"
        groups.setdefault(str(val), []).append(r)
    out = []
    for val, gr in groups.items():
        s = simple_summary(gr)
        s[group_label or key] = val
        out.append(s)
    out.sort(key=lambda r: as_float(r.get("obs_sum"), 0.0), reverse=True)
    return out


def classify(r):
    obs = r.get("observed", 0.0)
    mod = r.get("model", 0.0)
    ratio = r.get("ratio", -1.0)
    g = r.get("geh", 0.0)
    prt_ratio = r.get("prt_obs_ratio", -1.0)
    pair_ratio = r.get("pair_ratio", -1.0)
    pair_n = r.get("pair_n", 0)
    if obs <= 1e-9:
        if mod > 100:
            return "OBS_ZERO_MODEL_POSITIVE"
        return "OBS_ZERO_OR_INACTIVE"
    if g < 10:
        return "ACCEPTABLE_GEHLT10"
    if pair_n >= 2 and 0.8 <= pair_ratio <= 1.2 and g >= 20:
        return "DIRECTIONAL_SPLIT_OR_MAPPING"
    if ratio < 0.5:
        if prt_ratio >= 0.8 and r.get("freight_share_prt", 0.0) >= 0.2:
            return "PASSENGER_SCOPE_OR_FREIGHT_EXCLUSION"
        return "SYSTEMATIC_UNDERLOAD_DEMAND_OR_ROUTE"
    if ratio < 0.8:
        return "MODERATE_UNDERLOAD"
    if ratio > 1.5:
        return "OVERROUTE_OR_OBS_SCOPE"
    if ratio > 1.2:
        return "MODERATE_OVERLOAD"
    return "HIGH_GEH_SHAPE_OR_LOCAL"


def build_detail_rows(v, manifest, link_idx, cl_objs):
    rows = []
    for cl in cl_objs:
        no = as_int(att(cl, ["NO", "No"]))
        meta = manifest.get(no, {})
        link_no = as_int(att(cl, ["LINKNO", "LinkNo"], meta.get("current_link_no")))
        fr = as_int(att(cl, ["FROMNODENO", "FromNodeNo"], meta.get("current_from_node_no")))
        to = as_int(att(cl, ["TONODENO", "ToNodeNo"], meta.get("current_to_node_no")))
        link = link_idx.get((link_no, fr, to), {})
        observed = as_float(att(cl, ["R1_OBS_RPDI", "R1_OBS_VALUE"], meta.get("observed_passenger_cars_O", 0.0)), 0.0)
        row = {
            "countlocation_no": no,
            "code": text(att(cl, ["CODE", "Code"], meta.get("countlocation_code", ""))),
            "name": text(att(cl, ["NAME", "Name"], "")),
            "obs_id": text(att(cl, ["R1_OBS_ID"], meta.get("profile_id", ""))),
            "role": text(att(cl, ["R1_ROLE"], meta.get("role", ""))),
            "active": as_int(att(cl, ["R1_ACTIVE"], 1), 1),
            "link_no": link_no,
            "from_node_no": fr,
            "to_node_no": to,
            "relpos": as_float(att(cl, ["RELPOS", "RelPos"], meta.get("relpos", 0.5)), 0.5),
            "observed": observed,
            "cisloSU": meta.get("cisloSU", ""),
            "csd_direction": meta.get("csd_direction", ""),
            "Kraj": meta.get("Kraj", ""),
            "Okres": meta.get("Okres", ""),
            "triedaPK": meta.get("triedaPK", ""),
            "cisloPK": meta.get("cisloPK", ""),
            "smerPK": meta.get("smerPK", ""),
            "vehicle_scope": meta.get("vehicle_scope", ""),
            "period_basis": meta.get("period_basis", ""),
            "evidence_tier": meta.get("evidence_tier", ""),
            "mapping_selection_basis": meta.get("mapping_selection_basis", ""),
            "mapping_qa": meta.get("mapping_qa", ""),
            "qa_reasons": meta.get("qa_reasons", ""),
            "type_no": link.get("type_no", ""),
            "type_name": link.get("type_name", ""),
            "road_no_link": link.get("road_no_link", ""),
            "tsysset_link": link.get("tsysset_link", text(att(cl, ["TSYSSET", "TSysSet"], ""))),
            "length": link.get("length", ""),
            "num_lanes": link.get("num_lanes", ""),
            "cap_prt": link.get("cap_prt", ""),
            "v0_prt": link.get("v0_prt", ""),
            "vdf_no": link.get("vdf_no", ""),
        }
        model = 0.0
        layer_tot = {layer: 0.0 for layer in LAYERS}
        family_tot = {fam: 0.0 for fam in FAMILIES}
        for ds in PASSENGER_DSEGS:
            val = link.get("model_%s" % ds, 0.0)
            row["model_%s" % ds] = val
            model += val
            parts = ds.split("_", 2)
            if ds.startswith("EXOG_EE_"):
                layer = "EXOG_EE"
                fam = ds.replace("EXOG_EE_", "")
            else:
                layer = "NATIVE"
                fam = ds.replace("NATIVE_", "")
            layer_tot[layer] += val
            family_tot[fam] += val
        row["model"] = model
        row["diff"] = model - observed
        row["abs_diff"] = abs(model - observed)
        row["ratio"] = (model / observed if observed > 0 else -1.0)
        row["geh"] = geh_value(model, observed)
        for layer in LAYERS:
            row["layer_%s" % layer] = layer_tot[layer]
        for fam in FAMILIES:
            row["family_%s" % fam] = family_tot[fam]
        row["qa_freight_LNV_excluded"] = link.get("qa_freight_LNV_excluded", 0.0)
        row["qa_freight_NV_excluded"] = link.get("qa_freight_NV_excluded", 0.0)
        row["freight_total_excl"] = row["qa_freight_LNV_excluded"] + row["qa_freight_NV_excluded"]
        row["qa_tsys_c"] = link.get("qa_tsys_c", 0.0)
        row["qa_tsys_cnot"] = link.get("qa_tsys_cnot", 0.0)
        row["qa_tsys_c_plus_cnot"] = row["qa_tsys_c"] + row["qa_tsys_cnot"]
        row["qa_model_minus_tsys_c_plus_cnot"] = model - row["qa_tsys_c_plus_cnot"]
        row["qa_prt_total"] = link.get("qa_prt_total", 0.0)
        row["freight_share_prt"] = (row["freight_total_excl"] / row["qa_prt_total"] if row["qa_prt_total"] > 0 else 0.0)
        row["prt_obs_ratio"] = (row["qa_prt_total"] / observed if observed > 0 else -1.0)
        row["exog_share_model"] = (row["layer_EXOG_EE"] / model if model > 0 else 0.0)
        row["native_share_model"] = (row["layer_NATIVE"] / model if model > 0 else 0.0)
        row["primary_layer"] = "NONE" if model <= 0 else ("EXOG_EE" if row["layer_EXOG_EE"] >= row["layer_NATIVE"] else "NATIVE")
        row["primary_family"] = "NONE"
        if model > 0:
            row["primary_family"] = max(FAMILIES, key=lambda fam: family_tot[fam])
        if model <= 0:
            row["layer_mix"] = "NO_MODEL"
        elif row["exog_share_model"] >= 0.60:
            row["layer_mix"] = "EXOG_DOMINANT"
        elif row["exog_share_model"] <= 0.20:
            row["layer_mix"] = "NATIVE_DOMINANT"
        else:
            row["layer_mix"] = "MIXED"
        row["pair_key"] = "%s|%s" % (row.get("cisloSU", ""), row.get("cisloPK", ""))
        row["diag_severity"] = severity(row["geh"])
        rows.append(row)
    return rows


def add_pair_and_diag(rows):
    pair = {}
    for r in rows:
        k = r["pair_key"]
        p = pair.setdefault(k, {"pair_key": k, "pair_n": 0, "pair_obs_sum": 0.0, "pair_model_sum": 0.0, "pair_absdiff_sum": 0.0, "pair_max_geh": 0.0})
        p["pair_n"] += 1
        p["pair_obs_sum"] += r["observed"]
        p["pair_model_sum"] += r["model"]
        p["pair_absdiff_sum"] += r["abs_diff"]
        p["pair_max_geh"] = max(p["pair_max_geh"], r["geh"])
    pair_rows = []
    for p in pair.values():
        p["pair_ratio"] = (p["pair_model_sum"] / p["pair_obs_sum"] if p["pair_obs_sum"] > 0 else -1.0)
        pair_rows.append(p)
    pair_rows.sort(key=lambda p: p["pair_absdiff_sum"], reverse=True)
    pair_by_key = {p["pair_key"]: p for p in pair_rows}
    for r in rows:
        p = pair_by_key[r["pair_key"]]
        r.update(p)
        r["diag_class"] = classify(r)
        r["action_priority_score"] = r["geh"] * math.log1p(max(0.0, r["observed"])) / 10.0 + r["abs_diff"] / 1000.0
    action = sorted(rows, key=lambda r: r["action_priority_score"], reverse=True)
    for i, r in enumerate(action, start=1):
        r["action_rank"] = i
    return pair_rows, action


def write_outputs(outdir, rows, pair_rows, action_rows, probe_rows, uda_rows):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    detail_headers = [
        "countlocation_no","code","name","obs_id","role","active","cisloSU","csd_direction","Kraj","Okres","triedaPK","cisloPK","smerPK","vehicle_scope","period_basis",
        "link_no","from_node_no","to_node_no","relpos","type_no","type_name","road_no_link","tsysset_link","length","num_lanes","cap_prt","v0_prt","vdf_no",
        "observed","model","diff","abs_diff","ratio","geh","diag_severity","diag_class","action_rank","action_priority_score",
        "pair_key","pair_n","pair_obs_sum","pair_model_sum","pair_ratio","pair_absdiff_sum","pair_max_geh",
        "primary_layer","primary_family","layer_mix","exog_share_model","native_share_model","freight_total_excl","freight_share_prt","prt_obs_ratio",
    ]
    for ds in PASSENGER_DSEGS:
        detail_headers.append("model_%s" % ds)
    for layer in LAYERS:
        detail_headers.append("layer_%s" % layer)
    for fam in FAMILIES:
        detail_headers.append("family_%s" % fam)
    detail_headers += ["qa_freight_LNV_excluded","qa_freight_NV_excluded","qa_tsys_c","qa_tsys_cnot","qa_tsys_c_plus_cnot","qa_model_minus_tsys_c_plus_cnot","qa_prt_total","evidence_tier","mapping_selection_basis","mapping_qa","qa_reasons"]
    write_rows(outdir / "01_DETAIL_408_FORENSIC.csv", detail_headers, rows)
    summ = simple_summary(rows)
    kv = [("script_id", SCRIPT_ID), ("timestamp", now_text()), ("status", "PASS"), ("countlocations", len(rows))]
    for k in ["n","obs_sum","model_sum","model_obs_ratio","bias","bias_percent","mae","rmse","geh_mean","geh_median","geh_p85","geh_p90","geh_p95","geh_max","geh_lt5","geh_lt10","geh_ge30","underload_n","severe_underload_n","overload_n","exog_share_model_weighted","freight_share_prt_weighted"]:
        kv.append((k, summ.get(k, "")))
    write_kv(outdir / "00_EXECUTIVE_SUMMARY.csv", kv)
    group_specs = [
        ("role", "02_BY_ROLE.csv"),
        ("triedaPK", "03_BY_ROAD_CLASS.csv"),
        ("cisloPK", "04_BY_ROAD_NO.csv"),
        ("Kraj", "05_BY_KRAJ.csv"),
        ("Okres", "06_BY_OKRES.csv"),
        ("type_name", "07_BY_LINK_TYPE.csv"),
        ("diag_class", "08_BY_DIAG_CLASS.csv"),
        ("primary_family", "09_BY_PRIMARY_FAMILY.csv"),
        ("layer_mix", "10_BY_LAYER_MIX.csv"),
    ]
    group_headers = ["group","n","obs_sum","model_sum","model_obs_ratio","bias","bias_percent","mae","rmse","geh_mean","geh_median","geh_p85","geh_p90","geh_p95","geh_max","geh_lt5","geh_lt10","geh_ge30","underload_n","severe_underload_n","overload_n","exog_share_model_weighted","freight_share_prt_weighted"]
    for key, fname in group_specs:
        gs = group_summary(rows, key, "group")
        write_rows(outdir / fname, group_headers, gs)
    write_rows(outdir / "11_TOP_UNDERLOAD_75.csv", detail_headers, sorted(rows, key=lambda r: r["diff"])[:75])
    write_rows(outdir / "12_TOP_OVERLOAD_50.csv", detail_headers, sorted(rows, key=lambda r: r["diff"], reverse=True)[:50])
    write_rows(outdir / "13_ZERO_OBS_MODEL_POSITIVE.csv", detail_headers, [r for r in sorted(rows, key=lambda r: r["model"], reverse=True) if r["observed"] <= 0 and r["model"] > 100])
    pair_headers = ["pair_key","pair_n","pair_obs_sum","pair_model_sum","pair_ratio","pair_absdiff_sum","pair_max_geh"]
    write_rows(outdir / "14_PAIR_DIRECTION_BALANCE.csv", pair_headers, pair_rows)
    write_rows(outdir / "15_ACTION_QUEUE_TOP120.csv", detail_headers, action_rows[:120])
    write_rows(outdir / "16_ASSIGNMENT_ATTRIBUTE_PROBE.csv", ["attribute","purpose","status"], probe_rows)
    write_rows(outdir / "17_UDA_STATUS.csv", ["attribute","action","status"], uda_rows)
    summary_json = {
        "script_id": SCRIPT_ID,
        "timestamp": now_text(),
        "status": "PASS",
        "countlocations": len(rows),
        "summary": summ,
        "diag_class_counts": {},
        "model_scope": MODEL_SCOPE,
        "assignment_executed_by_script": False,
        "version_saved": False,
    }
    for r in rows:
        summary_json["diag_class_counts"][r["diag_class"]] = summary_json["diag_class_counts"].get(r["diag_class"], 0) + 1
    (outdir / "09_SUMMARY.json").write_text(json.dumps(summary_json, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "18_NEXT_STEPS.txt").write_text(
        "R1 STEP 12D GEH forensic completed.\n\n"
        "Use 08_BY_DIAG_CLASS and 15_ACTION_QUEUE_TOP120 to separate systematic demand/route underload from directional/mapping/scope issues.\n"
        "High-priority next checks: top systematic underload by road number and link type; one official observed=0 row with model positive; any pair with near-ok pair ratio but bad directional split.\n"
        "No assignment was run and .ver was not saved by this script.\n",
        encoding="utf-8")


def write_udas(rows, cl_objs):
    by_no = {as_int(att(o, ["NO", "No"]), None): o for o in cl_objs}
    for r in rows:
        obj = by_no.get(r["countlocation_no"])
        if obj is None:
            continue
        set_att(obj, "R1_12D_DIAG_CLASS", r["diag_class"], False)
        set_att(obj, "R1_12D_SEVERITY", r["diag_severity"], False)
        set_att(obj, "R1_12D_ACTION_RANK", r["action_rank"], False)
        set_att(obj, "R1_12D_PRIMARY_FAMILY", r["primary_family"], False)
        set_att(obj, "R1_12D_LAYER_MIX", r["layer_mix"], False)
        set_att(obj, "R1_12D_PAIR_RATIO", r["pair_ratio"], False)
        set_att(obj, "R1_12D_FREIGHT_SHARE", r["freight_share_prt"], False)


def main():
    stamp = now_stamp()
    v = get_visum()
    project_dir = version_project_dir(v)
    root = project_dir / "R1_12D_CSD2022_GEH_FORENSIC"
    outdir = root / ("R1_12D_%s" % stamp)
    outdir.mkdir(parents=True, exist_ok=True)
    log_file = outdir / "12d_geh_forensic.log"
    def log(msg):
        with log_file.open("a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (now_text(), msg))
    log("START %s" % SCRIPT_ID)
    manifest = load_manifest()
    probe_rows = []
    link_idx = read_link_index(v, probe_rows)
    cl_objs = read_countlocations(v)
    authority_qa = verify_live_authority(manifest, cl_objs, link_idx)
    uda_rows = []
    if WRITE_DIAGNOSTIC_UDAS:
        uda_rows = ensure_countlocation_udas(v)
    rows = build_detail_rows(v, manifest, link_idx, cl_objs)
    pair_rows, action_rows = add_pair_and_diag(rows)
    if WRITE_DIAGNOSTIC_UDAS:
        write_udas(rows, cl_objs)
    write_outputs(outdir, rows, pair_rows, action_rows, probe_rows, uda_rows)
    (outdir / "19_CSD408_AUTHORITY_CHECK.json").write_text(json.dumps(authority_qa, ensure_ascii=False, indent=2), encoding="utf-8")
    # Package latest output directory for sharing.
    zip_path = root / "R1_12D_CSD2022_GEH_FORENSIC_LATEST.zip"
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(outdir.glob("*")):
            z.write(str(p), p.name)
    (outdir / "12d_PASS.txt").write_text(
        "R1 STEP 12D GEH forensic PASS\ncountlocations=%d\nassignment_executed_by_script=false\nversion_saved=false\noutput_dir=%s\n" % (len(rows), str(outdir)),
        encoding="utf-8")
    log("PASS countlocations=%d output=%s" % (len(rows), str(outdir)))

try:
    main()
except Exception:
    tb = traceback.format_exc()
    try:
        err_root = Path(__file__).resolve().parent
        (err_root / "ERROR_12D_GEH_FORENSIC.txt").write_text(tb, encoding="utf-8")
    except Exception:
        pass
    raise
