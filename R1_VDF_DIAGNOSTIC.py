# -*- coding: utf-8 -*-
"""R1 VDF diagnostic (READ-ONLY) - BPR functions vs. counts per road category.

Run in Visum on the current calibration state (e.g. ACCEPTED_A_0005_*.ver, assignment
results present): Scripts -> Run script file -> R1_VDF_DIAGNOSTIC.py

Nothing is written into the model.  Output next to the .ver (else next to this script,
else Documents):  R1_VDF_DIAGNOSTIC\\<timestamp>\\
  00_STATUS.txt               summary per VDF / link type
  01_PROFILES_VDF.csv         every counted profile: link type, VDF (a, b, c), capacity,
                              v0, t0, tcur, tcur/t0, v/c, model C, observed, GEH
  02_VDF_CLASS_SUMMARY.csv    per VDF: profiles, mean model/obs, over/under counts,
                              mean v/c on counted links, network km, km with v/c > 0.9/1.0/1.2
  03_LINKTYPE_SUMMARY.csv     the same per link type
"""
from __future__ import annotations

import csv
import datetime
import math
import os
import sys
from pathlib import Path

SHOW_MESSAGE_BOX = True
# BPR in Visum: tcur = t0 * (1 + a * (q / (c * cap)) ^ b)   (a = BPR_A, b = BPR_B, c = capacity factor)
VDF = {  # from the procedure XML 2026-10-16 (VDF_REGISTRY.csv): no -> (name, a, b, c)
    1: ("default", 1.0, 2.0, 1.0),
    2: ("dialnice", 1.0, 5.2, 1.45),
    3: ("traditional", 0.15, 4.0, 1.0),
    4: ("I. triedy", 1.05, 5.0, 1.2),
    5: ("rychla II.", 1.1, 5.0, 1.1),
    6: ("pomalsia II.", 1.05, 5.0, 1.05),
    7: ("I. - 3/4 pruh", 0.35, 3.5, 1.0),
    8: ("dialnica - intrazonal", 0.5, 5.0, 1.2),
    9: ("D-6", 0.85, 6.0, 1.35),
    10: ("D-2", 0.2, 5.2, 1.05),
    11: ("I.trieda", 0.8, 3.0, 1.4),
    12: ("I.trieda-dense", 0.75, 2.0, 1.35),
}
TYPE_TO_VDF = {1: 9, 2: 2, 3: 8, 4: 3, 5: 1, 6: 2, 8: 7, 9: 7, 10: 11, 11: 11, 12: 11, 13: 12,
               18: 12, 19: 12, 20: 7, 22: 12, 30: 5, 32: 6, 33: 6, 34: 12, 35: 12, 36: 12,
               37: 12, 38: 12, 39: 12, 40: 3}
LINK_ATTRS = ["NO", "FROMNODENO", "TONODENO", "TYPENO", "LENGTH", "CAPPRT", "V0PRT",
              "T0_PRTSYS(C)", "TCUR_PRTSYS(C)", "VOLVEHPRT(AP)", "VOLCAPRATIOPRT(AP)", "NUMLANES"]
PAX_ATTRS = ["VOLVEH_TSYS(C,AP)", "VOLVEH_TSYS(C_noT,AP)"]


def _here():
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path(os.getcwd())


def _visum():
    g = globals()
    if "Visum" in g:
        return g["Visum"]
    import __main__
    if hasattr(__main__, "Visum"):
        return __main__.Visum
    raise RuntimeError("Visum object not found - run the script from inside Visum")


