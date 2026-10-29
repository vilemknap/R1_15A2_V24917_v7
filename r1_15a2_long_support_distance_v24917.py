"""Fixed OSRM distance authority for LONG support, independent of IDP skims."""
from __future__ import annotations

import numpy as np

from r1_15a2_com_compat import com_call_with_retry
from r1_15a2_skim_v24916 import zone_numbers
from r1_15a2_skim_v24916p2c import ordered_zone_hash
from r1_15a2_path_incidence_v24917 import matrix_values_hash

MATRIX_NO = 9697
MATRIX_CODE = "R1_OSRM_DIST_KM"
DISTANCE_BASIS = "FIXED_OSRM_DIST_KM_9697"


def read_current(adapter):
    """Read only the user-selected source and pin its identity within this run.

    GetValues uses Visum's zone collection order. Check that order before and
    after reading; never substitute a native DIS matrix when OSRM is missing.
    Kilometres are the explicitly selected R1_OSRM_DIST_KM source contract.
    Only hashes are retained on the adapter, not another full matrix cache.
    """
    retry = getattr(adapter, "com_retry_policy", None) or {}
    def call(fn, label):
        return com_call_with_retry(fn, label="LONG_OSRM:" + label, retry_policy=retry)
    zones = list(adapter.zones)
    if zone_numbers(adapter.visum, retry) != zones:
        raise ValueError("LONG_OSRM_ZONE_ORDER_MISMATCH")
    matrix = call(lambda: adapter.visum.Net.Matrices.ItemByKey(MATRIX_NO), "LOOKUP")
    def identity():
        no = float(call(lambda: matrix.AttValue("NO"), "NO"))
        code = str(call(lambda: matrix.AttValue("CODE"), "CODE")).strip().upper()
        if no != MATRIX_NO or code != MATRIX_CODE:
            raise ValueError("LONG_OSRM_MATRIX_IDENTITY_MISMATCH")
    identity()
    distance = np.array(call(matrix.GetValues, "VALUES"), dtype=np.float64, copy=True, order="C")
    if distance.shape != (len(zones), len(zones)) or not len(zones):
        raise ValueError("LONG_OSRM_DISTANCE_SHAPE")
    if not np.isfinite(distance).all() or np.any(distance < 0):
        raise ValueError("LONG_OSRM_DISTANCE_NOT_FINITE_NONNEGATIVE")
    identity()
    if zone_numbers(adapter.visum, retry) != zones:
        raise ValueError("LONG_OSRM_ZONE_ORDER_CHANGED_DURING_READ")
    source = {"distance_basis": DISTANCE_BASIS, "matrix_no": MATRIX_NO,
              "matrix_code": MATRIX_CODE, "unit": "km",
              "unit_authority": "USER_SELECTED_R1_OSRM_DIST_KM_CONTRACT",
              "values_sha256": matrix_values_hash(distance),
              "zone_order_sha256": ordered_zone_hash(zones),
              "assignment_dependent": False}
    anchor = getattr(adapter, "_long_osrm_support_anchor", None)
    if anchor is not None and source != anchor:
        raise ValueError("LONG_OSRM_DISTANCE_CHANGED_DURING_RUN")
    adapter._long_osrm_support_anchor = dict(source)
    distance.flags.writeable = False
    return distance, source
