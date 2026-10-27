# -*- coding: utf-8 -*-
"""DIAGFAST V2: bulk COM reads + exact NumPy for 12D/11D (FAST_EXACT only).

Installed by r1_15a2_diagfast_v1.configure_namespace for FAST_EXACT. The
reference helper code still produces every output row; V2 only changes WHERE
attribute values come from and how the three 11D matrix loops are summed:

* per-object ``AttValue`` calls are replaced by one ``GetMultiAttValues`` per
  attribute and collection (column cache, one helper invocation only);
* every column is checked against a scalar ``AttValue`` of a real probe
  object (same value, same Python type, same -0.0 sign, same missing state);
* any technical mismatch (unsupported bulk API, bulk/scalar disagreement,
  ambiguous key, container order mismatch) falls back to the V1/reference path
  for that component and is recorded in the helper profile;
* malformed bulk data stays a DATA error (never a silent fallback).

Assumption made explicit: the row id returned by ``GetMultiAttValues`` is
the 1-based position of the object in the collection (the order of
``GetAll``). Where output order depends on it (11D traffic rows), V2 checks
it against ``GetAll`` before use. Live parity (99 artifacts) certifies it.
"""
from __future__ import annotations

import math
import os
from types import SimpleNamespace

import r1_15a2_diagfast_v1 as df
import r1_15a2_diagfast_numpy_v2 as fastnp

RELEASE_V2 = 'R1_15A2_DIAGFAST_V2_BULK_NUMPY_20261024'
FEATURES = ('bulk_12d_links', 'bulk_12d_countlocations', 'bulk_11d_countlocations',
            'bulk_11d_matrices', 'numpy_11d', 'memo_11d_curves', 'interp_11d_xs_cache')
DISABLE_ENV = 'R1_DIAGFAST_V2_DISABLE'


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

def options():
    """Feature switches: cfg['diagfast_v2'] and env R1_DIAGFAST_V2_DISABLE."""
    opts = {name: True for name in FEATURES}
    ctx = df.CONTEXT.get() or {}
    cfg = ctx.get('cfg') or {}
    for key, value in dict(cfg.get('diagfast_v2') or {}).items():
        if key in opts:
            opts[key] = bool(value)
    for token in os.environ.get(DISABLE_ENV, '').split(','):
        token = token.strip().lower()
        if token == 'all':
            opts = {name: False for name in FEATURES}
        elif token in opts:
            opts[token] = False
    return opts


# ---------------------------------------------------------------------------
# bulk column cache
# ---------------------------------------------------------------------------

class BulkUnavailable(Exception):
    """Attribute not readable in bulk; mirrors a failing scalar AttValue."""


class BulkLateFault(BaseException):
    """A probe fault after rows were handed out. Never swallowed by helpers."""


def same_value(a, b):
    """Exact equality as seen by csv/json writers: type, value, -0.0, NaN."""
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    try:
        return bool(a == b)
    except Exception:
        return False


def _capability(reason):
    return df.CapabilityUnavailable(df.DiagFastError(reason))


