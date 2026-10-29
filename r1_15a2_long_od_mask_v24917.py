# -*- coding: utf-8 -*-
"""LONG OD support and restricted P/A feasibility checks.

The live support mask uses fixed OSRM matrix 9697/R1_OSRM_DIST_KM.
The older pure epoch-bound builder is retained for compatibility only.  It never writes demand matrices and the mask alone is
not native enforcement evidence.  Native LONG generation remains disabled
until the actual Visum TD support mechanism is verified on the live model.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import math
import re
from typing import Any, Mapping, Sequence

import numpy as np

from r1_15a2_long_distance_guard_v24917 import MATRIX_NOS, MIN_KM, MIN_CDF_KM, MAX_CDF_KM

RELEASE = "R1_15A2_V24917_TDLONG1_PURE_MASK_20261027"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KM_UNITS = {"km", "kilometre", "kilometer", "kilometres", "kilometers"}


@dataclass(frozen=True)
class LongSupport:
    """Immutable support and project-authority hashes for one skim epoch."""

    mask: np.ndarray
    zone_nos: tuple[int, ...]
    values_sha256: str
    zone_order_sha256: str
    epoch_hash: str
    assignment_epoch: int
    skim_epoch: int
    mask_sha256_diagnostic_only: str
    counts: Mapping[str, int]

    def summary(self) -> dict[str, Any]:
        return {
            "release": RELEASE,
            "status": "MASK_READY_NATIVE_FILTER_UNVERIFIED",
            "minimum_km": float(MIN_KM),
            "conditional_cdf_range_km": [float(MIN_CDF_KM), float(MAX_CDF_KM)],
            "above_200_km_permitted": True,
            "counts": dict(self.counts),
            "zone_order_sha256": self.zone_order_sha256,
            "native_cl_dis_values_sha256": self.values_sha256,
            "skim_epoch_hash": self.epoch_hash,
            "skim_epoch": int(self.skim_epoch),
            "assignment_epoch": int(self.assignment_epoch),
            "mask_sha256": self.mask_sha256_diagnostic_only,
            "mask_hash_role": "DIAGNOSTIC_ONLY_NOT_A_PROJECT_AUTHORITY",
            "native_filter_verified": False,
            "long_generation_permitted": False,
        }


def _strict_zone_axis(zone_nos: Sequence[int]) -> tuple[int, ...]:
    result = []
    for value in zone_nos:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise ValueError("TDLONG1_INVALID_ZONE_ID")
        zone = int(value)
        if zone <= 0:
            raise ValueError("TDLONG1_INVALID_ZONE_ID")
        result.append(zone)
    if not result:
        raise ValueError("TDLONG1_EMPTY_ZONE_AXIS")
    if len(set(result)) != len(result):
        raise ValueError("TDLONG1_DUPLICATE_ZONE_ID")
    return tuple(result)


def build_support_mask(distance_km: Any, zone_nos: Sequence[int], *, unit: str,
                       expected_values_sha256: str, expected_zone_order_sha256: str,
                       epoch_hash: str, assignment_epoch: int, skim_epoch: int,
                       diagnostic_epoch_hash: str,
                       diagnostic_assignment_epoch: int) -> LongSupport:
    """Build exact ``distance >= MIN_KM`` support and verify both skim axes.

    ``expected_*`` fields must come from the existing V24916 dynamic skim
    authority.  The function also recomputes both project hashes, making stale
    or altered arrays fail closed.  The input is copied and never modified.
    """
    zones = _strict_zone_axis(zone_nos)
    normalized_unit = str(unit).strip().lower()
    if normalized_unit not in _KM_UNITS:
        raise ValueError("TDLONG1_DISTANCE_UNIT_NOT_KM")
    for label, value in (("values", expected_values_sha256),
                         ("zone", expected_zone_order_sha256),
                         ("epoch", epoch_hash),
                         ("diagnostic_epoch", diagnostic_epoch_hash)):
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            raise ValueError("TDLONG1_INVALID_%s_HASH" % label.upper())
    try:
        assignment_epoch = int(assignment_epoch)
        skim_epoch = int(skim_epoch)
        diagnostic_assignment_epoch = int(diagnostic_assignment_epoch)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("TDLONG1_INVALID_EPOCH") from exc
    if assignment_epoch < 0 or skim_epoch < 0 or diagnostic_assignment_epoch < 0:
        raise ValueError("TDLONG1_INVALID_EPOCH")
    if diagnostic_epoch_hash != epoch_hash or diagnostic_assignment_epoch != assignment_epoch:
        raise ValueError("TDLONG1_DIAGNOSTIC_EPOCH_MISMATCH")

    from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash

    if ordered_zone_hash(zones) != expected_zone_order_sha256:
        raise ValueError("TDLONG1_ZONE_ORDER_HASH_MISMATCH")
    distance = np.array(distance_km, dtype=np.float64, copy=True, order="C")
    if distance.shape != (len(zones), len(zones)):
        raise ValueError("TDLONG1_DISTANCE_SHAPE_MISMATCH")
    if not np.isfinite(distance).all() or np.any(distance < 0.0):
        raise ValueError("TDLONG1_DISTANCE_NOT_FINITE_NONNEGATIVE")
    actual_values_hash = matrix_values_hash(distance)
    if actual_values_hash != expected_values_sha256:
        raise ValueError("TDLONG1_DISTANCE_VALUES_HASH_MISMATCH")

    mask, diagnostic_hash, counts = _mask_geometry(distance, zones, expected_zone_order_sha256)
    return LongSupport(mask=mask, zone_nos=zones,
                       values_sha256=actual_values_hash,
                       zone_order_sha256=expected_zone_order_sha256,
                       epoch_hash=epoch_hash, assignment_epoch=assignment_epoch,
                       skim_epoch=skim_epoch,
                       mask_sha256_diagnostic_only=diagnostic_hash, counts=counts)


def _mask_geometry(distance, zones, expected_zone_order_sha256):
    mask = np.greater_equal(distance, float(MIN_KM))
    mask.setflags(write=False)
    below = distance < float(MIN_KM)
    conditional = (distance >= float(MIN_CDF_KM)) & (distance <= float(MAX_CDF_KM))
    above = distance > float(MAX_CDF_KM)
    packed = np.packbits(mask, bitorder="little")
    diagnostic_hash = hashlib.sha256(
        ("%dx%d|%s|" % (len(zones), len(zones), expected_zone_order_sha256)).encode("ascii")
        + packed.tobytes()).hexdigest()
    counts = {
        "allowed_ge_min_km": int(np.count_nonzero(mask)),
        "below_min_km": int(np.count_nonzero(below)),
        "allowed_below_cdf_min_km": int(np.count_nonzero((distance >= MIN_KM) & (distance < MIN_CDF_KM))),
        "km_100_to_200_inclusive": int(np.count_nonzero(conditional)),
        "above_200_km_allowed": int(np.count_nonzero(above)),
        "total_od_pairs": int(distance.size),
    }
    if counts["allowed_ge_min_km"] + counts["below_min_km"] != counts["total_od_pairs"]:
        raise ValueError("TDLONG1_SUPPORT_COUNT_NONCONSERVATIVE")
    return mask, diagnostic_hash, counts


def _marginal(values: Any, n: int, label: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.shape != (n,):
        raise ValueError("TDLONG1_MARGINAL_SHAPE:%s" % label)
    if not np.isfinite(result).all() or np.any(result < 0.0):
        raise ValueError("TDLONG1_MARGINAL_INVALID:%s" % label)
    return np.array(result, dtype=np.float64, copy=True)


def _finite_sum(values: np.ndarray, label: str) -> float:
    try:
        total = math.fsum(float(x) for x in values)
    except (OverflowError, ValueError) as exc:
        raise ValueError("TDLONG1_MARGINAL_SUM_OVERFLOW:%s" % label) from exc
    if not math.isfinite(total):
        raise ValueError("TDLONG1_MARGINAL_SUM_OVERFLOW:%s" % label)
    return total


def _restricted_max_flow(mask: np.ndarray, production: np.ndarray,
                         attraction: np.ndarray, tolerance: float) -> dict[str, Any]:
    """Dense-residual push/relabel on the bipartite graph, O(Z²) memory.

    The only dense arrays are the OD support and one (2Z+2)² residual matrix;
    no profile-by-OD tensor is formed.  This computes the exact maximum flow
    up to the supplied numeric tolerance.
    """
    n = len(production)
    total = _finite_sum(production, "production")
    sink_total = _finite_sum(attraction, "attraction")
    scale = max(total, sink_total)
    tol = float(tolerance) * max(1.0, scale)
    if abs(total - sink_total) > tol:
        return {"feasible": False, "reason": "UNEQUAL_TOTALS", "total_production": total,
                "total_attraction": sink_total, "mass_shortfall": abs(total-sink_total),
                "witness": {"kind": "MARGINAL_TOTALS"}}
    if total <= tol:
        return {"feasible": True, "reason": "FEASIBLE", "total_production": total,
                "total_attraction": sink_total, "max_flow": 0.0, "mass_shortfall": 0.0,
                "witness": None}

    source, sink = 0, 2*n+1
    node_count = sink + 1
    origins = np.arange(1, n+1)
    destinations = np.arange(n+1, 2*n+1)
    residual = np.zeros((node_count, node_count), dtype=np.float64)
    residual[source, origins] = production
    residual[destinations, sink] = attraction
    residual[np.ix_(origins, destinations)] = np.where(mask, total, 0.0)

    height = np.zeros(node_count, dtype=np.int64)
    height[source] = node_count
    excess = np.zeros(node_count, dtype=np.float64)
    current = np.zeros(node_count, dtype=np.int64)
    in_queue = np.zeros(node_count, dtype=bool)
    queue = deque()
    for origin in origins:
        amount = residual[source, origin]
        if amount > 0.0:
            residual[source, origin] = 0.0
            residual[origin, source] = amount
            excess[origin] = amount
            queue.append(int(origin)); in_queue[origin] = True

    while queue:
        u = queue.popleft(); in_queue[u] = False
        while excess[u] > tol:
            v = int(current[u])
            if v >= node_count:
                neighbors = np.flatnonzero(residual[u] > 0.0)
                if not len(neighbors):
                    break
                height[u] = int(np.min(height[neighbors])) + 1
                current[u] = 0
                continue
            cap = residual[u, v]
            if cap > 0.0 and height[u] == height[v] + 1:
                amount = min(excess[u], cap)
                residual[u, v] -= amount
                residual[v, u] += amount
                excess[u] -= amount
                was_inactive = excess[v] <= tol
                excess[v] += amount
                if v not in (source, sink) and was_inactive and excess[v] > tol and not in_queue[v]:
                    queue.append(v); in_queue[v] = True
            else:
                current[u] += 1

    max_flow = float(excess[sink])
    shortfall = max(0.0, total - max_flow)
    feasible = shortfall <= tol
    witness = None
    if not feasible:
        reachable = np.zeros(node_count, dtype=bool)
        reachable[source] = True
        todo = deque([source])
        while todo:
            u = todo.popleft()
            for v in np.flatnonzero(residual[u] > 0.0):
                if not reachable[v]:
                    reachable[v] = True; todo.append(int(v))
        # Use explicit sliced node identities for a stable Hall/min-cut witness.
        origin_idx = np.flatnonzero(reachable[1:n+1])
        neighbor_idx = np.flatnonzero(mask[origin_idx].any(axis=0)) if len(origin_idx) else np.array([], dtype=int)
        witness = {
            "kind": "RESIDUAL_MIN_CUT",
            "origin_indices": [int(x) for x in origin_idx],
            "destination_indices": [int(x) for x in neighbor_idx],
            "origin_production": _finite_sum(production[origin_idx], "witness_production"),
            "neighbor_attraction": _finite_sum(attraction[neighbor_idx], "witness_attraction"),
            "isolated_origins": [int(x) for x in np.flatnonzero((production > tol) & ~mask.any(axis=1))],
            "isolated_destinations": [int(x) for x in np.flatnonzero((attraction > tol) & ~mask.any(axis=0))],
        }
    return {"feasible": bool(feasible), "reason": "FEASIBLE" if feasible else "INFEASIBLE_PA",
            "total_production": total, "total_attraction": sink_total,
            "max_flow": max_flow, "mass_shortfall": shortfall, "tolerance": tol,
            "witness": witness}


def check_restricted_pa_feasibility(support: Any,
                                   component_marginals: Mapping[int, Mapping[str, Any]], *,
                                   zone_nos: Sequence[int] | None = None,
                                   symmetry_safe: bool = False,
                                   relative_tolerance: float = 1.0e-10) -> dict[str, Any]:
    """Check exact bipartite feasibility separately for LONG matrices 9111-9115.

    ``symmetry_safe=True`` uses ``support & support.T`` as a conservative
    pre-TD restriction for the 20B V7 domestic return process. Its BOUNDED_IPF
    seed adds reverse support, and the 1.5:1 direction cap retains both sides
    of a positive pair. This precheck alone is not a proof of final support:
    20B can also repair tiny IPF support, so its actual output and downstream
    matrices must be checked against the original distance mask. No demand
    mass is added or moved by this function.
    """
    mask = np.asarray(support, dtype=bool)
    if mask.ndim != 2 or mask.shape[0] != mask.shape[1] or not len(mask):
        raise ValueError("TDLONG1_SUPPORT_SHAPE")
    mask = np.array(mask, dtype=bool, copy=True)
    if zone_nos is None:
        zones = tuple(range(1, len(mask)+1))
    else:
        zones = _strict_zone_axis(zone_nos)
    if len(zones) != len(mask):
        raise ValueError("TDLONG1_SUPPORT_ZONE_AXIS_MISMATCH")
    if not math.isfinite(float(relative_tolerance)) or relative_tolerance < 0.0:
        raise ValueError("TDLONG1_INVALID_FLOW_TOLERANCE")
    if symmetry_safe:
        mask &= mask.T
    expected = set(MATRIX_NOS)
    received = {int(no) for no in component_marginals}
    if received != expected:
        return {"status": "INVALID_MARGINS", "reason": "LONG_COMPONENT_SET_MISMATCH",
                "missing_components": sorted(expected-received),
                "unexpected_components": sorted(received-expected),
                "symmetry_safe": bool(symmetry_safe)}
    results = {}
    for no in MATRIX_NOS:
        item = component_marginals[no]
        try:
            production = _marginal(item.get("production"), len(mask), "M%d.production" % no)
            attraction = _marginal(item.get("attraction"), len(mask), "M%d.attraction" % no)
            result = _restricted_max_flow(mask, production, attraction, float(relative_tolerance))
            result["matrix_no"] = int(no)
            if result.get("witness") and "origin_indices" in result["witness"]:
                result["witness"]["origin_zones"] = [zones[i] for i in result["witness"]["origin_indices"]]
                result["witness"]["destination_zones"] = [zones[i] for i in result["witness"]["destination_indices"]]
                result["witness"]["isolated_origin_zones"] = [zones[i] for i in result["witness"]["isolated_origins"]]
                result["witness"]["isolated_destination_zones"] = [zones[i] for i in result["witness"]["isolated_destinations"]]
        except (TypeError, ValueError) as exc:
            result = {"matrix_no": int(no), "feasible": False, "reason": "INVALID_MARGINS",
                      "error": str(exc)}
        results[str(no)] = result
    feasible = all(bool(row.get("feasible")) for row in results.values())
    invalid = any(row.get("reason") == "INVALID_MARGINS" for row in results.values())
    status = "INVALID_MARGINS" if invalid else "FEASIBLE" if feasible else "INFEASIBLE_PA"
    return {"release": RELEASE, "status": status, "reason": status,
            "symmetry_safe": bool(symmetry_safe),
            "support_policy": "BIDIRECTIONAL_INTERSECTION" if symmetry_safe else "DIRECTED_EXACT_SUPPORT",
            "allowed_pairs": int(np.count_nonzero(mask)), "components": results,
            "native_filter_verified": False, "long_generation_permitted": False}


def build_osrm_support_mask(distance_km, zone_nos, *, expected_values_sha256,
                            expected_zone_order_sha256):
    """Pure fixed-OSRM mask; no assignment/skim epoch is invented for this source."""
    from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash
    from r1_15a2_long_support_distance_v24917 import MATRIX_NO, MATRIX_CODE, DISTANCE_BASIS
    zones = _strict_zone_axis(zone_nos)
    if ordered_zone_hash(zones) != expected_zone_order_sha256:
        raise ValueError("TDLONG1_OSRM_ZONE_ORDER_HASH_MISMATCH")
    distance = np.array(distance_km, dtype=np.float64, copy=True, order="C")
    if distance.shape != (len(zones), len(zones)):
        raise ValueError("TDLONG1_OSRM_DISTANCE_SHAPE_MISMATCH")
    if not np.isfinite(distance).all() or np.any(distance < 0):
        raise ValueError("TDLONG1_OSRM_DISTANCE_NOT_FINITE_NONNEGATIVE")
    if matrix_values_hash(distance) != expected_values_sha256:
        raise ValueError("TDLONG1_OSRM_DISTANCE_VALUES_HASH_MISMATCH")
    mask, diagnostic_hash, counts = _mask_geometry(distance, zones, expected_zone_order_sha256)
    summary = {"release": RELEASE, "status": "MASK_READY_NATIVE_FILTER_UNVERIFIED",
               "distance_basis": DISTANCE_BASIS, "matrix_no": MATRIX_NO,
               "matrix_code": MATRIX_CODE, "unit": "km", "assignment_dependent": False,
               "minimum_km": MIN_KM, "conditional_cdf_range_km": [MIN_CDF_KM, MAX_CDF_KM],
               "above_200_km_permitted": True, "counts": counts,
               "values_sha256": expected_values_sha256,
               "zone_order_sha256": expected_zone_order_sha256,
               "mask_sha256": diagnostic_hash,
               "mask_hash_role": "DIAGNOSTIC_ONLY_NOT_A_PROJECT_AUTHORITY",
               "native_filter_verified": False, "long_generation_permitted": False}
    return mask, summary


def capture_current(adapter: Any, diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    """Read the selected fixed OSRM source, independently of dynamic IDP skims."""
    try:
        from r1_15a2_long_support_distance_v24917 import read_current
        distance, source = read_current(adapter)
        _, summary = build_osrm_support_mask(distance, adapter.zones,
            expected_values_sha256=source["values_sha256"],
            expected_zone_order_sha256=source["zone_order_sha256"])
        return {"status": "MASK_READY_NATIVE_FILTER_UNVERIFIED",
                "source": summary, "native_filter_status": "UNVERIFIED_NATIVE_FILTER",
                "long_generation_permitted": False}
    except Exception as exc:
        return {"status": "INVALID_SOURCE", "reason": "INVALID_SOURCE",
                "native_filter_status": "UNVERIFIED_NATIVE_FILTER",
                "long_generation_permitted": False,
                "error": "%s:%s" % (type(exc).__name__, str(exc)[:700])}


__all__ = ["RELEASE", "LongSupport", "build_support_mask",
           "check_restricted_pa_feasibility", "build_osrm_support_mask", "capture_current"]
