"""Private MEMORY/OFF build -> checked, hash-bound, atomic read-only publication.

This is a same-run local cache. Existing cross-run authorization is unchanged;
the historical persistent manager, if enabled, keeps its original FULL path.
Only the V24917 adapter's scoped build may request the private fast constructor.
"""
from __future__ import annotations

from contextvars import ContextVar
import copy
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import time
import uuid

import r1_15a2_two_mode_v238 as paths
import r1_15a2_path_export_probe_v24917 as probe
import r1_15a2_path_store_build_v24917 as builder

RELEASE = 'R1_PATH_CACHE_ATOMIC_PUBLISH1_20261030'
STORE = 'TWO_MODE_PATH_STORE.sqlite'
MANIFEST = 'PATH_CACHE_MANIFEST.json'
_SCOPE = ContextVar('r1_path_cache_build_scope', default=None)
DEFAULTS = {'fast_staging': False, 'page_probe': False,
            'probe_candidates': [256, 2048, 4096, 8192, 16384],
            'probe_starts': [1, 65537], 'probe_repetitions': 2, 'probe_memory_mib': 128.}


def options(root=None, environ=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    path = root / 'R1_RUN_OPTIONS.json'
    raw = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    if not isinstance(raw, dict) or not isinstance(raw.get('path_io', {}), dict):
        raise ValueError('PATH_IO_OPTIONS_NOT_OBJECT')
    raw = raw.get('path_io', {})
    if set(raw) - set(DEFAULTS):
        raise ValueError('PATH_IO_UNKNOWN_OPTIONS:' + repr(sorted(set(raw) - set(DEFAULTS))))
    out = dict(DEFAULTS, **raw)
    environ = os.environ if environ is None else environ
    for key, name in (('fast_staging', 'R1_PATH_STORE_FAST_STAGING'),
                      ('page_probe', 'R1_PATH_EXPORT_PAGE_PROBE')):
        value = str(environ.get(name, '')).strip().lower()
        if value:
            if value not in ('1', '0', 'true', 'false'):
                raise ValueError('PATH_IO_INVALID_ENV_BOOLEAN:' + name)
            out[key] = value in ('1', 'true')
    for key in ('fast_staging', 'page_probe'):
        if type(out[key]) is not bool:
            raise ValueError('PATH_IO_BOOLEAN_REQUIRED:' + key)
    for key, maximum in (('probe_candidates', probe.MAX_PAGE), ('probe_starts', 1000000000)):
        values = out[key]
        if not isinstance(values, list) or not 1 <= len(values) <= 8:
            raise ValueError('PATH_IO_INVALID_LIST:' + key)
        values = [paths.com.exact_int(v, key) for v in values]
        if min(values) < 1 or max(values) > maximum or len(set(values)) != len(values):
            raise ValueError('PATH_IO_INVALID_RANGE:' + key)
        out[key] = values
    out['probe_repetitions'] = paths.com.exact_int(out['probe_repetitions'], 'PROBE_REPETITIONS')
    out['probe_memory_mib'] = paths.com.finite_float(out['probe_memory_mib'], 'PROBE_MEMORY_MIB')
    if not 1 <= out['probe_repetitions'] <= 5 or not 1 <= out['probe_memory_mib'] <= 1024:
        raise ValueError('PATH_IO_INVALID_PROBE_BUDGET')
    return out


def _sha(path, control=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for i, block in enumerate(iter(lambda: f.read(1024 ** 2), b'')):
            digest.update(block)
            if control is not None and i % 16 == 0:
                control.checkpoint('PATH_CACHE_PUBLICATION_SHA256', hashed_mib=i + 1)
    return digest.hexdigest()


def _fsync_dir(path):
    # Python cannot open a Windows directory for fsync. Files are always flushed;
    # the receipt explicitly states this platform limit instead of promising a
    # power-loss-durable directory rename on Windows/network file systems.
    if os.name == 'nt':
        return 'NOT_AVAILABLE_ON_WINDOWS_FILES_FSYNCED'
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return 'FSYNCED'


def _write_manifest(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())


def _readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA temp_store=MEMORY')
        # Main DB writes are denied by mode=ro. query_only=ON would also deny
        # Supply's required CREATE TEMP TABLE current_impact and break proposals.
        return db
    except BaseException:
        db.close()
        raise


def _published_manifest(path):
    """Verify fast-cache publication; a source SHA alone is not reuse permission."""
    path = Path(path)
    if any(p.name.startswith('.UNPUBLISHED_PATH_CACHE_') for p in path.parents):
        raise paths.SupplyContractError('PATH_CACHE_UNPUBLISHED_OPEN_FORBIDDEN')
    if not path.is_file() or path.stat().st_size <= 0:
        return None  # Preserve the historical missing/empty-store error.
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        marker = db.execute("SELECT value FROM metadata WHERE key='path_cache_publication_state'").fetchone()
    finally:
        db.close()
    if marker is None:
        return None  # Historical stores retain their original authorization.
    manifest_path = path.parent / MANIFEST
    if marker[0] != 'PUBLISHED' or not manifest_path.is_file():
        raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_MANIFEST_REQUIRED')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('schema') != RELEASE or manifest.get('store_file') != path.name
            or manifest.get('manifest_sha256') != paths.canonical_hash(
                {k: v for k, v in manifest.items() if k != 'manifest_sha256'})
            or manifest.get('store_bytes') != path.stat().st_size
            or manifest.get('store_sha256') != _sha(path)):
        raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_MANIFEST_OR_SHA_MISMATCH')
    return manifest


def _semantic(collector, codes):
    collector.prepare_incidence_evidence()
    if (set(collector.parents) != {paths.core.norm_code(c) for c in codes}
            or not collector.export_complete or not collector.incidence_ready
            or not collector.summary.get('all_selected_dsegs_complete')
            or not all(a['passes'] for a in collector.parents.values())
            or not all(a.get('geometry_complete') for a in collector.mode_audits.values())):
        raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_INCOMPLETE_EXPORT')
    metadata = dict(collector.db.execute('SELECT key,value FROM metadata'))
    if metadata.get('schema') != paths.SCHEMA:
        raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_SCHEMA')
    if metadata.get('structural_export_complete') != 'true' or metadata.get('incidence_ready') != 'true':
        raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_MISSING_COMPLETION_MARKERS')
    stored_audits = {code: json.loads(value) for code, value in collector.db.execute(
        'SELECT dseg,audit_json FROM segments')}
    if stored_audits != collector.parents or metadata.get('parent_hash') != collector.parent_hash:
        raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_STORED_AUTHORITY')
    # Verify actual stored volume bytes against the source hashes, rather than
    # treating in-memory completion counters as proof of what SQLite contains.
    for code, audit in collector.parents.items():
        key_hash, volume_hash = hashlib.sha256(), hashlib.sha256()
        count = 0
        for o, d, ix, vol in collector.db.execute('''
                SELECT g.orig,g.dest,g.path_index,v.volume FROM geometry g
                JOIN volumes v ON v.gid=g.gid AND v.dseg=? WHERE g.mode=?
                ORDER BY g.orig,g.dest,g.path_index''', (code, audit['mode'])):
            key_hash.update(struct.pack('<III', o, d, ix))
            volume_hash.update(struct.pack('<IIId', o, d, ix, vol))
            count += 1
            if count % 8192 == 0:
                collector.control.checkpoint('PATH_CACHE_VERIFY_VOLUMES', dseg_code=code, rows=count)
        expected = collector._path_sql_volume_hashes[code]
        if (count != audit['path_rows'] or key_hash.hexdigest() != audit['parent_keys_sha256']
                or volume_hash.hexdigest() != expected):
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_STORED_VOLUME_HASH:' + code)
    for mode, audit in collector.mode_audits.items():
        geometry_hash = hashlib.sha256()
        checked = 0
        for o, d, ix, blob, count, digest, kind in collector.db.execute('''
                SELECT orig,dest,path_index,edge_ids,edge_count,sequence_sha256,geometry_kind
                FROM geometry WHERE mode=? ORDER BY orig,dest,path_index''', (mode,)):
            expected_kind = ('LINK_SEQUENCE' if count else
                'ZERO_LINK_INTRAZONAL_NO_ADDVAL1_EFFECT' if o == d else
                'ZERO_LINK_INTERZONAL_NO_ADDVAL1_EFFECT')
            if (blob is None or len(blob) != count * 4 or hashlib.sha256(blob).hexdigest() != digest
                    or kind != expected_kind):
                raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_STORED_GEOMETRY_HASH')
            geometry_hash.update(struct.pack('<III', o, d, ix)); geometry_hash.update(digest.encode('ascii'))
            checked += 1
            if checked % 8192 == 0:
                collector.control.checkpoint('PATH_CACHE_VERIFY_GEOMETRY', mode=mode, rows=checked)
        if geometry_hash.hexdigest() != audit['representative_geometry_sha256']:
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_MODE_GEOMETRY_HASH')
    flow = [0.] * len(collector.profiles)
    for i, value in collector.db.execute('''SELECT h.profile_index,SUM(v.volume*h.multiplicity)
            FROM profile_hits h JOIN volumes v ON v.gid=h.gid GROUP BY h.profile_index'''):
        if not 0 <= i < len(flow):
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_PROFILE_INDEX')
        flow[i] = value
    if flow != collector.flow:
        raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_STORED_PROFILE_FLOW')
    profile_rows = []
    for i, row in enumerate(collector.epoch_profiles):
        model = paths.number(row['model'])
        actual = paths.number(collector.flow[i])
        tolerance = max(collector.policy.parity_absolute_tolerance,
                        collector.policy.parity_relative_tolerance * abs(model))
        if abs(actual - model) > tolerance:
            raise paths.SupplyContractError('ALL_PASSENGER_PATH_TO_PROFILE_FLOW_PARITY:PATH_CACHE_PUBLICATION')
        profile_rows.append((collector._profile_id(row), model, actual))
    counts = {table: collector.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
              for table in ('segments', 'geometry', 'volumes', 'edges', 'profile_hits', 'edge_postings')}
    if (counts['segments'] != len(collector.parents)
            or counts['geometry'] != collector.geometry_count
            or counts['volumes'] != sum(a['path_rows'] for a in collector.parents.values())
            or collector.db.execute('SELECT COUNT(*) FROM geometry WHERE edge_ids IS NULL OR edge_count IS NULL').fetchone()[0]):
        raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_ROW_COUNTS')
    return {'parent_hash': collector.parent_hash, 'schema': paths.SCHEMA, 'counts': counts,
            'profile_order_hash': paths.canonical_hash([collector._profile_id(r) for r in collector.profiles]),
            'observation_authority_hash': collector.authority_hash,
            'profile_origin_parity_hash': paths.canonical_hash(profile_rows),
            'path_structure_hash': collector.path_structure_hash(),
            'path_basis_hash': collector.path_basis_hash(),
            'path_basis_comparison_hash': collector.path_basis_comparison_hash()}


class BuildScope:
    def __init__(self, adapter, folder, snapshot, opts):
        self.adapter, self.folder, self.snapshot, self.opts = adapter, Path(folder), copy.deepcopy(snapshot), opts
        self.fast = opts['fast_staging'] and not adapter.persistent_path_cache.enabled
        self.staging = self.destination = self.collector = None
        self.retirement = None
        self.page_report = None
        self.published = False
        self.completed = False

    def construct(self, original, collector, args, kwargs):
        if self.collector is not None:
            raise paths.SupplyContractError('PATH_CACHE_MULTIPLE_BUILDERS_IN_SCOPE')
        # Original signature: profiles, policy, parent_hash, links, db_path,...
        args = list(args)
        requested = Path(args[4] if len(args) > 4 else kwargs['db_path'])
        if self.fast:
            token = uuid.uuid4().hex
            self.staging = requested.parent / ('.UNPUBLISHED_PATH_CACHE_' + token)
            self.destination = requested.parent / ('PATH_CACHE_' + token)
            self.staging.mkdir(exist_ok=False)
            target = self.staging / STORE
            if len(args) > 4: args[4] = target
            else: kwargs = dict(kwargs, db_path=target)
        original(collector, *args, **kwargs)
        self.collector = collector
        try:
            if self.fast:
                # Keep the sealed constructor/schema (one initial FULL commit).
                # Only the unpublished bulk-load phase uses MEMORY/OFF. MEMORY
                # preserves logical SQL rollback unlike journal_mode=OFF.
                mode = collector.db.execute('PRAGMA journal_mode=MEMORY').fetchone()[0]
                collector.db.execute('PRAGMA synchronous=OFF')
                if mode != 'memory' or collector.db.execute('PRAGMA synchronous').fetchone()[0] != 0:
                    raise paths.SupplyContractError('PATH_CACHE_FAST_PRAGMAS_NOT_APPLIED')
                collector.db.execute('INSERT INTO metadata VALUES(?,?)',
                                     ('path_cache_publication_state', 'UNPUBLISHED'))
                collector.db.commit()
            size = int(collector.settings['page_size'])
            if self.opts['page_probe']:
                before = self.adapter.snapshot()
                if before != self.snapshot:
                    raise paths.SupplyContractError('PATH_PAGE_PROBE_PARENT_CHANGED_BEFORE')
                self.page_report = probe.benchmark(self.adapter.visum, collector.settings, collector.control,
                    candidates=self.opts['probe_candidates'], starts=self.opts['probe_starts'],
                    repetitions=self.opts['probe_repetitions'], memory_limit_mib=self.opts['probe_memory_mib'])
                if self.adapter.snapshot() != before:
                    raise paths.SupplyContractError('PATH_PAGE_PROBE_PARENT_CHANGED_AFTER')
                size = self.page_report['selected_page_size']
                self.page_report['snapshot_hash'] = paths.canonical_hash(before)
            else:
                self.page_report = {'selected_page_size': size, 'probe_enabled': False,
                                    'runtime_page_fallback': False}
            collector.settings['path_export_fixed_page_size'] = size
            collector.settings['path_export_page_stats'] = {}
            collector.summary['path_export_pages'] = collector.settings['path_export_page_stats']
            if self.fast:
                collector.settings['path_cache_verify_sql'] = True
                builder._stats(collector).update(journal_mode='MEMORY', synchronous='OFF',
                                                unpublished_only=True)
            paths.atomic_json(self.folder / 'PATH_EXPORT_PAGE_PROFILE.json', self.page_report)
        except BaseException:
            collector.close()
            raise

    def publish(self, collector):
        if collector is not self.collector or self.staging is None:
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_BUILDER_MISMATCH')
        started = time.perf_counter()
        collector.control.checkpoint('PATH_CACHE_PUBLICATION_CHECKS', force=True)
        semantic = _semantic(collector, self.adapter.cfg['supply']['passenger_dsegs'])
        collector.db.commit()
        # Required unique/primary indexes and FKs were kept throughout loading.
        # No secondary index is deferred unless an actual consumer needs it.
        for key, value in semantic.items():
            if key.endswith('_hash'):
                collector.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, value))
        collector.db.execute('UPDATE metadata SET value=? WHERE key=?',
                             ('PUBLISHED', 'path_cache_publication_state'))
        collector.db.commit()
        integrity = [r[0] for r in collector.db.execute('PRAGMA integrity_check')]
        if integrity != ['ok'] or list(collector.db.execute('PRAGMA foreign_key_check')):
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_SQLITE_INTEGRITY')
        collector.db.execute('PRAGMA journal_mode=DELETE')
        collector.db.execute('PRAGMA synchronous=FULL')
        collector.db.close()  # Preserve in-memory evidence/readiness on this object.
        store = self.staging / STORE
        with store.open('r+b') as f:
            os.fsync(f.fileno())
        collector.control.checkpoint('PATH_CACHE_PUBLICATION_SHA256', force=True, bytes=store.stat().st_size)
        digest = _sha(store, collector.control)
        stat = store.stat()
        manifest = {'schema': RELEASE, 'store_file': STORE, 'store_sha256': digest,
            'store_bytes': stat.st_size, 'semantic': semantic, 'sqlite_integrity': 'ok',
            'foreign_key_violations': 0, 'secondary_indexes_deferred': False,
            'page_profile': self.page_report, 'same_run_only': True,
            'main_database': 'IMMUTABLE_READ_ONLY', 'temporary_tables': 'MEMORY_WRITABLE',
            'directory_fsync': 'UNAVAILABLE_WINDOWS' if os.name == 'nt' else 'SUPPORTED'}
        manifest['manifest_sha256'] = paths.canonical_hash(manifest)
        _write_manifest(self.staging / MANIFEST, manifest)
        _fsync_dir(self.staging)
        # This can be a long hash/check pass: recheck live parent immediately
        # before publication, not just before the export or before hashing.
        if self.adapter.snapshot() != self.snapshot:
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_LIVE_PARENT_CHANGED')
        if self.destination.exists():
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_DESTINATION_EXISTS')
        collector.control.checkpoint('PATH_CACHE_ATOMIC_RENAME', force=True)
        os.rename(str(self.staging), str(self.destination))
        self.published = True
        _fsync_dir(self.destination.parent)
        final = self.destination / STORE
        after = final.stat()
        if (stat.st_size, stat.st_ino, stat.st_mtime_ns) != (after.st_size, after.st_ino, after.st_mtime_ns):
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_FILE_IDENTITY_CHANGED')
        readback = json.loads((self.destination / MANIFEST).read_text(encoding='utf-8'))
        if readback != manifest:
            raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_MANIFEST_READBACK')
        collector.db = _readonly(final)
        collector.read_only = True
        collector.route_db_path = str(final)
        collector.summary['path_cache_publication'] = {
            'published': True, 'store_sha256': digest, 'store_bytes': after.st_size,
            'manifest': str(self.destination / MANIFEST), 'seconds': time.perf_counter() - started,
            'main_read_only': True, 'same_run_only': True}
        paths.atomic_json(self.folder / 'PATH_CACHE_PUBLICATION.json', collector.summary['path_cache_publication'])
        return manifest

    def cleanup(self):
        if self.staging is not None and self.staging.exists():
            shutil.rmtree(self.staging)


