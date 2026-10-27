# -*- coding: utf-8 -*-
"""Bitwise-exact NumPy replacements for the three hot 11D v1.3 loops.

Installed only by r1_15a2_diagfast_v2 in FAST_EXACT. The original Python
functions stay available as ``_reference_<name>`` and are used for every input
the fast path cannot reproduce exactly.

Exactness argument
------------------
* Cells are visited in the same row-major order (C-order flatten).
* The reference accumulates with ``total += x`` left to right. ``np.cumsum``
  is a strictly sequential left-to-right float64 accumulation, so its last
  element is bitwise identical to the Python loop (``np.sum`` would NOT be:
  it uses pairwise summation).
* ``x * c`` products are separate IEEE-754 float64 multiplications in both.
* Bin membership reproduces ``bin_label_for_value`` rule by rule, first match
  wins, including the closed first bin and the open infinite last bin.
* Any input that is not a plain rectangular grid of Python float/int values
  (None, str, bool, ragged rows) and any dimension mismatch returns ``None``;
  the caller then runs the untouched reference, which also produces the
  reference error message.
"""
from __future__ import annotations

from itertools import chain

import numpy as np

_INF = float("inf")
_ARRAY_CACHE = {}          # id(values) -> (values, array); one helper run only
_ARRAY_CACHE_LIMIT = 64


class _Rows(list):
    """List of row lists (reference type) carrying the float64 array."""
    __slots__ = ("np_values",)


def clear_cache():
    _ARRAY_CACHE.clear()