class BulkCollection:
    """Per-attribute columns of one COM collection, probe-verified."""

    def __init__(self, coll, prof, label):
        self.coll = coll
        self.prof = prof
        self.label = label
        self.keep = None           # optional row-id subset retained after validation
        self.cols = {}
        self.missing = {}
        self.ids = None            # frozenset of row ids (from first strict column)
        self.probe_rid = None
        self.probe_obj = None
        self.probe_factory = None
        self.fault = None
        self.frozen = False

    # -- probe ---------------------------------------------------------------
    def set_probe(self, rid, obj):
        self.probe_rid, self.probe_obj = rid, obj
        if self.keep is not None and rid is not None:
            self.keep.add(rid)

    def retain(self, rids):
        """Keep only these rows of later columns (memory bound for big networks)."""
        self.keep = set(rids)
        if self.probe_rid is not None:
            self.keep.add(self.probe_rid)

    def _probe(self):
        if self.probe_obj is None and self.probe_factory is not None:
            factory, self.probe_factory = self.probe_factory, None
            rid, obj = factory()
            self.set_probe(rid, obj)
        return self.probe_rid, self.probe_obj

    def _verify(self, name):
        rid, obj = self._probe()
        if obj is None:
            raise _capability('DIAGFAST_V2_NO_PROBE_OBJECT:%s:%s' % (self.label, name))
        self.prof.count('v2_probe_scalar_reads')
        try:
            scalar = obj.AttValue(name)
            scalar_ok = True
        except Exception as exc:
            scalar, scalar_ok = exc, False
        if name in self.cols:
            if not scalar_ok:
                raise _capability('DIAGFAST_V2_BULK_OK_SCALAR_FAILS:%s:%s' % (self.label, name))
            if rid not in self.cols[name]:
                raise _capability('DIAGFAST_V2_PROBE_ROW_ABSENT:%s:%s' % (self.label, name))
            if not same_value(self.cols[name][rid], scalar):
                raise _capability('DIAGFAST_V2_BULK_SCALAR_MISMATCH:%s:%s:%r!=%r' % (
                    self.label, name, self.cols[name][rid], scalar))
        elif scalar_ok:
            raise _capability('DIAGFAST_V2_BULK_FAILS_SCALAR_OK:%s:%s' % (self.label, name))

    # -- columns -------------------------------------------------------------
    def _load(self, name, strict, on_full=None):
        self.prof.count('v2_bulk_calls')
        try:
            raw = df._bulk_values(self.coll, name)
        except df.CapabilityUnavailable:
            if strict:
                raise
            self.missing[name] = 'CAPABILITY'
            return None
        except df.DiagFastError:
            raise
        except Exception as exc:
            if strict:
                raise
            self.missing[name] = repr(exc)
            return None
        col = {}
        for rid, value in raw:
            if rid in col:
                raise df.DiagFastError('DIAGFAST_BULK_DUPLICATE_ROW:%s:%s:%s' % (self.label, name, rid))
            col[rid] = value
        if self.ids is None:
            self.ids = frozenset(col)
        elif set(col) != self.ids:
            raise df.DiagFastError('DIAGFAST_BULK_COLUMN_COVERAGE_MISMATCH:%s:%s' % (self.label, name))
        self.prof.count('v2_bulk_values', len(col))
        if on_full is not None:
            on_full(col)
        if self.keep is not None:
            col = {rid: col[rid] for rid in self.keep if rid in col}
        return col

    def strict_column(self, name, verify=True, on_full=None):
        """Mandatory column; any failure propagates (capability -> fallback)."""
        if name not in self.cols:
            col = self._load(name, strict=True, on_full=on_full)
            self.cols[name] = col
            if verify and self.probe_obj is not None:
                self._verify(name)
        return self.cols[name]

    def column(self, name):
        """Lazily loaded, probe-verified column; raises BulkUnavailable if absent."""
        if name in self.cols:
            return self.cols[name]
        if self.fault is not None:
            if self.frozen:                  # never let a helper swallow it
                raise BulkLateFault(repr(self.fault))
            raise BulkUnavailable('FAULTED:%s:%s' % (self.label, name))
        if name in self.missing:
            raise BulkUnavailable('%s:%s' % (self.label, name))
        try:
            col = self._load(name, strict=False)
            if col is not None:
                self.cols[name] = col
            self._verify(name)
        except BaseException as exc:
            self.cols.pop(name, None)
            self.missing[name] = 'FAULT'
            self.fault = exc
            if self.frozen:
                raise BulkLateFault(repr(exc)) from exc
            raise BulkUnavailable('FAULT:%s:%s' % (self.label, name)) from exc
        if col is None:
            raise BulkUnavailable('%s:%s' % (self.label, name))
        return col

    def preload(self, groups):
        """Resolve name groups like att(): first existing name wins."""
        for group in groups:
            for name in ([group] if isinstance(group, str) else group):
                try:
                    self.column(name)
                    break
                except BulkUnavailable:
                    if self.fault is not None:
                        raise self.fault
                    continue

    def raise_fault(self):
        if self.fault is not None:
            raise self.fault


