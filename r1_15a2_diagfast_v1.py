# -*- coding: utf-8 -*-
"""Scoped, read-only diagnostic overlay. No model access or activation on import.

Reference numerical functions remain untouched on disk. V1 selects live links and
shares immutable matrix values within ONE helper invocation. V2 (FAST_EXACT only,
module r1_15a2_diagfast_v2) adds probe-verified bulk COM columns and bitwise-exact
sequential NumPy sums for the three 11D matrix loops; every technical mismatch
falls back to the V1/reference path.
"""
from __future__ import annotations
import ast
import contextlib
import contextvars
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import time
from types import SimpleNamespace
import zipfile
import r1_15a2_com_compat as com

ROOT = Path(__file__).resolve().parent
RELEASE = 'R1_15A2_DIAGFAST_V2_BULK_NUMPY_20261024'
HELPERS = {
    '12D': 'R1_12D_CURRENT_COUNTLOCATION_488_ALL_CALIBRATION_20261022.py',
    '11D': 'R1_11D_V1_3_COMPONENT_DIST_BEHAVIOR_DIAGNOSTICS.py',
}
MODES = ('LEGACY', 'FAST_EXACT', 'PARITY_AUDIT')
CONTEXT = contextvars.ContextVar('r1_diagfast_context', default=None)

class DiagFastError(RuntimeError):
    pass

class ReadOnlyViolation(DiagFastError):
    pass

class CapabilityUnavailable(DiagFastError):
    def __init__(self, original):
        self.original = original
        super().__init__(repr(original))


def mode(value):
    value = str(value).upper().strip()
    if value not in MODES:
        raise DiagFastError('DIAGFAST_INVALID_BACKEND:' + value)
    return value


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_integrity(root=ROOT, include_overlay=True):
    """Exact parent identity; extra files allowed, no original removed or replaced."""
    root = Path(root)
    mf = json.loads((root / 'DIAGFAST_V1_BASE_MANIFEST.json').read_text('utf-8'))
    failures = []
    for name, expected in mf['files'].items():
        path = root / name
        if not path.is_file() or digest_file(path) != expected:
            failures.append(name)
    if include_overlay:
        own = root / 'DIAGFAST_V1_RELEASE_MANIFEST.json'
        if not own.is_file():
            raise DiagFastError('DIAGFAST_RELEASE_MANIFEST_MISSING')
        for name, expected in json.loads(own.read_text('utf-8'))['files'].items():
            if not (root/name).is_file() or digest_file(root/name) != expected:
                failures.append(name)
    if failures:
        raise DiagFastError('DIAGFAST_SOURCE_INTEGRITY_FAILED:' + ','.join(failures[:30]))
    return {'status': 'PASS', 'parent_files_checked': len(mf['files']),
            'parent_archive_sha256': mf['archive_sha256'], 'overlay_checked': include_overlay}


class Profile:
    """Aggregated nested spans. No per-link/cell events or file I/O."""
    def __init__(self, helper, backend, enabled=True):
        self.helper, self.backend, self.enabled = helper, backend, enabled
        self.started = time.perf_counter()
        self.stages, self.counts, self.matrix_reads = {}, {}, {}
        self.matrix_shapes = {}
        self.stack, self.fallbacks = [], []
        self.notes = {}

    def count(self, key, n=1):
        if self.enabled:
            self.counts[key] = self.counts.get(key, 0) + n

    @contextlib.contextmanager
    def span(self, name):
        if not self.enabled:
            yield
            return
        entry = [time.perf_counter(), 0.0]
        self.stack.append(entry)
        try:
            yield
        finally:
            elapsed = time.perf_counter() - entry[0]
            self.stack.pop()
            rec = self.stages.setdefault(name, {'calls': 0, 'inclusive_seconds': 0.0,
                                                'exclusive_seconds': 0.0, 'max_seconds': 0.0})
            rec['calls'] += 1
            rec['inclusive_seconds'] += elapsed
            rec['exclusive_seconds'] += max(0.0, elapsed - entry[1])
            rec['max_seconds'] = max(rec['max_seconds'], elapsed)
            if self.stack:
                self.stack[-1][1] += elapsed

    def report(self, status='PASS'):
        return {'schema': 'R1_DIAGFAST_HELPER_PROFILE_V1', 'release': RELEASE,
                'helper': self.helper, 'backend': self.backend, 'status': status,
                'wall_clock_seconds': time.perf_counter()-self.started,
                'stages': self.stages, 'com_and_cache_counts': self.counts,
                'matrix_reads_by_no': self.matrix_reads, 'matrix_shapes_by_no': self.matrix_shapes,
                'fallbacks': self.fallbacks,
                'notes': self.notes, 'model_writes_allowed': False,
                'scope': 'ONE_HELPER_INVOCATION_NO_CROSS_STATE_CACHE',
                'inclusive_spans_may_overlap': True}