def defer_retirement(adapter, store_path, audit_folder):
    scope = _SCOPE.get()
    if scope is None or scope.adapter is not adapter or not scope.fast:
        return None
    scope.retirement = (store_path, audit_folder)
    return {'retired': False, 'reason': 'DEFERRED_UNTIL_ATOMIC_PATH_CACHE_PUBLICATION'}


def run_build(adapter, folder, snapshot, callback):
    builder.install()
    install()
    opts = options()
    scope = BuildScope(adapter, folder, snapshot, opts)
    token = _SCOPE.set(scope)
    try:
        result = callback()
        collector, links, export = result
        if scope.fast:
            scope.publish(collector)
            # Update audit summaries written by the historical collector while
            # it was still unpublished, then retire the old payload LAST.
            for name in ('TWO_MODE_CACHE_AUDIT.json', '03A_PATH_EXPORT_SUMMARY.json'):
                paths.atomic_json(Path(folder) / name, collector.summary)
        scope.completed = True
        return collector, links, export
    except BaseException as exc:
        if scope.collector is not None:
            try:
                scope.collector.close()
            finally:
                if getattr(adapter, 'cache', None) is scope.collector:
                    adapter.cache = None
                    adapter.cache_snapshot = None
                    adapter.cache_live_snapshot = None
        paths.atomic_json(Path(folder) / 'PATH_CACHE_BUILD_FAILED.json', {
            'error': type(exc).__name__ + ':' + str(exc), 'published': scope.published,
            'failed_staging_is_authority': False, 'probe_report': getattr(exc, 'probe_report', None)})
        raise
    finally:
        _SCOPE.reset(token)
        scope.cleanup()
        # Retirement must happen outside the scope to reach the original owner.
        # A failed build keeps the previous store even when it has been closed.
        if scope.completed and scope.published and scope.retirement is not None:
            old, audit = scope.retirement
            record = adapter._retire_obsolete_epoch_store(old, audit)
            epoch_path = Path(folder) / 'PATH_EPOCH.json'
            if epoch_path.exists():
                epoch = json.loads(epoch_path.read_text(encoding='utf-8'))
                epoch['obsolete_store_retention'] = record
                epoch['path_cache_publication'] = scope.collector.summary['path_cache_publication']
                paths.atomic_json(epoch_path, epoch)