class BulkRow:
    """Read-only row view. AttValue from columns, rest from the real object."""
    __slots__ = ('_bulk', '_rid', '_real')

    def __init__(self, bulk, rid, real=None):
        self._bulk, self._rid, self._real = bulk, rid, real

    def AttValue(self, name):
        col = self._bulk.column(name)
        try:
            return col[self._rid]
        except KeyError:                     # a programming error, never a default value
            raise BulkLateFault('DIAGFAST_V2_ROW_NOT_RETAINED:%s:%s:%s' % (
                self._bulk.label, name, self._rid))

    def __getattr__(self, name):
        real = self._real() if callable(self._real) else self._real
        if real is None:
            raise AttributeError(name)
        return getattr(real, name)

    def __repr__(self):
        return '<BulkRow %s #%s>' % (self._bulk.label, self._rid)


class _RawValue:
    def __init__(self, value):
        self.value = value

    def AttValue(self, name):
        return self.value


def _fallback(prof, component, exc):
    original = getattr(exc, 'original', exc)
    prof.fallbacks.append({'from': 'V2_' + component, 'to': 'V1_OR_REFERENCE',
                           'reason': repr(original),
                           'hresult': df.com.com_error_hresult(original)})
    prof.count('v2_fallbacks')


# ---------------------------------------------------------------------------
# 12D
# ---------------------------------------------------------------------------

_12D_CL_GROUPS = (
    ['NO', 'No'], ['R1_ACTIVE', 'R1 Active'], 'CODE', 'R1_OBS_ID', 'R1_ROLE',
    'R1_OBS_BASIS', 'R1_OBS_SCOPE', 'LINKNO', 'FROMNODENO', 'TONODENO',
    'R1_OBS_RPDI', 'R1_WEIGHT', ['LINKNO', 'LinkNo'], ['FROMNODENO', 'FromNodeNo'],
    ['TONODENO', 'ToNodeNo'], ['CODE', 'Code'], ['NAME', 'Name'],
    ['RELPOS', 'RelPos'], ['TSYSSET', 'TSysSet'],
)


def link_index_v2(v, probes, env, reference_index, v1_index, manifest, prof):
    """Bulk replacement of read_link_index for approved links + first sample."""
    start_len = len(probes)
    try:
        wanted = df.requested_keys(manifest)
        links = v.Net.Links
        bulk = BulkCollection(links, prof, '12D.Links')
        cols = [bulk.strict_column(a, verify=False) for a in ('NO', 'FROMNODENO', 'TONODENO')]
        count = df._capability_call(lambda: links.Count)
        rids = sorted(cols[0])
        if len(rids) != int(count):
            raise df.DiagFastError('DIAGFAST_BULK_IDENTITY_COVERAGE_MISMATCH')
        key_by_rid = {rid: tuple(df.exact_id(c[rid]) for c in cols) for rid in rids}
        rid_by_key = {}
        endpoints = {}
        for rid in rids:
            key = key_by_rid[rid]
            if key in rid_by_key:
                raise df.DiagFastError('DIAGFAST_DUPLICATE_DIRECTED_KEY:' + str(key))
            rid_by_key[key] = rid
            endpoints.setdefault(key[1:], []).append(key)
        for key in wanted:
            if key not in rid_by_key:
                raise df.DiagFastError('APPROVED physical directed link unavailable:' + str(key))
            if len(endpoints[key[1:]]) != 1:
                raise df.DiagFastError('DIAGFAST_AMBIGUOUS_PARALLEL_LINK:' + str(key))
        probe_key = wanted[0]
        real = df._capability_call(lambda: links.ItemByKey(probe_key[1], probe_key[2]))
        if df._identity(real, env) != probe_key:
            raise df.DiagFastError('DIAGFAST_ITEMBYKEY_IDENTITY_MISMATCH:' + str(probe_key))
        bulk.set_probe(rid_by_key[probe_key], real)
        for name in ('NO', 'FROMNODENO', 'TONODENO'):
            bulk._verify(name)
        sample_rid = rids[0]
        sample_key = key_by_rid[sample_rid]
        bulk.retain([sample_rid] + [rid_by_key[k] for k in wanted])

        def validate_all(attr):
            def check(full):
                for rid in rids:
                    env['required_model_volume'](_RawValue(full[rid]), attr)
                prof.count('validated_network_passenger_values', len(full))
            return check
        with prof.span('DIAG_12D_REQUIRED_VOLUME_SWEEP'):
            for ds in env['PASSENGER_DSEGS']:
                attr = 'VOLVEH_DSEG(%s,AP)' % ds
                bulk.strict_column(attr, on_full=validate_all(attr))
        selected = [BulkRow(bulk, sample_rid)]
        selected.extend(BulkRow(bulk, rid_by_key[k]) for k in wanted if k != sample_key)
        prof.notes['network_links'] = len(rids)
        prof.notes['requested_unique_links'] = len(wanted)
        prof.notes['full_link_rows_read'] = len(selected)
        restricted = SimpleNamespace(Net=SimpleNamespace(
            Links=SimpleNamespace(GetAll=tuple(selected)), LinkTypes=v.Net.LinkTypes))
        result = reference_index(restricted, probes)
        bulk.raise_fault()
        prof.notes['identity_backend'] = 'V2_BULK_COLUMNS_PROBE_VERIFIED'
        prof.notes['v2_link_columns'] = sorted(bulk.cols)
        prof.notes['v2_link_missing_columns'] = sorted(bulk.missing)
        return result
    except df.CapabilityUnavailable as failure:
        del probes[start_len:]
        _fallback(prof, '12D_LINKS', failure)
        return v1_index(v, probes)


