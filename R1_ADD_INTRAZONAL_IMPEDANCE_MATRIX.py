# -*- coding: utf-8 -*-
"""R1 V24917 IZPEN1 - one-time model setup for the intrazonal impedance lever.

Run ONCE in Visum (Scripts -> Run script file) on the .ver you calibrate from, then
SAVE the version (File -> Save version as ...) and start the calibration from it.

What it does
  1. creates matrix M9002 "R1_TD_IMP_IZPEN" as an exact copy of M9001 (same matrix type,
     same object type);  if M9002 already exists and its off-diagonal equals M9001 it is
     kept (existing diagonal penalties stay);
  2. switches the utility (impedance) matrix of the 16 native trip-distribution strata
     (1_WORK_*, 2_SERV_*, 3_LONG_*, 5_SCHOOL) from M9001 to M9002; 4_FOREIGN stays on M9001;
  3. prints the zones the calibrator will select (WORK+SERVICE 9101-9110: intrazonal
     share > 70 % and production > 5000).

M9001 is NOT changed.  M9002 = M9001 at setup, so the trip distribution result is
identical until the calibrator writes a diagonal penalty for the selected zones.
No procedure is executed.
"""
from __future__ import annotations

import math
import re

TARGET_NO = 9002
BASE_NO = 9001
CODE = "R1_TD_IMP_IZPEN"
NAME = "R1 TD impedance = M9001 + intrazonal penalty (V24917 IZ lever)"
NATIVE_CODES = ["1_WORK_E_C", "1_WORK_E_noC", "1_WORK_noE_C", "1_WORK_noE_noC", "1_WORK_stud",
                "2_SERV_E_C", "2_SERV_E_noC", "2_SERV_noE_C", "2_SERV_noE_noC", "2_SERV_stud",
                "3_LONG_E_C", "3_LONG_E_noC", "3_LONG_noE_C", "3_LONG_noE_noC", "3_LONG_stud",
                "5_SCHOOL"]
WS_MATRICES = list(range(9101, 9111))
MIN_SHARE, MIN_PROD = 0.70, 5000.0


def _v():
    v = globals().get("Visum")
    if v is None:
        raise RuntimeError("Spustte ve Visumu: Scripts -> Run script file")
    return v


def _values(m):
    return [list(map(float, row)) for row in m.GetValues()]


def _ref_no(text):
    s = str(text or "")
    m = re.search(r"\[NO\]\s*=\s*(\d+)", s, re.I)
    if m:
        return int(m.group(1))
    nums = re.findall(r"(\d+)", s)
    return int(nums[-1]) if len(nums) == 1 else None


def _all(coll):
    try:
        return list(coll.GetAll)
    except Exception:
        return [coll.ItemByKey(i) for i in range(1, int(coll.Count) + 1)]