def _retry(prof, policy, label, call):
    def attempt():
        prof.count('com_attempts:' + label)
        return call()
    try:
        return com.com_call_with_retry(attempt, label='DIAGFAST:'+label,
                                       retry_policy=policy,
                                       on_retry=lambda e: prof.count('com_busy_retries'))
    except Exception as exc:
        if com.is_retryable_com_error(exc):
            prof.notes['terminal_com_busy_error'] = repr(exc)
        raise


class ReadOnlyProxy:
    """Guards helper access, counts actual read attempts, preserves raw values."""
    __slots__ = ('_obj', '_prof', '_policy', '_path')
    def __init__(self, obj, prof, policy=None, path='Visum'):
        object.__setattr__(self, '_obj', obj)
        object.__setattr__(self, '_prof', prof)
        object.__setattr__(self, '_policy', policy or {})
        object.__setattr__(self, '_path', path)

    def __setattr__(self, name, value):
        raise ReadOnlyViolation('DIAGFAST_COM_WRITE_FORBIDDEN:'+name)

    def __getattr__(self, name):
        if name.lower().startswith(('set', 'add', 'remove', 'delete', 'execute', 'save', 'load')):
            raise ReadOnlyViolation('DIAGFAST_COM_MUTATOR_FORBIDDEN:'+name)
        obj, prof, policy, path = self._obj, self._prof, self._policy, self._path
        value = _retry(prof, policy, path+'.property:'+name, lambda: getattr(obj, name))
        # COM dispatch objects themselves can be callable (default member).
        # A callable Net/Matrices property is NOT a bound COM read method.
        read_methods = {'AttValue', 'AttrExists', 'GetValues', 'GetMultiAttValues',
                        'GetPath', 'GetAll', 'ItemByKey', 'ItemByNum', 'GetDataRow',
                        # Read-only Visum 2026 native TD DStrat accessor.
                        # Essential for sealed 16-stratum 09C + frozen FOREIGN.
                        'TripDistributionDStratParameters'}
        if callable(value) and name in read_methods:
            def read(*args, **kwargs):
                label = path+'.'+name
                if name in ('AttValue', 'GetMultiAttValues') and args:
                    label += ':'+str(args[0])
                result = _retry(prof, policy, label, lambda: value(*args, **kwargs))
                if name in ('GetValues', 'GetMultiAttValues', 'AttValue', 'GetPath'):
                    return result
                return _wrap(result, prof, policy, path+'.'+name)
            return read
        return _wrap(value, prof, policy, path+'.'+name)

    def __iter__(self):
        for item in self._obj:
            yield _wrap(item, self._prof, self._policy, self._path+'.item')


def _wrap(value, prof, policy, path):
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return value
    if isinstance(value, ReadOnlyProxy):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_wrap(x, prof, policy, path+'.item') for x in value)
    if isinstance(value, dict):
        return value
    return ReadOnlyProxy(value, prof, policy, path)


