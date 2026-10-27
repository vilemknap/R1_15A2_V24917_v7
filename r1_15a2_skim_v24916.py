# -*- coding: utf-8 -*-
"""Read-only skim authority and shadow diagnostics for V2.4.9.16.

Only DIST_KM is a required scientific authority. TT0/TTC/IMP/DIS/DID/AD1/
VP0/VPC are optional, read-only shadow evidence. This module never calculates
skims, runs assignment, changes Procedure Sequence, or writes model data.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
import r1_15a2_runtime_io_hotfix_profile488 as runtime_io_hotfix
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import r1_15a2_com_compat as com

DISTANCE_CODE_CANDIDATES = ("R1_OSRM_DIST_KM", "DIST_KM", "DISTANCE", "DIS")
DISTANCE_NO_CANDIDATES = (9697,)
OPTIONAL_SKIM_CODES = ("TT0", "TTC", "IMP", "DIS", "DID", "AD1", "VP0", "VPC")


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            value = value.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
            if not value or value.lower() in {"nan", "none", "null"}:
                return default
        result = float(value)
        return result if math.isfinite(result) else default
    except Exception:
        return default


def _plain_multi(rows: Any) -> List[Any]:
    result = []
    for row in rows or []:
        result.append(row[1] if isinstance(row, (tuple, list)) and len(row) >= 2 else row)
    return result


def _multi_values(collection: Any, attribute: str, retry_policy=None) -> List[Any]:
    """Read one canonical attribute without expected-error alias probing.

    PTV Visum 2026 documents ``GetMultiAttValues(attribute, OnlyActive)`` and
    returns a two-column SAFEARRAY containing collection indices and values.
    The production path therefore always uses the canonical CodeID and
    ``OnlyActive=False``.
    """
    rows = com.get_multi_att_values(collection, str(attribute), retry_policy)
    return _plain_multi(rows)


def zone_numbers(visum: Any, retry_policy=None) -> List[int]:
    values = _multi_values(visum.Net.Zones, "NO", retry_policy)
    if not values:
        raise RuntimeError("V24916_SKIM_ZONE_NUMBERS_UNREADABLE")
    zones = []
    for value in values:
        try:
            zones.append(int(round(float(value))))
        except Exception as exc:
            raise RuntimeError("V24916_SKIM_ZONE_NUMBER_INVALID:%r" % (value,)) from exc
    if len(zones) != len(set(zones)):
        raise RuntimeError("V24916_SKIM_ZONE_ORDER_NOT_UNIQUE")
    return zones


def matrix_inventory(visum: Any, retry_policy=None) -> List[Dict[str, Any]]:
    """Read canonical PTV Visum 2026 matrix metadata in standard order."""
    matrices = visum.Net.Matrices
    attrs = {
        "matrix_no": "NO",
        "matrix_code": "CODE",
        "matrix_name": "NAME",
        "matrix_type": "MATRIXTYPE",
        "dseg_code": "DSEGCODE",
        "data_source_type": "DATASOURCETYPE",
        "formula": "FORMULA",
        "num_rows": "NUMROWS",
        "num_cols": "NUMCOLS",
    }
    columns: Dict[str, List[Any]] = {}
    maximum = 0
    for logical, code_id in attrs.items():
        try:
            values = _multi_values(matrices, code_id, retry_policy)
        except Exception:
            # Formula/NumRows/NumCols can be unavailable for some matrix kinds.
            # They are optional metadata and do not trigger alias probing.
            if logical in {"formula", "num_rows", "num_cols"}:
                values = []
            else:
                raise RuntimeError("V24916_MATRIX_ATTRIBUTE_UNREADABLE:%s" % code_id)
        columns[logical] = values
        maximum = max(maximum, len(values))
    rows = []
    for i in range(maximum):
        row = {name: (values[i] if i < len(values) else "")
               for name, values in columns.items()}
        try:
            row["matrix_no_int"] = int(round(float(row["matrix_no"])))
        except Exception:
            row["matrix_no_int"] = None
        row["matrix_code_norm"] = str(row.get("matrix_code", "") or "").strip().upper()
        row["dseg_code_norm"] = str(row.get("dseg_code", "") or "").strip().upper()
        row["matrix_type_norm"] = str(row.get("matrix_type", "") or "").strip().upper()
        row["data_source_type_norm"] = str(row.get("data_source_type", "") or "").strip().upper()
        row["formula_norm"] = str(row.get("formula", "") or "").strip().upper()
        rows.append(row)
    return rows


def matrix_by_code_or_no(visum: Any, code_candidates: Sequence[str] = DISTANCE_CODE_CANDIDATES,
                         no_candidates: Sequence[int] = DISTANCE_NO_CANDIDATES,
                         retry_policy=None) -> Tuple[Any, str]:
    """Resolve the required distance matrix from canonical NO/CODE only.

    This avoids requiring unrelated optional metadata (NAME/MATRIXTYPE/etc.)
    just to resolve DIST_KM and reduces live COM surface.
    """
    matrices = visum.Net.Matrices
    nos = _multi_values(matrices, "NO", retry_policy)
    codes = _multi_values(matrices, "CODE", retry_policy)
    by_code = {}
    for i, raw_no in enumerate(nos):
        try:
            no = int(round(float(raw_no)))
        except Exception:
            continue
        code = str(codes[i] if i < len(codes) else "").strip().upper()
        if code:
            by_code[code] = no
    for code in code_candidates:
        no = by_code.get(str(code).upper())
        if no is not None:
            return com.com_call_with_retry(
                lambda no=no: matrices.ItemByKey(int(no)),
                "Matrices.ItemByKey(%s)" % no, retry_policy=retry_policy), "CODE:%s" % code
    for no in no_candidates:
        try:
            return com.com_call_with_retry(
                lambda no=no: matrices.ItemByKey(int(no)),
                "Matrices.ItemByKey(%s)" % no, retry_policy=retry_policy), "NO:%s" % no
        except Exception:
            pass
    return None, "NOT_FOUND"

def _matrix_values(matrix: Any, zones: Sequence[int], label: str, retry_policy=None):
    raw = com.com_call_with_retry(lambda: matrix.GetValues(),
                                  "Matrix.GetValues[%s]" % label,
                                  retry_policy=retry_policy)
    if len(raw) != len(zones):
        raise RuntimeError("V24916_SKIM_ROW_COUNT_MISMATCH:%s:%s:%s" %
                           (label, len(raw), len(zones)))
    values = []
    finite = nonnegative = 0
    for index, raw_row in enumerate(raw):
        if len(raw_row) != len(zones):
            raise RuntimeError("V24916_SKIM_COL_COUNT_MISMATCH:%s:%s" % (label, index))
        row = []
        for raw_value in raw_row:
            value = _f(raw_value, None)
            if value is None:
                value = float("nan")
            else:
                finite += 1
                if value >= 0.0:
                    nonnegative += 1
            row.append(value)
        values.append(tuple(row))
    return tuple(values), finite, nonnegative


def _hash_matrix(values: Sequence[Sequence[float]], zones: Sequence[int]) -> Tuple[str, str]:
    zone_hash = hashlib.sha256("|".join(str(int(z)) for z in zones).encode("ascii")).hexdigest()
    digest = hashlib.sha256((zone_hash + "|").encode("ascii"))
    for row in values:
        for value in row:
            digest.update(("%.17g|" % float(value)).encode("ascii", "replace"))
    return digest.hexdigest(), zone_hash


@dataclass(frozen=True)
class DistanceAuthority:
    source: str
    zone_numbers: Tuple[int, ...]
    values: Tuple[Tuple[float, ...], ...]
    zone_index: Mapping[int, int]
    sha256: str
    zone_order_sha256: str
    finite_count: int
    nonnegative_count: int

    def value(self, origin: int, destination: int) -> Optional[float]:
        oi = self.zone_index.get(int(origin)); di = self.zone_index.get(int(destination))
        if oi is None or di is None:
            return None
        value = self.values[oi][di]
        return value if math.isfinite(value) else None

    def to_summary(self) -> Dict[str, Any]:
        return {
            "schema": "R1_15A2_DISTANCE_SKIM_AUTHORITY_V24916",
            "status": "PASS", "source": self.source,
            "zone_count": len(self.zone_numbers),
            "matrix_sha256": self.sha256,
            "zone_order_sha256": self.zone_order_sha256,
            "finite_count": self.finite_count,
            "nonnegative_count": self.nonnegative_count,
            "required_for_v24916": True,
            "optional_shadow_skims": list(OPTIONAL_SKIM_CODES),
        }


@dataclass(frozen=True)
class OptionalSkimAuthority:
    matrix_no: int
    matrix_code: str
    dseg_code: str
    matrix_name: str
    source: str
    zone_numbers: Tuple[int, ...]
    values: Tuple[Tuple[float, ...], ...]
    sha256: str
    zone_order_sha256: str
    finite_count: int
    nonnegative_count: int
    elapsed_seconds: float

    def value(self, origin: int, destination: int) -> Optional[float]:
        index = {z: i for i, z in enumerate(self.zone_numbers)}
        oi = index.get(int(origin)); di = index.get(int(destination))
        if oi is None or di is None:
            return None
        value = self.values[oi][di]
        return value if math.isfinite(value) else None

    def summary(self) -> Dict[str, Any]:
        return {
            "matrix_no": self.matrix_no, "matrix_code": self.matrix_code,
            "dseg_code": self.dseg_code, "matrix_name": self.matrix_name,
            "source": self.source, "rows": len(self.zone_numbers),
            "cols": len(self.zone_numbers), "matrix_sha256": self.sha256,
            "zone_order_sha256": self.zone_order_sha256,
            "finite_count": self.finite_count,
            "nonnegative_count": self.nonnegative_count,
            "elapsed_seconds": self.elapsed_seconds,
            "role": "SHADOW_DIAGNOSTIC_ONLY",
        }


def read_distance_authority(visum: Any, retry_policy=None) -> DistanceAuthority:
    matrix, source = matrix_by_code_or_no(visum, retry_policy=retry_policy)
    if matrix is None:
        raise RuntimeError("V24916_REQUIRED_DISTANCE_SKIM_NOT_FOUND")
    zones = zone_numbers(visum, retry_policy)
    values, finite, nonnegative = _matrix_values(matrix, zones, "DIST_KM", retry_policy)
    if finite == 0 or nonnegative != finite:
        raise RuntimeError("V24916_DISTANCE_SKIM_NONFINITE_OR_NEGATIVE")
    digest, zone_hash = _hash_matrix(values, zones)
    return DistanceAuthority(source, tuple(zones), values, {z: i for i, z in enumerate(zones)},
                             digest, zone_hash, finite, nonnegative)


class SkimAuthorityCache:
    """Accepted-state cache for required and optional read-only skim matrices."""
    def __init__(self, visum: Any, retry_policy=None):
        self.visum = visum
        self.retry_policy = retry_policy or {}
        self.state_hash: Optional[str] = None
        self.distance: Optional[DistanceAuthority] = None
        self.optional: Dict[Tuple[str, str], OptionalSkimAuthority] = {}
        self.inventory: List[Dict[str, Any]] = []
        self.read_counts: Dict[int, int] = {}

    def reset_for_state(self, state_hash: str) -> None:
        if self.state_hash != str(state_hash):
            self.state_hash = str(state_hash)
            self.distance = None
            self.optional = {}
            self.inventory = []
            self.read_counts = {}

    def required_distance(self, state_hash: str) -> DistanceAuthority:
        self.reset_for_state(state_hash)
        if self.distance is None:
            self.distance = read_distance_authority(self.visum, self.retry_policy)
        return self.distance

    def optional_inventory(self, state_hash: str, target_dsegs: Sequence[str],
                           requested_codes: Sequence[str] = OPTIONAL_SKIM_CODES) -> Dict[str, Any]:
        self.reset_for_state(state_hash)
        if not self.inventory:
            self.inventory = matrix_inventory(self.visum, self.retry_policy)
        targets = {str(x).upper() for x in target_dsegs}
        requested = {str(x).upper() for x in requested_codes}
        rows = []
        selected = []
        for row in self.inventory:
            code = row.get("matrix_code_norm", "")
            dseg = row.get("dseg_code_norm", "")
            is_skim = "SKIM" in row.get("matrix_type_norm", "")
            chosen = bool(is_skim and code in requested and dseg in targets and row.get("matrix_no_int") is not None)
            item = dict(row); item["selected"] = int(chosen)
            rows.append(item)
            if chosen:
                selected.append(item)
        have = {(r["dseg_code_norm"], r["matrix_code_norm"]) for r in selected}
        missing = [{"dseg_code": dseg, "skim_code": code, "status": "NOT_AVAILABLE"}
                   for dseg in sorted(targets) for code in sorted(requested)
                   if (dseg, code) not in have]
        return {"inventory_rows": rows, "selected_rows": selected, "missing_rows": missing}

    def load_optional(self, state_hash: str, target_dsegs: Sequence[str],
                      requested_codes: Sequence[str] = OPTIONAL_SKIM_CODES) -> Dict[str, Any]:
        bundle = self.optional_inventory(state_hash, target_dsegs, requested_codes)
        zones = zone_numbers(self.visum, self.retry_policy)
        matrices = self.visum.Net.Matrices
        errors = []
        for row in bundle["selected_rows"]:
            key = (row["dseg_code_norm"], row["matrix_code_norm"])
            if key in self.optional:
                continue
            no = int(row["matrix_no_int"])
            started = time.perf_counter()
            try:
                matrix = com.com_call_with_retry(
                    lambda no=no: matrices.ItemByKey(no),
                    "Matrices.ItemByKey(%s)" % no,
                    retry_policy=self.retry_policy,
                )
                values, finite, nonnegative = _matrix_values(
                    matrix, zones, "%s:%s" % key, self.retry_policy)
                digest, zone_hash = _hash_matrix(values, zones)
                self.read_counts[no] = self.read_counts.get(no, 0) + 1
                self.optional[key] = OptionalSkimAuthority(
                    no, key[1], key[0], str(row.get("matrix_name", "")),
                    "MATRIX:%s" % no, tuple(zones), values, digest, zone_hash,
                    finite, nonnegative, time.perf_counter() - started)
            except Exception as exc:
                errors.append({"matrix_no": no, "dseg_code": key[0],
                               "skim_code": key[1], "status": "READ_FAILED",
                               "error": repr(exc)[:1000]})
        return {
            "schema": "R1_15A2_OPTIONAL_SKIM_SHADOW_AUTHORITY_V24916",
            "status": "PASS_WITH_OPTIONAL_GAPS" if bundle["missing_rows"] or errors else "PASS",
            "state_hash": str(state_hash),
            "selected": [authority.summary() for authority in self.optional.values()],
            "missing": bundle["missing_rows"], "errors": errors,
            "read_counts": dict(self.read_counts),
            "automatic_skim_calculation": False,
            "procedure_sequence_modified": False,
            "assignment_executed": False,
            "objective_role": "NONE_SHADOW_DIAGNOSTIC_ONLY",
        }


def distance_bin(distance_km: Optional[float], edges: Sequence[float]) -> str:
    value = _f(distance_km, None)
    if value is None:
        return "UNKNOWN"
    low = 0.0
    for high in edges:
        high = float(high)
        if value < high:
            return "[%g,%g)" % (low, high)
        low = high
    return "[%g,INF)" % low


def write_authority_summary(path: Any, authority: DistanceAuthority) -> None:
    runtime_io_hotfix.critical_atomic_json(path, authority.to_summary())


__all__ = [
    "DISTANCE_CODE_CANDIDATES", "DISTANCE_NO_CANDIDATES", "OPTIONAL_SKIM_CODES",
    "DistanceAuthority", "OptionalSkimAuthority", "SkimAuthorityCache",
    "matrix_inventory", "matrix_by_code_or_no", "zone_numbers",
    "read_distance_authority", "distance_bin", "write_authority_summary",
]

# ---------------------------------------------------------------------------
# Compatibility API for the historical V24916 focused tests.  This is an
# explicit-map, read-only reader; it performs no discovery, calculation,
# assignment or model write and therefore matches the final sealed contract.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OptionalSkimBundleAuthority:
    status: str
    zone_numbers: Tuple[int, ...]
    authorities: Mapping[Tuple[str, str], OptionalSkimAuthority]
    missing: Tuple[Tuple[str, str], ...]

    def value(self, dseg_code: str, skim_code: str,
              origin: int, destination: int) -> Optional[float]:
        authority = self.authorities.get((str(dseg_code).upper(), str(skim_code).upper()))
        if authority is None:
            return None
        return authority.value(origin, destination)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "schema": "R1_15A2_OPTIONAL_SKIM_EXPLICIT_MAP_AUTHORITY_V24916",
            "status": self.status,
            "zone_count": len(self.zone_numbers),
            "selected": [a.summary() for _, a in sorted(self.authorities.items())],
            "missing": [
                {"dseg_code": dseg, "skim_code": code, "status": "NOT_AVAILABLE"}
                for dseg, code in self.missing
            ],
            "calculation_performed": False,
            "model_modified": False,
            "assignment_executed": False,
            "procedure_sequence_modified": False,
            "objective_role": "NONE_SHADOW_DIAGNOSTIC_ONLY",
        }


def read_optional_skim_authority(
        visum: Any, target_dsegs: Sequence[str], requested_codes: Sequence[str],
        matrix_map: Mapping[str, Mapping[str, int]], retry_policy=None
) -> OptionalSkimBundleAuthority:
    """Read optional skims from an explicit DSeg/code -> Matrix.No map only.

    Missing optional entries are nonfatal.  There is deliberately no matrix
    name/code probing and no automatic skim calculation.
    """
    zones = zone_numbers(visum, retry_policy)
    matrices = visum.Net.Matrices
    authorities: Dict[Tuple[str, str], OptionalSkimAuthority] = {}
    missing: List[Tuple[str, str]] = []
    normalized_map = {
        str(dseg).upper(): {str(code).upper(): int(no) for code, no in rows.items()}
        for dseg, rows in (matrix_map or {}).items()
    }
    for dseg in [str(x).upper() for x in target_dsegs]:
        for code in [str(x).upper() for x in requested_codes]:
            no = normalized_map.get(dseg, {}).get(code)
            if no is None:
                missing.append((dseg, code))
                continue
            started = time.perf_counter()
            matrix = com.com_call_with_retry(
                lambda no=no: matrices.ItemByKey(int(no)),
                "Matrices.ItemByKey(%s)" % no, retry_policy=retry_policy)
            values, finite, nonnegative = _matrix_values(
                matrix, zones, "%s:%s" % (dseg, code), retry_policy)
            digest, zone_hash = _hash_matrix(values, zones)
            authorities[(dseg, code)] = OptionalSkimAuthority(
                int(no), code, dseg, code, "EXPLICIT_MATRIX_MAP:%s" % no,
                tuple(zones), values, digest, zone_hash, finite, nonnegative,
                time.perf_counter() - started)
    status = "PASS_WITH_OPTIONAL_GAPS" if missing else "PASS"
    return OptionalSkimBundleAuthority(
        status=status, zone_numbers=tuple(zones),
        authorities=authorities, missing=tuple(missing))

# Extend the original public surface without altering existing APIs.
try:
    __all__ = list(__all__) + ["OptionalSkimBundleAuthority", "read_optional_skim_authority"]
except NameError:
    pass
