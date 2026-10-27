# -*- coding: utf-8 -*-
"""Assignment-coupled PrT distance skims for V24916/PERF2C.

Scientific contract
-------------------
The static R1_OSRM_DIST_KM matrix is *not* an active calibration authority on a
congested network.  Every TD candidate must be realized on the loaded network,
then the configured native PrT skim operations are executed from the resulting
assignment paths.  The resulting DIS matrices are bound to that exact
assignment epoch and are the distance basis for IDP/FineCDF evaluation.

This module does not alter b/c, P/A, OD matrices, VDFs, or acceptance
thresholds.  It only orchestrates an already-configured Procedure Sequence and
reads its skim results.  ACTIVE flags are restored exactly by the caller/bridge.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import json
import math

import numpy as np

import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_runtime_v1 as rt
from r1_15a2_supply import SupplyContractError
from r1_15a2_skim_v24916 import matrix_inventory
from r1_15a2_skim_v24916p2c import matrix_values_hash, ordered_zone_hash

SCHEMA = "R1_15A2_V24916_DYNAMIC_ASSIGNMENT_SKIM_V1"

# All passenger-native families present in the current R1 model.  FOREIGN is
# retained for provenance/parity even though the domestic IDP objective does
# not calibrate it.
REQUIRED_NATIVE_DSEGS = (
    "NATIVE_CW", "NATIVE_CW_NOT", "NATIVE_CS", "NATIVE_CS_NOT",
    "NATIVE_CL", "NATIVE_CF",
)
IDP_NATIVE_DSEGS = REQUIRED_NATIVE_DSEGS[:-1]


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()


def _call(adapter: Any, fn, label: str):
    return com.com_call_with_retry(
        fn, label=label,
        retry_policy=getattr(adapter, "com_retry_policy", None) or
        (getattr(adapter, "cfg", {}) or {}).get("com_resilience", {}) or {})


def _matrix_values(adapter: Any, no: int, n: int, label: str) -> np.ndarray:
    obj = _call(adapter, lambda: adapter.visum.Net.Matrices.ItemByKey(int(no)),
                "Matrices.ItemByKey[%s:%s]" % (label, no))
    raw = _call(adapter, lambda: obj.GetValues(), "Matrix.GetValues[%s:%s]" % (label, no))
    a = np.asarray(raw, dtype=np.float64)
    if a.shape != (n, n):
        raise SupplyContractError(
            "V24916_DYNAMIC_SKIM_SHAPE_MISMATCH:%s:%r" % (label, a.shape))
    if not np.isfinite(a).all():
        raise SupplyContractError("V24916_DYNAMIC_SKIM_NONFINITE:" + label)
    if float(np.min(a)) < -1.0e-10:
        raise SupplyContractError("V24916_DYNAMIC_SKIM_NEGATIVE:" + label)
    # Do not retain a COM SAFEARRAY/nested list; keep one compact float64 array.
    return np.array(a, dtype=np.float64, copy=True, order="C")


def _native_dis_rows(adapter: Any) -> dict[str, dict[str, Any]]:
    rows = matrix_inventory(adapter.visum, getattr(adapter, "com_retry_policy", None))
    found: dict[str, dict[str, Any]] = {}
    duplicates: dict[str, list[int]] = {}
    for row in rows:
        if str(row.get("matrix_code_norm", "")) != "DIS":
            continue
        dseg = core.norm_code(row.get("dseg_code_norm", ""))
        if dseg not in REQUIRED_NATIVE_DSEGS:
            continue
        no = row.get("matrix_no_int")
        if no is None:
            continue
        if dseg in found:
            duplicates.setdefault(dseg, [int(found[dseg]["matrix_no_int"])]).append(int(no))
        else:
            found[dseg] = row
    if duplicates:
        detail = ";".join("%s=%s" % (k, ",".join(map(str, v)))
                          for k, v in sorted(duplicates.items()))
        raise SupplyContractError("V24916_DYNAMIC_SKIM_DUPLICATE_DIS_MATRIX:" + detail)
    missing = [d for d in REQUIRED_NATIVE_DSEGS if d not in found]
    if missing:
        raise SupplyContractError("V24916_DYNAMIC_SKIM_REQUIRED_DIS_MISSING:" + ",".join(missing))
    return found


def active_native_skim_positions(visum: Any) -> tuple[list[int], list[int]]:
    """Return active PrT-skim positions and active group positions.

    We intentionally do not guess a COM parameter object/member name for skim
    operations.  The live model itself already owns the configured six native
    PrT skim procedures.  Scientific identity is verified on the *resulting*
    DIS matrices by exact DSEG code after execution.
    """
    rows = com.operation_rows(visum)
    skim = [int(r["no"]) for r in rows
            if int(r["active"]) and int(r["type"]) == com.SKIMS_PRT]
    groups = [int(r["no"]) for r in rows
              if int(r["active"]) and int(r["type"]) == com.GROUP]
    if len(skim) != len(REQUIRED_NATIVE_DSEGS):
        raise SupplyContractError(
            "V24916_DYNAMIC_SKIM_EXPECTED_6_ACTIVE_PRT_SKIMS_FOUND_%d" % len(skim))
    return sorted(skim), sorted(groups)


@dataclass(frozen=True)
class DynamicSkimEpoch:
    schema: str
    epoch: int
    assignment_epoch: int
    assignment_token: str
    zone_order_sha256: str
    operation_positions: tuple[int, ...]
    matrices_by_dseg: Mapping[str, np.ndarray]
    matrix_meta_by_dseg: Mapping[str, Mapping[str, Any]]
    family_distance: Mapping[str, np.ndarray]
    family_hashes: Mapping[str, str]
    epoch_hash: str

    def summary(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "epoch": self.epoch,
            "assignment_epoch": self.assignment_epoch,
            "assignment_token": self.assignment_token,
            "zone_order_sha256": self.zone_order_sha256,
            "operation_positions": list(self.operation_positions),
            "matrix_meta_by_dseg": {k: dict(v) for k, v in self.matrix_meta_by_dseg.items()},
            "family_hashes": dict(self.family_hashes),
            "epoch_hash": self.epoch_hash,
            "role": "ACTIVE_TD_CALIBRATION_DISTANCE_AUTHORITY",
            "static_r1_osrm_dist_km_role": "REFERENCE_ONLY_NOT_ACTIVE_CALIBRATION",
            "source": "VISUM_FRESH_ASSIGNMENT_PATHS_PRT_DIS",
        }


def _weighted_pair(a_dist: np.ndarray, b_dist: np.ndarray,
                   a_flow: np.ndarray, b_flow: np.ndarray) -> np.ndarray:
    if not (a_dist.shape == b_dist.shape == a_flow.shape == b_flow.shape):
        raise SupplyContractError("V24916_DYNAMIC_SKIM_WEIGHTED_PAIR_SHAPE_MISMATCH")
    total = a_flow + b_flow
    out = np.empty_like(a_dist, dtype=np.float64)
    positive = total > 1.0e-12
    out[positive] = ((a_flow[positive] * a_dist[positive] +
                      b_flow[positive] * b_dist[positive]) / total[positive])
    # Zero-current-demand cells do not contribute to the current IDP objective.
    # Keep them finite/deterministic for future use without inventing volume:
    # choose the shorter *available native-family assignment skim*.
    out[~positive] = np.minimum(a_dist[~positive], b_dist[~positive])
    return out


class DynamicSkimManager:
    """Run/read assignment-coupled native DIS skims and expose family matrices."""

    def __init__(self, adapter: Any):
        self.adapter = adapter
        self.epoch = 0
        self.current: DynamicSkimEpoch | None = None

    def _read_epoch(self, assignment_token: str, operation_positions: Sequence[int],
                    live_matrices: Mapping[str, Any]) -> DynamicSkimEpoch:
        zones = tuple(int(z) for z in self.adapter.zones)
        n = len(zones)
        zhash = ordered_zone_hash(zones)
        rows = _native_dis_rows(self.adapter)
        matrices: dict[str, np.ndarray] = {}
        meta: dict[str, dict[str, Any]] = {}
        for dseg in REQUIRED_NATIVE_DSEGS:
            row = rows[dseg]
            no = int(row["matrix_no_int"])
            values = _matrix_values(self.adapter, no, n, "DIS:" + dseg)
            matrices[dseg] = values
            meta[dseg] = {
                "matrix_no": no,
                "matrix_code": str(row.get("matrix_code", "DIS")),
                "dseg_code": str(row.get("dseg_code", dseg)),
                "canonical_dseg": dseg,
                "values_sha256": matrix_values_hash(values),
                "shape": [n, n],
                "unit": "km",
            }

        def flow(code: str) -> np.ndarray:
            matches = None
            for raw, value in (live_matrices or {}).items():
                if core.norm_code(raw) == code:
                    matches = value
                    break
            if matches is None:
                raise SupplyContractError("V24916_DYNAMIC_SKIM_LIVE_DEMAND_MISSING:" + code)
            a = np.asarray(matches, dtype=np.float64)
            if a.shape != (n, n) or not np.isfinite(a).all() or float(np.min(a)) < -1.0e-10:
                raise SupplyContractError("V24916_DYNAMIC_SKIM_LIVE_DEMAND_INVALID:" + code)
            return a

        family = {
            "WORK": _weighted_pair(matrices["NATIVE_CW"], matrices["NATIVE_CW_NOT"],
                                   flow("NATIVE_CW"), flow("NATIVE_CW_NOT")),
            "SERVICE": _weighted_pair(matrices["NATIVE_CS"], matrices["NATIVE_CS_NOT"],
                                      flow("NATIVE_CS"), flow("NATIVE_CS_NOT")),
            "LONG": np.array(matrices["NATIVE_CL"], copy=True),
            "FOREIGN": np.array(matrices["NATIVE_CF"], copy=True),
        }
        fhash = {k: matrix_values_hash(v) for k, v in family.items()}
        self.epoch += 1
        rm = getattr(self.adapter, "readback_manager", None)
        assignment_epoch = int(getattr(rm, "assignment_epoch", self.epoch) or self.epoch)
        payload = {
            "schema": SCHEMA,
            "epoch": self.epoch,
            "assignment_epoch": assignment_epoch,
            "assignment_token": str(assignment_token),
            "zone_order_sha256": zhash,
            "operation_positions": [int(x) for x in operation_positions],
            "matrix_hashes": {d: meta[d]["values_sha256"] for d in REQUIRED_NATIVE_DSEGS},
            "family_hashes": fhash,
        }
        return DynamicSkimEpoch(
            schema=SCHEMA, epoch=self.epoch, assignment_epoch=assignment_epoch,
            assignment_token=str(assignment_token), zone_order_sha256=zhash,
            operation_positions=tuple(int(x) for x in operation_positions),
            matrices_by_dseg=matrices, matrix_meta_by_dseg=meta,
            family_distance=family, family_hashes=fhash, epoch_hash=_hash(payload))

    def capture_after_execution(self, folder: Path, assignment_token: str,
                                operation_positions: Sequence[int],
                                live_matrices: Mapping[str, Any]) -> DynamicSkimEpoch:
        epoch = self._read_epoch(assignment_token, operation_positions, live_matrices)
        self.current = epoch
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        rt.write_json(folder / "DYNAMIC_SKIM_EPOCH.json", epoch.summary())
        return epoch

    def require_current(self) -> DynamicSkimEpoch:
        if self.current is None:
            raise SupplyContractError("V24916_DYNAMIC_SKIM_EPOCH_MISSING")
        rm = getattr(self.adapter, "readback_manager", None)
        current_assignment = int(getattr(rm, "assignment_epoch", self.current.assignment_epoch)
                                 or self.current.assignment_epoch)
        if current_assignment != int(self.current.assignment_epoch):
            raise SupplyContractError(
                "V24916_DYNAMIC_SKIM_STALE_ASSIGNMENT_EPOCH:%s!=%s" %
                (self.current.assignment_epoch, current_assignment))
        return self.current


__all__ = [
    "SCHEMA", "REQUIRED_NATIVE_DSEGS", "IDP_NATIVE_DSEGS", "DynamicSkimEpoch",
    "DynamicSkimManager", "active_native_skim_positions",
]
