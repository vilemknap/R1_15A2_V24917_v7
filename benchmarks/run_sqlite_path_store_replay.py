"""Replay a REAL completed path store into private benchmark copies (stdlib only).

Source is read-only and SHA-checked before/after. Copies are never calibration
authorities and are removed. Measures disk/SQLite behavior without re-exporting
paths through COM. Commit batching is explicit, not a live-calibration forecast.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import struct
import shutil
import sys
import tempfile
import time

TABLES = ('metadata', 'segments', 'edges', 'geometry', 'volumes',
          'profile_hits', 'driver_markets', 'edge_postings')
SCHEMA = 'R1_15A2_TWO_MODE_PATH_STORE_V238'


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for blob in iter(lambda: f.read(1024 ** 2), b''): h.update(blob)
    return h.hexdigest()


def fingerprint(db):
    result = {}
    for table in TABLES:
        cols = list(db.execute('PRAGMA table_info(' + table + ')'))
        order = sorted((c[5], c[0] + 1) for c in cols if c[5])
        query = 'SELECT * FROM ' + table + ' ORDER BY ' + ','.join(str(c) for _, c in order)
        h = hashlib.sha256(); count = 0
        for row in db.execute(query):
            for value in row:
                blob = value if isinstance(value, bytes) else repr(value).encode('utf-8')
                h.update(type(value).__name__.encode('ascii') + b'\0')
                h.update(struct.pack('<Q', len(blob))); h.update(blob)
            count += 1
        result[table] = {'rows': count, 'sha256': h.hexdigest()}
    return result


def replay(source, folder, expected, fast, commit_rows):
    stage = folder / 'UNPUBLISHED.sqlite'
    db = sqlite3.connect(str(stage))
    try:
        # Copy only to obtain the exact schema/index definitions, then clear and
        # vacuum outside the timed region. No source DDL is executed as code.
        source.backup(db)
        db.execute('PRAGMA foreign_keys=OFF')
        for table in reversed(TABLES): db.execute('DELETE FROM ' + table)
        db.commit(); db.execute('VACUUM')
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=' + ('MEMORY' if fast else 'DELETE'))
        db.execute('PRAGMA synchronous=' + ('OFF' if fast else 'FULL'))
        db.execute('PRAGMA cache_size=-32768')
        started = time.perf_counter()
        commits = 0
        for table in TABLES:
            ncols = len(list(db.execute('PRAGMA table_info(' + table + ')')))
            sql = 'INSERT INTO ' + table + ' VALUES(' + ','.join('?' for _ in range(ncols)) + ')'
            batch, memory, in_transaction = [], 0, 0
            for row in source.execute('SELECT * FROM ' + table):
                batch.append(row)
                memory += sys.getsizeof(row) + sum(sys.getsizeof(v) for v in row)
                in_transaction += 1
                if len(batch) >= commit_rows or memory >= 16 * 1024 ** 2 or in_transaction == commit_rows:
                    db.executemany(sql, batch); batch.clear(); memory = 0
                if in_transaction == commit_rows:
                    db.commit(); commits += 1; in_transaction = 0
            if batch: db.executemany(sql, batch)
            if in_transaction: db.commit(); commits += 1
        written = time.perf_counter()
        assert list(db.execute('PRAGMA integrity_check')) == [('ok',)]
        assert list(db.execute('PRAGMA foreign_key_check')) == []
        actual = fingerprint(db)
        if actual != expected: raise RuntimeError('SQLITE_REPLAY_CONTENT_MISMATCH')
        db.execute('PRAGMA journal_mode=DELETE'); db.execute('PRAGMA synchronous=FULL')
        db.close()
        with stage.open('r+b') as f:
            import os
            os.fsync(f.fileno())
        digest = sha_file(stage)
        elapsed = time.perf_counter()
        return {'insert_seconds': written - started, 'checks_fsync_sha_seconds': elapsed - written,
                'total_seconds': elapsed - started, 'commits': commits, 'store_bytes': stage.stat().st_size,
                'store_sha256': digest, 'content_exact': True}
    finally:
        db.close()


def benchmark(source_path, output, *, repetitions=2, commit_rows=5000, work_root=None):
    source_path, output = Path(source_path).resolve(), Path(output).resolve()
    if (output == source_path or output.parent == source_path.parent or not 1 <= repetitions <= 5
            or not 1 <= commit_rows <= 100000):
        raise ValueError('REPLAY_USE_SEPARATE_OUTPUT_DIRECTORY_AND_VALID_BUDGETS')
    if any(p.name.startswith('.UNPUBLISHED_PATH_CACHE_') for p in source_path.parents):
        raise ValueError('REPLAY_COMPLETED_SOURCE_REQUIRED')
    scratch = Path(work_root) if work_root is not None else Path(tempfile.gettempdir())
    if shutil.disk_usage(scratch).free < source_path.stat().st_size * 3 + 512 * 1024 ** 2:
        raise ValueError('REPLAY_INSUFFICIENT_SCRATCH_SPACE')
    source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
    try:
        source.execute('PRAGMA query_only=ON')
        objects = list(source.execute("SELECT type,name FROM sqlite_master WHERE type NOT IN ('index')"))
        if {name for kind, name in objects if kind == 'table'} != set(TABLES) or any(k != 'table' for k, _ in objects):
            raise ValueError('REPLAY_EXPECTED_EXACT_PATH_STORE_TABLES_NO_VIEWS_OR_TRIGGERS')
        metadata = dict(source.execute('SELECT key,value FROM metadata'))
        if metadata.get('schema') != SCHEMA:
            raise ValueError('REPLAY_PATH_STORE_SCHEMA_MISMATCH')
        if (metadata.get('structural_export_complete') != 'true' or metadata.get('incidence_ready') != 'true'
                or metadata.get('path_cache_publication_state') == 'UNPUBLISHED'
                or source.execute('PRAGMA journal_mode').fetchone()[0] != 'delete'):
            raise ValueError('REPLAY_COMPLETED_DELETE_MODE_SOURCE_REQUIRED')
        if any(not list(source.execute('PRAGMA table_info(' + t + ')')) for t in TABLES):
            raise ValueError('REPLAY_PATH_STORE_TABLE_MISSING')
        before = sha_file(source_path)
        expected = fingerprint(source)
        runs = {'full': [], 'fast': []}
        for rep in range(repetitions):
            for fast in ((False, True) if rep % 2 == 0 else (True, False)):
                with tempfile.TemporaryDirectory(prefix='.UNPUBLISHED_PATH_CACHE_REPLAY_', dir=work_root) as name:
                    label = 'fast' if fast else 'full'
                    result = replay(source, Path(name), expected, fast, commit_rows)
                    runs[label].append(result)
                    print(json.dumps({'repetition': rep, 'variant': label, **result}), flush=True)
        if sha_file(source_path) != before:
            raise RuntimeError('REPLAY_SOURCE_CHANGED_DURING_BENCHMARK')
        metrics = ('insert_seconds', 'checks_fsync_sha_seconds', 'total_seconds')
        medians = {label: {m: statistics.median(r[m] for r in rows) for m in metrics}
                   for label, rows in runs.items()}
        report = {'schema': 'R1_REAL_SQLITE_REPLAY_BENCHMARK_V1', 'source_sha256': before,
            'source_read_only': True, 'source_content_unchanged': True, 'source_tables': expected,
            'benchmark_copies_are_authorities': False, 'commit_rows': commit_rows,
            'repetitions': repetitions, 'median_seconds': medians, 'runs': runs,
            'full_over_fast': {m: medians['full'][m] / medians['fast'][m] for m in metrics},
            'limitations': 'SQLite replay batching; excludes source-copy/vacuum setup, COM and native calibration.'}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        return report
    finally:
        source.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-store', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--work-root', type=Path, help='Existing scratch directory on the disk to measure')
    p.add_argument('--repetitions', type=int, default=2)
    p.add_argument('--commit-rows', type=int, default=5000)
    args = p.parse_args()
    result = benchmark(args.source_store, args.output, repetitions=args.repetitions,
                       commit_rows=args.commit_rows, work_root=args.work_root)
    print(json.dumps({k: v for k, v in result.items() if k != 'runs'}, indent=2))


if __name__ == '__main__':
    main()
