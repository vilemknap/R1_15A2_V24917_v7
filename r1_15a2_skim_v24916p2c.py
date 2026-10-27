"""Sealed read-only skim support for the PERF2C/V24916 integration."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Sequence
import hashlib
import json
import math

from r1_15a2_skim_v24916 import *  # noqa: F401,F403

SCHEMA = "R1_15A2_V24916_PERF2C_SEALED_SKIM_V1"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _matrix_shape(values: Any) -> tuple[int, int]:
    shape = getattr(values, "shape", None)
    if shape is not None and len(shape) == 2:
        return int(shape[0]), int(shape[1])
    n = len(values)
    return n, len(values[0]) if n else 0


def _matrix_value(values: Any, i: int, j: int) -> float:
    try:
        return float(values[i, j])
    except (TypeError, KeyError, IndexError):
        return float(values[i][j])


def ordered_zone_hash(zone_nos: Sequence[int]) -> str:
    vals = [int(v) for v in zone_nos]
    if len(vals) != len(set(vals)):
        raise ValueError("V24916_SKIM_DUPLICATE_ZONE_IDENTITY")
    return _hash(vals)


def matrix_values_hash(values: Any) -> str:
    n, m = _matrix_shape(values)
    h = hashlib.sha256()
    h.update(f"{n}x{m}|".encode("ascii"))
    for i in range(n):
        for j in range(m):
            v = _matrix_value(values, i, j)
            if not math.isfinite(v):
                raise ValueError("V24916_SKIM_NONFINITE")
            # Stable round-trip textual representation, without materializing a nested list.
            h.update(float(v).hex().encode("ascii"))
            h.update(b";")
    return h.hexdigest()


@dataclass(frozen=True)
class SealedSkimIdentity:
    schema: str
    matrix_no: int
    matrix_code: str
    unit: str
    n_zones: int
    zone_order_hash: str
    values_hash: str
    role: str
    identity_hash: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def seal_dist_km(
    *,
    matrix_no: int,
    matrix_code: str,
    unit: str,
    values: Any,
    zone_nos: Sequence[int],
    exact_expected_code: str | None = None,
) -> SealedSkimIdentity:
    code = str(matrix_code)
    if exact_expected_code is not None and code != str(exact_expected_code):
        raise ValueError(f"V24916_DIST_KM_CODE_MISMATCH:{code!r}!={exact_expected_code!r}")
    normalized_unit = str(unit).strip().lower()
    if normalized_unit not in {"km", "kilometre", "kilometer", "kilometres", "kilometers"}:
        raise ValueError(f"V24916_DIST_KM_UNIT_NOT_KM:{unit!r}")
    n = len(zone_nos)
    if _matrix_shape(values) != (n, n):
        raise ValueError("V24916_DIST_KM_DIMENSION_MISMATCH")
    payload = {
        "schema": SCHEMA,
        "matrix_no": int(matrix_no),
        "matrix_code": code,
        "unit": "km",
        "n_zones": n,
        "zone_order_hash": ordered_zone_hash(zone_nos),
        "values_hash": matrix_values_hash(values),
        "role": "READ_ONLY_TARGETING_CONTEXT_NOT_ACCEPTANCE_AUTHORITY",
    }
    return SealedSkimIdentity(**payload, identity_hash=_hash(payload))


def require_same_skim_identity(expected: SealedSkimIdentity, actual: SealedSkimIdentity) -> None:
    if expected.identity_hash != actual.identity_hash:
        raise RuntimeError("V24916_DIST_KM_IDENTITY_CHANGED")


def shortest_imp_oracle_enabled(config: dict[str, Any] | None = None) -> bool:
    """Hard-disabled in the first integration release.

    The old donor does not contain a production-grade cached-path impedance
    authority, therefore skim-driven path epoch invalidation must not activate.
    """
    requested = bool((config or {}).get("shortest_imp_oracle_enabled", False))
    if requested:
        raise RuntimeError("V24916_SHORTEST_IMP_ORACLE_NOT_CERTIFIED")
    return False