def reference_namespace(kind, workspace, visum=None, print_fn=print):
    """Load hash-pinned reference definitions; remove ONLY 12D autostart Try."""
    path = ROOT / 'helpers' / HELPERS[kind]
    expected = json.loads((ROOT/'DIAGFAST_V1_BASE_MANIFEST.json').read_text('utf-8'))['files']['helpers/'+path.name]
    if digest_file(path) != expected:
        raise DiagFastError('DIAGFAST_REFERENCE_HASH_MISMATCH:'+path.name)
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    final = tree.body[-1]
    if kind == '12D':
        if not (isinstance(final, ast.Try) and len(final.body) == 1
                and isinstance(final.body[0], ast.Expr)
                and isinstance(final.body[0].value, ast.Call)
                and isinstance(final.body[0].value.func, ast.Name)
                and final.body[0].value.func.id == 'main'):
            raise DiagFastError('DIAGFAST_REFERENCE_BOOTSTRAP_CONTRACT_CHANGED')
        tree.body.pop()
        entry_body = [final]
    else:
        if not isinstance(final, ast.If) or not final.body or not isinstance(final.body[0], ast.Try):
            raise DiagFastError('DIAGFAST_REFERENCE_BOOTSTRAP_CONTRACT_CHANGED')
        entry_body = final.body
    # Preserve the reference failure artifact and fatal logging paths exactly,
    # while keeping plain definition loading free of execution side effects.
    entry = ast.parse('def _diagfast_reference_entry():\n    pass\n').body[0]
    entry.body = entry_body
    entry.lineno = final.lineno
    entry.end_lineno = final.end_lineno
    tree.body.append(entry)
    ast.fix_missing_locations(tree)
    env = {'__name__': '_r1_diagfast_reference_'+kind, '__file__': str(Path(workspace)/path.name),
           'Visum': visum, 'print': print_fn}
    exec(compile(tree, str(path), 'exec'), env, env)
    return env


def _timed(env, name, prof, stage):
    fn = env[name]
    @functools.wraps(fn)
    def call(*args, **kwargs):
        with prof.span(stage):
            return fn(*args, **kwargs)
    env[name] = call


def technical_capability_error(exc):
    return isinstance(exc, (AttributeError, TypeError, NotImplementedError)) or com.com_error_hresult(exc) in (
        -2147352573,  # DISP_E_MEMBERNOTFOUND
        -2147352562,  # DISP_E_BADPARAMCOUNT
        -2147024809,  # E_INVALIDARG (safe scalar identity fallback only)
    )


def exact_id(value):
    if isinstance(value, bool) or value is None:
        raise DiagFastError('DIAGFAST_INVALID_ID:'+repr(value))
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DiagFastError('DIAGFAST_INVALID_ID:'+repr(value)) from exc
    if not math.isfinite(x) or not x.is_integer():
        raise DiagFastError('DIAGFAST_INVALID_ID:'+repr(value))
    return int(x)


def requested_keys(manifest):
    out = dict()
    for row in manifest.values():
        key = tuple(exact_id(row[k]) for k in ('current_link_no','current_from_node_no','current_to_node_no'))
        out[key] = None
        if row.get('observation_direction') == 'BOTH':
            if key[1] == key[2]:
                raise DiagFastError('CITY90 BOTH reverse directed link unavailable:'+str(key))
            out[(key[0],key[2],key[1])] = None
    return list(out)


def _identity(obj, env):
    return tuple(env['as_int'](env['att'](obj, names)) for names in
                 (['NO','No'], ['FROMNODENO','FromNodeNo'], ['TONODENO','ToNodeNo']))


def _scalar_selected(items, wanted, env):
    by_key = {}
    for obj in items:
        key = _identity(obj, env)
        if key in wanted:
            if key in by_key:
                raise DiagFastError('DIAGFAST_DUPLICATE_DIRECTED_KEY:'+str(key))
            by_key[key] = obj
    return by_key


