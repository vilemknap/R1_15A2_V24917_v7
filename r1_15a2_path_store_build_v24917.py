"""Exact build acceleration for the sealed V238 SQLite saved-path store.

Patch methods on the existing class, so previously imported adapter aliases and
read-only reopen remain compatible. No schema, COM page size, durability, path
authority, geometry sampling or completion/parity gate is changed.
"""
from __future__ import annotations

from array import array
from collections import Counter, defaultdict
from functools import wraps
import hashlib
import json
import math
import struct
import time
import zlib

import r1_15a2_two_mode_v238 as base

RELEASE = "R1_15A2_PATH_STORE_BUILD1_20261030"
Error = base.SupplyContractError


def _stats(store):
    return store.summary.setdefault("path_store_build", {
        "release": RELEASE, "keymap_sql_reads": 0, "keymap_cache_hits": 0,
        "parent_calls": 0, "parent_seconds": 0.0,
        "geometry_calls": 0, "geometry_seconds": 0.0,
        "geometry_sql_seconds": 0.0, "geometry_flushes": 0,
        "max_cached_modes": 1, "journal_mode": "DELETE", "synchronous": "FULL",
        "timing_semantics": "PHASES_INCLUDE_COM_ITERATION;SQL_FLUSH_INCLUDES_PACKING_COMPRESSION_COMMIT",
    })


def _key_map(store, mode):
    # One mode only, only in this collector/build. Detect both local out-of-band
    # SQL and commits on another connection before reusing a map. No hash-only
    # key comparison and no cross-run cache authorization is introduced.
    version = store.db.execute("PRAGMA data_version").fetchone()[0]
    cached = getattr(store, "_path_build_keymap", None)
    token = (mode, store.db.total_changes, version)
    if cached is not None and cached[:3] == token and not store.db.in_transaction:
        _stats(store)["keymap_cache_hits"] += 1
        return cached[3]
    store._path_build_keymap = None
    cached = None
    result = {(o, d, ix): gid for gid, o, d, ix in store.db.execute(
        "SELECT gid,orig,dest,path_index FROM geometry WHERE mode=?", (mode,))}
    _stats(store)["keymap_sql_reads"] += 1
    return result


def _timed_build(phase, release_map=False):
    def decorate(fn):
        @wraps(fn)
        def run(self, *args, **kwargs):
            started = time.perf_counter()
            stats = _stats(self)
            stats[phase + "_calls"] += 1
            try:
                return fn(self, *args, **kwargs)
            except BaseException:
                self._path_build_keymap = None
                if self.db.in_transaction:
                    self.db.rollback()
                raise
            finally:
                stats[phase + "_seconds"] += time.perf_counter() - started
                if release_map:
                    self._path_build_keymap = None
        run.__r1_path_store_build__ = RELEASE
        return run
    return decorate


