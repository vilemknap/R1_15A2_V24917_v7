# -*- coding: utf-8 -*-
"""Run in opened Visum: read-only page profiling, no calibration or model writes.

Writes PATH_EXPORT_BENCHMARK_*/REPORT.json beside this script. The winner is
advisory: enable path_io.page_probe in R1_RUN_OPTIONS.json to qualify and pin a
size again inside the exact parent/assignment of a normal calibration build.
Larger pages have not been live-qualified by the offline package tests.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def main(visum=None):
    visum = visum if visum is not None else globals().get('Visum')
    if visum is None:
        visum = globals().get('COM')
    if visum is None:
        raise RuntimeError('NO_INJECTED_VISUM')
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    for name, module in list(sys.modules.items()):
        if name.startswith('r1_15a2_'):
            source = getattr(module, '__file__', None)
            if source and Path(source).resolve().parent != HERE:
                raise RuntimeError('PATH_PAGE_PROBE_WRONG_MODULE_ORIGIN:' + name)
    import r1_15a2_path_export_probe_v24917 as probe
    import r1_15a2_path_cache_publish_v24917 as publication
    import r1_15a2_two_mode_v238 as paths
    codes = sorted(set().union(*paths.EXPECTED_MODE_DSEGS.values()))
    # Use the approved live spelling; the normalizer maps *_noT to *_NOT.
    cfg = {'path_export_dsegs': codes}
    out = HERE / ('PATH_EXPORT_BENCHMARK_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir(exist_ok=False)
    opts = publication.options(HERE)
    settings = dict(paths.DEFAULT_SETTINGS)
    settings['max_runtime_seconds'] = 3600.
    control = paths.RunControl(out, settings)

    def binding():
        zones = sorted(paths.com.get_multi_att_values(visum.Net.Zones, 'NO'))
        nos = [paths._id(row[1]) for row in zones]
        if len(nos) != 681 or len(set(nos)) != 681:
            raise RuntimeError('PATH_PAGE_PROBE_EXPECTED_681_UNIQUE_ZONES')
        segments = paths.rt.selected_passenger_dsegs(visum, cfg)
        if {r['norm_code'] for r in segments} != set(codes):
            raise RuntimeError('PATH_PAGE_PROBE_EXPECTED_12_PASSENGER_DSEGS')
        return {'zone_order': zones, 'matrices': {
            r['norm_code']: paths.read_matrix_authority(r, 681) for r in segments}}

    try:
        before = binding()
        report = probe.benchmark(visum, settings, control,
            candidates=opts['probe_candidates'], starts=opts['probe_starts'],
            repetitions=opts['probe_repetitions'], memory_limit_mib=opts['probe_memory_mib'])
        if binding() != before:
            raise RuntimeError('PATH_PAGE_PROBE_MODEL_CHANGED')
        report.update(binding_hash=paths.canonical_hash(before), advisory_only=True,
                      model_modified=False, assignment_executed=False)
        paths.atomic_json(out / 'REPORT.json', report)
        control.finish('COMPLETE', selected_page_size=report['selected_page_size'])
        print('PATH EXPORT PROBE: page_size=%d; report=%s' % (report['selected_page_size'], out / 'REPORT.json'))
        return report
    except BaseException as exc:
        paths.atomic_json(out / 'FAILED.json', {'error': type(exc).__name__ + ':' + str(exc),
                                              'model_modified': False,
                                              'probe_report': getattr(exc, 'probe_report', None)})
        control.finish('FAILED', error=str(exc))
        raise


if __name__ == '__main__' or globals().get('Visum') is not None or globals().get('COM') is not None:
    main()
