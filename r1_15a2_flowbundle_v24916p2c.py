"""V24916 FlowBundle overlay rebased on PERF2C.

This module deliberately keeps FlowBundle as read-only targeting/evidence.
It never writes demand, never changes acceptance, and never retains a full
681x681 matrix after reduction.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Optional, Sequence
import hashlib
import heapq
import json
import math

# Canonical donor. Public donor symbols remain available for compatibility.
from r1_15a2_flowbundle_v24916 import *  # noqa: F401,F403

SCHEMA = "R1_15A2_V24916_PERF2C_FLOWBUNDLE_REDUCED_V1"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def ordered_zone_hash(zone_nos: Sequence[int]) -> str:
    vals = [int(v) for v in zone_nos]
    if len(vals) != len(set(vals)):
        raise ValueError("V24916_DUPLICATE_ZONE_IDENTITY")
    return canonical_hash(vals)


@dataclass(frozen=True)
class FlowBundleEvidenceIdentity:
    run_token: str
    visum_session_token: str
    semantic_state_hash: str
    assignment_token: str
    assignment_epoch: int
    path_epoch: int
    path_basis_hash: str
    comparison_basis_hash: str
    zone_order_hash: str
    flowbundle_contract_hash: str
    dist_km_hash: str
    targeting_config_hash: str

    @property
    def identity_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class ReducedFlowBundle:
    schema: str
    zone_order_hash: str
    n_zones: int
    total: float
    retained_total: float
    tail_total: float
    retained_od: tuple[tuple[int, int, float], ...]
    origin_totals: tuple[float, ...]
    destination_totals: tuple[float, ...]
    source_directions: tuple[str, ...]
    payload_hash: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FlowBundleMatrixReducer:
    """Single-pass reducer with bounded memory.

    The reducer consumes one or two matrices and stores only O(n + top_k)
    values. It intentionally does not cache or return the original matrix.
    """

    def __init__(self, zone_nos: Sequence[int], *, top_k: int = 4096, negative_atol: float = 1e-12):
        self.zone_nos = tuple(int(v) for v in zone_nos)
        self.zone_order_hash = ordered_zone_hash(self.zone_nos)
        self.top_k = max(0, int(top_k))
        self.negative_atol = float(negative_atol)

    @staticmethod
    def _shape(matrix: Any) -> tuple[int, int]:
        shape = getattr(matrix, "shape", None)
        if shape is not None and len(shape) == 2:
            return int(shape[0]), int(shape[1])
        n = len(matrix)
        return n, len(matrix[0]) if n else 0

    @staticmethod
    def _value(matrix: Any, i: int, j: int) -> float:
        try:
            return float(matrix[i, j])
        except (TypeError, KeyError, IndexError):
            return float(matrix[i][j])

    def reduce(
        self,
        forward: Any,
        reverse: Any | None = None,
        *,
        source_directions: Sequence[str] = ("DIRECTED",),
    ) -> ReducedFlowBundle:
        n = len(self.zone_nos)
        if self._shape(forward) != (n, n):
            raise ValueError("V24916_FLOWBUNDLE_DIMENSION_MISMATCH")
        if reverse is not None and self._shape(reverse) != (n, n):
            raise ValueError("V24916_FLOWBUNDLE_REVERSE_DIMENSION_MISMATCH")

        origin = [0.0] * n
        destination = [0.0] * n
        total = 0.0
        # Min-heap of (flow, i, j); deterministic tie-breaking by i/j.
        heap: list[tuple[float, int, int]] = []
        for i in range(n):
            for j in range(n):
                v = self._value(forward, i, j)
                if reverse is not None:
                    v += self._value(reverse, i, j)
                if not math.isfinite(v):
                    raise ValueError("V24916_FLOWBUNDLE_NONFINITE")
                if v < -self.negative_atol:
                    raise ValueError("V24916_FLOWBUNDLE_NEGATIVE")
                if v < 0.0:
                    v = 0.0
                total += v
                origin[i] += v
                destination[j] += v
                if self.top_k and v > 0.0:
                    item = (v, i, j)
                    if len(heap) < self.top_k:
                        heapq.heappush(heap, item)
                    elif item > heap[0]:
                        heapq.heapreplace(heap, item)

        # Highest flow first, then zone identity for deterministic output.
        retained_index = sorted(heap, key=lambda x: (-x[0], self.zone_nos[x[1]], self.zone_nos[x[2]]))
        retained = tuple((self.zone_nos[i], self.zone_nos[j], float(v)) for v, i, j in retained_index)
        retained_total = math.fsum(v for _, _, v in retained)
        tail = total - retained_total
        if abs((retained_total + tail) - total) > max(1e-9, abs(total) * 1e-12):
            raise AssertionError("V24916_FLOWBUNDLE_RETAINED_TAIL_PARITY_FAIL")
        payload = {
            "schema": SCHEMA,
            "zone_order_hash": self.zone_order_hash,
            "n_zones": n,
            "total": total,
            "retained_total": retained_total,
            "tail_total": tail,
            "retained_od": retained,
            "origin_totals": origin,
            "destination_totals": destination,
            "source_directions": list(source_directions),
        }
        return ReducedFlowBundle(
            schema=SCHEMA,
            zone_order_hash=self.zone_order_hash,
            n_zones=n,
            total=float(total),
            retained_total=float(retained_total),
            tail_total=float(tail),
            retained_od=retained,
            origin_totals=tuple(float(v) for v in origin),
            destination_totals=tuple(float(v) for v in destination),
            source_directions=tuple(str(v) for v in source_directions),
            payload_hash=canonical_hash(payload),
        )


def reduce_directed(
    matrix: Any,
    zone_nos: Sequence[int],
    *,
    top_k: int = 4096,
) -> ReducedFlowBundle:
    return FlowBundleMatrixReducer(zone_nos, top_k=top_k).reduce(matrix, source_directions=("DIRECTED",))


def reduce_both_directions(
    forward: Any,
    reverse: Any,
    zone_nos: Sequence[int],
    *,
    top_k: int = 4096,
) -> ReducedFlowBundle:
    # BOTH is the exact cell-wise sum of the two explicitly obtained directed matrices.
    return FlowBundleMatrixReducer(zone_nos, top_k=top_k).reduce(
        forward,
        reverse,
        source_directions=("FORWARD", "REVERSE"),
    )


def assert_reduced_parity(reduced: ReducedFlowBundle, expected_total: float, *, rtol: float = 1e-9, atol: float = 1e-6) -> None:
    expected = float(expected_total)
    if not math.isfinite(expected):
        raise ValueError("V24916_EXPECTED_TOTAL_NONFINITE")
    if not math.isclose(reduced.total, expected, rel_tol=rtol, abs_tol=atol):
        raise AssertionError(
            f"V24916_FLOWBUNDLE_TOTAL_PARITY_FAIL:{reduced.total!r}!={expected!r}"
        )
    if not math.isclose(reduced.retained_total + reduced.tail_total, reduced.total, rel_tol=rtol, abs_tol=atol):
        raise AssertionError("V24916_FLOWBUNDLE_TAIL_BUCKET_PARITY_FAIL")