@_timed_build("parent")
def add_parents(self, code, mode, rows, matrix_authority):
    """Exact key join; one sort and ordered primary-key inserts per DSeg."""
    code = base.core.norm_code(code)
    if code in self.parents or mode not in ('C', 'C_NOT'):
        raise Error('DUPLICATE_DSEG_OR_UNKNOWN_MODE')
    values = {}
    max_rows = int(self.settings['max_parent_rows_per_dseg'])
    for raw in rows:
        if len(raw) != 4:
            raise Error('PARENT_ROW_SCHEMA_MISMATCH')
        key = (base._id(raw[0]), base._id(raw[1]), base._id(raw[2]))
        if key in values:
            raise Error('DUPLICATE_PARENT_KEY:' + code)
        vol = base.com.finite_float(raw[3], 'Vol(AP)')
        if vol < 0:
            raise Error('NEGATIVE_PATH_VOLUME')
        if len(values) >= max_rows:
            raise Error('PARENT_ROW_BUDGET_EXCEEDED')
        values[key] = vol
    sorted_keys = sorted(values)
    mode_is_new = mode not in self.mode_audits
    if mode_is_new:
        self._path_build_keymap = None
        self.db.executemany('INSERT INTO geometry(mode,orig,dest,path_index) VALUES(?,?,?,?)',
                            ((mode, *key) for key in sorted_keys))
    key_map = _key_map(self, mode)
    if not mode_is_new and (len(key_map) != len(values) or any(k not in key_map for k in values)):
        missing = sorted(set(key_map) - set(values))[:8]
        extra = sorted(set(values) - set(key_map))[:8]
        raise Error('FULL_PARENT_KEYS_DIFFER: %s missing=%r extra=%r' % (code, missing, extra))
    # Hash bytes and ordering remain identical to the original implementation.
    key_digest = hashlib.sha256()
    vol_hash = hashlib.sha256()
    comparison_hash = hashlib.sha256()
    decimals = int(self.settings['path_epoch_volume_comparison_decimals'])
    for key in sorted_keys:
        if mode_is_new:
            key_digest.update(struct.pack('<III', *key))
        vol_hash.update(struct.pack('<IIId', *key, values[key]))
        comparison_hash.update(struct.pack('<IIId', *key, round(values[key], decimals)))
    key_hash = (key_digest.hexdigest() if mode_is_new else
                self.mode_audits[mode]['parent_keys_sha256'])
    if mode_is_new:
        self.mode_audits[mode] = {'representative_dseg': code, 'parent_keys_sha256': key_hash,
                                'parent_count': len(values), 'dsegs': []}
    total = math.fsum(values.values())
    intra = math.fsum(v for (o, d, _), v in values.items() if o == d)
    inter = math.fsum(v for (o, d, _), v in values.items() if o != d)
    ref = float(matrix_authority['matrix_interzonal'])
    rel = abs(inter - ref) / max(1.0, abs(ref))
    tolerance = float(self.settings.get('dseg_path_volume_relative_tolerance', 0.01))
    passes = abs(inter) <= 1e-9 if ref <= 1e-9 else rel <= tolerance
    audit = {'dseg_code': code, 'mode': mode, 'path_rows': len(values),
             'positive_volume_rows': sum(v > 0 for v in values.values()),
             'zero_volume_rows': sum(v == 0 for v in values.values()),
             'intrazonal_parent_rows': sum(o == d for o, d, _ in values),
             'parent_keys_sha256': key_hash, 'keys_and_volumes_sha256': vol_hash.hexdigest(),
             'keys_and_volumes_comparison_sha256': comparison_hash.hexdigest(),
             'path_epoch_volume_comparison_decimals': decimals,
             'saved_path_volume_sum': total, 'saved_path_interzonal_volume_sum': inter,
             'saved_path_intrazonal_volume_sum': intra,
             'relative_abs_diff': rel, 'passes': passes, 'tolerance': tolerance,
             'parity_basis': 'SAME_RUN_INTERZONAL_MATRIX_VS_INTERZONAL_SAVED_PATHS',
             **matrix_authority}
    self.db.execute('INSERT INTO segments VALUES(?,?,?)', (code, mode, json.dumps(audit)))
    self.db.executemany('INSERT INTO volumes VALUES(?,?,?)',
                        ((key_map[key], code, values[key]) for key in sorted_keys))
    self.db.commit()
    version = self.db.execute('PRAGMA data_version').fetchone()[0]
    self._path_build_keymap = (mode, self.db.total_changes, version, key_map)
    self.parents[code] = audit
    self.parity_rows.append(audit)
    self.mode_audits[mode]['dsegs'].append(code)
    self.summary['dsegs'].append(code)
    self.control.checkpoint('PARENTS_DSEG_COMPLETE', force=True, dseg_code=code,
                           parent_rows=len(values), positive_volume_rows=audit['positive_volume_rows'],
                           offdiagonal_relative_difference=rel)
    self.check_resources(force=True)
    if not passes:
        raise Error('SAME_RUN_OFFDIAGONAL_PARITY_FAILED:' + code)
    return audit