def ensure_matrix(visum):
    base = visum.Net.Matrices.ItemByKey(BASE_NO)
    bvals = _values(base)
    n = len(bvals)
    try:
        m = visum.Net.Matrices.ItemByKey(TARGET_NO)
        existed = True
    except Exception:
        m, existed = None, False
    if existed and all(v == 0.0 for row in _values(m) for v in row):
        if str(m.AttValue("MATRIXTYPE")) != str(base.AttValue("MATRIXTYPE")):
            raise RuntimeError("Prazdna M%d ma jiny typ matice nez M9001" % TARGET_NO)
        m.SetValues(bvals)
        print("Prazdna M%d naplnena kopii M9001." % TARGET_NO)
        existed = False
        return m, True
    if existed:
        cur = _values(m)
        bad =sum(1 for i in range(n) for j in range(n) if i != j and abs(cur[i][j] - bvals[i][j]) > 1e-9)
        if bad:
            raise RuntimeError("M%d uz existuje a mimo diagonalu se lisi od M9001 (%d bunek). "
                               "Zvolte jine cislo (R1_RUN_OPTIONS.json iz_matrix_no) nebo M%d smazte."
                               % (TARGET_NO, bad, TARGET_NO))
        print("M%d existuje, mimo diagonalu = M9001 -> ponechana (stavajici prirazky zustavaji)." % TARGET_NO)
        return m, False
    otype = base.AttValue("OBJECTTYPEREF")
    mtype = base.AttValue("MATRIXTYPE")
    candidates = [(TARGET_NO, otype, mtype)]
    try:
        candidates.append((TARGET_NO, int(float(otype)), int(float(mtype))))
    except Exception:
        pass
    # COM enums OBJECTTYPEREF_ZONE / MATRIXTYPE_SKIM; the type is verified against M9001 below
    candidates += [(TARGET_NO, 2, 4), (TARGET_NO, 2, 3), (TARGET_NO, 2, 2)]
    errors = []
    m = None
    for args in candidates:
        try:
            m = visum.Net.AddMatrix(*args)
        except Exception as exc:
            errors.append("%r -> %r" % (args, exc))
            m = None
            continue
        if str(m.AttValue("MATRIXTYPE")) == str(mtype) and str(m.AttValue("OBJECTTYPEREF")) == str(otype):
            break
        errors.append("%r -> typ %s/%s" % (args, m.AttValue("MATRIXTYPE"), m.AttValue("OBJECTTYPEREF")))
        try:
            visum.Net.RemoveMatrix(m)
        except Exception as exc:
            raise RuntimeError("M%d vznikla se spatnym typem a nejde smazat (%r); smazte ji rucne, zalozte "
                               "M%d jako Skim matici zon a skript spustte znovu." % (TARGET_NO, exc, TARGET_NO))
        m = None
    if m is None:
        raise RuntimeError("M%d se nepodarilo zalozit se stejnym typem jako M9001 (%s/%s): %s. Zalozte ji rucne "
                           "jako Skim matici zon a skript spustte znovu (prazdnou ji zkopiruje)."
                           % (TARGET_NO, mtype, otype, " | ".join(errors)))
    for attr, val in (("CODE", CODE), ("NAME", NAME)):
        try:
            m.SetAttValue(attr, val)
        except Exception:
            pass
    m.SetValues(bvals)
    back = _values(m)
    worst = max(abs(back[i][j] - bvals[i][j]) for i in range(n) for j in range(n))
    if worst > 1e-9:
        raise RuntimeError("Kontrola kopie M%d selhala (max rozdil %g)" % (TARGET_NO, worst))
    print("M%d vytvorena jako presna kopie M9001 (%dx%d)." % (TARGET_NO, n, n))
    return m, True


def find_td(visum):
    found = []
    for op in _all(visum.Procedures.Operations):
        try:
            if int(float(op.AttValue("OPERATIONTYPE"))) != 46:
                continue
            params = op.TripDistributionParameters
            dset = {x.strip() for x in str(params.AttValue("DSTRATSET")).split(",") if x.strip()}
        except Exception:
            continue
        if set(NATIVE_CODES) <= dset:
            found.append((op, params))
    if len(found) != 1:
        raise RuntimeError("Ocekavana prave 1 operace rozdeleni prepravy se 16 nativnimi vrstvami, nalezeno %d"
                           % len(found))
    return found[0][1]


UTIL_NAMES = ("UTILITYFUNCTION", "UtilityFunction", "UTILITYMATRIX", "UtilityMatrix",
              "UTILITYMATRIXREF", "IMPEDANCEMATRIX", "IMPEDANCEMATRIXREF", "SKIMMATRIXREF")


def _attr_ids(obj):
    try:
        return [str(a.ID) for a in obj.Attributes.GetAll]
    except Exception:
        try:
            return [str(a.Code) for a in obj.Attributes.GetAll]
        except Exception:
            return []


def _gravity(d):
    for prop in ("GravitationParameters", "GravityParameters", "DistributionParameters"):
        try:
            g = getattr(d, prop)
            if g is not None:
                return g
        except Exception:
            pass
    return None


