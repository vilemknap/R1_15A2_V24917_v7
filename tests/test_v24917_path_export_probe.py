"""Bounded fake-COM qualification, immutable range retries, no size fallback."""
from types import SimpleNamespace

import pytest

import r1_15a2_path_export_probe_v24917 as probe
import r1_15a2_two_mode_v238 as paths
from test_v237_15p_bounded_offdiag_stream import BoundedHierarchical


def fake_lists(monkeypatch, damage=None, count=100):
    ticks = [0.]
    objects = []
    if count < 256:
        monkeypatch.setattr(probe, 'REFERENCE_PAGE', 1)
    def make(visum, kind, code):
        rows = ([[i + 1, i + 2, 1, 2.5] for i in range(count)] if kind == 'CreatePrTPathList'
                else [['', '', '', i + 1, i + 2, i + 3, i + 4] for i in range(count)])
        obj = BoundedHierarchical(rows)
        original = obj._oleobj_.Invoke
        def invoke(memid, lcid, k, method, first, last):
            size = last - first + 1
            ticks[0] += 1. + .001 * size
            if damage == 'capacity' and size in (8, 16):
                raise MemoryError('PAGE_TOO_LARGE')
            if damage == 'transient' and size == 8:
                raise RuntimeError('call was rejected by callee')
            raw = original(memid, lcid, k, method, first, last)
            if damage == 'content' and size == 8 and raw:
                raw = [list(r) for r in raw]; raw[0][0] = 999
            if damage == 'reference_drift' and first == 1 and size == 16:
                obj.raw[0] = [999] + obj.raw[0][1:]
            return raw
        obj._oleobj_.Invoke = invoke
        objects.append(obj)
        return obj
    monkeypatch.setattr(paths, 'create_list', make)
    monkeypatch.setattr(probe, '_clock', lambda: ticks[0])
    monkeypatch.setattr(probe, '_rss', lambda: 123456)
    return objects


def run_probe():
    return probe.benchmark(None, paths.DEFAULT_SETTINGS, paths.QuietControl(),
                           candidates=(2, 4, 8, 16), starts=(1, 65), repetitions=2)


def test_selects_one_size_from_exact_same_windows(monkeypatch):
    objects = fake_lists(monkeypatch)
    report = run_probe()
    assert report['selected_page_size'] == 16
    assert all(r['eligible'] for r in report['candidates'])
    assert all(not obj.unbounded_calls for obj in objects)
    assert len(objects) == 4
    assert report['runtime_page_fallback'] is False
    assert all(s['host_rss_after'] == 123456 for r in report['candidates'] for s in r['samples'])


def test_native_16384_size_is_supported_by_probe_not_sealed_config(monkeypatch):
    fake_lists(monkeypatch, count=17000)
    report = probe.benchmark(None, paths.DEFAULT_SETTINGS, paths.QuietControl(),
                            candidates=(2048, 4096, 8192, 16384), starts=(1,), repetitions=1)
    assert report['selected_page_size'] == 16384
    assert all(r['eligible'] for r in report['candidates'])


@pytest.mark.parametrize('damage', ['capacity', 'transient', 'content'])
def test_failed_probe_candidate_is_disqualified_before_export(monkeypatch, damage):
    fake_lists(monkeypatch, damage)
    report = run_probe()
    result = {r['page_size']: r for r in report['candidates']}
    assert not result[8]['eligible']
    assert result[8]['errors']
    if damage == 'capacity': assert report['selected_page_size'] == 4
    else: assert report['selected_page_size'] == 16
    if damage == 'transient': assert result[8]['retry_incidence'] == 1


def test_reference_drift_is_fatal(monkeypatch):
    fake_lists(monkeypatch, 'reference_drift')
    with pytest.raises(Exception, match='REFERENCE_CHANGED'):
        run_probe()


def test_no_full_page_is_not_a_large_page_certificate(monkeypatch):
    fake_lists(monkeypatch, count=3)
    report = run_probe()
    assert report['selected_page_size'] == 2
    assert all(not r['eligible'] for r in report['candidates'] if r['page_size'] > 2)


