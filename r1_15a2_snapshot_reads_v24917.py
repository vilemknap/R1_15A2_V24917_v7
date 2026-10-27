"""GENFIX1: exact snapshot reads without swallowing transient COM failures.

The sealed PERF2C implementation uses compatibility fallbacks for optional
COM attributes and parameter object spellings.  Those fallbacks also catch
RPC_E_CALL_REJECTED / RPC_E_SERVERCALL_RETRYLATER and can publish an incomplete
snapshot as if the live model had changed.  This additive reader preserves
the successful PERF2C payload and its exact hashes, but lets those two busy
errors reach the existing bounded whole-snapshot retry scope.

No global patches, assignments, parameter writes, approximate comparison or
fallback to the permissive reader are performed here.  Unsupported optional
members retain their historical compatibility behavior.
"""
from __future__ import annotations

import hashlib
import inspect
import math
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

import r1_15a2_com_busy_snapshot_hotfix_v24916 as combusy
import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_multiblock as mb
import r1_15a2_runtime_v1 as rt
import r1_15a2_single_pass_snapshot_v24915p2c as parent
import r1_15a2_visum_parameters as vp
from r1_15a2_supply import SupplyContractError, canonical_hash, integer, key_text


RELEASE = "R1_15A2_V24917_GENFIX1_STRICT_SNAPSHOT_READS_20261027"


def _raise_if_busy(exc: Exception) -> None:
    if com.is_retryable_com_error(exc):
        raise exc


def _att(obj: Any, name: str, default: Any = None) -> Any:
    """rt.att compatibility, except that a busy COM server is never a value."""
    try:
        value = obj.AttValue(name)
        return default if value is None else value
    except Exception as exc:
        _raise_if_busy(exc)
        return default


def _collection_items(collection: Any, label: str = "collection") -> List[Any]:
    """com.collection_items with transient Count failures also propagated."""
    try:
        values = com.member_value(getattr(collection, "GetAll"))
        if values is None:
            raise RuntimeError("GetAll returned None")
        rows = list(values)
    except Exception as exc:
        _raise_if_busy(exc)
        raise RuntimeError("COM_GETALL_FAILED:%s:%s" % (label, exc)) from exc
    try:
        count_member = getattr(collection, "Count")
    except Exception as exc:
        _raise_if_busy(exc)
        count_member = None  # IOperations does not expose Count.
    if count_member is not None:
        count = com.exact_int(com.member_value(count_member), label + ".Count")
        if count != len(rows):
            raise RuntimeError("INCOMPLETE_COM_COLLECTION:%s:%s/%s" %
                               (label, len(rows), count))
    return rows


def _dseg_bindings(visum: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ds in _collection_items(visum.Net.DemandSegments):
        code = rt.sval(_att(ds, "CODE", "")).strip()
        if not code:
            continue
        matrix_no: Any = ""
        try:
            matrix = ds.ODMatrix
            if matrix is not None:
                matrix_no = rt.ival(_att(matrix, "NO", None), "")
        except Exception as exc:
            _raise_if_busy(exc)
        rows.append({"code": code, "norm_code": rt.norm_code(code),
                     "object": ds, "matrix_no": matrix_no})
    return rows


def _operation_records(visum: Any) -> List[parent.OperationRecord]:
    records: List[parent.OperationRecord] = []
    operations = _collection_items(visum.Procedures.Operations, "Operations")
    for position, op in enumerate(operations, 1):
        operation_type_raw = op.AttValue("OPERATIONTYPE")
        records.append(parent.OperationRecord(
            position=position,
            obj=op,
            operation_type_raw=operation_type_raw,
            operation_type=com.exact_int(operation_type_raw, "OPERATIONTYPE"),
            active=int(com.active_bool(op.AttValue("ACTIVE"))),
            comment=str(_att(op, "COMMENT", "")),
            name=str(_att(op, "NAME", "")),
        ))
    if not records:
        raise RuntimeError("EMPTY_OPERATION_LIST")
    return records


def _find_td_operation(records: Sequence[parent.OperationRecord],
                       required_codes: Sequence[str]):
    """Parent TD resolution order, preserving genuine unsupported fallbacks."""
    best = None
    audit: List[Dict[str, Any]] = []
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
        for prop in ("TripDistributionParameters", "TripDistributionParameter"):
            try:
                params = getattr(record.obj, prop)
                if params is not None:
                    source = prop
                    break
            except Exception as exc:
                _raise_if_busy(exc)
        row["parameter_source"] = source
        row["parameter_status"] = "OK" if params is not None else "UNREADABLE"
        score = 100 if record.active else 0
        dset = ""
        if params is not None:
            for attr in ("DSTRATSET", "DStratSet", "DEMANDSTRATUMSET"):
                dset = mb.sval(_att(params, attr, ""))
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
        and required_upper <= (com.code_set(row["dstratset"])
                               if row.get("dstratset") else set())
    ]
    if len(complete_active) > 1:
        for row in complete_active:
            row["resolution_error"] = "AMBIGUOUS_ACTIVE_OPERATION_SCOPE"
        return None, None, audit
    best[3]["selected"] = 1
    return best[1], best[2], audit


