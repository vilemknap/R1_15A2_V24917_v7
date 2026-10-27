# -*- coding: utf-8 -*-
"""DIRECT start of the calibration with DIAGFAST V2, without a separate parity run.

Replaces the manual live-parity certificate by two automatic guards inside the
calibration run itself:

1. Inline parity: before the first N calls of 12D and of 11D (default N=1)
   the helper runs once in LEGACY and once in FAST_EXACT into two scratch
   folders, exactly as R1_15A2_DIAGFAST_LIVE_PARITY.py does, and all artifacts
   (incl. ZIP payloads) are compared without rounding. Only on PARITY_PASS the
   real call runs in FAST_EXACT; the report goes to DIRECT_PARITY_*.json.
2. LEGACY fallback: if the inline audit or a FAST_EXACT helper raises (parity
   mismatch, V2 fault, anything else), the same helper is re-run in LEGACY. If
   LEGACY succeeds the rest of the run stays LEGACY (FAST-specific problem); if
   LEGACY fails too, its exception propagates unchanged (a genuine model/data
   error, handled by the calibrator exactly as before) and the mode is kept.

Every decision is appended to %LOCALAPPDATA%\\R1DF\\DIRECT_GUARD_<stamp>_<id>.jsonl.
No model writes, no Visum Execute/Save/Load, no change to TG/TD, acceptance or
diagnostic science. Environment switches:
    R1_DIAGFAST_INLINE_PARITY = number of audited calls per helper (default 1, 0 = off)
    R1_DIAGFAST_BACKEND=LEGACY  -> whole run in LEGACY
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

import r1_15a2_diagfast_v1 as df
import r1_15a2_diagfast_v2 as v2

STATUS = 'DIRECT_NO_LIVE_CERTIFICATE_INLINE_PARITY_THEN_FAST_EXACT_WITH_LEGACY_FALLBACK'
INLINE_ENV = 'R1_DIAGFAST_INLINE_PARITY'
_CFG_POSITION = {'12D': 0, '11D': 1}     # run_12d(v,out,label,cfg) / run_11d(v,out,label,d12,cfg)


def default_log_dir():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'R1DF'


def inline_parity_count():
    raw = os.environ.get(INLINE_ENV, '1').strip()
    try:
        value = int(raw)
    except ValueError:
        raise df.DiagFastError('DIAGFAST_DIRECT_INVALID_%s:%r' % (INLINE_ENV, raw))
    if value < 0:
        raise df.DiagFastError('DIAGFAST_DIRECT_INVALID_%s:%r' % (INLINE_ENV, raw))
    return value


def _with_backend(kind, args, kwargs, backend):
    args, kwargs = list(args), dict(kwargs)
    if 'cfg' in kwargs:
        kwargs['cfg'] = dict(kwargs['cfg'] or {}, diagnostics_backend=backend)
    else:
        pos = _CFG_POSITION[kind]
        if len(args) > pos:
            args[pos] = dict(args[pos] or {}, diagnostics_backend=backend)
        else:
            kwargs['cfg'] = {'diagnostics_backend': backend}
    return args, kwargs


class DirectGuard:
    def __init__(self, rt, inline_parity=1, start_mode='FAST_EXACT', log_dir=None, print_fn=print):
        if start_mode not in ('FAST_EXACT', 'LEGACY'):
            raise df.DiagFastError('DIAGFAST_DIRECT_INVALID_START_MODE:' + str(start_mode))
        self.rt = rt
        self.mode = start_mode
        self.remaining_parity = {'12D': int(inline_parity), '11D': int(inline_parity)}
        self.inline_parity = int(inline_parity)
        self.print = print_fn
        folder = Path(log_dir) if log_dir else default_log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self.log_path = folder / ('DIRECT_GUARD_%s_%s.jsonl' % (time.strftime('%Y%m%d_%H%M%S'),
                                                               uuid.uuid4().hex[:6]))
        self.counts = {'calls': 0, 'parity_pass': 0, 'fast': 0, 'legacy': 0, 'fallbacks': 0}
        self.originals = {'12D': rt.run_12d, '11D': rt.run_11d}
        self.event('START', mode=self.mode, inline_parity=self.inline_parity,
                   release=df.RELEASE, v2_release=v2.RELEASE_V2)

    # -- evidence ---------------------------------------------------------------
    def event(self, kind, **data):
        record = dict(data, event=kind, time=time.strftime('%Y-%m-%dT%H:%M:%S'))
        try:
            with self.log_path.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
        except Exception as exc:      # evidence must never stop the calibration
            self.print('DIAGFAST_DIRECT_LOG_WARNING', repr(exc))
        if kind not in ('CALL_OK',):
            self.print('DIAGFAST_DIRECT', kind, json.dumps(data, default=str)[:600])

    def certificate(self):
        """Value stored as launcher._diagfast_live_certificate (EFFECTIVE_CONFIG)."""
        return {'status': STATUS,
                'scope': 'INLINE_PARITY_AUDIT_FIRST_%d_CALLS_PER_HELPER_THEN_FAST_EXACT' % self.inline_parity,
                'report_folder': str(self.log_path)}

    # -- routing ----------------------------------------------------------------
    def install(self):
        self.rt.run_12d = self.wrap('12D')
        self.rt.run_11d = self.wrap('11D')
        return self

    def wrap(self, kind):
        original = self.originals[kind]

        def run(visum, out_dir, label, *args, **kwargs):
            self.counts['calls'] += 1
            if self.mode == 'LEGACY':
                return self._call(original, kind, 'LEGACY', visum, out_dir, label, args, kwargs)
            audited = self.remaining_parity[kind] > 0
            backend = 'INLINE_PARITY+FAST_EXACT' if audited else 'FAST_EXACT'
            try:
                if audited:
                    self._inline_audit(original, kind, visum, label, args, kwargs)
                result = self._call(original, kind, 'FAST_EXACT', visum, out_dir, label, args, kwargs)
            except (Exception, v2.BulkLateFault) as first:
                self.counts['fallbacks'] += 1
                self.event('FAST_PATH_FAILED_RERUN_LEGACY', helper=kind, label=str(label),
                           backend=backend, error=repr(first)[:2000])
                try:
                    result = self._call(original, kind, 'LEGACY', visum, out_dir, label, args, kwargs)
                except Exception as legacy_error:
                    self.event('LEGACY_ALSO_FAILED_GENUINE_ERROR_PROPAGATED', helper=kind,
                               label=str(label), error=repr(legacy_error)[:2000])
                    raise
                self.mode = 'LEGACY'
                self.event('SWITCHED_TO_LEGACY_FOR_REST_OF_RUN', helper=kind, label=str(label))
                return result
            if audited:
                self.remaining_parity[kind] -= 1
                self.counts['parity_pass'] += 1
                self.event('INLINE_PARITY_PASS', helper=kind, label=str(label),
                           remaining=self.remaining_parity[kind])
            return result
        run.__name__ = 'run_' + kind.lower() + '_direct_guard'
        run.__wrapped__ = original
        return run

    def _inline_audit(self, original, kind, visum, label, args, kwargs):
        """LEGACY and FAST_EXACT into twin scratch folders, exact artifact comparison."""
        import r1_15a2_diagfast_parity_v1 as parity
        base = Path(tempfile.mkdtemp(prefix='R1DFD_'))
        legacy_dir, fast_dir = base / 'L', base / 'F'
        self._call(original, kind, 'LEGACY', visum, legacy_dir, label, args, kwargs)
        self._call(original, kind, 'FAST_EXACT', visum, fast_dir, label, args, kwargs)
        report = parity.compare_artifacts(legacy_dir, fast_dir, scope='DIRECT_INLINE_AUDIT')
        report['helper'], report['label'] = kind, str(label)
        report_path = self.log_path.with_name('DIRECT_PARITY_%s_%s_%s.json' % (
            self.log_path.stem.replace('DIRECT_GUARD_', ''), kind, uuid.uuid4().hex[:6]))
        try:
            report_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        except Exception as exc:
            self.print('DIAGFAST_DIRECT_LOG_WARNING', repr(exc))
        self.event('INLINE_PARITY_REPORT', helper=kind, label=str(label), status=report['status'],
                   artifacts=report['artifact_count'], equal=report['equal_artifacts'],
                   report=str(report_path), scratch=str(base))
        if report['status'] != 'PARITY_PASS':
            raise df.DiagFastError('DIAGFAST_DIRECT_INLINE_PARITY_FAILED:%s:%s' % (
                kind, ','.join(report['failures'][:10])))
        shutil.rmtree(str(base), ignore_errors=True)
        return report

    def _call(self, original, kind, backend, visum, out_dir, label, args, kwargs):
        a, k = _with_backend(kind, args, kwargs, backend)
        start = time.perf_counter()
        result = original(visum, out_dir, label, *a, **k)
        self.counts['legacy' if backend == 'LEGACY' else 'fast'] += 1
        self.event('CALL_OK', helper=kind, label=str(label), backend=backend,
                   seconds=round(time.perf_counter() - start, 3))
        return result


def install(launcher, inline_parity=None, start_mode=None, log_dir=None, print_fn=print):
    """Wrap the activated DIAGFAST runtime of a prepared launcher."""
    if inline_parity is None:
        inline_parity = inline_parity_count()
    if start_mode is None:
        start_mode = 'LEGACY' if os.environ.get('R1_DIAGFAST_BACKEND', '').strip().upper() == 'LEGACY' \
            else 'FAST_EXACT'
    guard = DirectGuard(launcher.rt, inline_parity, start_mode, log_dir, print_fn).install()
    launcher._diagfast_live_certificate = guard.certificate()
    launcher._diagfast_direct_guard = guard
    return guard
