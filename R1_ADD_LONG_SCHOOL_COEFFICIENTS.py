# -*- coding: utf-8 -*-
"""R1: create zone coefficients for LONG and SCHOOL trip generation.

Visum: open the base .ver -> Scripts -> Run script file -> R1_ADD_LONG_SCHOOL_COEFFICIENTS.py
Creates (if missing) the zone user-defined attributes
    ADD_PROD_L   = 0.2  (replaces the AMDY constant k_long = 0,2 in FP_3_LONG_*)
    ADD_ATT_L    = 0.2  (replaces only AMDY 0.2 × PRENOC_SVK in FA_3_LONG)
    ADD_PROD_SCH = 1.0
    ADD_ATT_SCH  = 1.0   (double, all zones)
Existing attributes are NOT overwritten (their values stay).  Nothing else changes,
no procedure is run and the version is NOT saved - save it yourself after editing the
generation formulas (see R1_LONG_SCHOOL_FORMULAS in the reply / START_HERE).
With these start values the model results are identical to AMDY only if both
native LONG formulas are linked correctly. Existing attributes remain unchanged.
SCHOOL coefficients are not used by the original AMDY school formulas.
"""
from __future__ import annotations

NEW_ATTRIBUTES = (
    ("ADD_PROD_L", "R1 calibration coefficient LONG production (AMDY k_long)", 0.2),
    ("ADD_ATT_L", "R1 LONG overnight term coefficient (PRENOC_SVK only)", 0.2),
    ("ADD_PROD_SCH", "R1 calibration coefficient SCHOOL production", 1.0),
    ("ADD_ATT_SCH", "R1 calibration coefficient SCHOOL attraction", 1.0),
)
VALUE_TYPE_DOUBLE = 2
DECIMALS = 6


def _exists(zones, code):
    try:
        zones.GetMultiAttValues(code, False)
        return True
    except Exception:
        return False


def main():
    visum = globals().get("Visum") or globals().get("COM")
    if visum is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    zones = visum.Net.Zones
    report = []
    for code, name, start in NEW_ATTRIBUTES:
        if _exists(zones, code):
            report.append((code, "EXISTS_KEPT"))
            continue
        zones.AddUserDefinedAttribute(code, code, name, VALUE_TYPE_DOUBLE, DECIMALS)
        keys = [k for k, _ in zones.GetMultiAttValues("NO", False)]
        zones.SetMultiAttValues(code, tuple((k, start) for k in keys))
        vals = [float(v) for _, v in zones.GetMultiAttValues(code, False)]
        if len(vals) != len(keys) or any(abs(v - start) > 1e-12 for v in vals):
            raise RuntimeError("R1_ADD_COEFFICIENT_WRITE_CHECK_FAILED:" + code)
        report.append((code, "CREATED_ALL_%g" % start))
    for code, status in report:
        print("R1 LONG/SCHOOL coefficient %-13s %s" % (code, status))
    print("Version NOT saved. Edit the FP_3_LONG_*, FA_3_LONG, FP_5_SCHOOL, FA_5_SCHOOL formulas, then save.")


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
