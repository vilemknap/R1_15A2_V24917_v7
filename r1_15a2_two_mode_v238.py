"""Experimental two-mode saved-path store. READ-ONLY DESIGN ONLY.

One ordered geometry per (snapshot, mode, origin, destination, PathIndex).
One independent returned Vol(AP) per (geometry_id, DSeg), INCLUDING zero values.
Cross-run reuse is allowed only through the V2.4.8 hash-authorized persistent cache; no shortest paths; no OD, assignment or network writes.

Full parent-key identity and same-run bounded geometry fingerprints are gates,
not proof of identical unobserved geometry across DSegs. Every consumer and
candidate is labelled provisional, and APPLY is rejected at the adapter boundary.
"""
from __future__ import annotations

from array import array
from collections import Counter, defaultdict
from datetime import datetime
from itertools import groupby
from pathlib import Path
import gc
import hashlib
import json
import math
import os
import shutil
import sqlite3
import struct
import sys
import time
import zlib

import numpy as np
import r1_15a2_com_compat as com
import r1_15a2_core as core
import r1_15a2_runtime_v1 as rt
from r1_15a2_sequence_v23 import ActualSequenceRouteCollector
from r1_15a2_supply import (ActualRouteCollector, SupplyContractError,
    canonical_hash, number, observation_identity)

SCHEMA = 'R1_15A2_TWO_MODE_PATH_STORE_V238'
PROVISIONAL = 'PROVISIONAL_SAME_MODE_GEOMETRY_NOT_FULLY_VERIFIED'
EXPECTED_MODE_DSEGS = {
    'C': frozenset(('NATIVE_CW','NATIVE_CS','NATIVE_CF','NATIVE_CL',
                    'EXOG_EE_CW','EXOG_EE_CS','EXOG_EE_CF','EXOG_EE_CL')),
    'C_NOT': frozenset(('NATIVE_CW_NOT','NATIVE_CS_NOT','EXOG_EE_CW_NOT','EXOG_EE_CS_NOT')),
}
PARENT_COLUMNS = ('OrigZoneNo', 'DestZoneNo', 'Index', 'Vol(AP)')
GEOMETRY_COLUMNS = ('OrigZoneNo', 'DestZoneNo', 'PathIndex', 'Index',
                    'LinkNo', 'FromNodeNo', 'ToNodeNo')
DEFAULT_SETTINGS = {
    'enabled': True,
    'design_only': True,
    'representatives': {'C': 'NATIVE_CW', 'C_NOT': 'NATIVE_CW_noT'},
    'page_size': 256,
    'page_size_fallbacks': [1024, 512, 256, 80],
    'max_runtime_seconds': 1800.0,
    'max_parent_rows_per_dseg': 1500000,
    'max_geometry_rows_per_mode': 100000000,
    'max_links_per_path': 100000,
    'commit_routes': 5000,
    'max_store_gib': 12.0,
    'min_free_disk_gib': 1.0,
    'sample_windows': [[1, 256], [8193, 8448], [65537, 65792]],
    'progress_interval_seconds': 2.0,
    'path_epoch_volume_comparison_decimals': 6,
}


def validated_settings(settings=None):
    result=dict(DEFAULT_SETTINGS,**(settings or {}))
    for name,lo,hi in (("page_size",1,4096),("max_parent_rows_per_dseg",1,10000000),
                      ("max_geometry_rows_per_mode",1,1000000000),("max_links_per_path",1,1000000),
                      ("commit_routes",1,100000),
                      ("path_epoch_volume_comparison_decimals",0,12)):
        v=com.exact_int(result[name],name)
        if not lo <= v <= hi:raise SupplyContractError("INVALID_TWO_MODE_SETTING:"+name)
        result[name]=v
    for name,lo,hi in (("max_runtime_seconds",1,86400),("max_store_gib",0.001,1024),
                      ("min_free_disk_gib",0,1024),("progress_interval_seconds",0,60)):
        v=com.finite_float(result[name],name)
        if not lo <= v <= hi:raise SupplyContractError("INVALID_TWO_MODE_SETTING:"+name)
        result[name]=v
    if result.get('design_only') is not True or result.get('enabled') is not True:
        raise SupplyContractError('EXPLICIT_ENABLED_DESIGN_ONLY_REQUIRED')
    if set(result['representatives'])!={'C','C_NOT'}:
        raise SupplyContractError('EXACT_TWO_MODE_REPRESENTATIVES_REQUIRED')
    fallbacks=[]
    for value in result.get('page_size_fallbacks', []):
        v=com.exact_int(value,'page_size_fallback')
        if not 1 <= v <= 4096:
            raise SupplyContractError('INVALID_TWO_MODE_SETTING:page_size_fallbacks')
        if v < result['page_size'] and v not in fallbacks:
            fallbacks.append(v)
    if 80 < result['page_size'] and 80 not in fallbacks:
        fallbacks.append(80)
    result['page_size_fallbacks']=fallbacks
    return result


class DesignStopRequested(RuntimeError):
    stop_design_run = True


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as h:
        json.dump(value, h, ensure_ascii=True, allow_nan=False, indent=2)
    os.replace(tmp, path)


class RunControl:
    """Cooperative stop/deadline, only on the host thread. No timer COM calls."""
    def __init__(self, root, settings=None, clock=time.monotonic):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = validated_settings(settings)
        self.clock = clock
        self.started = clock()
        self.last_write = -math.inf
        self.progress = {'schema': 'R1_15A2_TWO_MODE_PROGRESS_V1',
                         'apply': False, 'phase': 'STARTING', 'status':'RUNNING',
                         'geometry_identity': PROVISIONAL}
        self.stop_paths = (self.root / 'STOP_REQUESTED', self.root.parent / 'STOP_REQUESTED')
        self.checkpoint('STARTING', force=True)

    def checkpoint(self, phase=None, force=False, **details):
        if phase is not None:
            self.progress['phase'] = phase
        self.progress.update(details)
        now = self.clock()
        reason = None
        if any(p.exists() for p in self.stop_paths):
            reason = 'USER_STOP_REQUESTED'
        if now - self.started >= float(self.settings['max_runtime_seconds']):
            reason = reason or 'COOPERATIVE_TIME_BUDGET_EXCEEDED'
        if reason:
            self.progress.update(status='STOP_REQUESTED', stop_reason=reason)
            self._write(now)
            raise DesignStopRequested(reason)
        if force or now-self.last_write >= float(self.settings['progress_interval_seconds']):
            self._write(now)

    def _write(self, now):
        self.progress.update(elapsed_seconds=round(now-self.started, 3),
                             updated=datetime.now().astimezone().isoformat())
        atomic_json(self.root / '00_PROGRESS.json', self.progress)
        self.last_write = now

    def finish(self, status, **details):
        self.progress.update(status=status, phase='FINISHED', **details)
        self._write(self.clock())


class QuietControl:
    """Test/offline control, never selected by the live entrypoint."""
    def checkpoint(self, *args, **kwargs):
        pass


def _id(value):
    if type(value) is int:
        result = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        result = int(value)
    else:
        result = com.exact_int(value, 'SAVED_PATH_ID')
    if result < 1 or result > 2147483647:
        raise SupplyContractError('INVALID_POSITIVE_PATH_ID')
    return result


def _filled(value):
    return value is not None and value != ''


def _packed(values):
    a = array('I', values)
    if a.itemsize != 4:
        raise SupplyContractError('UNSUPPORTED_UINT32_STORAGE')
    if sys.byteorder != 'little':
        a.byteswap()
    return a.tobytes()


def _unpacked(blob):
    if len(blob) % 4:
        raise SupplyContractError('CORRUPT_UINT32_GEOMETRY_BLOB')
    a = array('I')
    a.frombytes(blob)
    if sys.byteorder != 'little':
        a.byteswap()
    return a


def _key_digest(keys):
    h = hashlib.sha256()
    for key in sorted(keys):
        h.update(struct.pack('<III', *key))
    return h.hexdigest()


def create_list(visum, kind, code):
    """Only the PTV interfaces already exercised by the user's 15P/Q/R/S."""
    lists, _ = rt.get_lists_object(visum)
    obj = rt.create_list(lists, kind)
    all_routes, _ = rt.get_all_routes_filter()
    obj.SetObjects(0, code, all_routes)
    columns = PARENT_COLUMNS if kind == 'CreatePrTPathList' else GEOMETRY_COLUMNS
    for column in columns:
        obj.AddColumn(column)
    return obj


def bounded_rows(obj, columns, settings, control, phase, **details):
    size = int(settings['page_size'])
    fallback_sizes = list(settings.get('page_size_fallbacks', []))
    max_rows = int(settings['max_parent_rows_per_dseg'] if columns == PARENT_COLUMNS
                   else settings['max_geometry_rows_per_mode'])
    # Signature introspection is fail-closed; there is NO unbounded fallback.
    ole, memid, kind = rt.verified_bounded_signature(obj)
    first = 1
    pages = 0
    fallback_index = 0
    previous_full_page = None
    while True:
        control.checkpoint(phase, raw_rows=first-1, pages=pages, **details)
        last = first + size - 1
        retry_policy = settings.get("com_retry_policy")
        def retry_observer(event):
            control.checkpoint(
                phase, force=True, raw_rows=first-1, pages=pages,
                bounded_range_first=first, bounded_range_last=last,
                bounded_page_size=size, com_retry_event=event, **details)
        def exhausted_observer(event):
            control.checkpoint(
                phase, force=True, raw_rows=first-1, pages=pages,
                bounded_range_first=first, bounded_range_last=last,
                bounded_page_size=size, com_retry_event=event,
                com_retry_exhausted=True,
                com_retry_hresult=event.get("hresult"), **details)
        try:
            raw = com.bounded_ole_invoke_with_retry(
                ole, memid, kind, first, last,
                retry_policy=retry_policy, label=phase, on_retry=retry_observer,
                on_exhausted=exhausted_observer)
        except Exception as exc:
            # A transient RPC rejection already exhausted bounded same-range
            # retries. Never disguise it as a page-size problem.
            if com.is_retryable_com_error(exc):
                control.checkpoint(
                    phase, force=True, raw_rows=first-1, pages=pages,
                    bounded_range_first=first, bounded_range_last=last,
                    bounded_page_size=size, com_retry_exhausted=True,
                    com_retry_hresult=com.com_error_hresult(exc), **details)
                raise
            if not com.is_bounded_page_size_error(exc):
                raise
            while fallback_index < len(fallback_sizes) and fallback_sizes[fallback_index] >= size:
                fallback_index += 1
            if fallback_index < len(fallback_sizes):
                failed_size = size
                size = int(fallback_sizes[fallback_index])
                fallback_index += 1
                control.checkpoint(phase, force=True, raw_rows=first-1, pages=pages,
                                   page_size_fallback_from=failed_size,
                                   page_size_fallback_to=size,
                                   page_size_error=type(exc).__name__,
                                   page_size_hresult=com.com_error_hresult(exc), **details)
                continue
            raise
        page = [] if raw is None else raw
        if len(page) > size:
            raise SupplyContractError('BOUNDED_PAGE_EXCEEDS_REQUEST')
        if first-1+len(page) > max_rows:
            raise SupplyContractError('PATH_ROW_BUDGET_EXCEEDED:' + phase)
        # Catch a host ignoring FirstObject rather than running forever.
        if len(page) == size and previous_full_page is not None and page == previous_full_page:
            raise SupplyContractError('REPEATED_BOUNDED_PAGE_NO_PROGRESS')
        previous_full_page = page if len(page) == size else None
        for row in page:
            if len(row) != len(columns):
                raise SupplyContractError('BOUNDED_ROW_SCHEMA_MISMATCH')
            yield row
        pages += 1
        control.checkpoint(phase, raw_rows=first-1+len(page), pages=pages,
                           effective_page_size=size, **details)
        if len(page) < size:
            break
        first += len(page)


