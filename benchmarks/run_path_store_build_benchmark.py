"""Offline exact-path-store benchmark. No Visum, COM timing or speed assertion.

Example: python benchmarks/run_path_store_build_benchmark.py --output /tmp/path-build.json
Runs alternate old/new order, validates every SQL table and canonical path hash.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import struct
import sys
import tempfile
import time
from types import MethodType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import r1_15a2_path_store_build_v24917 as fast
from r1_15a2_supply import SupplyPolicy


class QueryProbe:
    def __init__(self, connection):
        self.connection = connection
        self.keymap_reads = 0

    def execute(self, sql, *args, **kwargs):
        if sql.startswith('SELECT gid,orig,dest,path_index FROM geometry WHERE mode='):
            self.keymap_reads += 1
        return self.connection.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def sql_digest(db):
    hashes = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        ncols = len(list(db.execute('PRAGMA table_info(' + name + ')')))
        digest = hashlib.sha256()
        for row in db.execute('SELECT * FROM ' + name + ' ORDER BY ' + ','.join(str(i + 1) for i in range(ncols))):
            for value in row:
                blob = value if isinstance(value, bytes) else repr(value).encode('utf-8')
                digest.update(struct.pack('<Q', len(blob))); digest.update(blob)
        hashes[name] = digest.hexdigest()
    return hashes


def run(sealed, folder, n, optimized, links_per_path):
    # One directed cycle, traversed twice: exercise repeated-edge multiplicity.
    edges = [(100 + i, i + 1, (i + 1) % links_per_path + 1) for i in range(links_per_path)]
    network = {e: {'eligible': True, 'addval1': 0., 't0_c_seconds': 60.} for e in edges}
    profile = dict(link_no=edges[0][0], from_node_no=edges[0][1], to_node_no=edges[0][2],
                   observed=1., model=1., role='CALIBRATION', countlocation_no='P1')
    keys = [(i // 680 + 1, (i % 680 + 100) % 681 + 1, 1) for i in range(n)]
    c = sealed.TwoModeRouteCollector([profile], SupplyPolicy(), 'state', network,
        folder / ('new.sqlite' if optimized else 'old.sqlite'),
        dict(sealed.DEFAULT_SETTINGS, min_free_disk_gib=0))
    if optimized:
        c.add_parents = MethodType(fast.add_parents, c)
        c.add_geometry = MethodType(fast.add_geometry, c)
    c.db = QueryProbe(c.db)

    def geometry_rows():
        for key in keys:
            yield (*key, '', '', '', '')
            for ix, edge in enumerate(edges * 2, 1):
                yield ('', '', '', ix, *edge)

    try:
        # Construct inputs outside timed region; feed identical reverse-ordered
        # keys and floating-point volumes with explicit zero rows to both builds.
        parents = [[(*k, 0. if i % 13 == 0 else 10. + d / 10.)
                    for i, k in reversed(list(enumerate(keys)))] for d in range(8)]
        authorities = [{'matrix_interzonal': sum(v for o, de, ix, v in rows if o != de)}
                       for rows in parents]
        t0 = time.perf_counter()
        for mode, count in (('C', 8), ('C_NOT', 4)):
            for d in range(count):
                c.add_parents(mode + str(d), mode, iter(parents[d]), authorities[d])
        t1 = time.perf_counter()
        for mode in ('C', 'C_NOT'):
            c.add_geometry(mode, geometry_rows())
        t2 = time.perf_counter()
        c.prepare_incidence_evidence()
        t3 = time.perf_counter()
        result = {'parent_seconds': t1 - t0, 'geometry_seconds': t2 - t1,
                  'incidence_seconds': t3 - t2, 'total_seconds': t3 - t0,
                  'keymap_sql_reads': c.db.keymap_reads,
                  'store_bytes': Path(c.route_db_path).stat().st_size,
                  'tables_sha256': sql_digest(c.db), 'flow': c.flow,
                  'structure_hash': c.path_structure_hash(), 'basis_hash': c.path_basis_hash(),
                  'comparison_hash': c.path_basis_comparison_hash()}
        assert list(c.db.execute('PRAGMA foreign_key_check')) == []
        assert c.db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        return result
    finally:
        c.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--paths-per-mode', type=int, default=12000)
    parser.add_argument('--cycle-links', type=int, default=20)
    parser.add_argument('--repetitions', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.paths_per_mode <= 681 * 680 or args.cycle_links < 1 or args.repetitions < 1:
        parser.error('invalid workload')
    spec = importlib.util.spec_from_file_location('_sealed_path_store_benchmark', ROOT / 'r1_15a2_two_mode_v238.py')
    sealed = importlib.util.module_from_spec(spec); spec.loader.exec_module(sealed)
    results = {False: [], True: []}
    for rep in range(args.repetitions):
        with tempfile.TemporaryDirectory(prefix='r1-path-build-') as directory:
            pair = {}
            for optimized in ((False, True) if rep % 2 == 0 else (True, False)):
                pair[optimized] = run(sealed, Path(directory), args.paths_per_mode, optimized, args.cycle_links)
                results[optimized].append(pair[optimized])
            for key in ('tables_sha256', 'flow', 'structure_hash', 'basis_hash', 'comparison_hash'):
                assert pair[False][key] == pair[True][key], key
    metrics = ('parent_seconds', 'geometry_seconds', 'incidence_seconds', 'total_seconds')
    medians = {name: {m: statistics.median(r[m] for r in results[opt]) for m in metrics}
               for opt, name in ((False, 'original'), (True, 'optimized'))}
    output = {'schema': 'R1_PATH_STORE_BUILD_OFFLINE_BENCHMARK_V1', 'live_visum_run': False,
              'paths_per_mode': args.paths_per_mode, 'dsegs': 12,
              'geometry_rows': 2 * args.paths_per_mode * (2 * args.cycle_links + 1),
              'repetitions': args.repetitions, 'all_tables_and_hashes_exact': True,
              'median_seconds': medians,
              'speedup': {m: medians['original'][m] / medians['optimized'][m] for m in metrics},
              'runs': {'original': results[False], 'optimized': results[True]},
              'limitations': 'Synthetic cyclic paths; excludes live COM and network/Windows disk latency.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in output.items() if k != 'runs'}, indent=2))


if __name__ == '__main__':
    main()
