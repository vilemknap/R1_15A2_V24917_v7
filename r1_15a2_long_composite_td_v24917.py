"""Shared LONG TD contract. Shared TD preparation; support is post-TD multiplication with accepted loss.

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
        "generation_fixed_during_td_stage": True,
        "target_copies": 1, "component_targets_created": False,
        "component_guards": ["A_AND_FOREIGN_FROZEN", "NATIVE_MARGINALS_BEFORE_MASK",
                             "POST_MASK_VOLUME_LOSS_AUDIT",
                             "NONNEGATIVE_OD", "LONG_SUPPORT_EACH_STAGE"],
        "minimum_km": MIN_KM, "conditional_cdf_max_km": MAX_CDF_KM,
        "support_distance_basis": DISTANCE_BASIS,
        "support_distance_matrix_no": MATRIX_NO, "support_distance_matrix_code": MATRIX_CODE,
        "finecdf_distance_basis": "FRESH_NATIVE_CL_DIS_KM",
        "above_200_km_permitted": True,
        "live_enabled": False, "status": "READY_FOR_LIVE_PROOF_NOT_YET_CERTIFIED",
        "support_method": "POST_TD_MULTIPLICATION_ACCEPT_VOLUME_LOSS",
        "native_od_filter_required": False,
        "blockers": ["LIVE_NATIVE_DYNAMIC_COUNT_RESPONSE_PROOF_REQUIRED"],
        "required_validation": ["POST_MASK_VOLUME_LOSS_AUDIT",
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


def live_readiness(bridge):
    """Current-state proof for *measured* LONG count responses in native TDJOINT1.

    This is NOT a frozen-path LONG count derivative. The dynamic FineCDF
    evaluator must recalculate TD, 20A/20B, mask, all four assignments,
    fresh skims and all calibration-count profile volumes per candidate.
    The proof is re-read from Visum; a caller flag cannot certify the epoch.
    """
    import r1_15a2_demand_policy_v1 as dp
    from r1_15a2_long_post_td_mask_v24917 import _verify_support, _read
    from r1_15a2_long_support_distance_v24917 import read_current
    from r1_15a2_long_profile_incidence_v24917 import COMPONENT_MATRICES, FINAL_MATRIX

    opts = dp.load_options()
    if not opts["long_composite_td_enabled"]:
        raise RuntimeError("TDLONG_COMPOSITE_DISABLED")
    if not opts["td_joint_enabled"] or opts["td_inner_mode"] != "DYNAMIC":
        raise RuntimeError("TDLONG_COMPOSITE_MEASURED_DYNAMIC_REQUIRED")
    outer = getattr(bridge, "outer_adapter", None)
    if (outer is None or getattr(bridge, "dynamic_skim_enabled", False) is not True
            or not getattr(outer, "_long_post_td_mask_enabled", False)):
        raise RuntimeError("TDLONG_COMPOSITE_NATIVE_REALIZATION_UNAVAILABLE")
    if getattr(bridge, "_v24917_frozen", False):
        raise RuntimeError("TDLONG_COMPOSITE_FROZEN_PATH_COUNT_RESPONSE_FORBIDDEN")
    skim = getattr(outer, "v24916_dynamic_skims", None)
    if skim is None or not callable(getattr(skim, "require_current", None)):
        raise RuntimeError("TDLONG_COMPOSITE_FRESH_ASSIGNMENT_EPOCH_REQUIRED")
    epoch = skim.require_current()
    if epoch is None or getattr(epoch, "family_distance", {}).get("LONG") is None:
        raise RuntimeError("TDLONG_COMPOSITE_NATIVE_CL_SKIM_NOT_CURRENT")
    if getattr(epoch, "assignment_epoch", None) is None:
        raise RuntimeError("TDLONG_COMPOSITE_ASSIGNMENT_EPOCH_UNVERIFIED")
    distance, support = read_current(outer)
    mask = np.asarray(distance >= MIN_KM, dtype=bool)
    _verify_support(outer, mask, MATRIX_NOS + COMPONENT_MATRICES + (FINAL_MATRIX,))
    components = [np.asarray(_read(outer, n)[1], dtype=np.float64)
                  for n in COMPONENT_MATRICES]
    final = np.asarray(_read(outer, FINAL_MATRIX)[1], dtype=np.float64)
    if not np.allclose(sum(components, np.zeros_like(final)), final,
                       rtol=1e-8, atol=1e-6):
        raise RuntimeError("TDLONG_COMPOSITE_FINAL_9305_COMPONENT_PARITY_FAILED")
    if float(final.sum()) <= 0.0:
        raise RuntimeError("TDLONG_COMPOSITE_NO_POSITIVE_VEHICLE_DEMAND")
    return {"status": "READY_CURRENT_NATIVE_DYNAMIC_COUNT_RESPONSE",
            "group": GROUP, "component_matrix_nos": list(MATRIX_NOS),
            "vehicle_component_matrix_nos": list(COMPONENT_MATRICES),
            "final_vehicle_matrix_no": FINAL_MATRIX,
            "count_response_method": "MEASURED_NATIVE_ASSIGNMENT_EVERY_TD_EVALUATION",
            "assignment_epoch": int(epoch.assignment_epoch),
            "skim_epoch_hash": getattr(epoch, "epoch_hash", None),
            "support_basis": support,
            "minimum_km": MIN_KM, "finecdf_conditional_km": [MIN_CDF_KM, MAX_CDF_KM],
            "above_200_km_permitted": True,
            "aggregate_target_count": 1,
            "vehicle_volume": float(final.sum()),
            "source_model_modified": False}


def require_live_ready(groups, bridge=None):
    """Require positive native proof, not a caller-provided enabled flag."""
    if any(name == GROUP for name, _ in groups):
        if bridge is None:
            raise RuntimeError("TDLONG_COMPOSITE_LONG_COUNT_RESPONSE_UNVERIFIED")
        return live_readiness(bridge)
    return None