def read_matrix_authority(ds, zones):
    matrix = ds['object'].ODMatrix
    a = np.asarray(matrix.GetValues(), dtype='<f8')
    if a.shape != (zones, zones) or not np.isfinite(a).all() or (a < 0).any():
        raise SupplyContractError('INVALID_DSEG_MATRIX_AUTHORITY:' + ds['code'])
    total = float(a.sum(dtype=np.float64))
    declared = com.finite_float(matrix.AttValue('SUM'), 'DSeg matrix sum')
    if abs(total-declared) > max(1e-6, abs(total)*1e-8):
        raise SupplyContractError('MATRIX_SUM_MISMATCH:' + ds['code'])
    diagonal = float(np.trace(a))
    return {'matrix_no': _id(matrix.AttValue('NO')), 'matrix_total': total,
            'matrix_diagonal': diagonal, 'matrix_interzonal': max(0.0, total-diagonal),
            'matrix_sha256': hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest(),
            'matrix_shape': list(a.shape)}


class TwoModeRouteCollector(ActualSequenceRouteCollector):
    """Reuses branch solver algebra, not the old expanded per-DSeg route tables."""
    def __init__(self, profiles, policy, parent_hash, links, db_path,
                 settings=None, control=None, duplicate_scope_policy='FAIL',
                 max_unique_sequences=100000, max_pairs_per_market=64):
        ActualRouteCollector.__init__(self, profiles, policy, parent_hash,
            [k for k, v in links.items() if v.get('eligible')],
            duplicate_scope_policy=duplicate_scope_policy)
        self.epoch_profiles = [dict(x) for x in self.profiles]
        self.settings = validated_settings(settings)
        self.control = control or QuietControl()
        self.route_db_path = str(db_path)
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            raise SupplyContractError('MODE_STORE_MUST_BE_NEW_NO_CROSS_RUN_REUSE')
        self.db = sqlite3.connect(str(p))
        try:
            self.db.executescript('''
                PRAGMA journal_mode=DELETE;
                PRAGMA synchronous=FULL;
                PRAGMA foreign_keys=ON;
                PRAGMA cache_size=-32768;
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE segments(dseg TEXT PRIMARY KEY, mode TEXT NOT NULL, audit_json TEXT NOT NULL);
                CREATE TABLE geometry(
                    gid INTEGER PRIMARY KEY, mode TEXT NOT NULL, orig INTEGER NOT NULL,
                    dest INTEGER NOT NULL, path_index INTEGER NOT NULL,
                    edge_ids BLOB, edge_count INTEGER, sequence_sha256 TEXT, geometry_kind TEXT,
                    UNIQUE(mode,orig,dest,path_index));
                CREATE TABLE volumes(
                    gid INTEGER NOT NULL REFERENCES geometry(gid), dseg TEXT NOT NULL REFERENCES segments(dseg),
                    volume REAL NOT NULL CHECK(volume>=0), PRIMARY KEY(gid,dseg)) WITHOUT ROWID;
                CREATE TABLE edges(eid INTEGER PRIMARY KEY, link_no INTEGER NOT NULL,
                    from_no INTEGER NOT NULL,to_no INTEGER NOT NULL, UNIQUE(link_no,from_no,to_no));
                CREATE TABLE profile_hits(gid INTEGER NOT NULL, profile_index INTEGER NOT NULL,
                    multiplicity INTEGER NOT NULL, PRIMARY KEY(gid,profile_index)) WITHOUT ROWID;
                CREATE TABLE driver_markets(mode TEXT NOT NULL,orig INTEGER NOT NULL,dest INTEGER NOT NULL,
                    PRIMARY KEY(mode,orig,dest)) WITHOUT ROWID;
                CREATE TABLE edge_postings(eid INTEGER NOT NULL,chunk INTEGER NOT NULL,pairs BLOB NOT NULL,
                    PRIMARY KEY(eid,chunk)) WITHOUT ROWID;
            ''')
            self.db.execute('INSERT INTO metadata VALUES(?,?)', ('schema', SCHEMA))
            self.db.execute('INSERT INTO metadata VALUES(?,?)', ('parent_hash', parent_hash))
            self.db.execute('INSERT INTO metadata VALUES(?,?)', ('geometry_identity', PROVISIONAL))
            self.db.execute('INSERT INTO metadata VALUES(?,?)', ('apply_permitted', 'false'))
            self.edge_keys = (None,) + tuple(sorted(links))
            self.edge_ids = {key: i for i, key in enumerate(self.edge_keys) if key is not None}
            self.db.executemany('INSERT INTO edges VALUES(?,?,?,?)',
                                ((i, *key) for key, i in self.edge_ids.items()))
            self.allowed_tsys = {k: set(v.get('tsys', ())) for k,v in links.items()}
            self.db.commit()
            self.evidence = defaultdict(dict)
            self.max_unique_sequences = int(max_unique_sequences)
            self.max_pairs_per_market = int(max_pairs_per_market)
            self.skipped_branches = Counter()
            self.protected = {i for i,r in enumerate(self.profiles) if
                str(r.get('role','')).upper() == 'CALIBRATION' and number(r['observed']) > 0
                and core.geh(number(r['model']),number(r['observed'])) < 5.0}
            self.cal_indices = {i for i,r in enumerate(self.profiles) if
                                str(r.get('role','')).upper() == 'CALIBRATION'}
            self.parents = {}
            self.parity_rows = []
            self.mode_audits = {}
            self.route_count = 0
            self.geometry_count = 0
            self.export_complete = False
            self.incidence_ready = False
            self.sequence_ready = False
            self.ready = False
            self._finished_proof = None
            self._posting_chunk = 0
            self._last_resource_check = 0.0
            self._closed = False
            self.summary = {'schema': SCHEMA, 'apply_permitted': False,
                            'pathlink_geometry_full_identity_proven': False,
                            'geometry_identity': PROVISIONAL, 'status': 'BUILDING',
                            'parent_hash': parent_hash, 'same_run_only': True,
                            'modes': {}, 'dsegs': [], 'fatal_errors': [],
                            'edge_dictionary_sha256':canonical_hash(list(self.edge_keys[1:]))}
        except BaseException:
            self.db.close()
            self._closed = True
            raise

    @classmethod
    def open_existing(cls, profiles, policy, links, db_path, settings=None, control=None,
                      duplicate_scope_policy='FAIL', max_unique_sequences=100000,
                      max_pairs_per_market=64, read_only=True,
                      require_profile_metadata=False):
        """Rehydrate a completed normalized path store without COM enumeration.

        The caller remains responsible for manifest/state authorization. This
        method validates the SQLite structure, link dictionary and observation
        profile order before exposing proposal evidence.
        """
        path = Path(db_path)
        if not path.is_file() or path.stat().st_size <= 0:
            raise SupplyContractError('PERSISTENT_MODE_STORE_MISSING_OR_EMPTY')
        uri = path.resolve().as_uri() + '?mode=ro'
        db = sqlite3.connect(uri, uri=True) if read_only else sqlite3.connect(str(path))
        try:
            if read_only:
                db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA foreign_keys=ON')
            check = [str(r[0]) for r in db.execute('PRAGMA quick_check')]
            if check != ['ok']:
                raise SupplyContractError('PERSISTENT_MODE_STORE_QUICK_CHECK_FAILED')
            if list(db.execute('PRAGMA foreign_key_check')):
                raise SupplyContractError('PERSISTENT_MODE_STORE_FOREIGN_KEY_FAILED')
            metadata = {str(k): str(v) for k, v in db.execute(
                'SELECT key,value FROM metadata')}
            if metadata.get('schema') != SCHEMA:
                raise SupplyContractError('PERSISTENT_MODE_STORE_SCHEMA_MISMATCH')
            if (metadata.get('structural_export_complete') != 'true' or
                    metadata.get('incidence_ready') != 'true'):
                raise SupplyContractError('PERSISTENT_MODE_STORE_NOT_COMPLETE')
            parent_hash = metadata.get('parent_hash')
            if not parent_hash:
                raise SupplyContractError('PERSISTENT_MODE_STORE_PARENT_HASH_MISSING')

            self = cls.__new__(cls)
            ActualRouteCollector.__init__(
                self, profiles, policy, parent_hash,
                [k for k, v in links.items() if v.get('eligible')],
                duplicate_scope_policy=duplicate_scope_policy)
            self.epoch_profiles = [dict(x) for x in self.profiles]
            self.settings = validated_settings(settings)
            self.control = control or QuietControl()
            self.route_db_path = str(path)
            self.db = db
            self.read_only = bool(read_only)
            self.max_unique_sequences = int(max_unique_sequences)
            self.max_pairs_per_market = int(max_pairs_per_market)
            self.skipped_branches = Counter()
            self.evidence = defaultdict(dict)
            self._finished_proof = None
            self._last_resource_check = 0.0
            self._closed = False
            self._posting_chunk = int(db.execute(
                'SELECT COALESCE(MAX(chunk),0) FROM edge_postings').fetchone()[0])

            edge_rows = list(db.execute(
                'SELECT eid,link_no,from_no,to_no FROM edges ORDER BY eid'))
            if [int(r[0]) for r in edge_rows] != list(range(1, len(edge_rows) + 1)):
                raise SupplyContractError(
                    'PERSISTENT_MODE_STORE_EDGE_IDS_NOT_CONTIGUOUS')
            stored_keys = tuple((int(r[1]), int(r[2]), int(r[3])) for r in edge_rows)
            live_keys = tuple(sorted(tuple(int(x) for x in key) for key in links))
            if stored_keys != live_keys:
                raise SupplyContractError(
                    'PERSISTENT_MODE_STORE_LINK_DICTIONARY_CHANGED')
            self.edge_keys = (None,) + stored_keys
            self.edge_ids = {key: i for i, key in enumerate(self.edge_keys)
                             if key is not None}
            self.allowed_tsys = {k: set(v.get('tsys', ())) for k, v in links.items()}

            self.parents = {}
            self.parity_rows = []
            for code, mode, audit_json in db.execute(
                    'SELECT dseg,mode,audit_json FROM segments ORDER BY dseg'):
                try:
                    audit = json.loads(audit_json)
                except Exception as exc:
                    raise SupplyContractError(
                        'PERSISTENT_MODE_STORE_SEGMENT_AUDIT_INVALID:' + str(exc))
                if audit.get('dseg_code') != code or audit.get('mode') != mode:
                    raise SupplyContractError(
                        'PERSISTENT_MODE_STORE_SEGMENT_AUDIT_MISMATCH')
                self.parents[str(code)] = audit
                self.parity_rows.append(audit)
            if not self.parents:
                raise SupplyContractError('PERSISTENT_MODE_STORE_EMPTY_SEGMENTS')

            self.mode_audits = {}
            self.geometry_count = 0
            for mode in sorted({a['mode'] for a in self.parents.values()}):
                dsegs = sorted(c for c, a in self.parents.items() if a['mode'] == mode)
                rep = core.norm_code(self.settings['representatives'][mode])
                if rep not in dsegs:
                    raise SupplyContractError(
                        'PERSISTENT_MODE_STORE_REPRESENTATIVE_MISSING:' + mode)
                rep_audit = self.parents[rep]
                rows = list(db.execute(
                    'SELECT orig,dest,path_index,sequence_sha256,edge_count,geometry_kind '
                    'FROM geometry WHERE mode=? ORDER BY orig,dest,path_index', (mode,)))
                if (not rows or
                        any(r[3] is None or r[4] is None or r[5] is None for r in rows)):
                    raise SupplyContractError(
                        'PERSISTENT_MODE_STORE_GEOMETRY_INCOMPLETE:' + mode)
                h = hashlib.sha256()
                children = zero_inter = zero_intra = 0
                for o, d, ix, digest, count, kind in rows:
                    h.update(struct.pack('<III', int(o), int(d), int(ix)))
                    h.update(str(digest).encode('ascii'))
                    children += int(count)
                    if int(count) == 0:
                        if int(o) == int(d):
                            zero_intra += 1
                        else:
                            zero_inter += 1
                self.mode_audits[mode] = {
                    'representative_dseg': rep,
                    'parent_keys_sha256': rep_audit['parent_keys_sha256'],
                    'parent_count': len(rows),
                    'dsegs': dsegs,
                    'geometry_complete': True,
                    'geometry_routes': len(rows),
                    'geometry_link_children': children,
                    'geometry_raw_rows': len(rows) + children,
                    'zero_link_interzonal_paths': zero_inter,
                    'zero_link_intrazonal_paths': zero_intra,
                    'representative_geometry_sha256': h.hexdigest(),
                    'geometry_reads': 0,
                    'reopened_from_persistent_store': True,
                }
                self.geometry_count += len(rows)

            max_profile = db.execute(
                'SELECT COALESCE(MAX(profile_index),-1) FROM profile_hits').fetchone()[0]
            if int(max_profile) >= len(self.profiles):
                raise SupplyContractError(
                    'PERSISTENT_MODE_STORE_PROFILE_INDEX_OUT_OF_RANGE')
            profile_ids = [self._profile_id(r) for r in self.profiles]
            stored_authority = metadata.get('observation_authority_hash')
            stored_order = metadata.get('profile_order_hash')
            if require_profile_metadata and (not stored_authority or not stored_order):
                raise SupplyContractError(
                    'PERSISTENT_MODE_STORE_PROFILE_METADATA_MISSING')
            if (stored_authority and
                    stored_authority != observation_identity(
                        self.profiles, include_model=False)):
                raise SupplyContractError(
                    'PERSISTENT_MODE_STORE_OBSERVATION_AUTHORITY_CHANGED')
            if stored_order and stored_order != canonical_hash(profile_ids):
                raise SupplyContractError(
                    'PERSISTENT_MODE_STORE_PROFILE_ORDER_CHANGED')

            self.route_count = 0
            self.export_complete = False
            self.incidence_ready = False
            self.sequence_ready = False
            self.ready = False
            self.summary = {
                'schema': SCHEMA,
                'apply_permitted': False,
                'pathlink_geometry_full_identity_proven': False,
                'geometry_identity': PROVISIONAL,
                'status': 'REOPENING_PERSISTENT_STORE',
                'parent_hash': parent_hash,
                'same_run_only': False,
                'persistent_cross_run_reuse': True,
                'modes': {},
                'dsegs': [],
                'fatal_errors': [],
                'edge_dictionary_sha256': canonical_hash(list(self.edge_keys[1:])),
            }
            # Restore maximum repeated-edge multiplicity used by ADDVAL1 safety.
            self.edge_max_multiplicity = Counter()
            for eid, blob in db.execute(
                    'SELECT eid,pairs FROM edge_postings ORDER BY eid,chunk'):
                values = _unpacked(zlib.decompress(blob))
                if len(values) % 2:
                    raise SupplyContractError(
                        'PERSISTENT_MODE_STORE_CORRUPT_EDGE_POSTINGS')
                maximum = max((int(values[i + 1])
                               for i in range(0, len(values), 2)), default=0)
                if maximum:
                    key = self.edge_keys[int(eid)]
                    self.edge_max_multiplicity[key] = max(
                        self.edge_max_multiplicity[key], maximum)
            self.prepare_incidence_evidence()
            self.summary['persistent_cache_reopened'] = True
            self.summary['persistent_cache_read_only'] = bool(read_only)
            return self
        except BaseException:
            db.close()
            raise

    def close(self):
        if not self._closed:
            self.db.close()
            self._closed = True
        self.ready = False
        self.export_complete = False
        self.incidence_ready = False
        self.sequence_ready = False
        self._finished_proof = None

    def check_resources(self, force=False):
        now = time.monotonic()
        if not force and now-self._last_resource_check < 5:
            return
        self._last_resource_check = now
        p = Path(self.route_db_path)
        size = p.stat().st_size if p.exists() else 0
        if size > float(self.settings['max_store_gib'])*1024**3:
            raise DesignStopRequested('SQLITE_STORAGE_BUDGET_EXCEEDED')
        if shutil.disk_usage(p.parent).free < float(self.settings['min_free_disk_gib'])*1024**3:
            raise DesignStopRequested('LOW_FREE_DISK_SPACE')

    def add_parents(self, code, mode, rows, matrix_authority):
        """Full DSeg scan, exact set join, distinct volumes including all zero rows."""
        code = core.norm_code(code)
        if code in self.parents or mode not in ('C','C_NOT'):
            raise SupplyContractError('DUPLICATE_DSEG_OR_UNKNOWN_MODE')
        values = {}
        for raw in rows:
            if len(raw)!=4:raise SupplyContractError('PARENT_ROW_SCHEMA_MISMATCH')
            key = tuple(_id(x) for x in raw[:3])
            if key in values:
                raise SupplyContractError('DUPLICATE_PARENT_KEY:' + code)
            vol = com.finite_float(raw[3], 'Vol(AP)')
            if vol < 0:
                raise SupplyContractError('NEGATIVE_PATH_VOLUME')
            if len(values) >= int(self.settings['max_parent_rows_per_dseg']):
                raise SupplyContractError('PARENT_ROW_BUDGET_EXCEEDED')
            values[key] = vol
        key_hash = _key_digest(values)
        key_map = {tuple(r[1:]): r[0] for r in self.db.execute(
            'SELECT gid,orig,dest,path_index FROM geometry WHERE mode=?', (mode,))}
        mode_is_new = mode not in self.mode_audits
        if not mode_is_new and set(key_map) != set(values):
            missing = sorted(set(key_map)-set(values))[:8]
            extra = sorted(set(values)-set(key_map))[:8]
            raise SupplyContractError('FULL_PARENT_KEYS_DIFFER: %s missing=%r extra=%r' % (code,missing,extra))
        if mode_is_new:
            self.db.executemany('INSERT INTO geometry(mode,orig,dest,path_index) VALUES(?,?,?,?)',
                ((mode,*key) for key in sorted(values)))
            key_map = {tuple(r[1:]): r[0] for r in self.db.execute(
                'SELECT gid,orig,dest,path_index FROM geometry WHERE mode=?', (mode,))}
            self.mode_audits[mode] = {'representative_dseg': code, 'parent_keys_sha256': key_hash,
                                      'parent_count':len(values), 'dsegs':[]}
        total = math.fsum(values.values())
        intra = math.fsum(v for (o,d,_),v in values.items() if o==d)
        inter = math.fsum(v for (o,d,_),v in values.items() if o!=d)
        ref = float(matrix_authority['matrix_interzonal'])
        rel = abs(inter-ref)/max(1.0,abs(ref))
        tolerance = float(self.settings.get('dseg_path_volume_relative_tolerance', 0.01))
        passes = abs(inter) <= 1e-9 if ref <= 1e-9 else rel <= tolerance
        vol_hash = hashlib.sha256()
        comparison_hash = hashlib.sha256()
        comparison_decimals = int(self.settings['path_epoch_volume_comparison_decimals'])
        for key in sorted(values):
            vol_hash.update(struct.pack('<IIId',*key,values[key]))
            comparison_hash.update(struct.pack('<IIId',*key,round(values[key], comparison_decimals)))
        audit = {'dseg_code':code,'mode':mode,'path_rows':len(values),
                 'positive_volume_rows':sum(v>0 for v in values.values()),
                 'zero_volume_rows':sum(v==0 for v in values.values()),
                 'intrazonal_parent_rows':sum(o==d for o,d,_ in values),
                 'parent_keys_sha256':key_hash, 'keys_and_volumes_sha256':vol_hash.hexdigest(),
                 'keys_and_volumes_comparison_sha256':comparison_hash.hexdigest(),
                 'path_epoch_volume_comparison_decimals':comparison_decimals,
                 'saved_path_volume_sum':total,'saved_path_interzonal_volume_sum':inter,
                 'saved_path_intrazonal_volume_sum':intra,
                 'relative_abs_diff':rel,'passes':passes,'tolerance':tolerance,
                 'parity_basis':'SAME_RUN_INTERZONAL_MATRIX_VS_INTERZONAL_SAVED_PATHS',
                 **matrix_authority}
        self.db.execute('INSERT INTO segments VALUES(?,?,?)',(code,mode,json.dumps(audit)))
        self.db.executemany('INSERT INTO volumes VALUES(?,?,?)',
                            ((key_map[key],code,v) for key,v in values.items()))
        self.db.commit()
        self.parents[code] = audit
        self.parity_rows.append(audit)
        self.mode_audits[mode]['dsegs'].append(code)
        self.summary['dsegs'].append(code)
        self.control.checkpoint('PARENTS_DSEG_COMPLETE', force=True, dseg_code=code,
             parent_rows=len(values), positive_volume_rows=audit['positive_volume_rows'],
             offdiagonal_relative_difference=rel)
        self.check_resources(force=True)
        if not passes:
            raise SupplyContractError('SAME_RUN_OFFDIAGONAL_PARITY_FAILED:' + code)
        return audit

    def add_geometry(self, mode, raw_rows):
        """Parse ONE representative's full hierarchy; keep state across pages."""
        if mode not in self.mode_audits or self.mode_audits[mode].get('geometry_complete'):
            raise SupplyContractError('INVALID_OR_DUPLICATE_GEOMETRY_MODE')
        key_map = {tuple(r[1:]):r[0] for r in self.db.execute(
            'SELECT gid,orig,dest,path_index FROM geometry WHERE mode=?', (mode,))}
        seen = set()
        parent = None
        seq_ids = []
        updates = []
        hits_batch = []
        market_batch = set()
        postings = defaultdict(lambda:array('I'))
        raw_count = child_count = 0
        last_end = None
        mode_max_mult = Counter()
        zero_link_interzonal = zero_link_intrazonal = 0
        def flush():
            if not updates:
                return
            self.control.checkpoint('GEOMETRY_STORE_COMMIT', mode=mode,
                 geometry_routes=len(seen), raw_rows=raw_count, link_children=child_count)
            self.db.executemany('UPDATE geometry SET edge_ids=?,edge_count=?,sequence_sha256=?,geometry_kind=? WHERE gid=?',updates)
            self.db.executemany('INSERT INTO profile_hits VALUES(?,?,?)',hits_batch)
            self.db.executemany('INSERT OR IGNORE INTO driver_markets VALUES(?,?,?)',market_batch)
            self._posting_chunk += 1
            self.db.executemany('INSERT INTO edge_postings VALUES(?,?,?)',
                ((eid,self._posting_chunk,zlib.compress(_packed(ids),1)) for eid,ids in postings.items()))
            self.db.commit()
            updates.clear(); hits_batch.clear(); market_batch.clear(); postings.clear()
            self.check_resources()
        def finish_route():
            nonlocal zero_link_interzonal, zero_link_intrazonal
            if parent is None:
                return
            if parent not in key_map or parent in seen:
                raise SupplyContractError('ORPHAN_OR_REPEATED_GEOMETRY_PARENT:%r' % (parent,))
            gid = key_map[parent]
            # A complete official parent with no link children has no link-cost
            # exposure.  Do not confuse its b'' payload with an unexported NULL.
            kind = 'LINK_SEQUENCE'
            if not seq_ids:
                if parent[0] != parent[1]:
                    zero_link_interzonal += 1
                    kind = 'ZERO_LINK_INTERZONAL_NO_ADDVAL1_EFFECT'
                else:
                    zero_link_intrazonal += 1
                    kind = 'ZERO_LINK_INTRAZONAL_NO_ADDVAL1_EFFECT'
            seen.add(parent)
            blob = _packed(seq_ids)
            updates.append((blob,len(seq_ids),hashlib.sha256(blob).hexdigest(),kind,gid))
            mult = Counter(seq_ids)
            hit = Counter()
            for eid,n in mult.items():
                postings[eid].extend((gid,n))
                key = self.edge_keys[eid]
                mode_max_mult[key] = max(mode_max_mult[key],n)
                for i in self.profile_index_by_key.get(key,()):
                    hit[i] += n
            hits_batch.extend((gid,i,n) for i,n in hit.items())
            # Store every CAL market, not only the drivers selected at export
            # time.  Path epochs reclassify live residual drivers after accepted
            # assignments without repeating the expensive COM enumeration.
            if any(i in hit for i in self.cal_indices):
                market_batch.add((mode,parent[0],parent[1]))
            if len(updates) >= int(self.settings['commit_routes']):
                flush()
        for raw in raw_rows:
            raw_count += 1
            if raw_count > int(self.settings['max_geometry_rows_per_mode']):
                raise SupplyContractError('GEOMETRY_ROW_BUDGET_EXCEEDED')
            if len(raw)!=7:
                raise SupplyContractError('GEOMETRY_ROW_SCHEMA_MISMATCH')
            supplied_parent = tuple(_filled(x) for x in raw[:3])
            supplied_link = tuple(_filled(x) for x in raw[3:])
            if not any(supplied_link):
                if not all(supplied_parent):
                    raise SupplyContractError('INCOMPLETE_GEOMETRY_PARENT')
                next_parent = tuple(_id(x) for x in raw[:3])
                finish_route()
                parent=next_parent; seq_ids=[]; last_end=None
                if parent not in key_map or parent in seen:
                    raise SupplyContractError('UNKNOWN_OR_REOPENED_GEOMETRY_PARENT')
                continue
            if not all(supplied_link):
                raise SupplyContractError('INCOMPLETE_GEOMETRY_CHILD')
            if all(supplied_parent):
                k=tuple(_id(x) for x in raw[:3])
                if k!=parent:
                    finish_route()
                    parent=k; seq_ids=[]; last_end=None
                    if parent not in key_map or parent in seen:
                        raise SupplyContractError('UNKNOWN_OR_REOPENED_FLAT_PARENT')
            elif any(supplied_parent):
                if parent is None or any(s and _id(raw[j]) != parent[j] for j,s in enumerate(supplied_parent)):
                    raise SupplyContractError('CONFLICTING_PARTIAL_GEOMETRY_PARENT')
            if parent is None:
                raise SupplyContractError('ORPHAN_GEOMETRY_CHILD')
            idx=_id(raw[3]); key=tuple(_id(x) for x in raw[4:])
            if idx!=len(seq_ids)+1:
                raise SupplyContractError('GEOMETRY_LINK_INDEX_NOT_CONTIGUOUS')
            if last_end is not None and last_end!=key[1]:
                raise SupplyContractError('DISCONNECTED_OFFICIAL_PATH_LINK_SEQUENCE')
            if key not in self.edge_ids:
                raise SupplyContractError('PATH_EDGE_NOT_IN_LIVE_NETWORK:%r' % (key,))
            # Link existence/topology are verified; no inferred replacement edge.
            seq_ids.append(self.edge_ids[key]); last_end=key[2]; child_count+=1
            if len(seq_ids)>int(self.settings['max_links_per_path']):
                raise SupplyContractError('SINGLE_ROUTE_LENGTH_BUDGET_EXCEEDED')
        finish_route(); flush()
        if seen!=set(key_map):
            raise SupplyContractError('GEOMETRY_PARENT_COVERAGE_INCOMPLETE')
        for key,n in mode_max_mult.items():
            self.edge_max_multiplicity[key]=max(self.edge_max_multiplicity[key],n)
        h=hashlib.sha256()
        for o,d,ix,digest in self.db.execute('SELECT orig,dest,path_index,sequence_sha256 FROM geometry WHERE mode=? ORDER BY orig,dest,path_index',(mode,)):
            h.update(struct.pack('<III',o,d,ix));h.update(digest.encode('ascii'))
        self.mode_audits[mode].update(geometry_complete=True,geometry_routes=len(seen),
             geometry_link_children=child_count,geometry_raw_rows=raw_count,
             zero_link_interzonal_paths=zero_link_interzonal,
             zero_link_intrazonal_paths=zero_link_intrazonal,
             representative_geometry_sha256=h.hexdigest(),geometry_reads=1)
        self.geometry_count+=len(seen)
        self.control.checkpoint('MODE_GEOMETRY_COMPLETE',force=True,mode=mode,
            geometry_routes=len(seen),link_children=child_count)
        return self.mode_audits[mode]

    def _decode(self, blob):
        return tuple(self.edge_keys[eid] for eid in _unpacked(blob))

    @staticmethod
    def _profile_id(row):
        value = core.first_value(row, ('countlocation_no','obs_id','code'), '')
        value = str(value).strip()
        if not value:
            raise SupplyContractError('INVALID_OBSERVATION_IDENTITY')
        return value

    def _refresh_driver_state(self):
        """Refresh dynamic driver classification without re-enumerating paths.

        Profile identity, directed link scope, CAL/VALID role, observed values and
        weights remain immutable.  Only live model values may change between
        accepted states.  Sequence evidence is therefore rebuilt from the same
        frozen path epoch, while the expensive COM path enumeration is retained.
        """
        excluded = set(self.duplicate_scope_audit.get(
            'excluded_conflicting_driver_indices', ()))
        self.protected = {i for i,r in enumerate(self.profiles) if
            str(r.get('role','')).upper() == 'CALIBRATION' and
            number(r['observed']) > 0 and
            core.geh(number(r['model']), number(r['observed'])) < 5.0}
        self.cal_indices = {i for i,r in enumerate(self.profiles) if
                            str(r.get('role','')).upper() == 'CALIBRATION'}
        duplicate_physical = set()
        drivers = []
        for i,row in enumerate(self.profiles):
            if i in excluded or str(row.get('role','')).upper() != 'CALIBRATION':
                continue
            obs = number(row['observed']); model = number(row['model'])
            if (obs <= 0 or abs(model-obs) < self.policy.min_residual or
                    core.geh(model, obs) < self.policy.min_geh):
                continue
            physical = (self.key_groups[i], str(row.get('source_group','CSD2022')))
            if physical in duplicate_physical:
                continue
            duplicate_physical.add(physical)
            drivers.append(i)
        drivers.sort(key=lambda i:(-core.geh(number(self.profiles[i]['model']),
                                                   number(self.profiles[i]['observed'])),
                                   self.keys[i]))
        self.drivers = drivers[:self.policy.max_driver_profiles]
        self.edge_contrast = {i:defaultdict(float) for i in self.drivers}
        self.support = {i:0.0 for i in self.drivers}
        self.market_counts = {i:0 for i in self.drivers}
        self.probe_only_counts = {i:0 for i in self.drivers}
        self.evidence = defaultdict(dict)
        self.skipped_branches = Counter()
        self.sequence_ready = False
        self.ready = False
        self._finished_proof = None
        self.summary['sequence_evidence_ready'] = False
        self.summary['live_driver_count'] = len(self.drivers)

    def rebind_profiles(self, rows, *, refresh_drivers=False):
        """Bind current diagnostics to an immutable path epoch.

        This is not a path refresh.  It updates only the live model values used
        by proposal generation.  Any identity, role, observation, weight or
        directed-scope drift is a hard error.
        """
        rows = [dict(x) for x in rows]
        if observation_identity(rows, include_model=False) != self.authority_hash:
            raise SupplyContractError('PATH_EPOCH_OBSERVATION_AUTHORITY_CHANGED')
        observation_identity(rows, include_model=True)
        live = {self._profile_id(r):r for r in rows}
        if len(live) != len(rows) or len(live) != len(self.profiles):
            raise SupplyContractError('PATH_EPOCH_PROFILE_SET_CHANGED')
        rebound = []
        for old in self.profiles:
            ident = self._profile_id(old)
            if ident not in live:
                raise SupplyContractError('PATH_EPOCH_PROFILE_MISSING:' + ident)
            new = live[ident]
            if (str(new.get('role','')).upper() != str(old.get('role','')).upper() or
                    number(new.get('observed'),'observed') != number(old.get('observed'),'observed') or
                    number(new.get('profile_weight',1.0),'profile_weight') !=
                    number(old.get('profile_weight',1.0),'profile_weight') or
                    tuple(core._profile_link_keys(new)) != tuple(core._profile_link_keys(old))):
                raise SupplyContractError('PATH_EPOCH_PROFILE_STATIC_CONTRACT_CHANGED:' + ident)
            rebound.append(new)
        self.profiles = rebound
        if refresh_drivers:
            self._refresh_driver_state()
        else:
            self.protected = {i for i,r in enumerate(self.profiles) if
                str(r.get('role','')).upper() == 'CALIBRATION' and
                number(r['observed']) > 0 and
                core.geh(number(r['model']), number(r['observed'])) < 5.0}
            self.cal_indices = {i for i,r in enumerate(self.profiles) if
                                str(r.get('role','')).upper() == 'CALIBRATION'}
        model_hash = canonical_hash([(self._profile_id(r), number(r['model']))
                                     for r in self.profiles])
        self.summary['live_profile_model_hash'] = model_hash
        self.summary['profiles_rebound_without_path_enumeration'] = True
        return {'profile_count':len(self.profiles), 'model_hash':model_hash,
                'drivers_refreshed':bool(refresh_drivers),
                'driver_count':len(self.drivers)}

    def path_structure_hash(self):
        self.prepare_incidence_evidence()
        payload = {
            'edge_dictionary_sha256':self.summary['edge_dictionary_sha256'],
            'modes':{m:{'parent_keys_sha256':a['parent_keys_sha256'],
                        'representative_geometry_sha256':a['representative_geometry_sha256']}
                     for m,a in sorted(self.mode_audits.items())},
            'dsegs':{c:self.parents[c]['parent_keys_sha256'] for c in sorted(self.parents)},
        }
        return canonical_hash(payload)

    def path_basis_hash(self):
        """Exact geometry + IEEE-754 path-volume identity for audit."""
        self.prepare_incidence_evidence()
        return canonical_hash({
            'structure':self.path_structure_hash(),
            'dsegs':{c:self.parents[c]['keys_and_volumes_sha256'] for c in sorted(self.parents)},
        })

    def path_basis_comparison_hash(self):
        """Canonical route/volume identity for refresh stationarity.

        Unlike the exact audit hash this ignores path-index renumbering and
        aggregates duplicate identical sequences inside one OD relation.  Route
        geometry, DSeg, OD and materially different volume remain authoritative.
        Tiny volume noise is rounded only for this comparison; exact hashes are
        persisted separately.
        """
        self.prepare_incidence_evidence()
        cached = self.summary.get('path_basis_comparison_hash')
        if cached:
            return cached
        decimals = int(self.settings['path_epoch_volume_comparison_decimals'])
        digest = hashlib.sha256()
        digest.update(('ROUTE_VOLUME_V1|DECIMALS=%d|' % decimals).encode('ascii'))
        query = '''SELECT v.dseg,g.mode,g.orig,g.dest,g.sequence_sha256,g.geometry_kind,SUM(v.volume)
            FROM volumes v JOIN geometry g ON g.gid=v.gid
            GROUP BY v.dseg,g.mode,g.orig,g.dest,g.sequence_sha256,g.geometry_kind
            ORDER BY v.dseg,g.mode,g.orig,g.dest,g.sequence_sha256,g.geometry_kind'''
        count = 0
        for code,mode,o,d,sequence_sha,kind,volume in self.db.execute(query):
            if sequence_sha is None or kind is None:
                raise SupplyContractError('PATH_EPOCH_COMPARISON_GEOMETRY_INCOMPLETE')
            digest.update(str(code).encode('utf-8')); digest.update(b'\0')
            digest.update(str(mode).encode('ascii')); digest.update(b'\0')
            digest.update(struct.pack('<II',int(o),int(d)))
            digest.update(str(sequence_sha).encode('ascii')); digest.update(b'\0')
            digest.update(str(kind).encode('ascii')); digest.update(b'\0')
            digest.update(struct.pack('<d',round(float(volume or 0.0),decimals)))
            count += 1
        digest.update(struct.pack('<Q',count))
        result = digest.hexdigest()
        self.summary['path_basis_comparison_hash'] = result
        self.summary['path_basis_comparison_rows'] = count
        self.summary['path_basis_comparison_semantics'] = (
            'DSEG_MODE_OD_SEQUENCE_GEOMETRY_KIND_AGGREGATED_VOLUME_PATH_INDEX_INVARIANT')
        return result

    def prepare_incidence_evidence(self):
        """Finalize export/parity state needed by TG without building branch pairs."""
        if self.incidence_ready:
            return self.summary
        if self.db.execute('SELECT COUNT(*) FROM geometry WHERE edge_ids IS NULL OR edge_count IS NULL').fetchone()[0]:
            raise SupplyContractError('UNEXPORTED_GEOMETRY_IS_NOT_A_ZERO_LINK_PATH')
        if any(not a.get('geometry_complete') for a in self.mode_audits.values()):
            raise SupplyContractError('TWO_MODE_GEOMETRY_NOT_COMPLETE')
        self.control.checkpoint('ALL_PROFILE_FLOW_PARITY',force=True)
        self.flow=[0.0]*len(self.profiles)
        for i,v in self.db.execute('''SELECT h.profile_index,SUM(v.volume*h.multiplicity)
             FROM profile_hits h JOIN volumes v ON v.gid=h.gid GROUP BY h.profile_index'''):
            self.flow[i]=v
        self.batches=[]
        self.route_count=0
        for code,audit in self.parents.items():
            n = audit['positive_volume_rows'];vol=audit['saved_path_volume_sum']
            self.route_count+=n
            self.batches.append({'dseg':code,'positive_paths':n,'covered_paths':n,
                'path_coverage':1.0,'volume_coverage':1.0,'total_volume':vol,'covered_volume':vol,
                'official_route_batch_hash':canonical_hash([audit['keys_and_volumes_sha256'],
                    self.mode_audits[audit['mode']]['representative_geometry_sha256']]),
                'geometry_mode':audit['mode'],'geometry_identity':PROVISIONAL})
        zero_rows = [dict(dseg=r[0], zero_link_paths=r[1], zero_link_volume=r[2],
                          positive_zero_link_paths=r[3]) for r in self.db.execute('''
            SELECT v.dseg,COUNT(*),SUM(v.volume),SUM(CASE WHEN v.volume>0 THEN 1 ELSE 0 END)
            FROM volumes v JOIN geometry g ON v.gid=g.gid WHERE g.edge_count=0
            GROUP BY v.dseg ORDER BY v.dseg''')]
        self.summary['zero_link_paths_by_dseg'] = zero_rows
        self.summary['zero_link_policy'] = 'EXPLICIT_COMPLETE_PARENT_PRESERVE_VOLUME_NO_LINK_ATTRIBUTION'
        self.summary['connector_topology_proven'] = False
        self.export_complete=True
        self.incidence_ready=True
        self.summary.update(status='INCIDENCE_READY_SEQUENCE_DEFERRED',modes=self.mode_audits,
            export_complete=True,incidence_ready=True,sequence_evidence_ready=False,
            full_parent_keys_identical_within_mode=True,
            dseg_count=len(self.parents),dseg_complete_count=len(self.parents),
            all_selected_dsegs_complete=True,
            dseg_path_volume_parity_passes=all(r['passes'] for r in self.parity_rows),
            path_rows=sum(r['path_rows'] for r in self.parents.values()),
            positive_segment_paths=self.route_count,geometry_route_count=self.geometry_count,
            full_geometry_read_count=len(self.mode_audits),
            pathlink_rows=sum(a['geometry_link_children'] for a in self.mode_audits.values()),
            memory_strategy='TWO_MODE_UINT32_GEOMETRY_SQLITE_INDEPENDENT_DSEG_VOLUMES',
            new_assignment_executed=False,derived_design_provisional=True)
        self.summary['path_structure_hash'] = canonical_hash({
            'edge_dictionary_sha256':self.summary['edge_dictionary_sha256'],
            'modes':{m:{'parent_keys_sha256':a['parent_keys_sha256'],
                        'representative_geometry_sha256':a['representative_geometry_sha256']}
                     for m,a in sorted(self.mode_audits.items())},
            'dsegs':{c:self.parents[c]['parent_keys_sha256'] for c in sorted(self.parents)},
        })
        self.summary['path_basis_hash'] = canonical_hash({
            'structure':self.summary['path_structure_hash'],
            'dsegs':{c:self.parents[c]['keys_and_volumes_sha256'] for c in sorted(self.parents)},
        })
        # Canonical index-invariant comparison hash is computed lazily from
        # completed geometry + volumes by path_basis_comparison_hash().
        if not getattr(self, 'read_only', False):
            self.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('structural_export_complete','true'))
            self.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('incidence_ready','true'))
            self.db.commit()
        return self.summary

    def prepare_sequence_evidence(self):
        """Build the expensive ON/OFF branch-pair evidence only when Supply starts."""
        if self.sequence_ready:
            return self.summary
        self.prepare_incidence_evidence()
        # Same conditional ON/OFF path-pair algebra; only the storage layout changed.
        query='''SELECT g.mode,g.orig,g.dest,g.path_index,g.gid,g.edge_ids,v.dseg,v.volume
            FROM geometry g JOIN driver_markets m ON m.mode=g.mode AND m.orig=g.orig AND m.dest=g.dest
            JOIN volumes v ON v.gid=g.gid WHERE v.volume>0
            ORDER BY g.mode,g.orig,g.dest,g.path_index,v.dseg'''
        market_count=0
        for market, rows in groupby(self.db.execute(query),key=lambda r:r[:3]):
            per_segment=defaultdict(list)
            last_gid=None;seq=None;mult=None
            for mode,o,d,ix,gid,blob,code,vol in rows:
                if gid!=last_gid:
                    seq=self._decode(blob);mult=Counter(seq);last_gid=gid
                per_segment[code].append({'pk':(code,o,d,ix),'seq':seq,'multiplicity':mult,'volume':vol})
            for code,routes in per_segment.items():
                mkey=(code,market[1],market[2])
                for i in self.drivers:
                    on=[r for r in routes if any(k in r['multiplicity'] for k in self.key_groups[i])]
                    if not on:continue
                    self.market_counts[i]+=1
                    self.support[i]+=sum(r['volume']*sum(r['multiplicity'].get(k,0) for k in self.key_groups[i]) for r in on)
                    if len(on)==len(routes):self.probe_only_counts[i]+=1
                self._add_pair_evidence(mkey,routes)
            market_count+=1
            if market_count%128==0:
                self.control.checkpoint('SEQUENCE_BRANCH_EVIDENCE',markets_completed=market_count)
        self.sequence_ready=True
        self.ready=True
        self.summary.update(status='COMPLETE_PROVISIONAL_DESIGN_ONLY',modes=self.mode_audits,
            export_complete=True,incidence_ready=True,sequence_evidence_ready=True,
            full_parent_keys_identical_within_mode=True,
            dseg_count=len(self.parents),dseg_complete_count=len(self.parents),
            all_selected_dsegs_complete=True,
            dseg_path_volume_parity_passes=all(r['passes'] for r in self.parity_rows),
            path_rows=sum(r['path_rows'] for r in self.parents.values()),
            positive_segment_paths=self.route_count,geometry_route_count=self.geometry_count,
            full_geometry_read_count=len(self.mode_audits),
            pathlink_rows=sum(a['geometry_link_children'] for a in self.mode_audits.values()),
            memory_strategy='TWO_MODE_UINT32_GEOMETRY_SQLITE_INDEPENDENT_DSEG_VOLUMES',
            new_assignment_executed=False,derived_design_provisional=True)
        if not getattr(self, 'read_only', False):
            self.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('sequence_evidence_ready','true'))
            self.db.commit()
        return self.summary

    def build_route_evidence(self):
        """Compatibility entry point preserving the original single-build guard."""
        if self.sequence_ready or self.ready:
            raise SupplyContractError('ROUTE_EVIDENCE_ALREADY_BUILT')
        return self.prepare_sequence_evidence()

    def finish(self):
        if not self.sequence_ready:
            raise SupplyContractError('MODE_CACHE_NOT_READY')
        if self._finished_proof is None:
            # Export parity is tied to the assignment that created this path
            # epoch, not to later live diagnostics rebound onto the frozen basis.
            parity=[]
            for i,row in enumerate(self.epoch_profiles):
                model=number(row['model'])
                diff=abs(self.flow[i]-model)
                tol=max(self.policy.parity_absolute_tolerance,
                        self.policy.parity_relative_tolerance*abs(model))
                parity.append({'id':self._profile_id(row),'role':row['role'],
                               'model':model,'actual_path_flow':self.flow[i],
                               'absolute_diff':diff,'passes':diff<=tol})
            if not all(row['passes'] for row in parity):
                raise SupplyContractError('ALL_PASSENGER_PATH_TO_PROFILE_FLOW_PARITY:PATH_EPOCH_ORIGIN')
            proof={'parent_hash':self.parent_hash,
                   'observation_authority_hash':self.authority_hash,
                   'assignment_path_hash':canonical_hash(self.batches),
                   'dseg_batches':self.batches,'profile_parity':parity,
                   'driver_count':len(self.drivers),
                   'uses_reconstructed_routes':False,
                   'parity_basis':'PATH_EPOCH_ORIGIN_ASSIGNMENT'}
            proof.update(path_store_route_count=self.route_count,
                path_store_type='NORMALIZED_TWO_MODE_SQLITE',
                unique_geometry_routes=self.geometry_count,
                unique_sequence_bundles=sum(len(x) for x in self.evidence.values()),
                skipped_branch_cases=dict(self.skipped_branches),
                geometry_identity=PROVISIONAL,
                pathlink_geometry_full_identity_proven=False,apply_permitted=False)
            self._finished_proof=proof
        return self._finished_proof

    def impact(self, changes, driver_idx, driver_support):
        """All stored geometry exposure x ALL 12 distinct segment volumes.

        Exact conditional on the provisional sharing assumption, NOT a flow
        prediction and NOT proof of native cross-DSeg geometry equivalence.
        """
        self.finish()
        if not changes:raise SupplyContractError('EMPTY_SEQUENCE_IMPACT')
        self.control.checkpoint('ALL_PATH_COLLATERAL_IMPACT',force=True)
        by_geometry=defaultdict(float)
        for change in changes:
            eid=self.edge_ids[tuple(change['key'])]
            delta=10.0*number(change['delta'])
            for (blob,) in self.db.execute('SELECT pairs FROM edge_postings WHERE eid=? ORDER BY chunk',(eid,)):
                data=_unpacked(zlib.decompress(blob))
                if len(data)%2:raise SupplyContractError('CORRUPT_EDGE_POSTINGS')
                for j in range(0,len(data),2):by_geometry[data[j]]+=delta*data[j+1]
                self.control.checkpoint()
        self.db.execute('DROP TABLE IF EXISTS temp.current_impact')
        self.db.execute('CREATE TEMP TABLE current_impact(gid INTEGER PRIMARY KEY,delta REAL)')
        self.db.executemany('INSERT INTO current_impact VALUES(?,?)',
                            ((gid,d) for gid,d in by_geometry.items() if abs(d)>1e-12))
        groups=defaultdict(lambda: {'routes':0,'volume':0.0,
            'volume_weighted_abs_seconds':0.0,'volume_weighted_signed_seconds':0.0})
        protected={'routes':0,'volume':0.0,'volume_weighted_abs_seconds':0.0}
        # CAL only; VALIDATION observations must not classify/rank proposals.
        calmap=defaultdict(set)
        for gid,i in self.db.execute('SELECT h.gid,h.profile_index FROM profile_hits h JOIN current_impact c ON c.gid=h.gid'):
            if i in self.cal_indices:calmap[gid].add(i)
        max_abs=0.0;count=0;by_dseg=defaultdict(lambda:{'routes':0,'volume':0.0,'volume_weighted_signed_seconds':0.0})
        for gid,delta,code,v in self.db.execute('SELECT c.gid,c.delta,v.dseg,v.volume FROM current_impact c JOIN volumes v ON v.gid=c.gid WHERE v.volume>0 ORDER BY c.gid,v.dseg'):
            count+=1;max_abs=max(max_abs,abs(delta));cal=calmap[gid]
            if cal & self.protected:
                protected['routes']+=1;protected['volume']+=v
                protected['volume_weighted_abs_seconds']+=v*abs(delta)
            label=('DRIVER_ON' if driver_idx in cal else 'OTHER_PROTECTED_CAL' if cal & self.protected
                   else 'OTHER_CAL' if cal else 'UNRELATED_TO_CAL')
            group=groups[label];group['routes']+=1;group['volume']+=v
            group['volume_weighted_abs_seconds']+=v*abs(delta)
            group['volume_weighted_signed_seconds']+=v*delta
            by_dseg[code]['routes']+=1;by_dseg[code]['volume']+=v
            by_dseg[code]['volume_weighted_signed_seconds']+=v*delta
            if count%4096==0:self.control.checkpoint('ALL_PATH_COLLATERAL_IMPACT',affected_paths=count)
        collateral=sum(groups.get(x,{}).get('volume',0.0) for x in ('OTHER_PROTECTED_CAL','OTHER_CAL','UNRELATED_TO_CAL'))
        return {'affected_routes':count,'max_abs_path_seconds':max_abs,
            'by_cal_class':dict(groups),'by_dseg':dict(by_dseg),
            'protected_cal_exposure_including_driver_overlap':protected,
            'collateral_to_support_ratio':collateral/max(driver_support,1e-9),
            'uses_validation_targets':False,'counterfactual_flow_prediction':False,
            'geometry_identity':PROVISIONAL,'conditional_on_geometry_sharing_assumption':True}

    def incidence(self, cfg, actuatable_zones, live_od_matrices=None):
        """Same core incidence algebra via normalized profile hits, no COM reread.

        Catalogs include zero-flow OD keys, just like the original core; there
        is no demand or profile selection hidden in this storage optimization.
        Optional cordon pairs are deliberately unsupported rather than guessed.
        """
        if not self.incidence_ready:raise SupplyContractError('MODE_CACHE_NOT_READY_FOR_GENERATION')
        if cfg.get('enable_kordon_pairs'):
            raise SupplyContractError('TWO_MODE_CORDON_INCIDENCE_NOT_IMPLEMENTED')
        self.control.checkpoint('GENERATION_INCIDENCE_FROM_CACHE',force=True)
        codes=[core.norm_code(c) for c in cfg['path_export_dsegs']]
        if set(codes)-set(self.parents):raise SupplyContractError('GENERATION_DSEG_MISSING_FROM_CACHE')
        mutable=set(core.norm_code(c) for c in cfg['mutable_dsegs'])
        active=set(actuatable_zones) if actuatable_zones is not None else None
        relation=cfg.get('mutable_relation_policy','BOTH_ENDPOINTS_ACTUATABLE')
        if relation not in ('BOTH_ENDPOINTS_ACTUATABLE','ALL_MUTABLE_RELATIONS'):
            raise SupplyContractError('UNSUPPORTED_MUTABLE_RELATION_POLICY')
        n=len(self.profiles); full=np.zeros(n); native=np.zeros(n); mod=np.zeros(n)
        variables=[];basevars=[];q=[];rr=[];cc=[];vv=[];shares=[]
        excluded_count=0;excluded_volume=0.0;excluded_od=0
        path_count=link_count=covered_count=0;total=covered=0.0
        zero_count=0;zero_volume=0.0
        live_od_matrices = ({core.norm_code(k):np.asarray(v,dtype=float)
                             for k,v in live_od_matrices.items()}
                            if live_od_matrices is not None else None)
        if live_od_matrices is not None and set(codes)-set(live_od_matrices):
            raise SupplyContractError('PATH_EPOCH_LIVE_OD_MATRIX_MISSING')
        zero_share_gap_rows=[]
        zero_share_live_interzonal={}
        for code in codes:
            self.control.checkpoint('GENERATION_INCIDENCE_FROM_CACHE',force=True,dseg_code=code)
            mutable_code=code in mutable and core.family_from_dseg(code) in ('WORK','SERVICE')
            totals=self.db.execute('SELECT COUNT(*),SUM(g.edge_count),SUM(CASE WHEN g.edge_count>0 THEN 1 ELSE 0 END) FROM volumes v JOIN geometry g ON g.gid=v.gid WHERE v.dseg=?',(code,)).fetchone()
            path_count+=totals[0];link_count+=totals[1] or 0;covered_count+=totals[2] or 0
            zero = self.db.execute('''SELECT COUNT(*) FROM volumes v
                JOIN geometry g ON g.gid=v.gid WHERE v.dseg=? AND g.edge_count=0''',(code,)).fetchone()
            zero_count += zero[0]
            # Aggregate per-OD profile traversal, preserving repeated edges and BOTH profiles.
            hit_query='''SELECT g.orig,g.dest,h.profile_index,SUM(v.volume*h.multiplicity)
                FROM volumes v JOIN geometry g ON g.gid=v.gid JOIN profile_hits h ON h.gid=g.gid
                WHERE v.dseg=? GROUP BY g.orig,g.dest,h.profile_index ORDER BY g.orig,g.dest,h.profile_index'''
            hit_iter=iter(self.db.execute(hit_query,(code,)));h=next(hit_iter,None)
            oq='''SELECT g.orig,g.dest,SUM(v.volume),COUNT(*),
                SUM(CASE WHEN g.edge_count>0 THEN v.volume ELSE 0 END),
                SUM(CASE WHEN g.edge_count=0 THEN v.volume ELSE 0 END)
                FROM volumes v JOIN geometry g ON g.gid=v.gid WHERE v.dseg=?
                GROUP BY g.orig,g.dest ORDER BY g.orig,g.dest'''
            counter=0
            live_matrix = live_od_matrices.get(code) if live_od_matrices is not None else None
            if live_matrix is not None:
                zero_share_live_interzonal[code] = float(np.sum(live_matrix) - np.trace(live_matrix))
                if (live_matrix.shape != (int(cfg['expected_zones']),int(cfg['expected_zones'])) or
                        not np.isfinite(live_matrix).all() or (live_matrix < -1e-10).any()):
                    raise SupplyContractError('PATH_EPOCH_INVALID_LIVE_OD_MATRIX:' + code)
                support = np.zeros(live_matrix.shape, dtype=bool)
                for so,sd in self.db.execute('''SELECT DISTINCT g.orig,g.dest FROM volumes v
                    JOIN geometry g ON g.gid=v.gid WHERE v.dseg=?''',(code,)):
                    support[int(so)-1,int(sd)-1] = True
                # Intrazonal (diagonal) OD has no network path geometry by
                # definition and is excluded from the path-based link-incidence
                # authority.  V2.4.7 treated a positive diagonal cell as a
                # missing path and forced an endless re-enumeration attempt.
                # Only positive OFF-DIAGONAL relations require frozen path
                # support.  This matches the existing OFFDIAGONAL_INTERZONAL
                # parity contract used for path export/application gates.
                positive_offdiag = (live_matrix > core.EPS).copy()
                np.fill_diagonal(positive_offdiag, False)
                missing = np.argwhere(positive_offdiag & ~support)
                if len(missing):
                    mo,md = missing[0]
                    raise SupplyContractError(
                        'PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:%s:%s:%s' %
                        (code,int(mo)+1,int(md)+1))
            for o,d,stored_vol,npaths,stored_covered,stored_zero in self.db.execute(oq,(code,)):
                stored_vol=float(stored_vol or 0.0)
                stored_covered=float(stored_covered or 0.0)
                stored_zero=float(stored_zero or 0.0)
                vol=(float(live_matrix[o-1,d-1]) if live_matrix is not None else stored_vol)
                if stored_vol <= core.EPS and vol > core.EPS:
                    zero_share_gap = int(o) != int(d)
                    if zero_share_gap:
                        zero_share_gap_rows.append({'dseg':code,'origin':int(o),'destination':int(d),
                                                    'live_volume':vol,'epoch_volume':stored_vol,
                                                    'path_count':int(npaths)})
                    # Diagonal demand has no network-link attribution.  A
                    # diagonal parent row, if present, contributes zero path
                    # incidence rather than requiring a route split.
                    scale=0.0
                else:
                    scale=vol/stored_vol if stored_vol>core.EPS else 0.0
                total+=vol
                covered+=stored_covered*scale
                zero_volume+=stored_zero*scale
                act=relation=='ALL_MUTABLE_RELATIONS' or active is None or (o in active and d in active)
                # A live-positive relation whose enumerated DSeg path rows all have
                # zero saved volume has geometry but no defensible frozen route
                # split.  It may contribute to projection base marginals, but it
                # must never become a path-guidance actuator unless a share exists.
                if stored_vol <= core.EPS and vol > core.EPS and int(o) != int(d):
                    act=False
                vi=None
                if mutable_code:
                    meta={'dseg_code':code,'family':core.family_from_dseg(code),'origin':o,
                        'destination':d,'q_current':vol,'path_count':npaths,'actuatable_relation':int(act)}
                    basevars.append(dict(meta,base_variable_index=len(basevars)))
                    if act:
                        vi=len(variables);variables.append(dict(meta,variable_index=vi));q.append(vol)
                    else:
                        excluded_count+=npaths;excluded_volume+=vol;excluded_od+=1
                while h is not None and (h[0],h[1])==(o,d):
                    _,_,pi,through=h;through=float(through)*scale
                    full[pi]+=through
                    if mutable_code:native[pi]+=through
                    if vi is not None:
                        mod[pi]+=through
                        if vol>core.EPS:
                            rr.append(pi);cc.append(vi);vv.append(through);shares.append(through/vol)
                    h=next(hit_iter,None)
                counter+=1
                if counter%4096==0:self.control.checkpoint('GENERATION_INCIDENCE_FROM_CACHE',od_rows=counter)
            if h is not None:raise SupplyContractError('CACHE_INCIDENCE_JOIN_FAILED')
        zero_share_audit={
            'policy':'NONE', 'accepted':True, 'row_count':0, 'volume':0.0,
            'max_single_od_volume':0.0, 'by_dseg':{}, 'sample_rows':[]}
        if zero_share_gap_rows:
            policy=cfg.get('two_mode',{}).get('zero_share_residual_policy',{})
            if policy.get('enabled') is not True:
                first=zero_share_gap_rows[0]
                raise SupplyContractError('PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:%s:%s:%s' %
                                          (first['dseg'],first['origin'],first['destination']))
            if self.summary.get('dseg_path_volume_parity_passes') is not True:
                raise SupplyContractError('PATH_EPOCH_ZERO_SHARE_RESIDUAL_REQUIRES_PATH_PARITY_PASS')
            limit=float(policy.get('max_dseg_relative_volume',cfg.get('dseg_path_volume_relative_tolerance',0.01)))
            if not (0.0 < limit <= float(cfg.get('dseg_path_volume_relative_tolerance',0.01))):
                raise SupplyContractError('PATH_EPOCH_ZERO_SHARE_RESIDUAL_INVALID_TOLERANCE')
            grouped=defaultdict(lambda:{'rows':0,'volume':0.0,'max_single_od_volume':0.0})
            for row in zero_share_gap_rows:
                g=grouped[row['dseg']]; g['rows']+=1; g['volume']+=float(row['live_volume'])
                g['max_single_od_volume']=max(g['max_single_od_volume'],float(row['live_volume']))
            offenders=[]; by_dseg={}
            for code,g in sorted(grouped.items()):
                denom=max(core.EPS,float(zero_share_live_interzonal.get(code,0.0)))
                rel=float(g['volume'])/denom
                by_dseg[code]=dict(g,live_interzonal_volume=denom,relative_volume=rel,limit=limit)
                if rel > limit + 1e-15: offenders.append((code,rel,float(g['volume'])))
            if offenders:
                code,rel,vol=offenders[0]
                raise SupplyContractError('PATH_EPOCH_NEW_POSITIVE_OD_REQUIRES_REENUMERATION:%s:%s:%s:ZERO_SHARE_RESIDUAL_EXCEEDS_GUIDANCE_TOLERANCE:%.12g:%.12g' %
                                          (code,zero_share_gap_rows[0]['origin'],zero_share_gap_rows[0]['destination'],rel,vol))
            zero_share_audit={
                'policy':'EXISTING_GEOMETRY_ZERO_SHARE_RESIDUAL_EXCLUDED_FROM_GUIDANCE_PRESERVE_BASE_MARGINS',
                'accepted':True, 'row_count':len(zero_share_gap_rows),
                'volume':float(sum(float(r['live_volume']) for r in zero_share_gap_rows)),
                'max_single_od_volume':float(max(float(r['live_volume']) for r in zero_share_gap_rows)),
                'by_dseg':by_dseg, 'sample_rows':zero_share_gap_rows[:100],
                'acceptance_authority':'FRESH_VISUM_ASSIGNMENT_PLUS_LIVE_12D_11D'}
        profiles=[]
        for i,p in enumerate(self.profiles):
            x=dict(p,_profile_index=i,_link_key=core._profile_link_key(p),_link_keys=core._profile_link_keys(p));profiles.append(x)
        values=np.array(vv,dtype=float)
        result={'profiles':profiles,'variables':variables,'projection_base_variables':basevars,
            'q_current':np.array(q,dtype=float),
            'incidence':core.SparseOperator(np.array(rr,dtype=np.int64),np.array(cc,dtype=np.int64),values,n,len(q)),
            'incidence_share':np.array(shares,dtype=float),'incidence_through':values,
            'full_profile_model_from_paths':full,'native_ws_profile_model_from_paths':native,
            'mutable_profile_model_from_paths':mod,
            'path_summary':{'input_rows':path_count,'normalized_paths':path_count,'invalid_rows':0,
                            'negative_volume_rows':0,'total_path_volume':total},
            'path_count':path_count,'pathlink_count':link_count,'paths_with_link_rows':covered_count,
            'path_link_coverage':covered_count/(path_count-zero_count) if path_count>zero_count else 1.0,
            'total_path_volume':total, 'covered_path_volume':covered,
            'path_link_volume_coverage':covered/(total-zero_volume) if total-zero_volume>core.EPS else 1.0,
            'raw_all_path_link_coverage':covered_count/max(1,path_count),
            'raw_all_path_link_volume_coverage':covered/total if total>core.EPS else 0.0,
            'zero_link_path_count':zero_count, 'zero_link_path_volume':zero_volume,
            'link_effect_path_count':path_count-zero_count,
            'link_effect_path_volume':total-zero_volume,
            'coverage_basis':'LINK_EFFECT_PATHS_EXPLICIT_ZERO_LINK_EXCLUDED_ONLY_FROM_COVERAGE_DENOMINATOR',
            'orphan_pathlink_rows':0,'invalid_pathlink_rows':0,'variable_count':len(q),
            'projection_base_variable_count':len(basevars),'incidence_nnz':len(vv),
            'actuator_scope':{'mutable_relation_policy':relation,'actuatable_zone_count':len(active) if active is not None else None,
                'excluded_mutable_path_count':excluded_count,'excluded_mutable_path_volume':excluded_volume,
                'excluded_mutable_od_count':excluded_od},
            'pair_observations':{'enabled':False,'observations':[], 'row_idx':np.zeros(0,dtype=np.int64),
                'col_idx':np.zeros(0,dtype=np.int64),'values':np.zeros(0), 'full_model':np.zeros(0),
                'mutable_model':np.zeros(0),'wiggly_skipped_paths':0},
            'geometry_identity':PROVISIONAL,'provisional':True,'apply_permitted':False,
            'path_epoch_live_od_reweighted':live_od_matrices is not None,
            'intrazonal_path_support_policy':'NO_NETWORK_PATH_REQUIRED_EXCLUDED_FROM_PATH_INCIDENCE',
            'zero_share_residual_audit':zero_share_audit}
        summary=dict(self.summary,dsegs=codes,
            source=('FROZEN_PATH_EPOCH_LIVE_OD_REWEIGHT_NO_COM_REEXPORT'
                    if live_od_matrices is not None else 'SAME_RUN_TWO_MODE_SQLITE_CACHE_NO_COM_REEXPORT'))
        return result,summary


