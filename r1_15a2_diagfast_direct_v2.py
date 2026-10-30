# -*- coding: utf-8 -*-
"""DIRECT start of the calibration with DIAGFAST V2, without a separate parity run.

Replaces the manual live-parity certificate by two automatic guards inside the
calibration run itself:

1. RELAXED semantic parity: before the first N calls of 12D/11D, compare
   JSON/CSV numeric values using a 0.1% relative / 0.001 absolute envelope.
   Tiny zero crossings are tolerated; selected derived diagnostic output SHA
   fields may differ if the same report contains verified numeric payload.
   Source/model/cache hashes, IDs, dimensions and decisions stay exact.
2. Adaptive parity: if full V2 differs materially, repeat the same bounded
   comparison with narrowly disabled optional V2 features. Only a verified
   PARITY_PASS authorizes that reduced FAST_EXACT configuration.
3. Per-helper LEGACY fallback: if no configuration passes, rerun only the
   affected helper in LEGACY; do not downgrade the independently certified
   other helper. Legacy also failing still propagates the genuine model error.
   Materially different numbers and incomplete parity are never accepted.

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

STATUS = 'DIRECT_INLINE_RELAXED_SEMANTIC_PARITY_FEATURE_ISOLATION_PER_HELPER_LEGACY_FALLBACK'
INLINE_ENV = 'R1_DIAGFAST_INLINE_PARITY'
_CFG_POSITION = {'12D': 0, '11D': 1}     # run_12d(v,out,label,cfg) / run_11d(v,out,label,d12,cfg)
# Retry ONLY a structural/material parity failure, not a model/data read error.
# Each retry disables one optional feature and must pass the SAME bounded-float
# comparison; the safe numeric thresholds and exact nonnumeric schema remain.
_PARITY_RETRY_FEATURES = {
    '12D': ({'bulk_12d_links': False}, {'bulk_12d_countlocations': False}),
    '11D': ({'numpy_11d': False},
            {'bulk_11d_matrices': False},
            {'bulk_11d_countlocations': False}),
}



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


def _with_backend(kind, args, kwargs, backend, feature_limits=None):
    args, kwargs = list(args), dict(kwargs)
    if 'cfg' in kwargs:
        cfg = dict(kwargs['cfg'] or {})
        kwargs['cfg'] = cfg
    else:
        pos = _CFG_POSITION[kind]
        if len(args) > pos:
            cfg = dict(args[pos] or {})
            args[pos] = cfg
        else:
            cfg = {}
            kwargs['cfg'] = cfg
    cfg['diagnostics_backend'] = backend
    if feature_limits:
        opts = dict(cfg.get('diagfast_v2') or {})
        # Caller-enforced disabled features cannot be re-enabled here.
        for name, value in feature_limits.items():
            if value is not False:
                raise df.DiagFastError('DIAGFAST_DIRECT_RETRY_MUST_ONLY_DISABLE:' + name)
            opts[name] = False
        cfg['diagfast_v2'] = opts
    return args, kwargs


class DirectGuard:
    def __init__(self, rt, inline_parity=1, start_mode='FAST_EXACT', log_dir=None, print_fn=print):
        if start_mode not in ('FAST_EXACT', 'LEGACY'):
            raise df.DiagFastError('DIAGFAST_DIRECT_INVALID_START_MODE:' + str(start_mode))
        self.rt = rt
        self.mode = start_mode
        self.helper_mode = {'12D': start_mode, '11D': start_mode}
        self.feature_limits = {'12D': {}, '11D': {}}
        self.remaining_parity = {'12D': int(inline_parity), '11D': int(inline_parity)}
        self.inline_parity = int(inline_parity)
        self.print = print_fn
        folder = Path(log_dir) if log_dir else default_log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self.log_path = folder / ('DIRECT_GUARD_%s_%s.jsonl' % (time.strftime('%Y%m%d_%H%M%S'),
                                                               uuid.uuid4().hex[:6]))
        self.counts = {'calls': 0, 'parity_pass': 0, 'fast': 0, 'legacy': 0, 'fallbacks': 0,
                       'strict_feature_retry_attempts': 0, 'strict_feature_retry_passes': 0}
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
                'scope': 'RELAXED_SEMANTIC_INLINE_PARITY_WITH_FEATURE_ISOLATION_PER_HELPER_FIRST_%d_CALLS' % self.inline_parity,
                'report_folder': str(self.log_path),
                'numeric_parity_relaxed': True,
                'numeric_parity_abs_tol': 1e-3,
                'numeric_parity_rel_tol': 1e-3,
                'numeric_parity_zero_cross_noise_floor': 1e-6,
                'derived_diagnostic_digest_parity_relaxed': True,
                'source_authority_and_manifest_sha_exact': True,
                'numeric_parity_identifiers_exact': True,
                'legacy_fallback_scope': 'AFFECTED_HELPER_ONLY'}

    # -- routing ----------------------------------------------------------------
    def install(self):
        self.rt.run_12d = self.wrap('12D')
        self.rt.run_11d = self.wrap('11D')
        return self

    def wrap(self, kind):
        original = self.originals[kind]

        def run(visum, out_dir, label, *args, **kwargs):
            self.counts['calls'] += 1
            if self.helper_mode[kind] == 'LEGACY':
                return self._call(original, kind, 'LEGACY', visum, out_dir, label, args, kwargs)
            audited = self.remaining_parity[kind] > 0
            backend = 'INLINE_PARITY+FAST_EXACT' if audited else 'FAST_EXACT'
            try:
                if audited:
                    audit_report = self._audit_with_feature_isolation(
                        original, kind, visum, label, args, kwargs)
                result = self._call(original, kind, 'FAST_EXACT', visum, out_dir, label,
                                    args, kwargs, self.feature_limits[kind])
            except (Exception, v2.BulkLateFault) as first:
                self.counts['fallbacks'] += 1
                self.event('FAST_PATH_FAILED_RERUN_LEGACY', helper=kind, label=str(label),
                           backend=backend, error=repr(first)[:2000],
                           feature_limits=self.feature_limits[kind])
                try:
                    result = self._call(original, kind, 'LEGACY', visum, out_dir, label, args, kwargs)
                except Exception as legacy_error:
                    self.event('LEGACY_ALSO_FAILED_GENUINE_ERROR_PROPAGATED', helper=kind,
                               label=str(label), error=repr(legacy_error)[:2000])
                    raise
                # A 11D mismatch must NEVER downgrade already certified 12D
                # to LEGACY (nor vice versa). No unverified FAST output survives.
                self.helper_mode[kind] = 'LEGACY'
                self.mode = ('LEGACY' if all(x == 'LEGACY' for x in self.helper_mode.values())
                             else 'MIXED')
                self.event('SWITCHED_HELPER_TO_LEGACY', helper=kind, label=str(label),
                           helper_modes=dict(self.helper_mode), run_mode=self.mode)
                return result
            if audited:
                self.remaining_parity[kind] -= 1
                self.counts['parity_pass'] += 1
                self.event('INLINE_PARITY_PASS', helper=kind, label=str(label),
                           remaining=self.remaining_parity[kind],
                           strict_feature_limits=self.feature_limits[kind],
                           tolerated_values=audit_report.get('tolerated_value_count', 0),
                           tolerated_artifacts=audit_report.get('tolerated_artifacts', 0),
                           max_tolerated_abs_difference=audit_report.get(
                               'max_tolerated_abs_difference', 0.0),
                           tolerated_derived_digests=audit_report.get(
                               'tolerated_derived_digest_count', 0))
            return result
        run.__name__ = 'run_' + kind.lower() + '_direct_guard'
        run.__wrapped__ = original
        return run

    def _audit_with_feature_isolation(self, original, kind, visum, label, args, kwargs):
        """Retry only true parity failures; never waive material/scientific drift."""
        try:
            return self._inline_audit(original, kind, visum, label, args, kwargs,
                                      self.feature_limits[kind])
        except df.DiagFastError as first:
            if not str(first).startswith('DIAGFAST_DIRECT_INLINE_PARITY_FAILED:'):
                raise
            self.event('BOUNDED_PARITY_MISMATCH_REDUCE_FEATURES', helper=kind,
                       label=str(label), original_error=str(first)[:1600])
            for limits in _PARITY_RETRY_FEATURES[kind]:
                self.counts['strict_feature_retry_attempts'] += 1
                try:
                    report = self._inline_audit(original, kind, visum, label,
                                                args, kwargs, limits)
                except df.DiagFastError as exc:
                    # Model/COM errors are not optional features; they must go
                    # through the original, fully verified LEGACY failure path.
                    if not str(exc).startswith('DIAGFAST_DIRECT_INLINE_PARITY_FAILED:'):
                        raise
                    self.event('BOUNDED_PARITY_RETRY_REJECTED', helper=kind,
                               label=str(label), feature_limits=limits,
                               error=str(exc)[:1600])
                    continue
                self.feature_limits[kind] = dict(limits)
                self.counts['strict_feature_retry_passes'] += 1
                self.event('FAST_FEATURES_REDUCED_BOUNDED_PARITY_PASS', helper=kind,
                           label=str(label), feature_limits=limits,
                           artifact_count=report['artifact_count'])
                return report
            raise first  # original failure, original report still available

    def _inline_audit(self, original, kind, visum, label, args, kwargs,
                      feature_limits=None):
        """Isolated LEGACY-vs-FAST; strict structure, bounded numeric parity."""
        import r1_15a2_diagfast_parity_v1 as parity
        base = Path(tempfile.mkdtemp(prefix='R1DFD_'))
        legacy_dir, fast_dir = base / 'L', base / 'F'
        self._call(original, kind, 'LEGACY', visum, legacy_dir, label, args, kwargs)
        self._call(original, kind, 'FAST_EXACT', visum, fast_dir, label,
                   args, kwargs, feature_limits)
        report = parity.compare_artifacts(legacy_dir, fast_dir, scope='DIRECT_INLINE_AUDIT',
                                          numeric_tolerance=True)
        report['helper'], report['label'] = kind, str(label)
        report['feature_limits'] = dict(feature_limits or {})
        report_path = self.log_path.with_name('DIRECT_PARITY_%s_%s_%s.json' % (
            self.log_path.stem.replace('DIRECT_GUARD_', ''), kind, uuid.uuid4().hex[:6]))
        try:
            report_path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        except Exception as exc:
            self.print('DIAGFAST_DIRECT_LOG_WARNING', repr(exc))
        self.event('INLINE_PARITY_REPORT', helper=kind, label=str(label), status=report['status'],
                   artifacts=report['artifact_count'], equal=report['equal_artifacts'],
                   report=str(report_path), scratch=str(base),
                   feature_limits=report['feature_limits'], failures=report['failures'][:10],
                   tolerated_values=report['tolerated_value_count'],
                   max_abs_delta=report['max_tolerated_abs_difference'],
                   tolerated_derived_digests=report['tolerated_derived_digest_count'])
        if report['status'] != 'PARITY_PASS':
            raise df.DiagFastError('DIAGFAST_DIRECT_INLINE_PARITY_FAILED:%s:%s' % (
                kind, ','.join(report['failures'][:10])))
        shutil.rmtree(str(base), ignore_errors=True)
        return report

    def _call(self, original, kind, backend, visum, out_dir, label, args, kwargs,
              feature_limits=None):
        a, k = _with_backend(kind, args, kwargs, backend, feature_limits)
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