def _capability_call(call):
    try:
        return call()
    except Exception as exc:
        if technical_capability_error(exc):
            raise CapabilityUnavailable(exc) from exc
        raise


def _bulk_values(collection, attribute):
    # Only invocation/signature errors permit capability fallback. Malformed
    # values returned by a successful invocation are DATA errors, never fallback.
    def invoke():
        method = collection.GetMultiAttValues
        try:
            return method(attribute, False)
        except TypeError:
            return method(attribute)
    raw = _capability_call(invoke)
    if raw is None or isinstance(raw, (str, bytes, dict)):
        raise DiagFastError('DIAGFAST_BULK_DATA_SCHEMA:'+attribute)
    try:
        rows = list(raw)
    except (TypeError, ValueError) as exc:
        raise DiagFastError('DIAGFAST_BULK_DATA_SCHEMA:'+attribute) from exc
    result = []
    for row in rows:
        if not isinstance(row,(tuple,list)) or len(row)!=2:
            raise DiagFastError('DIAGFAST_BULK_DATA_ROW_SCHEMA:'+attribute)
        result.append((exact_id(row[0]),row[1]))
    return result


def sparse_link_index(v, probes, env, legacy, manifest, prof):
    wanted = requested_keys(manifest)
    wanted_set = set(wanted)
    items = env['collection_items'](v.Net.Links)
    prof.notes['network_links'] = len(items)
    prof.notes['requested_unique_links'] = len(wanted)
    by_key = None
    # Bulk row IDs are JOINED, never assumed to match GetAll positions.
    try:
        cols = []
        for attr in ('NO','FROMNODENO','TONODENO'):
            raw = _bulk_values(v.Net.Links, attr)
            col = {}
            for row in raw:
                if len(row) != 2:
                    raise DiagFastError('DIAGFAST_BULK_IDENTITY_MALFORMED:'+attr)
                idx, val = row
                if idx in col:
                    raise DiagFastError('DIAGFAST_BULK_DUPLICATE_ROW:'+str(idx))
                col[idx] = exact_id(val)
            cols.append(col)
        if not all(set(c)==set(cols[0]) for c in cols) or len(cols[0]) != len(items):
            raise DiagFastError('DIAGFAST_BULK_IDENTITY_COVERAGE_MISMATCH')
        keys = [tuple(c[i] for c in cols) for i in cols[0]]
        keyset = set(keys)
        if len(keys) != len(keyset):
            raise DiagFastError('DIAGFAST_DUPLICATE_DIRECTED_KEY')
        endpoints = {}
        for k in keys:
            endpoints.setdefault(k[1:], []).append(k)
        for k in wanted:
            if k not in keyset:
                raise DiagFastError('APPROVED physical directed link unavailable:'+str(k))
            if len(endpoints[k[1:]]) != 1:
                raise DiagFastError('DIAGFAST_AMBIGUOUS_PARALLEL_LINK:'+str(k))
        # The reference also fails on invalid passenger volumes OUTSIDE the
        # profile roster. Preserve this failure coverage with 12 bulk sweeps,
        # not per-link COM traffic. These values are validation only: profile
        # values still come from the original required_model_volume path.
        class RawValue:
            def __init__(self,value): self.value=value
            def AttValue(self,name): return self.value
        with prof.span('DIAG_12D_REQUIRED_VOLUME_SWEEP'):
            for ds in env['PASSENGER_DSEGS']:
                attr='VOLVEH_DSEG(%s,AP)' % ds
                raw=_bulk_values(v.Net.Links,attr)
                if len(raw)!=len(cols[0]) or {r[0] for r in raw}!=set(cols[0]):
                    raise DiagFastError('DIAGFAST_BULK_VOLUME_COVERAGE_MISMATCH:'+attr)
                for idx,value in raw:
                    env['required_model_volume'](RawValue(value),attr)
                prof.count('validated_network_passenger_values',len(raw))
        by_key = {}
        for k in wanted:
            obj = _capability_call(lambda: v.Net.Links.ItemByKey(k[1], k[2]))
            if _identity(obj, env) != k:
                raise DiagFastError('DIAGFAST_ITEMBYKEY_IDENTITY_MISMATCH:'+str(k))
            by_key[k] = obj
        prof.notes['identity_backend'] = 'BULK_KEY_JOIN_VALIDATED_ITEMBYKEY'
    except CapabilityUnavailable as failure:
        exc = failure.original
        prof.fallbacks.append({'from': 'BULK_KEY_JOIN_VALIDATED_ITEMBYKEY',
                              'to': 'LEGACY_FULL_LINK_READER',
                              'reason': repr(exc), 'hresult': com.com_error_hresult(exc)})
        # First establish unambiguous required identities. A technical fallback
        # must never hide a missing or duplicate calibration edge.
        checked = _scalar_selected(items,wanted_set,env)
        if wanted_set-set(checked):
            raise DiagFastError('APPROVED physical directed link unavailable:'+str(sorted(wanted_set-set(checked))))
        prof.notes['identity_backend'] = 'LEGACY_FULL_LINK_READER'
        prof.notes['full_link_rows_read'] = len(items)
        return legacy(v,probes)
    missing = wanted_set - set(by_key)
    if missing:
        raise DiagFastError('APPROVED physical directed link unavailable:'+str(sorted(missing)))
    # First physical GetAll object remains the diagnostic sample, even when not
    # a calibrated link. Its full row is read too, preserving old sample failure.
    selected = []
    first_key = None
    if items:
        first_key = _identity(items[0], env)
        selected.append(items[0])
    selected.extend(by_key[k] for k in wanted if k != first_key)
    prof.notes['full_link_rows_read'] = len(selected)
    class SelectedLinks:
        GetAll = tuple(selected)
    restricted = SimpleNamespace(Net=SimpleNamespace(Links=SelectedLinks(), LinkTypes=v.Net.LinkTypes))
    return legacy(restricted, probes)


