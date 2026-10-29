"""Shared LONG TD contract. Preparation only: native support is still unverified.

One delta-b and one log multiplier of negative c apply to all five strata.
The sealed 512-point aggregate target is used once, never copied to strata.
This module neither writes COM nor authorizes a native OD support mechanism.
"""
from __future__ import annotations

import math

import numpy as np

from r1_15a2_long_distance_guard_v24917 import MATRIX_NOS, MIN_KM, MIN_CDF_KM, MAX_CDF_KM
from r1_15a2_long_support_distance_v24917 import MATRIX_NO, MATRIX_CODE, DISTANCE_BASIS

GROUP = "LONG_COMPOSITE"


def activation_plan():
    """Report actual readiness; a requested policy is not live evidence."""
    return {
        "group": GROUP, "matrix_nos": list(MATRIX_NOS),
        "requested_policy": "SHARED_B_OFFSET_AND_C_MULTIPLIER",
        "a_frozen": True, "generation_frozen": True,
        "target_copies": 1, "component_targets_created": False,
        "component_guards": ["A_AND_FOREIGN_FROZEN", "NATIVE_MARGINALS_AND_TOTALS",
                             "NONNEGATIVE_OD", "LONG_SUPPORT_EACH_STAGE"],
        "minimum_km": MIN_KM, "conditional_cdf_max_km": MAX_CDF_KM,
        "support_distance_basis": DISTANCE_BASIS,
        "support_distance_matrix_no": MATRIX_NO, "support_distance_matrix_code": MATRIX_CODE,
        "finecdf_distance_basis": "FRESH_NATIVE_CL_DIS_KM",
        "above_200_km_permitted": True,
        "live_enabled": False, "status": "PREPARED_NOT_LIVE_ENABLED",
        "blockers": ["NATIVE_LONG_OD_PAIR_FILTER_UNVERIFIED",
                     "LONG_COUNT_RESPONSE_UNVERIFIED"],
        "required_validation": ["RESTRICTED_PA_FEASIBILITY",
                                "SUPPORT_AFTER_TD_SYMMETRY_AND_20A_20B",
                                "FRESH_ASSIGNMENT_AND_SKIMS",
                                "VERIFIED_NATIVE_ROLLBACK"],
    }


def reference_contract(ref):
    """Validate aggregate scope without modifying sealed targets or parameters."""
    target = ref.TARGETS[GROUP]
    if tuple(target["matrix_nos"]) != tuple(MATRIX_NOS):
        raise ValueError("TDLONG_COMPOSITE_COMPONENT_SCOPE")
    fine = ref.FINE_AUTHORITY
    entry = fine["targets"][GROUP]
    grid = np.asarray(fine["common_grid_long_km"], dtype=float)
    cdf = np.asarray(entry["cdf"], dtype=float)
    if (entry["grid"] != "long" or grid.shape != (512,) or cdf.shape != (512,)
            or not np.isfinite(grid).all() or not np.isfinite(cdf).all()
            or np.any(np.diff(grid) <= 0) or np.any(np.diff(cdf) < -1e-12)
            or grid[0] != MIN_CDF_KM or grid[-1] != MAX_CDF_KM
            or np.any((cdf < 0) | (cdf > 1))):
        raise ValueError("TDLONG_COMPOSITE_FINECDF_AUTHORITY")
    return dict(activation_plan(), aggregate_target_verified=True,
                aggregate_target_points=512, target_source=entry["source"])


def realization_groups(rows, parent_rows, component_no):
    """Keep all LONG members atomic, including outer component isolation.

    Parent rows are live snapshot b/c values; source/epoch validation and native
    support authorization belong to the transaction owner, not this pure check.
    """
    parent = {str(r["component"]): r for r in parent_rows}
    groups, long_rows, seen = [], [], set()
    for row in rows:
        name = str(row["component"])
        if name in seen:
            raise ValueError("TDLONG_COMPOSITE_DUPLICATE_COMPONENT")
        seen.add(name)
        if component_no.get(name) in MATRIX_NOS:
            long_rows.append(row)
        else:
            groups.append((name, [row]))
    if long_rows:
        if {component_no[r["component"]] for r in long_rows} != set(MATRIX_NOS):
            raise ValueError("TDLONG_COMPOSITE_PARTIAL_GROUP")
        db, lc = [], []
        for row in long_rows:
            old = parent[str(row["component"])]
            b, c = float(old["current_b"]), float(old["current_c"])
            nb, nc = float(row["candidate_b"]), float(row["candidate_c"])
            if not all(math.isfinite(v) for v in (b, c, nb, nc)) or b < 0 or c >= 0 or nc >= 0:
                raise ValueError("TDLONG_COMPOSITE_PARAMETER_DOMAIN")
            db.append(nb - b)
            lc.append(math.log(-nc) - math.log(-c))
        if (any(not math.isclose(v, db[0], rel_tol=1e-10, abs_tol=1e-8) for v in db)
                or any(not math.isclose(v, lc[0], rel_tol=1e-10, abs_tol=1e-8) for v in lc)):
            raise ValueError("TDLONG_COMPOSITE_INDEPENDENT_COMPONENT_STEP")
        groups.append((GROUP, sorted(long_rows, key=lambda r: component_no[r["component"]])))
    return sorted(groups, key=lambda item: item[0])


def require_live_ready(groups):
    """No user-provided verified flag can bypass the missing native implementation."""
    if any(name == GROUP for name, _ in groups):
        raise RuntimeError("TDLONG_COMPOSITE_NATIVE_SUPPORT_AND_COUNT_RESPONSE_UNVERIFIED")
