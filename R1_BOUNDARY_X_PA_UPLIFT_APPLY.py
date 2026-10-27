# -*- coding: utf-8 -*-
"""
R1 | PTV Visum 2026 | Border-crossing synthetic P/A uplift, graded by volume (X1-X31).

Multiplies the synthetic boundary production P09F4_PER_PRE_* and attraction
A09F4_PER_PRE_* of the cordon crossing zones 650-680 (X1-X31) in all 16 non-FOREIGN
person-group layers (WORK, SERV, LONG x 5 groups, SCHOOL).  P and A of a zone get the
same factor (boundary vectors stay symmetric).

GRADED FACTOR by the current volume V of the crossing (sum of its 16 P layers):
    V <= LOW_VOLUME  (300)   -> FACTOR_LOW  (8x)
    V >= HIGH_VOLUME (2000)  -> FACTOR_HIGH (2x)
    in between: log-linear  f = FACTOR_LOW * (FACTOR_HIGH/FACTOR_LOW) ** t,
                            t = ln(V/LOW_VOLUME) / ln(HIGH_VOLUME/LOW_VOLUME)
    (e.g. 500 -> 4.9x, 1000 -> 3.3x).  A zone with V = 0 stays 0.

Never touches: *_FOREIGN, FP_*/FA_* (derived), ADD_*, ZAHR_*, COUNTRY_ADD*, matrices,
procedures.  Does not run TG/TD/assignment and does not save the .ver.

Run in Visum: Scripts -> Run script file...
  1. this file (DRY_RUN = True): nothing is written, the plan is shown in a message box
     and in <output folder>/DRYRUN_<time>/ (02_ZONE_TOTALS.csv).
  2. the _APPLY file (DRY_RUN = False): backup -> write -> readback -> rollback on error.
     Then SAVE AS a new .ver.
The output folder is printed and shown in the message box (next to the open .ver,
otherwise next to this script, otherwise Documents).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import time
import traceback
from pathlib import Path

DRY_RUN = False
LOW_VOLUME = 300.0
HIGH_VOLUME = 2000.0
FACTOR_LOW = 8.0
FACTOR_HIGH = 2.0
ZONES = list(range(650, 681))                    # X1 .. X31
EXPECT_NAMES_X = True                            # zone 650 = 'X1' ... 680 = 'X31'
ALLOW_REPEAT = False
SHOW_MESSAGE_BOX = True
EXPECTED_ZONE_COUNT = 681
LAYERS = ["LONG_E_C", "LONG_E_noC", "LONG_noE_C", "LONG_noE_noC", "LONG_stud", "SCHOOL",
          "SERV_E_C", "SERV_E_noC", "SERV_noE_C", "SERV_noE_noC", "SERV_stud",
          "WORK_E_C", "WORK_E_noC", "WORK_noE_C", "WORK_noE_noC", "WORK_stud"]
ATTRS = ["P09F4_PER_PRE_" + l for l in LAYERS] + ["A09F4_PER_PRE_" + l for l in LAYERS]
GUARDS = ["P09F4_PER_PRE_FOREIGN", "A09F4_PER_PRE_FOREIGN"]
TOL = 1.0e-6
STEP_ID = "R1_BOUNDARY_X_PA_UPLIFT_V2_GRADED"


def factor_for(volume: float) -> float:
    if volume <= 0.0:
        return 1.0
    if volume <= LOW_VOLUME:
        return FACTOR_LOW
    if volume >= HIGH_VOLUME:
        return FACTOR_HIGH
    t = math.log(volume / LOW_VOLUME) / math.log(HIGH_VOLUME / LOW_VOLUME)
    return FACTOR_LOW * (FACTOR_HIGH / FACTOR_LOW) ** t


def _visum():
    v = globals().get("Visum") or globals().get("COM")
    if v is not None:
        return v
    try:
        import builtins
        v = getattr(builtins, "Visum", None)
        if v is not None:
            return v
    except Exception:
        pass
    import win32com.client  # type: ignore
    return win32com.client.GetActiveObject("Visum.Visum")


def _get(zones, attr):
    try:
        return list(zones.GetMultiAttValues(attr, False))
    except TypeError:
        return list(zones.GetMultiAttValues(attr))


def _set(zones, attr, pairs):
    try:
        zones.SetMultiAttValues(attr, pairs, False)
    except TypeError:
        zones.SetMultiAttValues(attr, pairs)


def _keys(zones):
    by_no = {}
    for key, raw in _get(zones, "NO"):
        no = int(round(float(raw)))
        if no in by_no:
            raise RuntimeError("Duplicate Zone.NO %d" % no)
        by_no[no] = key
    if len(by_no) != EXPECTED_ZONE_COUNT:
        raise RuntimeError("Expected %d zones, model has %d" % (EXPECTED_ZONE_COUNT, len(by_no)))
    return by_no


def _read(zones, attr, by_no):
    data = dict(_get(zones, attr))
    out = {}
    for no, key in by_no.items():
        raw = data.get(key)
        v = float(str(raw).replace(",", ".")) if raw not in (None, "") else 0.0
        if not math.isfinite(v):
            raise RuntimeError("NaN/Inf in %s zone %d" % (attr, no))
        out[no] = v
    return out


def _candidate_roots(v):
    roots = []
    for get in (lambda: v.AttValue("VERSIONFILE"), lambda: v.IO.CurrentVersionFile if hasattr(v, "IO") else None):
        try:
            raw = get()
        except Exception:
            continue
        if raw and str(raw).strip().lower().endswith((".ver", ".verx")):
            roots.append(Path(str(raw)).parent)
    f = globals().get("__file__")
    if f:
        roots.append(Path(str(f)).resolve().parent)
    try:
        roots.append(Path(str(v.GetPath(2))))
    except Exception:
        pass
    roots.append(Path(os.path.expanduser("~")) / "Documents")
    roots.append(Path(os.getcwd()))
    return roots


def _out_dir(v, dry):
    errors = []
    for base in _candidate_roots(v):
        try:
            root = base / "R1_BOUNDARY_X_PA_UPLIFT"
            root.mkdir(parents=True, exist_ok=True)
            d = root / (("DRYRUN_" if dry else "APPLY_") + time.strftime("%Y%m%d_%H%M%S"))
            n = 1
            while d.exists():
                d = root / (d.name + "_%d" % n)
                n += 1
            d.mkdir()
            return root, d
        except Exception as exc:
            errors.append("%s: %r" % (base, exc))
    raise RuntimeError("No writable output folder: " + "; ".join(errors))


def _already_applied(root, before):
    """True when the live values equal the 'after' of an earlier successful APPLY (double run)."""
    for bk in sorted(root.glob("APPLY_*/BACKUP_BEFORE.json.gz")):
        try:
            data = json.loads(gzip.open(str(bk), "rb").read().decode("utf-8"))
            after = data.get("after") or {}
        except Exception:
            continue
        if not after:
            continue
        hit = True
        nonzero = False
        for a in ATTRS:
            for z in ZONES:
                x = float(after.get(a, {}).get(str(z), 0.0))
                nonzero = nonzero or x > 0
                if abs(before[a][z] - x) > TOL * max(1.0, abs(x)):
                    hit = False
                    break
            if not hit:
                break
        if hit and nonzero:
            return str(bk)
    return None


def _message(title, body):
    if not SHOW_MESSAGE_BOX:
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, body[:1800], title, 0x40)
    except Exception:
        pass


def main(v=None):
    v = v or _visum()
    zones = v.Net.Zones
    status, details, out = "FAILED", [], None
    written, before = [], {}
    try:
        root, out = _out_dir(v, DRY_RUN)
        by_no = _keys(zones)
        missing = [z for z in ZONES if z not in by_no]
        if missing:
            raise RuntimeError("Missing zones %s" % missing)
        if EXPECT_NAMES_X:
            names = dict(_get(zones, "NAME"))
            bad = [(z, names.get(by_no[z])) for i, z in enumerate(ZONES)
                   if str(names.get(by_no[z]) or "").strip().upper() != "X%d" % (i + 1)]
            if bad:
                raise RuntimeError("Zone names are not X1..X31: %s (set EXPECT_NAMES_X = False if intended)"
                                   % bad[:5])
        before = {a: _read(zones, a, by_no) for a in ATTRS}
        guards = {a: _read(zones, a, by_no) for a in GUARDS}
        if not DRY_RUN and not ALLOW_REPEAT:
            prev = _already_applied(root, before)
            if prev:
                raise RuntimeError("This model already contains the uplift of %s - refusing to multiply again "
                                   "(reopen the original .ver or set ALLOW_REPEAT = True)" % prev)
        factors, per_zone = {}, []
        for z in ZONES:
            vol_p = sum(before[a][z] for a in ATTRS if a.startswith("P09F4"))
            vol_a = sum(before[a][z] for a in ATTRS if a.startswith("A09F4"))
            f = factor_for(vol_p)
            factors[z] = f
            per_zone.append([z, "X%d" % (z - 649), round(vol_p, 1), round(f, 3), round(vol_p * f, 1),
                             round(vol_a, 1), round(vol_a * f, 1)])
        plan, rows = {}, []
        for a in ATTRS:
            plan[a] = dict(before[a])
            for z in ZONES:
                plan[a][z] = before[a][z] * factors[z]
                if before[a][z] != 0.0:
                    rows.append([z, "X%d" % (z - 649), a, before[a][z], round(factors[z], 4), plan[a][z]])
        with open(str(out / "01_PLANNED_CHANGES.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["zone_no", "zone", "attribute", "before", "factor", "after"])
            w.writerows(rows)
        with open(str(out / "02_ZONE_TOTALS.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["zone_no", "zone", "P_before", "factor", "P_after", "A_before", "A_after"])
            w.writerows(per_zone)
        p0 = sum(r[2] for r in per_zone)
        p1 = sum(r[4] for r in per_zone)
        details.append("crossings=%d  P total %.0f -> %.0f (x%.2f)  rule: <=%.0f -> x%g, >=%.0f -> x%g"
                       % (sum(1 for r in per_zone if r[2] > 0), p0, p1, p1 / p0 if p0 else 0.0,
                          LOW_VOLUME, FACTOR_LOW, HIGH_VOLUME, FACTOR_HIGH))
        for r in sorted(per_zone, key=lambda r: -r[2]):
            if r[2] > 0:
                details.append("  %-4s P %8.0f  x%5.2f -> %8.0f" % (r[1], r[2], r[3], r[4]))
        if DRY_RUN:
            status = "PASS_DRY_RUN_NOTHING_WRITTEN"
            return status
        raw = json.dumps({"schema": STEP_ID, "factors": {str(z): f for z, f in factors.items()},
                          "values": {a: {str(z): before[a][z] for z in by_no} for a in ATTRS},
                          "after": {a: {str(z): plan[a][z] for z in ZONES} for a in ATTRS}},
                         separators=(",", ":")).encode("utf-8")
        with gzip.open(str(out / "BACKUP_BEFORE.json.gz"), "wb") as fh:
            fh.write(raw)
        (out / "BACKUP_SHA256.txt").write_text(hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii")
        for a in ATTRS:
            if all(before[a][z] == 0.0 for z in ZONES):
                continue
            written.append(a)
            _set(zones, a, [[by_no[no], float(val)] for no, val in sorted(plan[a].items())])
            back = _read(zones, a, by_no)
            bad = [z for z in by_no if abs(back[z] - plan[a][z]) > TOL * max(1.0, abs(plan[a][z]))]
            if bad:
                raise RuntimeError("Readback mismatch %s zones %s" % (a, bad[:5]))
        if {a: _read(zones, a, by_no) for a in GUARDS} != guards:
            raise RuntimeError("FOREIGN boundary vectors changed - aborting")
        status = "PASS_APPLIED_NOT_SAVED"
        details.append("written attributes=%d - now SAVE AS a new .ver" % len(written))
        return status
    except Exception as exc:
        details.append("ERROR: %r" % (exc,))
        details.append(traceback.format_exc()[-1500:])
        if written and before:
            try:
                by_no = _keys(zones)
                for a in reversed(written):
                    _set(zones, a, [[by_no[no], float(val)] for no, val in sorted(before[a].items())])
                details.append("ROLLBACK: original values restored for %d attributes" % len(written))
                status = "FAILED_ROLLED_BACK"
            except Exception as rb:
                details.append("ROLLBACK FAILED: %r - do NOT save, reopen the .ver" % (rb,))
                status = "FAILED_ROLLBACK_FAILED_DO_NOT_SAVE"
        return status
    finally:
        body = status + "\n" + STEP_ID + "\n" + ("output: %s\n" % out if out else "") + "\n".join(details) + "\n"
        if out is not None:
            try:
                (out / "00_STATUS.txt").write_text(body, encoding="utf-8")
            except Exception:
                pass
        if not SHOW_MESSAGE_BOX:          # inside Visum every print line pops up its own dialog
            print(body)
        try:
            v.Log(20480, STEP_ID + " " + status + " | " + str(out))
        except Exception:
            pass
        _message("R1 border-crossing uplift: " + status, body)


if globals().get("__r1_test__") is not True:
    main()
