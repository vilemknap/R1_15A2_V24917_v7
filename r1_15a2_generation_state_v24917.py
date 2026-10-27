# -*- coding: utf-8 -*-
"""GENFIX1: exact Generation parent guard with bounded mismatch evidence.

The guard reads live state when the adapter provides generation_guard_snapshot.
It never rebases the accepted parent, restores parameters, or relaxes equality.
Evidence contains fingerprints and bounded samples, never full matrix values.
"""
from __future__ import annotations

import math
import numbers
from pathlib import Path
from typing import Any, Mapping

from r1_15a2_controller_v22 import atomic_json
from r1_15a2_supply import SupplyContractError


SCHEMA = "R1_15A2_V24917_GENERATION_PARENT_GENFIX1"
SAMPLE_LIMIT = 100
TEXT_LIMIT = 1000
_MISSING = object()
_CORE_KEYS = frozenset((
    "addval1", "addval_hash", "fixed_link_hash", "matrix_hash", "matrices",
    "dseg_map", "dseg_hash", "generation_hash", "generation_values",
    "td_values", "td_hash", "operations_hash", "state_hash",
))


def _equal(before: Any, current: Any) -> bool:
    """Use the same exact object equality as the existing parent-state guard."""
    if before is _MISSING or current is _MISSING:
        return before is current
    try:
        return bool(before == current)
    except (TypeError, ValueError):
        # An invalid/ambiguous snapshot payload is never accepted as equal.
        return False


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _keys(before: Mapping, current: Mapping):
    return sorted(set(before) | set(current), key=lambda key: (str(type(key)), str(key)))


def _safe(value: Any, depth: int = 0) -> Any:
    """Bound evidence recursively and make scalar/numpy scalar values JSON-safe."""
    if value is _MISSING:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value if len(value) <= TEXT_LIMIT else value[:TEXT_LIMIT] + "...[truncated]"
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        result = float(value)
        return result if math.isfinite(result) else {"nonfinite": str(result)}
    if depth >= 6:
        return {"type": type(value).__name__, "detail": "DEPTH_LIMIT"}
    if isinstance(value, Mapping):
        keys = sorted(value, key=str)
        result = {str(key): _safe(value[key], depth + 1) for key in keys[:SAMPLE_LIMIT]}
        if len(keys) > SAMPLE_LIMIT:
            result["__total_keys__"] = len(keys)
            result["__truncated__"] = True
        return result
    if isinstance(value, (list, tuple)):
        sample = [_safe(item, depth + 1) for item in value[:SAMPLE_LIMIT]]
        if len(value) > SAMPLE_LIMIT:
            return {"sample": sample, "total_items": len(value), "truncated": True}
        return sample
    # Numpy scalars such as bool_ are not all numbers.Real subclasses.
    if getattr(value, "ndim", None) == 0 and callable(getattr(value, "item", None)):
        return _safe(value.item(), depth + 1)
    if hasattr(value, "shape") and hasattr(value, "dtype"):
        # Snapshot extensions may be malformed; do not dump a matrix or ndarray.
        return {"type": type(value).__name__, "shape": list(value.shape),
                "dtype": str(value.dtype), "values_omitted": True}
    return {"type": type(value).__name__, "text": str(value)[:TEXT_LIMIT]}


def _change(key_name: str, key: Any, before: Any, current: Any):
    return {key_name: _safe(key), "before_present": before is not _MISSING,
            "current_present": current is not _MISSING,
            "before": _safe(before), "current": _safe(current)}


def _mapping_changes(before: Any, current: Any, key_name: str = "key"):
    before, current = _mapping(before), _mapping(current)
    count, sample = 0, []
    for key in _keys(before, current):
        old, new = before.get(key, _MISSING), current.get(key, _MISSING)
        if not _equal(old, new):
            count += 1
            if len(sample) < SAMPLE_LIMIT:
                sample.append(_change(key_name, key, old, new))
    return {"changed_count": count, "sample": sample, "truncated": count > len(sample)}