@_timed_build("geometry", release_map=True)
def add_geometry(self, mode, raw_rows):
    """Stream official hierarchy/flat rows; avoid per-child slice/generator churn."""
    if mode not in self.mode_audits or self.mode_audits[mode].get('geometry_complete'):
        raise Error('INVALID_OR_DUPLICATE_GEOMETRY_MODE')
    key_map = _key_map(self, mode)
    self._path_build_keymap = None
    seen = set()
    parent = None
    seq_ids = []
    updates, hits_batch = [], []
    market_batch = set()
    postings = defaultdict(lambda: array('I'))
    raw_count = child_count = 0
    last_end = None
    mode_max_mult = Counter()
    zero_link_interzonal = zero_link_intrazonal = 0
    to_id = base._id
    edge_ids = self.edge_ids
    edge_profiles = {edge_ids[k]: indices for k, indices in self.profile_index_by_key.items()
                     if k in edge_ids}
    commit_routes = int(self.settings['commit_routes'])
    max_rows = int(self.settings['max_geometry_rows_per_mode'])
    max_links = int(self.settings['max_links_per_path'])
    stats = _stats(self)

    def flush():
        if not updates:
            return
        self.control.checkpoint('GEOMETRY_STORE_COMMIT', mode=mode,
                                geometry_routes=len(seen), raw_rows=raw_count, link_children=child_count)
        started = time.perf_counter()
        self.db.executemany('UPDATE geometry SET edge_ids=?,edge_count=?,sequence_sha256=?,geometry_kind=? WHERE gid=?', updates)
        self.db.executemany('INSERT INTO profile_hits VALUES(?,?,?)', hits_batch)
        self.db.executemany('INSERT OR IGNORE INTO driver_markets VALUES(?,?,?)', market_batch)
        self._posting_chunk += 1
        self.db.executemany('INSERT INTO edge_postings VALUES(?,?,?)',
                            ((eid, self._posting_chunk, zlib.compress(base._packed(ids), 1))
                             for eid, ids in postings.items()))
        self.db.commit()
        stats['geometry_sql_seconds'] += time.perf_counter() - started
        stats['geometry_flushes'] += 1
        updates.clear(); hits_batch.clear(); market_batch.clear(); postings.clear()
        self.check_resources()

    def finish_route():
        nonlocal zero_link_interzonal, zero_link_intrazonal
        if parent is None:
            return
        if parent not in key_map or parent in seen:
            raise Error('ORPHAN_OR_REPEATED_GEOMETRY_PARENT:%r' % (parent,))
        gid = key_map[parent]
        kind = 'LINK_SEQUENCE'
        if not seq_ids:
            if parent[0] != parent[1]:
                zero_link_interzonal += 1
                kind = 'ZERO_LINK_INTERZONAL_NO_ADDVAL1_EFFECT'
            else:
                zero_link_intrazonal += 1
                kind = 'ZERO_LINK_INTRAZONAL_NO_ADDVAL1_EFFECT'
        seen.add(parent)
        blob = base._packed(seq_ids)
        updates.append((blob, len(seq_ids), hashlib.sha256(blob).hexdigest(), kind, gid))
        hit = Counter()
        for eid, n in Counter(seq_ids).items():
            postings[eid].extend((gid, n))
            if n > mode_max_mult[eid]:
                mode_max_mult[eid] = n
            for i in edge_profiles.get(eid, ()):
                hit[i] += n
        hits_batch.extend((gid, i, n) for i, n in hit.items())
        if any(i in hit for i in self.cal_indices):
            market_batch.add((mode, parent[0], parent[1]))
        if len(updates) >= commit_routes:
            flush()

    for raw in raw_rows:
        raw_count += 1
        if raw_count > max_rows:
            raise Error('GEOMETRY_ROW_BUDGET_EXCEEDED')
        if len(raw) != 7:
            raise Error('GEOMETRY_ROW_SCHEMA_MISMATCH')
        o, d, ix, index, link, start, end = raw
        po = o is not None and o != ''
        pd = d is not None and d != ''
        pi = ix is not None and ix != ''
        li = index is not None and index != ''
        ll = link is not None and link != ''
        ls = start is not None and start != ''
        le = end is not None and end != ''
        if not (li or ll or ls or le):
            if not (po and pd and pi):
                raise Error('INCOMPLETE_GEOMETRY_PARENT')
            next_parent = (to_id(o), to_id(d), to_id(ix))
            finish_route()
            parent = next_parent; seq_ids = []; last_end = None
            if parent not in key_map or parent in seen:
                raise Error('UNKNOWN_OR_REOPENED_GEOMETRY_PARENT')
            continue
        if not (li and ll and ls and le):
            raise Error('INCOMPLETE_GEOMETRY_CHILD')
        if po and pd and pi:
            key = (to_id(o), to_id(d), to_id(ix))
            if key != parent:
                finish_route()
                parent = key; seq_ids = []; last_end = None
                if parent not in key_map or parent in seen:
                    raise Error('UNKNOWN_OR_REOPENED_FLAT_PARENT')
        elif po or pd or pi:
            if (parent is None or (po and to_id(o) != parent[0]) or
                    (pd and to_id(d) != parent[1]) or (pi and to_id(ix) != parent[2])):
                raise Error('CONFLICTING_PARTIAL_GEOMETRY_PARENT')
        if parent is None:
            raise Error('ORPHAN_GEOMETRY_CHILD')
        index = to_id(index)
        key = (to_id(link), to_id(start), to_id(end))
        if index != len(seq_ids) + 1:
            raise Error('GEOMETRY_LINK_INDEX_NOT_CONTIGUOUS')
        if last_end is not None and last_end != key[1]:
            raise Error('DISCONNECTED_OFFICIAL_PATH_LINK_SEQUENCE')
        if key not in edge_ids:
            raise Error('PATH_EDGE_NOT_IN_LIVE_NETWORK:%r' % (key,))
        seq_ids.append(edge_ids[key]); last_end = key[2]; child_count += 1
        if len(seq_ids) > max_links:
            raise Error('SINGLE_ROUTE_LENGTH_BUDGET_EXCEEDED')
    finish_route(); flush()
    if len(seen) != len(key_map):  # Every seen key was checked against key_map.
        raise Error('GEOMETRY_PARENT_COVERAGE_INCOMPLETE')
    for eid, n in mode_max_mult.items():
        key = self.edge_keys[eid]
        self.edge_max_multiplicity[key] = max(self.edge_max_multiplicity[key], n)
    h = hashlib.sha256()
    for o, d, ix, digest in self.db.execute(
            'SELECT orig,dest,path_index,sequence_sha256 FROM geometry WHERE mode=? ORDER BY orig,dest,path_index', (mode,)):
        h.update(struct.pack('<III', o, d, ix)); h.update(digest.encode('ascii'))
    self.mode_audits[mode].update(geometry_complete=True, geometry_routes=len(seen),
        geometry_link_children=child_count, geometry_raw_rows=raw_count,
        zero_link_interzonal_paths=zero_link_interzonal, zero_link_intrazonal_paths=zero_link_intrazonal,
        representative_geometry_sha256=h.hexdigest(), geometry_reads=1)
    self.geometry_count += len(seen)
    self.control.checkpoint('MODE_GEOMETRY_COMPLETE', force=True, mode=mode,
                            geometry_routes=len(seen), link_children=child_count)
    return self.mode_audits[mode]


def install():
    """Idempotent method patch: aliases to the original class remain effective."""
    cls = base.TwoModeRouteCollector
    if getattr(cls.add_geometry, '__r1_path_store_build__', None) == RELEASE:
        return {'installed': True, 'already': True, 'release': RELEASE}
    original_close = cls.close

    @wraps(original_close)
    def close(self):
        try:
            return original_close(self)
        finally:
            self._path_build_keymap = None

    cls.add_parents = add_parents
    cls.add_geometry = add_geometry
    cls.close = close
    return {'installed': True, 'release': RELEASE, 'schema_changed': False,
            'com_page_size_changed': False, 'durability': 'DELETE/FULL'}