def configure_namespace(env, kind, backend, prof):
    backend = mode(backend)
    if backend == 'PARITY_AUDIT':
        raise DiagFastError('PARITY_BACKEND_MUST_RUN_TWO_ISOLATED_HELPERS')
    if kind == '12D':
        saved = {}
        original_manifest = env['load_manifest']
        def manifest():
            # main owns the initial SHA verification. No cross-run cache.
            result = original_manifest()
            saved['manifest'] = result
            return result
        env['load_manifest'] = manifest
        original_index = env['read_link_index']
        env['_diagfast_reference_read_link_index'] = original_index
        if backend == 'FAST_EXACT':
            def index(v, probes):
                authority = saved.get('manifest')
                if authority is None:
                    authority = env['load_manifest']()
                return sparse_link_index(v, probes, env, original_index, authority, prof)
            env['read_link_index'] = index
        for fn, stage in [('main','DIAG_12D_TOTAL'),('load_manifest','DIAG_12D_AUTHORITY'),
                          ('verify_live_authority','DIAG_12D_AUTHORITY'),
                          ('read_link_index','DIAG_12D_LINK_INDEX'),('build_detail_rows','DIAG_12D_ROW_BUILD'),
                          ('write_outputs','DIAG_12D_IO'),
                          # V2 telemetry only (both backends): finer live attribution.
                          ('read_countlocations','DIAG_12D_COUNTLOCATIONS'),
                          ('add_pair_and_diag','DIAG_12D_PAIR_DIAG')]:
            _timed(env,fn,prof,stage)
    else:
        cache = {}
        original_read = env['read_matrix_values']
        def read_matrix(mat):
            no = exact_id(mat.AttValue('NO'))
            prof.count('matrix_value_requests')
            if backend == 'FAST_EXACT' and no in cache:
                prof.count('matrix_value_cache_hits')
                return cache[no]
            with prof.span('DIAG_11D_MATRIX_GETVALUES'):
                vals, method = original_read(mat)
            prof.matrix_reads[str(no)] = prof.matrix_reads.get(str(no),0)+1
            prof.matrix_shapes[str(no)] = {'rows':len(vals),
                'row_lengths':sorted(set(len(row) for row in vals)),
                'cells':sum(map(len,vals))}
            prof.count('matrix_getvalues_success')
            if backend == 'FAST_EXACT':
                # Preserve raw Python scalar objects, no dtype/rounding changes.
                frozen = tuple(tuple(row) for row in vals)
                cache[no] = (frozen, method)
                prof.count('matrix_cached_cells', sum(map(len,frozen)))
                return cache[no]
            return vals, method
        env['read_matrix_values'] = read_matrix
        for fn, stage in [('main','DIAG_11D_TOTAL'),('matrix_inventory_row','DIAG_11D_MATRIX_INVENTORY'),
                          ('compute_matrix_distribution','DIAG_11D_DISTRIBUTION'),
                          ('write_csv','DIAG_11D_IO'),('write_json','DIAG_11D_IO'),
                          # V2 telemetry only (both backends): finer live attribution.
                          ('tff_scaffold_status','DIAG_11D_TFF_SCAFFOLD'),
                          ('countlocation_rows','DIAG_11D_COUNTLOCATIONS'),
                          ('find_matrix_by_code','DIAG_11D_MATRIX_LOOKUP'),
                          ('load_class_matrix','DIAG_11D_CLASS_MATRIX'),
                          ('component_weight_rows','DIAG_11D_COMPONENT_WEIGHTS'),
                          ('resolve_authority_dir','DIAG_11D_AUTHORITY_RESOLVE'),
                          ('load_component_curves','DIAG_11D_AUTHORITY_CURVES'),
                          ('load_long_basis','DIAG_11D_AUTHORITY_LONG'),
                          ('curve_stats','DIAG_11D_CURVE_STATS'),
                          ('fit_simplex_basis','DIAG_11D_LONG_FIT')]:
            _timed(env,fn,prof,stage)
        env['_diagfast_matrix_cache'] = cache
    v2_features = {}
    if backend == 'FAST_EXACT':
        import r1_15a2_diagfast_v2 as v2
        v2_features = v2.install(env, kind, prof)
        if kind == '11D' and v2_features.get('numpy_11d'):
            for fn, stage in [('compute_matrix_distribution','DIAG_11D_DISTRIBUTION_V2'),
                              ('matrix_total','DIAG_11D_MATRIX_TOTAL_V2'),
                              ('load_class_matrix','DIAG_11D_CLASS_MATRIX_V2')]:
                _timed(env,fn,prof,stage)
    prof.notes['protected_original_unchanged_on_disk'] = True
    prof.notes['runtime_overlay_applied'] = backend == 'FAST_EXACT'
    prof.notes['numeric_functions_rewritten'] = (
        'NUMPY_SEQUENTIAL_CUMSUM_BITWISE_EXACT_WITH_REFERENCE_FALLBACK'
        if v2_features.get('numpy_11d') and kind == '11D' else False)
    prof.notes['unselected_link_full_volume_validation'] = 'PRESERVED_BULK_VALIDITY_SWEEP_OR_LEGACY_FULL_FALLBACK'
    return env