def _f(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _i(v):
    x = _f(v)
    return None if x is None else int(round(x))


def geh(m, o):
    return 0.0 if m + o <= 0 else math.sqrt(2.0 * (m - o) ** 2 / (m + o))


def read_roster(root):
    rows = []
    a = root / "authorities"
    city = a / "R1_PROFILE_ROSTER_V24917_CITY.csv"
    csd = a / "R1_PROFILE_ROSTER_V24917_CSD.csv"
    if city.is_file():
        for r in csv.DictReader(open(city, encoding="utf-8-sig")):
            if str(r.get("active", "1")).strip() in ("0", "False", "false"):
                continue
            rows.append({"countlocation_no": r["countlocation_no"], "source": "CITY", "role": r["role"],
                         "observed": _f(r["observed_passenger_cars_O"]),
                         "link": _i(r["current_link_no"]), "from": _i(r["current_from_node_no"]),
                         "to": _i(r["current_to_node_no"]),
                         "both": str(r.get("observation_direction", "")).upper() == "BOTH"})
    if csd.is_file():
        for r in csv.DictReader(open(csd, encoding="utf-8-sig")):
            if str(r.get("current_objective_enabled", "1")).strip() in ("0", "False", "false"):
                continue
            rows.append({"countlocation_no": r["countlocation_no"], "source": "CSD", "role": r["role"],
                         "observed": _f(r.get("live_observed_value") or r["observed_passenger_cars_O"]),
                         "link": _i(r["current_link_no"]), "from": _i(r["current_from_node_no"]),
                         "to": _i(r["current_to_node_no"]), "both": False})
    return rows


def read_links(visum):
    links = visum.Net.Links
    cols = {}
    for a in LINK_ATTRS + PAX_ATTRS:
        try:
            cols[a] = [v[1] for v in links.GetMultiAttValues(a)]
        except Exception:
            cols[a] = None
    if cols["NO"] is None:
        raise RuntimeError("Links.GetMultiAttValues(NO) failed")
    out = {}
    for k in range(len(cols["NO"])):
        row = {a: (cols[a][k] if cols[a] is not None else None) for a in cols}
        key = (_i(row["NO"]), _i(row["FROMNODENO"]), _i(row["TONODENO"]))
        out[key] = row
    return out, [a for a in PAX_ATTRS if cols[a] is not None]


def link_metrics(row, pax_attrs):
    typ = _i(row["TYPENO"])
    vdf = TYPE_TO_VDF.get(typ)
    name, a, b, c = VDF.get(vdf, ("?", None, None, None))
    t0 = _f(row["T0_PRTSYS(C)"])
    tc = _f(row["TCUR_PRTSYS(C)"])
    pax = sum(_f(row[p]) or 0.0 for p in pax_attrs) if pax_attrs else None
    return {"typeno": typ, "vdf_no": vdf, "vdf_name": name, "bpr_a": a, "bpr_b": b, "cap_factor": c,
            "capprt": _f(row["CAPPRT"]), "v0prt": _f(row["V0PRT"]), "numlanes": _i(row["NUMLANES"]),
            "length_km": _f(row["LENGTH"]), "t0_s": t0, "tcur_s": tc,
            "tcur_over_t0": (tc / t0) if (t0 and tc) else None,
            "vol_veh_prt": _f(row["VOLVEHPRT(AP)"]), "vc_ratio": _f(row["VOLCAPRATIOPRT(AP)"]),
            "vol_pax_c": pax}


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else (round(r[k], 4) if isinstance(r[k], float) else r[k]))
                        for k in keys})


def summarize(rows, key, links_all):
    groups = {}
    for r in rows:
        groups.setdefault(r[key], []).append(r)
    net = {}
    for m in links_all:
        g = net.setdefault(m[key], {"km": 0.0, "km_vc09": 0.0, "km_vc10": 0.0, "km_vc12": 0.0, "vehkm": 0.0})
        L = m["length_km"] or 0.0
        vc = m["vc_ratio"] or 0.0
        g["km"] += L
        g["vehkm"] += L * (m["vol_veh_prt"] or 0.0)
        g["km_vc09"] += L if vc > 0.9 else 0.0
        g["km_vc10"] += L if vc > 1.0 else 0.0
        g["km_vc12"] += L if vc > 1.2 else 0.0
    out = []
    for k in sorted(set(groups) | set(net), key=lambda x: (x is None, x)):
        g = groups.get(k, [])
        cal = [r for r in g if r["model"] is not None and r["observed"]]
        ratio = (sum(r["model"] for r in cal) / sum(r["observed"] for r in cal)) if cal else None
        vcs = [r["vc_ratio"] for r in g if r["vc_ratio"] is not None]
        sample = g[0] if g else None
        n = net.get(k, {})
        out.append({key: k, "vdf_name": (sample or {}).get("vdf_name"),
                    "bpr_a": (sample or {}).get("bpr_a"), "bpr_b": (sample or {}).get("bpr_b"),
                    "cap_factor": (sample or {}).get("cap_factor"),
                    "profiles": len(g),
                    "model_over_obs": ratio,
                    "over_geh10": sum(1 for r in cal if r["model"] > r["observed"] and r["geh"] >= 10),
                    "under_geh10": sum(1 for r in cal if r["model"] < r["observed"] and r["geh"] >= 10),
                    "mean_geh": (sum(r["geh"] for r in cal) / len(cal)) if cal else None,
                    "mean_vc_counted": (sum(vcs) / len(vcs)) if vcs else None,
                    "max_vc_counted": max(vcs) if vcs else None,
                    "mean_tcur_over_t0_counted": (lambda xs: sum(xs) / len(xs) if xs else None)(
                        [r["tcur_over_t0"] for r in g if r["tcur_over_t0"]]),
                    "network_km": n.get("km"), "network_vehkm": n.get("vehkm"),
                    "km_vc_gt_0_9": n.get("km_vc09"), "km_vc_gt_1_0": n.get("km_vc10"),
                    "km_vc_gt_1_2": n.get("km_vc12")})
    return out


