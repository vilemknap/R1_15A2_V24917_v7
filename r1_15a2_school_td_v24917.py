# -*- coding: utf-8 -*-
"""Source-bound SCHOOL Trip Distribution, never SCHOOL Trip Generation.

The original AMDY SCHOOL production and attraction formulas remain fixed.
Only native DStrat 5_SCHOOL gravity b/c on M9117 may be optimized.  The
source-owned 512-point IDP direct-purpose CDF is validated, never rebuilt.
"""
from __future__ import annotations

import numpy as np

RELEASE = "R1_V24917_SCHOOL_TD_512_IDP_20261030"
GROUP = "SCHOOL"
MATRIX_NO = 9117
DSTRAT_CODE = "5_SCHOOL"
POINTS = 512
GRID_MIN_KM = 0.1
GRID_MAX_KM = 100.0
SOURCE = "DIRECT_PURPOSE"


def reference_contract(ref):
    """Fail closed if the sealed FineCDF SCHOOL source is not the expected one."""
    if GROUP not in ref.TARGETS:
        raise RuntimeError("TDSCHOOL_REFERENCE_TARGET_MISSING")
    coarse = ref.TARGETS[GROUP]
    if list(coarse.get("matrix_nos", ())) != [MATRIX_NO]:
        raise RuntimeError("TDSCHOOL_MATRIX_SCOPE_MISMATCH")
    by_no = getattr(ref, "BY_NO", {})
    if by_no.get(MATRIX_NO, {}).get("dstrat_code") != DSTRAT_CODE:
        raise RuntimeError("TDSCHOOL_DSTRAT_AUTHORITY_MISMATCH")
    if MATRIX_NO not in getattr(ref, "MUTABLE_NOS", ()):
        raise RuntimeError("TDSCHOOL_BC_PARAMETERS_NOT_MUTABLE")
    fine = ref.FINE_AUTHORITY
    target = fine.get("targets", {}).get(GROUP, {})
    if target.get("grid") != "atomic" or target.get("source") != SOURCE:
        raise RuntimeError("TDSCHOOL_DIRECT_IDP_PURPOSE_AUTHORITY_MISMATCH")
    grid = np.asarray(fine.get("common_grid_atomic_km", ()), dtype=float)
    cdf = np.asarray(target.get("cdf", ()), dtype=float)
    if (grid.shape != (POINTS,) or cdf.shape != (POINTS,)
            or not np.isfinite(grid).all() or not np.isfinite(cdf).all()
            or not np.all(np.diff(grid) > 0.0)
            or not np.all(np.diff(cdf) >= -1.e-12)
            or not np.isclose(grid[0], GRID_MIN_KM, atol=1.e-12)
            or not np.isclose(grid[-1], GRID_MAX_KM, atol=1.e-12)
            or not np.isclose(cdf[0], 0., atol=1.e-12)
            or not np.isclose(cdf[-1], 1., atol=1.e-12)
            or np.any(cdf < -1.e-12) or np.any(cdf > 1. + 1.e-12)):
        raise RuntimeError("TDSCHOOL_FINECDF_512_SOURCE_INVALID")
    return {
        "release": RELEASE,
        "group": GROUP,
        "matrix_no": MATRIX_NO,
        "dstrat_code": DSTRAT_CODE,
        "target_points": POINTS,
        "distance_grid_km": [GRID_MIN_KM, GRID_MAX_KM],
        "finecdf_source": fine.get("target_authority"),
        "school_purpose": SOURCE,
        "school_generation_policy": "FIXED_ORIGINAL_AMDY_FORMULAS",
        "optimized_parameters": ["b", "c"],
        "parameter_a_frozen": True,
        "native_td_and_assignment_required_for_acceptance": True,
        "status": "SOURCE_REFERENCE_VERIFIED_LIVE_OPTIMIZATION_PENDING",
    }