def check_geometry_samples(visum, groups, settings, control):
    audits={}
    windows=settings['sample_windows']
    if not windows:raise SupplyContractError('LIVE_GEOMETRY_SAMPLES_REQUIRED')
    for mode,segments in groups.items():
        expected=None
        mode_audit={'dsegs':{},'full_geometry_identity_proven':False}
        for ds in segments:
            control.checkpoint('SAME_RUN_GEOMETRY_SAMPLES',force=True,dseg_code=ds['code'],mode=mode)
            obj=create_list(visum,'CreatePrTPathLinkList',ds['code'])
            ole,memid,kind=rt.verified_bounded_signature(obj)
            fingerprints={}
            for first,last in windows:
                if int(first)<1 or int(last)<int(first) or int(last)-int(first)+1>256:
                    raise SupplyContractError('INVALID_BOUNDED_GEOMETRY_WINDOW')
                def retry_observer(event):
                    control.checkpoint(
                        'SAME_RUN_GEOMETRY_SAMPLES', force=True,
                        dseg_code=ds['code'], mode=mode,
                        bounded_range_first=int(first), bounded_range_last=int(last),
                        com_retry_event=event)
                def exhausted_observer(event):
                    control.checkpoint(
                        'SAME_RUN_GEOMETRY_SAMPLES', force=True,
                        dseg_code=ds['code'], mode=mode,
                        bounded_range_first=int(first), bounded_range_last=int(last),
                        com_retry_event=event, com_retry_exhausted=True,
                        com_retry_hresult=event.get("hresult"))
                raw = com.bounded_ole_invoke_with_retry(
                    ole, memid, kind, int(first), int(last),
                    retry_policy=settings.get("com_retry_policy"),
                    label="GEOMETRY_SAMPLE:%s:%s" % (mode, ds['code']),
                    on_retry=retry_observer, on_exhausted=exhausted_observer)
                raw=[] if raw is None else raw
                if len(raw)>last-first+1:raise SupplyContractError('GEOMETRY_SAMPLE_TOO_LARGE')
                norm=[]
                for row in raw:
                    if len(row)!=7:raise SupplyContractError('GEOMETRY_SAMPLE_SCHEMA')
                    norm.append([_id(x) if _filled(x) else None for x in row])
                fingerprints['%d-%d'%(first,last)]={'rows':len(norm),'sha256':canonical_hash(norm)}
            if not any(r['rows'] for r in fingerprints.values()):
                raise SupplyContractError('EMPTY_GEOMETRY_SAMPLES')
            if expected is not None and fingerprints!=expected:
                raise SupplyContractError('SAME_MODE_GEOMETRY_SAMPLE_MISMATCH:' + ds['code'])
            expected=fingerprints;mode_audit['dsegs'][ds['code']]=fingerprints
            del ole,obj
        mode_audit['sample_windows_equal']=True;audits[mode]=mode_audit
    return audits