def _dstrat_object(params: Any, code: str, prefixes: Sequence[str]):
    names: List[str] = []
    for prefix in prefixes:
        names.extend((prefix + "DStratParameters", prefix + "DStratParas"))
    names.extend(("DStratParameters", "DStratParas"))
    for name in names:
        try:
            obj = getattr(params, name)
        except Exception as exc:
            _raise_if_busy(exc)
            continue
        if (getattr(obj, "_oleobj_", None) is None and
                (inspect.ismethod(obj) or inspect.isfunction(obj) or inspect.isbuiltin(obj))):
            try:
                value = obj(code)
                if value is not None:
                    return value, name + "(code)"
            except Exception as exc:
                _raise_if_busy(exc)
        for method in ("ItemByKey", "Item"):
            try:
                value = getattr(obj, method)(code)
                if value is not None:
                    return value, name + "." + method
            except Exception as exc:
                _raise_if_busy(exc)
        try:
            for value in _collection_items(obj):
                live = mb.sval(_att(value, "DEMANDSTRATUMCODE", "") or
                               _att(value, "CODE", ""))
                if live == code:
                    return value, name + " iteration"
        except Exception as exc:
            _raise_if_busy(exc)
    return None, "NOT_FOUND"


def _read_any(obj: Any, attrs: Sequence[str]):
    for name in attrs:
        try:
            value = obj.AttValue(name)
            if value not in (None, ""):
                return name, value, "AttValue"
        except Exception as exc:
            _raise_if_busy(exc)
    for name in attrs:
        try:
            value = getattr(obj, name)
            if value not in (None, ""):
                return name, value, "property"
        except Exception as exc:
            _raise_if_busy(exc)
    return "", None, "NOT_READ"


def _td_snapshot(records: Sequence[parent.OperationRecord]):
    required = [item["dstrat_code"] for item in mb.COMPONENT_REGISTRY.values()]
    _op, params, operation_rows = _find_td_operation(records, required)
    if params is None:
        raise RuntimeError("Could not locate readable Trip Distribution operation")
    selected = [row for row in operation_rows if int(row.get("selected", 0) or 0) == 1]
    if not selected or int(selected[0].get("active", 0) or 0) != 1:
        raise RuntimeError("Selected Trip Distribution operation is inactive or unresolved")
    dset = mb.sval(selected[0].get("dstratset"))
    tokens = com.code_set(dset) if dset else set()
    missing = [code for code in required if code.upper() not in tokens]
    if missing:
        raise RuntimeError("Trip Distribution DStratSet misses: %s" % ",".join(missing))

    rows: List[Dict[str, Any]] = []
    for component, registry in mb.COMPONENT_REGISTRY.items():
        d_obj, _source = _dstrat_object(params, registry["dstrat_code"], ("TripDistribution",))
        if d_obj is None:
            rows.append({"component": component, "current_b": None,
                         "current_c": None, "status": "DSTRAT_NOT_FOUND"})
            continue
        grav = d_obj
        for prop in ("GravitationParameters", "GravityParameters", "DistributionParameters"):
            try:
                candidate = getattr(d_obj, prop)
                if candidate is not None:
                    grav = candidate
                    break
            except Exception as exc:
                _raise_if_busy(exc)
        _b_attr, b_raw, _b_mode = _read_any(grav, vp.TD_B_ATTRS)
        _c_attr, c_raw, _c_mode = _read_any(grav, vp.TD_C_ATTRS)
        b_value = mb.fval(b_raw, None)
        c_value = mb.fval(c_raw, None)
        status = "OK" if b_value is not None and c_value is not None else "PARAM_READ_INCOMPLETE"
        rows.append({"component": component, "current_b": b_value,
                     "current_c": c_value, "status": status})
    return rows, operation_rows