def _to_float64(vals):
    """C-contiguous float64 2-D array, or None if not exactly representable."""
    if isinstance(vals, _Rows):
        return vals.np_values
    if isinstance(vals, np.ndarray):
        return vals if vals.dtype == np.float64 and vals.ndim == 2 else None
    hit = _ARRAY_CACHE.get(id(vals))
    if hit is not None and hit[0] is vals:
        return hit[1]
    try:
        rows = vals if isinstance(vals, (list, tuple)) else list(vals)
        if not rows:
            return None
        width = len(rows[0])
        if width == 0 or any(len(r) != width for r in rows):
            return None
        if not set(map(type, chain.from_iterable(rows))) <= {float, int}:
            return None
        arr = np.array(rows, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        return None
    if arr.ndim != 2:
        return None
    arr = np.ascontiguousarray(arr)
    if isinstance(vals, tuple):
        if len(_ARRAY_CACHE) >= _ARRAY_CACHE_LIMIT:
            _ARRAY_CACHE.clear()
        _ARRAY_CACHE[id(vals)] = (vals, arr)
    return arr


def _seq_sum(values):
    """Left-to-right float64 sum, bitwise equal to ``t = 0.0; t += v``."""
    if values.size == 0:
        return 0.0
    seq = np.empty(values.size + 1, dtype=np.float64)
    seq[0] = 0.0
    seq[1:] = values
    return float(np.cumsum(seq)[-1])


def _bin_index(c, bins):
    """Vectorised bin_label_for_value(): first matching bin index, -1 if none."""
    out = np.full(c.shape, -1, dtype=np.int64)
    free = np.ones(c.shape, dtype=bool)
    for idx, (low, high, _label) in enumerate(bins):
        if high == _INF:
            hit = c > low
        elif idx == 0:
            hit = (c >= low) & (c <= high)
        else:
            hit = (c > low) & (c <= high)
        take = hit & free
        out[take] = idx
        free &= ~take
    return out


def make_matrix_total(reference_read):
    def matrix_total(mat):
        vals, _method = reference_read(mat)
        a = _to_float64(vals)
        if a is None:
            return None
        flat = a.ravel()
        finite = np.isfinite(flat)
        nonfinite = int(flat.size - int(finite.sum()))
        x = flat[finite]
        neg = x < 0
        negative = int(neg.sum())
        x = np.where(neg, 0.0, x)
        return _seq_sum(x), negative, nonfinite
    return matrix_total


def make_compute_matrix_distribution(reference_read):
    def compute_matrix_distribution(mat, class_matrix_values, bins,
                                    condition_low=None, condition_high=None):
        vals, method = reference_read(mat)
        a = _to_float64(vals)
        c2 = _to_float64(class_matrix_values)
        if a is None or c2 is None or a.shape != c2.shape:
            return None          # reference raises/handles with its own message
        bins = list(bins)        # original low/high objects are written to outputs
        for low, high, _label in bins:
            if type(low) not in (int, float) or type(high) not in (int, float):
                return None
        x = a.ravel()
        c = c2.ravel()
        valid = np.isfinite(x) & np.isfinite(c)
        nonfinite_cells = int(x.size - int(valid.sum()))
        x = x[valid]
        c = c[valid]
        neg = x < 0
        negative_cells = int(neg.sum())
        x = np.where(neg, 0.0, x)
        keep = x != 0.0
        x = x[keep]
        c = c[keep]

        total = _seq_sum(x)
        weighted_sum = _seq_sum(x * c)
        in_cond = np.ones(x.shape, dtype=bool)
        outside_low = 0.0
        outside_high = 0.0
        if condition_low is not None:
            lowmask = c < condition_low
            outside_low = _seq_sum(x[lowmask])
            in_cond &= ~lowmask
        if condition_high is not None:
            highmask = c > condition_high
            outside_high = _seq_sum(x[highmask])
            in_cond &= ~highmask
        xi = x[in_cond]
        ci = c[in_cond]
        conditioned_total = _seq_sum(xi)
        conditioned_weighted_sum = _seq_sum(xi * ci)

        idx = _bin_index(ci, bins)
        labels_in_order = []
        for _low, _high, label in bins:
            if label not in labels_in_order:
                labels_in_order.append(label)
        bin_sums = {}
        for label in labels_in_order:
            members = [k for k, (_l, _h, lab) in enumerate(bins) if lab == label]
            mask = np.isin(idx, members) if len(members) > 1 else (idx == members[0])
            bin_sums[label] = _seq_sum(xi[mask])

        rows = []
        for low, high, label in bins:
            value = bin_sums[label]
            rows.append({
                "bin_label": label,
                "bin_low": low,
                "bin_high": "INF" if high == _INF else high,
                "volume": value,
                "share_conditioned": value / conditioned_total if conditioned_total > 0 else 0.0,
                "share_total": value / total if total > 0 else 0.0,
            })
        meta = {
            "read_method": method,
            "total_volume": total,
            "conditioned_volume": conditioned_total,
            "outside_low_volume": outside_low,
            "outside_high_volume": outside_high,
            "outside_low_share_total": outside_low / total if total > 0 else 0.0,
            "outside_high_share_total": outside_high / total if total > 0 else 0.0,
            "mean_all": weighted_sum / total if total > 0 else None,
            "mean_conditioned": (conditioned_weighted_sum / conditioned_total
                                 if conditioned_total > 0 else None),
            "negative_cells": negative_cells,
            "nonfinite_cells": nonfinite_cells,
        }
        return rows, meta
    return compute_matrix_distribution


def make_load_class_matrix(reference_read, expected_n_getter):
    def load_class_matrix(mat):
        vals, method = reference_read(mat)
        a = _to_float64(vals)
        n = int(expected_n_getter())
        if a is None or a.shape != (n, n):
            return None          # reference raises its own 681x681 message
        a = a.copy()
        bad = ~np.isfinite(a)
        nonfinite = int(bad.sum())
        a[bad] = 0.0
        neg = a < 0
        negative = int(neg.sum())
        a[neg] = 0.0
        out = _Rows(a.tolist())
        out.np_values = a
        return out, {"read_method": method, "nonfinite_cells": nonfinite, "negative_cells": negative}
    return load_class_matrix


def install(env, prof=None):
    """Swap the three hot functions in an 11D namespace, keep references.

    The wrappers resolve ``read_matrix_values`` at call time so the DIAGFAST
    single-read cache (and any later overlay) is always honoured.
    """
    clear_cache()

    def read(mat):
        return env["read_matrix_values"](mat)

    fast = {
        "matrix_total": make_matrix_total(read),
        "compute_matrix_distribution": make_compute_matrix_distribution(read),
        "load_class_matrix": make_load_class_matrix(read, lambda: env["EXPECTED_ZONE_COUNT"]),
    }
    for name, fn in fast.items():
        ref = env[name]
        env["_reference_" + name] = ref

        def wrapper(*args, _fast=fn, _ref=ref, _name=name, **kwargs):
            result = _fast(*args, **kwargs)
            if result is None:
                if prof is not None:
                    prof.count("v2_numpy_reference_fallback:" + _name)
                return _ref(*args, **kwargs)
            if prof is not None:
                prof.count("v2_numpy_fast:" + _name)
            return result
        wrapper.__name__ = name
        wrapper.__wrapped__ = ref
        env[name] = wrapper
    return sorted(fast)