def collect_two_modes(visum, collector, cfg, folder, *, build_sequence_evidence=True):
    """Build a new cache only from the current injected instance and snapshot."""
    if cfg.get('apply') is not False:
        raise SupplyContractError('EXPERIMENTAL_MODE_CACHE_FORBIDS_APPLY')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    settings=collector.settings;control=collector.control
    path_cfg=dict(cfg,path_export_dsegs=cfg['supply']['passenger_dsegs'])
    dsrows=rt.selected_passenger_dsegs(visum,path_cfg)
    expected={core.norm_code(c) for c in cfg['supply']['passenger_dsegs']}
    if expected!=set().union(*EXPECTED_MODE_DSEGS.values()):
        raise SupplyContractError('APPROVED_12_PASSENGER_DSEG_CONTRACT_CHANGED')
    if len(dsrows)!=len(expected) or {r['norm_code'] for r in dsrows}!=expected:
        raise SupplyContractError('EXACT_PASSENGER_SCOPE_REQUIRED')
    groups=defaultdict(list)
    for ds in dsrows:
        mode=core.norm_code(ds['mode'])
        if mode not in ('C','C_NOT'):raise SupplyContractError('UNSUPPORTED_LIVE_MODE:' + mode)
        groups[mode].append(ds)
    if set(groups)!=set(settings['representatives']):
        raise SupplyContractError('EXACT_TWO_MODE_SCOPE_REQUIRED')
    for mode,group in groups.items():
        if {d['norm_code'] for d in group}!=EXPECTED_MODE_DSEGS[mode]:
            raise SupplyContractError('APPROVED_DSEG_MODE_MEMBERSHIP_CHANGED')
        rep=core.norm_code(settings['representatives'][mode])
        if rep not in {d['norm_code'] for d in group}:
            raise SupplyContractError('REPRESENTATIVE_DSEG_NOT_IN_LIVE_MODE')
        group.sort(key=lambda d:(d['norm_code']!=rep,d['norm_code']))
    try:
        collector.check_resources(force=True)
        for mode in sorted(groups):
            for ds in groups[mode]:
                control.checkpoint('PARENTS_AND_VOLUMES',force=True,dseg_code=ds['code'],mode=mode)
                authority=read_matrix_authority(ds,int(cfg['expected_zones']))
                obj=create_list(visum,'CreatePrTPathList',ds['code'])
                rows=bounded_rows(obj,PARENT_COLUMNS,settings,control,'PARENTS_AND_VOLUMES',dseg_code=ds['code'],mode=mode)
                collector.add_parents(ds['code'],mode,rows,authority)
                del rows,obj
                rt.write_csv(folder/'03D_DSEG_PATH_VOLUME_PARITY.csv',collector.parity_rows)
        samples=check_geometry_samples(visum,groups,settings,control)
        atomic_json(folder/'TWO_MODE_GEOMETRY_SAMPLE_QA.json',samples)
        for mode in sorted(groups):
            ds=groups[mode][0]
            control.checkpoint('REPRESENTATIVE_GEOMETRY',force=True,mode=mode,dseg_code=ds['code'])
            obj=create_list(visum,'CreatePrTPathLinkList',ds['code'])
            rows=bounded_rows(obj,GEOMETRY_COLUMNS,settings,control,'REPRESENTATIVE_GEOMETRY',mode=mode,dseg_code=ds['code'])
            collector.add_geometry(mode,rows)
            del rows,obj
        # Check all 12 matrices again. No stale-matrix reuse across a long export.
        for ds in dsrows:
            control.checkpoint('FINAL_MATRIX_FINGERPRINT_CHECK',dseg_code=ds['code'])
            after=read_matrix_authority(ds,int(cfg['expected_zones']))
            if after!= {k:collector.parents[ds['norm_code']][k] for k in after}:
                raise SupplyContractError('MATRIX_CHANGED_DURING_MODE_CACHE_BUILD:' + ds['code'])
        summary=(collector.prepare_sequence_evidence() if build_sequence_evidence
                 else collector.prepare_incidence_evidence())
        summary['same_run_geometry_samples_equal']=True
        collector.summary=summary
        return summary
    except BaseException as exc:
        collector.ready=False
        collector.incidence_ready=False
        collector.sequence_ready=False
        collector.summary.update(status='STOPPED' if getattr(exc,'stop_design_run',False) else 'FAILED',
            fatal_errors=[type(exc).__name__+': '+str(exc)],all_selected_dsegs_complete=False)
        raise
    finally:
        rt.write_csv(folder/'03D_DSEG_PATH_VOLUME_PARITY.csv',collector.parity_rows)
        rt.write_csv(folder/'03B_DSEG_PATH_EXPORT_STATUS.csv',list(collector.parents.values()))
        collector.summary['modes']=collector.mode_audits
        atomic_json(folder/'03A_PATH_EXPORT_SUMMARY.json',collector.summary)
        atomic_json(folder/'TWO_MODE_CACHE_AUDIT.json',collector.summary)
        gc.collect()