class _ReadContext(parent.SnapshotReadContext):
    """Same per-call memoization and telemetry keys as the parent reader."""

    def dseg_bindings(self):
        return self.get_once("dseg_bindings", lambda: _dseg_bindings(self.visum))

    def operation_records(self):
        return self.get_once("operation_records", lambda: _operation_records(self.visum))

    def td_and_operations(self):
        def load():
            records = self.operation_records()
            td_rows, audit = _td_snapshot(records)
            # This parent helper is pure: it never calls COM.
            return td_rows, parent._inventory_from_records(records, audit)
        return self.get_once("td_and_operations", load)


def _matrix_fingerprint(matrix: Any) -> Tuple[Dict[str, Any], float]:
    values = matrix.GetValues()
    array = np.asarray(values, dtype="<f8")
    if array.ndim != 2:
        raise RuntimeError("matrix array is not 2D: shape=%r" % (array.shape,))
    if not np.all(np.isfinite(array)) or np.any(array < 0):
        raise RuntimeError("Demand matrix contains nonfinite or negative values")
    contiguous = np.ascontiguousarray(array, dtype="<f8")
    total = float(np.sum(contiguous))
    row = {
        "matrix_no": rt.ival(_att(matrix, "NO", None), ""),
        "rows": int(contiguous.shape[0]),
        "cols": int(contiguous.shape[1]),
        "sha256_float64_le": hashlib.sha256(contiguous.tobytes(order="C")).hexdigest(),
    }
    return row, total


def _snapshot_once(adapter: Any) -> Dict[str, Any]:
    context = _ReadContext(adapter)
    links = context.links()
    fixed: List[Dict[str, Any]] = []
    addval_values: Dict[str, float] = {}
    for key, row in sorted(links.items()):
        addval_values[key_text(key)] = row["addval1"]
        fixed.append({name: value for name, value in row.items()
                      if name not in ("addval1", "object", "eligible")})

    dseg_rows = context.dseg_bindings()
    if len({row["norm_code"] for row in dseg_rows}) != len(dseg_rows):
        raise SupplyContractError("DUPLICATE_DSEG_IDENTITY")
    dseg_map = {row["norm_code"]: row.get("matrix_no") for row in dseg_rows}
    required = {core.norm_code(value) for value in
                (adapter.cfg["supply"]["passenger_dsegs"] +
                 adapter.cfg["supply"].get("freight_dsegs", []))}
    if not required <= set(dseg_map):
        raise SupplyContractError("REQUIRED_DEMAND_SEGMENT_MISSING:" +
                                  ",".join(sorted(required - set(dseg_map))))
    unbound = sorted(code for code in required if dseg_map[code] in (None, ""))
    if unbound:
        raise SupplyContractError("REQUIRED_DSEG_ODMATRIX_UNREADABLE:" + ",".join(unbound))
    numbers = {integer(row["matrix_no"]) for row in dseg_rows
               if row.get("matrix_no") not in (None, "")}
    numbers.update(integer(value) for value in
                   adapter.cfg["supply"].get("component_matrix_nos", []))
    matrix_rows: List[Dict[str, Any]] = []
    for matrix_no in sorted(numbers):
        matrix = adapter.visum.Net.Matrices.ItemByKey(matrix_no)
        row, matrix_sum = _matrix_fingerprint(matrix)
        expected_zones = adapter.cfg.get("expected_zones")
        if expected_zones is not None and (row["rows"], row["cols"]) != (
                int(expected_zones), int(expected_zones)):
            raise SupplyContractError("DEMAND_MATRIX_AXIS_SHAPE_MISMATCH:%s" % matrix_no)
        if not math.isfinite(matrix_sum) or matrix_sum < 0:
            raise SupplyContractError("NONFINITE_OR_NEGATIVE_DEMAND")
        matrix_rows.append(row)
    if not matrix_rows:
        raise SupplyContractError("EMPTY_DEMAND_FINGERPRINT")

    generation_values = context.generation_values()
    td_values, operations = context.td_and_operations()
    if (len(td_values) != len(mb.COMPONENT_REGISTRY) or
            any(row.get("status") != "OK" for row in td_values)):
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


def strict_snapshot(adapter: Any) -> Dict[str, Any]:
    """Read one exact snapshot; retry a busy read, never publish its defaults."""
    return combusy._read_retry(adapter, "V24917_STRICT_FULL_SNAPSHOT",
                              lambda: _snapshot_once(adapter))


__all__ = ["RELEASE", "strict_snapshot"]