def test_no_winner_fails_with_diagnostic_details(monkeypatch):
    fake_lists(monkeypatch, count=1)
    with pytest.raises(Exception, match='NO_QUALIFIED_SIZE') as exc:
        run_probe()
    assert len(exc.value.probe_report['candidates']) == 4


def test_memory_limit_disqualifies_candidate(monkeypatch):
    fake_lists(monkeypatch)
    monkeypatch.setattr(probe, '_page_bytes', lambda page: (200 if len(page) == 16 else 1) * 1024 ** 2)
    report = run_probe()
    assert report['selected_page_size'] == 8
    assert not next(r for r in report['candidates'] if r['page_size'] == 16)['eligible']


@pytest.mark.parametrize('damage', ['size_error', 'wrong_schema', 'too_many', 'repeated', 'wrong_signature'])
def test_fixed_export_never_resizes_on_failure(damage):
    obj = BoundedHierarchical([[i + 1, i + 2, 1, 10.] for i in range(10)])
    original = obj._oleobj_.Invoke
    def invoke(memid, lcid, k, method, first, last):
        if damage == 'size_error':
            obj._oleobj_.calls.append((first, last))
            raise MemoryError('PAGE_TOO_LARGE')
        result = original(memid, lcid, k, method, first, last)
        if damage == 'wrong_schema': return [[1]]
        if damage == 'too_many': return result + result
        if damage == 'repeated': return obj.raw[:4]
        return result
    obj._oleobj_.Invoke = invoke
    if damage == 'wrong_signature': obj._oleobj_.typeinfo.names = ('SaveToArray', 'Wrong', 'LastObject')
    settings = dict(paths.DEFAULT_SETTINGS, path_export_fixed_page_size=4,
                    com_retry_policy={'enabled': False})
    with pytest.raises(Exception):
        list(probe.fixed_rows(obj, paths.PARENT_COLUMNS, settings, paths.QuietControl(), 'TEST'))
    assert all(last - first + 1 == 4 for first, last in obj._oleobj_.calls)
    assert obj.unbounded_calls == 0


def test_transient_retry_repeats_identical_range(monkeypatch):
    obj = BoundedHierarchical([[i + 1, i + 2, 1, 10.] for i in range(5)])
    calls = []
    def invoke(memid, lcid, kind, method, first, last):
        calls.append((first, last))
        if len(calls) == 1: raise RuntimeError('call was rejected by callee')
        return obj.raw[first - 1:last]
    obj._oleobj_.Invoke = invoke
    settings = dict(paths.DEFAULT_SETTINGS, path_export_fixed_page_size=4,
                    com_retry_policy={'enabled': True, 'max_attempts': 2,
                                      'initial_delay_seconds': 0., 'max_delay_seconds': 0.})
    result = list(probe.fixed_rows(obj, paths.PARENT_COLUMNS, settings, paths.QuietControl(), 'TEST'))
    assert result == obj.raw
    assert calls == [(1, 4), (1, 4), (5, 8)]
    assert settings['path_export_page_stats']['TEST::']['retry_events'] == 1


def test_fixed_reader_above_4096_preserves_all_rows():
    obj = BoundedHierarchical([[i + 1, i + 2, 1, 10.] for i in range(20000)])
    settings = dict(paths.DEFAULT_SETTINGS, path_export_fixed_page_size=8192)
    result = list(probe.fixed_rows(obj, paths.PARENT_COLUMNS, settings, paths.QuietControl(), 'TEST'))
    assert result == obj.raw
    assert obj._oleobj_.calls == [(1, 8192), (8193, 16384), (16385, 24576)]


def test_fixed_reader_keeps_row_budget():
    obj = BoundedHierarchical([[i + 1, i + 2, 1, 10.] for i in range(5)])
    settings = dict(paths.DEFAULT_SETTINGS, path_export_fixed_page_size=4, max_parent_rows_per_dseg=4)
    with pytest.raises(Exception, match='PATH_ROW_BUDGET_EXCEEDED'):
        list(probe.fixed_rows(obj, paths.PARENT_COLUMNS, settings, paths.QuietControl(), 'TEST'))
