# -*- coding: utf-8 -*-
"""Summarize DIAGFAST helper profiles of a live (or mock) parity folder.

Read-only, no Visum access. Run either from plain Python:
    python diagfast_tools/summarize_diagfast_profiles.py <PARITY_folder>
or inside Visum via Scripts > Run script file (then the newest
%LOCALAPPDATA%\\R1DF\\PARITY_* folder is used).

Writes DIAGFAST_PROFILE_SUMMARY.md and .json into that folder and prints the
markdown. Works for V1 (HOTFIX4) and V2 profiles alike.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
from pathlib import Path


def newest_parity_folder():
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'R1DF'
    folders = sorted((p for p in base.glob('PARITY_*') if p.is_dir()), key=lambda p: p.stat().st_mtime)
    if not folders:
        raise SystemExit('No PARITY_* folder under %s' % base)
    return folders[-1]


def backend_of(path):
    for part in reversed(path.parts):
        m = re.match(r'PAIR_\d+_(LEGACY|FAST_EXACT)$', part)
        if m:
            return m.group(1)
    return None


def com_budget(counts):
    b = {'scalar_AttValue': 0, 'ItemByKey': 0, 'bulk_GetMultiAttValues': 0,
         'GetValues': 0, 'GetAll': 0, 'other_property_gets': 0}
    for key, n in counts.items():
        if not key.startswith('com_attempts:'):
            continue
        label = key[len('com_attempts:'):]
        if '.AttValue:' in label or label.endswith('.AttValue'):
            b['scalar_AttValue'] += n
        elif label.endswith('.ItemByKey'):
            b['ItemByKey'] += n
        elif 'GetMultiAttValues:' in label:
            b['bulk_GetMultiAttValues'] += n
        elif label.endswith('.GetValues'):
            b['GetValues'] += n
        elif label.endswith('property:GetAll') or label.endswith('.GetAll'):
            b['GetAll'] += n
        elif '.property:' in label or label.startswith('Visum.property'):
            b['other_property_gets'] += n
    b['bulk_values'] = counts.get('v2_bulk_values', counts.get('validated_network_passenger_values', 0))
    b['com_busy_retries'] = counts.get('com_busy_retries', 0)
    return b


def med(values):
    return statistics.median(values) if values else None


def summarize(folder):
    folder = Path(folder)
    data = {}
    for path in folder.rglob('DIAGFAST_*_PROFILE*.json'):
        try:
            prof = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        backend = backend_of(path) or prof.get('backend')
        helper = prof.get('helper')
        if helper not in ('12D', '11D') or backend not in ('LEGACY', 'FAST_EXACT'):
            continue
        data.setdefault((backend, helper), []).append(prof)
    archives = {}
    for path in folder.rglob('DIAGFAST_ARCHIVE_*.json'):
        try:
            rec = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        backend = backend_of(path) or rec.get('backend')
        archives.setdefault(backend, []).append(rec.get('inclusive_seconds', 0.0))
    pair_bench = None
    bench_path = folder / 'PERFORMANCE_BENCHMARK.json'
    if bench_path.is_file():
        try:
            pair_bench = json.loads(bench_path.read_text(encoding='utf-8'))
        except Exception:
            pair_bench = None

    result = {'folder': str(folder), 'helpers': {}, 'archive_seconds_median': {},
              'pair_benchmark': None}
    if pair_bench:
        source = pair_bench.get('distributions') or pair_bench.get('benchmark') or pair_bench
        result['pair_benchmark'] = {k: (source.get(k) or {}).get('median_seconds')
                                    for k in ('LEGACY', 'FAST_EXACT')}
    for backend, values in archives.items():
        result['archive_seconds_median'][backend] = med(values)
    for (backend, helper), profs in sorted(data.items()):
        stages = {}
        for prof in profs:
            for name, rec in prof.get('stages', {}).items():
                s = stages.setdefault(name, {'inclusive': [], 'exclusive': [], 'calls': []})
                s['inclusive'].append(rec.get('inclusive_seconds', 0.0))
                s['exclusive'].append(rec.get('exclusive_seconds', 0.0))
                s['calls'].append(rec.get('calls', 0))
        budgets = [com_budget(p.get('com_and_cache_counts', {})) for p in profs]
        budget = {k: med([b[k] for b in budgets]) for k in budgets[0]} if budgets else {}
        notes = profs[-1].get('notes', {})
        result['helpers']['%s/%s' % (backend, helper)] = {
            'samples': len(profs),
            'release': profs[-1].get('release'),
            'wall_seconds_median': med([p.get('wall_clock_seconds', 0.0) for p in profs]),
            'stages': {k: {'inclusive_median': med(v['inclusive']),
                           'exclusive_median': med(v['exclusive']),
                           'calls_median': med(v['calls'])} for k, v in stages.items()},
            'com_budget_median': budget,
            'fallbacks': [f for p in profs for f in p.get('fallbacks', [])],
            'network_links': notes.get('network_links'),
            'v2_features': notes.get('v2_features'),
            'workspace_bytes': notes.get('workspace_bytes'),
        }
    return result


def markdown(result):
    lines = ['# DIAGFAST profile summary', '', 'Folder: `%s`' % result['folder'], '']
    if result.get('pair_benchmark'):
        pb = result['pair_benchmark']
        lines.append('Pair median (12D+11D incl. runtime I/O): LEGACY %s s, FAST_EXACT %s s' % (
            _f(pb.get('LEGACY')), _f(pb.get('FAST_EXACT'))))
        lines.append('')
    if result['archive_seconds_median']:
        lines.append('Runtime evidence archive median: ' + ', '.join(
            '%s %s s' % (k, _f(v)) for k, v in sorted(result['archive_seconds_median'].items())))
        lines.append('')
    for key, h in sorted(result['helpers'].items()):
        lines += ['## %s  (%d samples, release %s)' % (key, h['samples'], h['release']), '',
                  'Helper wall median: %s s; network links: %s; workspace bytes: %s' % (
                      _f(h['wall_seconds_median']), h['network_links'], h['workspace_bytes']), '',
                  '| stage | calls | inclusive s | exclusive s |', '| --- | ---: | ---: | ---: |']
        for name, s in sorted(h['stages'].items(), key=lambda kv: -(kv[1]['inclusive_median'] or 0)):
            lines.append('| %s | %s | %s | %s |' % (name, _f(s['calls_median'], 0),
                                                    _f(s['inclusive_median']), _f(s['exclusive_median'])))
        lines += ['', 'COM budget (median per helper): ' + ', '.join(
            '%s=%s' % (k, _f(v, 0)) for k, v in h['com_budget_median'].items())]
        if h['fallbacks']:
            lines.append('Fallbacks: ' + '; '.join('%s -> %s (%s)' % (f.get('from'), f.get('to'), f.get('reason'))
                                                   for f in h['fallbacks'][:6]))
        lines.append('')
    return '\n'.join(lines) + '\n'


def _f(value, digits=3):
    if value is None:
        return '-'
    if isinstance(value, float):
        return ('%.' + str(digits) + 'f') % value
    return str(value)


def main(argv=None):
    argv = [a for a in (sys.argv[1:] if argv is None else argv) if str(a).strip()]
    folder = Path(argv[0]) if argv and Path(argv[0]).is_dir() else newest_parity_folder()
    result = summarize(folder)
    text = markdown(result)
    (folder / 'DIAGFAST_PROFILE_SUMMARY.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (folder / 'DIAGFAST_PROFILE_SUMMARY.md').write_text(text, encoding='utf-8')
    print(text)
    return result


if __name__ == '__main__' or globals().get('Visum') is not None:
    main()