def install():
    probe.install()
    cls = paths.TwoModeRouteCollector
    original = cls.__init__
    if getattr(original, '__r1_unpublished_cache__', False):
        return {'installed': True, 'already': True, 'release': RELEASE}
    @wraps(original)
    def init(self, *args, **kwargs):
        scope = _SCOPE.get()
        if scope is None:
            return original(self, *args, **kwargs)
        return scope.construct(original, self, args, kwargs)
    init.__r1_unpublished_cache__ = True
    cls.__init__ = init
    original_open = cls.open_existing.__func__
    @classmethod
    @wraps(original_open)
    def open_existing(cls_, profiles, policy, links, db_path, settings=None, control=None,
                      duplicate_scope_policy='FAIL', max_unique_sequences=100000,
                      max_pairs_per_market=64, read_only=True, require_profile_metadata=False):
        # Check the path before opening even a structurally complete staging DB.
        manifest = _published_manifest(db_path)
        if manifest is not None and read_only is not True:
            raise paths.SupplyContractError('PATH_CACHE_PUBLISHED_STORE_IS_IMMUTABLE')
        result = original_open(cls_, profiles, policy, links, db_path, settings, control,
            duplicate_scope_policy, max_unique_sequences, max_pairs_per_market,
            read_only, require_profile_metadata)
        if manifest is not None:
            try:
                if (result.parent_hash != manifest['semantic']['parent_hash']
                        or result.path_basis_hash() != manifest['semantic']['path_basis_hash']):
                    raise paths.SupplyContractError('PATH_CACHE_PUBLICATION_SEMANTIC_READBACK')
                result.db.close()
                result.db = _readonly(Path(db_path))
                result.read_only = True
                result._refresh_driver_state()
                result.summary.update(same_run_only=True, persistent_cross_run_reuse=False,
                                      published_local_cache_read_only=True)
            except BaseException:
                result.close()
                raise
        return result
    cls.open_existing = open_existing
    return {'installed': True, 'release': RELEASE, 'options': options(),
            'cross_run_cache_policy_changed': False}