def _generation_changes(before: Any, current: Any):
    before, current = _mapping(before), _mapping(current)
    attrs, sample, count = [], [], 0
    for attr in _keys(before, current):
        old_attr, new_attr = before.get(attr, _MISSING), current.get(attr, _MISSING)
        if _equal(old_attr, new_attr):
            continue
        attrs.append(str(attr))
        old_map, new_map = _mapping(old_attr), _mapping(new_attr)
        for zone in _keys(old_map, new_map):
            old, new = old_map.get(zone, _MISSING), new_map.get(zone, _MISSING)
            if not _equal(old, new):
                count += 1
                if len(sample) < SAMPLE_LIMIT:
                    row = _change("zone_no", zone, old, new)
                    row["attribute"] = str(attr)
                    sample.append(row)
    return {"changed_attribute_count": len(attrs),
            "changed_attributes": attrs[:SAMPLE_LIMIT],
            "changed_value_count": count, "sample": sample,
            "truncated": count > len(sample) or len(attrs) > SAMPLE_LIMIT}


def _indexed_rows(value: Any, key: str):
    result = {}
    if not isinstance(value, (list, tuple)):
        return result
    for position, row in enumerate(value):
        identity = row.get(key) if isinstance(row, Mapping) else None
        # Include an occurrence discriminator so duplicate identities are not lost.
        label = str(identity) if identity is not None else "position:%d" % position
        unique = label
        occurrence = 1
        while unique in result:
            occurrence += 1
            unique = "%s#%d" % (label, occurrence)
        result[unique] = row
    return result


def _row_changes(before: Any, current: Any, key: str, *, matrix: bool = False):
    before, current = _indexed_rows(before, key), _indexed_rows(current, key)
    count, sample = 0, []
    matrix_fields = ("matrix_no", "rows", "cols", "sha256_float64_le")
    for identity in _keys(before, current):
        old, new = before.get(identity, _MISSING), current.get(identity, _MISSING)
        if _equal(old, new):
            continue
        count += 1
        if len(sample) >= SAMPLE_LIMIT:
            continue
        if matrix:
            # Even an unexpected payload cannot place matrix cell values in the audit.
            old = ({name: old.get(name) for name in matrix_fields}
                   if isinstance(old, Mapping) else old)
            new = ({name: new.get(name) for name in matrix_fields}
                   if isinstance(new, Mapping) else new)
        sample.append(_change(key, identity, old, new))
    return {"changed_count": count, "sample": sample, "truncated": count > len(sample)}


def _operation_view(adapter: Any):
    result = {"view": "CURRENT_ONLY", "before_inventory_available": False}
    if not hasattr(adapter, "visum"):
        return dict(result, status="UNAVAILABLE_NO_VISUM")
    try:
        import r1_15a2_com_compat as com
        rows = com.operation_rows(adapter.visum)
        sample = [{str(key): _safe(value) for key, value in row.items() if key != "object"}
                  for row in rows[:SAMPLE_LIMIT]]
        return dict(result, status="READ", total_count=len(rows), sample=sample,
                    truncated=len(rows) > len(sample))
    except Exception as exc:
        return dict(result, status="READ_FAILED", error_type=type(exc).__name__,
                    error=str(exc)[:TEXT_LIMIT])


