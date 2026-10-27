"""PTV Visum 2026 COM boundary. No model writes or automatic COM activation.

References are listed in COM_API_SOURCE_REGISTER.json. In particular GetAll
indices are NOT network object numbers; Operations uses sequence positions;
and returned Dispatch objects may be callable without being factory methods.
"""
from __future__ import annotations
import inspect
import math
import re
import time

TG = 45
TD = 46
EXECUTE_SCRIPT = 65
GROUP = 75
ASSIGNMENT_PRT = 101
ASSIGNMENT_PUT = 100
SKIMS_PRT = 103
ALL_ROUTES = 0  # Explicit PTV ILists.CreatePrTPathList Python example, 2026.

RPC_E_CALL_REJECTED = -2147418111
RPC_E_SERVERCALL_RETRYLATER = -2147417846
E_OUTOFMEMORY = -2147024882
E_INVALIDARG = -2147024809
DISP_E_OVERFLOW = -2147352566
_BOUNDED_PAGE_SIZE_HRESULTS = frozenset((E_OUTOFMEMORY, DISP_E_OVERFLOW))
_RETRYABLE_COM_MESSAGES = (
    "call was rejected by callee",
    "server call retry later",
    "volany odmitl volani",
    "volan\u00fd odm\u00edtl vol\u00e1n\u00ed",
)


def _signed_hresult(value):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number > 0x7fffffff:
        number -= 0x100000000
    return number


def com_error_hresult(exc):
    """Return a normalized signed HRESULT when a COM exception exposes one."""
    for name in ("hresult", "HRESULT", "scode"):
        value = getattr(exc, name, None)
        result = _signed_hresult(value)
        if result is not None:
            return result
    for value in getattr(exc, "args", ()):
        result = _signed_hresult(value)
        if result is not None and (result < -1000 or result > 1000):
            return result
        if isinstance(value, (tuple, list)):
            for nested in value:
                result = _signed_hresult(nested)
                if result is not None and (result < -1000 or result > 1000):
                    return result
    return None


def is_retryable_com_error(exc):
    """Recognize only transient RPC call-rejected/retry-later failures."""
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if com_error_hresult(current) in (RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER):
            return True
        text = str(current).lower()
        normalized = (text.replace("\u00e1", "a").replace("\u00ed", "i")
                           .replace("\u00fd", "y").replace("\u011b", "e")
                           .replace("\u0161", "s").replace("\u010d", "c")
                           .replace("\u0159", "r").replace("\u017e", "z"))
        if any(token in text or token in normalized for token in _RETRYABLE_COM_MESSAGES):
            return True
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return False


def scoped_retry_policy(policy, scope=None):
    """Return a fail-closed retry policy for one explicitly named COM scope.

    Top-level settings remain the generic policy.  A release may add exact
    overrides below ``scoped_policies`` for long-running read-only operations
    such as bounded path export or final-state verification.  The scope only
    changes timing/budget; retry eligibility remains restricted to the two
    transient RPC HRESULTs recognized by :func:`is_retryable_com_error`.
    """
    raw = dict(policy or {})
    if not scope:
        raw.pop("scoped_policies", None)
        return raw
    scoped_map = raw.pop("scoped_policies", {}) or {}
    if not isinstance(scoped_map, dict):
        raise RuntimeError("INVALID_COM_SCOPED_RETRY_POLICIES")
    override = scoped_map.get(str(scope), {}) or {}
    if not isinstance(override, dict):
        raise RuntimeError("INVALID_COM_SCOPED_RETRY_POLICY:%s" % scope)
    enabled = raw.get("enabled") is True and override.get("enabled", True) is True
    raw.update(override)
    raw["enabled"] = enabled
    raw["scope"] = str(scope)
    return raw


def _retry_budget(policy):
    raw = dict(policy or {})
    enabled = raw.get("enabled") is True
    attempts = max(1, int(raw.get("max_attempts", 1 if not enabled else 5)))
    if not enabled:
        attempts = 1
    initial = max(0.0, float(raw.get("initial_delay_seconds", 0.05)))
    factor = max(1.0, float(raw.get("backoff_factor", 2.0)))
    maximum = max(initial, float(raw.get("max_delay_seconds", 0.8)))
    raw_elapsed = raw.get("max_elapsed_seconds")
    maximum_elapsed = None if raw_elapsed in (None, "") else max(0.0, float(raw_elapsed))
    return attempts, initial, factor, maximum, maximum_elapsed