def run_reference_helper(kind, workspace, visum, backend='LEGACY', policy=None, print_fn=print,
                         profile_enabled=True):
    workspace = Path(workspace); workspace.mkdir(parents=True,exist_ok=True)
    prof = Profile(kind,backend,enabled=profile_enabled)
    prof.notes['workspace_path'] = str(workspace)
    import shutil
    shutil.copy2(ROOT/'helpers'/HELPERS[kind],workspace/HELPERS[kind])
    if kind == '12D':
        # Restore verified package authorities after an outer helper retry clears TEMP.
        import shutil
        for name in ('R1_CSD2022_COUNTLOCATION_AUTHORITY_CURRENT_362_20261022.csv',
                     'R1_CITY_RPDI_COUNTLOCATION_AUTHORITY_CURRENT_126_20261022.csv'):
            if not (workspace/name).exists():
                shutil.copy2(ROOT/'authorities'/name,workspace/name)
    proxy = ReadOnlyProxy(visum,prof,policy)
    with prof.span('DIAG_REFERENCE_LOAD'):
        env = reference_namespace(kind,workspace,proxy,print_fn)
    if kind == '12D':
        # Runtime's short cwd is the helper output authority, not active .ver.
        # Normally the parent path-hotfix already redirects GetPath(2). Make
        # explicit only here; numerical/reference semantics are unchanged.
        env['version_project_dir'] = lambda v: workspace
        real_zip = env['zipfile']
        class TimedZip:
            def __init__(self,*args,**kwargs):
                self.span = prof.span('DIAG_EVIDENCE_ARCHIVE')
                self.span.__enter__()
                try:
                    self.z = real_zip.ZipFile(*args,**kwargs)
                except BaseException:
                    self.span.__exit__(*__import__('sys').exc_info()); raise
            def __enter__(self): return self.z.__enter__()
            def __exit__(self,*args):
                try: return self.z.__exit__(*args)
                finally: self.span.__exit__(*args)
        env['zipfile'] = SimpleNamespace(ZipFile=TimedZip,ZIP_DEFLATED=zipfile.ZIP_DEFLATED)
    configure_namespace(env,kind,backend,prof)
    status = 'PASS'
    try:
        env['_diagfast_reference_entry']()
        if prof.notes.get('terminal_com_busy_error'):
            raise DiagFastError('DIAGFAST_COM_BUSY_EXHAUSTED:'+prof.notes['terminal_com_busy_error'])
    except BaseException as exc:
        status = 'FAILED'
        prof.notes['exception'] = repr(exc)
        raise
    finally:
        env.get('_diagfast_matrix_cache',{}).clear()
        if backend == 'FAST_EXACT':
            import r1_15a2_diagfast_v2 as v2
            v2.release(env)
        prof.notes['cache_released'] = True
        try:
            prof.notes['workspace_bytes'] = sum(p.stat().st_size for p in workspace.rglob('*') if p.is_file())
            (workspace/('DIAGFAST_'+kind+'_PROFILE.json')).write_text(
                json.dumps(prof.report(status),ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as evidence_error:
            # Diagnostic telemetry must not replace the original scientific exception.
            prof.notes['telemetry_io_error'] = repr(evidence_error)
            ctx = CONTEXT.get() or {}
            if status == 'PASS' and ctx.get('backend') == 'PARITY_AUDIT':
                raise DiagFastError('DIAGFAST_PARITY_TELEMETRY_WRITE_FAILED:'+repr(evidence_error)) from evidence_error
            print_fn('DIAGFAST_TELEMETRY_IO_WARNING',repr(evidence_error))
    return prof.report(status)


def execute_helper(kind, namespace):
    ctx = CONTEXT.get() or {'backend':'LEGACY','policy':{}}
    backend = mode(ctx['backend'])
    workspace = Path(namespace['__file__']).parent
    visum = namespace.get('Visum')
    if visum is None:
        raise DiagFastError('DIAGFAST_REQUIRES_INJECTED_VISUM')
    if backend == 'PARITY_AUDIT':
        from r1_15a2_diagfast_parity_v1 import parity_helper
        return parity_helper(kind, workspace, visum,ctx.get('policy'),namespace.get('print',print))
    return run_reference_helper(kind,workspace,visum,backend,ctx.get('policy'),namespace.get('print',print))
