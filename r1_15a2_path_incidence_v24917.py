"""Exact sparse-incidence validation and bounded NumPy hashing helpers."""
from __future__ import annotations

import hashlib
import numpy as np


def indices(values, size, label):
    a = np.asarray(values)
    if (a.ndim != 1 or a.dtype.kind not in 'iuf' or not np.isfinite(a).all()
            or np.any(a < 0) or np.any(a >= size) or np.any(a != np.floor(a))):
        raise ValueError('PATH_INCIDENCE_INDEX_INVALID:' + label)
    return a.astype(np.int64, copy=False)


def sparse_arrays(op, n_rows, n_cols):
    if getattr(op, 'n_rows', n_rows) != n_rows or getattr(op, 'n_cols', n_cols) != n_cols:
        raise ValueError('PATH_INCIDENCE_OPERATOR_SHAPE')
    row = indices(op.row_idx, n_rows, 'row')
    col = indices(op.col_idx, n_cols, 'col')
    value = np.asarray(op.values, dtype=float)
    if (value.ndim != 1 or row.shape != col.shape or row.shape != value.shape
            or not np.isfinite(value).all() or np.any(value < 0)):
        raise ValueError('PATH_INCIDENCE_OPERATOR_INVALID')
    return row, col, value


def matrix_values_hash(values):
    """Byte-identical to the project's hex-cell hash; bounded 4096-cell blocks.

    No rounding, byte-order change or new hash protocol. The C-level join/map
    avoids per-cell Python indexing and digest updates; signed zero is preserved.
    """
    a = np.asarray(values, dtype=np.float64)
    if a.ndim != 2 or not np.isfinite(a).all():
        raise ValueError('PATH_INCIDENCE_HASH_MATRIX_INVALID')
    h = hashlib.sha256()
    h.update(('%dx%d|' % a.shape).encode('ascii'))
    flat = a.ravel(order='C')
    for start in range(0, flat.size, 4096):
        h.update((';'.join(map(float.hex, flat[start:start+4096])) + ';').encode('ascii'))
    return h.hexdigest()