def snapshot_diff(expected: Mapping, current: Mapping):
    """Return a bounded exact-state diff; hashes alone never decide equality."""
    expected, current = _mapping(expected), _mapping(current)
    changed = [key for key in _keys(expected, current)
               if not _equal(expected.get(key, _MISSING), current.get(key, _MISSING))]
    hashes = [key for key in changed if str(key).endswith("_hash") and key != "state_hash"]
    extensions = [key for key in changed if key not in _CORE_KEYS]
    return {
        "changed_top_level_count": len(changed),
        "changed_top_level_keys": [_safe(key) for key in changed[:SAMPLE_LIMIT]],
        "changed_hash_domains": [_safe(key) for key in hashes[:SAMPLE_LIMIT]],
        "hash_domains": {str(key): {"before": _safe(expected.get(key, _MISSING)),
                                    "current": _safe(current.get(key, _MISSING))}
                         for key in hashes[:SAMPLE_LIMIT]},
        "matrices": _row_changes(expected.get("matrices"), current.get("matrices"),
                                  "matrix_no", matrix=True),
        "generation_values": _generation_changes(expected.get("generation_values"),
                                                  current.get("generation_values")),
        "td_values": _row_changes(expected.get("td_values"), current.get("td_values"), "component"),
        "dseg_map": _mapping_changes(expected.get("dseg_map"), current.get("dseg_map"), "dseg"),
        "addval1": _mapping_changes(expected.get("addval1"), current.get("addval1"), "link"),
        "extensions": {"changed_count": len(extensions), "sample": [
            _change("key", key, expected.get(key, _MISSING), current.get(key, _MISSING))
            for key in extensions[:SAMPLE_LIMIT]], "truncated": len(extensions) > SAMPLE_LIMIT},
        "sample_limit": SAMPLE_LIMIT,
    }


def _write_preserving_failure(path: Path, payload: Any, primary: BaseException):
    try:
        atomic_json(path, payload)
    except Exception as exc:
        # An unavailable evidence directory must not replace the scientific/COM failure.
        try:
            primary.generation_parent_audit_error = "%s:%s" % (type(exc).__name__, str(exc)[:TEXT_LIMIT])
        except Exception:
            pass


def require_parent(adapter: Any, expected_state: Mapping, folder: Any, *, phase: str):
    """Read and verify the exact accepted parent; return that live snapshot on pass.

    Uses the optional uncached adapter API. Fallback keeps existing mock/adapter
    compatibility. A mismatch is recorded, then raises the original guard code.
    """
    folder = Path(folder)
    fresh = getattr(adapter, "generation_guard_snapshot", None)
    use_fresh = callable(fresh)
    reader = fresh if use_fresh else adapter.snapshot
    audit = {"schema": SCHEMA, "phase": str(phase),
             "snapshot_source": "generation_guard_snapshot" if use_fresh else "snapshot",
             "expected_state_hash": _safe(_mapping(expected_state).get("state_hash")),
             "exact_object_equality_required": True, "parent_rebased": False}
    try:
        current = reader()
    except BaseException as exc:
        audit.update(status="SNAPSHOT_READ_FAILED", passes=False,
                     error_type=type(exc).__name__, error=str(exc)[:TEXT_LIMIT])
        _write_preserving_failure(folder / "GENERATION_PARENT_CHECK.json", audit, exc)
        raise
    audit["current_state_hash"] = _safe(_mapping(current).get("state_hash"))
    if _equal(current, expected_state):
        audit.update(status="EXACT_PARENT_MATCH", passes=True)
        atomic_json(folder / "GENERATION_PARENT_CHECK.json", audit)
        return current

    audit.update(status="PARENT_STATE_CHANGED", passes=False)
    error = SupplyContractError("V242_GENERATION_TRIAL_PARENT_CHANGED")
    _write_preserving_failure(folder / "GENERATION_PARENT_CHECK.json", audit, error)
    try:
        detail = dict(audit, **snapshot_diff(expected_state, current))
        if "operations_hash" in detail["changed_hash_domains"]:
            detail["operation_inventory"] = _operation_view(adapter)
    except Exception as exc:
        # Malformed state should still fail closed if optional detail extraction fails.
        detail = dict(audit, diff_error_type=type(exc).__name__, diff_error=str(exc)[:TEXT_LIMIT])
    _write_preserving_failure(folder / "GENERATION_PARENT_DIFF.json", detail, error)
    raise error

