"""Real-store replay entrypoint: no source writes, exact contents, bounded copies."""
import importlib.util
import json
from pathlib import Path

import pytest

from test_two_mode_v238 import fill, store

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('_sqlite_replay_benchmark',
        ROOT / 'benchmarks/run_sqlite_path_store_replay.py')
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize('batch', [1, 3])
def test_replay_is_exact_and_source_unchanged(tmp_path, batch):
    c = store(tmp_path / 'SOURCE'); fill(c)
    path = Path(c.route_db_path); before = path.read_bytes(); c.close()
    scratch = tmp_path / 'scratch'; scratch.mkdir()
    report_path = tmp_path / 'results/REPORT.json'
    report = module().benchmark(path, report_path, repetitions=1, commit_rows=batch, work_root=scratch)
    assert path.read_bytes() == before
    assert report['source_read_only'] and report['source_content_unchanged']
    assert report['source_tables']['volumes']['rows'] == 2
    assert not report['benchmark_copies_are_authorities']
    assert all(row['content_exact'] for runs in report['runs'].values() for row in runs)
    assert not list(scratch.iterdir())
    assert json.loads(report_path.read_text()) == report


def test_replay_refuses_incomplete_source(tmp_path):
    c = store(tmp_path / 'SOURCE')
    path = Path(c.route_db_path); c.close()
    with pytest.raises(ValueError, match='COMPLETED'):
        module().benchmark(path, tmp_path / 'out/REPORT.json', repetitions=1)


def test_replay_refuses_report_in_source_directory(tmp_path):
    c = store(tmp_path / 'SOURCE'); fill(c)
    path = Path(c.route_db_path); c.close()
    with pytest.raises(ValueError, match='SEPARATE_OUTPUT'):
        module().benchmark(path, path.parent / 'REPORT.json')
