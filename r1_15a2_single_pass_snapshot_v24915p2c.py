# -*- coding: utf-8 -*-
"""Exact single-pass semantic snapshot for V24915 PERF2C.

The optimization is deliberately local to one ``snapshot()`` invocation.  It
never caches data across candidates, assignments, diagnostics, or model writes.
The public payload and all legacy semantic hashes remain unchanged.

Only two proven duplicate/unused read classes are removed:

* DSeg binding capture reads only CODE and ODMatrix.NO, because the legacy
  semantic snapshot does not use DSeg NAME/MODE or matrix CODE/SUM.
* Trip-distribution parameter capture and Procedure Sequence inventory share a
  single Operations.GetAll result and one read of OPERATIONTYPE/ACTIVE/COMMENT.

Everything else intentionally follows the legacy full snapshot contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt
import r1_15a2_visum_parameters as vp
from r1_15a2_supply import SupplyContractError, canonical_hash, integer, key_text, number

SCHEMA = "R1_15A2_V24915_PERF2C_SINGLE_PASS_EXACT_SNAPSHOT_V1"
RELEASE = "R1_15A2_V2_4_9_15_PERF2C_SINGLE_PASS_EXACT_SNAPSHOT_20261020"


@dataclass(frozen=True)
class OperationRecord:
    """One exact, reusable read of a Procedure Sequence operation."""

    position: int
    obj: Any
    operation_type_raw: Any
    operation_type: int
    active: int
    comment: str
    name: str


class SnapshotReadContext:
    """Per-call memoization only; the instance is discarded after snapshot()."""

    def __init__(self, adapter: Any, *, clock: Callable[[], float] = time.perf_counter):
        self.adapter = adapter
        self.visum = adapter.visum
        self.cfg = adapter.cfg
        self.clock = clock
        self._values: Dict[str, Any] = {}
        self.loader_calls: Dict[str, int] = {}
        self.loader_seconds: Dict[str, float] = {}

    def get_once(self, key: str, loader: Callable[[], Any]) -> Any:
        if key in self._values:
            return self._values[key]
        started = self.clock()
        value = loader()
        elapsed = self.clock() - started
        self._values[key] = value
        self.loader_calls[key] = self.loader_calls.get(key, 0) + 1
        self.loader_seconds[key] = self.loader_seconds.get(key, 0.0) + elapsed
        return value

    def links(self) -> Mapping[Tuple[int, int, int], Mapping[str, Any]]:
        return self.get_once("links", self.adapter.read_links)

    def dseg_bindings(self) -> List[Dict[str, Any]]:
        return self.get_once("dseg_bindings", lambda: _read_dseg_bindings(self.visum))

    def operation_records(self) -> List[OperationRecord]:
        return self.get_once("operation_records", lambda: _read_operation_records(self.visum))

    def generation_values(self) -> Dict[str, Dict[str, float]]:
        def load() -> Dict[str, Dict[str, float]]:
            return {
                attr: {
                    str(zone_no): number(value)
                    for zone_no, value in zip(
                        self.adapter.zones,
                        rt.read_zone_attr_strict(
                            self.visum,
                            attr,
                            self.adapter.zones,
                            zone_indices=self.adapter.zone_write_index_by_no,
                            retry_policy=self.adapter.com_retry_policy,
                        ),
                    )
                }
                for attr in mb.GENERATION_ATTRS
            }

        return self.get_once("generation_values", load)

    def td_and_operations(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        def load() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
            records = self.operation_records()
            td_rows, td_operation_audit = _read_td_snapshot_from_records(self.visum, records)
            operation_rows = _inventory_from_records(records, td_operation_audit)
            return td_rows, operation_rows

        return self.get_once("td_and_operations", load)

    def telemetry(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "loader_calls": dict(self.loader_calls),
            "loader_seconds": dict(self.loader_seconds),
            "per_call_cache_entries": sorted(self._values),
            "cross_call_cache": False,
        }


def _read_dseg_bindings(visum: Any) -> List[Dict[str, Any]]:
    """Read exactly the DSeg fields consumed by the legacy semantic snapshot.

    ``rt.list_dsegs`` additionally reads DSeg NAME/MODE and matrix CODE/SUM.
    Those values never enter ``dseg_map``, ``matrix_hash`` or ``state_hash`` in
    the legacy full snapshot, so reading them here would be redundant COM I/O.
    Error handling for CODE/ODMatrix.NO intentionally mirrors ``list_dsegs``.
    """

    rows: List[Dict[str, Any]] = []
    for ds in rt.get_all(visum.Net.DemandSegments):
        code = rt.sval(rt.att(ds, "CODE", "")).strip()
        if not code:
            continue
        matrix_no: Any = ""
        try:
            matrix = ds.ODMatrix
            if matrix is not None:
                matrix_no = rt.ival(rt.att(matrix, "NO", None), "")
        except Exception:
            pass
        rows.append({
            "code": code,
            "norm_code": rt.norm_code(code),
            "object": ds,
            "matrix_no": matrix_no,
        })
    return rows


def _operation_text(op: Any, attribute: str) -> str:
    try:
        value = op.AttValue(attribute)
        return "" if value is None else str(value)
    except Exception:
        return ""


def _read_operation_records(visum: Any) -> List[OperationRecord]:
    operations = com.collection_items(visum.Procedures.Operations, "Operations")
    records: List[OperationRecord] = []
    for position, op in enumerate(operations, 1):
        operation_type_raw = op.AttValue("OPERATIONTYPE")
        records.append(OperationRecord(
            position=position,
            obj=op,
            operation_type_raw=operation_type_raw,
            operation_type=com.exact_int(operation_type_raw, "OPERATIONTYPE"),
            active=int(com.active_bool(op.AttValue("ACTIVE"))),
            comment=_operation_text(op, "COMMENT"),
            name=_operation_text(op, "NAME"),
        ))
    if not records:
        raise RuntimeError("EMPTY_OPERATION_LIST")
    return records


def _find_td_operation_from_records(
        records: Sequence[OperationRecord], required_codes: Sequence[str]):
    """Exact local equivalent of vp._find_operation for TD operation 46."""

    best = None
    audit: List[Dict[str, Any]] = []
    parameter_props = ("TripDistributionParameters", "TripDistributionParameter")
    for record in records:
        row: Dict[str, Any] = {
            "index": record.position,
            "operation_type": mb.sval(record.operation_type_raw),
            "active": int(record.active),
            "comment": record.comment,
            "selected": 0,
        }
        if record.operation_type != 46:
            audit.append(row)
            continue
        params = None
        source = ""
        for prop in parameter_props:
            try:
                params = getattr(record.obj, prop)
                if params is not None:
                    source = prop
                    break
            except Exception:
                pass
        row["parameter_source"] = source
        row["parameter_status"] = "OK" if params is not None else "UNREADABLE"
        score = 100 if record.active else 0
        dset = ""
        if params is not None:
            for attr in ("DSTRATSET", "DStratSet", "DEMANDSTRATUMSET"):
                dset = mb.sval(rt.att(params, attr, ""))
                if dset:
                    break
            tokens = com.code_set(dset, "DSTRATSET") if dset else set()
            score += sum(1 for code in required_codes if code.upper() in tokens)
        row["dstratset"] = dset
        if params is not None and (best is None or score > best[0]):
            best = (score, record.obj, params, row)
        audit.append(row)
    if best is None:
        return None, None, audit
    required_upper = {code.upper() for code in required_codes}
    complete_active = [
        row for row in audit
        if row.get("active") and row.get("parameter_status") == "OK"
        and required_upper <= (
            com.code_set(row["dstratset"]) if row.get("dstratset") else set())
    ]
    if len(complete_active) > 1:
        for row in complete_active:
            row["resolution_error"] = "AMBIGUOUS_ACTIVE_OPERATION_SCOPE"
        return None, None, audit
    best[3]["selected"] = 1
    return best[1], best[2], audit


def _read_td_snapshot_from_records(
        visum: Any, records: Sequence[OperationRecord]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    required_codes = [item["dstrat_code"] for item in mb.COMPONENT_REGISTRY.values()]
    _op, params, operation_rows = _find_td_operation_from_records(records, required_codes)
    if params is None:
        raise RuntimeError("Could not locate readable Trip Distribution operation")
    selected_ops = [row for row in operation_rows if int(row.get("selected", 0) or 0) == 1]
    if not selected_ops or int(selected_ops[0].get("active", 0) or 0) != 1:
        raise RuntimeError("Selected Trip Distribution operation is inactive or unresolved")
    dset = mb.sval(selected_ops[0].get("dstratset"))
    tokens = com.code_set(dset) if dset else set()
    missing_set = [code for code in required_codes if code.upper() not in tokens]
    if missing_set:
        raise RuntimeError("Trip Distribution DStratSet misses: %s" % ",".join(missing_set))

    rows: List[Dict[str, Any]] = []
    for component, registry in mb.COMPONENT_REGISTRY.items():
        d_obj, source = vp._dstrat_object(  # pylint: disable=protected-access
            params, registry["dstrat_code"], ("TripDistribution",))
        if d_obj is None:
            rows.append({
                "component": component,
                "dstrat_code": registry["dstrat_code"],
                "matrix_no": registry["matrix_no"],
                "status": "DSTRAT_NOT_FOUND",
                "source": source,
            })
            continue
        grav = d_obj
        grav_source = "DStratPara"
        for prop in ("GravitationParameters", "GravityParameters", "DistributionParameters"):
            try:
                candidate = getattr(d_obj, prop)
                if candidate is not None:
                    grav = candidate
                    grav_source = prop
                    break
            except Exception:
                pass
        b_attr, b_raw, b_mode = vp._read_any(grav, vp.TD_B_ATTRS)  # pylint: disable=protected-access
        c_attr, c_raw, c_mode = vp._read_any(grav, vp.TD_C_ATTRS)  # pylint: disable=protected-access
        b_value = mb.fval(b_raw, None)
        c_value = mb.fval(c_raw, None)
        status = "OK" if b_value is not None and c_value is not None else "PARAM_READ_INCOMPLETE"
        rows.append({
            "component": component,
            "family": registry["family"],
            "dstrat_code": registry["dstrat_code"],
            "matrix_no": registry["matrix_no"],
            "status": status,
            "source": source,
            "gravitation_source": grav_source,
            "b_attr": b_attr,
            "current_b": b_value,
            "b_mode": b_mode,
            "c_attr": c_attr,
            "current_c": c_value,
            "c_mode": c_mode,
        })
    compact_rows = [
        {
            "component": row.get("component"),
            "current_b": row.get("current_b"),
            "current_c": row.get("current_c"),
            "status": row.get("status"),
        }
        for row in rows
    ]
    return compact_rows, operation_rows


def _inventory_from_records(
        records: Sequence[OperationRecord], td_operation_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Build exact com.operation_rows payload without rereading shared attrs."""

    audit_by_position = {int(row["index"]): row for row in td_operation_rows}
    inventory: List[Dict[str, Any]] = []
    for record in records:
        audit = audit_by_position.get(record.position, {})
        operation_type = (
            com.exact_int(audit.get("operation_type"), "OPERATIONTYPE")
            if audit.get("operation_type") not in (None, "")
            else record.operation_type
        )
        inventory.append({
            "no": record.position,
            "position": record.position,
            "type": operation_type,
            "active": int(audit.get("active", record.active)),
            "comment": str(audit.get("comment", record.comment)),
            "name": record.name,
        })
    return inventory