def locate_utility(d):
    """(label, object, attribute, value) of the utility-matrix reference of one TD stratum."""
    objs = [("TripDistributionDStratParameters", d), ("GravitationParameters", _gravity(d))]
    for label, obj in objs:
        if obj is None:
            continue
        for name in UTIL_NAMES:
            try:
                return label, obj, name, obj.AttValue(name)
            except Exception:
                continue
    for label, obj in objs:
        if obj is None:
            continue
        for aid in _attr_ids(obj):
            u = aid.upper()
            if "UTIL" in u or "IMPED" in u:
                try:
                    return label, obj, aid, obj.AttValue(aid)
                except Exception:
                    continue
    listing = []
    for label, obj in objs:
        if obj is not None:
            ids = _attr_ids(obj)
            listing.append("%s: %s" % (label, ", ".join(ids) if ids else "(seznam atributu nedostupny)"))
    raise RuntimeError("Atribut matice uzitku/odporu jsem nenasel. Dostupne atributy -> " + " || ".join(listing))


def switch_utility(params):
    rows = []
    for code in NATIVE_CODES:
        d = params.TripDistributionDStratParameters(code)
        label, obj, attr, old = locate_utility(d)
        old_no = _ref_no(old)
        if old_no == TARGET_NO:
            rows.append((code, "%s.%s" % (label, attr), old, old, "UZ_M%d" % TARGET_NO))
            continue
        if old_no != BASE_NO:
            raise RuntimeError("%s pouziva matici odporu %r (%s.%s), ocekavana M9001 - u dalsich vrstev nic nemenim"
                               % (code, old, label, attr))
        ok = False
        errors = []
        for value in ("Matrix([NO]=%d)" % TARGET_NO, "Matrix([NO] = %d)" % TARGET_NO, "Matrix([NO]=%d.0)" % TARGET_NO,
                      str(TARGET_NO), TARGET_NO):
            try:
                obj.SetAttValue(attr, value)
            except Exception as exc:
                errors.append("%r: %s" % (value, str(exc)[:160]))
                continue
            if _ref_no(obj.AttValue(attr)) == TARGET_NO:
                ok = True
                break
        if not ok:
            raise RuntimeError("%s: nepodarilo se prepnout %s.%s na M%d (%s). Nastavte rucne: Procedure sequence -> "
                               "rozdeleni prepravy -> %s -> matice uzitku = M%d a skript spustte znovu."
                               % (code, label, attr, TARGET_NO, " | ".join(errors), code, TARGET_NO))
        rows.append((code, "%s.%s" % (label, attr), old, obj.AttValue(attr), "PREPNUTO"))
    return rows


def selection_preview(visum):
    zones = [int(round(float(v))) for _k, v in visum.Net.Zones.GetMultiAttValues("NO")]
    names = [str(v) for _k, v in visum.Net.Zones.GetMultiAttValues("NAME")]
    n = len(zones)
    ws = [[0.0] * n for _ in range(n)]
    for no in WS_MATRICES:
        vals = _values(visum.Net.Matrices.ItemByKey(no))
        for i in range(n):
            row, acc = vals[i], ws[i]
            for j in range(n):
                acc[j] += row[j]
    out = []
    for i in range(n):
        prod = sum(ws[i])
        share = ws[i][i] / prod if prod > 0 else 0.0
        if share > MIN_SHARE and prod > MIN_PROD:
            out.append((zones[i], names[i], share, prod))
    return sorted(out, key=lambda r: -r[3])


def main():
    visum = _v()
    print("=== R1 V24917 IZPEN1 setup: M%d = M9001 + vnitrozonova prirazka ===" % TARGET_NO)
    ensure_matrix(visum)
    rows = switch_utility(find_td(visum))
    print("Matice odporu (UTILITYFUNCTION) 16 nativnich vrstev:")
    for code, where, old, new, st in rows:
        print("  %-16s %-22s -> %-22s %s  [%s]" % (code, old, new, st, where))
    print("4_FOREIGN beze zmeny (M9001).")
    sel = selection_preview(visum)
    print("Zony pro paku (podil vnitrozonovych WORK+SERVICE > 70 %%, produkce > 5000): %d" % len(sel))
    for z, name, share, prod in sel:
        print("  %4d %-24s podil %.3f  produkce %9.0f" % (z, name, share, prod))
    print("HOTOVO. Ulozte verzi (File -> Save version as ...) a kalibraci spustte z ni.")


if globals().get("Visum") is not None or __name__ == "__main__":
    main()
