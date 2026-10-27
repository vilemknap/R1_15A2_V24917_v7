# -*- coding: utf-8 -*-
"""R1: check that the LONG/SCHOOL generation formulas really use the new coefficients.

Visum: Scripts -> Run script file -> R1_LONG_SCHOOL_FORMULA_CHECK.py
For each coefficient it doubles the value in ONE zone, reads the dependent formula
attribute, and immediately writes the original value back.  No procedure is run,
the version is NOT saved; the model ends exactly as it started.
"""
from __future__ import annotations

CHECKS = (
    ("ADD_PROD_L", ("FP_3_LONG_E_C", "FP_3_LONG_E_noC", "FP_3_LONG_noE_C", "FP_3_LONG_noE_noC", "FP_3_LONG_stud")),
    ("ADD_ATT_L", ("FA_3_LONG",)),
    ("ADD_PROD_SCH", ("FP_5_SCHOOL",)),
    ("ADD_ATT_SCH", ("FA_5_SCHOOL",)),
)


def main():
    visum = globals().get("Visum") or globals().get("COM")
    if visum is None:
        raise RuntimeError("NO_INJECTED_VISUM")
    zones = visum.Net.Zones
    ok_all = True
    for coef, targets in CHECKS:
        base_t = {t: dict(zones.GetMultiAttValues(t, False)) for t in targets}
        key = max(base_t[targets[0]], key=lambda k: float(base_t[targets[0]][k] or 0.0))
        coef_vals = dict(zones.GetMultiAttValues(coef, False))
        c0 = float(coef_vals[key])
        try:
            zones.SetMultiAttValues(coef, ((key, 2.0 * c0),))
            res = []
            for t in targets:
                v0 = float(base_t[t][key] or 0.0)
                v1 = float(dict(zones.GetMultiAttValues(t, False))[key] or 0.0)
                ratio = v1 / v0 if v0 else float("nan")
                ok = v0 == 0.0 or abs(ratio - 2.0) < 1e-6
                ok_all &= ok
                res.append("%s %.4f->%.4f x%.3f %s" % (t, v0, v1, ratio, "OK" if ok else "NOT_LINKED"))
        finally:
            zones.SetMultiAttValues(coef, ((key, c0),))
        restored = float(dict(zones.GetMultiAttValues(coef, False))[key])
        print("R1 FORMULA CHECK %-13s (zone index %s, %g restored=%s): %s"
              % (coef, key, c0, abs(restored - c0) < 1e-12, "; ".join(res)))
    print("R1 FORMULA CHECK RESULT:", "ALL_LINKED" if ok_all else "SOME_FORMULAS_NOT_LINKED")


if __name__ == "__main__" or globals().get("Visum") is not None or globals().get("COM") is not None:
    main()
