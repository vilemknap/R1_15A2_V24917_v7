# -*- coding: utf-8 -*-
"""LONGGUARD1: non-mutating 80+ km admissibility proof for live LONG generation.

The existing LONG_COMPOSITE FineCDF is CONDITIONAL on 100..200 km.  It
cannot detect demand generated below 100 km or above 200 km.  This guard
measures all five 9111..9115 LONG OD matrices against the current
fixed OSRM 9697/R1_OSRM_DIST_KM matrix.  >200 km is legal and never dropped.

This is an acceptance guard, NOT an OD writer and NOT a native structural
support mask.  If the parent already contains <80 km mass, further LONG
production steps must be deferred until the native TD support is corrected;
other generation families may proceed only without increasing short mass.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

RELEASE = "R1_15A2_V24917_LONGGUARD1_20261027"
MATRIX_NOS = (9111, 9112, 9113, 9114, 9115)
MIN_KM = 80.0
MIN_CDF_KM = 100.0
MAX_CDF_KM = 200.0  # only an IDP-conditioned CDF boundary, NOT a trip upper bound
MASS_ATOL = 1.0e-6
FINE_RMSE_ATOL = 0.002
FINE_RMSE_RTOL = 0.05


def _finite_array(value: Any, n: int, label: str) -> np.ndarray:
    data = np.asarray(value, dtype=np.float64)
    if data.shape != (n, n):
        raise ValueError("LONGGUARD1_SHAPE:%s:%r" % (label, data.shape))
    if not np.isfinite(data).all() or float(data.min()) < -1.0e-10:
        raise ValueError("LONGGUARD1_INVALID_VALUES:" + label)
    return np.maximum(data, 0.0)


def measure(distance: Any, matrices: Mapping[int, Any], *, epoch: Mapping[str, Any] = None) -> dict:
    """Pure volume-conservation audit. Total = forbidden + allowed 80..100 + conditional 100..200 + tail."""
    dist = np.asarray(distance, dtype=np.float64)
    if dist.ndim != 2 or dist.shape[0] != dist.shape[1] or not len(dist):
        raise ValueError("LONGGUARD1_DIST_SHAPE")
    n = int(dist.shape[0])
    if not np.isfinite(dist).all() or float(dist.min()) < -1.0e-10:
        raise ValueError("LONGGUARD1_DIST_NOT_FINITE_NONNEGATIVE")
    missing = sorted(set(MATRIX_NOS) - {int(k) for k in matrices})
    if missing:
        raise ValueError("LONGGUARD1_MISSING_LONG_MATRICES:" + repr(missing))
    all_long = np.zeros_like(dist, dtype=np.float64)
    by_matrix = []
    short = dist < MIN_KM
    mid = (dist >= MIN_CDF_KM) & (dist <= MAX_CDF_KM)
    tolerance_band = (dist >= MIN_KM) & (dist < MIN_CDF_KM)
    tail = dist > MAX_CDF_KM
    for no in MATRIX_NOS:
        values = _finite_array(matrices[no], n, "M%d" % no)
        all_long += values
        by_matrix.append({"matrix_no": no, "total": float(values.sum()),
                          "below_min_km": float(values[short].sum()),
                          "below_100_km": float(values[dist < MIN_CDF_KM].sum()),
                          "allowed_below_cdf_min_km": float(values[tolerance_band].sum()),
                          "km_100_to_200": float(values[mid].sum()),
                          "above_200_km": float(values[tail].sum())})
    total = float(all_long.sum())
    a = float(all_long[short].sum()); b = float(all_long[mid].sum()); c = float(all_long[tail].sum())
    tolerance_mass = float(all_long[tolerance_band].sum())
    if not math.isclose(a + tolerance_mass + b + c, total, rel_tol=1.0e-10, abs_tol=MASS_ATOL):
        raise ValueError("LONGGUARD1_NONCONSERVATIVE_VOLUME")
    return {"status": "MEASURED", "release": RELEASE, "distance_basis": "FIXED_OSRM_DIST_KM_9697",
            "minimum_km": MIN_KM, "long_above_200_permitted": True,
            "conditional_100_200_is_not_full_long_support": True,
            "total_volume": total, "below_min_km": a,
            "below_100_km": float(all_long[dist < MIN_CDF_KM].sum()),
            "allowed_below_cdf_min_km": tolerance_mass, "km_100_to_200": b,
            "above_200_km": c, "below_min_share": a / total if total > 0 else 0.0,
            "support_clean": bool(a <= MASS_ATOL), "by_matrix": by_matrix,
            "epoch": dict(epoch or {})}


def _fine_rmse(diag: Mapping[str, Any]) -> float | None:
    d11 = ((diag or {}).get("d11") or {}).get("summary") or {}
    rows = d11.get("component_dist_summary_rows") or []
    rows = [r for r in rows if r.get("component") == "LONG_COMPOSITE"]
    if len(rows) != 1:
        return None
    value = rows[0].get("dynamic_fine_cdf_rmse")
    if value is None:
        return None
    try:
        x = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return x if math.isfinite(x) and x >= 0.0 else None


def capture(adapter: Any, diag: Mapping[str, Any]) -> dict:
    """Read live LONG matrices; fail with explicit UNVERIFIED, never assume zero."""
    try:
        manager = getattr(adapter, "v24916_dynamic_skims", None)
        if manager is None:
            raise RuntimeError("LONGGUARD1_DYNAMIC_SKIMS_UNAVAILABLE")
        epoch = manager.require_current()
        distance = epoch.family_distance.get("LONG")
        if distance is None or "NATIVE_CL" not in epoch.matrix_meta_by_dseg:
            raise RuntimeError("LONGGUARD1_NATIVE_CL_DIS_MISSING")
        if str(epoch.matrix_meta_by_dseg["NATIVE_CL"].get("unit", "")).lower() != "km":
            raise RuntimeError("LONGGUARD1_NATIVE_CL_DIS_NOT_KM")
        from r1_15a2_skim_v24916p2c import ordered_zone_hash
        if ordered_zone_hash(adapter.zones) != epoch.zone_order_sha256:
            raise RuntimeError("LONGGUARD1_ZONE_ORDER_MISMATCH")
        # A CDF from a different assignment/skim epoch cannot certify the
        # live diagnostics. The fixed OSRM support has a separate identity.
        diag_epoch = (diag or {}).get("dynamic_skim_epoch") or (
            ((((diag or {}).get("d11") or {}).get("summary") or {})
             .get("dynamic_distance_authority")) or {})
        if diag_epoch.get("epoch_hash") != epoch.epoch_hash:
            raise RuntimeError("LONGGUARD1_DIAGNOSTICS_NOT_BOUND_TO_CL_SKIM_EPOCH")
        from r1_15a2_long_support_distance_v24917 import read_current
        distance, support_source = read_current(adapter)
        from r1_15a2_long_post_td_mask_v24917 import _read
        matrices = {}
        for no in MATRIX_NOS:
            matrices[no] = _read(adapter, no)[1]
        proof = measure(distance, matrices, epoch={
            "assignment_epoch": int(epoch.assignment_epoch),
            "skim_epoch": int(epoch.epoch),
            "skim_epoch_hash": epoch.epoch_hash,
            "zone_order_sha256": epoch.zone_order_sha256,
            "finecdf_native_cl_values_sha256": epoch.matrix_meta_by_dseg["NATIVE_CL"].get("values_sha256")})
        proof["support_distance_source"] = support_source
        # The 512-point curve still uses the fresh native skim; support uses OSRM.
        proof["fine_100_200_rmse"] = _fine_rmse(diag)
        proof["fine_cdf_verified"] = proof["fine_100_200_rmse"] is not None
        proof["long_generation_permitted"] = bool(proof["support_clean"] and
                                                    proof["fine_cdf_verified"] and
                                                    proof["total_volume"] > 0)
        return proof
    except Exception as exc:
        return {"status": "UNVERIFIED", "release": RELEASE, "long_generation_permitted": False,
                "fine_cdf_verified": False, "error": "%s:%s" % (type(exc).__name__, str(exc)[:700]),
                "long_above_200_permitted": True}


def decide(parent: Mapping[str, Any], candidate: Mapping[str, Any],
           *, changed_long: bool) -> dict:
    """Conservative live gate; the caller rejects, backtracks and rolls back."""
    reasons = []
    if not changed_long and parent.get("status") != "MEASURED":
        # The LONG lever has already been excluded before the trial. Do not
        # reject otherwise valid WORK/SERVICE merely because the CL skim was
        # unreadable at the parent. The outer cycle remains INCOMPLETE.
        return {"passes": True, "reasons": [], "changed_long": False,
                "status": "DEFER_LONG_ALLOW_OTHER_FAMILIES_PARENT_UNVERIFIED",
                "parent_status": parent.get("status"),
                "candidate_status": candidate.get("status"),
                "long_distance_authority_verified": False}
    if candidate.get("status") != "MEASURED":
        reasons.append("LONGGUARD1_CANDIDATE_UNVERIFIED")
    if changed_long and not parent.get("long_generation_permitted"):
        reasons.append("LONGGUARD1_PARENT_NOT_ADMISSIBLE_FOR_LONG_GENERATION")
    if parent.get("status") == "MEASURED" and candidate.get("status") == "MEASURED":
        b = float(parent["below_min_km"]); a = float(candidate["below_min_km"])
        if b <= MASS_ATOL:
            if a > MASS_ATOL:
                reasons.append("LONGGUARD1_NEW_TRIPS_BELOW_MIN_KM")
        elif a > b + MASS_ATOL:
            reasons.append("LONGGUARD1_SHORT_TRIPS_INCREASED_FROM_INVALID_PARENT")
        if changed_long:
            before = parent.get("fine_100_200_rmse")
            after = candidate.get("fine_100_200_rmse")
            if before is None or after is None:
                reasons.append("LONGGUARD1_512_CDF_UNVERIFIED")
            elif after > before * (1.0 + FINE_RMSE_RTOL) + FINE_RMSE_ATOL:
                reasons.append("LONGGUARD1_512_CDF_DEGRADED")
            anchor = parent.get("fine_cdf_anchor_rmse")
            if anchor is not None and after is not None and after > (
                    float(anchor) * (1.0 + FINE_RMSE_RTOL) + FINE_RMSE_ATOL):
                reasons.append("LONGGUARD1_512_CDF_RUN_ANCHOR_DEGRADED")
    elif changed_long or parent.get("status") != "MEASURED":
        reasons.append("LONGGUARD1_PARENT_OR_CANDIDATE_UNVERIFIED")
    return {"passes": not reasons, "reasons": reasons, "changed_long": bool(changed_long),
            "parent_status": parent.get("status"), "candidate_status": candidate.get("status"),
            "parent_below_min_km": parent.get("below_min_km"),
            "parent_below_100_km": parent.get("below_100_km"),
            "candidate_below_min_km": candidate.get("below_min_km"),
            "candidate_below_100_km": candidate.get("below_100_km"),
            "parent_fine_rmse": parent.get("fine_100_200_rmse"),
            "candidate_fine_rmse": candidate.get("fine_100_200_rmse")}


def changed_long(rows: Any) -> bool:
    return any(str(r.get("attr", "")).upper() in ("ADD_PROD_L", "ADD_ATT_L")
               for r in (rows or []) if isinstance(r, Mapping))


__all__ = ["RELEASE", "MATRIX_NOS", "MIN_KM", "measure", "capture", "decide", "changed_long"]