def countlocations_12d_v2(v, env, reference, prof):
    try:
        coll = v.Net.CountLocations
        bulk = BulkCollection(coll, prof, '12D.CountLocations')
        nos = bulk.strict_column('NO', verify=False)
        count = df._capability_call(lambda: coll.Count)
        rids = sorted(nos)
        if len(rids) != int(count):
            raise df.DiagFastError('DIAGFAST_BULK_COUNTLOCATION_COVERAGE_MISMATCH')
        probe_rid = rids[0]
        probe_no = df.exact_id(nos[probe_rid])
        real = df._capability_call(lambda: coll.ItemByKey(probe_no))
        bulk.set_probe(probe_rid, real)
        bulk._verify('NO')
        bulk.preload(_12D_CL_GROUPS)
        bulk.frozen = True
        rows = tuple(BulkRow(bulk, rid) for rid in rids)
        facade = SimpleNamespace(Net=SimpleNamespace(CountLocations=SimpleNamespace(GetAll=rows)))
        result = reference(facade)
        prof.notes['v2_countlocation_columns'] = sorted(bulk.cols)
        return result
    except df.CapabilityUnavailable as failure:
        _fallback(prof, '12D_COUNTLOCATIONS', failure)
        return reference(v)


def install_12d(env, prof, opts):
    saved = {}
    current_manifest = env['load_manifest']

    def manifest():
        result = current_manifest()
        saved['manifest'] = result
        return result
    env['load_manifest'] = manifest

    if opts['bulk_12d_links']:
        reference_index = env['_diagfast_reference_read_link_index']
        v1_index = env['read_link_index']

        def index(v, probes):
            authority = saved.get('manifest')
            if authority is None:
                authority = env['load_manifest']()
            return link_index_v2(v, probes, env, reference_index, v1_index, authority, prof)
        env['read_link_index'] = index
        df._timed(env, 'read_link_index', prof, 'DIAG_12D_LINK_INDEX_V2')

    if opts['bulk_12d_countlocations']:
        reference_cl = env['read_countlocations']

        def read_countlocations(v):
            return countlocations_12d_v2(v, env, reference_cl, prof)
        env['read_countlocations'] = read_countlocations
        df._timed(env, 'read_countlocations', prof, 'DIAG_12D_COUNTLOCATIONS_V2')