def load_live_vdf(visum, out):
    """Replace the built-in VDF table by the live procedure parameters (if exportable)."""
    import xml.etree.ElementTree as ET
    path = out / "PROCEDURES_LIVE.xml"
    for name in ("SaveXml", "Save"):
        fn = getattr(getattr(visum, "Procedures", None), name, None)
        if fn is None:
            continue
        try:
            fn(str(path))
            root = ET.parse(str(path)).getroot()
        except Exception:
            continue
        live = {}
        for sc in root.iter():
            if sc.tag.upper() != "LINKVDFUNCTIONSPARAMETERS":
                continue
            for el in sc:
                if el.tag.upper() == "VDFUNCTION" and el.attrib.get("VDFUNCTIONTYPE", "").upper() == "BPR":
                    live[int(float(el.attrib["NO"]))] = (el.attrib.get("NAME", ""), _f(el.attrib.get("BPR_A")),
                                                         _f(el.attrib.get("BPR_B")), _f(el.attrib.get("CAPACITYFACTOR")))
        if live:
            VDF.clear()
            VDF.update(live)
            return "LIVE_PROCEDURE_PARAMETERS"
    return "BUILT_IN_TABLE_20261016"


def run(visum, root, out_root):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_root / "R1_VDF_DIAGNOSTIC" / stamp
    out.mkdir(parents=True, exist_ok=True)
    vdf_source = load_live_vdf(visum, out)
    roster = read_roster(root)
    links, pax_attrs = read_links(visum)
    prof_rows, missing = [], []
    for r in roster:
        key = (r["link"], r["from"], r["to"])
        if key not in links:
            missing.append(r["countlocation_no"])
            continue
        m = link_metrics(links[key], pax_attrs)
        model = m["vol_pax_c"]
        if r["both"]:
            rev = links.get((r["link"], r["to"], r["from"]))
            if rev is not None and model is not None:
                model += link_metrics(rev, pax_attrs)["vol_pax_c"] or 0.0
        row = {"countlocation_no": r["countlocation_no"], "source": r["source"], "role": r["role"],
               "link_no": r["link"], "from_node": r["from"], "to_node": r["to"], "both_directions": r["both"]}
        row.update(m)
        row["model"] = model
        row["observed"] = r["observed"]
        row["model_over_obs"] = (model / r["observed"]) if (model is not None and r["observed"]) else None
        row["geh"] = geh(model, r["observed"]) if (model is not None and r["observed"]) else None
        prof_rows.append(row)
    prof_rows.sort(key=lambda x: -(x["geh"] or 0.0))
    all_m = [link_metrics(v, pax_attrs) for v in links.values()]
    write_csv(out / "01_PROFILES_VDF.csv", prof_rows)
    s_vdf = summarize(prof_rows, "vdf_no", all_m)
    s_typ = summarize(prof_rows, "typeno", all_m)
    write_csv(out / "02_VDF_CLASS_SUMMARY.csv", s_vdf)
    write_csv(out / "03_LINKTYPE_SUMMARY.csv", s_typ)
    lines = ["R1 VDF DIAGNOSTIC (read-only) " + stamp,
             "profiles: %d, not found in network: %d %s" % (len(prof_rows), len(missing), missing[:20]),
             "VDF parameters: " + vdf_source,
             "model volume = %s (+ reverse direction for BOTH city profiles)" % ("+".join(pax_attrs) or "N/A"),
             "", "VDF  name                  a     b    c     prof  model/obs  over10 under10  mean_vc  km_vc>1.0"]
    for s in s_vdf:
        lines.append("%-4s %-20s %5s %5s %5s %5d %9s %6d %7d %8s %9s" % (
            s["vdf_no"], (s["vdf_name"] or "")[:20], s["bpr_a"], s["bpr_b"], s["cap_factor"], s["profiles"],
            "" if s["model_over_obs"] is None else "%.3f" % s["model_over_obs"], s["over_geh10"], s["under_geh10"],
            "" if s["mean_vc_counted"] is None else "%.2f" % s["mean_vc_counted"],
            "" if s["km_vc_gt_1_0"] is None else "%.1f" % s["km_vc_gt_1_0"]))
    lines.append("")
    lines.append("STATUS: PASS_READ_ONLY")
    (out / "00_STATUS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _out_root(visum, here):
    cands = []
    try:
        cands.append(Path(str(visum.IO.CurrentVersionFile)).parent)
    except Exception:
        pass
    cands += [here, Path.home() / "Documents"]
    for c in cands:
        try:
            c.mkdir(parents=True, exist_ok=True)
            t = c / ".r1_write_test"
            t.write_text("x")
            t.unlink()
            return c
        except Exception:
            continue
    return here


def main():
    visum = _visum()
    here = _here()
    out = run(visum, here, _out_root(visum, here))
    msg = "R1 VDF diagnostic finished (read-only).\n" + str(out)
    if SHOW_MESSAGE_BOX:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "R1 VDF diagnostic", 0)
        except Exception:
            print(msg)
    else:
        print(msg)


if __name__ != "__r1_test__":
    try:
        main()
    except Exception as exc:   # show the reason instead of failing silently inside Visum
        import traceback
        txt = "R1 VDF diagnostic FAILED: %r\n%s" % (exc, traceback.format_exc())
        try:
            (_here() / "R1_VDF_DIAGNOSTIC_FAILED.txt").write_text(txt, encoding="utf-8")
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, txt[:1500], "R1 VDF diagnostic", 0)
        except Exception:
            print(txt)
