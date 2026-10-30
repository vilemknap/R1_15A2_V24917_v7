"""Million-row SQLite build benchmark, identical strong publication gates.

Synthetic source paths only; includes checks/fsync/hash/atomic rename/RO open.
Does not measure live Visum, COM latency, SMB or Windows power-loss behavior.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import r1_15a2_path_cache_publish_v24917 as publication
import r1_15a2_path_store_build_v24917 as builder
import r1_15a2_two_mode_v238 as paths
from r1_15a2_supply import SupplyPolicy


def run(folder, count, fast):
    folder.mkdir()
    network = {(10 + i, i + 1, (i + 1) % 4 + 1):
               {'eligible': True, 'addval1': 0., 't0_c_seconds': 60.} for i in range(4)}
    edges = tuple(network) * 2
    keys = [(i // 680 + 1, (i % 680 + i // 680 + 1) % 681 + 1, 1) for i in range(count)]
    nonzero = sum(i % 17 != 0 for i in range(count))
    model = float(nonzero * (sum(range(1, 9)) + sum(range(1, 5))) * 2)
    profile = dict(link_no=10, from_node_no=1, to_node_no=2,
        observed=model, model=model, role='CALIBRATION', countlocation_no='SYNTHETIC')
    snapshot = {'state_hash': 'synthetic-parent'}
    codes = {m: sorted(v, key=lambda c: (c != paths.core.norm_code(paths.DEFAULT_SETTINGS['representatives'][m]), c))
             for m, v in paths.EXPECTED_MODE_DSEGS.items()}
    adapter = SimpleNamespace(persistent_path_cache=SimpleNamespace(enabled=False),
        snapshot=lambda: dict(snapshot), cfg={'supply': {'passenger_dsegs': sum(codes.values(), [])}},
        visum=None)
    scope = publication.BuildScope(adapter, folder, snapshot,
                                    dict(publication.DEFAULTS, fast_staging=True))
    token = publication._SCOPE.set(scope)
    c = None
    try:
        c = paths.TwoModeRouteCollector([profile], SupplyPolicy(), 'synthetic-parent', network,
            folder / publication.STORE, dict(paths.DEFAULT_SETTINGS, min_free_disk_gib=0), paths.QuietControl())
        if not fast:
            c.db.execute('PRAGMA journal_mode=DELETE')
            c.db.execute('PRAGMA synchronous=FULL')
        t0 = time.perf_counter()
        for mode in ('C', 'C_NOT'):
            for d, code in enumerate(codes[mode], 1):
                c.add_parents(code, mode, ((*k, float(d) if i % 17 else 0.) for i, k in enumerate(keys)),
                              {'matrix_interzonal': float(nonzero * d)})
        t1 = time.perf_counter()
        def geometry():
            for key in keys:
                yield (*key, '', '', '', '')
                for ix, edge in enumerate(edges, 1):
                    yield ('', '', '', ix, *edge)
        for mode in ('C', 'C_NOT'):
            c.add_geometry(mode, geometry())
        t2 = time.perf_counter()
        c.prepare_incidence_evidence()
        comparison = c.path_basis_comparison_hash()
        t3 = time.perf_counter()
        manifest = scope.publish(c)
        t4 = time.perf_counter()
        return {'parent_seconds': t1 - t0, 'geometry_seconds': t2 - t1,
                'incidence_and_comparison_seconds': t3 - t2, 'bulk_seconds': t3 - t0,
                'publication_seconds': t4 - t3, 'end_to_end_seconds': t4 - t0,
                'semantic': manifest['semantic'], 'store_bytes': manifest['store_bytes'],
                'comparison_hash': comparison, 'read_only_after_publish': c.read_only}
    finally:
        if c is not None: c.close()
        publication._SCOPE.reset(token)
        scope.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--paths-per-mode', type=int, default=180000)
    parser.add_argument('--repetitions', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.paths_per_mode <= 681 * 680 or not 1 <= args.repetitions <= 5:
        parser.error('invalid workload')
    builder.install(); publication.install()
    rows = {'full': [], 'fast': []}
    for rep in range(args.repetitions):
        with tempfile.TemporaryDirectory(prefix='r1-staging-benchmark-') as directory:
            pair = {}
            for fast in ((False, True) if rep % 2 == 0 else (True, False)):
                label = 'fast' if fast else 'full'
                result = run(Path(directory) / label, args.paths_per_mode, fast)
                pair[label] = result
                rows[label].append(result)
                print(json.dumps({'repetition': rep, 'variant': label,
                    **{k: v for k, v in result.items() if k.endswith('_seconds')}}), flush=True)
            assert pair['full']['semantic'] == pair['fast']['semantic']
    metrics = ('parent_seconds', 'geometry_seconds', 'bulk_seconds',
               'publication_seconds', 'end_to_end_seconds')
    medians = {label: {m: statistics.median(row[m] for row in runs) for m in metrics}
               for label, runs in rows.items()}
    report = {'schema': 'R1_STAGING_MILLION_ROW_BENCHMARK_V1', 'synthetic': True, 'live_visum': False,
              'paths_per_mode': args.paths_per_mode, 'volume_rows': 12 * args.paths_per_mode,
              'geometry_rows': 2 * args.paths_per_mode, 'geometry_input_rows': 18 * args.paths_per_mode,
              'repetitions': args.repetitions, 'identical_strong_publication_gates': True,
              'semantics_exact': True, 'median_seconds': medians,
              'full_over_fast': {m: medians['full'][m] / medians['fast'][m] for m in metrics},
              'runs': rows, 'limitations': 'Linux local disk; no live model, COM or network-disk timing.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'runs'}, indent=2))


if __name__ == '__main__':
    main()