# ---------------------------------------------------------------------------
# 11D
# ---------------------------------------------------------------------------

class _LinkKeyFacade:
    """Links.ItemByKey(from, to) served from bulk FROMNODENO/TONODENO columns."""

    def __init__(self, links, prof):
        self.links = links
        self.bulk = BulkCollection(links, prof, '11D.Links')
        fr = self.bulk.strict_column('FROMNODENO', verify=False)
        to = self.bulk.strict_column('TONODENO', verify=False)
        self.by_key = {}
        for rid in sorted(fr):
            key = (df.exact_id(fr[rid]), df.exact_id(to[rid]))
            if key in self.by_key:
                raise _capability('DIAGFAST_V2_PARALLEL_FROM_TO:' + str(key))
            self.by_key[key] = rid
        self.bulk.probe_factory = self._make_probe
        self.first_key = None

    def _make_probe(self):
        key = self.first_key or next(iter(self.by_key))
        real = df._capability_call(lambda: self.links.ItemByKey(key[0], key[1]))
        got = (df.exact_id(real.AttValue('FROMNODENO')), df.exact_id(real.AttValue('TONODENO')))
        if got != key:
            raise df.DiagFastError('DIAGFAST_ITEMBYKEY_IDENTITY_MISMATCH:' + str(key))
        return self.by_key[key], real

    def ItemByKey(self, fr, to):
        key = (int(fr), int(to))
        rid = self.by_key.get(key)
        if rid is None:
            raise KeyError(key)              # reference: COM error -> get_link None
        if self.bulk.keep is not None and rid not in self.bulk.keep:
            self.bulk.prof.count('v2_link_rows_outside_retained_scalar')
            return self.links.ItemByKey(fr, to)   # exact scalar object
        if self.first_key is None:
            self.first_key = key
        return BulkRow(self.bulk, rid)

    def retain_pairs(self, pairs):
        rids = [self.by_key[k] for k in pairs if k in self.by_key]
        self.bulk.retain(rids)


