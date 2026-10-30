"""Read-only page-size profiling and fixed-page native path enumeration.

Profiling is opt-in: a failed candidate is rejected BEFORE an export starts.
Once selected, production pagination never changes size after an error. Only
the existing transient COM retry of the identical range remains permitted.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import statistics
import struct
import sys
import time

import r1_15a2_two_mode_v238 as paths

RELEASE = 'R1_PATH_EXPORT_PAGE_PROBE1_20261030'
MAX_PAGE = 16384
REFERENCE_PAGE = 256
_clock = time.perf_counter


def _rss():
    """Current Python-host RSS; never presented as Visum/native peak memory."""
    if os.name == 'nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    'peak', 'working', 'qpeak', 'q', 'ppeak', 'p', 'page', 'pagepeak')]
        c = Counters(); c.cb = ctypes.sizeof(c)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb):
            raise OSError(ctypes.get_last_error(), 'GetProcessMemoryInfo')
        return int(c.working)
    stat = Path('/proc/self/statm')
    return int(stat.read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE') if stat.exists() else None


def _page_bytes(page):
    # Bound probe payload, not the unobservable native COM allocator high water.
    return sys.getsizeof(page) + sum(sys.getsizeof(r) + sum(sys.getsizeof(v) for v in r) for r in page)


def _hash_rows(digest, page, columns):
    if columns == paths.PARENT_COLUMNS:
        for row in page:
            o, d, ix = (paths._id(v) for v in row[:3])
            vol = paths.com.finite_float(row[3], 'Vol(AP)')
            if vol < 0:
                raise paths.SupplyContractError('NEGATIVE_PATH_VOLUME')
            digest.update(struct.pack('<IIId', o, d, ix, vol))
    else:
        for row in page:
            digest.update(struct.pack('<7I', *(paths._id(v) if paths._filled(v) else 0 for v in row)))


def _window(obj, columns, start, span, size, control, memory_limit):
    ole, memid, kind = paths.rt.verified_bounded_signature(obj)
    first, end = start, start + span - 1
    digest = hashlib.sha256()
    rows = full_pages = calls = peak_payload = retry_errors = 0
    latencies = []
    previous = None
    rss_before = _rss()
    while first <= end:
        last = min(end, first + size - 1)
        control.checkpoint('PATH_PAGE_PROBE', page_size=size, first=first, last=last)
        started = _clock()
        try:
            # No COMBUSY budget-floor retries during a size qualification. Any
            # transient rejection disqualifies this candidate in this profile.
            raw = paths.com.bounded_ole_invoke_with_retry(
                ole, memid, kind, first, last, retry_policy={'enabled': False}, label='PATH_PAGE_PROBE')
        except Exception as exc:
            if paths.com.is_retryable_com_error(exc):
                retry_errors += 1
            raise
        latencies.append(_clock() - started)
        calls += 1
        page = [] if raw is None else raw
        count = len(page)
        if count > last - first + 1:
            raise paths.SupplyContractError('PATH_PAGE_PROBE_EXCEEDS_REQUEST')
        if any(len(r) != len(columns) for r in page):
            raise paths.SupplyContractError('PATH_PAGE_PROBE_ROW_SCHEMA')
        if count == size and previous is not None and page == previous:
            raise paths.SupplyContractError('REPEATED_BOUNDED_PAGE_NO_PROGRESS')
        payload = _page_bytes(page)
        peak_payload = max(peak_payload, payload)
        if payload > memory_limit:
            raise paths.SupplyContractError('PATH_PAGE_PROBE_PAYLOAD_BUDGET')
        _hash_rows(digest, page, columns)
        rows += count
        full_pages += count == size
        previous = page if count == size else None
        if count < last - first + 1:
            break
        first = last + 1
    seconds = sum(latencies)
    return {'rows': rows, 'sha256': digest.hexdigest(), 'calls': calls,
            'com_seconds': seconds, 'latency_median_seconds': statistics.median(latencies),
            'rows_per_second': rows / max(seconds, 1e-12), 'full_pages': full_pages,
            'max_python_page_bytes': peak_payload, 'host_rss_before': rss_before,
            'host_rss_after': _rss(), 'retryable_errors': retry_errors}


def benchmark(visum, settings, control, *, candidates=(256, 2048, 4096, 8192, 16384),
              starts=(1, 65537), repetitions=2, memory_limit_mib=128):
    """Compare identical bounded windows for both modes and both native lists.

    Caller owns whole-model before/after identity. Results are advisory outside
    that scope; no saved profile can authorize a later assignment/Visum session.
    """
    candidates = sorted(set(paths.com.exact_int(v, 'PAGE_CANDIDATE') for v in candidates))
    if not candidates or candidates[0] < 1 or candidates[-1] > MAX_PAGE:
        raise ValueError('PATH_PAGE_PROBE_CANDIDATES')
    starts = tuple(paths.com.exact_int(v, 'PAGE_WINDOW_START') for v in starts)
    repetitions = paths.com.exact_int(repetitions, 'PAGE_REPETITIONS')
    memory_limit_mib = paths.com.finite_float(memory_limit_mib, 'PAGE_MEMORY_MIB')
    memory_limit = memory_limit_mib * 1024 ** 2
    if (not starts or min(starts) < 1 or len(starts) > 8 or len(set(starts)) != len(starts)
            or not 1 <= repetitions <= 5 or not 1 <= memory_limit_mib <= 1024):
        raise ValueError('PATH_PAGE_PROBE_BUDGET')
    span = max(candidates)
    limits = {paths.PARENT_COLUMNS: settings['max_parent_rows_per_dseg'],
              paths.GEOMETRY_COLUMNS: settings['max_geometry_rows_per_mode']}
    results = {size: {'page_size': size, 'eligible': True, 'samples': [], 'errors': []}
               for size in candidates}
    references = {}
    for mode, code in sorted(settings['representatives'].items()):
        for kind, columns in (('CreatePrTPathList', paths.PARENT_COLUMNS),
                              ('CreatePrTPathLinkList', paths.GEOMETRY_COLUMNS)):
            if any(start + span - 1 > limits[columns] for start in starts):
                raise ValueError('PATH_PAGE_PROBE_WINDOW_EXCEEDS_ROW_BUDGET')
            obj = paths.create_list(visum, kind, code)
            label = mode + ':' + kind
            for start in starts:
                references[(label, start)] = _window(
                    obj, columns, start, span, REFERENCE_PAGE, control, memory_limit)
            if not sum(references[(label, start)]['rows'] for start in starts):
                raise paths.SupplyContractError('PATH_PAGE_PROBE_EMPTY_REFERENCE:' + label)
            for rep in range(repetitions):
                for size in (candidates if rep % 2 == 0 else list(reversed(candidates))):
                    result = results[size]
                    if not result['eligible']:
                        continue
                    for start in starts:
                        try:
                            sample = _window(obj, columns, start, span, size, control, memory_limit)
                            ref = references[(label, start)]
                            if (sample['rows'], sample['sha256']) != (ref['rows'], ref['sha256']):
                                raise paths.SupplyContractError('PATH_PAGE_PROBE_CONTENT_MISMATCH')
                            sample.update(list=label, start=start, repetition=rep)
                            result['samples'].append(sample)
                        except Exception as exc:
                            if getattr(exc, 'stop_design_run', False):
                                raise
                            result['eligible'] = False
                            result['errors'].append({'list': label, 'start': start, 'repetition': rep,
                                'error': type(exc).__name__ + ':' + str(exc),
                                'retryable': paths.com.is_retryable_com_error(exc)})
                            break
            # A partial/empty tail cannot qualify a large page. Require a full
            # page in EACH list and EACH repetition, wherever it fits the data.
            for size, result in results.items():
                for rep in range(repetitions):
                    if not any(s['list'] == label and s['repetition'] == rep and s['full_pages']
                               for s in result['samples']):
                        result['eligible'] = False
                        result['errors'].append({'list': label, 'repetition': rep,
                                                 'error': 'NO_FULL_PAGE_OBSERVED'})
            # Re-read the independent small-page authority after qualification.
            for start in starts:
                after = _window(obj, columns, start, span, REFERENCE_PAGE, control, memory_limit)
                ref = references[(label, start)]
                if (after['rows'], after['sha256']) != (ref['rows'], ref['sha256']):
                    raise paths.SupplyContractError('PATH_PAGE_PROBE_REFERENCE_CHANGED')
            del obj
    for result in results.values():
        per_rep = [sum(s['com_seconds'] for s in result['samples'] if s['repetition'] == rep)
                   for rep in range(repetitions)]
        result['median_com_seconds'] = statistics.median(per_rep)
        result['retry_incidence'] = sum(e.get('retryable', False) for e in result['errors'])
    eligible = [r for r in results.values() if r['eligible']]
    if not eligible:
        exc = paths.SupplyContractError('PATH_PAGE_PROBE_NO_QUALIFIED_SIZE')
        exc.probe_report = {'candidates': list(results.values()), 'runtime_page_fallback': False}
        raise exc
    winner = min(eligible, key=lambda r: (r['median_com_seconds'], r['page_size']))['page_size']
    return {'schema': RELEASE, 'selected_page_size': winner, 'candidates': list(results.values()),
            'reference_page_size': REFERENCE_PAGE, 'window_span': span, 'window_starts': starts,
            'repetitions': repetitions, 'read_only': True, 'runtime_page_fallback': False,
            'scope': 'CURRENT_BUILD_ONLY_NOT_A_CROSS_SESSION_CERTIFICATE',
            'memory_semantics': 'PYTHON_PAGE_PAYLOAD_AND_SAMPLED_HOST_RSS_NOT_NATIVE_PEAK',
            'retry_semantics': 'NO_PYTHON_RETRIES_DURING_PROBE;HOST_MESSAGE_FILTER_NOT_OBSERVABLE'}


def fixed_rows(obj, columns, settings, control, phase, **details):
    """Never backtrack, skip or resize; validate the same bounded export gates."""
    size = paths.com.exact_int(settings['path_export_fixed_page_size'], 'FIXED_PAGE_SIZE')
    if not 1 <= size <= MAX_PAGE:
        raise ValueError('PATH_EXPORT_FIXED_PAGE_SIZE_RANGE')
    limit = int(settings['max_parent_rows_per_dseg'] if columns == paths.PARENT_COLUMNS
                else settings['max_geometry_rows_per_mode'])
    ole, memid, kind = paths.rt.verified_bounded_signature(obj)
    first = 1
    pages = 0
    previous = None
    stats = settings.setdefault('path_export_page_stats', {})
    label = ':'.join(str(v) for v in (phase, details.get('mode', ''), details.get('dseg_code', '')))
    stat = stats.setdefault(label, {'calls': 0, 'rows': 0, 'com_seconds': 0., 'retry_events': 0,
                                   'errors': 0, 'fixed_page_size': size})
    while True:
        control.checkpoint(phase, raw_rows=first - 1, pages=pages, **details)
        last = first + size - 1
        def retry(event):
            stat['retry_events'] += 1
            control.checkpoint(phase, force=True, raw_rows=first - 1, pages=pages,
                bounded_range_first=first, bounded_range_last=last, bounded_page_size=size,
                com_retry_event=event, **details)
        started = time.perf_counter()
        stat['calls'] += 1
        try:
            raw = paths.com.bounded_ole_invoke_with_retry(
                ole, memid, kind, first, last, retry_policy=settings.get('com_retry_policy'),
                label=phase, on_retry=retry, on_exhausted=retry)
        except BaseException:
            stat['errors'] += 1
            raise
        finally:
            stat['com_seconds'] += time.perf_counter() - started
        page = [] if raw is None else raw
        if len(page) > size:
            raise paths.SupplyContractError('BOUNDED_PAGE_EXCEEDS_REQUEST')
        if first - 1 + len(page) > limit:
            raise paths.SupplyContractError('PATH_ROW_BUDGET_EXCEEDED:' + phase)
        if len(page) == size and previous is not None and page == previous:
            raise paths.SupplyContractError('REPEATED_BOUNDED_PAGE_NO_PROGRESS')
        previous = page if len(page) == size else None
        for row in page:
            if len(row) != len(columns):
                raise paths.SupplyContractError('BOUNDED_ROW_SCHEMA_MISMATCH')
            yield row
        stat['rows'] += len(page)
        pages += 1
        if len(page) < size:
            break
        first = last + 1


def install():
    original = paths.bounded_rows
    if getattr(original, '__r1_fixed_page_dispatch__', False):
        return
    def dispatch(obj, columns, settings, control, phase, **details):
        fn = fixed_rows if 'path_export_fixed_page_size' in settings else original
        return fn(obj, columns, settings, control, phase, **details)
    dispatch.__r1_fixed_page_dispatch__ = True
    paths.bounded_rows = dispatch