def _retry_policy(policy):
    return _retry_budget(policy)[:4]


def com_retry_settings(policy):
    """Public normalized retry settings for helper-level retries."""
    return _retry_policy(policy)


def com_retry_budget_settings(policy, scope=None):
    """Public normalized retry settings including an optional elapsed lease."""
    return _retry_budget(scoped_retry_policy(policy, scope))


def _pump_waiting_messages():
    try:
        import pythoncom  # type: ignore
        pythoncom.PumpWaitingMessages()
    except Exception:
        pass


def com_call_with_retry(call, label="COM_CALL", retry_policy=None, sleep_fn=time.sleep,
                        on_retry=None, on_exhausted=None, clock_fn=time.monotonic):
    """Run one COM call with bounded retry only for transient RPC rejection.

    Signature/overload fallback is intentionally not handled here. TypeError and
    all non-transient exceptions escape immediately.  The optional elapsed lease
    is an additional hard bound, not permission to retry other exceptions.
    ``on_retry`` is called before a real wait; ``on_exhausted`` records the final
    transient failure without changing the original exception type.
    """
    attempts, delay, factor, maximum, maximum_elapsed = _retry_budget(retry_policy)
    started = clock_fn()
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not is_retryable_com_error(exc):
                raise
            elapsed = max(0.0, float(clock_fn() - started))
            next_delay = max(0.0, float(delay))
            attempts_exhausted = attempt >= attempts
            elapsed_exhausted = (maximum_elapsed is not None and
                                 (elapsed >= maximum_elapsed or
                                  elapsed + next_delay > maximum_elapsed))
            exhausted = attempts_exhausted or elapsed_exhausted
            event = {
                "label": str(label),
                "attempt": attempt,
                "next_attempt": None if exhausted else attempt + 1,
                "max_attempts": attempts,
                "hresult": com_error_hresult(exc),
                "delay_seconds": 0.0 if exhausted else next_delay,
                "elapsed_seconds": elapsed,
                "max_elapsed_seconds": maximum_elapsed,
                "exhausted": exhausted,
                "exhausted_by_attempts": attempts_exhausted,
                "exhausted_by_elapsed": elapsed_exhausted,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if exhausted:
                if on_exhausted is not None:
                    on_exhausted(event)
                raise
            if on_retry is not None:
                on_retry(event)
            _pump_waiting_messages()
            if next_delay > 0.0:
                sleep_fn(next_delay)
            delay = min(maximum, next_delay * factor if next_delay > 0.0 else maximum)
    raise RuntimeError("COM_RETRY_INTERNAL_ERROR:%s" % label)


def is_bounded_page_size_error(exc):
    """Return True only for errors for which a smaller bounded page is plausible.

    Transient RPC call rejection is deliberately excluded.  A busy Visum host
    must retry the *same* FirstObject/LastObject range rather than silently
    changing pagination.
    """
    current = exc
    seen = set()
    tokens = (
        "page too large", "page_too_large", "array too large", "array_too_large",
        "result too large", "result_too_large", "invalid bounded range",
        "range too large", "out of memory", "not enough memory",
        "memory allocation", "simulated_com_page_too_large",
    )
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if is_retryable_com_error(current):
            return False
        if isinstance(current, (MemoryError, OverflowError)):
            return True
        if com_error_hresult(current) in _BOUNDED_PAGE_SIZE_HRESULTS:
            return True
        text = str(current).lower()
        if any(token in text for token in tokens):
            return True
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return False


def bounded_ole_invoke_with_retry(ole, memid, kind, first, last, *,
                                  retry_policy=None, label="BOUNDED_SAVE_TO_ARRAY",
                                  sleep_fn=time.sleep, on_retry=None,
                                  on_exhausted=None, clock_fn=time.monotonic):
    """Invoke verified bounded SaveToArray with transient-only retry.

    The exact page range is immutable across retries. Page-size backtracking is
    a caller decision and must only happen after ``is_bounded_page_size_error``.
    Long path exports use only the explicit ``bounded_path_export`` timing scope;
    exception eligibility is unchanged and remains transient-RPC-only.
    """
    first = exact_int(first, "FirstObject")
    last = exact_int(last, "LastObject")
    if first < 1 or last < first:
        raise RuntimeError("INVALID_BOUNDED_SAVE_TO_ARRAY_RANGE")
    scoped = scoped_retry_policy(retry_policy, "bounded_path_export")
    return com_call_with_retry(
        lambda: ole.Invoke(memid, 0, kind, True, first, last),
        "%s[%d:%d]" % (label, first, last),
        retry_policy=scoped, sleep_fn=sleep_fn, on_retry=on_retry,
        on_exhausted=on_exhausted, clock_fn=clock_fn)


def get_multi_att_values(container, attr_name, retry_policy=None):
    """Read all values; keep overload fallback separate from COM-busy retry."""
    method = getattr(container, "GetMultiAttValues")
    try:
        return list(com_call_with_retry(
            lambda: method(attr_name, False),
            "GetMultiAttValues(%s,False)" % attr_name, retry_policy))
    except TypeError:
        return list(com_call_with_retry(
            lambda: method(attr_name),
            "GetMultiAttValues(%s)" % attr_name, retry_policy))


def set_multi_att_values(container, attr_name, rows, retry_policy=None):
    """Write all values; keep overload fallback separate from COM-busy retry."""
    method = getattr(container, "SetMultiAttValues")
    try:
        return com_call_with_retry(
            lambda: method(attr_name, rows, False),
            "SetMultiAttValues(%s,False)" % attr_name, retry_policy)
    except TypeError:
        return com_call_with_retry(
            lambda: method(attr_name, rows),
            "SetMultiAttValues(%s)" % attr_name, retry_policy)


def zone_identity(visum, expected_zone_nos=None, retry_policy=None):
    """Read Zone.NO once and return model-axis order plus No -> COM row key."""
    rows = get_multi_att_values(visum.Net.Zones, "NO", retry_policy)
    ordered = []
    result = {}
    seen_indices = set()
    for index, no in rows:
        index, no = exact_int(index, "zone index"), exact_int(no, "Zone.NO")
        if no in result or index in seen_indices:
            raise RuntimeError("DUPLICATE_ZONE_WRITE_IDENTITY")
        result[no] = index
        seen_indices.add(index)
        ordered.append(no)
    if expected_zone_nos is not None:
        expected = [exact_int(x, "Zone.NO") for x in expected_zone_nos]
        if len(expected) != len(set(expected)) or set(result) != set(expected):
            raise RuntimeError("ZONE_WRITE_COVERAGE_MISMATCH")
    return ordered, result


def finite_float(value, label="value"):
    if value is None or isinstance(value, bool):
        raise RuntimeError("INVALID_NUMERIC:%s:%r" % (label, value))
    if isinstance(value, str):
        text = value.strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
        # Decimal comma is supported. A simultaneous dot and comma is ambiguous.
        if not text or ("," in text and "." in text):
            raise RuntimeError("INVALID_NUMERIC:%s:%r" % (label, value))
        value = text.replace(",", ".")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise RuntimeError("INVALID_NUMERIC:%s:%r" % (label, value)) from exc
    if not math.isfinite(result):
        raise RuntimeError("NONFINITE_NUMERIC:%s" % label)
    return result


def exact_int(value, label="id"):
    result = finite_float(value, label)
    if result != math.trunc(result):
        raise RuntimeError("NONINTEGRAL_ID:%s:%r" % (label, value))
    return int(result)


def active_bool(value):
    """Python bool and COM VARIANT_BOOL (-1/0), plus serialized forms."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "yes", "active"):
            return True
        if s in ("false", "no", "inactive"):
            return False
    n = finite_float(value, "ACTIVE")
    if n not in (-1, 0, 1):
        raise RuntimeError("UNKNOWN_ACTIVE_FLAG:%r" % value)
    return n != 0


def member_value(value):
    """Call actual Python methods only, never a returned COM Dispatch object.

    pywin32 CDispatch has __call__ (DISPID_VALUE). callable(Dispatch) is True
    even when Visum already returned the requested object property.
    """
    if getattr(value, "_oleobj_", None) is not None:
        return value
    if inspect.ismethod(value) or inspect.isfunction(value) or inspect.isbuiltin(value):
        return value()
    return value


def object_property(parent, name):
    value = member_value(getattr(parent, name))
    if value is None:
        raise RuntimeError("EMPTY_COM_OBJECT_PROPERTY:%s" % name)
    return value


def collection_items(coll, label="collection"):
    try:
        values = member_value(getattr(coll, "GetAll"))
        if values is None:
            raise RuntimeError("GetAll returned None")
        rows = list(values)
    except Exception as exc:
        # No ItemByKey(1..Count) guess: network keys can be sparse.
        raise RuntimeError("COM_GETALL_FAILED:%s:%s" % (label, exc)) from exc
    try:
        count_member = getattr(coll, "Count")
    except Exception:
        count_member = None  # IOperations does not define Count.
    if count_member is not None:
        count = exact_int(member_value(count_member), label + ".Count")
        if count != len(rows):
            raise RuntimeError("INCOMPLETE_COM_COLLECTION:%s:%s/%s" % (label, len(rows), count))
    return rows


def operation_rows(visum):
    """IOperations.ItemByKey uses 1-based POSITION, not AttValue('NO')."""
    rows = []
    for position, op in enumerate(collection_items(visum.Procedures.Operations, "Operations"), 1):
        def text(attr):
            try:
                value = op.AttValue(attr)
                return "" if value is None else str(value)
            except Exception:
                return ""
        rows.append({"no": position, "position": position,
                     "type": exact_int(op.AttValue("OPERATIONTYPE"), "OPERATIONTYPE"),
                     "active": int(active_bool(op.AttValue("ACTIVE"))),
                     "comment": text("COMMENT"), "name": text("NAME"), "object": op})
    if not rows:
        raise RuntimeError("EMPTY_OPERATION_LIST")
    return rows


def code_set(value, label="code set"):
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("EMPTY_OR_NONSTRING_CODE_SET:%s" % label)
    return {x.strip("'\"").upper() for x in re.split(r"[,;{}\s]+", value) if x.strip("'\"")}


def indexed_zone_values(visum, attr_name, zone_nos, retry_policy=None, zone_indices=None):
    """Join Zone.NO and attribute values by COM row key, then Zone.NO.

    A caller may supply the verified run-start ``zone_indices`` map so repeated
    candidate apply/rollback reads do not re-query Zone.NO.
    """
    if zone_indices is None:
        _ordered, zone_indices = zone_identity(visum, zone_nos, retry_policy)
    indices = {exact_int(index, "zone index"): exact_int(no, "Zone.NO")
               for no, index in zone_indices.items()}
    values = {}
    for index, raw in get_multi_att_values(visum.Net.Zones, attr_name, retry_policy):
        index = exact_int(index, "zone index")
        if index not in indices or index in values:
            raise RuntimeError("UNEXPECTED_OR_DUPLICATE_ZONE_ATTRIBUTE_INDEX")
        values[index] = finite_float(raw, "Zone.%s[%s]" % (attr_name, indices[index]))
    expected = {exact_int(x) for x in zone_nos}
    seen_zones = set(indices.values())
    if len(expected) != len(zone_nos) or seen_zones != expected or set(values) != set(indices):
        raise RuntimeError("ZONE_ATTRIBUTE_COVERAGE_MISMATCH:%s" % attr_name)
    by_no = {indices[index]: value for index, value in values.items()}
    return [by_no[exact_int(no)] for no in zone_nos]


def zone_write_indices(visum, zone_nos, retry_policy=None):
    _ordered, result = zone_identity(visum, zone_nos, retry_policy)
    return result


def bind_injected(namespace):
    """Never start Visum or attach to an unrelated running model via ROT."""
    value = namespace.get("Visum")
    source = "injected Visum"
    if value is None:
        value = namespace.get("COM")
        source = "injected COM"
    if value is None:
        raise RuntimeError("NO_INJECTED_VISUM: run the file inside the target Visum session; automatic GetActiveObject/Dispatch is intentionally disabled")
    for name in ("Net", "Procedures"):
        if getattr(value, name, None) is None:
            raise RuntimeError("NOT_A_VISUM_COM_INSTANCE:%s missing; the Python Hub environment does not expose COM" % name)
    return value, source


def validated_array_rows(rows, headers, required_columns):
    """No zip truncation, missing key coercion, or nonfinite volume tolerance."""
    result = []
    for position, row in enumerate(rows, 1):
        if len(row) != len(headers):
            raise RuntimeError("LIST_ROW_WIDTH_MISMATCH:row=%s got=%s expected=%s" % (position, len(row), len(headers)))
        rec = dict(zip(headers, row))
        for key in required_columns:
            if key not in rec:
                raise RuntimeError("REQUIRED_LIST_COLUMN_MISSING:%s" % key)
            if key == "Vol(AP)":
                rec[key] = finite_float(rec[key], key)
                if rec[key] < 0:
                    raise RuntimeError("NEGATIVE_PATH_VOLUME")
            else:
                rec[key] = exact_int(rec[key], key)
                if rec[key] < 0:
                    raise RuntimeError("NEGATIVE_PATH_ID:%s" % key)
        result.append(rec)
    return result


def normalized_prt_pathlink_rows(rows, headers):
    """Normalize Visum 2026 *actual* IPrTPathLinkList.SaveToArray layout.

    Live IPrTPathLinkList has hierarchical keys: a route header contains
    OrigZoneNo, DestZoneNo, PathIndex but blank link columns; subsequent child
    rows have Index, LinkNo, FromNodeNo, ToNodeNo but blank route keys.  Some
    exports are already flat.  Only real link children become output records.
    No route, link, OD, path index, or path sequence is invented.  Missing
    parent and discontinuous/gapped sequences fail closed.
    """
    required = ("OrigZoneNo", "DestZoneNo", "PathIndex", "Index", "LinkNo", "FromNodeNo", "ToNodeNo")
    if tuple(headers) != required:
        raise RuntimeError("PRT_PATHLINK_REQUIRED_SCHEMA_CHANGED")
    parent = None
    counts = {}
    ends = {}
    active_path = None
    closed = set()
    for source_row, raw in enumerate(rows, 1):
        if len(raw) != len(headers):
            raise RuntimeError("LIST_ROW_WIDTH_MISMATCH:row=%d got=%d expected=%d" %
                               (source_row, len(raw), len(headers)))
        data = dict(zip(headers, raw))
        def filled(name):
            value = data[name]
            return value is not None and str(value).strip() != ""
        route_present = tuple(filled(x) for x in required[:3])
        link_present = tuple(filled(x) for x in required[3:])
        if not any(link_present):
            # A pure route parent is a key, not a traversed link.  A completely
            # blank parent row is ambiguous and must not silently disappear.
            if not all(route_present):
                raise RuntimeError("PATHLINK_INCOMPLETE_ROUTE_PARENT:row=%d" % source_row)
            parent = tuple(exact_int(data[k],k) for k in required[:3])
            if min(parent) < 1:
                raise RuntimeError("PATHLINK_INVALID_PARENT_KEY:row=%d" % source_row)
            if parent in closed:
                raise RuntimeError("PATHLINK_REOPENED_ROUTE:row=%d" % source_row)
            if active_path is not None and active_path != parent:
                closed.add(active_path)
            active_path = parent
            continue
        if not all(link_present):
            raise RuntimeError("PATHLINK_INCOMPLETE_LINK_CHILD:row=%d" % source_row)
        if all(route_present):
            path = tuple(exact_int(data[k], k) for k in required[:3])
            if parent is not None and path != parent:
                # A flat new route is allowed, even immediately following a
                # hierarchical route, but it must start at Index=1 below.
                parent = path
        elif not any(route_present):
            if parent is None:
                raise RuntimeError("PATHLINK_ORPHAN_LINK_CHILD:row=%d" % source_row)
            path = parent
        else:
            # Host emitted only some path identifiers on a child.  Reuse the
            # route header exclusively if every supplied ID matches it.
            if parent is None:
                raise RuntimeError("PATHLINK_ORPHAN_PARTIAL_KEY:row=%d" % source_row)
            for j, name in enumerate(required[:3]):
                if route_present[j] and exact_int(data[name],name) != parent[j]:
                    raise RuntimeError("PATHLINK_CONFLICTING_PARENT:row=%d" % source_row)
            path = parent
        if min(path) < 1:
            raise RuntimeError("PATHLINK_INVALID_PATH_KEY:row=%d" % source_row)
        if active_path is not None and path != active_path:
            closed.add(active_path)
        if path in closed:
            raise RuntimeError("PATHLINK_NONCONTIGUOUS_ROUTE:row=%d" % source_row)
        active_path = path
        parent = path
        step, link_no, from_no, to_no = (exact_int(data[k],k) for k in required[3:])
        if step < 1 or link_no < 1 or from_no < 1 or to_no < 1:
            raise RuntimeError("PATHLINK_INVALID_DIRECTED_EDGE:row=%d" % source_row)
        expected = counts.get(path,0) + 1
        if step != expected:
            raise RuntimeError("PATHLINK_INDEX_NOT_CONTIGUOUS:row=%d path=%r index=%d expected=%d" %
                               (source_row,path,step,expected))
        if path in ends and ends[path] != from_no:
            raise RuntimeError("PATHLINK_BROKEN_TOPOLOGICAL_CONTINUITY:row=%d path=%r" % (source_row,path))
        ends[path] = to_no
        counts[path] = step
        yield dict(zip(required, (*path,step,link_no,from_no,to_no)))