def _matrix_fingerprint_exact(mat: Any) -> Tuple[Dict[str, Any], float]:
    """Return exactly the legacy published row plus the validation sum.

    The legacy helper also reads matrix CODE and counts nonzero cells, although
    neither enters the published semantic snapshot.  PERF2C omits only those
    unused operations; full matrix values and byte-level SHA semantics remain
    unchanged.
    """

    values = mat.GetValues()
    array = np.asarray(values, dtype="<f8")
    if array.ndim != 2:
        raise RuntimeError("matrix array is not 2D: shape=%r" % (array.shape,))
    if not np.all(np.isfinite(array)) or np.any(array < 0):
        raise RuntimeError("Demand matrix contains nonfinite or negative values")
    contiguous = np.ascontiguousarray(array, dtype="<f8")
    total = float(np.sum(contiguous))
    row = {
        "matrix_no": rt.ival(rt.att(mat, "NO", None), ""),
        "rows": int(contiguous.shape[0]),
        "cols": int(contiguous.shape[1]),
        "sha256_float64_le": hashlib.sha256(contiguous.tobytes(order="C")).hexdigest(),
    }
    return row, total


def single_pass_exact_snapshot(adapter: Any) -> Dict[str, Any]:
    """Build the exact legacy full semantic snapshot with per-call coalescing."""

    context = SnapshotReadContext(adapter)

    links = context.links()
    fixed: List[Dict[str, Any]] = []
    addval_values: Dict[str, float] = {}
    for key, row in sorted(links.items()):
        addval_values[key_text(key)] = row["addval1"]
        fixed.append({
            name: value for name, value in row.items()
            if name not in ("addval1", "object", "eligible")
        })

    dseg_rows = context.dseg_bindings()
    if len({row["norm_code"] for row in dseg_rows}) != len(dseg_rows):
        raise SupplyContractError("DUPLICATE_DSEG_IDENTITY")
    dseg_map = {row["norm_code"]: row.get("matrix_no") for row in dseg_rows}
    required = {
        core.norm_code(value)
        for value in (
            adapter.cfg["supply"]["passenger_dsegs"]
            + adapter.cfg["supply"].get("freight_dsegs", [])
        )
    }
    if not required <= set(dseg_map):
        raise SupplyContractError(
            "REQUIRED_DEMAND_SEGMENT_MISSING:"
            + ",".join(sorted(required - set(dseg_map))))
    unbound = sorted(code for code in required if dseg_map[code] in (None, ""))
    if unbound:
        raise SupplyContractError(
            "REQUIRED_DSEG_ODMATRIX_UNREADABLE:" + ",".join(unbound))

    matrix_numbers = {
        integer(row["matrix_no"])
        for row in dseg_rows
        if row.get("matrix_no") not in (None, "")
    }
    matrix_numbers.update(
        integer(value)
        for value in adapter.cfg["supply"].get("component_matrix_nos", []))
    matrix_rows: List[Dict[str, Any]] = []
    for matrix_no in sorted(matrix_numbers):
        matrix = adapter.visum.Net.Matrices.ItemByKey(matrix_no)
        row, matrix_sum = _matrix_fingerprint_exact(matrix)
        expected_zones = adapter.cfg.get("expected_zones")
        if expected_zones is not None and (row["rows"], row["cols"]) != (
                int(expected_zones), int(expected_zones)):
            raise SupplyContractError(
                "DEMAND_MATRIX_AXIS_SHAPE_MISMATCH:%s" % matrix_no)
        if not math.isfinite(matrix_sum) or matrix_sum < 0:
            raise SupplyContractError("NONFINITE_OR_NEGATIVE_DEMAND")
        matrix_rows.append(row)
    if not matrix_rows:
        raise SupplyContractError("EMPTY_DEMAND_FINGERPRINT")

    generation_values = context.generation_values()
    td_values, operations = context.td_and_operations()
    if (len(td_values) != len(mb.COMPONENT_REGISTRY)
            or any(row.get("status") != "OK" for row in td_values)):
        raise SupplyContractError("COMPONENT_PARAMETER_SNAPSHOT_FAILED")
    td_values = sorted(td_values, key=lambda row: row["component"])

    result: Dict[str, Any] = {
        "addval1": addval_values,
        "addval_hash": canonical_hash(addval_values),
        "fixed_link_hash": canonical_hash(fixed),
        "matrix_hash": canonical_hash(matrix_rows),
        "matrices": matrix_rows,
        "dseg_map": dseg_map,
        "dseg_hash": canonical_hash(dseg_map),
        "generation_hash": canonical_hash(generation_values),
        "generation_values": generation_values,
        "td_values": td_values,
        "td_hash": canonical_hash(td_values),
        "operations_hash": canonical_hash(operations),
    }
    result["state_hash"] = canonical_hash(result)

    telemetry_payload = context.telemetry()
    telemetry_payload.update({
        "state_hash": result["state_hash"],
        "matrix_count": len(matrix_rows),
        "dseg_count": len(dseg_rows),
        "generation_attribute_count": len(generation_values),
        "operation_count": len(operations),
    })
    adapter.last_perf2c_snapshot_telemetry = telemetry_payload
    telemetry = getattr(adapter, "telemetry", None)
    if telemetry is not None:
        telemetry.event("PERF2C_SINGLE_PASS_EXACT_SNAPSHOT", **telemetry_payload)
    return result


__all__ = [
    "SCHEMA",
    "RELEASE",
    "SnapshotReadContext",
    "single_pass_exact_snapshot",
]