def countlocation_rows_v2(visum, env, reference, prof):
    try:
        coll = visum.Net.CountLocations
        bulk = BulkCollection(coll, prof, '11D.CountLocations')
        nos = bulk.strict_column('NO', verify=False)
        rids = sorted(nos)
        real_all = env['get_all'](coll)
        if len(real_all) != len(rids):
            raise _capability('DIAGFAST_V2_COUNTLOCATION_GETALL_LENGTH')
        if rids:
            for pos in sorted({0, len(rids) // 2, len(rids) - 1}):
                prof.count('v2_order_scalar_reads')
                if not same_value(real_all[pos].AttValue('NO'), nos[rids[pos]]):
                    raise _capability('DIAGFAST_V2_COUNTLOCATION_ORDER_MISMATCH:%d' % pos)
            bulk.set_probe(rids[0], real_all[0])
            bulk._verify('NO')
        links = _LinkKeyFacade(visum.Net.Links, prof)
        try:
            cl_fr, cl_to = bulk.column('FROMNODENO'), bulk.column('TONODENO')
            pairs = set()
            for rid in rids:
                a, b = cl_fr.get(rid), cl_to.get(rid)
                if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
                        and math.isfinite(a) and math.isfinite(b):
                    pairs.add((int(round(a)), int(round(b))))
                    pairs.add((int(round(b)), int(round(a))))
            links.retain_pairs(pairs)
        except BulkUnavailable:
            bulk.raise_fault()               # a probe fault aborts V2 here
        rows = tuple(BulkRow(bulk, rid, real_all[i]) for i, rid in enumerate(rids))
        facade = SimpleNamespace(Net=SimpleNamespace(
            CountLocations=SimpleNamespace(GetAll=rows), Links=links))
        result = reference(facade)
        bulk.raise_fault()
        links.bulk.raise_fault()
        prof.notes['v2_11d_countlocation_columns'] = sorted(bulk.cols)
        prof.notes['v2_11d_link_columns'] = sorted(links.bulk.cols)
        return result
    except df.CapabilityUnavailable as failure:
        _fallback(prof, '11D_COUNTLOCATIONS', failure)
        return reference(visum)


_MATRIX_PRELOAD = ('NO', 'CODE', 'NAME', 'MATRIXTYPE', 'OBJECTTYPEREF', 'NUMROWS', 'NUMCOLS')


class _HybridMatrix:
    """Matrix view: catalog attributes from bulk columns, values from the real object."""
    __slots__ = ('_cat', '_rid', '_no')

    def __init__(self, cat, rid, no):
        self._cat, self._rid, self._no = cat, rid, no

    def AttValue(self, name):
        if name in self._cat.bulk.cols or name in self._cat.bulk.missing:
            return self._cat.bulk.column(name)[self._rid]
        return self._cat.real(self._no).AttValue(name)

    def __getattr__(self, name):
        return getattr(self._cat.real(self._no), name)

    def __repr__(self):
        return '<HybridMatrix NO=%s>' % self._no


class _MatrixCatalog:
    def __init__(self, visum, prof):
        self.mats = visum.Net.Matrices
        self.prof = prof
        self.bulk = BulkCollection(self.mats, prof, '11D.Matrices')
        nos = self.bulk.strict_column('NO', verify=False)
        self.rids = sorted(nos)
        if not self.rids:
            raise _capability('DIAGFAST_V2_EMPTY_MATRIX_COLLECTION')
        self.no_by_rid = {}
        self.rid_by_no = {}
        for rid in self.rids:
            no = df.exact_id(nos[rid])
            if no in self.rid_by_no:
                raise _capability('DIAGFAST_V2_DUPLICATE_MATRIX_NO:%d' % no)
            self.no_by_rid[rid] = no
            self.rid_by_no[no] = rid
        self._real = {}
        first = self.no_by_rid[self.rids[0]]
        self.bulk.set_probe(self.rids[0], self.real(first))
        self.bulk._verify('NO')
        self.bulk.preload(_MATRIX_PRELOAD)
        self.bulk.frozen = True

    def real(self, no):
        obj = self._real.get(no)
        if obj is None:
            self.prof.count('v2_matrix_itembykey')
            obj = df._capability_call(lambda: self.mats.ItemByKey(int(no)))
            self._real[no] = obj
        return obj

    def by_no(self, no):
        rid = self.rid_by_no.get(no)
        return None if rid is None else _HybridMatrix(self, rid, no)

    def code_matches(self, target):
        """Row ids with matching CODE in container order; None = use reference scan."""
        try:
            codes = self.bulk.column('CODE')
        except BulkUnavailable:
            return None
        out = []
        for rid in self.rids:
            value = codes[rid]
            text = self._sval('' if value is None else value)
            if text.strip().upper() == target:
                out.append(rid)
        return out

    @staticmethod
    def _sval(v):
        try:
            return '' if v is None else str(v)
        except Exception:
            return repr(v)


def install_11d(env, prof, opts):
    if opts['bulk_11d_countlocations']:
        reference_rows = env['countlocation_rows']

        def countlocation_rows(visum):
            return countlocation_rows_v2(visum, env, reference_rows, prof)
        env['countlocation_rows'] = countlocation_rows
        df._timed(env, 'countlocation_rows', prof, 'DIAG_11D_COUNTLOCATIONS_V2')

    if opts['bulk_11d_matrices']:
        catalogs = {}
        reference_by_no = env['matrix_by_no']
        reference_by_code = env['find_matrix_by_code']

        def catalog(visum):
            key = id(visum)
            entry = catalogs.get(key)
            if entry is None or entry[0] is not visum:
                try:
                    cat = _MatrixCatalog(visum, prof)
                except df.CapabilityUnavailable as failure:
                    _fallback(prof, '11D_MATRICES', failure)
                    cat = None
                entry = (visum, cat)
                catalogs[key] = entry
            return entry[1]

        def matrix_by_no(visum, no):
            cat = catalog(visum)
            if cat is None:
                return reference_by_no(visum, no)
            try:
                key = int(no)
            except Exception:
                return reference_by_no(visum, no)
            found = cat.by_no(key)
            return found if found is not None else reference_by_no(visum, no)

        def find_matrix_by_code(visum, code):
            cat = catalog(visum)
            if cat is None:
                return reference_by_code(visum, code)
            matches = cat.code_matches(code.strip().upper())
            if matches is None:
                return reference_by_code(visum, code)
            if not matches:
                return None
            if len(matches) > 1:          # first-in-GetAll semantics: keep reference
                prof.count('v2_duplicate_matrix_code_reference')
                return reference_by_code(visum, code)
            rid = matches[0]
            return _HybridMatrix(cat, rid, cat.no_by_rid[rid])

        env['matrix_by_no'] = matrix_by_no
        env['find_matrix_by_code'] = find_matrix_by_code
        env['_diagfast_v2_matrix_catalogs'] = catalogs

    if opts['numpy_11d']:
        fastnp.install(env, prof)

    if opts['interp_11d_xs_cache']:
        install_interp_cache(env, prof)

    if opts['memo_11d_curves']:
        reference_stats = env['curve_stats']
        memo = {}

        def curve_stats(points, bins):
            key = (id(points), id(bins))
            hit = memo.get(key)
            if hit is not None and hit[0] is points and hit[1] is bins and hit[2] == len(points):
                prof.count('v2_curve_stats_memo_hits')
                return list(hit[3]), hit[4]
            shares, mean = reference_stats(points, bins)
            memo[key] = (points, bins, len(points), tuple(shares), mean)
            return list(shares), mean
        env['curve_stats'] = curve_stats
        env['_diagfast_v2_curve_memo'] = memo


def install_interp_cache(env, prof):
    """interp() of 11D v1.3 with the x-grid list built once per curve.

    The reference rebuilds ``xs = [p[0] for p in points]`` on every call
    (O(n) per point, O(n^2) per integral). The body below is the reference
    statement for statement; only ``xs`` comes from a per-invocation cache
    keyed by the identity of the immutable points list.
    """
    bisect_left = env['bisect_left']
    cache = {}

    def xs_for(points):
        hit = cache.get(id(points))
        if hit is not None and hit[0] is points and len(hit[1]) == len(points) \
                and hit[1][0] == points[0][0] and hit[1][-1] == points[-1][0]:
            return hit[1]
        xs = [p[0] for p in points]
        cache[id(points)] = (points, xs)
        return xs

    def interp(points, x):
        if not points:
            return 0.0
        if x < points[0][0] or x > points[-1][0]:
            return 0.0
        if x == points[0][0]:
            return points[0][1]
        xs = xs_for(points)
        pos = bisect_left(xs, x)
        if pos < len(points) and points[pos][0] == x:
            return points[pos][1]
        if pos <= 0 or pos >= len(points):
            return 0.0
        x0, y0 = points[pos - 1]
        x1, y1 = points[pos]
        if x1 == x0:
            return y0
        t = (x - x0) / (x1 - x0)
        return y0 + t * (y1 - y0)

    env['_reference_interp'] = env['interp']
    env['interp'] = interp
    env['_diagfast_v2_interp_cache'] = cache


def install(env, kind, prof):
    """Called from configure_namespace(FAST_EXACT) after the V1 overlay."""
    opts = options()
    prof.notes['v2_release'] = RELEASE_V2
    prof.notes['v2_features'] = dict(opts)
    if kind == '12D':
        install_12d(env, prof, opts)
    else:
        install_11d(env, prof, opts)
    return opts


def release(env):
    """Drop per-invocation caches (called from run_reference_helper finally)."""
    fastnp.clear_cache()
    for name in ('_diagfast_v2_matrix_catalogs', '_diagfast_v2_curve_memo',
                 '_diagfast_v2_interp_cache'):
        value = env.get(name)
        if hasattr(value, 'clear'):
            value.clear()
